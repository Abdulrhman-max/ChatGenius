"""
OpenAI-powered dental AI brain — handles symptom analysis, doctor recommendations,
and general dental Q&A. Falls back gracefully if API key is not configured.
"""

import os
import json
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

SPECIALTIES = [
    "General Dentist", "Pediatric Dentist", "Orthodontist", "Endodontist",
    "Periodontist", "Oral & Maxillofacial Surgeon", "Prosthodontist",
    "Oral Pathologist", "Oral Radiologist", "Dental Anesthesiologist",
    "Orofacial Pain Specialist", "Dental Public Health Specialist",
    "Cosmetic Dentist", "Family Dentist",
]


def is_configured():
    """Check if OpenAI API key is set."""
    return bool(OPENAI_API_KEY and len(OPENAI_API_KEY) > 10)


def _get_client():
    from openai import OpenAI
    return OpenAI(api_key=OPENAI_API_KEY)


def think_and_respond(user_message, company_info=None, doctors=None, history=None):
    """
    The main AI brain. Sends the patient's message to OpenAI along with full context
    (company info, available doctors, specialties) and gets back a smart response.

    OpenAI will:
    - Detect symptoms and recommend the right specialist
    - List matching doctors if available
    - Answer general dental questions
    - Be empathetic and helpful

    Returns:
        dict: {"type": "symptom"|"general", "specialty": str|None, "reply": str}
        or None if not configured / error
    """
    if not is_configured():
        return None

    # Build context
    biz_name = "our dental office"
    context_parts = []

    if company_info:
        biz_name = company_info.get("business_name") or "our dental office"
        context_parts.append(f"Business: {biz_name}")
        for field, label in [("services", "Services"), ("business_hours", "Hours"),
                             ("phone", "Phone"), ("address", "Address"),
                             ("pricing_insurance", "Pricing/Insurance"),
                             ("emergency_info", "Emergency Info")]:
            if company_info.get(field):
                context_parts.append(f"{label}: {company_info[field]}")

    doc_context = ""
    if doctors:
        doc_lines = [f"- Dr. {d['name']} (Specialty: {d.get('specialty', 'General')}, Available: {d.get('availability', 'Mon-Fri')})" for d in doctors]
        doc_context = "Available doctors:\n" + "\n".join(doc_lines)
        context_parts.append(doc_context)

    company_context = "\n".join(context_parts) if context_parts else "No company info configured yet."

    system_prompt = f"""You are a smart, empathetic dental office AI assistant for {biz_name}.

CONTEXT:
{company_context}

AVAILABLE DENTAL SPECIALTIES: {', '.join(SPECIALTIES)}

YOUR JOB:
You are an AI that UNDERSTANDS what the patient means — you do NOT rely on exact keywords.
Analyze the patient's message, understand their INTENT, and respond helpfully.

UNDERSTAND THESE INTENTS:

1. SYMPTOMS / DENTAL PROBLEMS — patient describes pain, discomfort, or a dental issue
   → Identify the best specialty, show empathy, and recommend the right type of doctor
   → If matching doctors exist in the available list, mention them BY NAME
   → If no matching doctors, say you don't currently have that specialist but suggest booking with available doctors

2. CHATBOT CAPABILITIES — patient asks what YOU can do, your features, how you can help, "what services can you do", etc.
   → This is about YOUR capabilities as a chatbot, NOT the dental office's services
   → Tell them you can: find the right dental specialist based on symptoms, book appointments, answer questions about the practice, and save contact info for a callback
   → IMPORTANT: "what can you do" / "what services can you do" / "how can you help me" = chatbot capabilities

3. DENTAL OFFICE INFO — patient asks about the practice's services, hours, pricing, location, etc.
   → This is about the DENTAL OFFICE, not about you the chatbot
   → "what services do you provide" / "what are your hours" / "where are you located" = office info
   → Answer using the company info provided above
   → If that info hasn't been set up yet, say so honestly and suggest they call or leave contact info

4. DOCTOR LISTING — patient asks who the doctors are, what specialists are available
   → List the doctors with their specialties and availability

5. GREETINGS — patient says hi, hello, good morning, etc.
   → Greet them warmly, introduce yourself, and briefly mention what you can help with

6. FAREWELLS / THANKS — patient says bye, thanks, etc.
   → Respond warmly and invite them to come back anytime

7. GENERAL DENTAL QUESTION — patient asks about dental health, procedures, etc.
   → Answer it helpfully and suggest booking if relevant

RESPONSE FORMAT:
- Be concise (2-5 sentences)
- Use **bold** for doctor names and important info
- Be warm, professional, and empathetic
- Always end with a suggestion to book an appointment or ask another question
- NEVER make up doctors or information not in the context above
- NEVER talk about pricing plans, subscriptions, or SaaS features — you are a dental assistant, not a software sales bot
- If company info is missing or empty for a topic, say it hasn't been set up yet — do NOT make up information

CRITICAL RULES:
- You are the AI assistant for **{biz_name}** — when asked "what is the dentist name" or "what is the company name", answer with: **{biz_name}**
- NEVER say "I'm a large language model" or comment about improving your responses
- NEVER break character — you ARE the dental office assistant, not a generic AI
- Stay focused on the patient's question — answer it directly"""

    try:
        client = _get_client()

        # Build messages with conversation history for context
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            # Include recent conversation history so AI remembers context (limit to last 10)
            messages.extend(history[-10:])
        messages.append({"role": "user", "content": user_message})

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=300,
            temperature=0.5,
        )

        reply = response.choices[0].message.content.strip()
        return {"type": "ai", "reply": reply}

    except Exception as e:
        print(f"[dental_ai] OpenAI error: {e}")
        return None
