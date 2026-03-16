import os
import joblib
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
        "This procedure applies to all constituencies of the university",
        "The policy regulates the functioning of structures that impact relationships",
        "Employees are prohibited from disclosing confidential information",
        "All purchases must be approved by the procurement committee",
        "Faculty members must comply with the code of professional ethics",

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

        # ── PAGE_HEADER ──
        "MANUAL TITLE FINANCE AND ADMINISTRATION MANUAL DOCUMENT NO. FAM 18.02 DOCUMENT NAME ALUMNI EVENTS REVISION NO. 0 EFFECTIVITY DATE APRIL 11 2023 PAGE NO. 1 of 3",
        "MANUAL TITLE HUMAN RESOURCE MANUAL DOCUMENT NO. HRM 01.01 DOCUMENT NAME RECRUITMENT POLICY REVISION NO. 1 EFFECTIVITY DATE JANUARY 5 2022 PAGE NO. 1 of 5",
        "MANUAL TITLE OPERATIONS MANUAL DOCUMENT NO. OPM 05.03 DOCUMENT NAME PROCUREMENT PROCEDURE REVISION NO. 2 EFFECTIVITY DATE MARCH 20 2021 PAGE NO. 2 of 4",
        "VERSION NO. 1 MANUAL TITLE FINANCE AND ADMINISTRATION MANUAL DOCUMENT NO. FAM 18.02 DOCUMENT NAME ALUMNI EVENTS REVISION NO. 0 EFFECTIVITY DATE APRIL 11 2023 PAGE NO. 1 of 3",
        "VERSION NO. 2 DOCUMENT NO. HRM 02.01 DOCUMENT NAME LEAVE POLICY REVISION NO. 1 EFFECTIVITY DATE JUNE 1 2023 PAGE NO. 3 of 6",
        "DOCUMENT NO. FAM 10.01 DOCUMENT NAME PROCUREMENT MANUAL REVISION NO. 0 PAGE NO. 1 of 10 EFFECTIVITY DATE FEBRUARY 2022",
    ]

    labels = [
        # RESPONSIBILITY x19
        "RESPONSIBILITY","RESPONSIBILITY","RESPONSIBILITY","RESPONSIBILITY","RESPONSIBILITY",
        "RESPONSIBILITY","RESPONSIBILITY","RESPONSIBILITY","RESPONSIBILITY","RESPONSIBILITY",
        "RESPONSIBILITY","RESPONSIBILITY","RESPONSIBILITY","RESPONSIBILITY","RESPONSIBILITY",
        "RESPONSIBILITY","RESPONSIBILITY","RESPONSIBILITY","RESPONSIBILITY",
        # PROCEDURE x15
        "PROCEDURE","PROCEDURE","PROCEDURE","PROCEDURE","PROCEDURE",
        "PROCEDURE","PROCEDURE","PROCEDURE","PROCEDURE","PROCEDURE",
        "PROCEDURE","PROCEDURE","PROCEDURE","PROCEDURE","PROCEDURE",
        # POLICY x16
        "POLICY","POLICY","POLICY","POLICY","POLICY",
        "POLICY","POLICY","POLICY","POLICY","POLICY",
        "POLICY","POLICY","POLICY","POLICY","POLICY","POLICY",
        # WORKING INSTRUCTION x15
        "WORKING INSTRUCTION","WORKING INSTRUCTION","WORKING INSTRUCTION","WORKING INSTRUCTION","WORKING INSTRUCTION",
        "WORKING INSTRUCTION","WORKING INSTRUCTION","WORKING INSTRUCTION","WORKING INSTRUCTION","WORKING INSTRUCTION",
        "WORKING INSTRUCTION","WORKING INSTRUCTION","WORKING INSTRUCTION","WORKING INSTRUCTION","WORKING INSTRUCTION",
        # PAGE_HEADER x6
        "PAGE_HEADER","PAGE_HEADER","PAGE_HEADER","PAGE_HEADER","PAGE_HEADER","PAGE_HEADER",
    ]

    vectorizer = TfidfVectorizer()
    X = vectorizer.fit_transform(texts)
    model = LinearSVC()
    model.fit(X, labels)

    joblib.dump(model, MODEL_PATH)
    joblib.dump(vectorizer, VECTORIZER_PATH)


def predict(text):
    X_test = vectorizer.transform([text])
    return model.predict(X_test)
