"""
SVM Model Evaluation with Expanded Dataset - Clean Results
"""

import json
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score, f1_score
from collections import Counter

def load_dataset():
    """Load the expanded dataset"""
    import expanded_dataset
    return expanded_dataset.texts, expanded_dataset.labels

def evaluate_svm_model():
    print("=" * 70)
    print("SVM TEXT CATEGORIZATION - EXPANDED DATASET EVALUATION")
    print("=" * 70)

    # Load data
    texts, labels = load_dataset()
    print(f"Dataset: {len(texts)} samples across {len(set(labels))} categories")
    print(f"Categories: {', '.join(sorted(set(labels)))}")
    print()

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=42, stratify=labels
    )

    # Vectorize
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=5000)
    X_train_vec = vectorizer.fit_transform(X_train)
    X_test_vec = vectorizer.transform(X_test)

    # Train model
    model = LinearSVC(class_weight='balanced', max_iter=2000, random_state=42)
    model.fit(X_train_vec, y_train)

    # Evaluate
    y_pred = model.predict(X_test_vec)

    # Key metrics
    accuracy = accuracy_score(y_test, y_pred)
    f1_weighted = f1_score(y_test, y_pred, average='weighted')
    f1_macro = f1_score(y_test, y_pred, average='macro')

    print("KEY PERFORMANCE METRICS:")
    print("-" * 30)
    print(".1f")
    print(".1f")
    print(".1f")
    print()

    # Per-class F1 scores
    print("PER-CLASS F1 SCORES:")
    print("-" * 30)
    f1_per_class = f1_score(y_test, y_pred, average=None)
    class_names = sorted(set(labels))
    for cls, f1_val in zip(class_names, f1_per_class):
        print("15")
    print()

    # Cross-validation
    cv_scores = cross_val_score(model, X_train_vec, y_train, cv=5, scoring='f1_weighted')
    print("CROSS-VALIDATION RESULTS:")
    print("-" * 30)
    print(".3f")
    print(".3f")
    print()

    # Confusion matrix (simplified)
    print("CONFUSION MATRIX:")
    print("-" * 30)
    cm = confusion_matrix(y_test, y_pred)
    print("Actual\\Predicted |", " | ".join("12" for cls in class_names))
    print("-" * 60)
    for i, actual in enumerate(class_names):
        row = "15" + " | ".join("2" for j in range(len(class_names)))
        print(row)
    print()

    # Assessment
    if accuracy >= 0.8:
        assessment = "EXCELLENT"
    elif accuracy >= 0.7:
        assessment = "GOOD"
    elif accuracy >= 0.6:
        assessment = "MODERATE"
    else:
        assessment = "NEEDS IMPROVEMENT"

    print(f"OVERALL ASSESSMENT: {assessment}")
    print(f"Model shows {assessment.lower()} performance with {accuracy:.1f}% accuracy")
    print("=" * 70)

if __name__ == "__main__":
    evaluate_svm_model()