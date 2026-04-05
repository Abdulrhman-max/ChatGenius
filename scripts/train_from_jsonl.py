"""
Train sklearn intent classifier from the combined JSONL training data.
Reads brightsmile_training.jsonl (6170 rows covering all 36 intents),
trains TF-IDF + LogisticRegression pipeline, saves as intent_classifier.pkl.
"""
import json
import pickle
import os
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

os.chdir(os.path.join(os.path.dirname(__file__), ".."))

JSONL_PATH = "brightsmile_training.jsonl"
MODEL_PATH = "intent_classifier.pkl"

# ── Load training data from JSONL ─────────────────────────────
texts = []
intents = []

with open(JSONL_PATH, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        messages = obj.get("messages", [])
        metadata = obj.get("metadata", {})
        intent = metadata.get("intent", "")

        # Extract user message
        user_msg = ""
        for msg in messages:
            if msg["role"] == "user":
                user_msg = msg["content"].strip()
                break

        if user_msg and intent:
            texts.append(user_msg)
            intents.append(intent)

print(f"Loaded {len(texts)} training examples from {JSONL_PATH}")

# ── Show intent distribution ──────────────────────────────────
from collections import Counter
dist = Counter(intents)
print(f"\nIntent distribution ({len(dist)} intents):")
for intent, count in sorted(dist.items(), key=lambda x: -x[1]):
    print(f"  {intent:<30} {count:>4}")

# ── Train/test split ──────────────────────────────────────────
X_train, X_test, y_train, y_test = train_test_split(
    texts, intents, test_size=0.15, random_state=42, stratify=intents
)

print(f"\nTraining: {len(X_train)} samples, Testing: {len(X_test)} samples")

# ── Train classifier ──────────────────────────────────────────
classifier = Pipeline([
    ("tfidf", TfidfVectorizer(
        ngram_range=(1, 3),
        max_features=30000,
        sublinear_tf=True,
        min_df=1,
    )),
    ("clf", LogisticRegression(
        max_iter=2000,
        C=5.0,
        class_weight="balanced",
    ))
])

classifier.fit(X_train, y_train)
predictions = classifier.predict(X_test)

print(f"\n{'='*60}")
print("CLASSIFICATION REPORT")
print(f"{'='*60}")
print(classification_report(y_test, predictions))

# ── Save model ────────────────────────────────────────────────
with open(MODEL_PATH, "wb") as f:
    pickle.dump(classifier, f)
print(f"Model saved to {MODEL_PATH}")

# ── Integration test with new feature intents ─────────────────
print(f"\n{'='*60}")
print("INTEGRATION TEST — NEW FEATURES")
print(f"{'='*60}")

test_cases = [
    # New 10 features
    ("Reminder",        "will I get a reminder before my appointment",          "appointment_reminder"),
    ("Survey",          "how do I leave feedback about my visit",               "survey_feedback"),
    ("Package",         "do you have a family dental package",                  "treatment_package"),
    ("Invoice",         "can I get a receipt for my payment",                   "invoice_receipt"),
    ("No-show",         "I missed my appointment can I rebook",                 "noshow_reschedule"),
    ("Doctor Portal",   "how do I access the doctor portal",                    "doctor_portal"),
    ("Upsell",          "should I add whitening to my cleaning",                "upsell_addon"),
    ("Channel",         "can I message you on WhatsApp",                        "channel_inbox"),
    ("Report",          "can I see last month performance report",              "performance_report"),
    ("Whitelabel",      "can I customize the chatbot branding",                 "whitelabel_branding"),
    # Original intents (regression check)
    ("Booking",         "I want to book an appointment with Dr Sarah",          "book_appointment"),
    ("Emergency",       "my tooth is broken and bleeding badly",                "emergency"),
    ("Pricing",         "how much does a root canal cost",                      "pricing_info"),
    ("Insurance",       "do you accept Bupa insurance",                         "insurance_verification"),
    ("Intake",          "I need to fill out the new patient form",              "patient_intake"),
    ("Hours",           "what are your office hours on Friday",                 "office_hours"),
    ("Hygiene",         "how should I floss properly",                          "oral_hygiene"),
]

passed = 0
failed = 0
print(f"\n{'Label':<20} {'Expected':<30} {'Predicted':<30} {'Conf':>6} {'Status'}")
print("-" * 95)

for label, message, expected in test_cases:
    probs = classifier.predict_proba([message])[0]
    pred_idx = probs.argmax()
    predicted = classifier.classes_[pred_idx]
    conf = probs[pred_idx]
    ok = predicted == expected
    if ok:
        passed += 1
    else:
        failed += 1
    status = "PASS" if ok else f"FAIL (got {predicted})"
    print(f"{label:<20} {expected:<30} {predicted:<30} {conf:>5.2f} {status}")

print(f"\n{passed}/{passed+failed} tests passed")
