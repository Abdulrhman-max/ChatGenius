"""
Contact collection engine for BrightSmile Advanced Dental Center.
Conversationally collects patient contact details for callbacks and follow-ups.
"""

import message_interpreter
import dental_ai

CONTACT_FOOTER = (
    "\n\n---\n"
    "**BrightSmile Advanced Dental Center** | "
    "Phone: +966 11 234 5678 | WhatsApp: +966 55 987 6543"
)

CONTACT_FIELDS = [
    "full_name",
    "phone",
    "email",
    "preferred_contact_time",
    "reason",
    "preferred_method",  # call, WhatsApp, email
    "language",
]

SYSTEM_PROMPT = """You are the contact collection assistant for BrightSmile Advanced Dental Center.

YOUR JOB:
Conversationally collect the patient's contact details so our team can follow up. Be natural and friendly — don't make it feel like a form.

INFORMATION TO COLLECT:
1. **Full name**
2. **Phone number** (with country code, default +966 for Saudi Arabia)
3. **Email address** (optional but helpful)
4. **Preferred contact time** (morning, afternoon, evening, or specific time)
5. **Reason for contact** (appointment, question, complaint, follow-up, etc.)
6. **Preferred contact method** — phone call, WhatsApp, or email
7. **Language preference** — Arabic or English

HOW TO COLLECT:
- Ask for 1-2 pieces of information at a time, not all at once
- If they've already provided some info in their message, acknowledge it and ask for what's missing
- Confirm the details back to them before finishing
- Be conversational, not robotic

IMPORTANT RULES:
- Be warm and helpful
- Be concise (2-4 sentences per response)
- Use **bold** for field names when confirming
- If they seem in a hurry, collect just name and phone — the rest is optional
- NEVER pressure for information they don't want to share
- Thank them when they provide info"""

FALLBACK_RESPONSE = (
    "I'd love to help connect you with our team! Could you please share:\n\n"
    "- Your **full name**\n"
    "- **Phone number** (we'll default to +966 country code)\n"
    "- **Preferred contact method** — phone call, WhatsApp, or email?\n"
    "- **Best time to reach you** — morning, afternoon, or evening?\n\n"
    "And if you could briefly share the **reason for your inquiry**, "
    "we'll make sure the right person gets back to you!"
    + CONTACT_FOOTER
)


def handle(message, company_info=None, history=None):
    """
    Handle contact collection conversations.

    Args:
        message: The user's message (already spell-corrected)
        company_info: Dict with business info
        history: List of conversation history messages

    Returns:
        str: Response string
    """
    enriched_prompt = f"[Contact collection] {message}"

    # Try Grok AI (message_interpreter) first
    if message_interpreter.is_configured():
        result = message_interpreter.think_and_respond(
            enriched_prompt, company_info, history=history
        )
        if result and result.get("reply"):
            return result["reply"] + CONTACT_FOOTER

    # Fallback to OpenAI
    if dental_ai.is_configured():
        result = dental_ai.think_and_respond(
            enriched_prompt, company_info, history=history
        )
        if result and result.get("reply"):
            return result["reply"] + CONTACT_FOOTER

    # Hardcoded fallback
    return FALLBACK_RESPONSE
