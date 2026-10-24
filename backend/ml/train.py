import os
from collections import Counter

import numpy as np
import torch
import torch.nn as nn
from phrasebank_data import load_phrasebank_splits
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)

# Ensure models directory exists
os.makedirs("models", exist_ok=True)
os.makedirs("backend/ml/results", exist_ok=True)

# 1. Custom Trainer to handle class-weighted loss
class WeightedLossTrainer(Trainer):
    def __init__(self, class_weights, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Move weights to the appropriate device (CPU, MPS, CUDA)
        self.class_weights = torch.tensor(class_weights, dtype=torch.float).to(self.args.device)
        print(f"Trainer initialized with class weights: {class_weights} on device: {self.args.device}")
        
    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.get("labels")
        outputs = model(**inputs)
        logits = outputs.get("logits")
        # Initialize CrossEntropyLoss with weights
        loss_fct = nn.CrossEntropyLoss(weight=self.class_weights)
        loss = loss_fct(logits.view(-1, self.model.config.num_labels), labels.view(-1))
        return (loss, outputs) if return_outputs else loss

# 2. Compute metrics function for evaluation
def compute_metrics(eval_pred):
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)
    precision, recall, f1, _ = precision_recall_fscore_support(labels, predictions, average="weighted")
    acc = accuracy_score(labels, predictions)
    return {
        "accuracy": acc,
        "f1": f1,
        "precision": precision,
        "recall": recall
    }

def main():
    print("Step 1: Loading pinned Financial PhraseBank and deterministic splits...")
    splits, dataset_metadata = load_phrasebank_splits()
    train_dataset = splits["train"]
    val_dataset = splits["validation"]
    test_dataset = splits["test"]
    print(f"Loaded {dataset_metadata['sample_count']} labeled samples.")
    print(f"Dataset archive SHA-256: {dataset_metadata['archive_sha256']}")

    print("\nStep 2: Using fixed FinBERT label order (positive=0, negative=1, neutral=2)...")
    print("\nStep 3: Reusing the shared stratified 80/10/10 split...")
    
    print(f"Train samples: {len(train_dataset)}")
    print(f"Val samples:   {len(val_dataset)}")
    print(f"Test samples:  {len(test_dataset)}")

    # Print baseline class distribution
    class_counts = Counter(train_dataset["label"])
    print(f"Train class distribution (0=pos, 1=neg, 2=neu): {dict(class_counts)}")

    print("\nStep 4: Computing dynamic class weights for unbalanced loss...")
    # Formula: total_samples / (num_classes * class_count)
    total_samples = len(train_dataset)
    num_classes = 3
    class_weights = [total_samples / (num_classes * class_counts[i]) for i in range(num_classes)]
    print(f"Computed class weights: {class_weights}")

    print("\nStep 5: Loading tokenizer and tokenizing data...")
    model_name = "ProsusAI/finbert"
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    
    def tokenize_fn(examples):
        return tokenizer(examples["sentence"], padding="max_length", truncation=True, max_length=128)
        
    tokenized_train = train_dataset.map(tokenize_fn, batched=True)
    tokenized_val = val_dataset.map(tokenize_fn, batched=True)
    tokenized_test = test_dataset.map(tokenize_fn, batched=True)

    print("\nStep 6: Loading pre-trained FinBERT model...")
    model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=3)

    print("\nStep 7: Configuring training arguments...")
    training_args = TrainingArguments(
        output_dir="models/checkpoints",
        eval_strategy="epoch",
        save_strategy="epoch",
        learning_rate=2e-5,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=16,
        num_train_epochs=5,
        weight_decay=0.01,
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        greater_is_better=True,
        logging_steps=10,
        report_to="none"  # Disable external logging for local execution
    )

    print("\nStep 8: Starting model training...")
    trainer = WeightedLossTrainer(
        class_weights=class_weights,
        model=model,
        args=training_args,
        train_dataset=tokenized_train,
        eval_dataset=tokenized_val,
        compute_metrics=compute_metrics
    )

    trainer.train()

    print("\nStep 9: Evaluating model on held-out test split...")
    test_results = trainer.evaluate(tokenized_test)
    print(f"Test split evaluation results: {test_results}")

    print("\nStep 10: Saving final best fine-tuned model and tokenizer...")
    best_model_path = "models/checkpoint-best"
    trainer.save_model(best_model_path)
    tokenizer.save_pretrained(best_model_path)
    print(f"Fine-tuned model saved successfully to {best_model_path}")

if __name__ == "__main__":
    main()
