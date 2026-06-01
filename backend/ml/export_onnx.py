import os
import json
import time
import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer
import onnxruntime as ort
from onnxruntime.quantization import quantize_dynamic, QuantType

def benchmark_onnx(model_path, tokenizer, dummy_text, num_runs=200):
    # Set thread count for reliable local CPU benchmarking
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    
    session = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
    
    # Tokenize input
    inputs = tokenizer(dummy_text, return_tensors="np", padding=True, truncation=True, max_length=128)
    
    # Prepare input dictionary mapping names to numpy arrays
    onnx_inputs = {
        "input_ids": inputs["input_ids"].astype(np.int64),
        "attention_mask": inputs["attention_mask"].astype(np.int64),
        "token_type_ids": inputs["token_type_ids"].astype(np.int64),
    }
    
    # Warmup
    for _ in range(10):
        session.run(None, onnx_inputs)
        
    # Benchmark runs
    latencies = []
    for _ in range(num_runs):
        t0 = time.perf_counter()
        session.run(None, onnx_inputs)
        latencies.append((time.perf_counter() - t0) * 1000.0) # Convert to ms
        
    p50 = np.percentile(latencies, 50)
    p95 = np.percentile(latencies, 95)
    p99 = np.percentile(latencies, 99)
    mean = np.mean(latencies)
    
    return {
        "mean_ms": float(mean),
        "p50_ms": float(p50),
        "p95_ms": float(p95),
        "p99_ms": float(p99)
    }

def main():
    best_model_path = "models/checkpoint-best"
    if not os.path.exists(best_model_path):
        print(f"Error: Fine-tuned model checkpoint not found at {best_model_path}. Please run train.py first.")
        return

    print("Step 1: Loading best fine-tuned PyTorch model checkpoint...")
    model = AutoModelForSequenceClassification.from_pretrained(best_model_path)
    tokenizer = AutoTokenizer.from_pretrained(best_model_path)
    model.eval()

    # 1. Export PyTorch model to standard FP32 ONNX
    fp32_onnx_path = "models/finbert-fp32.onnx"
    print(f"\nStep 2: Exporting PyTorch model to FP32 ONNX format at {fp32_onnx_path}...")
    
    dummy_text = "Apple stock surges 5% as quarterly sales beat all Wall Street expectations."
    inputs = tokenizer(dummy_text, return_tensors="pt", padding=True, truncation=True, max_length=128)
    
    input_ids = inputs["input_ids"]
    attention_mask = inputs["attention_mask"]
    token_type_ids = inputs["token_type_ids"]

    # Native torch ONNX export
    torch.onnx.export(
        model,
        (input_ids, attention_mask, token_type_ids),
        fp32_onnx_path,
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch_size", 1: "sequence_length"},
            "attention_mask": {0: "batch_size", 1: "sequence_length"},
            "token_type_ids": {0: "batch_size", 1: "sequence_length"},
            "logits": {0: "batch_size"}
        },
        opset_version=14
    )
    print("FP32 ONNX export completed successfully.")

    # 2. Dynamic INT8 Quantization
    int8_onnx_path = "models/finbert-int8.onnx"
    print(f"\nStep 3: Running dynamic INT8 quantization to {int8_onnx_path}...")
    quantize_dynamic(
        model_input=fp32_onnx_path,
        model_output=int8_onnx_path,
        weight_type=QuantType.QInt8
    )
    print("INT8 Quantization completed successfully.")

    # 3. Size Comparison
    fp32_size_mb = os.path.getsize(fp32_onnx_path) / (1024 * 1024)
    int8_size_mb = os.path.getsize(int8_onnx_path) / (1024 * 1024)
    print(f"\n--- Model Size Comparison ---")
    print(f"FP32 Model Size: {fp32_size_mb:.2f} MB")
    print(f"INT8 Model Size: {int8_size_mb:.2f} MB (Reduced by {((fp32_size_mb - int8_size_mb) / fp32_size_mb) * 100:.1f}%)")
    print(f"-----------------------------")

    # 4. Latency Benchmarking on CPU
    print("\nStep 4: Benchmarking FP32 vs INT8 latency on CPU...")
    print("Benchmarking FP32 ONNX Session (200 runs)...")
    fp32_metrics = benchmark_onnx(fp32_onnx_path, tokenizer, dummy_text)
    
    print("Benchmarking INT8 ONNX Session (200 runs)...")
    int8_metrics = benchmark_onnx(int8_onnx_path, tokenizer, dummy_text)

    speedup = fp32_metrics["mean_ms"] / int8_metrics["mean_ms"]
    print(f"\n--- CPU Latency Benchmark Results ---")
    print(f"FP32 Mean Latency: {fp32_metrics['mean_ms']:.2f} ms (p99: {fp32_metrics['p99_ms']:.2f} ms)")
    print(f"INT8 Mean Latency: {int8_metrics['mean_ms']:.2f} ms (p99: {int8_metrics['p99_ms']:.2f} ms)")
    print(f"Dynamic INT8 speedup: {speedup:.2fx} faster CPU execution")
    print(f"-------------------------------------")

    # Save quantization benchmarks
    results_dir = "backend/ml/results"
    benchmark_file = os.path.join(results_dir, "quantization_benchmark.json")
    benchmark_data = {
        "model_sizes": {
            "fp32_mb": fp32_size_mb,
            "int8_mb": int8_size_mb,
            "reduction_pct": ((fp32_size_mb - int8_size_mb) / fp32_size_mb) * 100
        },
        "latencies": {
            "fp32": fp32_metrics,
            "int8": int8_metrics,
            "speedup_factor": speedup
        }
    }
    with open(benchmark_file, "w") as f:
        json.dump(benchmark_data, f, indent=4)
    print(f"Saved quantization benchmarks to {benchmark_file}")

if __name__ == "__main__":
    main()
