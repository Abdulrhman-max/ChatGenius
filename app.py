"""
ChatGenius Flask backend with three chatbot features:
1. Q&A — answers business questions from knowledge base
2. Appointment Booking — collects info, checks calendar, confirms, emails
3. Lead Capture — collects name/phone when not ready to book
All work inside the chat window with a conversation state machine.
"""

from flask import Flask, request, jsonify, send_from_directory
import torch
import os
import json
import re
import uuid
from datetime import datetime, timedelta

import database as db
import calendar_service as cal
import email_service as email
import social_auth
import dental_ai
import dental_knowledge_engine as dke
import intent_classifier
import message_interpreter
import claude_specialist
import grok_cleaner
import sklearn_classifier
import smart_router
import restriction_filter

app = Flask(__name__, static_folder="static")

# ── Load knowledge base ──
KB_PATH = os.path.join(os.path.dirname(__file__), "data", "knowledge_base.json")
with open(KB_PATH) as f:
    KB = json.load(f)

# ── Model config ──
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models", "chatgenius-tinyllama")
BASE_MODEL = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
SYSTEM_MSG = "You are ChatGenius AI, a helpful sales assistant. Answer concisely in 1-3 sentences using this context:\n\n"

model = None
tokenizer = None
device = None

# ── Session store (in-memory, keyed by session_id) ──
sessions = {}


def get_session(sid):
    if sid not in sessions:
        sessions[sid] = {"flow": None, "data": {}, "step": None, "history": []}
    # Migration: add history to old sessions
    if "history" not in sessions[sid]:
        sessions[sid]["history"] = []
    return sessions[sid]


def reset_session(sid):
    sessions[sid] = {"flow": None, "data": {}, "step": None, "history": []}


def is_admin_role(user):
    """Check if user is any type of admin (head_admin or admin)."""
    return user.get("role") in ("admin", "head_admin")


def get_effective_admin_id(user):
    """Get the company-scoping admin_id.
    head_admin uses their own id, admin uses their admin_id, doctor uses admin_id."""
    if user.get("role") == "head_admin":
        return user["id"]
    return user.get("admin_id", 0) or user["id"]


def load_model():
    global model, tokenizer, device
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"Loading model on {device}...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    base = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float16)
    model = PeftModel.from_pretrained(base, MODEL_DIR)
    model = model.merge_and_unload()
    model.to(device)
    model.eval()
    print("Model ready!")


# ══════════════════════════════════════════════
#  Q&A — Knowledge Base Responses
# ══════════════════════════════════════════════

KEYWORD_MAP = {
    "pricing": ["price", "pricing", "cost", "how much", "plan", "basic", "pro", "agency", "pay", "afford", "cheap", "expensive", "dollar", "month", "subscription", "tier", "billing"],
    "features": ["feature", "what can", "what does", "capabilit", "offer", "include", "do for me", "functionality"],
    "setup": ["setup", "set up", "install", "get started", "begin", "onboard", "configure", "implement", "how long", "how do i"],
    "trial": ["trial", "free", "try", "test", "credit card", "cancel", "risk", "money back", "refund", "guarantee"],
    "industries": ["industry", "dental", "law", "restaurant", "real estate", "ecommerce", "e-commerce", "salon", "clinic", "shop", "store", "fitness", "my business"],
    "integration": ["integrat", "connect", "crm", "hubspot", "salesforce", "zapier", "calendar", "wordpress", "shopify", "wix", "website", "embed", "slack"],
    "security": ["safe", "secur", "encrypt", "gdpr", "complian", "privacy", "data", "ccpa", "soc"],
    "support": ["support", "help me with", "contact", "customer service", "onboarding"],
    "comparison": ["differ", "compar", "vs", "versus", "better", "intercom", "drift", "tidio", "zendesk", "unique", "advantage", "regular chatbot"],
    "how_it_works": ["how does", "how it work", "what is chatgenius", "about chatgenius", "tell me about", "explain"],
    "languages": ["language", "spanish", "french", "german", "translat", "multilingual"],
}

KB_RESPONSES = {
    "pricing": "We have three plans: **Basic** at $49/month (500 conversations, 1 chatbot, email support), **Pro** at $149/month (5,000 conversations, 3 chatbots, appointment booking, CRM integration, priority support), and **Agency** at $299/month (unlimited everything, white-label, API access, dedicated manager). All include a 14-day free trial — no credit card required! Save 20% with annual billing.",
    "features": "ChatGenius includes: 24/7 instant AI replies (under 2 seconds), automated appointment booking with calendar sync, smart lead capture with CRM integration, one-line website integration, a no-code dashboard, and templates for 20+ industries. Pro adds multi-language support, analytics, and human handoff.",
    "setup": "Setup takes under 5 minutes: 1) Sign up free, 2) Enter your business info, 3) Upload your knowledge base or let AI learn from your website, 4) Customize the look, 5) Paste one line of code on your site. No coding or technical skills needed!",
    "trial": "We offer a 14-day free trial with full Pro features — no credit card required. After the trial, choose a paid plan or continue with a limited free tier (50 conversations/month). We also have a 30-day money-back guarantee on all paid plans. Zero risk!",
    "industries": "ChatGenius works for any industry! Popular verticals: dental clinics, law firms, real estate, restaurants, e-commerce, fitness studios, salons, automotive, professional services, and education. We have pre-built templates for 20+ industries, and the AI adapts to your specific business.",
    "integration": "We integrate with HubSpot, Salesforce, Zoho, Pipedrive (CRM), Google Calendar, Calendly, Outlook (scheduling), Slack, Teams (communication), Zapier, Make (automation), and Google Analytics. Works on WordPress, Shopify, Wix, Squarespace, Webflow, and any custom website.",
    "security": "All data is encrypted with AES-256 at rest and TLS 1.3 in transit. We're GDPR and CCPA compliant, hosted on AWS with 99.9% uptime. Agency plan includes SOC 2 Type II compliance. We never sell your data — you own everything and can export or delete anytime.",
    "support": "Basic: email support (24-48h response). Pro: priority email + chat (under 4h). Agency: dedicated account manager, Slack channel, phone support. All users get access to our knowledge base, video tutorials, weekly webinars, and community forum.",
    "comparison": "Unlike scripted chatbots, ChatGenius uses real AI that understands context and intent. Compared to Intercom ($74+/mo, built for enterprise), we're purpose-built for SMBs at lower cost. Compared to Tidio, our AI handles unexpected questions and maintains conversation flow.",
    "how_it_works": "ChatGenius uses AI trained on your business data to understand and respond to customer questions naturally. Visitors get instant answers, can book appointments, and share their contact info — all automatically. You manage everything from a simple dashboard.",
    "languages": "On Pro and Agency plans, ChatGenius supports 10 languages: English, Spanish, French, German, Portuguese, Italian, Dutch, Japanese, Korean, and Chinese. The chatbot auto-detects the visitor's language and responds accordingly.",
}


DENTAL_KEYWORD_MAP = {
    "hours": ["hour", "open", "close", "when are you", "what time", "schedule", "weekend", "saturday", "sunday", "lunch break", "working hour", "office hour"],
    "location": ["where", "address", "location", "directions", "located", "find you", "come to", "parking", "near"],
    "services": ["service", "offer", "provide", "do you do", "treatment", "cleaning", "filling", "whitening", "implant", "crown", "braces", "invisalign", "root canal", "extraction", "cosmetic", "veneer", "pediatric", "orthodont", "x-ray", "xray", "check-up", "checkup", "emergency"],
    "pricing": ["price", "cost", "how much", "fee", "charge", "expensive", "afford", "cheap", "pay", "dollar", "rate"],
    "insurance": ["insurance", "accept insurance", "dental plan", "delta", "cigna", "aetna", "metlife", "bluecross", "coverage", "in-network", "out of network"],
    "payment": ["payment", "pay", "credit card", "cash", "financing", "carecredit", "payment plan", "installment"],
    "emergency": ["emergency", "urgent", "pain", "broken tooth", "knocked out", "bleeding", "swollen", "abscess", "after hours", "walk-in", "walk in", "same day"],
    "about": ["about", "who are you", "tell me about", "experience", "years", "credential", "certified", "accredit", "award", "team", "doctor", "dentist", "staff", "why choose", "special", "different", "unique", "reputation", "review"],
    "contact": ["phone", "call", "contact", "reach", "number", "email"],
}


def _get_company_info_response(topic, admin_id=1):
    """Build a dynamic response from saved company info."""
    info = db.get_company_info(admin_id)

    field_map = {
        "hours": "business_hours",
        "location": "address",
        "services": "services",
        "pricing": "pricing_insurance",
        "insurance": "pricing_insurance",
        "payment": "pricing_insurance",
        "emergency": "emergency_info",
        "about": "about",
        "contact": "phone",
    }

    field = field_map.get(topic)
    if not field:
        return None

    # If no company info or field is empty, tell the user it's not available yet
    if not info or not info.get(field):
        friendly_names = {
            "hours": "business hours",
            "location": "address",
            "services": "services",
            "pricing": "pricing information",
            "insurance": "insurance information",
            "payment": "payment options",
            "emergency": "emergency information",
            "about": "practice details",
            "contact": "contact information",
        }
        label = friendly_names.get(topic, "that information")
        return (
            f"I'm sorry, our {label} haven't been set up yet. "
            f"Please call us directly or **leave your contact info** and we'll get back to you!\n\n"
            f"I can also help you **book an appointment** or find the right specialist for your needs."
        )

    biz_name = _fix_spelling_general(info.get("business_name") or "our office")
    content = info[field]

    # Use OpenAI to reformat the raw data into a clean, professional response
    if dental_ai.is_configured():
        formatted = _reformat_with_ai(topic, content, biz_name)
        if formatted:
            return formatted

    # Fallback: fix spelling locally and format
    cleaned_content = _fix_spelling_general(content)

    prefix_map = {
        "hours": f"Here are **{biz_name}**'s hours:\n\n",
        "location": f"We're located at:\n\n",
        "services": f"Here are the services we offer at **{biz_name}**:\n\n",
        "pricing": f"Here's our pricing information:\n\n",
        "insurance": f"Here's our insurance and coverage info:\n\n",
        "payment": f"Here are our payment options:\n\n",
        "emergency": f"Here's our emergency information:\n\n",
        "about": f"Here's about **{biz_name}**:\n\n",
        "contact": f"You can reach us at:\n\n",
    }

    response = prefix_map.get(topic, "") + cleaned_content
    response += "\n\nWould you like to **book an appointment** or ask another question?"
    return response


