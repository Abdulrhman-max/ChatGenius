"""
Smart router for BrightSmile Advanced Dental Center chatbot.
Connects each sklearn intent to the correct AI engine.
Does NOT contain any new AI logic — purely a routing layer.
"""
import message_interpreter
import dental_ai
import claude_specialist
import dental_knowledge_engine as dke

CLINIC_CONTEXT = """
You are the virtual assistant for BrightSmile Advanced Dental Center.
Location: King Fahd Road, Al Olaya District, Riyadh, near Kingdom Centre Tower, 3rd Floor.
Phone: +966 11 234 5678 | WhatsApp: +966 55 987 6543 | Emergency 24/7: +966 50 111 2222
Hours: Sat-Thu 9AM-10PM | Fri 2PM-10PM | Emergency: 24/7
Doctors: Dr. Ahmed Al-Harbi (General Dentistry, 12 years), Dr. Sarah Al-Qahtani (Orthodontics, 10 years),
         Dr. Mohammed Al-Otaibi (Oral Surgery, 15 years), Dr. Lina Al-Salem (Pediatric Dentistry, 8 years),
         Dr. Khalid Al-Faisal (Cosmetic Dentistry, 11 years)
Prices in USD: Consultation $27 | Cleaning $67 | Filling $53-$107 | Root Canal $213-$400 |
               Extraction $80-$187 | Implant $800-$1,600 | Whitening $267-$480 |
               Braces $2,133-$4,000 | Veneers $320-$667 per tooth
Insurance: Bupa Arabia, Tawuniya, MedGulf, Allianz Saudi Fransi, AXA Cooperative
Payment: Cash, Visa, Mastercard, Mada, Apple Pay, STC Pay, Tabby, Tamara
"""

EMERGENCY_RESPONSE_PREFIX = (
    "**This sounds like a dental emergency!** Please call our emergency line "
    "immediately: **+966 50 111 2222** (available 24/7).\n\n"
)

CONTACT_FOOTER = (
    "\n\n---\n"
    "**BrightSmile Advanced Dental Center** | "
    "Phone: +966 11 234 5678 | WhatsApp: +966 55 987 6543"
)


def chatgpt_symptom_engine(message, doctors=None, history=None):
    """Route symptoms to Claude specialist (most accurate for medical triage)."""
    # Try Claude first
    if claude_specialist.is_configured():
        result = claude_specialist.analyze_symptoms(message, doctors=doctors, history=history)
        if result and result.get("reply"):
            return result["reply"] + CONTACT_FOOTER

    # Fallback to OpenAI
    if dental_ai.is_configured():
        result = dental_ai.think_and_respond(message, doctors=doctors, history=history)
        if result and result.get("reply"):
            return result["reply"] + CONTACT_FOOTER

    return None


def emergency_handler(message, doctors=None, history=None):
    """Handle emergency messages — always show emergency number."""
    ai_response = chatgpt_symptom_engine(message, doctors=doctors, history=history)
    if ai_response:
        return EMERGENCY_RESPONSE_PREFIX + ai_response
    return (
        EMERGENCY_RESPONSE_PREFIX
        + "In the meantime, rinse your mouth gently with warm salt water and "
        "avoid touching the affected area. If there is swelling, apply a cold "
        "compress to the outside of your cheek.\n\n"
        "You can also visit us during our regular hours: **Sat-Thu 9AM-10PM, Fri 2PM-10PM**."
        + CONTACT_FOOTER
    )


def grok_answer_engine(message, company_info=None, doctors=None,
                       doctor_slots=None, history=None):
    """Route general Q&A to Groq AI (message_interpreter)."""
    if message_interpreter.is_configured():
        result = message_interpreter.think_and_respond(
            message, company_info, doctors,
            doctor_slots=doctor_slots, history=history
        )
        if result and result.get("reply"):
            return result["reply"] + CONTACT_FOOTER

    # Fallback to OpenAI
    if dental_ai.is_configured():
        result = dental_ai.think_and_respond(
            message, company_info, doctors, history=history
        )
        if result and result.get("reply"):
            return result["reply"] + CONTACT_FOOTER

    return None


def pricing_lookup(message, company_info=None, doctors=None, history=None):
    """Route pricing questions — uses AI with clinic context."""
    return grok_answer_engine(message, company_info, doctors, history=history)


