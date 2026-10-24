import json
import os

import matplotlib.pyplot as plt
import numpy as np
from phrasebank_data import load_phrasebank_splits
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)
from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer


def main():
    print("Step 1: Loading the pinned labeled test split...")
    splits, dataset_metadata = load_phrasebank_splits()
    test_dataset = splits["test"]
    
    print(f"Test split samples to evaluate: {len(test_dataset)}")
    print(f"Dataset archive SHA-256: {dataset_metadata['archive_sha256']}")

    # 3. Load fine-tuned model and tokenizer
    best_model_path = "models/checkpoint-best"
    if not os.path.exists(best_model_path):
        print(f"Error: Fine-tuned model checkpoint not found at {best_model_path}. Please run train.py first.")
        return

    print(f"Step 2: Loading fine-tuned model and tokenizer from {best_model_path}...")
    tokenizer = AutoTokenizer.from_pretrained(best_model_path)
    model = AutoModelForSequenceClassification.from_pretrained(best_model_path)

    # 4. Tokenize test dataset
    def tokenize_fn(examples):
        return tokenizer(examples["sentence"], padding="max_length", truncation=True, max_length=128)
        
    tokenized_test = test_dataset.map(tokenize_fn, batched=True)

    # 5. Run prediction using HuggingFace Trainer
    print("Step 3: Running inference on test split...")
    trainer = Trainer(model=model)
    predictions_output = trainer.predict(tokenized_test)
    
    logits = predictions_output.predictions
    true_labels = predictions_output.label_ids
    pred_labels = np.argmax(logits, axis=-1)

    # 6. Compute metrics
    acc = accuracy_score(true_labels, pred_labels)
    weighted_p, weighted_r, weighted_f1, _ = precision_recall_fscore_support(
        true_labels, pred_labels, average="weighted"
    )
    
    # Per-class metrics
    # finbert: 0=positive, 1=negative, 2=neutral
    class_names = ["positive", "negative", "neutral"]
    precision, recall, f1, support = precision_recall_fscore_support(
        true_labels, pred_labels, labels=[0, 1, 2]
    )

    per_class_metrics = {}
    for i, name in enumerate(class_names):
        per_class_metrics[name] = {
            "precision": float(precision[i]),
            "recall": float(recall[i]),
            "f1": float(f1[i]),
            "support": int(support[i])
        }

    overall_metrics = {
        "accuracy": float(acc),
        "weighted_precision": float(weighted_p),
        "weighted_recall": float(weighted_r),
        "weighted_f1": float(weighted_f1),
        "per_class": per_class_metrics
    }

    print("\n--- Evaluation Results ---")
    print(f"Overall Accuracy: {acc:.4f}")
    print(f"Overall Weighted F1: {weighted_f1:.4f}")
    print("\nPer-Class Breakdown:")
    for name, metrics in per_class_metrics.items():
        print(f"Class: {name.upper():<10} | F1: {metrics['f1']:.4f} | Precision: {metrics['precision']:.4f} | Recall: {metrics['recall']:.4f} | Support: {metrics['support']}")
    print("--------------------------")

    # 7. Write benchmarks to benchmark.json
    results_dir = "backend/ml/results"
    os.makedirs(results_dir, exist_ok=True)
    benchmark_path = os.path.join(results_dir, "benchmark.json")
    with open(benchmark_path, "w") as f:
        json.dump(overall_metrics, f, indent=4)
    print(f"Saved benchmark metrics to {benchmark_path}")

    # 8. Generate and save Confusion Matrix
    print("\nStep 4: Generating and saving confusion matrix...")
    cm = confusion_matrix(true_labels, pred_labels, labels=[0, 1, 2])
    
    plt.figure(figsize=(8, 6))
    plt.imshow(cm, interpolation='nearest', cmap=plt.cm.Blues)
    plt.title('SentiStream FinBERT Confusion Matrix')
    plt.colorbar()
    
    tick_marks = np.arange(len(class_names))
    plt.xticks(tick_marks, [name.capitalize() for name in class_names])
    plt.yticks(tick_marks, [name.capitalize() for name in class_names])
    
    # Label each cell
    thresh = cm.max() / 2.
    for i, j in np.ndindex(cm.shape):
        plt.text(j, i, format(cm[i, j], 'd'),
                 horizontalalignment="center",
                 color="white" if cm[i, j] > thresh else "black")
                 
    plt.ylabel('True Sentiment Label')
    plt.xlabel('Predicted Sentiment Label')
    plt.tight_layout()
    
    cm_path = os.path.join(results_dir, "confusion_matrix.png")
    plt.savefig(cm_path, dpi=300)
    plt.close()
    print(f"Saved confusion matrix chart to {cm_path}")

if __name__ == "__main__":
    main()
