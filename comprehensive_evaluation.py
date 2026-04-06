"""
Comprehensive SVM Model Evaluation with Expanded Dataset
This script evaluates the SVM model using a larger, more diverse dataset
"""

import json
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import (
    classification_report, confusion_matrix, accuracy_score,
    precision_score, recall_score, f1_score, roc_auc_score
)
from collections import Counter

def load_expanded_dataset():
    """Load the expanded dataset from the Python file"""
    # Import the dataset from the expanded_dataset.py file
    import expanded_dataset
    return expanded_dataset.texts, expanded_dataset.labels

def evaluate_svm_comprehensive():
    print("=" * 80)
    print("COMPREHENSIVE SVM MODEL EVALUATION - EXPANDED DATASET")
    print("=" * 80)
    print()

    # Load dataset
    texts, labels = load_expanded_dataset()

    print("DATASET OVERVIEW:")
    print(f"Total samples: {len(texts)}")
    print(f"Classes: {set(labels)}")
    print("Class distribution:")
    for label, count in Counter(labels).items():
        print(f"  {label}: {count} samples ({count/len(texts)*100:.1f}%)")
    print()

    # Split dataset
    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=42, stratify=labels
    )

    print("TRAIN/TEST SPLIT:")
    print(f"Training set: {len(X_train)} samples")
    print(f"Test set: {len(X_test)} samples")
    print()

    # Feature extraction
    print("FEATURE EXTRACTION:")
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        max_features=5000,
        min_df=2,
        max_df=0.95
    )
    X_train_vec = vectorizer.fit_transform(X_train)
    X_test_vec = vectorizer.transform(X_test)
    print(f"Features extracted: {X_train_vec.shape[1]}")
    print()

    # Model training
    print("MODEL TRAINING:")
    model = LinearSVC(
        class_weight='balanced',
        max_iter=2000,
        random_state=42,
        C=1.0
    )
    model.fit(X_train_vec, y_train)
    print("Model trained successfully")
    print()

    # Predictions
    y_pred = model.predict(X_test_vec)

    # Cross-validation scores
    print("CROSS-VALIDATION RESULTS:")
    cv_scores = cross_val_score(model, X_train_vec, y_train, cv=5, scoring='f1_weighted')
    print(f"CV F1 Scores: {cv_scores}")
    print(".4f")
    print(".4f")
    print()

    # Overall metrics
    print("OVERALL PERFORMANCE METRICS:")
    print("-" * 40)
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, average='weighted')
    recall = recall_score(y_test, y_pred, average='weighted')
    f1 = f1_score(y_test, y_pred, average='weighted')

    print(".4f")
    print(".4f")
    print(".4f")
    print(".4f")
    print()

    # Per-class metrics
    print("PER-CLASS PERFORMANCE:")
    print("-" * 40)
    report = classification_report(y_test, y_pred, target_names=sorted(set(labels)))
    print(report)

    # F1 Score breakdown
    print("F1 SCORE BREAKDOWN:")
    print("-" * 40)
    f1_per_class = f1_score(y_test, y_pred, average=None)
    class_names = sorted(set(labels))
    for cls, f1_val in zip(class_names, f1_per_class):
        print("15")
    print()

    # Confusion Matrix
    print("CONFUSION MATRIX:")
    print("-" * 40)
    cm = confusion_matrix(y_test, y_pred)
    print("Predicted ->")
    header = "Actual |" + "".join("15" for cls in class_names)
    print(header)
    print("-" * len(header))

    for i, actual in enumerate(class_names):
        row = "15" + "".join("15" for j in range(len(class_names)))
        print(row)
    print()

    # Additional metrics
    print("ADDITIONAL METRICS:")
    print("-" * 40)
    print(".4f")
    print(".4f")
    print(".4f")
    print(".4f")
    print()

    # Performance insights
    print("PERFORMANCE INSIGHTS:")
    print("-" * 40)

    # Find best and worst performing classes
    best_class_idx = np.argmax(f1_per_class)
    worst_class_idx = np.argmin(f1_per_class)

    print(f"Best performing class: {class_names[best_class_idx]} (F1: {f1_per_class[best_class_idx]:.4f})")
    print(f"Worst performing class: {class_names[worst_class_idx]} (F1: {f1_per_class[worst_class_idx]:.4f})")

    # Class balance analysis
    class_counts = Counter(y_test)
    print(f"Most frequent class in test set: {max(class_counts, key=class_counts.get)} ({max(class_counts.values())} samples)")
    print(f"Least frequent class in test set: {min(class_counts, key=class_counts.get)} ({min(class_counts.values())} samples)")

    # Overall assessment
    if accuracy > 0.8:
        assessment = "EXCELLENT"
    elif accuracy > 0.7:
        assessment = "GOOD"
    elif accuracy > 0.6:
        assessment = "MODERATE"
    else:
        assessment = "NEEDS IMPROVEMENT"

    print(f"\nOVERALL ASSESSMENT: {assessment} ({accuracy:.1f}%)")
    print("=" * 80)

if __name__ == "__main__":
    evaluate_svm_comprehensive()