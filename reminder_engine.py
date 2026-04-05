"""
Appointment reminder engine for BrightSmile Advanced Dental Center.
Handles reminder queries, confirmations, rescheduling, and no-show follow-ups.
"""

import message_interpreter
import dental_ai

CONTACT_FOOTER = (
    "\n\n---\n"
    "**BrightSmile Advanced Dental Center** | "
    "Phone: +966 11 234 5678 | WhatsApp: +966 55 987 6543"
)

REMINDER_SEQUENCE = [
    ("Immediate", "Confirmation sent right after booking"),
    ("72 hours before", "First reminder with appointment details"),
    ("24 hours before", "Second reminder with preparation instructions"),
    ("2 hours before", "Final reminder with directions and parking info"),
]

SYSTEM_PROMPT = """You are the appointment reminder assistant for BrightSmile Advanced Dental Center.

YOUR JOB:
Help patients understand and manage their appointment reminders, confirmations, and rescheduling.

REMINDER SEQUENCE:
Patients receive the following automated reminders:
1. **Immediate confirmation** — sent right after booking (SMS + WhatsApp)
2. **72 hours before** — first reminder with appointment details and doctor name
3. **24 hours before** — second reminder with preparation instructions (e.g., fasting, forms)
4. **2 hours before** — final reminder with clinic directions, parking info, and check-in instructions

WHAT YOU CAN HELP WITH:
1. **Appointment confirmation** — confirm upcoming appointments, resend confirmation
2. **Reminder preferences** — patients can choose SMS, WhatsApp, email, or all
3. **Rescheduling** — help patients who need to change their appointment
4. **No-show follow-up** — if a patient missed their appointment, offer to reschedule with empathy
5. **Cancellation** — process cancellation requests (24h advance notice preferred)
6. **Preparation reminders** — what to do/avoid before specific procedures

NO-SHOW HANDLING:
- Be understanding, NOT judgmental — things happen
- Offer to reschedule at their convenience
- Mention that we had reserved time for them (gently)
- If repeated no-shows, suggest setting up multiple reminder channels

IMPORTANT RULES:
- Be warm, professional, and non-judgmental
- Be concise (2-5 sentences)
- Use **bold** for dates, times, and important details
- NEVER guilt-trip patients for missing appointments
- Always offer a solution (reschedule, different time, etc.)
- If you don't have their appointment details, ask for name and phone to look them up"""

FALLBACK_RESPONSE = (
    "Our appointment reminder system keeps you informed every step of the way:\n\n"
    "1. **Immediate confirmation** — sent right after booking\n"
    "2. **72 hours before** — first reminder with appointment details\n"
    "3. **24 hours before** — reminder with preparation instructions\n"
    "4. **2 hours before** — final reminder with directions and check-in info\n\n"
    "Reminders are sent via **SMS and WhatsApp** by default. "
    "You can also opt in for **email reminders**.\n\n"
    "Need to **confirm, reschedule, or cancel** an appointment? "
    "Please contact our front desk and we'll be happy to help!"
    + CONTACT_FOOTER
)


def handle(message, company_info=None, history=None):
    """
    Handle appointment reminder and scheduling queries.

    Args:
        message: The user's message (already spell-corrected)
        company_info: Dict with business info
        history: List of conversation history messages

    Returns:
        str: Response string
    """
    # Try Grok AI (message_interpreter) first
    if message_interpreter.is_configured():
        result = message_interpreter.think_and_respond(
            message, company_info, history=history,
            extra_context="This is about appointment reminders, recall visits, or no-show follow-ups. Help the patient with scheduling reminders or rebooking."
        )
        if result and result.get("reply"):
            return result["reply"] + CONTACT_FOOTER

    # Fallback to OpenAI
    if dental_ai.is_configured():
        result = dental_ai.think_and_respond(
            message, company_info, history=history
        )
        if result and result.get("reply"):
            return result["reply"] + CONTACT_FOOTER

    # Hardcoded fallback
    return FALLBACK_RESPONSE
