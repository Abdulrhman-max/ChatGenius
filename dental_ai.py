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


def think_and_respond(user_message, company_info=None, doctors=None, history=None, doctor_slots=None):
    """
    The main AI brain. Sends the patient's message to OpenAI along with full context
    (company info, available doctors, specialties) and gets back a smart response.

    Returns:
        dict: {"type": "ai", "reply": str} or None if not configured / error
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
        if company_info.get("_customer_name"):
            context_parts.append(f"Current patient name: {company_info['_customer_name']}")

    if doctors:
        doc_lines = []
        for d in doctors:
            working_days_str = d.get('availability', 'Mon-Fri')
            if d.get('schedule_type') == 'flexible' and d.get('daily_hours'):
                try:
                    import json as _json
                    daily = d['daily_hours']
                    if isinstance(daily, str):
                        daily = _json.loads(daily)
                    day_order = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
                    working = [day for day in day_order if day in daily and not daily[day].get("off")]
                    if working:
                        working_days_str = ", ".join(working)
                        hours_parts = []
                        for day in working:
                            h = daily[day]
                            hours_parts.append(f"{day}: {h.get('from','%s')} - {h.get('to','%s')}")
                        working_days_str += " | Hours: " + "; ".join(hours_parts)
                except Exception:
                    pass
            line = f"- Dr. {d['name']} (Specialty: {d.get('specialty', 'General')}, Works on: {working_days_str})"
            doc_lines.append(line)
        context_parts.append("Available doctors:\n" + "\n".join(doc_lines))

    if doctor_slots:
        slot_lines = []
        for doc_name, slots in doctor_slots.items():
            slot_lines.append(f"Dr. {doc_name} today's slots: {', '.join(slots[:10])}")
        context_parts.append("Today's available time slots:\n" + "\n".join(slot_lines))

    company_context = "\n".join(context_parts) if context_parts else "No company info configured yet."

    system_prompt = f"""You are a smart, empathetic dental office AI assistant for {biz_name}.

CONTEXT:
{company_context}

IMPORTANT: You ONLY answer questions related to dentistry, dental health, and this dental office.
If the patient asks about anything unrelated to dentistry (e.g. cooking, politics, math, programming, etc.),
politely decline and say you can only help with dental-related questions.

YOUR JOB:
Analyze the patient's message and respond helpfully about dental topics.

HOW TO RESPOND:

1. AVAILABILITY QUESTIONS — "is doctor X free%s", "when is doctor available%s", "what times%s"
   → Check the time slots data above and give a SPECIFIC answer
   → Always mention the doctor by name

2. SYMPTOMS / DENTAL PROBLEMS — patient describes pain or dental issues
   → Show empathy, explain possible causes, give home care tips
   → Recommend the right type of specialist
   → If matching doctors exist, mention them BY NAME

3. DENTAL OFFICE INFO — hours, location, services, pricing
   → Answer using ONLY the data from the CONTEXT above. NEVER guess or make up prices.
   → For pricing questions, quote the EXACT price from the context. Do NOT invent price ranges.

4. DOCTOR LISTING — who are the doctors, what specialists
   → List doctors with specialties from context above

5. GREETINGS — hi, hello
   → Warm greeting, mention what you can help with

6. FAREWELLS — bye, thanks
   → Warm farewell

7. SERVICE QUESTIONS — when patient asks about a specific service/treatment
   → If we OFFER it: answer about it, quote the price, and offer to book
   → If we do NOT offer it: say we don't currently offer it and suggest similar services we DO offer

8. GENERAL DENTAL QUESTION — dental health, procedures, oral care tips
   → Answer helpfully and suggest booking if relevant

RESPONSE FORMAT:
- Be concise (2-5 sentences)
- Use **bold** for doctor names and important info
- Be warm and professional
- End with a relevant follow-up suggestion
- NEVER make up doctors or data not in the context above
- If company info is missing for a topic, say it hasn't been set up yet

CRITICAL RULES:
- You are the AI assistant for **{biz_name}**
- ONLY answer dentist-related questions. Decline anything unrelated to dentistry.
- NEVER say "I'm a large language model" or break character
- NEVER make up information not in the context above
- PRICING: Quote EXACT prices from the context. If a service price isn't listed, say you don't have pricing info for it."""

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
