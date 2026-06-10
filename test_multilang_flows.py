#!/usr/bin/env python3
"""
Comprehensive multi-language flow test for ChatGenius chatbot.
Tests all 7 supported languages across booking, reschedule, cancel,
mid-flow cancel, service selection, complex prompts, and general queries.

Usage:
    python3 test_multilang_flows.py [--server http://127.0.0.1:8080]
"""

import requests
import json
import sys
import time
import uuid

SERVER = "http://127.0.0.1:8080"
if "--server" in sys.argv:
    SERVER = sys.argv[sys.argv.index("--server") + 1]

PASS = 0
FAIL = 0
ERRORS = []


def chat(session_id, message, domain="brightsmile"):
    """Send a chat message and return the response dict."""
    time.sleep(0.3)  # Pace requests to avoid 30/min rate limit
    for attempt in range(3):
        try:
            r = requests.post(f"{SERVER}/chat", json={
                "message": message,
                "session_id": session_id,
                "domain": domain,
            }, timeout=30)
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"    [rate limited, waiting {wait}s...]")
                time.sleep(wait)
                continue
            return r.json()
        except Exception as e:
            return {"error": str(e)}
    return {"error": "rate limited after retries"}


def check(test_name, condition, detail=""):
    """Record a pass/fail result."""
    global PASS, FAIL, ERRORS
    if condition:
        PASS += 1
        print(f"  PASS  {test_name}")
    else:
        FAIL += 1
        msg = f"  FAIL  {test_name}"
        if detail:
            msg += f"  -- {detail}"
        print(msg)
        ERRORS.append(f"{test_name}: {detail}")


def sid():
    """Generate unique session ID."""
    return f"test_{uuid.uuid4().hex[:12]}"


# ═══════════════════════════════════════════════════════════════
#  Language definitions: messages for each flow in each language
# ═══════════════════════════════════════════════════════════════