def _fix_spelling_general(text):
    """Fix common misspellings in any text using a general English word list + edit distance."""
    # Common words that appear in dental office info
    _COMMON_WORDS = {
        "opens", "open", "from", "every", "day", "days", "excluding", "except",
        "friday", "fridays", "saturday", "saturdays", "sunday", "sundays",
        "monday", "mondays", "tuesday", "tuesdays", "wednesday", "wednesdays",
        "thursday", "thursdays", "morning", "afternoon", "evening", "night",
        "closed", "available", "hours", "until", "through", "between", "and",
        "the", "dentist", "dental", "clinic", "office", "practice", "doctor",
        "cleaning", "whitening", "filling", "fillings", "extraction", "braces",
        "implant", "implants", "crown", "crowns", "bridge", "bridges", "veneer",
        "veneers", "root", "canal", "checkup", "consultation", "surgery",
        "orthodontics", "pediatric", "cosmetic", "emergency", "general",
        "insurance", "accepted", "payment", "plans", "cash", "credit", "card",
        "financing", "price", "pricing", "cost", "free", "consultation",
        "located", "location", "address", "street", "avenue", "road", "drive",
        "main", "north", "south", "east", "west", "center", "central", "park",
        "suite", "floor", "building", "parking", "phone", "call", "email",
        "clinic", "hospital", "smile", "bright", "white", "pearl", "diamond",
        "star", "golden", "silver", "royal", "premier", "advanced", "modern",
        "gentle", "perfect", "happy", "healthy", "total",
        "contact", "walk-ins", "walkins", "welcome", "appointment", "appointments",
        "required", "recommended", "patients", "patient", "new", "existing",
        "accept", "provide", "offer", "service", "services", "treatment",
        "treatments", "professional", "experienced", "certified", "licensed",
        "specialist", "specialists", "care", "quality", "best", "trusted",
        "years", "experience", "serving", "community", "family", "children",
        "adults", "seniors", "all", "ages", "comprehensive", "preventive",
        "restorative", "aesthetic", "oral", "health", "hygiene", "exam",
    }

    words = text.split()
    result = []
    for word in words:
        # Extract just letters for matching, preserve original punctuation
        clean = re.sub(r'[^a-zA-Z]', '', word).lower()
        if not clean or len(clean) <= 2:
            result.append(word)
            continue

        # If already a known word, keep it
        if clean in _COMMON_WORDS:
            result.append(word)
            continue

        # Find closest match using edit distance
        best_match = None
        best_dist = 3  # Max edit distance to consider
        for known in _COMMON_WORDS:
            if abs(len(known) - len(clean)) > 2:
                continue
            dist = _edit_distance(clean, known)
            if dist < best_dist:
                best_dist = dist
                best_match = known

        if best_match and best_dist <= 2:
            # Preserve capitalization of first letter
            if word[0].isupper():
                best_match = best_match.capitalize()
            # Preserve any trailing punctuation
            trailing = re.sub(r'^[a-zA-Z]+', '', word)
            result.append(best_match + trailing)
        else:
            result.append(word)

    return ' '.join(result)


def _reformat_with_ai(topic, raw_content, biz_name):
    """Use OpenAI to reformat raw company info into a clean, professional chatbot response."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=dental_ai.OPENAI_API_KEY)

        topic_label = {
            "hours": "business hours",
            "location": "address/location",
            "services": "services offered",
            "pricing": "pricing and insurance",
            "insurance": "insurance information",
            "payment": "payment options",
            "emergency": "emergency information",
            "about": "about the practice",
            "contact": "contact information",
        }.get(topic, topic)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"""You are a friendly dental office chatbot for {biz_name}.
The admin has saved the following raw {topic_label} data. Your job is to:
1. Fix any spelling or grammar mistakes
2. Present it in a clean, well-formatted way using **bold** for key info
3. Keep the same information — do NOT add or invent anything
4. Be concise and professional
5. End with asking if they'd like to book an appointment or ask another question
6. Use line breaks and bullet points where appropriate"""},
                {"role": "user", "content": f"Here is the raw {topic_label} data to reformat:\n\n{raw_content}"},
            ],
            max_tokens=300,
            temperature=0.3,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"[reformat_ai] Error: {e}")
        return None


# ── Symptom-to-Specialty mapping ──
SYMPTOM_SPECIALTY_MAP = {
    "Orthodontist": [
        "jaw", "bite", "overbite", "underbite", "crossbite", "open bite",
        "misalign", "crooked", "braces", "alignment", "straighten", "gap between teeth",
        "upper jaw", "lower jaw", "jaw forward", "jaw backward", "teeth crowding",
        "crowded teeth", "spacing", "malocclusion", "invisalign", "retainer",
    ],
    "Endodontist": [
        "root canal", "tooth infection", "infected tooth", "abscess", "tooth abscess",
        "severe tooth pain", "throbbing pain", "deep cavity", "pulp", "nerve pain",
        "tooth sensitivity to hot", "sensitivity to cold", "cracked tooth pain",
        "tooth hurting", "teeth hurting", "tooth hurt", "teeth hurt", "toothache",
        "tooth ache", "teeth ache", "tooth pain", "teeth pain", "molar pain",
        "sharp pain in tooth", "tooth is killing", "painful tooth",
        "teeth is hurting", "tooth is hurting", "teeth are hurting",
        "teeth is paining", "tooth is paining",
    ],
    "Periodontist": [
        "gum", "bleeding gum", "gum disease", "receding gum", "swollen gum",
        "gingivitis", "periodontitis", "loose tooth", "bone loss", "gum surgery",
        "deep cleaning", "gum infection", "gum pain", "gum recession",
    ],
    "Oral & Maxillofacial Surgeon": [
        "wisdom tooth", "wisdom teeth", "impacted", "jaw surgery", "facial trauma",
        "jaw fracture", "broken jaw", "oral surgery", "tumor", "cyst",
        "cleft", "jaw reconstruction", "facial surgery", "biopsy",
    ],
    "Prosthodontist": [
        "denture", "false teeth", "missing teeth", "crown", "bridge", "implant",
        "replacement teeth", "lost tooth", "tooth replacement", "partial denture",
        "full denture", "veneer", "cosmetic restoration",
    ],
    "Pediatric Dentist": [
        "child", "kid", "baby tooth", "baby teeth", "baby", "my son", "my daughter",
        "toddler", "infant", "children", "pediatric", "kids teeth", "my kid",
        "little one", "boy teeth", "girl teeth", "son teeth", "daughter teeth",
    ],
    "Cosmetic Dentist": [
        "whitening", "teeth whitening", "whiter", "stain", "discolor", "yellow teeth",
        "smile makeover", "cosmetic", "bonding", "reshape", "aesthet",
        "ugly teeth", "teeth look", "beautiful smile", "nice smile", "white teeth",
        "brighter teeth", "brighten", "bleach",
    ],
    "Dental Anesthesiologist": [
        "sedation", "anesthesia", "afraid of dentist", "dental anxiety",
        "dental phobia", "nervous", "put me to sleep", "pain free",
    ],
    "Orofacial Pain Specialist": [
        "tmj", "jaw pain", "face pain", "clicking jaw", "jaw lock",
        "jaw clicking", "jaw popping", "headache from jaw", "facial pain",
        "temporomandibular",
    ],
    "General Dentist": [
        "cleaning", "checkup", "check-up", "cavity", "filling", "routine",
        "dental exam", "teeth cleaning", "general", "regular visit",
    ],
    "Family Dentist": [
        "family", "whole family", "family dental",
    ],
    "Oral Pathologist": [
        "mouth sore", "oral lesion", "mouth disease", "tongue sore",
        "white patch", "red patch", "oral cancer", "mouth cancer",
    ],
    "Oral Radiologist": [
        "x-ray", "xray", "scan", "ct scan", "panoramic", "dental imaging",
    ],
}


def find_symptom_specialty(text):
    """Match patient symptoms/description to a dental specialty."""
    lower = text.lower()
    # Also check a simplified version (remove filler words for better matching)
    simplified = re.sub(r'\b(is|are|am|was|were|my|me|i|the|a|an|it|so|very|really|too|has been|have been)\b', ' ', lower)
    simplified = re.sub(r'\s+', ' ', simplified).strip()
    scores = {}
    for specialty, keywords in SYMPTOM_SPECIALTY_MAP.items():
        score = sum(1 for kw in keywords if kw in lower or kw in simplified)
        if score > 0:
            scores[specialty] = score

    if not scores:
        return None

    # If child-related words are present, boost Pediatric Dentist
    child_words = ["baby", "child", "kid", "son", "daughter", "toddler", "infant", "children"]
    if any(w in lower for w in child_words) and "Pediatric Dentist" in scores:
        scores["Pediatric Dentist"] += 10

    return max(scores, key=scores.get)


def _build_symptom_response(specialty, admin_id):
    """Build a response recommending a specialist and showing available doctors."""
    # Get active doctors in this specialty
    all_doctors = db.get_doctors(admin_id)
    matching_doctors = [d for d in all_doctors if d.get("status") == "active" and d.get("specialty") == specialty]

    response = f"Based on what you're describing, I'd recommend seeing an **{specialty}**."

    if matching_doctors:
        if len(matching_doctors) == 1:
            doc = matching_doctors[0]
            response += f"\n\nWe have **Dr. {doc['name']}** ({specialty}) available for you."
        else:
            doc_list = "\n".join([f"**{i+1}.** Dr. {d['name']}" for i, d in enumerate(matching_doctors)])
            response += f"\n\nHere are our {specialty} doctors:\n\n{doc_list}"
        response += "\n\nWould you like to **book an appointment**?"
    else:
        # No doctors in this specialty — check if any doctors at all
        active_doctors = [d for d in all_doctors if d.get("status") == "active"]
        if active_doctors:
            response += "\n\nWe don't currently have a specialist in that category, but our other doctors may be able to help."
            response += "\n\nWould you like to **book an appointment** with one of our available doctors?"
        else:
            response += "\n\nWould you like to **book an appointment** or **leave your contact info** so we can get back to you?"

    return response


def find_dental_topic(text):
    """Check if the message matches a dental office question category."""
    lower = text.lower()
    scores = {}
    for topic, keywords in DENTAL_KEYWORD_MAP.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score > 0:
            scores[topic] = score
    return max(scores, key=scores.get) if scores else None


def find_topic(text):
    lower = text.lower()
    scores = {}
    for topic, keywords in KEYWORD_MAP.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score > 0:
            scores[topic] = score
    return max(scores, key=scores.get) if scores else None


def generate_ai_response(user_message, context):
    prompt = f"<|system|>\n{SYSTEM_MSG}{context}</s>\n<|user|>\n{user_message}</s>\n<|assistant|>\n"
    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=384)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model.generate(
            **inputs, max_new_tokens=60, temperature=0.7,
            do_sample=True, repetition_penalty=1.3, pad_token_id=tokenizer.eos_token_id,
        )
    new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
    response = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    for stop in ["</s>", "<|user|>", "<|system|>", "\n\n\n"]:
        if stop in response:
            response = response[:response.index(stop)].strip()
    return response if len(response) > 10 else None


# ══════════════════════════════════════════════
#  Spell Correction — fix misspellings before processing
# ══════════════════════════════════════════════

# Known words the chatbot needs to understand
_VOCABULARY = {
    # Booking
    "book": ["bok", "bkoo", "boook", "boo", "bokk", "buk"],
    "appointment": ["appoitmnet", "appointmnt", "apointment", "appointmet", "appoitment", "appoint", "appoinment", "appointemnt", "appointmnet"],
    "schedule": ["shedule", "scedule", "scheduel", "schedul", "shcedule"],
    "reserve": ["reserv", "resrve", "resereve"],
    "available": ["availble", "avialable", "avalable", "availabe", "avaliable"],
    "meeting": ["meating", "meetin", "meting", "meetng"],
    "slot": ["slott", "slto", "solt"],
    # Lead capture
    "contact": ["contcat", "conact", "contac", "cotact"],
    "number": ["numbr", "nubmer", "numbe", "numbeer"],
    "phone": ["phon", "fone", "phoen", "pohne"],
    "call": ["cal", "cll", "calll"],
    # General
    "want": ["wnat", "watn", "wnt", "wnta"],
    "hello": ["helo", "hllo", "helllo", "heloo"],
    "pricing": ["pricng", "priceing", "pricingg", "pricin"],
    "features": ["featurs", "feaures", "fetures", "featrues"],
    "help": ["hlep", "halp", "hep", "helpp"],
    "cancel": ["cancle", "cancl", "canel", "canecl"],
    "please": ["pleas", "pls", "plz", "pleaes", "plese"],
    "thanks": ["thnks", "thanx", "thansk", "thnaks", "thx"],
    "yes": ["yse", "ys", "yess", "yea", "yeah", "yep", "ya"],
    "no": ["noo", "nah", "nope"],
    "information": ["informaiton", "infromation", "infomation", "informaton"],
    "interested": ["intrested", "intreseted", "intersted", "intreested"],
    "question": ["qustion", "quesiton", "questin", "qestion"],
    "tomorrow": ["tomorow", "tommorow", "tommorrow", "tomorrw", "tmrw", "tmr"],
    "today": ["tday", "2day", "toady", "todya"],
}

# Build reverse lookup: misspelling -> correct word
_SPELL_MAP = {}
for correct, misspellings in _VOCABULARY.items():
    for ms in misspellings:
        _SPELL_MAP[ms] = correct


def _edit_distance(a, b):
    """Simple Levenshtein distance."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if len(b) == 0:
        return len(a)
    prev = range(len(b) + 1)
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[len(b)]


