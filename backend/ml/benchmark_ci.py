import os
import sys
import time
import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

def main():
    print("Running CI Model Benchmark (1000 inferences)...")
    
    # Resolve paths relative to root directory
    workspace_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    model_path = os.path.join(workspace_dir, "models", "finbert-int8.onnx")
    
    if not os.path.exists(model_path):
        print(f"ERROR: Quantized ONNX model not found at {model_path}!")
        sys.exit(1)
        
    tokenizer_path = os.path.join(workspace_dir, "models", "checkpoint-best")
    if not os.path.exists(tokenizer_path):
        print("Fallback to ProsusAI/finbert tokenizer baseline...")
        tokenizer_path = "ProsusAI/finbert"
        
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
    
    # Configure single-threaded inference for CPU benchmark stability
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    session = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
    
    dummy_text = "Apple beats earnings expectations by 10%, stock up 4% in premarket trading."
    inputs = tokenizer(dummy_text, return_tensors="np", padding=True, truncation=True, max_length=128)
    
    onnx_inputs = {
        "input_ids": inputs["input_ids"].astype(np.int64),
        "attention_mask": inputs["attention_mask"].astype(np.int64),
        "token_type_ids": inputs["token_type_ids"].astype(np.int64),
    }
    
    # Warmup runs to allow execution engine caching optimizations to settle
    for _ in range(15):
        session.run(None, onnx_inputs)
        
    # Execute benchmark iterations
    latencies = []
    for _ in range(1000):
        t0 = time.perf_counter()
        session.run(None, onnx_inputs)
        latencies.append((time.perf_counter() - t0) * 1000.0) # Convert to ms
        
    p50 = np.percentile(latencies, 50)
    p95 = np.percentile(latencies, 95)
    p99 = np.percentile(latencies, 99)
    mean = np.mean(latencies)
    
    print("\n--- CI CPU Benchmark Results ---")
    print(f"Inferences executed: {len(latencies)}")
    print(f"Mean Latency:        {mean:.2f} ms")
    print(f"p50 Latency (median): {p50:.2f} ms")
    print(f"p95 Latency:         {p95:.2f} ms")
    print(f"p99 Latency (slowest): {p99:.2f} ms")
    print("---------------------------------")
    
    # Setting threshold to 150ms for slow GitHub runner virtual machines
    CI_THRESHOLD_MS = 150.0
    if p99 > CI_THRESHOLD_MS:
        print(f"ERROR: p99 latency ({p99:.2f} ms) exceeds CI regression threshold ({CI_THRESHOLD_MS} ms)!")
        sys.exit(1)
        
    print(f"CI benchmark checks passed successfully (p99 latency < {CI_THRESHOLD_MS} ms).")

if __name__ == "__main__":
    main()