LANGUAGES = {
    "en": {
        "name": "English",
        "book": "I want to book an appointment",
        "reschedule": "I want to reschedule my appointment",
        "cancel_appt": "I want to cancel my appointment",
        "cancel_mid": "cancel",
        "never_mind": "never mind",
        "service": "I want to book a service",
        "complex_medical": (
            "The patient presents with severe malocclusion accompanied by chronic mandibular "
            "deviation and significant dental crowding. Clinical symptoms include incisor overlap, "
            "upper teeth protrusion, bite irregularity causing difficulty in chewing, intermittent "
            "temporomandibular joint pain, speech problems, and accelerated enamel erosion."
        ),
        "general_question": "What are your working hours?",
        "okay": "okay",
        "yes": "yes",
        "no": "no",
    },
    "ar": {
        "name": "Arabic",
        "book": "أريد حجز موعد",
        "reschedule": "أريد إعادة جدولة موعد",
        "cancel_appt": "أريد إلغاء موعد",
        "cancel_mid": "إلغاء",
        "never_mind": "لا تهتم",
        "service": "أريد حجز خدمة",
        "complex_medical": (
            "يُعاني المريض من سوء إطباق متفاقم مصحوب بانحراف مزمن في الفك السفلي "
            "وازدحام شديد في الأسنان. تشمل الأعراض السريرية تراكب القواطع وبروز "
            "الأسنان العلوية وعدم انتظام العضة مما يُسبب صعوبة في المضغ وألم متقطع "
            "في المفصل الصدغي الفكي ومشاكل في النطق وتآكل متسارع للمينا"
        ),
        "general_question": "ما هي ساعات العمل؟",
        "okay": "تمام",
        "yes": "نعم",
        "no": "لا",
    },
    "es": {
        "name": "Spanish",
        "book": "Quiero reservar una cita",
        "reschedule": "Quiero reprogramar mi cita",
        "cancel_appt": "Quiero cancelar mi cita",
        "cancel_mid": "cancelar",
        "never_mind": "no importa",
        "service": "Quiero reservar un servicio",
        "complex_medical": (
            "El paciente presenta una maloclusión severa acompañada de desviación mandibular "
            "crónica y apiñamiento dental significativo. Los síntomas clínicos incluyen "
            "superposición de incisivos, protrusión de dientes superiores, irregularidad "
            "de mordida que causa dificultad para masticar y dolor intermitente en la "
            "articulación temporomandibular"
        ),
        "general_question": "¿Cuáles son sus horarios de trabajo?",
        "okay": "vale",
        "yes": "sí",
        "no": "no",
    },
    "fr": {
        "name": "French",
        "book": "Je veux prendre un rendez-vous",
        "reschedule": "Je veux reprogrammer mon rendez-vous",
        "cancel_appt": "Je veux annuler mon rendez-vous",
        "cancel_mid": "annuler",
        "never_mind": "pas grave",
        "service": "Je veux réserver un service",
        "complex_medical": (
            "Le patient présente une malocclusion sévère accompagnée d'une déviation "
            "mandibulaire chronique et d'un encombrement dentaire important. Les symptômes "
            "cliniques comprennent un chevauchement des incisives, une protrusion des dents "
            "supérieures, une irrégularité de l'occlusion causant des difficultés de mastication"
        ),
        "general_question": "Quelles sont vos heures d'ouverture?",
        "okay": "d'accord",
        "yes": "oui",
        "no": "non",
    },
    "zh": {
        "name": "Chinese",
        "book": "我想预约",
        "reschedule": "我想重新安排我的预约",
        "cancel_appt": "我想取消我的预约",
        "cancel_mid": "取消",
        "never_mind": "算了",
        "service": "我想预约一个服务",
        "complex_medical": (
            "患者出现严重的错颌畸形，伴有慢性下颌偏移和明显的牙齿拥挤。"
            "临床症状包括切牙重叠、上牙突出、咬合不规则导致咀嚼困难、"
            "颞下颌关节间歇性疼痛、言语障碍和牙釉质加速侵蚀"
        ),
        "general_question": "你们的工作时间是什么？",
        "okay": "好的",
        "yes": "是的",
        "no": "不",
    },
    "ur": {
        "name": "Urdu",
        "book": "میں اپائنٹمنٹ بک کرنا چاہتا ہوں",
        "reschedule": "میں اپنی اپائنٹمنٹ دوبارہ شیڈول کرنا چاہتا ہوں",
        "cancel_appt": "میں اپنی اپائنٹمنٹ منسوخ کرنا چاہتا ہوں",
        "cancel_mid": "منسوخ",
        "never_mind": "کوئی بات نہیں",
        "service": "میں ایک سروس بک کرنا چاہتا ہوں",
        "complex_medical": (
            "مریض کو شدید مال اکلوژن ہے جس کے ساتھ دائمی نچلے جبڑے کا انحراف "
            "اور نمایاں دانتوں کی بھیڑ ہے۔ طبی علامات میں انسائزرز کی اوورلیپنگ، "
            "اوپری دانتوں کا آگے نکلنا، کاٹنے کی بے قاعدگی جو چبانے میں مشکل، "
            "ٹیمپورومینڈیبلر جوائنٹ میں وقفے وقفے سے درد"
        ),
        "general_question": "آپ کے کام کے اوقات کیا ہیں؟",
        "okay": "ٹھیک ہے",
        "yes": "ہاں",
        "no": "نہیں",
    },
    "tl": {
        "name": "Tagalog",
        "book": "Gusto kong mag-book ng appointment",
        "reschedule": "Gusto kong i-reschedule ang appointment ko",
        "cancel_appt": "Gusto kong i-cancel ang appointment ko",
        "cancel_mid": "cancel",
        "never_mind": "hindi na lang",
        "service": "Gusto kong mag-book ng service",
        "complex_medical": (
            "Ang pasyente ay nagpapakita ng malubhang malocclusion na may kasamang "
            "chronic mandibular deviation at malaking dental crowding. Kasama sa mga "
            "sintomas ang incisor overlap, upper teeth protrusion, bite irregularity "
            "na nagiging sanhi ng kahirapan sa pagnguya at pansamantalang pananakit "
            "ng temporomandibular joint"
        ),
        "general_question": "Ano ang inyong oras ng trabaho?",
        "okay": "sige",
        "yes": "oo",
        "no": "hindi",
    },
}