def correct_spelling(text):
    """Fix misspellings in user input using vocabulary + edit distance."""
    words = text.lower().split()
    corrected = []
    for word in words:
        # Clean punctuation for matching
        clean = re.sub(r'[^a-z]', '', word)
        if not clean or len(clean) <= 2:
            corrected.append(word)
            continue

        # Direct lookup in spelling map
        if clean in _SPELL_MAP:
            # Preserve original casing/punctuation context
            corrected.append(word.lower().replace(clean, _SPELL_MAP[clean]))
            continue

        # Already a known correct word
        if clean in _VOCABULARY:
            corrected.append(word)
            continue

        # Fuzzy match: try edit distance against vocabulary
        best_match = None
        best_dist = 999
        for correct_word in _VOCABULARY:
            if len(correct_word) >= 4 and len(clean) >= 4:
                dist = _edit_distance(clean, correct_word)
                max_allowed = 1 if len(clean) <= 5 else 2
                if dist <= max_allowed and dist < best_dist:
                    best_dist = dist
                    best_match = correct_word

        if best_match:
            corrected.append(word.lower().replace(clean, best_match))
        else:
            corrected.append(word)

    return " ".join(corrected)


# ══════════════════════════════════════════════
#  Intent Detection — route to correct flow
# ══════════════════════════════════════════════

def detect_intent(text):
    """Detect user intent using the smart intent classifier.
    Uses TF-IDF scoring against intent examples + structural analysis
    to understand WHAT the user actually wants — not just keyword matching.
    """
    intent, confidence = intent_classifier.classify(text)

    # Map classifier intents to flow intents
    # "availability_question" and "question" both go to "qa" —
    # they're answered, not routed to booking
    if intent in ("question", "availability_question", "greeting", "farewell"):
        return "qa"
    if intent == "cancel":
        return "cancel"
    if intent == "lead_capture":
        return "lead_capture"
    if intent == "booking":
        return "booking"
    return "qa"


# ══════════════════════════════════════════════
#  Booking Flow State Machine
# ══════════════════════════════════════════════

def _extract_email(text):
    """Try to extract an email address from natural text."""
    match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
    return match.group(0).lower() if match else None


def _extract_phone(text):
    """Try to extract a phone number from natural text."""
    # Remove common filler words
    cleaned = re.sub(r'\b(my|number|is|phone|call|me|at|its|it\'s|here)\b', '', text, flags=re.IGNORECASE)
    digits = re.sub(r'[^\d+\-() ]', '', cleaned).strip()
    if len(re.sub(r'\D', '', digits)) >= 7:
        return digits
    # Try just pulling all digits
    all_digits = re.sub(r'\D', '', text)
    if len(all_digits) >= 7:
        return all_digits
    return None


def _generate_upcoming_dates(num_days=7):
    """Generate upcoming weekday dates as dropdown items."""
    today = datetime.now()
    dates = []
    i = 1
    while len(dates) < num_days:
        d = today + timedelta(days=i)
        if d.weekday() < 5:  # Mon-Fri only
            day_label = d.strftime("%A, %B %d")
            # Show "Tomorrow" for the next day if it's a weekday
            if i == 1:
                day_label = f"Tomorrow — {day_label}"
            dates.append({
                "name": d.strftime("%A, %B %d"),
                "display": day_label,
                "iso": d.strftime("%Y-%m-%d"),
            })
        i += 1
    return dates


def _generate_doctor_slots(doctor, breaks=None):
    """Generate appointment time slots from a doctor's start_time, end_time, and appointment_length.
    Skips any time ranges that overlap with breaks."""
    def parse_12h(time_str):
        """Parse '09:00 AM' to total minutes since midnight."""
        if not time_str or time_str == '00:00 AM' or time_str == '00:00':
            return None
        m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str, re.IGNORECASE)
        if not m:
            return None
        h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if ampm == 'PM' and h < 12:
            h += 12
        if ampm == 'AM' and h == 12:
            h = 0
        return h * 60 + mi

    start_min = parse_12h(doctor.get("start_time"))
    end_min = parse_12h(doctor.get("end_time"))
    if start_min is None or end_min is None or start_min >= end_min:
        return []

    length = doctor.get("appointment_length") or 60
    if isinstance(length, str):
        length = int(length)

    def mins_to_12h(mins):
        h = mins // 60
        m = mins % 60
        ampm = "AM" if h < 12 else "PM"
        display_h = h if h <= 12 else h - 12
        if display_h == 0:
            display_h = 12
        return f"{display_h:02d}:{m:02d} {ampm}"

    # Parse break times into minute ranges
    break_ranges = []
    if breaks:
        for b in breaks:
            bs = parse_12h(b.get("start_time", ""))
            be = parse_12h(b.get("end_time", ""))
            if bs is not None and be is not None:
                break_ranges.append((bs, be))

    slots = []
    current = start_min
    while current + length <= end_min:
        h = current // 60
        m = current % 60
        slot_end = current + length
        # Check if this slot overlaps any break
        overlaps_break = False
        for bs, be in break_ranges:
            if current < be and slot_end > bs:
                overlaps_break = True
                # Jump past the break
                current = be
                break
        if overlaps_break:
            continue
        start_str = mins_to_12h(current)
        end_str = mins_to_12h(slot_end)
        time_str = f"{start_str} - {end_str}"
        slots.append({"time": time_str, "hour": h, "minute": m})
        current += length

    return slots


def _extract_time(text, available_slots=None):
    """Extract a time from natural text, with fuzzy matching against available slots."""
    lower = text.lower().strip()

    # Exact match against available slots (e.g. from dropdown selection like "09:00 AM - 10:00 AM")
    if available_slots:
        for s in available_slots:
            if s["time"].lower() == lower:
                return s["time"]

    # Handle ordinal references: "the first one", "the second", "3rd slot"
    ordinals = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2,
                "fourth": 3, "4th": 3, "fifth": 4, "5th": 4, "sixth": 5, "6th": 5,
                "seventh": 6, "7th": 6, "eighth": 7, "8th": 7, "last": -1}
    for word, idx in ordinals.items():
        if word in lower and available_slots:
            actual_idx = idx if idx >= 0 else len(available_slots) - 1
            if 0 <= actual_idx < len(available_slots):
                return available_slots[actual_idx]["time"]

    # Handle "earliest", "latest", "morning", "afternoon"
    if available_slots:
        if any(w in lower for w in ["earliest", "first available", "soonest", "early", "morning"]):
            for s in available_slots:
                if s["hour"] < 12:
                    return s["time"]
            return available_slots[0]["time"]
        if any(w in lower for w in ["latest", "last available", "late", "end of day"]):
            return available_slots[-1]["time"]
        if "afternoon" in lower:
            for s in available_slots:
                if s["hour"] >= 12:
                    return s["time"]
        if "lunch" in lower:
            for s in available_slots:
                if 11 <= s["hour"] <= 13:
                    return s["time"]

    # Try to parse a direct time value
    time_patterns = [
        r'(\d{1,2}:\d{2}\s*(?:am|pm))',  # 2:00 pm
        r'(\d{1,2}\s*(?:am|pm))',          # 2pm, 2 pm
        r'(\d{1,2}:\d{2})',                # 14:00
    ]
    for pattern in time_patterns:
        match = re.search(pattern, lower)
        if match:
            return match.group(1).strip()

    # If the whole message looks like a time (just a number with optional am/pm)
    simple = re.match(r'^(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)?\.?$', lower)
    if simple:
        num = simple.group(1)
        ampm = (simple.group(2) or "").replace(".", "")
        if ampm:
            return f"{num} {ampm}"
        # Guess am/pm from context
        h = int(num)
        if 1 <= h <= 6:
            return f"{num} pm"
        return num

    return None


