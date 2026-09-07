import os
import ast
import json
import numpy as np
import pandas as pd
from datasets import Dataset
from sklearn.metrics import (
    f1_score,
    precision_score,
    recall_score,
    classification_report,
)
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    DataCollatorWithPadding,
    Trainer,
    TrainingArguments,
)

BASE_MODEL = "distilbert-base-uncased"

TRAIN_FILE = "ml/datasets/train.csv"
VALIDATION_FILE = "ml/datasets/validation.csv"
TEST_FILE = "ml/datasets/test.csv"
TAG_MAPPING_FILE = "ml/datasets/issue_tag_mapping.json"

MODEL_DIR = "ml/saved_models/distilbert_revision_issues"
CHECKPOINT_DIR = "ml/training_checkpoints/issues"
EVALUATION_DIR = "ml/evaluation/issues"

PREDICTION_THRESHOLD = 0.50


def load_tag_mapping():
    with open(TAG_MAPPING_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)

    tag_to_id = data["tag_to_id"]
    id_to_tag = {
        int(index): tag
        for index, tag in data["id_to_tag"].items()
    }

    return tag_to_id, id_to_tag


def parse_vector(value):
    if isinstance(value, list):
        return value

    return ast.literal_eval(value)


def load_split(path):
    df = pd.read_csv(path, encoding="utf-8-sig").fillna("")

    df["issue_multihot"] = df["issue_multihot"].apply(parse_vector)

    records = {
        "text": df["model_input"].tolist(),
        "labels": df["issue_multihot"].tolist(),
    }

    return Dataset.from_dict(records)


def compute_metrics(prediction):
    logits, labels = prediction

    probabilities = 1 / (1 + np.exp(-logits))
    predicted = (probabilities >= PREDICTION_THRESHOLD).astype(int)
    labels = labels.astype(int)

    return {
        "f1_micro": f1_score(
            labels,
            predicted,
            average="micro",
            zero_division=0,
        ),
        "f1_macro": f1_score(
            labels,
            predicted,
            average="macro",
            zero_division=0,
        ),
        "precision_micro": precision_score(
            labels,
            predicted,
            average="micro",
            zero_division=0,
        ),
        "recall_micro": recall_score(
            labels,
            predicted,
            average="micro",
            zero_division=0,
        ),
    }


def main():
    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    os.makedirs(EVALUATION_DIR, exist_ok=True)

    tag_to_id, id_to_tag = load_tag_mapping()
    num_labels = len(tag_to_id)

    train_dataset = load_split(TRAIN_FILE)
    validation_dataset = load_split(VALIDATION_FILE)
    test_dataset = load_split(TEST_FILE)

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)

    def tokenize(batch):
        return tokenizer(
            batch["text"],
            truncation=True,
            max_length=512,
        )

    train_dataset = train_dataset.map(tokenize, batched=True)
    validation_dataset = validation_dataset.map(tokenize, batched=True)
    test_dataset = test_dataset.map(tokenize, batched=True)

    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL,
        num_labels=num_labels,
        problem_type="multi_label_classification",
        id2label=id_to_tag,
        label2id=tag_to_id,
    )

    args = TrainingArguments(
        output_dir=CHECKPOINT_DIR,
        learning_rate=2e-5,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=8,
        num_train_epochs=5,
        weight_decay=0.01,
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1_micro",
        greater_is_better=True,
        report_to="none",
        seed=42,
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        processing_class=tokenizer,
        data_collator=DataCollatorWithPadding(tokenizer=tokenizer),
        compute_metrics=compute_metrics,
    )

    trainer.train()
    trainer.save_model(MODEL_DIR)
    tokenizer.save_pretrained(MODEL_DIR)

    output = trainer.predict(test_dataset)

    probabilities = 1 / (1 + np.exp(-output.predictions))
    predicted = (probabilities >= PREDICTION_THRESHOLD).astype(int)
    actual = output.label_ids.astype(int)

    metrics = compute_metrics((output.predictions, actual))

    tag_names = [
        id_to_tag[index]
        for index in range(num_labels)
    ]

    report = classification_report(
        actual,
        predicted,
        target_names=tag_names,
        output_dict=True,
        zero_division=0,
    )

    prediction_rows = []

    for row_index in range(len(actual)):
        actual_tags = [
            tag_names[index]
            for index, value in enumerate(actual[row_index])
            if value == 1
        ]

        predicted_tags = [
            tag_names[index]
            for index, value in enumerate(predicted[row_index])
            if value == 1
        ]

        confidence_by_tag = {
            tag_names[index]: round(
                float(probabilities[row_index][index]) * 100,
                2,
            )
            for index in range(num_labels)
            if probabilities[row_index][index] >= PREDICTION_THRESHOLD
        }

        prediction_rows.append(
            {
                "actual_tags": "|".join(actual_tags),
                "predicted_tags": "|".join(predicted_tags),
                "predicted_tag_confidences": json.dumps(
                    confidence_by_tag
                ),
            }
        )

    pd.DataFrame(prediction_rows).to_csv(
        f"{EVALUATION_DIR}/test_tag_predictions.csv",
        index=False,
        encoding="utf-8-sig",
    )

    with open(
        f"{EVALUATION_DIR}/test_metrics.json",
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(metrics, file, indent=2)

    with open(
        f"{EVALUATION_DIR}/classification_report.json",
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(report, file, indent=2)

    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()