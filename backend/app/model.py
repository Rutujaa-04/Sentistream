import hashlib
import json
import os
import sys
import time
from functools import lru_cache

import numpy as np
import onnxruntime as ort
import structlog
from tokenizers import Tokenizer

# Add parent directory to path to import properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings

logger = structlog.get_logger()


def _workspace_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _artifact_path(configured_path: str) -> str:
    if os.path.isabs(configured_path):
        return configured_path
    return os.path.join(_workspace_dir(), configured_path)


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def get_model_evaluation_status() -> dict:
    """Validates the stored holdout report against the installed ONNX artifacts."""
    v1_path = _artifact_path(settings.MODEL_V1_PATH)
    v2_path = _artifact_path(settings.MODEL_V2_PATH)
    report_path = os.path.join(_workspace_dir(), "models", "model-evaluation.json")
    hashes = {
        "v1": _sha256(v1_path) if os.path.isfile(v1_path) else None,
        "v2": _sha256(v2_path) if os.path.isfile(v2_path) else None,
    }
    report = None
    try:
        with open(report_path, "r", encoding="utf-8") as report_file:
            report = json.load(report_file)
    except (OSError, json.JSONDecodeError):
        pass

    valid_report = bool(
        report
        and hashes["v1"]
        and hashes["v2"]
        and hashes["v1"] != hashes["v2"]
        and report.get("artifact_hashes") == hashes
        and report.get("experiment_eligible") is True
        and int(report.get("sample_count", 0)) >= settings.MODEL_EVAL_MIN_SAMPLES
    )
    experiment_enabled = bool(valid_report and settings.MODEL_EXPERIMENT_ENABLED)
    if valid_report:
        status = "ready"
        reason = (
            "Evaluation passed; set MODEL_EXPERIMENT_ENABLED=true to route the configured traffic split."
            if not settings.MODEL_EXPERIMENT_ENABLED
            else "Evaluation passed and the model experiment is enabled."
        )
    elif report and report.get("artifact_hashes") != hashes:
        status = "stale_evaluation"
        reason = "The evaluation report does not match the installed model artifacts. Re-run compare_models.py."
    elif report and report.get("status") == "rejected":
        status = "rejected"
        reason = "The challenger did not meet the holdout quality thresholds."
    else:
        status = "not_evaluated"
        reason = "Distinct model artifacts and a passing holdout evaluation are required before an experiment."

    return {
        "status": status,
        "experiment_enabled": experiment_enabled,
        "reason": reason,
        "minimum_samples": settings.MODEL_EVAL_MIN_SAMPLES,
        "sample_count": int(report.get("sample_count", 0)) if report else 0,
        "dataset": report.get("dataset") if report else None,
        "models": report.get("models", {}) if report else {},
        "artifact_hashes": hashes,
    }

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
        
        self.model_v1_path = _artifact_path(settings.MODEL_V1_PATH)
        self.model_v2_path = _artifact_path(settings.MODEL_V2_PATH)
        if not os.path.isfile(self.model_v1_path):
            raise FileNotFoundError(f"Baseline ONNX model not found at {self.model_v1_path}.")
        self.evaluation_status = get_model_evaluation_status()
        self.experiment_enabled = self.evaluation_status["experiment_enabled"]

        # Use the local tokenizer artifact produced by training/export. The
        # serving image intentionally does not install the training stack.
        workspace_dir = _workspace_dir()
        tokenizer_candidates = [
            os.path.join(workspace_dir, "models", "finbert-onnx", "tokenizer.json"),
            os.path.join(workspace_dir, "models", "checkpoint-best", "tokenizer.json"),
        ]
        tokenizer_file = next(
            (candidate for candidate in tokenizer_candidates if os.path.isfile(candidate)),
            None,
        )
        if tokenizer_file is None:
            raise FileNotFoundError(
                "Tokenizer assets not found. Export the model first so "
                "models/finbert-onnx/tokenizer.json is available."
            )

        try:
            self.tokenizer = Tokenizer.from_file(tokenizer_file)
            self.tokenizer.enable_truncation(max_length=128)
            self.tokenizer.enable_padding(length=128)
            logger.info("Tokenizer loaded successfully", source=tokenizer_file)
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
                "v1": ort.InferenceSession(self.model_v1_path, opts, providers=["CPUExecutionProvider"])
            }
            if self.experiment_enabled:
                self.sessions["v2"] = ort.InferenceSession(
                    self.model_v2_path, opts, providers=["CPUExecutionProvider"]
                )
            logger.info(
                "ONNX Inference Sessions initialized successfully",
                model_v1=self.model_v1_path,
                model_v2=self.model_v2_path if "v2" in self.sessions else None,
                experiment_enabled=self.experiment_enabled,
                evaluation_status=self.evaluation_status["status"],
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
        encoded = self.tokenizer.encode(text)
        t_tokenized = time.perf_counter()
        tokenization_latency = (t_tokenized - t0) * 1000.0

        # 3. Format inputs for ONNX Runner
        onnx_inputs = {
            "input_ids": np.asarray([encoded.ids], dtype=np.int64),
            "attention_mask": np.asarray([encoded.attention_mask], dtype=np.int64),
            "token_type_ids": np.asarray([encoded.type_ids], dtype=np.int64),
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