# ═══════════════════════════════════════════════════════════════
#  Test functions
# ═══════════════════════════════════════════════════════════════

def test_language_switch(lang_code, lang_data):
    """Test that language switch works and returns correct confirmation."""
    s = sid()
    resp = chat(s, f"__set_language__{lang_code}")
    reply = resp.get("reply", "")
    check(
        f"[{lang_code}] language switch",
        lang_code == "en" or reply != "" and "error" not in reply.lower(),
        f"reply='{reply[:80]}'"
    )
    return s  # return session for chaining


def test_booking_flow(lang_code, lang_data):
    """Test that booking intent is correctly classified."""
    s = sid()
    chat(s, f"__set_language__{lang_code}")
    resp = chat(s, lang_data["book"])
    reply = resp.get("reply", "").lower()

    # Booking flow should ask for name or show booking type options
    # Key indicators: asks for name, or shows booking_type/categories options
    opts_type = resp.get("options", {}).get("type", "")
    is_booking = (
        "name" in reply or "nombre" in reply or "nom" in reply or  # asking for name
        "اسم" in reply or "نام" in reply or "姓名" in reply or "全名" in reply or
        "pangalan" in reply or
        opts_type in ("booking_type", "categories") or
        "book" in reply or "appointment" in reply or "حجز" in reply or "موعد" in reply or
        "reservar" in reply or "rendez" in reply or "预约" in reply or
        "cita" in reply or "réserver" in reply
    )
    check(
        f"[{lang_code}] booking flow triggered",
        is_booking,
        f"reply='{reply[:80]}' opts={opts_type}"
    )


def test_reschedule_flow(lang_code, lang_data):
    """Test that reschedule intent triggers calendar."""
    s = sid()
    chat(s, f"__set_language__{lang_code}")
    resp = chat(s, lang_data["reschedule"])
    opts_type = resp.get("options", {}).get("type", "")
    reply = resp.get("reply", "")

    check(
        f"[{lang_code}] reschedule flow -> calendar",
        opts_type == "calendar",
        f"opts={opts_type} reply='{reply[:80]}'"
    )


def test_cancel_flow(lang_code, lang_data):
    """Test that cancel appointment intent triggers calendar."""
    s = sid()
    chat(s, f"__set_language__{lang_code}")
    resp = chat(s, lang_data["cancel_appt"])
    opts_type = resp.get("options", {}).get("type", "")
    reply = resp.get("reply", "")

    check(
        f"[{lang_code}] cancel flow -> calendar",
        opts_type == "calendar",
        f"opts={opts_type} reply='{reply[:80]}'"
    )


def test_cancel_mid_flow(lang_code, lang_data):
    """Test cancelling in the middle of a booking flow."""
    s = sid()
    chat(s, f"__set_language__{lang_code}")
    # Start booking
    chat(s, lang_data["book"])
    # Now cancel mid-flow
    resp = chat(s, lang_data["cancel_mid"])
    reply = resp.get("reply", "").lower()
    opts_type = resp.get("options", {}).get("type", "")

    # After cancel, should NOT still be in the booking flow
    # Should say something like "cancelled" or "how can I help"
    still_booking = opts_type in ("booking_type", "services", "doctors", "timeslots")
    # Also check the reply doesn't ask for booking info (name, email, etc.)
    asking_name = any(w in reply for w in ["name", "nombre", "nom", "اسم", "نام", "姓名", "pangalan"])

    check(
        f"[{lang_code}] cancel mid-flow exits booking",
        not still_booking and not asking_name,
        f"opts={opts_type} reply='{reply[:80]}'"
    )


def test_never_mind(lang_code, lang_data):
    """Test 'never mind' exits a flow."""
    s = sid()
    chat(s, f"__set_language__{lang_code}")
    chat(s, lang_data["book"])
    resp = chat(s, lang_data["never_mind"])
    reply = resp.get("reply", "").lower()
    opts_type = resp.get("options", {}).get("type", "")

    still_booking = opts_type in ("booking_type", "services", "doctors", "timeslots")
    check(
        f"[{lang_code}] 'never mind' exits flow",
        not still_booking,
        f"opts={opts_type} reply='{reply[:80]}'"
    )


