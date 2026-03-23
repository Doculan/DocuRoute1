import os
import joblib
from collections import Counter
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC

MODEL_PATH = os.path.join(os.path.dirname(__file__), "svm_model.pkl")
VECTORIZER_PATH = os.path.join(os.path.dirname(__file__), "vectorizer.pkl")

if os.path.exists(MODEL_PATH) and os.path.exists(VECTORIZER_PATH):
    model = joblib.load(MODEL_PATH)
    vectorizer = joblib.load(VECTORIZER_PATH)
else:
    texts = [
        # ── RESPONSIBILITY ──
        # Role-based: who is accountable for what
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
        # Step-by-step actions: submit, fill out, proceed, accomplish
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
        # Rules, entitlements, standards that apply broadly
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
        # Guidance, how-to, objectives, forms to use
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

    # FIX #3: balanced class weights so no class dominates
    vectorizer = TfidfVectorizer(ngram_range=(1, 2))
    X = vectorizer.fit_transform(texts)
    model = LinearSVC(class_weight='balanced', max_iter=2000)
    model.fit(X, labels)

    joblib.dump(model, MODEL_PATH)
    joblib.dump(vectorizer, VECTORIZER_PATH)


def predict(text: str) -> list:
    """Classify a single text string. Returns a list with one label."""
    X_test = vectorizer.transform([text])
    return model.predict(X_test)


def predict_section(text: str) -> str:
    """FIX #3: Sentence-level majority vote for more accurate section classification.

    Instead of averaging TF-IDF of an entire multi-line block, we classify
    each non-empty line individually and return the majority label.
    Falls back to single-pass predict() for very short inputs.
    """
    lines = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 10]

    if len(lines) <= 2:
        # Too short for voting — use single prediction
        return predict(text)[0]

    predictions = []
    for line in lines:
        try:
            predictions.append(predict(line)[0])
        except Exception:
            pass

    if not predictions:
        return 'UNTAGGED'

    # Majority vote
    return Counter(predictions).most_common(1)[0][0]