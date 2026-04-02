"""
AI specialist for symptom analysis and doctor specialization cases.
Uses OpenAI (primary) for medical triage.
Falls back to Groq 70B, then Claude if OpenAI fails.
"""

import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

_openai_client = None
_groq_client = None
_anthropic_client = None


def is_configured():
    return (bool(OPENAI_API_KEY and len(OPENAI_API_KEY) > 10) or
            bool(GROQ_API_KEY and len(GROQ_API_KEY) > 10) or
            bool(ANTHROPIC_API_KEY and len(ANTHROPIC_API_KEY) > 10))


def _get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def _get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


def is_specialization_query(message):
    """
    Detect if a message is about symptoms, pain, or asking what type of doctor to see.
    """
    lower = message.lower()

    symptom_words = [
        "hurt", "pain", "ache", "sore", "swollen", "bleeding", "broken",
        "crack", "chip", "loose", "numb", "tingling", "sensitive",
        "infection", "abscess", "fever", "bump", "lump", "ulcer",
        "cavity", "decay", "rotten", "throbbing", "sharp pain",
        "dull pain", "wisdom", "jaw", "gum", "tooth", "teeth",
        "bite", "chew", "grind", "clench", "click", "pop",
    ]

    doctor_type_words = [
        "what type of doctor", "what kind of doctor", "which doctor",
        "what specialist", "which specialist", "who should i see",
        "what doctor do i need", "what doctor should",
        "do i need a specialist", "recommend a doctor",
        "what dentist", "which dentist",
    ]

    has_symptom = any(w in lower for w in symptom_words)
    asks_doctor_type = any(w in lower for w in doctor_type_words)

    if has_symptom and asks_doctor_type:
        return True
    symptom_count = sum(1 for w in symptom_words if w in lower)
    if symptom_count >= 2:
        return True
    if asks_doctor_type:
        return True
    return False


SYSTEM_PROMPT_TEMPLATE = """You are an expert dental triage assistant. A patient is describing symptoms or asking what type of dental specialist they need.

YOUR EXPERTISE:
- General Dentist: routine care, checkups, fillings, cleanings, basic extractions
- Endodontist: root canals, tooth nerve issues, internal tooth pain, cracked teeth
- Periodontist: gum disease, gum surgery, gum recession, bone loss, deep cleaning
- Orthodontist: braces, Invisalign, teeth alignment, bite correction, jaw alignment
- Oral & Maxillofacial Surgeon: wisdom teeth removal, jaw surgery, facial trauma, complex extractions, implant placement
- Prosthodontist: crowns, bridges, dentures, veneers, tooth replacement, full mouth reconstruction
- Pediatric Dentist: children's dental care, baby teeth issues
- Oral Pathologist: mouth sores, lesions, oral cancer screening
- Cosmetic Dentist: whitening, veneers, bonding, smile makeover
- TMJ/Orofacial Pain Specialist: jaw pain, clicking/popping jaw, TMJ disorders, facial pain, bruxism

{doc_context}

YOUR JOB:
1. Analyze the patient's symptoms carefully
2. Identify the most likely dental condition
3. Recommend the CORRECT type of specialist based on symptoms — accuracy is critical
4. If a matching doctor exists in the available list, mention them BY NAME and suggest booking
5. If NO matching specialist is available, say: "I recommend seeing a **[correct specialist type]**, but unfortunately we don't have that type of specialist in our office at the moment. I'd suggest looking for one nearby."

CRITICAL RULES:
- NEVER recommend the WRONG specialist just because they're the only one available
- Tooth pain / toothache → General Dentist or Endodontist, NEVER an Orthodontist
- Gum bleeding / gum disease → Periodontist, NEVER an Orthodontist
- Jaw pain / TMJ → TMJ Specialist, NEVER an Orthodontist
- Braces / alignment / crooked teeth → Orthodontist (ONLY this case)
- Be HONEST — if the right specialist isn't in the office, say so clearly

RESPONSE FORMAT:
- Be empathetic and reassuring
- Use **bold** for specialist names and key info
- Be concise (3-5 sentences)
- NEVER diagnose definitively — use "this sounds like", "you may need"
- ONLY reference doctors from the list above — never make up names"""


def analyze_symptoms(user_message, doctors=None, history=None):
    """
    Send symptom/specialization query to AI for accurate analysis.
    Priority: OpenAI → Groq 70B → Claude
    """
    if not is_configured():
        return None

    # Build doctor context
    doc_context = "No doctors are currently listed."
    if doctors:
        doc_lines = [
            f"- Dr. {d['name']} (Specialty: {d.get('specialty', 'General')}, "
            f"Available: {d.get('availability', 'Mon-Fri')})"
            for d in doctors
        ]
        doc_context = "Available doctors at this office:\n" + "\n".join(doc_lines)

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(doc_context=doc_context)

    # Build conversation messages
    conv_messages = []
    if history:
        for msg in history[-6:]:
            conv_messages.append({"role": msg.get("role", "user"), "content": msg["content"]})
    conv_messages.append({"role": "user", "content": user_message})

    # 1. Try OpenAI (primary for symptoms)
    if OPENAI_API_KEY and len(OPENAI_API_KEY) > 10:
        try:
            client = _get_openai()
            messages = [{"role": "system", "content": system_prompt}] + conv_messages
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=400,
                temperature=0.2,
            )
            reply = response.choices[0].message.content.strip()
            print(f"[specialist] OpenAI response for: '{user_message[:50]}...'", flush=True)
            return {"reply": reply}
        except Exception as e:
            print(f"[specialist] OpenAI error: {e}", flush=True)

    # 2. Fallback: Groq 70B
    if GROQ_API_KEY and len(GROQ_API_KEY) > 10:
        try:
            client = _get_groq()
            messages = [{"role": "system", "content": system_prompt}] + conv_messages
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                max_tokens=400,
                temperature=0.2,
            )
            reply = response.choices[0].message.content.strip()
            print(f"[specialist] Groq 70B fallback for: '{user_message[:50]}...'", flush=True)
            return {"reply": reply}
        except Exception as e:
            print(f"[specialist] Groq 70B error: {e}", flush=True)

    # 3. Fallback: Claude
    if ANTHROPIC_API_KEY and len(ANTHROPIC_API_KEY) > 10:
        try:
            client = _get_anthropic()
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                system=system_prompt,
                messages=conv_messages,
            )
            reply = response.content[0].text.strip()
            print(f"[specialist] Claude fallback for: '{user_message[:50]}...'", flush=True)
            return {"reply": reply}
        except Exception as e:
            print(f"[specialist] Claude error: {e}", flush=True)

    return None
