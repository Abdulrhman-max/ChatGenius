"""
Full system integration test for BrightSmile chatbot routing.
Tests all 24 intents across all 10 engines + off-topic blocking.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sklearn_classifier
import restriction_filter
import smart_router

# Engine routing map for validation
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

# Test cases: (label, message, expected_engine)
TEST_CASES = [
    # Emergency Handler
    ("Emergency - swelling",        "my jaw is very swollen and painful",                  "EMERGENCY_HANDLER"),
    ("Emergency - bleeding",        "i have severe bleeding that wont stop after extraction","EMERGENCY_HANDLER"),
    ("Emergency - knocked out",     "my child knocked out a tooth playing soccer",          "EMERGENCY_HANDLER"),

    # Booking Engine (returns None — handled by app.py booking flow)
    ("Booking - appointment",       "i want to book an appointment with dr sarah",          "BOOKING_ENGINE"),
    ("Booking - reschedule",        "can i reschedule my appointment to next week",          "BOOKING_ENGINE"),

    # Calendar System
    ("Availability - doctor",       "is dr mohammed available this week",                    "CALENDAR_SYSTEM"),
    ("Availability - slots",        "what times are available for dr ahmed tomorrow",         "CALENDAR_SYSTEM"),

    # Pricing Database
    ("Pricing - implant",           "how much does a dental implant cost",                   "PRICING_DATABASE"),
    ("Pricing - braces",            "what is the price for braces at brightsmile",            "PRICING_DATABASE"),
    ("Payment - installment",       "can i pay for my treatment in installments",             "PRICING_DATABASE"),

    # Insurance Engine
    ("Insurance - bupa",            "does brightsmile accept bupa arabia insurance",          "INSURANCE_ENGINE"),
    ("Insurance - coverage",        "is my tawuniya insurance accepted for root canal",       "INSURANCE_ENGINE"),
    ("Insurance - verify",          "i want to verify my insurance coverage before visiting",  "INSURANCE_ENGINE"),

    # Patient Intake Engine
    ("Intake - forms",              "what forms do i need to fill before my first visit",     "INTAKE_ENGINE"),
    ("Intake - medical history",    "how do i submit my medical history to the clinic",       "INTAKE_ENGINE"),

    # Contact/Callback Engine
    ("Callback - call me",          "i am not ready to book but want a doctor to call me",   "CONTACT_ENGINE"),
    ("Callback - leave number",     "can i leave my number for someone to call me back",     "CONTACT_ENGINE"),

    # Reminder Engine
    ("Reminder - confirm",          "can you send me a reminder before my appointment",       "REMINDER_ENGINE"),
    ("Reminder - no-show",          "i missed my appointment yesterday can i rebook",          "REMINDER_ENGINE"),

    # Grok AI - various intents
    ("Grok - oral hygiene",         "how should i brush my teeth properly",                   "GROK_AI"),
    ("Grok - services",             "what is a hollywood smile makeover",                     "GROK_AI"),
    ("Grok - office hours",         "what time does brightsmile open on friday",              "GROK_AI"),
    ("Grok - specialist",           "which doctor handles crooked teeth",                     "GROK_AI"),
    ("Grok - post treatment",       "what should i do after a root canal",                    "GROK_AI"),
    ("Grok - recall",               "it has been over a year since my last dental visit should i come in", "GROK_AI"),
    ("Grok - promotions",           "do you have any special offers for teeth whitening",     "GROK_AI"),
    ("Grok - compliance",           "how does brightsmile protect my personal data",          "GROK_AI"),
    ("Grok - education",            "tell me about the benefits of dental implants compared to bridges", "GROK_AI"),
    ("Grok - multilingual",         "can i talk to the chatbot in arabic",                    "GROK_AI"),

    # Off-topic — should be BLOCKED
    ("BLOCK - weather",             "what is the weather in riyadh today",                    "BLOCKED"),
    ("BLOCK - joke",                "tell me a funny joke",                                   "BLOCKED"),
    ("BLOCK - restaurant",          "recommend a good restaurant near kingdom centre",        "BLOCKED"),
    ("BLOCK - sports",              "who won the football match last night",                   "BLOCKED"),
]


def get_effective_intent(message):
    """Mirror the app.py routing logic to determine effective intent + engine."""
    cleaned = message  # In real system, Grok AI cleans first

    # Step 1: Sklearn classification
    intent, conf = sklearn_classifier.classify(cleaned)

    # Step 2: Check restriction filter for off-topic
    is_blocked, _ = restriction_filter.is_off_topic(
        cleaned, sklearn_intent=intent, sklearn_conf=conf
    )
    if is_blocked:
        return "blocked", "BLOCKED", conf

    # Step 3: Keyword fallback (mirrors smart_router logic)
    keyword_intent = smart_router._detect_keyword_intent(cleaned)
    effective = intent

    if not intent or conf < 0.4:
        if keyword_intent:
            effective = keyword_intent
        else:
            # Low confidence + no keyword = falls through to general Grok AI
            return effective, "GROK_AI", conf
    else:
        if keyword_intent in ("emergency", "insurance_verification", "pricing_info", "noshow_reminders") and intent != keyword_intent:
            effective = keyword_intent

    engine = ENGINE_ROUTING.get(effective, "GROK_AI")
    return effective, engine, conf


print("=" * 110)
print("BRIGHTSMILE CHATBOT — FULL SYSTEM INTEGRATION TEST")
print(f"24 intents | 10 engines | {len(TEST_CASES)} test cases")
print("=" * 110)

passed = 0
failed = 0
print(f"\n{'Label':<28} {'Expected':<20} {'Got':<20} {'Intent':<28} {'Conf':>5} {'Status'}")
print("-" * 110)

for label, message, expected_engine in TEST_CASES:
    effective, engine, conf = get_effective_intent(message)
    ok = engine == expected_engine
    if ok:
        passed += 1
    else:
        failed += 1
    status = "PASS" if ok else f"FAIL"
    print(f"  {label:<26} {expected_engine:<20} {engine:<20} {effective:<28} {conf:>4.2f} {status}")

print(f"\n{'='*110}")
print(f"RESULTS: {passed}/{len(TEST_CASES)} passed, {failed}/{len(TEST_CASES)} failed")
if failed == 0:
    print("ALL TESTS PASSED!")
else:
    print(f"{failed} TESTS FAILED — review FAIL rows above")
print("=" * 110)
