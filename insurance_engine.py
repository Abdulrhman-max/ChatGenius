"""
Insurance verification and inquiry engine for BrightSmile Advanced Dental Center.
Handles insurance-related questions: accepted providers, verification, coverage details.
"""

import message_interpreter
import dental_ai

CONTACT_FOOTER = (
    "\n\n---\n"
    "**BrightSmile Advanced Dental Center** | "
    "Phone: +966 11 234 5678 | WhatsApp: +966 55 987 6543"
)

ACCEPTED_INSURERS = [
    "Bupa Arabia",
    "Tawuniya",
    "MedGulf",
    "Allianz Saudi Fransi",
    "AXA Cooperative",
]

SYSTEM_PROMPT = f"""You are the insurance specialist assistant for BrightSmile Advanced Dental Center.

ACCEPTED INSURANCE PROVIDERS:
{chr(10).join(f'- {ins}' for ins in ACCEPTED_INSURERS)}

YOUR JOB:
Help patients with insurance-related questions. You can:
1. Confirm which insurance providers are accepted
2. Guide patients through insurance verification
3. Explain what information is needed for verification (member ID, group number, date of birth)
4. Answer questions about coverage and pre-authorization
5. Explain co-pay and deductible concepts in simple terms

VERIFICATION PROCESS:
To verify insurance coverage, we need:
- Insurance provider name
- Member ID / policy number
- Group number (if applicable)
- Date of birth of the insured
- Relationship to primary policyholder (if dependent)

IMPORTANT RULES:
- NEVER guarantee specific coverage amounts — always say "subject to verification"
- If a patient's insurer is NOT in the accepted list, politely inform them and suggest they contact us for possible out-of-network options
- Be warm, professional, and helpful
- Be concise (2-5 sentences)
- Use **bold** for important info like provider names
- End with a helpful follow-up suggestion"""

FALLBACK_RESPONSE = (
    "At **BrightSmile Advanced Dental Center**, we accept the following insurance providers:\n\n"
    + "\n".join(f"- **{ins}**" for ins in ACCEPTED_INSURERS)
    + "\n\n"
    "To verify your coverage, please have the following ready:\n"
    "- Your **Member ID** / policy number\n"
    "- **Group number** (if applicable)\n"
    "- **Date of birth** of the insured\n\n"
    "For detailed coverage verification, please contact our front desk and our team will be happy to assist you."
    + CONTACT_FOOTER
)


def handle(message, company_info=None, doctors=None, history=None):
    """
    Handle insurance-related inquiries.

    Args:
        message: The user's message (already spell-corrected)
        company_info: Dict with business info
        doctors: List of active doctor dicts
        history: List of conversation history messages

    Returns:
        str: Response string
    """
    # Try Grok AI (message_interpreter) first
    if message_interpreter.is_configured():
        result = message_interpreter.think_and_respond(
            message, company_info, doctors, history=history,
            extra_context="This is an insurance-related inquiry. Help the patient with insurance verification, coverage questions, accepted providers, and co-pay information."
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

    # Hardcoded fallback
    return FALLBACK_RESPONSE
