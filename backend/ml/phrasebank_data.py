"""Pinned, local parser for the Financial PhraseBank holdout source."""

import hashlib
import zipfile

from datasets import ClassLabel, Dataset, Features, Value
from huggingface_hub import hf_hub_download

DATASET_REPO = "takala/financial_phrasebank"
DATASET_REVISION = "8d3fe0c36d5feec6b3cc5e455b0fcb4820fb9964"
DATASET_CONFIG = "sentences_allagree"
DATASET_FILENAME = "data/FinancialPhraseBank-v1.0.zip"
SPLIT_SEED = 42
LABEL_TO_ID = {"positive": 0, "negative": 1, "neutral": 2}


def load_phrasebank_splits():
    """Returns deterministic 80/10/10 splits and source fingerprints.

    The dataset is fetched into the Hugging Face cache and is not copied into
    the repository or runtime image. Its CC BY-NC-SA license is non-commercial.
    """
    archive_path = hf_hub_download(
        repo_id=DATASET_REPO,
        repo_type="dataset",
        filename=DATASET_FILENAME,
        revision=DATASET_REVISION,
    )
    rows = []
    with zipfile.ZipFile(archive_path) as archive:
        data_file = "FinancialPhraseBank-v1.0/Sentences_AllAgree.txt"
        with archive.open(data_file) as content:
            for line in content.read().decode("iso-8859-1").splitlines():
                sentence, label = line.rsplit("@", 1)
                label_id = LABEL_TO_ID.get(label.strip().lower())
                if sentence.strip() and label_id is not None:
                    rows.append({"sentence": sentence.strip(), "label": label_id})

    if not rows:
        raise ValueError("Pinned Financial PhraseBank archive contained no labeled rows.")

    complete = Dataset.from_list(
        rows,
        features=Features(
            {
                "sentence": Value("string"),
                "label": ClassLabel(names=["positive", "negative", "neutral"]),
            }
        ),
    )
    train_temp = complete.train_test_split(
        test_size=0.2, seed=SPLIT_SEED, stratify_by_column="label"
    )
    validation_test = train_temp["test"].train_test_split(
        test_size=0.5, seed=SPLIT_SEED, stratify_by_column="label"
    )
    splits = {
        "train": train_temp["train"],
        "validation": validation_test["train"],
        "test": validation_test["test"],
    }
    metadata = {
        "repo": DATASET_REPO,
        "revision": DATASET_REVISION,
        "config": DATASET_CONFIG,
        "archive_sha256": _sha256(archive_path),
        "split_seed": SPLIT_SEED,
        "split_strategy": "stratified_80_10_10",
        "class_order": ["positive", "negative", "neutral"],
        "sample_count": len(rows),
        "test_fingerprint": splits["test"]._fingerprint,
    }
    return splits, metadata


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
