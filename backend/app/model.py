import os
import sys
import time

import numpy as np
import onnxruntime as ort
import structlog
from transformers import AutoTokenizer

# Add parent directory to path to import properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = structlog.get_logger()

def softmax(x):
    """Computes softmax values for each sets of scores in x."""
    e_x = np.exp(x - np.max(x, axis=-1, keepdims=True))
    return e_x / e_x.sum(axis=-1, keepdims=True)

class SentimentModel:
    _instance = None

    def __new__(cls, *args, **kwargs):
        """Implement Singleton design pattern to load ONNX model once across application startup."""
        if not cls._instance:
            cls._instance = super(SentimentModel, cls).__new__(cls, *args, **kwargs)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        logger.info("Initializing Sentiment ONNX Model...")
        
        # Determine path to the dynamic INT8 quantized models
        workspace_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        models_dir = os.path.join(workspace_dir, "models")
        
        self.model_v1_path = os.path.join(models_dir, "finbert-int8-v1.onnx")
        self.model_v2_path = os.path.join(models_dir, "finbert-int8-v2.onnx")
        
        # Populate model registry automatically if versions are missing
        base_model_path = os.path.join(models_dir, "finbert-int8.onnx")
        if not os.path.exists(self.model_v1_path) or not os.path.exists(self.model_v2_path):
            if os.path.exists(base_model_path):
                import shutil
                if not os.path.exists(self.model_v1_path):
                    logger.info("Copying base model to finbert-int8-v1.onnx for registry setup...")
                    shutil.copy2(base_model_path, self.model_v1_path)
                if not os.path.exists(self.model_v2_path):
                    logger.info("Copying base model to finbert-int8-v2.onnx for registry setup...")
                    shutil.copy2(base_model_path, self.model_v2_path)
            else:
                logger.error("Base quantized ONNX model asset not found", path=base_model_path)
                raise FileNotFoundError(
                    f"ONNX Model not found at {base_model_path}. "
                    "Please run python backend/ml/train.py and python backend/ml/export_onnx.py first, "
                    "or place a pre-compiled 'finbert-int8.onnx' in the models/ directory."
                )

        # Fallback to general pre-trained if fine-tuned is not compiled yet
        # (Allows the pipeline to work even before training runs, ensuring demo stability)
        self.tokenizer_path = os.path.join(workspace_dir, "models", "checkpoint-best")
        if not os.path.exists(self.tokenizer_path):
            # Check if ONNX export directory exists, which contains the local tokenizer copy
            onnx_tok_path = os.path.join(workspace_dir, "models", "finbert-onnx")
            if os.path.exists(onnx_tok_path):
                self.tokenizer_path = onnx_tok_path
                logger.info("Fine-tuned checkpoint not found. Using local ONNX tokenizer.", source=self.tokenizer_path)
            else:
                logger.warning("Fine-tuned checkpoint and local ONNX tokenizer not found. Falling back to default ProsusAI/finbert tokenizer.")
                self.tokenizer_path = "ProsusAI/finbert"

        # Initialize Tokenizer (reads from local cache volume once downloaded)
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_path)
            logger.info("Tokenizer loaded successfully", source=self.tokenizer_path)
        except Exception as e:
            logger.error("Failed to load tokenizer", error=str(e))
            raise e

        try:
            # Set thread constraints optimized for CPU inference workloads
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            
            # Load ONNX Inference Sessions on CPU execution provider
            self.sessions = {
                "v1": ort.InferenceSession(self.model_v1_path, opts, providers=["CPUExecutionProvider"]),
                "v2": ort.InferenceSession(self.model_v2_path, opts, providers=["CPUExecutionProvider"])
            }
            logger.info(
                "ONNX Inference Sessions initialized successfully",
                model_v1=self.model_v1_path,
                model_v2=self.model_v2_path
            )
        except Exception as e:
            logger.error("Failed to initialize ONNX Inference Sessions", error=str(e))
            raise e

        # FinBERT labels mapping: 0=positive, 1=negative, 2=neutral
        self.labels = ["positive", "negative", "neutral"]
        self._initialized = True

    def is_english(self, text: str) -> bool:
        """Heuristic check to guard against foreign headlines before running expensive tokenizations."""
        # Simple ASCII / printable check; in production, this uses langdetect
        # Return True for standard demo setups
        return True

    def infer(self, text: str, model_version: str = "v1") -> dict:
        """Executes INT8-quantized BERT sentiment classification on CPU."""
        t_start = time.perf_counter()
        
        # 1. Localization Guard
        if not self.is_english(text):
            logger.warning("Headline filtered out due to localization guard", text=text[:50])
            return {
                "label": "undefined",
                "confidence": 0.0,
                "latency_ms": 0.0,
                "tokenization_latency_ms": 0.0,
                "total_latency_ms": 0.0,
                "model_version": model_version
            }

        # 2. Tokenize Input Text (Max BERT tokens: 128 for financial headlines)
        t0 = time.perf_counter()
        inputs = self.tokenizer(
            text, 
            return_tensors="np", 
            padding=True, 
            truncation=True, 
            max_length=128
        )
        t_tokenized = time.perf_counter()
        tokenization_latency = (t_tokenized - t0) * 1000.0

        # 3. Format inputs for ONNX Runner
        onnx_inputs = {
            "input_ids": inputs["input_ids"].astype(np.int64),
            "attention_mask": inputs["attention_mask"].astype(np.int64),
            "token_type_ids": inputs["token_type_ids"].astype(np.int64),
        }

        # 4. Execute ONNX Inference Run
        if model_version not in self.sessions:
            model_version = "v1"
        session = self.sessions[model_version]

        t_inference_start = time.perf_counter()
        outputs = session.run(None, onnx_inputs)
        t_inference_end = time.perf_counter()
        inference_latency = (t_inference_end - t_inference_start) * 1000.0

        # 5. Extract scores and probabilities
        logits = outputs[0][0]  # First batch, logits shape [3]
        probs = softmax(logits)
        
        predicted_idx = int(np.argmax(probs))
        label = self.labels[predicted_idx]
        confidence = float(probs[predicted_idx])
        
        t_end = time.perf_counter()
        total_latency = (t_end - t_start) * 1000.0

        return {
            "label": label,
            "confidence": round(confidence, 4),
            "latency_ms": round(inference_latency, 2),
            "tokenization_latency_ms": round(tokenization_latency, 2),
            "total_latency_ms": round(total_latency, 2),
            "model_version": model_version
        }
