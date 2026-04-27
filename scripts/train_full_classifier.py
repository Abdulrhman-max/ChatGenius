"""
Train the full BrightSmile intent classifier on 6000 rows (2000 old + 4000 new).
Covers all 26 intents across all engines.
"""
import pandas as pd
import json
import pickle
import os
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

os.chdir(os.path.join(os.path.dirname(__file__), ".."))

# ── STEP 1: Load both training files ─────────────────────────
df1 = pd.read_excel("data/dental_chatbot_qa_final.xlsx")
df2 = pd.read_excel("data/dental_feature_qa_4000.xlsx")

# Normalize column names — old file uses "Category", new uses "Feature Category"
if "Feature Category" in df2.columns:
    df2 = df2.rename(columns={"Feature Category": "Category"})
if "Feature Category" in df1.columns:
    df1 = df1.rename(columns={"Feature Category": "Category"})

df = pd.concat([df1, df2], ignore_index=True)
df = df.dropna(subset=["Question", "Expected Answer"])
df = df[df["Question"].astype(str).str.strip() != ""]
df = df[df["Expected Answer"].astype(str).str.strip() != ""]
print(f"Total training rows: {len(df)}")

# ── STEP 2: Intent map covering all engines ───────────────────
intent_map = {
    # Old 10 intents (from 2000-row file)
    "Appointment Scheduling":             "book_appointment",
    "Doctor Availability":                "check_availability",
    "Dental Services Info":               "services_info",
    "Pricing & Payment":                  "pricing_info",
    "Office Hours & Location":            "office_hours",
    "Oral Hygiene Tips":                  "oral_hygiene",
    "Specialist Recommendations":         "specialist_recommendation",
    "Post-Treatment Care":                "post_treatment",
    "Emergency Dental":                   "emergency",
    "General Dental Questions":           "general_dental",
    # New 16 intents (from 4000-row file)
    "Appointment Booking System":         "book_appointment",
    "Insurance Verification":             "insurance_verification",
    "FAQ & Knowledge Base":               "faq_general",
    "Emergency Triage & Routing":         "emergency",
    "Patient Intake & Digital Forms":     "patient_intake",
    "Contact Leaving & Callbacks":        "contact_callback",
    "Treatment Upselling & Education":    "treatment_education",
    "Patient Recall & Reactivation":      "patient_recall",
    "Payment Plans & Financing":          "payment_financing",
    "Promotions & Campaigns":             "promotions",
    "No-Show Reduction & Reminders":      "noshow_reminders",
    "Multilingual Support":               "multilingual",
    "HIPAA GDPR Compliance":              "compliance",
    "PMS Integration":                    "pms_integration",
    "Analytics Dashboard":                "analytics",
    "Multi-Location & DSO Support":       "multi_location",
}

# ── ENGINE ROUTING MAP ────────────────────────────────────────
ENGINE_ROUTING = {
    "symptom_detection":         "CHATGPT",
    "book_appointment":          "BOOKING_ENGINE",
    "check_availability":        "CALENDAR_SYSTEM",
    "pricing_info":              "PRICING_DATABASE",
    "payment_financing":         "PRICING_DATABASE",
    "emergency":                 "EMERGENCY_HANDLER",
    "insurance_verification":    "INSURANCE_ENGINE",
    "patient_intake":            "INTAKE_ENGINE",
    "contact_callback":          "CONTACT_ENGINE",
    "noshow_reminders":          "REMINDER_ENGINE",
    "faq_general":               "GROK_AI",
    "services_info":             "GROK_AI",
    "treatment_education":       "GROK_AI",
    "patient_recall":            "GROK_AI",
    "promotions":                "GROK_AI",
    "multilingual":              "GROK_AI",
    "compliance":                "GROK_AI",
    "pms_integration":           "GROK_AI",
    "analytics":                 "GROK_AI",
    "multi_location":            "GROK_AI",
    "office_hours":              "GROK_AI",
    "oral_hygiene":              "GROK_AI",
    "specialist_recommendation": "GROK_AI",
    "post_treatment":            "GROK_AI",
    "general_dental":            "GROK_AI",
}

