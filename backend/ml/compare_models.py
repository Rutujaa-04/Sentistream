"""Compare the full-precision baseline and INT8 challenger on one held-out set."""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone

import numpy as np
import onnxruntime as ort
from phrasebank_data import load_phrasebank_splits
from sklearn.metrics import accuracy_score, f1_score
from tokenizers import Tokenizer

WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODELS_DIR = os.path.join(WORKSPACE, "models")
def configured_artifact_path(variable, default):
    value = os.environ.get(variable, default)
    return value if os.path.isabs(value) else os.path.join(WORKSPACE, value)


MODEL_PATHS = {
    "v1": configured_artifact_path("MODEL_V1_PATH", "models/finbert-fp32.onnx"),
    "v2": configured_artifact_path("MODEL_V2_PATH", "models/finbert-int8.onnx"),
}
LABEL_NAMES = ["positive", "negative", "neutral"]
MIN_SAMPLES = int(os.environ.get("MODEL_EVAL_MIN_SAMPLES", "100"))
MAX_WEIGHTED_F1_DROP = 0.01
MAX_MACRO_F1_DROP = 0.02
MAX_ECE_INCREASE = 0.03


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def softmax(logits):
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    values = np.exp(shifted)
    return values / np.sum(values, axis=1, keepdims=True)


def expected_calibration_error(probabilities, labels, bins=10):
    confidence = probabilities.max(axis=1)
    predictions = probabilities.argmax(axis=1)
    correct = predictions == labels
    edges = np.linspace(0.0, 1.0, bins + 1)
    ece = 0.0
    for index in range(bins):
        in_bin = (confidence > edges[index]) & (confidence <= edges[index + 1])
        if np.any(in_bin):
            ece += in_bin.mean() * abs(correct[in_bin].mean() - confidence[in_bin].mean())
    return float(ece)


def evaluate_model(model_version, model_path, tokenizer, examples):
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(model_path, options, providers=["CPUExecutionProvider"])
    input_names = {item.name for item in session.get_inputs()}
    probabilities = []
    labels = []

    for example in examples:
        encoded = tokenizer.encode(example["sentence"])
        inputs = {
            "input_ids": np.asarray([encoded.ids], dtype=np.int64),
            "attention_mask": np.asarray([encoded.attention_mask], dtype=np.int64),
            "token_type_ids": np.asarray([encoded.type_ids], dtype=np.int64),
        }
        outputs = session.run(None, {name: value for name, value in inputs.items() if name in input_names})
        probabilities.append(softmax(np.asarray(outputs[0], dtype=np.float64))[0])
        labels.append(int(example["label"]))

    probabilities = np.asarray(probabilities)
    labels = np.asarray(labels, dtype=np.int64)
    predictions = probabilities.argmax(axis=1)
    class_support = {
        name: int(np.sum(labels == index)) for index, name in enumerate(LABEL_NAMES)
    }
    return {
        "model_version": model_version,
        "artifact": os.path.relpath(model_path, WORKSPACE),
        "artifact_sha256": sha256_file(model_path),
        "accuracy": round(float(accuracy_score(labels, predictions)), 6),
        "weighted_f1": round(float(f1_score(labels, predictions, average="weighted", zero_division=0)), 6),
        "macro_f1": round(float(f1_score(labels, predictions, average="macro", zero_division=0)), 6),
        "expected_calibration_error": round(expected_calibration_error(probabilities, labels), 6),
        "multiclass_brier_score": round(
            float(np.mean(np.sum((probabilities - np.eye(len(LABEL_NAMES))[labels]) ** 2, axis=1))), 6
        ),
        "class_support": class_support,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when the challenger fails the quality acceptance gates",
    )
    args = parser.parse_args()
    missing = [path for path in MODEL_PATHS.values() if not os.path.isfile(path)]
    tokenizer_path = os.path.join(MODELS_DIR, "finbert-onnx", "tokenizer.json")
    if missing or not os.path.isfile(tokenizer_path):
        raise FileNotFoundError(
            "Export both distinct ONNX artifacts and tokenizer first. Missing: "
            + ", ".join(missing + ([] if os.path.isfile(tokenizer_path) else [tokenizer_path]))
        )

    hashes = {version: sha256_file(path) for version, path in MODEL_PATHS.items()}
    if hashes["v1"] == hashes["v2"]:
        raise ValueError("Model comparison requires distinct v1 and v2 artifact hashes.")

    splits, dataset_metadata = load_phrasebank_splits()
    examples = splits["test"]
    tokenizer = Tokenizer.from_file(tokenizer_path)
    tokenizer.enable_truncation(max_length=128)
    tokenizer.enable_padding(length=128)

    models = {
        version: evaluate_model(version, path, tokenizer, examples)
        for version, path in MODEL_PATHS.items()
    }
    baseline = models["v1"]
    challenger = models["v2"]
    checks = {
        "distinct_artifacts": hashes["v1"] != hashes["v2"],
        "minimum_sample_count": len(examples) >= MIN_SAMPLES,
        "weighted_f1_within_tolerance": challenger["weighted_f1"] >= baseline["weighted_f1"] - MAX_WEIGHTED_F1_DROP,
        "macro_f1_within_tolerance": challenger["macro_f1"] >= baseline["macro_f1"] - MAX_MACRO_F1_DROP,
        "calibration_within_tolerance": (
            challenger["expected_calibration_error"]
            <= baseline["expected_calibration_error"] + MAX_ECE_INCREASE
        ),
    }
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if all(checks.values()) else "rejected",
        "experiment_eligible": all(checks.values()),
        "sample_count": len(examples),
        "dataset": dataset_metadata,
        "artifact_hashes": hashes,
        "models": models,
        "acceptance_criteria": {
            "minimum_samples": MIN_SAMPLES,
            "maximum_weighted_f1_drop": MAX_WEIGHTED_F1_DROP,
            "maximum_macro_f1_drop": MAX_MACRO_F1_DROP,
            "maximum_ece_increase": MAX_ECE_INCREASE,
        },
        "checks": checks,
        "note": "Financial PhraseBank is a CC BY-NC-SA dataset; results are for non-commercial evaluation.",
    }
    report_path = os.path.join(MODELS_DIR, "model-evaluation.json")
    with open(report_path, "w", encoding="utf-8") as report_file:
        json.dump(report, report_file, indent=2)
    print(json.dumps(report, indent=2))
    print(f"Saved hash-bound evaluation report to {report_path}")

    if args.strict and not report["experiment_eligible"]:
        raise SystemExit("Challenger did not meet all evaluation gates; traffic split remains disabled.")


if __name__ == "__main__":
    main()
