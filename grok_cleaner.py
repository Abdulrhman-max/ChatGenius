"""
Grok AI message cleaner for BrightSmile Advanced Dental Center.
Runs FIRST on every user message to fix spelling and reform poorly written
messages into clear English before any other processing happens.
Uses Groq API (fast LLM inference).
"""
import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

_client = None

SYSTEM_PROMPT = (
    "You are a spelling and grammar corrector. "
    "ONLY fix spelling mistakes and grammar. Keep questions as questions. "
    "NEVER answer the question. NEVER add information. NEVER change the meaning. "
    "If the message is already clear, return it exactly as-is. "
    "Return ONLY the corrected sentence, nothing else.\n\n"
    "Input: waht r ur clinic owrking horus\nOutput: What are your clinic working hours?\n"
    "Input: i wan buk apointmnt wit dr jhon tomorw\nOutput: I want to book an appointment with Dr. John tomorrow.\n"
    "Input: toth hirts alot wen i eet col stuf\nOutput: My tooth hurts a lot when I eat cold things.\n"
    "Input: what is the company name\nOutput: What is the company name?\n"
    "Input: WHAT IS THE DENTIST NAME\nOutput: What is the dentist name?"
)


def is_configured():
    return bool(GROQ_API_KEY and len(GROQ_API_KEY) > 10)


def _get_client():
    global _client
    if _client is None:
        from groq import Groq
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def clean(user_message, history=None):
    """
    Clean/reform a user message using Grok AI.
    Returns the corrected message, or the original on failure.
    """
    if not is_configured():
        return user_message

    # Skip very short messages (greetings, yes/no)
    if len(user_message.strip()) <= 3:
        return user_message

    try:
        client = _get_client()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=150,
            temperature=0,
        )
        cleaned = response.choices[0].message.content.strip()

        # Remove quotes if AI wrapped it
        if cleaned.startswith('"') and cleaned.endswith('"'):
            cleaned = cleaned[1:-1]
        if cleaned.startswith("'") and cleaned.endswith("'"):
            cleaned = cleaned[1:-1]

        # Safety: if output is way too different or too long, use original
        if len(cleaned) > len(user_message) * 3 or len(cleaned) < 2:
            return user_message

        # Safety: if a question was turned into an answer, use original
        raw_is_question = '?' in user_message or user_message.strip().lower().startswith(('what', 'who', 'where', 'when', 'how', 'why', 'which', 'is', 'are', 'do', 'does', 'can'))
        cleaned_is_statement = '?' not in cleaned and not cleaned.strip().lower().startswith(('what', 'who', 'where', 'when', 'how', 'why', 'which', 'is', 'are', 'do', 'does', 'can'))
        if raw_is_question and cleaned_is_statement:
            print(f"[grok_cleaner] BLOCKED answer-like output: '{cleaned}' — using original", flush=True)
            return user_message

        print(f"[grok_cleaner] '{user_message}' -> '{cleaned}'", flush=True)
        return cleaned

    except Exception as e:
        print(f"[grok_cleaner] Error: {e}", flush=True)
        return user_message
