"""
AI-powered dental assistant brain using Groq (free Llama models).
Two roles:
1. interpret() — spell-checks garbled user messages
2. think_and_respond() — the AI BRAIN that understands and answers everything
"""

import os
import json
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

_client = None


def is_configured():
    return bool(GROQ_API_KEY and len(GROQ_API_KEY) > 10)


def _get_client():
    global _client
    if _client is None:
        from groq import Groq
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def interpret(user_message, history=None):
    """
    Send the user's raw message to Groq AI to understand what they mean.
    Includes conversation history so the AI can resolve pronouns like "him", "that doctor", etc.
    Returns a clean, corrected version of their message.
    Falls back to the original message if Groq fails.
    """
    if not is_configured():
        return user_message

    try:
        client = _get_client()

        # Build context hint from history (just the topic, not full messages)
        context_hint = ""
        if history:
            # Extract doctor names and topics mentioned recently
            recent = history[-4:]
            for msg in recent:
                content = msg.get("content", "").lower()
                if "dr." in content or "doctor" in content:
                    # Find the doctor name
                    import re as _re
                    name_match = _re.search(r'(?:dr\.?|doctor)\s+(\w+(?:\s+\w+)?)', content, _re.IGNORECASE)
                    if name_match:
                        context_hint = f" The conversation is about Dr. {name_match.group(1)}."
                        break

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a spell checker. You fix spelling and grammar ONLY.\n\n"
                    "RULES:\n"
                    "- Output ONLY the corrected version of the user's message\n"
                    "- Fix spelling, typos, and grammar\n"
                    "- NEVER answer or respond to the question — just correct it\n"
                    "- NEVER change the meaning, intent, or sentence structure\n"
                    "- NEVER add information, advice, or words that weren't in the original\n"
                    "- If the original is a question, your output MUST be a question\n"
                    "- If the original is a refusal (no, don't want), keep it as a refusal\n"
                    "- Replace pronouns like 'him'/'her' with the person's name if known from context\n"
                    "- Keep names exactly as spelled (e.g. 'jhon' stays 'jhon')\n"
                    "- Your output should have roughly the same number of words as the input\n"
                    + (f"\nContext:{context_hint}" if context_hint else "")
                ),
            },
        ]

        messages.append({"role": "user", "content": user_message})

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=150,
            temperature=0,
        )
        corrected = response.choices[0].message.content.strip()
        # Remove quotes if AI wrapped it
        if corrected.startswith('"') and corrected.endswith('"'):
            corrected = corrected[1:-1]
        # Safety: if AI returned something way too different or too long, use original
        if len(corrected) > len(user_message) * 3 or len(corrected) < 2:
            return user_message
        print(f"[interpreter] '{user_message}' -> '{corrected}'", flush=True)
        return corrected
    except Exception as e:
        print(f"[interpreter] Groq error: {e}", flush=True)
        return user_message