def handle_booking(session, user_message, corrected_message=None):
    step = session["step"]
    data = session["data"]
    corrected = corrected_message or correct_spelling(user_message)
    lower = corrected.lower().strip()

    # At any step, handle conversational questions
    if step and step not in (None, "ask_name"):
        # "What slots/times are available?" — show slots if we have a date
        if any(w in lower for w in ["available", "slots", "times", "options", "what time", "show me", "list"]):
            if data.get("date_str") and step in ("get_time",):
                # Re-show the slots
                result, error = cal.get_available_slots(data["date_str"])
                if not error:
                    slots = result["slots"]
                    slot_list = "  ".join([f"**{s['time']}**" for s in slots[:8]])
                    return f"Here are the available slots on **{data['date_display']}**:\n\n{slot_list}\n\nJust tell me which time you'd like!"
            elif step == "get_date":
                return "Sure! Just tell me which day you're interested in and I'll show you all available times. For example: 'tomorrow', 'Monday', 'next Friday', or a specific date like 'April 15'."

        # "Can I change the date?" — go back to date step
        if any(w in lower for w in ["different date", "change date", "other date", "another date", "pick another day", "change day"]):
            if step in ("get_time",):
                session["step"] = "get_date"
                doctor_id = data.get("doctor_id")
                off_dates = db.get_doctor_off_dates(doctor_id) if doctor_id else []
                session["_ui_options"] = {"type": "calendar", "doctor_id": doctor_id, "off_dates": list(off_dates)}
                return "No problem! Pick a different date:"

    # Step 1: Ask for name
    if step is None or step == "ask_name":
        session["step"] = "get_name"
        return "I'd love to help you book an appointment! What's your full name?"

    # Step 2: Got name, ask for doctor (if doctors exist) or email
    if step == "get_name":
        # Accept anything as a name (people type naturally)
        name = user_message.strip()
        # Clean up obvious non-name prefixes
        name = re.sub(r'^(my name is|i\'?m|it\'?s|name:?|hi,?\s*(i\'?m)?)\s*', '', name, flags=re.IGNORECASE).strip()
        if len(name) < 2:
            return "I didn't quite catch your name. Could you tell me your full name?"
        data["name"] = name.title()

        # Check if doctors are configured — if so, ask what type of doctor
        admin_id = data.get("_admin_id", 1)
        all_doctors = db.get_doctors(admin_id)
        doctors = [d for d in all_doctors if d.get("status") == "active"]
        if doctors:
            # Get unique categories from active doctors
            categories = list(set(d.get("specialty", "General Dentist") for d in doctors if d.get("specialty")))
            categories.sort()
            if len(categories) > 1:
                data["_all_doctors"] = doctors
                data["_categories"] = categories
                session["step"] = "get_category"
                session["_ui_options"] = {"type": "categories", "items": [{"name": c} for c in categories]}
                return f"Nice to meet you, {data['name']}! What type of doctor would you like to see?"
            else:
                # Only one category or no categories — skip to doctor selection
                data["_doctors"] = doctors
                session["step"] = "get_doctor"
                session["_ui_options"] = {"type": "doctors", "items": [{"name": d["name"], "specialty": d.get("specialty", "General"), "availability": d.get("availability", "Mon-Fri")} for d in doctors]}
                return f"Nice to meet you, {data['name']}! Which doctor would you like to see?"
        else:
            session["step"] = "get_email"
            return f"Nice to meet you, {data['name']}! What's your email address? (We'll send you a confirmation)"

    # Step 2a: Got category choice, show doctors in that category
    if step == "get_category":
        categories = data.get("_categories", [])
        all_doctors = data.get("_all_doctors", [])
        chosen_cat = None

        # Try number selection
        num_match = re.search(r'(\d+)', lower)
        if num_match:
            idx = int(num_match.group(1)) - 1
            if 0 <= idx < len(categories):
                chosen_cat = categories[idx]

        # Try name matching
        if not chosen_cat:
            for cat in categories:
                if cat.lower() in lower or lower in cat.lower():
                    chosen_cat = cat
                    break
            # Fuzzy: check if any word matches
            if not chosen_cat:
                for cat in categories:
                    for word in lower.split():
                        if len(word) >= 3 and word in cat.lower():
                            chosen_cat = cat
                            break

        if not chosen_cat:
            session["_ui_options"] = {"type": "categories", "items": [{"name": c} for c in categories]}
            return f"I couldn't match that. Please pick a specialty:"

        # Filter doctors by chosen category
        doctors = [d for d in all_doctors if d.get("specialty") == chosen_cat]
        if not doctors:
            session["_ui_options"] = {"type": "categories", "items": [{"name": c} for c in categories]}
            return f"No active doctors found for **{chosen_cat}**. Please pick another specialty:"

        data["_doctors"] = doctors
        data["_chosen_category"] = chosen_cat

        session["step"] = "get_doctor"
        session["_ui_options"] = {"type": "doctors", "items": [{"name": d["name"], "specialty": d.get("specialty", "General"), "availability": d.get("availability", "Mon-Fri")} for d in doctors]}
        return f"Here are our **{chosen_cat}** doctors:"

    # Step 2b: Got doctor choice, ask for email
    if step == "get_doctor":
        doctors = data.get("_doctors", [])
        chosen = None

        # Try number selection
        num_match = re.search(r'(\d+)', lower)
        if num_match:
            idx = int(num_match.group(1)) - 1
            if 0 <= idx < len(doctors):
                chosen = doctors[idx]

        # Try name matching
        if not chosen:
            for d in doctors:
                if d["name"].lower() in lower or lower in d["name"].lower():
                    chosen = d
                    break
            # Fuzzy: check if any word matches
            if not chosen:
                for d in doctors:
                    for word in lower.split():
                        if len(word) >= 3 and word in d["name"].lower():
                            chosen = d
                            break

        if not chosen:
            session["_ui_options"] = {"type": "doctors", "items": [{"name": d["name"], "specialty": d.get("specialty", "General"), "availability": d.get("availability", "Mon-Fri")} for d in doctors]}
            return f"I couldn't match that to a doctor. Please pick one:"

        data["doctor_name"] = chosen["name"]
        data["doctor_id"] = chosen["id"]
        session["step"] = "get_date"
        off_dates = db.get_doctor_off_dates(chosen["id"])
        session["_ui_options"] = {"type": "calendar", "doctor_id": chosen["id"], "off_dates": list(off_dates)}
        return f"Great choice! You'll be seeing **Dr. {chosen['name']}**.\n\nWhen would you like to come in?"

    # Step 3: Got date, show time slot dropdown
    if step == "get_date":
        result, error = cal.get_available_slots(user_message)
        if error:
            doctor_id = data.get("doctor_id")
            off_dates = db.get_doctor_off_dates(doctor_id) if doctor_id else []
            session["_ui_options"] = {"type": "calendar", "doctor_id": doctor_id, "off_dates": list(off_dates)}
            return f"I had trouble understanding that date. Please pick a day:"

        data["date_str"] = user_message
        data["date_display"] = result["date_display"]
        data["date_iso"] = result["date"].isoformat()

        # Check if this date is a doctor's off day
        doctor_id = data.get("doctor_id")
        if doctor_id:
            off_dates = db.get_doctor_off_dates(doctor_id)
            if data["date_iso"] in off_dates:
                doctor = db.get_doctor_by_id(doctor_id)
                doc_name = doctor["name"] if doctor else "The doctor"
                session["_ui_options"] = {
                    "type": "calendar",
                    "doctor_id": doctor_id,
                    "off_dates": list(off_dates),
                }
                return f"Sorry, Dr. **{doc_name}** is not available on **{data['date_display']}**. Please pick another date:"

        # Generate slots from doctor's schedule
        slots = []
        if doctor_id:
            doctor = db.get_doctor_by_id(doctor_id)
            if doctor and doctor.get("start_time") and doctor["start_time"] != "00:00 AM":
                doctor_breaks = db.get_doctor_breaks(doctor_id)
                slots = _generate_doctor_slots(doctor, breaks=doctor_breaks)

        if not slots:
            slots = result["slots"]

        # Filter out already booked times for this doctor on this date
        booked_times = []
        if doctor_id:
            booked_times = db.get_booked_times(doctor_id, result["date"].isoformat())

        def _is_booked(slot_time, booked_list):
            """Check if a slot is booked — handles both range and single time formats."""
            if slot_time in booked_list:
                return True
            # Compare start time of range (e.g. "09:00 AM - 10:00 AM") against booked "09:00 AM"
            if " - " in slot_time:
                start_part = slot_time.split(" - ")[0].strip()
                return start_part in booked_list
            return False

        available_slots = []
        booked_slot_names = []
        for s in slots:
            if _is_booked(s["time"], booked_times):
                booked_slot_names.append(s["time"])
            else:
                available_slots.append(s)

        data["available_slots"] = available_slots

        # Build dropdown — available slots are selectable, booked ones shown as read-only
        dropdown_items = []
        for s in slots:
            item = {"name": s["time"], "hour": s["hour"], "minute": s.get("minute", 0)}
            if _is_booked(s["time"], booked_times):
                item["booked"] = True
            dropdown_items.append(item)

        session["_ui_options"] = {"type": "timeslots", "items": dropdown_items}
        session["step"] = "get_time"
        return f"Here are the available times on **{data['date_display']}** for **Dr. {data.get('doctor_name', '')}**:"

    # Step 4: Got time, ask for email
    if step == "get_time":
        time_str = _extract_time(user_message, data.get("available_slots", []))
        if not time_str:
            slots = data.get("available_slots", [])
            sample = ", ".join([s["time"] for s in slots[:4]]) if slots else "10:00 AM, 2:00 PM"
            return f"I couldn't quite understand that time. You can say:\n\n- A specific time like **{sample}**\n- **the earliest** or **the latest**\n- **morning** or **afternoon**\n\nWhat time would you like?"

        data["chosen_time"] = time_str
        session["step"] = "get_email"
        return f"**{time_str}** on **{data['date_display']}** — great choice!\n\nWhat's your email address? (We'll send you a confirmation)"

    # Step 5: Got email, ask for phone
    if step == "get_email":
        extracted_email = _extract_email(user_message)
        if extracted_email:
            data["email"] = extracted_email
            session["step"] = "get_phone"
            return "Got it! And your phone number? (In case we need to reach you)"
        if any(w in lower for w in ["skip", "no email", "don't have", "dont have", "none", "no thanks", "n/a", "na"]):
            data["email"] = ""
            session["step"] = "get_phone"
            return "No worries! What's your phone number instead?"
        return "I couldn't find a valid email in that. Could you type it out? Example: john@example.com\n\nOr say **skip** if you'd rather not provide one."

    # Step 6: Got phone, finalize booking
    if step == "get_phone":
        extracted_phone = _extract_phone(user_message)
        if not extracted_phone:
            return "I couldn't find a valid phone number. Could you try again? Example: (555) 123-4567 or 5551234567"

        data["phone"] = extracted_phone
        time_str = data.get("chosen_time", "")

        booking_result, error = cal.book_appointment(
            data["date_str"], time_str,
            data["name"], data.get("email", "")
        )
        if error:
            return error + "\n\nPlease pick another time from the available slots."

        # Save to database
        db.save_booking(
            customer_name=data["name"],
            customer_email=data.get("email", ""),
            customer_phone=data["phone"],
            date=booking_result["date"],
            time=booking_result["time"],
            calendar_event_id=booking_result.get("calendar_event_id", ""),
            doctor_id=data.get("doctor_id", 0),
            doctor_name=data.get("doctor_name", ""),
            admin_id=data.get("_admin_id", 0),
        )

        # Send confirmation emails
        if data.get("email"):
            email.send_booking_confirmation_customer(
                data["name"], data["email"],
                booking_result["date_display"], booking_result["time"]
            )
        email.send_booking_notification_owner(
            data["name"], data.get("email", ""), data["phone"],
            booking_result["date_display"], booking_result["time"]
        )

        # Reset session
        session["flow"] = None
        session["step"] = None
        session["data"] = {}

        confirmation = (
            f"Awesome, you're all set!\n\n"
            f"**Name:** {data['name']}\n"
        )
        if data.get("doctor_name"):
            confirmation += f"**Doctor:** Dr. {data['doctor_name']}\n"
        confirmation += (
            f"**Date:** {booking_result['date_display']}\n"
            f"**Time:** {booking_result['time']}\n"
        )
        if data.get("email"):
            confirmation += f"\nA confirmation email has been sent to **{data['email']}**."
        confirmation += "\n\nIs there anything else I can help you with?"
        return confirmation

    return "Something went wrong with the booking. Let me start over. Would you like to book an appointment?"


# ══════════════════════════════════════════════
#  Cancel Appointment Flow
# ══════════════════════════════════════════════

