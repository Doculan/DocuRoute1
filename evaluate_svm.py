import os
import joblib
from collections import Counter
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score, precision_score, recall_score, f1_score
import numpy as np

# Load the existing model and vectorizer
MODEL_PATH = os.path.join("Backend", "ml", "svm_model.pkl")
VECTORIZER_PATH = os.path.join("Backend", "ml", "vectorizer.pkl")

# Training data (same as in svm_model.py)
texts = [
    # ── RESPONSIBILITY ──
    "The manager shall ensure compliance with this policy",
    "Department heads are responsible for implementation",
    "The supervisor must monitor employee performance",
    "Alumni Affairs Director prepares the annual activities and events of the office",
    "Secure approval of activities from the concerned offices",
    "Reviews the proposed activities of the alumni association",
    "Conducts series of meetings and consultations for the improvement of events",
    "Post announcements in strategic places and platforms for dissemination",
    "Creates a report of all activities spearheaded by the alumni office",
    "Coordinate with the Alumni Affairs office for planned activities",
    "Evaluates and approves the proposed activities of the alumni office",
    "The Dean of Student Affairs secures approval and reserves venues",
    "Vice President for Academic Affairs evaluates proposed activities",
    "University President approves all proposed activities",
    "Spearhead solicitation and secures finances for approved activities",
    "Create different committees to spearhead the alumni homecoming",
    "Initiate linkages of alumni locally and internationally",
    "The committee chair shall oversee implementation of the event",
    "The registrar is responsible for verifying alumni registration",
    "The BAC Secretariat is responsible for receiving bid documents",
    "Supply Officer shall prepare the purchase request for approval",
    "The department head is responsible for endorsing the request to procurement",
    "Administrative Officer reviews and validates the submitted documents",
    "The finance officer certifies availability of funds before procurement",

    # ── PROCEDURE ──
    "Step 1: Open the application. Step 2: Click submit.",
    "This procedure must be followed during onboarding",
    "Follow these steps to complete the process",
    "All activities must be presented to university officials for approval",
    "Alumni are encouraged to fill out the registration form for tracing",
    "The Alumni Privilege ID Card must be shown during registration",
    "Submit the completed form to the registrar before the deadline",
    "Proceed to the cashier to pay the registration fee",
    "Fill out the required forms and attach necessary documents",
    "The request must be submitted at least five days in advance",
    "Accomplish the leave form and submit to the HR department",
    "Documents must be signed by the department head before submission",
    "The applicant must undergo orientation before starting work",
    "The form shall be forwarded to the concerned office for processing",
    "Complete all required fields and attach supporting documents",
    "The purchase request must be submitted to the procurement office",
    "Prepare the abstract of canvass after receiving three quotations",
    "Issue the purchase order upon approval of the BAC resolution",
    "Inspect and receive the delivered items and sign the inspection report",
    "Forward the paid documents to the accounting office for recording",
    "The supplier must deliver within the period stipulated in the contract",
    "Request for quotation must be sent to at least three suppliers",
    "Record the inventory items in the stock ledger card upon receipt",

    # ── POLICY ──
    "Employees may request leave up to 15 days annually",
    "All staff are entitled to medical benefits",
    "This policy applies to all full-time employees",
    "A yearly alumni homecoming hosted by the batch assigned is organized",
    "All alumni are encouraged to attend provided they register",
    "All specific activities must be duly approved by the University President",
    "As stated in the Constitution and by Laws of the Alumni Association",
    "Alumni elect their leaders every three years in the general assembly",
    "The university promotes sustained sense of belonging among alumni",
    "Regular contact with alumni is maintained through various activities",
    "All alumni of the university are encouraged to attend the general assembly",
    "This policy applies to all constituencies of the university",
    "The policy regulates the functioning of structures that impact relationships",
    "Employees are prohibited from disclosing confidential information",
    "All purchases must be approved by the procurement committee",
    "Faculty members must comply with the code of professional ethics",
    "All government procurement must follow Republic Act 9184",
    "Procurement of goods must comply with the approved annual procurement plan",
    "No payment shall be made without the corresponding purchase order",
    "Small value procurement is allowed for amounts below the threshold",

    # ── WORKING INSTRUCTION ──
    "How to download our manuals in PDF format",
    "Instructions for operating the scanning machine",
    "Refer to this guide when using the document portal",
    "To strengthen the ties between the university and alumni association",
    "To encourage better participation in various university alumni activities",
    "To promote a sustained sense of belonging to the university among alumni",
    "To disseminate information regarding the university its graduates and faculty",
    "To provide a forum for alumni for exchange of ideas on academic issues",
    "To let the alumni acknowledge their gratitude to their Alma Mater",
    "To organize events and reunion through communication",
    "Meeting of Minutes Form must be accomplished after every meeting",
    "Attendance of the meeting form must be signed by all participants",
    "Notice of Meeting Form must be distributed three days before the meeting",
    "Donation Slip Form must be issued for every donation received",
    "Use this form when requesting supplies from the procurement office",
    "To ensure proper documentation of procurement transactions",
    "To establish a systematic process for managing office supplies",
    "To provide guidelines for the conduct of competitive bidding",
    "Use the abstract of canvass form to record price quotations",
    "The purchase request form must indicate the specific item description and quantity",
]