_EMERGENCY_KEYWORDS = [
    "swollen", "swelling", "bleeding", "broken", "knocked out", "abscess",
    "severe pain", "unbearable", "can't eat", "can't sleep", "jaw swollen",
    "face swollen", "pus", "fever", "emergency",
]

_SYMPTOM_KEYWORDS = [
    "hurt", "hurts", "pain", "ache", "aching", "sore", "throbbing",
    "sensitive", "sensitivity", "bleeding gum", "loose tooth",
    "tooth hurts", "toothache", "jaw pain", "gum pain",
]

_PRICING_KEYWORDS = [
    "cost", "price", "how much", "pricing", "fee", "charge", "expensive",
    "cheap", "afford", "dollar", "pay", "insurance", "bupa", "accept",
    "tawuniya", "medgulf", "allianz", "axa", "payment",
]

_HOURS_KEYWORDS = [
    "open", "close", "hours", "time", "when do you", "working hours",
    "office hours", "schedule", "saturday", "friday", "weekend",
]

_SERVICES_KEYWORDS = [
    "hollywood smile", "smile makeover", "veneer", "whitening service",
    "implant service", "what services", "do you offer", "treatments",
]

_HYGIENE_KEYWORDS = [
    "brush", "brushing", "floss", "flossing", "mouthwash", "rinse",
    "clean teeth", "oral hygiene", "how to brush", "how to floss",
]


def _detect_keyword_intent(message):
    """Fallback keyword detection when sklearn confidence is low."""
    lower = message.lower()

    # Emergency takes highest priority
    if any(kw in lower for kw in _EMERGENCY_KEYWORDS):
        return "emergency"

    # Symptom detection
    symptom_count = sum(1 for kw in _SYMPTOM_KEYWORDS if kw in lower)
    if symptom_count >= 1:
        return "emergency"

    # Pricing
    if any(kw in lower for kw in _PRICING_KEYWORDS):
        return "pricing_info"

    # Hours
    if any(kw in lower for kw in _HOURS_KEYWORDS):
        return "office_hours"

    # Services
    if any(kw in lower for kw in _SERVICES_KEYWORDS):
        return "services_info"

    # Hygiene
    if any(kw in lower for kw in _HYGIENE_KEYWORDS):
        return "oral_hygiene"

    return None


def route(sklearn_intent, sklearn_conf, message, context):
    """
    Route message to the correct engine based on sklearn intent.

    Args:
        sklearn_intent: detected intent string
        sklearn_conf: confidence score (0-1)
        message: cleaned user message
        context: dict with company_info, active_doctors, doctor_slots, history

    Returns: response string or None (to fall through to existing routing)
    """
    # Use keyword detection to override or supplement sklearn
    keyword_intent = _detect_keyword_intent(message)
    effective_intent = sklearn_intent

    if not sklearn_intent or sklearn_conf < 0.4:
        # Low confidence — use keyword fallback
        if keyword_intent:
            effective_intent = keyword_intent
        else:
            return None  # No confident classification, fall through
    else:
        # Even with good sklearn confidence, certain keyword intents override
        if keyword_intent in ("emergency", "pricing_info", "services_info") and sklearn_intent != keyword_intent:
            effective_intent = keyword_intent

    company_info = context.get("company_info")
    active_doctors = context.get("active_doctors", [])
    doctor_slots = context.get("doctor_slots", {})
    history = context.get("history", [])

    # Emergency — always show emergency number
    if effective_intent == "emergency":
        return emergency_handler(message, doctors=active_doctors, history=history)

    # Symptom/specialist detection
    if effective_intent == "specialist_recommendation":
        return chatgpt_symptom_engine(message, doctors=active_doctors, history=history)

    # Availability, services, office hours — Groq AI with full context
    if effective_intent in ("check_availability", "services_info", "office_hours"):
        return grok_answer_engine(
            message, company_info, active_doctors,
            doctor_slots=doctor_slots, history=history
        )

    # Pricing — dedicated lookup
    if effective_intent == "pricing_info":
        return pricing_lookup(message, company_info, active_doctors, history=history)

    # Oral hygiene, post-treatment, general dental — AI answer
    if effective_intent in ("oral_hygiene", "post_treatment", "general_dental"):
        return grok_answer_engine(
            message, company_info, active_doctors, history=history
        )

    return None