def handle_cancel_appointment(session, user_message, admin_id):
    step = session["step"]
    data = session["data"]
    lower = user_message.strip().lower()

    # Abort if user says nevermind
    if lower in ("nevermind", "never mind", "stop", "go back"):
        session["flow"] = None
        session["step"] = None
        session["data"] = {}
        return "No problem! How else can I help you?"

    # Step 1: Get date — parse natural language ("this monday", "april 10", etc.)
    if step == "get_date":
        from calendar_service import _parse_date
        parsed_date = _parse_date(user_message)
        if not parsed_date:
            return "I didn't understand that date. Could you try again? (e.g. Monday, April 10, tomorrow)"

        date_iso = parsed_date.isoformat()
        date_display = parsed_date.strftime("%A, %B %d, %Y")
        bookings = db.find_bookings_by_date(admin_id, date_iso)

        if not bookings:
            session["flow"] = None
            session["step"] = None
            session["data"] = {}
            return f"There are no active appointments on **{date_display}**. Say **cancel my appointment** to try a different date."

        data["_cancel_date"] = date_iso
        data["_cancel_date_display"] = date_display

        if len(bookings) == 1:
            b = bookings[0]
            data["_booking_to_cancel"] = b
            session["step"] = "confirm"
            doctor_info = f" with **Dr. {b['doctor_name']}**" if b.get("doctor_name") else ""
            return (f"I found one appointment on **{date_display}**:\n\n"
                    f"**{b['customer_name']}** — {b['time']}{doctor_info}\n\n"
                    f"Do you want to cancel this appointment? (yes/no)")

        # Multiple bookings on that date — show as dropdown
        data["_bookings_list"] = bookings
        session["step"] = "choose"
        lines = []
        for i, b in enumerate(bookings, 1):
            doctor_info = f" — Dr. {b['doctor_name']}" if b.get("doctor_name") else ""
            lines.append(f"**{i}.** {b['customer_name']} at {b['time']}{doctor_info}")
        session["_ui_options"] = {
            "type": "cancel_bookings",
            "items": [
                {"name": f"{b['customer_name']} — {b['time']}" + (f" (Dr. {b['doctor_name']})" if b.get("doctor_name") else ""), "index": i}
                for i, b in enumerate(bookings, 1)
            ]
        }
        return f"I found **{len(bookings)}** appointments on **{date_display}**:\n\n" + "\n".join(lines) + "\n\nWhich one do you want to cancel?"

    # Step 2: Choose which booking
    if step == "choose":
        bookings = data.get("_bookings_list", [])
        chosen = None

        # Try number selection
        num_match = re.search(r'(\d+)', lower)
        if num_match:
            idx = int(num_match.group(1)) - 1
            if 0 <= idx < len(bookings):
                chosen = bookings[idx]

        # Try name matching
        if not chosen:
            for b in bookings:
                if b.get("customer_name", "").lower() in lower or lower in b.get("customer_name", "").lower():
                    chosen = b
                    break
            if not chosen:
                for b in bookings:
                    if b.get("doctor_name", "").lower() in lower or lower in b.get("doctor_name", "").lower():
                        chosen = b
                        break

        if chosen:
            data["_booking_to_cancel"] = chosen
            session["step"] = "confirm"
            doctor_info = f" with **Dr. {chosen['doctor_name']}**" if chosen.get("doctor_name") else ""
            return (f"You selected:\n\n"
                    f"**{chosen['customer_name']}** — {chosen['time']}{doctor_info}\n\n"
                    f"Do you want to cancel this appointment? (yes/no)")

        return "I couldn't match that. Please pick a number from the list or say the patient name."

    # Step 3: Confirm cancellation
    if step == "confirm":
        if lower in ("yes", "yeah", "yep", "yea", "sure", "ok", "okay", "y", "yes please", "confirm"):
            booking = data.get("_booking_to_cancel")
            if booking:
                db.cancel_booking(booking["id"])
                doctor_info = f" with Dr. {booking['doctor_name']}" if booking.get("doctor_name") else ""
                date_display = data.get("_cancel_date_display", booking["date"])
                session["flow"] = None
                session["step"] = None
                session["data"] = {}
                return (f"Done! The appointment for **{booking['customer_name']}** on **{date_display}** at **{booking['time']}**{doctor_info} "
                        f"has been **cancelled**. The time slot is now free for others.\n\n"
                        f"Is there anything else I can help you with?")
        elif lower in ("no", "nah", "nope", "n", "no thanks"):
            session["flow"] = None
            session["step"] = None
            session["data"] = {}
            return "Okay, the appointment is still active. How else can I help you?"

        return "Please say **yes** to confirm the cancellation or **no** to keep it."

    # Fallback
    session["flow"] = None
    session["step"] = None
    session["data"] = {}
    return "Something went wrong. Say **cancel my appointment** to try again."


# ══════════════════════════════════════════════
#  Lead Capture Flow State Machine
# ══════════════════════════════════════════════

def handle_lead_capture(session, user_message):
    step = session["step"]
    data = session["data"]

    # Step 1: Ask for name
    if step is None or step == "ask_name":
        session["step"] = "get_name"
        return "No problem! I'd love to stay in touch. What's your name?"

    # Step 2: Got name, ask for phone
    if step == "get_name":
        data["name"] = user_message.strip().title()
        session["step"] = "get_phone"
        return f"Thanks, {data['name']}! What's the best phone number to reach you at?"

    # Step 3: Got phone, save lead
    if step == "get_phone":
        phone = re.sub(r'[^\d+\-() ]', '', user_message.strip())
        if len(re.sub(r'\D', '', phone)) >= 7:
            data["phone"] = phone

            # Save to database
            db.save_lead(name=data["name"], phone=data["phone"])

            # Notify business owner
            email.send_booking_notification_owner(
                data["name"], "", data["phone"], "N/A", "N/A"
            )

            # Reset session
            session["flow"] = None
            session["step"] = None
            session["data"] = {}

            return (
                f"Got it, {data['name']}! We've saved your info and someone from our team "
                f"will reach out to you at **{data['phone']}** soon.\n\n"
                f"In the meantime, feel free to ask me any questions about ChatGenius!"
            )
        else:
            return "That doesn't look like a valid phone number. Could you try again? Example: (555) 123-4567"

    return "Let me start over. Would you like to leave your contact information?"


def _ask_ai_during_booking(user_message, session, admin_id=1):
    """Ask the AI brain a question while the booking flow is paused."""
    doctors = db.get_doctors(admin_id)
    active_doctors = [d for d in doctors if d.get("status") == "active"]
    history = session.get("history", [])[-10:]

    # Claude for symptom/specialization questions
    if claude_specialist.is_configured() and claude_specialist.is_specialization_query(user_message):
        result = claude_specialist.analyze_symptoms(user_message, doctors=active_doctors, history=history)
        if result and result.get("reply"):
            return result["reply"]

    # Groq for everything else
    if message_interpreter.is_configured():
        company_info = db.get_company_info(admin_id)
        doctor_slots = {}
        for doc in active_doctors:
            doc_breaks = db.get_doctor_breaks(doc["id"])
            slots = _generate_doctor_slots(doc, breaks=doc_breaks)
            if slots:
                doctor_slots[doc["name"]] = [s["time"] for s in slots]
        result = message_interpreter.think_and_respond(
            user_message, company_info, active_doctors,
            doctor_slots=doctor_slots, history=history
        )
        if result and result.get("reply"):
            return result["reply"]

    # Offline fallback
    kb_result = dke.find_best_answer(user_message)
    if kb_result:
        answer = kb_result["answer"]
        if kb_result.get("follow_up"):
            answer += "\n\n" + kb_result["follow_up"]
        return answer

    return None


# ══════════════════════════════════════════════
#  Main Chat Handler
# ══════════════════════════════════════════════