labels = [
    # RESPONSIBILITY x24
    "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY",
    "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY",
    "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY",
    "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY",
    "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY", "RESPONSIBILITY",
    # PROCEDURE x23
    "PROCEDURE", "PROCEDURE", "PROCEDURE", "PROCEDURE", "PROCEDURE",
    "PROCEDURE", "PROCEDURE", "PROCEDURE", "PROCEDURE", "PROCEDURE",
    "PROCEDURE", "PROCEDURE", "PROCEDURE", "PROCEDURE", "PROCEDURE",
    "PROCEDURE", "PROCEDURE", "PROCEDURE", "PROCEDURE", "PROCEDURE",
    "PROCEDURE", "PROCEDURE", "PROCEDURE",
    # POLICY x20
    "POLICY", "POLICY", "POLICY", "POLICY", "POLICY",
    "POLICY", "POLICY", "POLICY", "POLICY", "POLICY",
    "POLICY", "POLICY", "POLICY", "POLICY", "POLICY",
    "POLICY", "POLICY", "POLICY", "POLICY", "POLICY",
    # WORKING INSTRUCTION x20
    "WORKING INSTRUCTION", "WORKING INSTRUCTION", "WORKING INSTRUCTION", "WORKING INSTRUCTION", "WORKING INSTRUCTION",
    "WORKING INSTRUCTION", "WORKING INSTRUCTION", "WORKING INSTRUCTION", "WORKING INSTRUCTION", "WORKING INSTRUCTION",
    "WORKING INSTRUCTION", "WORKING INSTRUCTION", "WORKING INSTRUCTION", "WORKING INSTRUCTION", "WORKING INSTRUCTION",
    "WORKING INSTRUCTION", "WORKING INSTRUCTION", "WORKING INSTRUCTION", "WORKING INSTRUCTION", "WORKING INSTRUCTION",
]

def evaluate_svm_model():
    print("=== SVM Model Evaluation for Text Categorization ===\n")

    # Split the data
    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.3, random_state=42, stratify=labels
    )

    print(f"Training set size: {len(X_train)}")
    print(f"Test set size: {len(X_test)}")
    print(f"Classes: {set(labels)}")
    print()

    # Vectorize
    vectorizer = TfidfVectorizer(ngram_range=(1, 2))
    X_train_vec = vectorizer.fit_transform(X_train)
    X_test_vec = vectorizer.transform(X_test)

    # Train model
    model = LinearSVC(class_weight='balanced', max_iter=2000, random_state=42)
    model.fit(X_train_vec, y_train)

    # Predictions
    y_pred = model.predict(X_test_vec)

    # Basic metrics
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, average='weighted')
    recall = recall_score(y_test, y_pred, average='weighted')
    f1 = f1_score(y_test, y_pred, average='weighted')

    print("=== Overall Metrics ===")
    print(f"Accuracy: {accuracy:.4f}")
    print(f"Precision (weighted): {precision:.4f}")
    print(f"Recall (weighted): {recall:.4f}")
    print(f"F1 Score (weighted): {f1:.4f}")
    print()

    # Per-class metrics
    print("=== Per-Class Metrics ===")
    report = classification_report(y_test, y_pred, target_names=set(labels))
    print(report)

    # Confusion Matrix
    print("=== Confusion Matrix ===")
    cm = confusion_matrix(y_test, y_pred)
    class_names = sorted(set(labels))
    print("Predicted ->")
    print("Actual \\ Predicted |", " | ".join(f"{cls}" for cls in class_names))
    print("-" * 80)
    for i, actual in enumerate(class_names):
        print(f"{actual:>15} |", " | ".join(f"{cm[i, j]:>3}" for j in range(len(class_names))))
    print()

    # F1 Score per class
    print("=== F1 Score per Class ===")
    f1_per_class = f1_score(y_test, y_pred, average=None)
    for cls, f1_val in zip(sorted(set(labels)), f1_per_class):
        print(f"{cls}: {f1_val:.4f}")
    print()

    # Macro and Micro averages
    print("=== Additional Metrics ===")
    print(f"F1 Score (macro): {f1_score(y_test, y_pred, average='macro'):.4f}")
    print(f"F1 Score (micro): {f1_score(y_test, y_pred, average='micro'):.4f}")
    print(f"Precision (macro): {precision_score(y_test, y_pred, average='macro'):.4f}")
    print(f"Recall (macro): {recall_score(y_test, y_pred, average='macro'):.4f}")

if __name__ == "__main__":
    evaluate_svm_model()