def think_and_respond(user_message, company_info=None, doctors=None,
                      doctor_slots=None, history=None, extra_context=None):
    """
    The AI brain. Given the user's message and full business context,
    understands what they're asking and responds intelligently.

    Args:
        user_message: The user's message (already spell-corrected)
        company_info: Dict with business_name, business_hours, services, etc.
        doctors: List of active doctor dicts
        doctor_slots: Dict mapping doctor name -> list of time slot strings
        history: List of conversation history messages

    Returns:
        dict: {"reply": str, "intent": str} or None on failure
    """
    if not is_configured():
        return None

    try:
        client = _get_client()

        # Build rich context
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

        if doctors:
            doc_lines = []
            for d in doctors:
                # Derive working days from daily_hours (flexible) or availability (fixed)
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
                            # Add hours per day
                            hours_parts = []
                            for day in working:
                                h = daily[day]
                                hours_parts.append(f"{day}: {h.get('from','?')} - {h.get('to','?')}")
                            working_days_str += " | Hours: " + "; ".join(hours_parts)
                    except Exception:
                        pass
                line = f"- Dr. {d['name']} (Specialty: {d.get('specialty', 'General')}, Works on: {working_days_str})"
                doc_lines.append(line)
            context_parts.append("Available doctors:\n" + "\n".join(doc_lines))

        company_context = "\n".join(context_parts) if context_parts else "No company info configured yet."

        system_prompt = f"""You are a smart, empathetic dental office AI assistant for {biz_name}.

CONTEXT:
{company_context}

YOUR JOB:
You UNDERSTAND what the patient means and respond helpfully. You have access to real doctor schedules and office data above.

HOW TO RESPOND:

1. AVAILABILITY QUESTIONS — "is doctor X free at 3:15?", "when is doctor available?", "what times does doctor have?"
   → Check the time slots data above and give a SPECIFIC answer
   → If they ask about a specific time, tell them YES or NO based on the slots
   → If they ask generally, show the relevant time slots
   → Always mention the doctor by name

2. SYMPTOMS / DENTAL PROBLEMS — patient describes pain or dental issues
   → Show empathy, explain possible causes, give home care tips
   → Recommend the right type of specialist
   → If matching doctors exist, mention them BY NAME

3. DENTAL OFFICE INFO — hours, location, services, pricing
   → Answer using ONLY the data from the CONTEXT above. NEVER guess or make up prices.
   → For pricing questions, look up the exact service price from the "Pricing/Insurance" section above
   → If the service is listed with a price, quote THAT exact price. Do NOT invent price ranges.

4. DOCTOR LISTING — who are the doctors, what specialists
   → List doctors with specialties from context above

5. GREETINGS — hi, hello
   → Warm greeting, mention what you can help with

6. FAREWELLS — bye, thanks
   → Warm farewell

7. SERVICE QUESTIONS — when patient asks about a specific service/treatment
   → Check if the service is listed in the "Pricing/Insurance" or "Services" section in the CONTEXT above
   → If we OFFER it: answer about it, quote the price, and offer to book
   → If we do NOT offer it: say "We don't currently offer [service] at {biz_name}." and suggest similar services we DO offer, or recommend they call for more info
   → NEVER describe a service as if we offer it when it's not in our list

8. REFUSAL/NO — user says no, doesn't want something
   → Acknowledge politely, ask how else you can help

RESPONSE FORMAT:
- Be concise (2-5 sentences)
- Use **bold** for doctor names and important info
- Be warm and professional
- End with a relevant follow-up suggestion
- NEVER make up doctors or data not in the context above
- If company info is missing for a topic, say it hasn't been set up yet

CRITICAL RULES:
- You are the AI assistant for **{biz_name}** — when asked "what is the dentist name" or "what is the company name", answer with: **{biz_name}**
- NEVER say "I'm a large language model" or comment about improving your responses
- NEVER break character — you ARE the dental office assistant, not a generic AI
- Stay focused on the patient's question — answer it directly
- PRICING: When asked about service costs/prices, you MUST quote the EXACT price from the Pricing/Insurance section in the CONTEXT above. Do NOT estimate, guess, or provide ranges. Use the exact number listed. If a service is not in the list, say you don't have pricing info for it.
- SERVICES: You can ONLY discuss services that are listed in the CONTEXT above. If a patient asks about a service we don't offer (not in the list), clearly tell them "We don't currently offer that service." and suggest our available services instead. NEVER give general dental advice about services we don't provide."""

        if extra_context:
            system_prompt += f"\n\nADDITIONAL CONTEXT:\n{extra_context}"

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history[-10:])  # Last 10 messages for context
        messages.append({"role": "user", "content": user_message})

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=400,
            temperature=0.3,
        )

        reply = response.choices[0].message.content.strip()
        print(f"[groq_brain] Responded to: '{user_message[:50]}...'", flush=True)
        return {"reply": reply, "intent": "ai"}

    except Exception as e:
        print(f"[groq_brain] Error: {e}", flush=True)
        return None