def process_message(session_id, user_message, admin_id=1):
    session = get_session(session_id)

    # Step 0: Grok AI cleaner — runs FIRST on every message
    # Fixes spelling/grammar specifically for dental context (BrightSmile)
    grok_cleaned = grok_cleaner.clean(user_message, history=session.get("history"))

    # Step 1: AI interpreter — understands what the user REALLY means
    # Fixes typos, grammar, and garbled input using Groq LLM
    # Pass conversation history so it can resolve "him", "that doctor", etc.
    interpreted = message_interpreter.interpret(grok_cleaned, history=session.get("history"))

    # Step 2: Local spell-correct as additional cleanup
    corrected = correct_spelling(interpreted)
    lower = corrected.lower().strip()

    # Helper to save history and return response
    def _reply(response):
        session["history"].append({"role": "user", "content": user_message})
        session["history"].append({"role": "assistant", "content": response})
        # Keep last 20 messages (10 exchanges) to avoid token bloat
        if len(session["history"]) > 20:
            session["history"] = session["history"][-20:]
        return response

    # Detect if user wants to cancel an EXISTING appointment
    wants_cancel_appointment = bool(re.search(
        r"(cancel|delete|remove)\s+(my\s+)?(appointment|booking|reservation)",
        lower
    )) or bool(re.search(
        r"(i\s+want\s+to|i\s+need\s+to|can\s+i|please)\s+(cancel|delete|remove)\s+(my\s+)?(appointment|booking)",
        lower
    ))

    if wants_cancel_appointment and session["flow"] != "cancel_appointment":
        session["flow"] = "cancel_appointment"
        session["step"] = "get_date"
        session["data"] = {"_admin_id": admin_id}
        return _reply("I can help you cancel your appointment. What date is it on? (e.g. Monday, April 10, tomorrow)")

    # Handle cancel appointment flow
    if session["flow"] == "cancel_appointment":
        result = handle_cancel_appointment(session, user_message, admin_id)
        return _reply(result)

    # Check for cancel at any point — exact matches + refusal patterns
    is_cancel = lower in ("cancel", "nevermind", "never mind", "stop", "go back", "start over", "quit", "exit")
    # Also detect refusal phrases like "no i don't want to book", "i don't want an appointment"
    if not is_cancel and session.get("flow"):
        is_cancel = bool(re.search(
            r"\b(don'?t want|no\s+i\s+don|not\s+interested|i\s+refuse|no\s+thanks|no\s+thank|"
            r"i\s+changed\s+my\s+mind|forget\s+it|nah|nope\b.*book|no\s+i\s+don'?t|"
            r"don'?t\s+want\s+to\s+book|don'?t\s+need|no\s+booking|stop\s+booking)",
            lower
        ))
    if is_cancel:
        if session["flow"]:
            reset_session(session_id)
            return _reply("No problem! I've cancelled that. How else can I help you? You can ask me about our features, pricing, or book an appointment.")
        return _reply("No worries! Is there anything else I can help you with?")

    # Handle "continue" to resume booking from where they left off
    if lower in ("continue", "continue booking", "resume", "go on", "carry on", "back to booking"):
        if session["flow"] == "booking" and session.get("_paused"):
            session["_paused"] = False
            step = session["step"]
            data = session["data"]
            # Re-show the appropriate dropdown for the current step
            if step == "get_category":
                categories = data.get("_categories", [])
                if categories:
                    session["_ui_options"] = {"type": "categories", "items": [{"name": c} for c in categories]}
                return _reply("Let's continue! What type of doctor would you like to see?")
            elif step == "get_doctor":
                doctors = data.get("_doctors", [])
                if doctors:
                    session["_ui_options"] = {"type": "doctors", "items": [{"name": d["name"], "specialty": d.get("specialty", "General"), "availability": d.get("availability", "Mon-Fri")} for d in doctors]}
                return _reply("Let's continue! Which doctor would you like to see?")
            elif step == "get_date":
                doctor_id = data.get("doctor_id")
                off_dates = db.get_doctor_off_dates(doctor_id) if doctor_id else []
                session["_ui_options"] = {"type": "calendar", "doctor_id": doctor_id, "off_dates": list(off_dates)}
                return _reply("Let's continue! When would you like to come in?")
            elif step == "get_time":
                # Regenerate time slots for the chosen doctor/date
                doctor_id = data.get("doctor_id")
                date_iso = data.get("date_iso")
                slots = []
                if doctor_id:
                    doctor = db.get_doctor_by_id(doctor_id)
                    if doctor and doctor.get("start_time") and doctor["start_time"] != "00:00 AM":
                        doctor_breaks = db.get_doctor_breaks(doctor_id)
                        slots = _generate_doctor_slots(doctor, breaks=doctor_breaks)
                booked_times = []
                if doctor_id and date_iso:
                    booked_times = db.get_booked_times(doctor_id, date_iso)
                dropdown_items = []
                for s in slots:
                    item = {"name": s["time"], "hour": s["hour"], "minute": s.get("minute", 0)}
                    slot_start = s["time"].split(" - ")[0].strip() if " - " in s["time"] else s["time"]
                    if s["time"] in booked_times or slot_start in booked_times:
                        item["booked"] = True
                    dropdown_items.append(item)
                if dropdown_items:
                    session["_ui_options"] = {"type": "timeslots", "items": dropdown_items}
                return _reply(f"Let's continue! Pick a time on **{data.get('date_display', 'your chosen date')}**:")
            else:
                # For other steps just continue the flow
                return _reply(handle_booking(session, user_message, corrected))

    # If already in a flow, continue it (pass corrected text for understanding, original for data)
    if session["flow"] == "booking":
        if "_admin_id" not in session["data"]:
            session["data"]["_admin_id"] = admin_id

        # If booking is paused (user asked a question during dropdown), answer via AI
        if session.get("_paused"):
            ai_answer = _ask_ai_during_booking(user_message, session, admin_id)
            if ai_answer:
                return _reply(ai_answer + "\n\nWhen you're ready to continue booking, just say **continue**.")
            return _reply("I'm not sure about that. Say **continue** to resume your booking.")

        # During dropdown steps, detect if user is asking a question instead of selecting
        dropdown_steps = ("get_category", "get_doctor", "get_date", "get_time")
        if session["step"] in dropdown_steps:
            # Check if message looks like a question (contains ? or starts with question words)
            is_question = ("?" in user_message or
                re.match(r'^(what|how|why|when|where|who|can|do|does|is|are|tell|explain|help)\b', lower, re.IGNORECASE))
            if is_question:
                session["_paused"] = True
                ai_answer = _ask_ai_during_booking(user_message, session, admin_id)
                if ai_answer:
                    return _reply(ai_answer + "\n\nWhen you're ready to continue booking, just say **continue**.")
                # AI not available — give a generic helpful response
                return _reply("That's a great question! Unfortunately I can't look that up right now, but I'd be happy to help after we finish booking.\n\nWhen you're ready to continue booking, just say **continue**.")

        return _reply(handle_booking(session, user_message, corrected))
    if session["flow"] == "lead_capture":
        return _reply(handle_lead_capture(session, user_message))

    # Detect intent using the smart classifier (returns intent + confidence)
    classified_raw, classified_conf = intent_classifier.classify(corrected)
    intent = detect_intent(corrected)

    # Step 2b: Sklearn intent classifier — granular dental intent detection
    sklearn_intent, sklearn_conf = sklearn_classifier.classify(corrected)
    print(f"[router] sklearn: {sklearn_intent} ({sklearn_conf:.2f}) | classic: {classified_raw} ({classified_conf:.2f}) | flow: {intent}", flush=True)

    # Step 3: Restriction filter — block non-dental messages (only for Q&A, not booking/cancel)
    if intent == "qa" and classified_raw not in ("greeting", "farewell"):
        is_blocked, blocked_response = restriction_filter.is_off_topic(
            corrected, sklearn_intent=sklearn_intent, sklearn_conf=sklearn_conf
        )
        if is_blocked:
            return _reply(blocked_response)

    # Low-confidence booking with doctor name mentioned → likely an availability follow-up
    # e.g. "I mean for doctor jhon only" after asking about availability
    if intent == "booking" and classified_conf < 0.8:
        # Check if recent conversation was about availability/doctors
        recent_about_availability = False
        for msg in session.get("history", [])[-4:]:
            content = msg.get("content", "").lower()
            if any(w in content for w in ["available", "time slots", "schedule", "availability", "mon-fri"]):
                recent_about_availability = True
                break
        if recent_about_availability:
            intent = "qa"  # Treat as a follow-up question, not booking

    # Check if user is confirming a booking suggestion from AI (e.g. "okay", "yes", "sure")
    if lower in ("okay", "ok", "yes", "sure", "yeah", "yep", "yea", "please", "yes please", "book", "i want to book", "lets book", "let's book"):
        # Check if the last assistant message suggested booking
        if session["history"] and any(phrase in session["history"][-1].get("content", "").lower() for phrase in ["book an appointment", "book appointment", "would you like to book"]):
            session["flow"] = "booking"
            session["step"] = None
            session["data"] = {"_admin_id": admin_id}
            return _reply(handle_booking(session, user_message))

    # Specialization/symptom queries take priority over booking
    # e.g. "what specialist do I need for braces" is a question, not a booking request
    if claude_specialist.is_configured() and claude_specialist.is_specialization_query(corrected):
        all_doctors = db.get_doctors(admin_id)
        active_doctors = [d for d in all_doctors if d.get("status") == "active"]
        specialist_result = claude_specialist.analyze_symptoms(
            corrected, doctors=active_doctors, history=session["history"]
        )
        if specialist_result and specialist_result.get("reply"):
            return _reply(specialist_result["reply"])

    # Start booking flow (needs state management — must stay before AI)
    if intent == "booking":
        session["flow"] = "booking"
        session["step"] = None
        session["data"] = {"_admin_id": admin_id}
        return _reply(handle_booking(session, user_message))

    # Start lead capture flow (needs state management — must stay before AI)
    if intent == "lead_capture":
        session["flow"] = "lead_capture"
        session["step"] = None
        session["data"] = {}
        return _reply(handle_lead_capture(session, user_message))

    # ══════════════════════════════════════════════════════════════
    #  AI BRAIN — routes to the right AI for each type of question
    #  Step 4: Smart router (sklearn intent → correct engine)
    #  Fallback: Claude AI → Groq → OpenAI → offline
    # ══════════════════════════════════════════════════════════════
    company_info = db.get_company_info(admin_id)
    all_doctors = db.get_doctors(admin_id)
    active_doctors = [d for d in all_doctors if d.get("status") == "active"]

    # Build doctor time slots so the AI knows exact availability
    doctor_slots = {}
    for doc in active_doctors:
        doc_breaks = db.get_doctor_breaks(doc["id"])
        slots = _generate_doctor_slots(doc, breaks=doc_breaks)
        if slots:
            doctor_slots[doc["name"]] = [s["time"] for s in slots]

    # ── Smart router: sklearn intent → correct engine ──
    if sklearn_intent and sklearn_conf > 0.4:
        smart_result = smart_router.route(
            sklearn_intent, sklearn_conf, corrected,
            {
                "company_info": company_info,
                "active_doctors": active_doctors,
                "doctor_slots": doctor_slots,
                "history": session["history"],
            }
        )
        if smart_result:
            print(f"[router] Smart route: {sklearn_intent} -> response", flush=True)
            return _reply(smart_result)

    # ── Claude AI for specialization/symptom cases (fallback) ──
    if claude_specialist.is_configured() and claude_specialist.is_specialization_query(corrected):
        claude_result = claude_specialist.analyze_symptoms(
            corrected, doctors=active_doctors, history=session["history"]
        )
        if claude_result and claude_result.get("reply"):
            return _reply(claude_result["reply"])

    # ── Groq AI for everything else (fallback) ──
    if message_interpreter.is_configured():
        ai_result = message_interpreter.think_and_respond(
            corrected, company_info, active_doctors,
            doctor_slots=doctor_slots, history=session["history"]
        )
        if ai_result and ai_result.get("reply"):
            return _reply(ai_result["reply"])

    # Try OpenAI as last AI fallback
    if dental_ai.is_configured():
        ai_result = dental_ai.think_and_respond(
            corrected, company_info, active_doctors, history=session["history"]
        )
        if ai_result and ai_result.get("reply"):
            return _reply(ai_result["reply"])

    # ══════════════════════════════════════════════════════════════
    #  Offline fallbacks — if BOTH AI providers fail
    # ══════════════════════════════════════════════════════════════

    # Dental knowledge engine — trained on 60+ dental topics
    kb_result = dke.find_best_answer(user_message)
    if kb_result:
        answer = kb_result["answer"]
        if kb_result.get("follow_up"):
            answer += "\n\n" + kb_result["follow_up"]
        return _reply(answer)

    # Symptom detection
    symptom_specialty = find_symptom_specialty(corrected)
    if symptom_specialty:
        return _reply(_build_symptom_response(symptom_specialty, admin_id))

    return _reply(
        "I'm here to help with your dental needs! I can:\n\n"
        "**1.** Help you find the right specialist for your problem\n"
        "**2.** Book an appointment\n"
        "**3.** Answer questions about our services, hours, and pricing\n"
        "**4.** Save your contact info for a callback\n\n"
        "Tell me what's bothering you or what you need help with!"
    )


# ══════════════════════════════════════════════
#  Routes — Pages
# ══════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/login")
def login_page():
    return send_from_directory("static", "login.html")


@app.route("/dashboard")
def dashboard():
    return send_from_directory("static", "dashboard.html")


@app.route("/user-dashboard")
def user_dashboard():
    return send_from_directory("static", "user-dashboard.html")


@app.route("/privacy")
def privacy():
    return send_from_directory("static", "privacy.html")


@app.route("/data-deletion", methods=["GET", "POST"])
def data_deletion():
    if request.method == "POST":
        # Facebook sends a signed_request when user requests data deletion
        # Respond with a confirmation URL and tracking code
        import hashlib
        confirmation_code = hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()[:12]
        return jsonify({
            "url": request.host_url + "data-deletion",
            "confirmation_code": confirmation_code,
        })
    return send_from_directory("static", "data-deletion.html")


# ══════════════════════════════════════════════
#  Routes — Auth
# ══════════════════════════════════════════════

