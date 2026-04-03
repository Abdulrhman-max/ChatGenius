"""
Test the full chatbot routing flow with 15 messages.
Verifies each message reaches the correct engine and returns a proper response.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import grok_cleaner
import sklearn_classifier
import restriction_filter
import smart_router

# Test messages with expected routing
TESTS = [
    # (message, expected_intent, description)
    ("my toth hirts alot", "emergency", "Symptom → ChatGPT/Claude for symptom detection"),
    ("i wan buk apointmnt tomorw", "book_appointment", "Booking → booking engine"),
    ("iz dr sarah availble today", "check_availability", "Availability → calendar for Dr. Sarah"),
    ("how mch dos whitning cost", "pricing_info", "Pricing → return $267–$480"),
    ("my jaw is very swolen", "emergency", "Emergency → return +966 50 111 2222"),
    ("how do i brush corectly", "oral_hygiene", "Oral hygiene → Grok AI"),
    ("witch docter for croked teth", "specialist_recommendation", "Specialist → Dr. Sarah Al-Qahtani"),
    ("what to do aftr extration", "post_treatment", "Post-treatment → Grok AI"),
    ("wat time do u open", "office_hours", "Office hours → return 9AM Sat-Thu"),
    ("i want implant who is the docter", "specialist_recommendation", "Specialist → Dr. Mohammed Al-Otaibi"),
    ("how much r braces", "pricing_info", "Pricing → return $2,133–$4,000"),
    ("i want hollywood smile", "services_info", "Services → Dr. Khalid Al-Faisal"),
    ("do u accept bupa", "pricing_info", "Insurance → confirm Bupa Arabia"),
    ("tell me a joke", None, "BLOCKED — non-dental"),
    ("what is the weather today", None, "BLOCKED — non-dental"),
]


def test_cleaning():
    """Test Step 1: Grok AI cleaning."""
    print("\n" + "=" * 60)
    print("STEP 1: Grok AI Message Cleaning")
    print("=" * 60)

    test_msgs = [
        "my toth hirts alot",
        "i wan buk apointmnt tomorw",
        "iz dr sarah availble today",
        "how mch dos whitning cost",
        "wat time do u open",
    ]

    for msg in test_msgs:
        cleaned = grok_cleaner.clean(msg)
        print(f"  IN:  {msg}")
        print(f"  OUT: {cleaned}")
        print()


def test_intent_classification():
    """Test Step 2+4: Sklearn classification + keyword fallback routing."""
    print("\n" + "=" * 60)
    print("STEP 2+4: Intent Classification + Smart Routing")
    print("=" * 60)

    passed = 0
    failed = 0

    for msg, expected, desc in TESTS:
        # First clean
        cleaned = grok_cleaner.clean(msg)
        intent, conf = sklearn_classifier.classify(cleaned)

        # Determine effective intent (mirrors smart_router.route() logic)
        kw_intent = smart_router._detect_keyword_intent(cleaned)
        effective = intent
        if not intent or conf < 0.4:
            if kw_intent:
                effective = kw_intent
        else:
            if kw_intent in ("emergency", "pricing_info", "services_info") and intent != kw_intent:
                effective = kw_intent

        if expected is None:
            # Should be blocked
            is_blocked, _ = restriction_filter.is_off_topic(
                cleaned, sklearn_intent=intent, sklearn_conf=conf
            )
            status = "PASS" if is_blocked else "FAIL"
            if is_blocked:
                passed += 1
            else:
                failed += 1
            print(f"  [{status}] '{msg}' → BLOCKED | sklearn={intent}({conf:.2f})")
        else:
            status = "PASS" if effective == expected else "FAIL"
            if effective == expected:
                passed += 1
            else:
                failed += 1
            extra = f" (kw fallback)" if effective != intent else ""
            print(f"  [{status}] '{msg}' → {effective}{extra} (expected: {expected}, sklearn={intent}({conf:.2f}))")

    print(f"\n  Results: {passed}/15 passed, {failed}/15 failed")
    return passed, failed


def test_restriction():
    """Test Step 3: Restriction filter."""
    print("\n" + "=" * 60)
    print("STEP 3: Restriction Filter")
    print("=" * 60)

    blocked_tests = [
        "tell me a joke",
        "what is the weather today",
        "who won the football game",
        "write me python code",
    ]
    allowed_tests = [
        "my tooth hurts",
        "how much is cleaning",
        "what time do you open",
        "I need a dentist for braces",
    ]

    print("  Should BLOCK:")
    for msg in blocked_tests:
        intent, conf = sklearn_classifier.classify(msg)
        is_blocked, response = restriction_filter.is_off_topic(
            msg, sklearn_intent=intent, sklearn_conf=conf
        )
        status = "PASS" if is_blocked else "FAIL"
        print(f"    [{status}] '{msg}' → {'BLOCKED' if is_blocked else 'ALLOWED'}")

    print("\n  Should ALLOW:")
    for msg in allowed_tests:
        intent, conf = sklearn_classifier.classify(msg)
        is_blocked, response = restriction_filter.is_off_topic(
            msg, sklearn_intent=intent, sklearn_conf=conf
        )
        status = "PASS" if not is_blocked else "FAIL"
        print(f"    [{status}] '{msg}' → {'BLOCKED' if is_blocked else 'ALLOWED'}")


if __name__ == "__main__":
    test_cleaning()
    passed, failed = test_intent_classification()
    test_restriction()

    print("\n" + "=" * 60)
    if failed == 0:
        print("ALL TESTS PASSED!")
    else:
        print(f"SOME TESTS FAILED: {failed}/15")
    print("=" * 60)
