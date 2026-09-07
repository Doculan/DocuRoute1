import os
import json
import pandas as pd
from sklearn.model_selection import train_test_split

SOURCE_FILE = "ml/datasets/revision_data.csv"
OUTPUT_DIR = "ml/datasets"

ASSESSMENT_LABELS = {
    "Appropriate": 0,
    "Needs Revision": 1,
}

KNOWN_ISSUE_TAGS = [
    "ambiguous_language",
    "insufficient_detail",
    "missing_responsibility",
    "missing_approval_step",
    "missing_traceability",
    "missing_record_or_evidence",
    "irrelevant_content",
    "unclear_scope",
    "poor_organization",
    "illogical_sequence",
    "possible_contradiction",
    "ocr_quality_issue",
]

REQUIRED_COLUMNS = [
    "change_type",
    "original_text",
    "revised_text",
    "issue_tags",
    "reviewer_summary",
    "label",
]


def normalize_text(value):
    return " ".join(str(value).replace("\ufeff", "").split())


def parse_tags(value):
    value = normalize_text(value)

    if not value:
        return []

    tags = [tag.strip() for tag in value.split("|") if tag.strip()]
    unknown = set(tags) - set(KNOWN_ISSUE_TAGS)

    if unknown:
        raise ValueError(f"Unknown issue tags found: {sorted(unknown)}")

    return sorted(set(tags))


def build_model_input(row):
    return (
        f"[CHANGE TYPE]\n{row['change_type']}\n\n"
        f"[ORIGINAL TEXT]\n{row['original_text']}\n\n"
        f"[REVISED TEXT]\n{row['revised_text']}"
    )


def tags_to_multihot(tags, tag_to_id):
    vector = [0.0] * len(tag_to_id)

    for tag in tags:
        vector[tag_to_id[tag]] = 1.0

    return vector


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    df = pd.read_csv(SOURCE_FILE, encoding="cp1252").fillna("")

    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    for column in REQUIRED_COLUMNS:
        df[column] = df[column].apply(normalize_text)

    df["label"] = df["label"].str.strip()

    invalid_labels = set(df["label"]) - set(ASSESSMENT_LABELS)
    if invalid_labels:
        raise ValueError(
            f"Unexpected labels: {sorted(invalid_labels)}. "
            "Allowed labels are Appropriate and Needs Revision."
        )

    df = df[
        (df["change_type"] != "") &
        (df["original_text"] != "") &
        (df["revised_text"] != "")
    ].copy()

    df["parsed_tags"] = df["issue_tags"].apply(parse_tags)
    df["assessment_label_id"] = df["label"].map(ASSESSMENT_LABELS)
    df["model_input"] = df.apply(build_model_input, axis=1)

    tag_to_id = {
        tag: index
        for index, tag in enumerate(KNOWN_ISSUE_TAGS)
    }

    id_to_tag = {
        str(index): tag
        for tag, index in tag_to_id.items()
    }

    df["issue_multihot"] = df["parsed_tags"].apply(
        lambda tags: tags_to_multihot(tags, tag_to_id)
    )

    df = df.drop_duplicates(
        subset=[
            "change_type",
            "original_text",
            "revised_text",
            "label",
            "issue_tags",
        ]
    ).reset_index(drop=True)

    train_df, temporary_df = train_test_split(
        df,
        test_size=0.30,
        random_state=42,
        stratify=df["assessment_label_id"],
    )

    validation_df, test_df = train_test_split(
        temporary_df,
        test_size=0.50,
        random_state=42,
        stratify=temporary_df["assessment_label_id"],
    )

    output_columns = [
        "change_type",
        "original_text",
        "revised_text",
        "issue_tags",
        "reviewer_summary",
        "label",
        "assessment_label_id",
        "issue_multihot",
        "model_input",
    ]

    for name, split_df in [
        ("train", train_df),
        ("validation", validation_df),
        ("test", test_df),
    ]:
        split_df[output_columns].to_csv(
            f"{OUTPUT_DIR}/{name}.csv",
            index=False,
            encoding="utf-8-sig",
        )

    with open(
        f"{OUTPUT_DIR}/issue_tag_mapping.json",
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            {
                "tag_to_id": tag_to_id,
                "id_to_tag": id_to_tag,
            },
            file,
            indent=2,
        )

    tag_counts = {
        tag: int(
            df["parsed_tags"].apply(lambda tags: tag in tags).sum()
        )
        for tag in KNOWN_ISSUE_TAGS
    }

    summary = {
        "total_records": len(df),
        "assessment_counts": df["label"].value_counts().to_dict(),
        "issue_tag_counts": tag_counts,
        "train_records": len(train_df),
        "validation_records": len(validation_df),
        "test_records": len(test_df),
        "assessment_input_fields": [
            "change_type",
            "original_text",
            "revised_text",
        ],
        "issue_model_input_fields": [
            "change_type",
            "original_text",
            "revised_text",
        ],
        "metadata_not_used_as_input": [
            "reviewer_summary",
        ],
    }

    with open(
        f"{OUTPUT_DIR}/dataset_summary.json",
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(summary, file, indent=2)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()