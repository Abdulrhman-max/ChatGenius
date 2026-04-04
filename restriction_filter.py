"""
Restriction filter for BrightSmile Advanced Dental Center chatbot.
Blocks non-dental messages after intent detection.
Covers all 24 intents across all engines.
"""

ALLOWED_INTENTS = [
    # Booking Engine
    "book_appointment",
    # Calendar System
    "check_availability",
    # Pricing Database
    "pricing_info",
    "payment_financing",
    # Emergency Handler
    "emergency",
    # ChatGPT — symptom detection
    "symptom_detection",
    # Insurance Engine
    "insurance_verification",
    # Patient Intake Engine
    "patient_intake",
    # Contact/Callback Engine
    "contact_callback",
    # No-Show/Reminder Engine
    "noshow_reminders",
    # Grok AI — general dental
    "faq_general",
    "services_info",
    "treatment_education",
    "patient_recall",
    "promotions",
    "multilingual",
    "compliance",
    "pms_integration",
    "analytics",
    "multi_location",
    "office_hours",
    "oral_hygiene",
    "specialist_recommendation",
    "post_treatment",
    "general_dental",
]

BLOCKED_RESPONSE = (
    "I'm sorry, I can only assist with dental-related topics for BrightSmile "
    "Advanced Dental Center such as booking appointments, checking symptoms, "
    "dental services, pricing, insurance, office hours, and oral hygiene advice. "
    "For other inquiries please call us at +966 11 234 5678 or WhatsApp "
    "+966 55 987 6543. How can I assist you with your dental needs?"
)

# Keywords that indicate non-dental topics
_OFF_TOPIC_KEYWORDS = [
    "weather", "football", "soccer", "basketball", "baseball", "cricket",
    "stock", "bitcoin", "crypto", "politics", "election", "president",
    "recipe", "cook", "movie", "film", "song", "music", "game", "gaming",
    "code", "programming", "python", "javascript", "math", "equation",
    "homework", "essay", "history lesson", "geography",
    "joke", "tell me a joke", "funny", "riddle",
    "translate", "what language", "speak french",
    "restaurant", "hotel", "travel", "flight", "car rental",
]

# Keywords that are definitely dental (override off-topic detection)
_DENTAL_KEYWORDS = [
    "tooth", "teeth", "dental", "dentist", "doctor", "dr.", "appointment",
    "book", "schedule", "pain", "hurt", "ache", "cavity", "filling",
    "root canal", "crown", "bridge", "implant", "braces", "invisalign",
    "whitening", "cleaning", "extraction", "gum", "bleeding", "swollen",
    "jaw", "bite", "chew", "oral", "mouth", "tongue", "lip", "cheek",
    "wisdom", "veneer", "denture", "floss", "brush", "mouthwash",
    "clinic", "office", "hours", "price", "cost", "insurance", "payment",
    "emergency", "urgent", "specialist", "orthodont", "endodont", "periodon",
    "surgery", "x-ray", "xray", "checkup", "check-up", "consultation",
    "smile", "cosmetic", "pediatric", "child", "kid", "baby teeth",
    "abscess", "infection", "sensitivity", "sensitive", "numb",
    "brightsmile", "bright smile",
    "open", "close", "time", "hour", "schedule", "available", "availability",
    "hollywood", "bupa", "tawuniya", "medgulf", "allianz", "axa",
    "tabby", "tamara", "mada", "stc pay",
    "hurt", "swell", "swollen", "bleed", "broken", "crack", "chip",
    "loose", "numb", "tingling", "throb", "sharp", "dull",
    # New keywords for expanded features
    "intake", "form", "medical history", "allergy", "medication",
    "consent", "registration", "hipaa", "gdpr", "privacy",
    "callback", "call me", "contact me", "call back",
    "reminder", "no-show", "confirm", "cancel",
    "recall", "reactivation", "overdue", "checkup",
    "promotion", "offer", "discount", "special", "campaign",
    "financing", "installment", "payment plan", "carecredit",
    "upsell", "education", "treatment option",
    "pms", "dentrix", "eaglesoft", "open dental",
    "analytics", "dashboard", "report", "metrics",
    "multi-location", "dso", "branch", "location",
    "multilingual", "arabic", "language",
]


def check_restriction(intent):
    """Check if the detected intent is allowed."""
    if intent not in ALLOWED_INTENTS:
        return False, BLOCKED_RESPONSE
    return True, None


def is_off_topic(message, sklearn_intent=None, sklearn_conf=0.0):
    """
    Determine if a message is off-topic (non-dental).
    Uses a combination of intent confidence and keyword detection.

    Returns: (is_blocked, response_or_none)
    """
    lower = message.lower().strip()

    # If sklearn detected a dental intent with decent confidence, allow it
    if sklearn_intent and sklearn_conf > 0.45:
        allowed, _ = check_restriction(sklearn_intent)
        if allowed:
            return False, None

    # Check for dental keywords — if any are present, it's on-topic
    if any(kw in lower for kw in _DENTAL_KEYWORDS):
        return False, None

    # Check for off-topic keywords
    if any(kw in lower for kw in _OFF_TOPIC_KEYWORDS):
        return True, BLOCKED_RESPONSE

    # Low confidence on sklearn + no dental keywords = likely off-topic
    if sklearn_conf < 0.3:
        return True, BLOCKED_RESPONSE

    return False, None