@app.route("/auth/signup", methods=["POST"])
def auth_signup():
    data = request.get_json()
    name = data.get("name", "").strip()
    email_addr = data.get("email", "").strip().lower()
    password = data.get("password", "")
    company = data.get("company", "").strip()
    role = data.get("role", "admin").strip().lower()
    specialty = data.get("specialty", "").strip()

    if role not in ("admin", "doctor", "head_admin"):
        return jsonify({"error": "Invalid role."}), 400
    if not name or not email_addr or not password:
        return jsonify({"error": "Name, email, and password are required."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if "@" not in email_addr or "." not in email_addr:
        return jsonify({"error": "Please enter a valid email address."}), 400

    user, error = db.create_user(name, email_addr, password, company, role=role, specialty=specialty)
    if error:
        return jsonify({"error": error}), 400

    return jsonify({"token": user["token"], "user": db.user_to_public(user)})


@app.route("/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json()
    email_addr = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email_addr or not password:
        return jsonify({"error": "Email and password are required."}), 400

    user, error = db.login_user(email_addr, password)
    if error:
        return jsonify({"error": error}), 400

    return jsonify({"token": user["token"], "user": db.user_to_public(user)})


@app.route("/auth/forgot", methods=["POST"])
def auth_forgot():
    # In production, this would send a real reset email
    return jsonify({"ok": True})


@app.route("/auth/social-token", methods=["POST"])
def auth_social_token():
    """
    Verify a social login token server-side, then create/login user.

    Expects JSON: { provider, token, name (optional), email (optional), avatar_url (optional) }
    - Google: token is an access_token or id_token — verified via google-auth + Google API
    - Facebook: token is an access_token — verified via Graph API /debug_token
    - Apple: token is an id_token (JWT) — verified via Apple JWKS public keys

    If provider credentials are NOT configured, falls back to demo mode
    (trusts the client-provided name/email for local development).
    """
    data = request.get_json()
    provider = data.get("provider", "")
    token = data.get("token", "")
    client_name = data.get("name", "").strip()
    client_email = data.get("email", "").strip().lower()
    avatar_url = data.get("avatar_url", "")
    role = data.get("role", "admin").strip().lower()
    specialty = data.get("specialty", "").strip()
    role_confirmed = data.get("role_confirmed", False)  # True when user explicitly chose a role

    if role not in ("admin", "doctor", "head_admin"):
        return jsonify({"error": "Invalid role."}), 400
    if provider not in ("google", "facebook", "apple"):
        return jsonify({"error": "Unknown provider."}), 400

    # ── If provider is configured, verify the token server-side ──
    if social_auth.is_provider_configured(provider):
        if not token:
            return jsonify({"error": "Missing authentication token."}), 400
        try:
            verified = social_auth.verify_social_token(
                provider, token,
                client_name=client_name,
                client_email=client_email,
            )
        except social_auth.SocialAuthError as e:
            return jsonify({"error": str(e)}), 401

        name = verified["name"]
        email_addr = verified["email"]
        provider_id = verified["id"]
        avatar_url = verified.get("picture", avatar_url)

        if not email_addr:
            return jsonify({"error": "Could not retrieve email from provider. Please allow email access."}), 400

    # ── Demo/dev fallback: trust client-provided data ──
    else:
        email_addr = client_email
        name = client_name
        provider_id = token or f"demo_{provider}"

        if not email_addr:
            return jsonify({"error": "Email is required."}), 400
        if not name:
            name = email_addr.split("@")[0].title()

    # Check if user already exists — if not and role wasn't explicitly chosen, ask for role
    existing_user = db.get_user_by_email(email_addr)
    if not existing_user and not role_confirmed:
        return jsonify({
            "needs_role": True,
            "provider": provider,
            "token": token,
            "name": name,
            "email": email_addr,
            "avatar_url": avatar_url,
        })

    user, error = db.login_or_create_social(
        name=name,
        email=email_addr,
        provider=provider,
        provider_id=provider_id,
        avatar_url=avatar_url,
        role=role,
        specialty=specialty,
    )
    if error:
        return jsonify({"error": error}), 400

    return jsonify({"token": user["token"], "user": db.user_to_public(user)})


@app.route("/auth/social-config", methods=["GET"])
def auth_social_config():
    """Return which social providers are configured (so frontend can adapt)."""
    return jsonify({
        "google": social_auth.is_provider_configured("google"),
        "facebook": social_auth.is_provider_configured("facebook"),
        "apple": social_auth.is_provider_configured("apple"),
        "google_client_id": social_auth.GOOGLE_CLIENT_ID if social_auth.is_provider_configured("google") else "",
        "facebook_app_id": social_auth.FACEBOOK_APP_ID if social_auth.is_provider_configured("facebook") else "",
        "apple_client_id": social_auth.APPLE_CLIENT_ID if social_auth.is_provider_configured("apple") else "",
    })


@app.route("/auth/me", methods=["GET"])
def auth_me():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    return jsonify({"user": db.user_to_public(user)})


@app.route("/auth/update-plan", methods=["POST"])
def auth_update_plan():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if user.get("role") != "head_admin":
        return jsonify({"error": "Only head administrators can change the plan."}), 403

    data = request.get_json()
    plan = data.get("plan", "")
    if plan not in ("basic", "pro", "agency"):
        return jsonify({"error": "Invalid plan"}), 400

    db.update_user_plan(user["id"], plan)
    user["plan"] = plan
    return jsonify({"ok": True, "user": db.user_to_public(user)})


@app.route("/auth/update-profile", methods=["POST"])
def auth_update_profile():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json()
    name = data.get("name", "").strip()
    email_addr = data.get("email", "").strip().lower()
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")
    avatar_url = data.get("avatar_url", None)

    if not name:
        return jsonify({"error": "Name is required."}), 400
    if not email_addr or "@" not in email_addr:
        return jsonify({"error": "Valid email is required."}), 400

    # If email changed, check it's not taken
    if email_addr != user["email"]:
        existing = db.get_user_by_email(email_addr)
        if existing:
            return jsonify({"error": "This email is already in use by another account."}), 400

    # If changing password, verify current password first
    if new_password:
        if len(new_password) < 8:
            return jsonify({"error": "New password must be at least 8 characters."}), 400
        if user["provider"] == "email":
            if not current_password or db._hash_password(current_password) != user["password_hash"]:
                return jsonify({"error": "Current password is incorrect."}), 400

    updated = db.update_user_profile(user["id"], name, email_addr, new_password, avatar_url)
    if not updated:
        return jsonify({"error": "Failed to update profile."}), 500

    refreshed = db.get_user_by_token(token)
    return jsonify({"ok": True, "user": db.user_to_public(refreshed)})


# ══════════════════════════════════════════════
#  Routes — Chat & API
# ══════════════════════════════════════════════

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    session_id = data.get("session_id", "default")
    admin_id = data.get("admin_id", 1)

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    try:
        reply = process_message(session_id, user_message, admin_id=admin_id)
        # Check if session has UI options to send to frontend
        session = get_session(session_id)
        response = {"reply": reply}
        if session.get("_ui_options"):
            response["options"] = session.pop("_ui_options")
        return jsonify(response)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/leads", methods=["GET"])
def api_leads():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify(db.get_all_leads())
    if user.get("role") == "doctor":
        return jsonify([])  # Doctors don't see leads
    admin_id = get_effective_admin_id(user)
    return jsonify(db.get_all_leads(admin_id=admin_id))


@app.route("/api/bookings", methods=["GET"])
def api_bookings():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify(db.get_all_bookings())
    if user.get("role") == "doctor":
        # Doctor sees only their bookings
        doctor = db.get_doctor_by_user_id(user["id"])
        if doctor:
            return jsonify(db.get_all_bookings(doctor_id=doctor["id"]))
        return jsonify([])
    admin_id = get_effective_admin_id(user)
    return jsonify(db.get_all_bookings(admin_id=admin_id))


@app.route("/api/stats", methods=["GET"])
def api_stats():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify(db.get_stats())
    if user.get("role") == "doctor":
        doctor = db.get_doctor_by_user_id(user["id"])
        if doctor:
            return jsonify(db.get_stats(doctor_id=doctor["id"]))
        return jsonify(db.get_stats())
    admin_id = get_effective_admin_id(user)
    return jsonify(db.get_stats(admin_id=admin_id))


@app.route("/api/company-info", methods=["GET"])
def api_get_company_info():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    # Admin sees their own, doctor sees their admin's
    info_user_id = get_effective_admin_id(user)
    info = db.get_company_info(info_user_id)
    return jsonify(info or {})


@app.route("/api/company-info", methods=["POST"])
def api_save_company_info():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if user.get("role") != "head_admin":
        return jsonify({"error": "Only the head administrator can edit company info."}), 403
    data = request.get_json()
    admin_id = get_effective_admin_id(user)
    db.save_company_info(admin_id, data)
    return jsonify({"ok": True})


@app.route("/api/doctors", methods=["GET"])
def api_get_doctors():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if is_admin_role(user):
        doctors = db.get_doctors(get_effective_admin_id(user))
    else:
        doctors = db.get_doctors(user.get("admin_id", 0))
    return jsonify(doctors)


@app.route("/api/doctors", methods=["POST"])
def api_add_doctor():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if not is_admin_role(user):
        return jsonify({"error": "Only administrators can add doctors."}), 403
    data = request.get_json()
    name = data.get("name", "").strip()
    doctor_email = data.get("email", "").strip().lower()
    if not name:
        return jsonify({"error": "Doctor name is required"}), 400
    if not doctor_email:
        return jsonify({"error": "Doctor email is required"}), 400

    # Validate: email must exist and belong to a doctor account
    existing_user = db.get_user_by_email(doctor_email)
    if not existing_user:
        return jsonify({"error": "No account found with this email. The doctor must sign up first."}), 400
    if existing_user.get("role") != "doctor":
        return jsonify({"error": f"This email belongs to a {existing_user['role']} account, not a doctor account."}), 400
    if existing_user.get("admin_id") and existing_user["admin_id"] != 0:
        return jsonify({"error": "This doctor is already linked to another practice."}), 400

    # Use company-level admin_id so all admins in the company see this doctor
    company_admin_id = get_effective_admin_id(user)

    # Create doctor record in pending state (not linked yet)
    specialty = data.get("specialty", "") or existing_user.get("specialty", "")
    doctor_id = db.add_doctor(company_admin_id, name, doctor_email,
                               specialty, data.get("bio", ""),
                               data.get("availability", "Mon-Fri"))

    # Create a doctor request — doctor must accept before being linked
    company_info = db.get_company_info(company_admin_id)
    business_name = company_info.get("business_name", "") if company_info else ""
    if not business_name:
        business_name = user.get("company", "")
    req_id, err = db.create_doctor_request(
        company_admin_id, user["name"], business_name, doctor_email, doctor_id
    )
    if err:
        # Request already exists — remove the pending doctor record we just created
        db.delete_doctor(doctor_id, company_admin_id)
        return jsonify({"error": err}), 400

    return jsonify({"ok": True, "id": doctor_id, "message": "Invitation sent. The doctor must accept before joining."})


@app.route("/api/doctors/<int:doctor_id>", methods=["PUT"])
def api_update_doctor(doctor_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if not is_admin_role(user):
        return jsonify({"error": "Only administrators can edit doctors."}), 403
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Doctor name is required"}), 400
    company_admin_id = get_effective_admin_id(user)
    db.update_doctor(doctor_id, company_admin_id, name, data.get("specialty", ""),
                     data.get("bio", ""), data.get("availability", "Mon-Fri"),
                     start_time=data.get("start_time"),
                     end_time=data.get("end_time"),
                     is_active=data.get("is_active"),
                     appointment_length=data.get("appointment_length"))
    return jsonify({"ok": True})


@app.route("/api/doctors/<int:doctor_id>", methods=["DELETE"])
def api_delete_doctor(doctor_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if user.get("role") != "head_admin":
        return jsonify({"error": "Only the head administrator can remove doctors."}), 403
    # Unlink the doctor user from the company
    doctor = db.get_doctor_by_id(doctor_id)
    if doctor and doctor.get("user_id"):
        db.set_user_admin_id(doctor["user_id"], 0)
    db.delete_doctor(doctor_id, user["id"])
    return jsonify({"ok": True})


# ── Doctor Breaks ──

@app.route("/api/doctors/<int:doctor_id>/breaks", methods=["GET"])
def api_get_breaks(doctor_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    breaks = db.get_doctor_breaks(doctor_id)
    return jsonify(breaks)


@app.route("/api/doctors/<int:doctor_id>/breaks", methods=["POST"])
def api_add_break(doctor_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    break_id = db.add_doctor_break(
        doctor_id, data.get("break_name", "Break"),
        data.get("start_time", ""), data.get("end_time", ""))
    return jsonify({"ok": True, "id": break_id})


@app.route("/api/doctors/<int:doctor_id>/breaks/<int:break_id>", methods=["DELETE"])
def api_delete_break(doctor_id, break_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    db.delete_doctor_break(break_id, doctor_id)
    return jsonify({"ok": True})


# ── Doctor Off Days ──

@app.route("/api/doctors/<int:doctor_id>/off-days", methods=["GET"])
def api_get_off_days(doctor_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    off_days = db.get_doctor_off_days(doctor_id)
    return jsonify(off_days)


@app.route("/api/doctors/<int:doctor_id>/off-days", methods=["POST"])
def api_add_off_day(doctor_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    off_id, err = db.add_doctor_off_day(doctor_id, data.get("date", ""), data.get("reason", ""))
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True, "id": off_id})


@app.route("/api/doctors/<int:doctor_id>/off-days/<int:off_day_id>", methods=["DELETE"])
def api_delete_off_day(doctor_id, off_day_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    db.delete_doctor_off_day(off_day_id, doctor_id)
    return jsonify({"ok": True})


@app.route("/api/doctors/<int:doctor_id>/off-dates", methods=["GET"])
def api_get_off_dates(doctor_id):
    """Public endpoint — returns just the ISO date strings for a doctor."""
    off_dates = list(db.get_doctor_off_dates(doctor_id))
    return jsonify(off_dates)


# ── Company Info File Upload ──

@app.route("/api/company-info/upload", methods=["POST"])
def api_upload_company_file():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    if user.get("role") != "head_admin":
        return jsonify({"error": "Only the head administrator can upload company files."}), 403

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    filename = file.filename.lower()

    # Extract text based on file type
    text = ""
    try:
        if filename.endswith(".pdf"):
            import PyPDF2
            import io
            reader = PyPDF2.PdfReader(io.BytesIO(file.read()))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        elif filename.endswith(".docx"):
            import docx
            import io
            doc = docx.Document(io.BytesIO(file.read()))
            text = "\n".join(p.text for p in doc.paragraphs)
        elif filename.endswith((".txt", ".csv", ".md")):
            text = file.read().decode("utf-8", errors="ignore")
        else:
            # Try reading as text
            text = file.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return jsonify({"error": f"Could not read file: {str(e)}"}), 400

    if not text.strip():
        return jsonify({"error": "No text could be extracted from this file. It may be a scanned image."}), 400

    # Truncate if very long
    if len(text) > 10000:
        text = text[:10000]

    # Use AI to extract structured company info
    ai_prompt = (
        "Extract business information from this document. Return ONLY valid JSON with these keys:\n"
        "business_name, address, phone, business_hours, services, pricing_insurance, emergency_info, about\n"
        "If a field cannot be found, use an empty string. Do not add any text outside the JSON.\n\n"
        f"Document text:\n{text}"
    )

    extracted = None

    # Try Groq (free)
    if message_interpreter.is_configured():
        try:
            client = message_interpreter._get_client()
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": ai_prompt}],
                max_tokens=800, temperature=0,
            )
            raw = resp.choices[0].message.content.strip()
            # Extract JSON from response
            import json as _json
            # Find JSON in response
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                extracted = _json.loads(raw[start:end])
        except Exception as e:
            print(f"[upload] Groq extraction failed: {e}", flush=True)

    # Try OpenAI fallback
    if not extracted and dental_ai.is_configured():
        try:
            from openai import OpenAI
            client = OpenAI(api_key=dental_ai.OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": ai_prompt}],
                max_tokens=800, temperature=0,
            )
            raw = resp.choices[0].message.content.strip()
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                extracted = json.loads(raw[start:end])
        except Exception as e:
            print(f"[upload] OpenAI extraction failed: {e}", flush=True)

    if not extracted:
        return jsonify({"error": "AI could not extract info. Please fill in the fields manually.", "raw_text": text[:2000]}), 400

    return jsonify({"ok": True, "extracted": extracted})


# ── Categories ──

@app.route("/api/categories", methods=["GET"])
def api_get_categories():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    admin_id = get_effective_admin_id(user)
    return jsonify(db.get_categories(admin_id))


@app.route("/api/categories", methods=["POST"])
def api_add_category():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if not is_admin_role(user):
        return jsonify({"error": "Only administrators can add categories."}), 403
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Category name is required."}), 400
    cat_id, error = db.add_category(user["id"], name)
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"ok": True, "id": cat_id})


@app.route("/api/categories/<int:category_id>", methods=["DELETE"])
def api_delete_category(category_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if not is_admin_role(user):
        return jsonify({"error": "Only administrators can remove categories."}), 403
    db.delete_category(category_id, user["id"])
    return jsonify({"ok": True})


# ── Doctor Requests ──

@app.route("/api/doctor-requests", methods=["GET"])
def api_get_doctor_requests():
    """Get pending requests — for doctors: invitations sent to them; for admins: requests they sent."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if user.get("role") == "doctor":
        requests = db.get_doctor_requests_for_doctor(user["email"])
    else:
        admin_id = get_effective_admin_id(user)
        requests = db.get_doctor_requests_by_admin(admin_id)
    return jsonify(requests)


@app.route("/api/doctor-requests/<int:request_id>/respond", methods=["POST"])
def api_respond_doctor_request(request_id):
    """Accept or reject a doctor invitation."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if user.get("role") != "doctor":
        return jsonify({"error": "Only doctors can respond to requests."}), 403

    data = request.get_json()
    accept = data.get("accept", False)

    result, error = db.respond_to_doctor_request(request_id, user["id"], accept=accept)
    if error:
        return jsonify({"error": error}), 400

    # Refresh user data after accepting (role/admin_id may have changed)
    updated_user = db.get_user_by_token(token)
    return jsonify({"ok": True, "accepted": accept, "user": db.user_to_public(updated_user) if updated_user else None})


@app.route("/api/doctor-requests/<int:request_id>", methods=["DELETE"])
def api_delete_doctor_request(request_id):
    """Admin deletes a pending doctor request they sent."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if not is_admin_role(user):
        return jsonify({"error": "Only administrators can delete doctor requests."}), 403
    company_admin_id = get_effective_admin_id(user)
    db.delete_doctor_request(request_id, company_admin_id)
    return jsonify({"ok": True})


# ── Admin Requests (head_admin invites admins) ──

@app.route("/api/admin-requests", methods=["POST"])
def api_invite_admin():
    """Head admin sends invitation to a new admin."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if user.get("role") != "head_admin":
        return jsonify({"error": "Only head administrators can invite admins."}), 403
    data = request.get_json()
    admin_email = data.get("email", "").strip().lower()
    if not admin_email:
        return jsonify({"error": "Email is required."}), 400

    # Validate: email must exist and belong to an admin account
    existing_user = db.get_user_by_email(admin_email)
    if not existing_user:
        return jsonify({"error": "No account found with this email. The person must sign up first."}), 400
    if existing_user.get("role") == "doctor":
        return jsonify({"error": "This email belongs to a doctor account, not an admin."}), 400
    if existing_user.get("role") == "head_admin":
        return jsonify({"error": "This email belongs to a head administrator. They already own their own company."}), 400
    if existing_user.get("admin_id") and existing_user["admin_id"] != 0:
        return jsonify({"error": "This admin is already linked to another company."}), 400

    company_info = db.get_company_info(user["id"])
    biz_name = (company_info.get("business_name") if company_info else None) or user.get("company", "") or "Your Practice"
    req_id, error = db.create_admin_request(user["id"], user["name"], biz_name, admin_email)
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"ok": True, "id": req_id})


@app.route("/api/admin-requests", methods=["GET"])
def api_get_admin_requests():
    """Get admin requests — combines sent requests (if head_admin) and received invitations."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    # Return both sent and received, frontend will differentiate
    mode = request.args.get("mode", "")
    if mode == "received":
        return jsonify(db.get_admin_requests_for_user(user["email"]))
    elif mode == "sent" and user.get("role") == "head_admin":
        return jsonify(db.get_admin_requests_by_head(user["id"]))
    else:
        # Default: head_admin sees sent, others see received
        if user.get("role") == "head_admin":
            return jsonify(db.get_admin_requests_by_head(user["id"]))
        return jsonify(db.get_admin_requests_for_user(user["email"]))


@app.route("/api/admin-requests/<int:request_id>/respond", methods=["POST"])
def api_respond_admin_request(request_id):
    """Accept or reject an admin invitation."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    data = request.get_json()
    accept = data.get("accept", False)
    result, error = db.respond_to_admin_request(request_id, user["id"], accept=accept)
    if error:
        return jsonify({"error": error}), 400
    updated_user = db.get_user_by_token(token)
    return jsonify({"ok": True, "accepted": accept, "user": db.user_to_public(updated_user) if updated_user else None})


@app.route("/api/admin-requests/<int:request_id>", methods=["DELETE"])
def api_delete_admin_request(request_id):
    """Head admin cancels/deletes a sent invitation."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if user.get("role") != "head_admin":
        return jsonify({"error": "Only head administrators can delete invitations."}), 403
    db.delete_admin_request(request_id, user["id"])
    return jsonify({"ok": True})


@app.route("/api/company-admins", methods=["GET"])
def api_get_company_admins():
    """Get all admins under this head admin's company."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if user.get("role") != "head_admin":
        return jsonify({"error": "Only head administrators can view company admins."}), 403
    admins = db.get_company_admins(user["id"])
    return jsonify(admins)


@app.route("/api/company-admins/<int:admin_user_id>", methods=["DELETE"])
def api_remove_company_admin(admin_user_id):
    """Remove an admin from the company."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if user.get("role") != "head_admin":
        return jsonify({"error": "Only head administrators can remove admins."}), 403
    db.remove_admin_from_company(admin_user_id, user["id"])
    return jsonify({"ok": True})


@app.route("/api/doctors/public", methods=["GET"])
def api_public_doctors():
    """Public endpoint for chatbot to show available doctors for a given admin."""
    admin_id = request.args.get("admin_id", 1, type=int)
    doctors = db.get_doctors(admin_id)
    return jsonify([{"id": d["id"], "name": d["name"], "specialty": d["specialty"],
                     "availability": d["availability"]} for d in doctors if d.get("status") == "active"])


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "model_loaded": model is not None,
        "model": "chatgenius-tinyllama (fine-tuned)",
        "features": ["qa", "booking", "lead_capture", "dashboard", "auth"],
    })


if __name__ == "__main__":
    load_model()
    app.run(debug=False, port=8080)