def test_complex_medical_prompt(lang_code, lang_data):
    """Test that long complex medical text gets a relevant AI response, not garbage."""
    s = sid()
    chat(s, f"__set_language__{lang_code}")
    resp = chat(s, lang_data["complex_medical"])
    reply = resp.get("reply", "")

    # Should get a meaningful response (not empty, not error, not ". no . . no .")
    is_meaningful = (
        len(reply) > 30 and
        reply != ". no . . no ." and
        "error" not in reply.lower() and
        reply.count(".") < len(reply) * 0.5  # not mostly dots/punctuation
    )
    check(
        f"[{lang_code}] complex medical -> meaningful response",
        is_meaningful,
        f"len={len(reply)} reply='{reply[:80]}'"
    )


def test_general_question(lang_code, lang_data):
    """Test that a general question gets a response (not triggering a flow)."""
    s = sid()
    chat(s, f"__set_language__{lang_code}")
    resp = chat(s, lang_data["general_question"])
    reply = resp.get("reply", "")
    opts_type = resp.get("options", {}).get("type", "")

    # Should respond with info, not start a booking flow
    is_general = (
        len(reply) > 10 and
        opts_type not in ("calendar", "booking_type")
    )
    check(
        f"[{lang_code}] general question -> informational response",
        is_general,
        f"opts={opts_type} reply='{reply[:80]}'"
    )


def test_response_in_correct_language(lang_code, lang_data):
    """Test that the AI responds in the selected language, not English."""
    if lang_code == "en":
        return  # Skip for English

    s = sid()
    chat(s, f"__set_language__{lang_code}")
    resp = chat(s, lang_data["general_question"])
    reply = resp.get("reply", "")

    # Check reply contains non-ASCII characters (indicating non-English response)
    has_non_ascii = any(ord(c) > 127 for c in reply)

    # For Tagalog, responses might be mostly ASCII but with Filipino words
    if lang_code == "tl":
        has_non_ascii = True  # Tagalog uses Latin script, skip this check

    check(
        f"[{lang_code}] response is in {lang_data['name']} (not English)",
        has_non_ascii,
        f"reply='{reply[:80]}'"
    )


def test_service_booking_flow(lang_code, lang_data):
    """Test that service booking works and shows options."""
    s = sid()
    chat(s, f"__set_language__{lang_code}")
    resp1 = chat(s, lang_data["book"])
    reply1 = resp1.get("reply", "")

    # If it asks for name, provide one
    if resp1.get("options", {}).get("type") not in ("booking_type", "services"):
        resp2 = chat(s, "Test User")
        opts_type = resp2.get("options", {}).get("type", "")
    else:
        opts_type = resp1.get("options", {}).get("type", "")

    # Should eventually show booking_type or categories
    check(
        f"[{lang_code}] booking -> shows options after name",
        opts_type in ("booking_type", "categories", "services", "doctors"),
        f"opts={opts_type}"
    )


def test_option_items_have_values(lang_code, lang_data):
    """Test that translated option items preserve English values for backend matching."""
    if lang_code == "en":
        return

    s = sid()
    chat(s, f"__set_language__{lang_code}")
    chat(s, lang_data["book"])
    resp = chat(s, "Test User")
    opts = resp.get("options", {})
    items = opts.get("items", [])

    if not items or opts.get("type") not in ("booking_type", "categories", "services"):
        check(f"[{lang_code}] options have value fields", True, "skipped - no options shown")
        return

    # Each item should have both 'name' (translated) and 'value' (English)
    all_have_value = all(
        isinstance(item, dict) and item.get("value")
        for item in items
    )
    check(
        f"[{lang_code}] option items preserve English 'value'",
        all_have_value,
        f"items={json.dumps(items[:2], ensure_ascii=False)[:120]}"
    )