CLINIC_CONTEXT = """
You are the AI assistant for BrightSmile Advanced Dental Center.
Address: King Fahd Road, Al Olaya District, Riyadh 12214, near Kingdom Centre Tower, 3rd Floor.
Phone: +966 11 234 5678 | WhatsApp: +966 55 987 6543 | Emergency 24/7: +966 50 111 2222
Hours: Saturday-Thursday 9AM-10PM | Friday 2PM-10PM | Emergency: 24/7
Doctors: Dr. Ahmed Al-Harbi (General Dentistry, 12 years), Dr. Sarah Al-Qahtani (Orthodontics, 10 years),
         Dr. Mohammed Al-Otaibi (Oral Surgery, 15 years), Dr. Lina Al-Salem (Pediatric Dentistry, 8 years),
         Dr. Khalid Al-Faisal (Cosmetic Dentistry, 11 years)
Prices in USD: Consultation $27 | Cleaning $67 | Filling $53-$107 | Root Canal $213-$400 |
               Extraction $80-$187 | Implant $800-$1,600 | Whitening $267-$480 |
               Braces $2,133-$4,000 | Veneers $320-$667 per tooth
Insurance: Bupa Arabia, Tawuniya, MedGulf, Allianz Saudi Fransi, AXA Cooperative Insurance
Payment: Cash, Visa, MasterCard, Mada, Apple Pay, STC Pay, Tabby, Tamara
"""

BLOCKED_RESPONSE = (
    "I'm sorry, I can only assist with dental-related topics for "
    "BrightSmile Advanced Dental Center. How can I help you with your "
    "dental needs%s You can reach us at +966 11 234 5678 or "
    "WhatsApp +966 55 987 6543."
)

# Map categories to intents
df["Category"] = df["Category"].astype(str).str.strip()
df["intent"] = df["Category"].map(intent_map)
unmapped = df[df["intent"].isna()]["Category"].unique()
if len(unmapped) > 0:
    print(f"WARNING: Unmapped categories: {unmapped}")
df = df.dropna(subset=["intent"])
print(f"Rows after intent mapping: {len(df)}")
print(f"\nIntent distribution:")
print(df["intent"].value_counts().to_string())
print(f"\nEngine routing summary:")
for intent, engine in ENGINE_ROUTING.items():
    count = len(df[df["intent"] == intent])
    if count > 0:
        print(f"  {engine:<25} {intent:<35} {count} rows")

# ── STEP 3: Train intent classifier ──────────────────────────
X = df["Question"].astype(str)
y = df["intent"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.15, random_state=42, stratify=y
)

classifier = Pipeline([
    ("tfidf", TfidfVectorizer(
        ngram_range=(1, 3),
        max_features=15000,
        sublinear_tf=True,
        min_df=1
    )),
    ("clf", LogisticRegression(
        max_iter=2000,
        C=5.0,
        class_weight="balanced"
    ))
])

classifier.fit(X_train, y_train)
predictions = classifier.predict(X_test)
print(f"\n{'='*60}")
print("INTENT CLASSIFIER RESULTS")
print(f"{'='*60}")
print(classification_report(y_test, predictions))

# Save classifier
with open("intent_classifier.pkl", "wb") as f:
    pickle.dump(classifier, f)
print("Intent classifier saved as intent_classifier.pkl")

# Save engine routing
with open("engine_routing.json", "w") as f:
    json.dump(ENGINE_ROUTING, f, indent=2)
print("Engine routing saved as engine_routing.json")

# ── STEP 4: Build JSONL training file ────────────────────────
SYSTEM_PROMPT = f"You are the AI assistant for BrightSmile Advanced Dental Center. You are strictly domain-locked to dental topics only. Never answer anything outside dentistry or clinic operations. Always use real BrightSmile data. {CLINIC_CONTEXT} For off-topic questions respond only with: {BLOCKED_RESPONSE}"

entries = []
skipped = 0

