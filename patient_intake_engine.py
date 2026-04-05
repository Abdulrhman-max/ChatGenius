"""
Patient intake and registration engine for BrightSmile Advanced Dental Center.
Guides patients through the intake process: forms, medical history, consent.
"""

import message_interpreter
import dental_ai

CONTACT_FOOTER = (
    "\n\n---\n"
    "**BrightSmile Advanced Dental Center** | "
    "Phone: +966 11 234 5678 | WhatsApp: +966 55 987 6543"
)

MEDICAL_FLAGS = [
    "blood thinners",
    "diabetes",
    "pregnancy",
    "latex allergy",
]

SYSTEM_PROMPT = """You are the patient intake assistant for BrightSmile Advanced Dental Center.

YOUR JOB:
Guide new and returning patients through the intake and registration process. Be thorough but friendly.

INTAKE FORMS REQUIRED:
1. **Patient Registration Form** — personal info, emergency contact, ID/Iqama
2. **Medical History Form** — current conditions, past surgeries, chronic illnesses
3. **Allergies & Medications** — all current medications, known allergies (drug, food, latex)
4. **Consent for Treatment** — general consent for examination and treatment
5. **Insurance Authorization** — insurance details and authorization for billing
6. **Dental History** — previous dental work, concerns, last visit date

MEDICAL CONDITIONS TO FLAG (require dentist review before treatment):
- **Blood thinners** (warfarin, aspirin, Xarelto, Eliquis) — affects bleeding during procedures
- **Diabetes** (Type 1 or 2) — affects healing and infection risk
- **Pregnancy** — limits X-rays, certain medications, and some procedures
- **Latex allergy** — requires latex-free gloves and equipment

HOW TO GUIDE PATIENTS:
- Ask one section at a time, don't overwhelm them
- If they mention any flagged condition, acknowledge it and reassure them we'll take precautions
- Explain WHY each form is needed (briefly)
- Let them know forms can be completed online, in-person, or via WhatsApp

IMPORTANT RULES:
- Be warm, patient, and non-judgmental about medical history
- NEVER provide medical advice — only collect information
- Be concise (2-5 sentences per response)
- Use **bold** for form names and important flags
- If they seem anxious, reassure them that all information is confidential"""

FALLBACK_RESPONSE = (
    "Welcome to **BrightSmile Advanced Dental Center**! To get you started, we'll need a few forms completed:\n\n"
    "1. **Patient Registration Form** — your personal and contact details\n"
    "2. **Medical History Form** — any current or past health conditions\n"
    "3. **Allergies & Medications** — anything you're currently taking or allergic to\n"
    "4. **Consent for Treatment** — standard consent for your visit\n"
    "5. **Insurance Authorization** — if using insurance coverage\n"
    "6. **Dental History** — your previous dental work and concerns\n\n"
    "You can complete these forms **online before your visit**, **in-person** at our front desk, "
    "or we can guide you through them via **WhatsApp**.\n\n"
    "**Important:** Please let us know if you are on blood thinners, have diabetes, "
    "are pregnant, or have a latex allergy — we'll take extra precautions for your safety."
    + CONTACT_FOOTER
)


def handle(message, company_info=None, history=None):
    """
    Handle patient intake and registration inquiries.

    Args:
        message: The user's message (already spell-corrected)
        company_info: Dict with business info
        history: List of conversation history messages

    Returns:
        str: Response string
    """
    # Check for flagged medical conditions in the message
    lower_msg = message.lower()
    flags_found = [flag for flag in MEDICAL_FLAGS if flag.replace(" ", "") in lower_msg.replace(" ", "")]

    extra_ctx = "This is a patient intake inquiry. Help with pre-visit forms, medical history, and first-visit preparation."
    if flags_found:
        extra_ctx += f" FLAGGED CONDITIONS detected: {', '.join(flags_found)}. Alert the patient to inform the doctor about these."

    # Try Grok AI (message_interpreter) first
    if message_interpreter.is_configured():
        result = message_interpreter.think_and_respond(
            message, company_info, history=history,
            extra_context=extra_ctx
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
