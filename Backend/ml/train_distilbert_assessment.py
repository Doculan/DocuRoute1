import os
import json
import numpy as np
import pandas as pd
from datasets import Dataset
from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
    classification_report,
    confusion_matrix,
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

MODEL_DIR = "ml/saved_models/distilbert_revision_assessment"
CHECKPOINT_DIR = "ml/training_checkpoints/assessment"
EVALUATION_DIR = "ml/evaluation/assessment"

LABEL_TO_ID = {
    "Appropriate": 0,
    "Needs Revision": 1,
}

ID_TO_LABEL = {
    0: "Appropriate",
    1: "Needs Revision",
}


def load_split(path):
    df = pd.read_csv(path, encoding="utf-8-sig").fillna("")

    return Dataset.from_pandas(
        df[["model_input", "assessment_label_id"]].rename(
            columns={
                "model_input": "text",
                "assessment_label_id": "labels",
            }
        ),
        preserve_index=False,
    )


def compute_metrics(prediction):
    logits, labels = prediction
    predicted_ids = np.argmax(logits, axis=1)

    weighted = precision_recall_fscore_support(
        labels,
        predicted_ids,
        average="weighted",
        zero_division=0,
    )

    macro = precision_recall_fscore_support(
        labels,
        predicted_ids,
        average="macro",
        zero_division=0,
    )

    return {
        "accuracy": accuracy_score(labels, predicted_ids),
        "precision_weighted": weighted[0],
        "recall_weighted": weighted[1],
        "f1_weighted": weighted[2],
        "precision_macro": macro[0],
        "recall_macro": macro[1],
        "f1_macro": macro[2],
    }


def main():
    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    os.makedirs(EVALUATION_DIR, exist_ok=True)

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
        num_labels=2,
        id2label=ID_TO_LABEL,
        label2id=LABEL_TO_ID,
    )

    args = TrainingArguments(
        output_dir=CHECKPOINT_DIR,
        learning_rate=2e-5,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=8,
        num_train_epochs=4,
        weight_decay=0.01,
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1_macro",
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

    result = trainer.predict(test_dataset)
    predictions = np.argmax(result.predictions, axis=1)
    actual = result.label_ids

    metrics = compute_metrics((result.predictions, actual))
    report = classification_report(
        actual,
        predictions,
        target_names=[
            ID_TO_LABEL[0],
            ID_TO_LABEL[1],
        ],
        output_dict=True,
        zero_division=0,
    )

    matrix = confusion_matrix(actual, predictions)

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

    pd.DataFrame(
        matrix,
        index=[
            "actual_Appropriate",
            "actual_Needs_Revision",
        ],
        columns=[
            "predicted_Appropriate",
            "predicted_Needs_Revision",
        ],
    ).to_csv(
        f"{EVALUATION_DIR}/confusion_matrix.csv",
        encoding="utf-8-sig",
    )

    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()