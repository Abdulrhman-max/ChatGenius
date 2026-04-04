"""
Treatment education and contextual upselling engine for BrightSmile Advanced Dental Center.
Educates patients about dental treatments and suggests complementary services (non-pushy).
"""

import message_interpreter
import dental_ai

CONTACT_FOOTER = (
    "\n\n---\n"
    "**BrightSmile Advanced Dental Center** | "
    "Phone: +966 11 234 5678 | WhatsApp: +966 55 987 6543"
)

BRIGHTSMILE_DOCTORS = {
    "General Dentistry": "Dr. Ahmed Al-Harbi (12 years experience)",
    "Orthodontics": "Dr. Sarah Al-Qahtani (10 years experience)",
    "Oral Surgery": "Dr. Mohammed Al-Otaibi (15 years experience)",
    "Pediatric Dentistry": "Dr. Lina Al-Salem (8 years experience)",
    "Cosmetic Dentistry": "Dr. Khalid Al-Faisal (11 years experience)",
}

# Maps treatments to related services for contextual suggestions
TREATMENT_UPSELLS = {
    "cleaning": ["whitening", "fluoride treatment"],
    "filling": ["dental sealants", "preventive care plan"],
    "root canal": ["dental crown", "follow-up care"],
    "extraction": ["dental implant", "bridge", "denture"],
    "missing tooth": ["dental implant", "bridge", "partial denture"],
    "whitening": ["veneers", "cosmetic bonding"],
    "braces": ["retainers", "whitening after braces"],
    "implant": ["bone grafting", "implant-supported crown"],
    "veneer": ["smile makeover", "teeth whitening"],
    "crown": ["root canal assessment", "bite adjustment"],
}

SYSTEM_PROMPT = """You are the treatment education assistant for BrightSmile Advanced Dental Center.

YOUR JOB:
Educate patients about dental treatments in an accessible, non-intimidating way. When appropriate, mention complementary treatments — but NEVER be pushy or salesy.

BRIGHTSMILE DENTAL TEAM:
- **Dr. Ahmed Al-Harbi** — General Dentistry (12 years experience)
- **Dr. Sarah Al-Qahtani** — Orthodontics (10 years experience)
- **Dr. Mohammed Al-Otaibi** — Oral Surgery (15 years experience)
- **Dr. Lina Al-Salem** — Pediatric Dentistry (8 years experience)
- **Dr. Khalid Al-Faisal** — Cosmetic Dentistry (11 years experience)

CONTEXTUAL SUGGESTIONS (mention naturally, not as a sales pitch):
- Cleaning → "Many patients also love our teeth whitening — your smile looks even better on a clean canvas!"
- Missing tooth → Explain the differences: implants (most natural, long-lasting), bridges (non-surgical option), dentures (affordable for multiple missing teeth)
- Extraction → "After healing, you might want to explore replacement options like implants or bridges"
- Filling → "Dental sealants can help prevent future cavities in hard-to-reach areas"
- Root canal → "A dental crown is usually recommended after a root canal to protect the treated tooth"
- Braces → "Once your braces come off, professional whitening can really make your new smile shine"
- Whitening → "For even more dramatic results, some patients combine whitening with porcelain veneers"

HOW TO EDUCATE:
- Explain procedures in simple, patient-friendly language
- Mention what to expect: duration, pain level, recovery time
- Address common fears and misconceptions
- Recommend the appropriate BrightSmile doctor by name
- Mention complementary treatments naturally at the end

IMPORTANT RULES:
- NEVER be pushy or make patients feel they NEED additional treatments
- Use phrases like "you might also consider", "many patients enjoy", "something to think about"
- Be warm, educational, and empowering
- Be concise (3-6 sentences)
- Use **bold** for treatment names and doctor names
- NEVER provide specific pricing — direct them to ask about pricing or contact the clinic
- If a patient seems anxious, focus on reassurance first, education second"""

FALLBACK_RESPONSE = (
    "At **BrightSmile Advanced Dental Center**, we offer a full range of treatments "
    "and our team is here to help you understand your options:\n\n"
    "**Our Specialists:**\n"
    + "\n".join(f"- **{doc}** — {spec}" for spec, doc in BRIGHTSMILE_DOCTORS.items())
    + "\n\n"
    "Whether you're looking into **teeth cleaning**, **fillings**, **root canals**, "
    "**implants**, **braces**, or **cosmetic treatments** like whitening and veneers — "
    "we're happy to walk you through what each procedure involves, what to expect, "
    "and which options might work best for you.\n\n"
    "Feel free to ask about any specific treatment and I'll explain it in detail!"
    + CONTACT_FOOTER
)


def handle(message, company_info=None, doctors=None, history=None):
    """
    Handle treatment education and contextual upselling inquiries.

    Args:
        message: The user's message (already spell-corrected)
        company_info: Dict with business info
        doctors: List of active doctor dicts
        history: List of conversation history messages

    Returns:
        str: Response string
    """
    # Detect relevant treatments for contextual enrichment
    lower_msg = message.lower()
    related_suggestions = []
    for treatment, upsells in TREATMENT_UPSELLS.items():
        if treatment in lower_msg:
            related_suggestions.extend(upsells)

    enriched_prompt = f"[Treatment education inquiry] {message}"
    if related_suggestions:
        unique_suggestions = list(dict.fromkeys(related_suggestions))
        enriched_prompt += f" [Related treatments to mention naturally: {', '.join(unique_suggestions)}]"

    # Try Grok AI (message_interpreter) first
    if message_interpreter.is_configured():
        result = message_interpreter.think_and_respond(
            enriched_prompt, company_info, doctors, history=history
        )
        if result and result.get("reply"):
            return result["reply"] + CONTACT_FOOTER

    # Fallback to OpenAI
    if dental_ai.is_configured():
        result = dental_ai.think_and_respond(
            enriched_prompt, company_info, doctors, history=history
        )
        if result and result.get("reply"):
            return result["reply"] + CONTACT_FOOTER

    # Hardcoded fallback
    return FALLBACK_RESPONSE
