import os
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC

# Paths to save/load the model and vectorizer
MODEL_PATH = os.path.join(os.path.dirname(__file__), "svm_model.pkl")
VECTORIZER_PATH = os.path.join(os.path.dirname(__file__), "vectorizer.pkl")

# Check if model exists
if os.path.exists(MODEL_PATH) and os.path.exists(VECTORIZER_PATH):
    # Load saved model and vectorizer
    model = joblib.load(MODEL_PATH)
    vectorizer = joblib.load(VECTORIZER_PATH)
else:
    # Training data
    texts = [
    # RESPONSIBILITY
    "The manager shall ensure compliance with this policy",
    "Department heads are responsible for implementation",
    "The supervisor must monitor employee performance",

    # PROCEDURE
    "Step 1: Open the application. Step 2: Click submit.",
    "This procedure must be followed during onboarding",
    "Follow these steps to complete the process",

    # POLICY
    "Employees may request leave up to 15 days annually",
    "All staff are entitled to medical benefits",
    "This policy applies to all full-time employees",

    # WORKING INSTRUCTION
    "How to Download Our Manuals in PDF format",
    "Instructions for operating the scanning machine",
    "Refer to this guide when using the document portal",
]
    labels = [
    "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY",
    "PROCEDURE", "PROCEDURE", "PROCEDURE",
    "POLICY", "POLICY", "POLICY",
    "WORKING INSTRUCTION", "WORKING INSTRUCTION", "WORKING INSTRUCTION",
]

    # Vectorize and train
    vectorizer = TfidfVectorizer()
    X = vectorizer.fit_transform(texts)
    model = LinearSVC()
    model.fit(X, labels)

    # Save model and vectorizer for future use
    joblib.dump(model, MODEL_PATH)
    joblib.dump(vectorizer, VECTORIZER_PATH)


def predict(text):
    """
    Predict the section of a given text using the trained SVM.
    """
    X_test = vectorizer.transform([text])
    return model.predict(X_test)