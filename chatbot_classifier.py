"""
Chatbot Intent Classifier.
Classifies user messages into: booking, reschedule, cancel, or None (general).
Uses keyword/phrase matching on spell-corrected text.
"""
import re


# ── BOOKING PHRASES ──
BOOKING_PHRASES = [
    # Direct booking commands
    r"\bbook\s+(an?\s+)?(appointment|visit|service|slot|time|consultation)\b",
    r"\b(make|schedule|set\s*up|reserve|get|create)\s+(an%s\s+)%s(appointment|visit|service|booking|slot|time|reservation|consultation)\b",
    r"\bbook\s+(me\s+)?(in|now)\b",
    r"\b(schedule|put)\s+me\b",
    r"\bsign\s+me\s+up\b",
    r"\badd\s+me\s+to\s+(the\s+)?(schedule|calendar)\b",
    # "I want/need to book"
    r"\bi\s+(want|need|would\s+like|'?d\s+like)\s+to\s+(book|schedule|make|reserve|set)\b",
    r"\bi\s+(want|need|would\s+like|'?d\s+like)\s+(an?\s+)?(appointment|booking|visit|slot|consultation)\b",
    # "Can I book"
    r"\b(can|could|may)\s+i\s+(book|schedule|make|reserve|come\s+in|visit)\b",
    # Slot/availability queries with booking intent
    r"\b(give|get)\s+me\s+(a\s+)?(slot|appointment|time|booking)\b",
    r"\bi\s+(want|need)\s+(a\s+)?(time|slot)\b",
    r"\bany\s+(available|open)\s+slots\b",
    r"\b(do\s+you\s+have|what)\s+(availability|times?\s+available|slots?\s+available)\b",
    r"\bwhen\s+(can\s+i\s+come|are\s+you\s+free|is\s+the\s+next)\b",
    r"\b(earliest|next\s+available)\s+(appointment|slot)\b",
    r"\bany\s+(time|availability)\s+(available\s+)?(today|tomorrow|this\s+week)\b",
    r"\bi\s+want\s+to\s+come\s+(today|tomorrow|this\s+week)\b",
    # Service-specific booking
    r"\b(book|schedule|i\s+want)\s+(a\s+)?(cleaning|checkup|check-?up|consultation|treatment|extraction|whitening|braces|filling|crown|veneer|root\s+canal|x-?ray|scan)\b",
    # Simple booking
    r"\b(appointment|booking|schedule)\s+please\b",
    r"\b(help\s+me\s+)?(book|schedule)\b(?!.*\b(cancel|reschedule|change|move)\b)",
    # Quick/instant booking
    r"\b(simple|quick|instant)\s+booking\b",
]

# ── RESCHEDULE PHRASES ──
RESCHEDULE_PHRASES = [
    # Direct reschedule
    r"\breschedul\w*\b",
    r"\bresc\w*dul\w*\b",
    r"\bresch\w*ule\b",
    r"\breshc\w*ule\b",
    r"\breschd\w+\b",
    r"\bresche\w*dle\b",
    r"\breshe\w*ule\b",
    r"\brese\w*ule\b",
    r"\bpostpone\b",
    # Change/move/modify/edit/shift/update appointment
    r"\b(change|move|modify|edit|shift|update|switch)\s+(my\s+|the\s+)%s(app\w+|apo\w+|booking|reservation|visit)\b",
    # "I want/need/can I reschedule/change"
    r"\b(i\s+)?(want|need|would\s+like)\s+to\s+(reschedul\w*|change|move|modify|shift)\s+(my\s+|the\s+)?(app\w+|booking|visit)?\b",
    r"\b(can|could|may)\s+i\s+(reschedul\w*|change|move|modify|shift)\s+(my\s+|the\s+)?(app\w+|booking|visit|time|date)?\b",
    # Change time/date
    r"\b(change|switch)\s+(my\s+|the\s+)?(time|date|day|slot)\b",
    r"\b(different|another|new)\s+(time|date|day|slot|timing)\b",
    r"\bi\s+(want|need)\s+(a\s+)?(different|another|new)\s+(time|date|day|slot)\b",
    # Can't make it / busy (NOT "come" — that's cancel)
    r"\b(can'?t|cannot|won'?t|will\s+not)\s+(make\s+it|attend)\b",
    r"\b(can'?t|cannot|won'?t|will\s+not)\s+be\s+able\s+to\s+(come|make\s+it|attend)\b",
    r"\bsomething\s+came\s+up\b",
    r"\bneed\s+a\s+new\s+time\b",
    # "move it to", "switch to another day"
    r"\b(move|switch)\s+(it\s+)?to\s+(another|next|a\s+different)\b",
    r"\bcome\s+.{0,20}\binstead\b",
    # "doesn't work", "busy at that time"
    r"(doesn'?t|does\s+not|won'?t)\s+work",
    r"\b(busy|unavailable)\s+(at|on|during)\s+(that|this|the)\s+(time|date|day)\b",
    r"\bnot\s+this\s+(time|slot|day)\b",
    # Short contextual
    r"\b(change|move|reschedule)\s+it\b",
    # Cancel and rebook = reschedule
    r"\bcancel\s+and\s+(book|rebook|re-?book|reschedule|make\s+a?\s*new)\b",
]

# ── CANCEL PHRASES ──
CANCEL_PHRASES = [
    # Direct cancel
    r"\b(cancel|delete|remove)\s+(my\s+|the\s+)%s(app\w+|apo\w+|booking|reservation|visit|slot)\b",
    r"\b(cancel|delete|remove)\s+(my\s+|the\s+)%s(appointment|booking)\b",
    # "I want/need to cancel"
    r"\bi\s+(want|need|would\s+like)\s+to\s+(cancel|delete|remove)\b",
    r"\bplease\s+(cancel|delete|remove)\b",
    # Stop/end appointment
    r"\b(stop|end)\s+(my\s+|the\s+)?(appointment|booking)\b",
    # Won't come
    r"\bi\s+(won'?t|will\s+not|am\s+not)\s+(come|coming|go|going|attend)\b",
    r"\bi\s+(can'?t|cannot)\s+(come|go|attend)\s+(anymore|any\s+more)\b",
    r"\bi\s+don'?t\s+need\s+the\s+appointment\b",
]


def classify(text):
    """
    Classify user message intent.

    Args:
        text: The spell-corrected user message

    Returns:
        str: "booking", "reschedule", "cancel", or None
    """
    lower = text.strip().lower()

    if not lower or len(lower) < 2:
        return None

    # Check reschedule FIRST (before booking, since reschedule messages
    # often contain words like "appointment" that could match booking)
    for pattern in RESCHEDULE_PHRASES:
        if re.search(pattern, lower):
            # Make sure it's not "cancel and rebook" which is reschedule
            return "reschedule"

    # Check cancel
    for pattern in CANCEL_PHRASES:
        if re.search(pattern, lower):
            # "cancel and book again" = reschedule
            if re.search(r'cancel\s+and\s+(book|rebook|re-book|reschedule|make\s+a?\s*new)', lower):
                return "reschedule"
            return "cancel"

    # Check booking LAST
    for pattern in BOOKING_PHRASES:
        if re.search(pattern, lower):
            return "booking"

    return None