for _, row in df.iterrows():
    question = str(row.get("Question", "")).strip()
    answer = str(row.get("Expected Answer", "")).strip()
    intent = str(row.get("intent", "")).strip()
    if not question or not answer or question == "nan" or answer == "nan":
        skipped += 1
        continue
    engine = ENGINE_ROUTING.get(intent, "GROK_AI")
    entries.append({
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer}
        ],
        "metadata": {
            "intent": intent,
            "engine": engine,
            "category": str(row.get("Category", ""))
        }
    })

jsonl_path = "brightsmile_training.jsonl"
with open(jsonl_path, "w", encoding="utf-8") as f:
    for entry in entries:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
print(f"\nJSONL created: {len(entries)} entries, {skipped} skipped")

# ── STEP 5: Validate JSONL ────────────────────────────────────
valid = 0
invalid = 0
with open(jsonl_path, "r", encoding="utf-8") as f:
    for line in f:
        try:
            obj = json.loads(line)
            msgs = obj.get("messages", [])
            roles = [m["role"] for m in msgs]
            contents = [m["content"] for m in msgs]
            if (all(r in roles for r in ["system", "user", "assistant"])
                    and all(c.strip() for c in contents)):
                valid += 1
            else:
                invalid += 1
        except Exception:
            invalid += 1
print(f"Validation: {valid} valid entries, {invalid} invalid entries")
if invalid > 0:
    print("WARNING: Some invalid entries found!")
else:
    print("All entries valid!")

# ── STEP 6: Integration test ─────────────────────────────────
print(f"\n{'='*60}")
print("FULL SYSTEM INTEGRATION TEST")
print(f"{'='*60}")

ALLOWED_INTENTS = list(ENGINE_ROUTING.keys())

test_cases = [
    ("Symptom → ChatGPT",       "my tooth hurts very bad and my face is swollen",      "emergency"),
    ("Booking → Engine",         "i want to book an appointment with dr sarah tomorrow", "book_appointment"),
    ("Availability → Calendar",  "is dr mohammed available this week",                   "check_availability"),
    ("Pricing → Database",       "how much does an implant cost at BrightSmile",         "pricing_info"),
    ("Emergency → Handler",      "i have severe bleeding that wont stop after extraction","emergency"),
    ("Insurance → Engine",       "does BrightSmile accept my Tawuniya insurance",        "insurance_verification"),
    ("Intake → Engine",          "i need to fill my medical history before my first visit","patient_intake"),
    ("Callback → Contact",       "i am not ready to book but want a doctor to call me",  "contact_callback"),
    ("Reminder → Engine",        "can you send me a reminder before my appointment",      "noshow_reminders"),
    ("Grok - Oral Hygiene",      "how do i clean around my new implant",                  "oral_hygiene"),
    ("Grok - Services",          "what is a Hollywood smile makeover",                    "services_info"),
    ("Grok - Recall",            "i havent visited in 9 months should i come in",         "patient_recall"),
    ("Grok - Compliance",        "how does BrightSmile protect my personal data",         "compliance"),
    ("Grok - Promotions",        "do you have any special offers right now",              "promotions"),
    ("Grok - Payment Plans",     "can i pay for braces in installments",                  "payment_financing"),
    ("Grok - Upsell",            "i just want a cleaning nothing else",                   "treatment_education"),
]

passed = 0
failed = 0
print(f"\n{'Label':<25} {'Expected':<30} {'Predicted':<30} {'Conf':>6} {'Status'}")
print("-" * 100)

for label, message, expected_intent in test_cases:
    probs = classifier.predict_proba([message])[0]
    pred_idx = probs.argmax()
    predicted = classifier.classes_[pred_idx]
    conf = probs[pred_idx]
    expected_engine = ENGINE_ROUTING.get(expected_intent, "GROK_AI")
    predicted_engine = ENGINE_ROUTING.get(predicted, "GROK_AI")
    ok = predicted_engine == expected_engine
    if ok:
        passed += 1
    else:
        failed += 1
    status = "PASS" if ok else f"FAIL (got {predicted_engine})"
    print(f"{label:<25} {expected_intent:<30} {predicted:<30} {conf:>5.2f} {status}")

print(f"\n{passed}/{passed+failed} tests passed")
if failed == 0:
    print("ALL TESTS PASSED!")
else:
    print(f"{failed} tests FAILED — review above")