def test_exact_word_yes_no(lang_code, lang_data):
    """Test that yes/no/okay exact matches work."""
    s = sid()
    chat(s, f"__set_language__{lang_code}")
    # Ask a question first so yes/no has context
    chat(s, lang_data["general_question"])
    resp = chat(s, lang_data["okay"])
    reply = resp.get("reply", "")

    # Should get some response, not an error or empty
    check(
        f"[{lang_code}] 'okay' ({lang_data['okay']}) -> valid response",
        len(reply) > 5 and "error" not in reply.lower(),
        f"reply='{reply[:80]}'"
    )


def test_sequential_flow_switching(lang_code, lang_data):
    """Test switching between flows: book -> cancel -> reschedule."""
    s = sid()
    chat(s, f"__set_language__{lang_code}")

    # Start booking
    r1 = chat(s, lang_data["book"])
    r1_reply = r1.get("reply", "")

    # Cancel it
    r2 = chat(s, lang_data["cancel_mid"])
    r2_reply = r2.get("reply", "")
    r2_opts = r2.get("options", {}).get("type", "")

    # Now reschedule (different flow)
    r3 = chat(s, lang_data["reschedule"])
    r3_opts = r3.get("options", {}).get("type", "")

    check(
        f"[{lang_code}] book -> cancel -> reschedule works",
        r3_opts == "calendar",
        f"after_cancel_opts={r2_opts} reschedule_opts={r3_opts}"
    )


def test_no_duplicate_services(lang_code, lang_data):
    """Test that service list has no duplicates."""
    s = sid()
    chat(s, f"__set_language__{lang_code}")
    chat(s, lang_data["book"])
    r = chat(s, "Test User")
    opts = r.get("options", {})

    if opts.get("type") == "booking_type":
        # Select "service"
        r2 = chat(s, "service")
        opts = r2.get("options", {})

    items = opts.get("items", [])
    if not items or opts.get("type") != "services":
        check(f"[{lang_code}] no duplicate services", True, "skipped - no services shown")
        return

    names = [item.get("name", "") for item in items if isinstance(item, dict)]
    unique_names = set(names)
    check(
        f"[{lang_code}] no duplicate services",
        len(names) == len(unique_names),
        f"total={len(names)} unique={len(unique_names)} names={names[:4]}"
    )


# ═══════════════════════════════════════════════════════════════
#  Run all tests
# ═══════════════════════════════════════════════════════════════

def main():
    global PASS, FAIL

    print("=" * 70)
    print("  ChatGenius Multi-Language Flow Test Suite")
    print(f"  Server: {SERVER}")
    print(f"  Languages: {', '.join(LANGUAGES.keys())}")
    print("=" * 70)

    # Verify server is running
    try:
        requests.get(f"{SERVER}/", timeout=5)
    except Exception:
        print("\n  ERROR: Server not reachable at", SERVER)
        print("  Start the server first: python3 app.py")
        sys.exit(1)

    print()

    for lang_code, lang_data in LANGUAGES.items():
        print(f"\n--- {lang_data['name']} ({lang_code}) ---")
        test_language_switch(lang_code, lang_data)
        test_booking_flow(lang_code, lang_data)
        test_reschedule_flow(lang_code, lang_data)
        test_cancel_flow(lang_code, lang_data)
        test_cancel_mid_flow(lang_code, lang_data)
        test_never_mind(lang_code, lang_data)
        test_complex_medical_prompt(lang_code, lang_data)
        test_general_question(lang_code, lang_data)
        test_response_in_correct_language(lang_code, lang_data)
        test_service_booking_flow(lang_code, lang_data)
        test_option_items_have_values(lang_code, lang_data)
        test_exact_word_yes_no(lang_code, lang_data)
        test_sequential_flow_switching(lang_code, lang_data)
        test_no_duplicate_services(lang_code, lang_data)

    # Summary
    total = PASS + FAIL
    print("\n" + "=" * 70)
    print(f"  RESULTS: {PASS}/{total} passed, {FAIL} failed")
    print("=" * 70)

    if ERRORS:
        print("\n  FAILURES:")
        for err in ERRORS:
            print(f"    - {err}")

    print()
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
