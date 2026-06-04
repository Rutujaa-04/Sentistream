import json
import os
import shutil
import time

import numpy as np
import onnxruntime as ort
from optimum.onnxruntime import ORTModelForSequenceClassification, ORTQuantizer
from optimum.onnxruntime.configuration import AutoQuantizationConfig
from transformers import AutoTokenizer


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
    # Ensure models and results output directories exist
    os.makedirs("models", exist_ok=True)
    os.makedirs("backend/ml/results", exist_ok=True)

    best_model_path = "models/checkpoint-best"
    if not os.path.exists(best_model_path):
        print(f"Fine-tuned model checkpoint not found at {best_model_path}.")
        print("Falling back to default 'ProsusAI/finbert' model from HuggingFace for export...")
        model_load_path = "ProsusAI/finbert"
    else:
        print(f"Loading best fine-tuned model checkpoint from {best_model_path}...")
        model_load_path = best_model_path

    # 1. Export PyTorch model to standard FP32 ONNX using HuggingFace Optimum
    fp32_onnx_dir = "models/finbert-onnx"
    print(f"\nStep 1: Exporting {model_load_path} to ONNX format at {fp32_onnx_dir}...")
    
    # optimum will handle dynamic inputs, shapes, and vocabulary mapping automatically
    model = ORTModelForSequenceClassification.from_pretrained(model_load_path, export=True)
    tokenizer = AutoTokenizer.from_pretrained(model_load_path)
    
    model.save_pretrained(fp32_onnx_dir)
    tokenizer.save_pretrained(fp32_onnx_dir)
    print("FP32 ONNX export completed successfully.")

    # Copy raw model file to models/finbert-fp32.onnx to maintain pipeline compatibility
    fp32_onnx_path = "models/finbert-fp32.onnx"
    shutil.copyfile(os.path.join(fp32_onnx_dir, "model.onnx"), fp32_onnx_path)

    # 2. Dynamic INT8 Quantization using Optimum's ORTQuantizer
    int8_onnx_dir = "models/finbert-quantized"
    print(f"\nStep 2: Running dynamic INT8 quantization to {int8_onnx_dir}...")
    
    quantizer = ORTQuantizer.from_pretrained(fp32_onnx_dir)
    # Configure dynamic quantization targeting CPUs (avx2 instruction set configurations)
    qconfig = AutoQuantizationConfig.avx2(is_static=False, per_channel=False)
    
    quantizer.quantize(save_dir=int8_onnx_dir, quantization_config=qconfig)
    print("INT8 Quantization completed successfully.")

    # Copy quantized model file to models/finbert-int8.onnx to maintain pipeline compatibility
    int8_onnx_path = "models/finbert-int8.onnx"
    shutil.copyfile(os.path.join(int8_onnx_dir, "model_quantized.onnx"), int8_onnx_path)

    # 3. Size Comparison
    fp32_size_mb = os.path.getsize(fp32_onnx_path) / (1024 * 1024)
    int8_size_mb = os.path.getsize(int8_onnx_path) / (1024 * 1024)
    print("\n--- Model Size Comparison ---")
    print(f"FP32 Model Size: {fp32_size_mb:.2f} MB")
    print(f"INT8 Model Size: {int8_size_mb:.2f} MB (Reduced by {((fp32_size_mb - int8_size_mb) / fp32_size_mb) * 100:.1f}%)")
    print("-----------------------------")

    # 4. Latency Benchmarking on CPU
    print("\nStep 3: Benchmarking FP32 vs INT8 latency on CPU...")
    dummy_text = "Apple stock surges 5% as quarterly sales beat all Wall Street expectations."
    
    print("Benchmarking FP32 ONNX Session (200 runs)...")
    fp32_metrics = benchmark_onnx(fp32_onnx_path, tokenizer, dummy_text)
    
    print("Benchmarking INT8 ONNX Session (200 runs)...")
    int8_metrics = benchmark_onnx(int8_onnx_path, tokenizer, dummy_text)

    speedup = fp32_metrics["mean_ms"] / int8_metrics["mean_ms"]
    print("\n--- CPU Latency Benchmark Results ---")
    print(f"FP32 Mean Latency: {fp32_metrics['mean_ms']:.2f} ms (p99: {fp32_metrics['p99_ms']:.2f} ms)")
    print(f"INT8 Mean Latency: {int8_metrics['mean_ms']:.2f} ms (p99: {int8_metrics['p99_ms']:.2f} ms)")
    print(f"Dynamic INT8 speedup: {speedup:.2f}x faster CPU execution")
    print("-------------------------------------")

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
