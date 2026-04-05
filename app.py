"""
ChatGenius Flask backend with three chatbot features:
1. Q&A — answers business questions from knowledge base
2. Appointment Booking — collects info, checks calendar, confirms, emails
3. Lead Capture — collects name/phone when not ready to book
All work inside the chat window with a conversation state machine.
"""

from flask import Flask, request, jsonify, send_from_directory, redirect
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
import background_tasks

# ── New engine modules ──
import translations as tr
import emergency_handler
import handoff_engine
import doctor_comparison
import recall_engine
import treatment_followup_engine
import missed_call_engine
import gallery_engine
import promotions_engine as promo
import loyalty_engine as loyalty
import ab_testing
import two_factor_auth as tfa
import referral_engine
import patient_profile_engine as patient_profile
import realtime_engine as realtime
import benchmarking_engine as benchmarks
import gmb_engine as gmb

# ── New Feature Engines (10 features) ──
import appointment_reminder_engine as reminder_eng
import survey_engine
import upsell_engine
import channel_engine
import invoice_engine
import report_engine
import package_engine
import doctor_portal_engine
import noshow_recovery_engine

app = Flask(__name__, static_folder="static")

# ── CORS for embedded chatbot ──
from flask_cors import CORS
CORS(app, resources={r"/chat": {"origins": "*"}, r"/static/chatbot-embed.js": {"origins": "*"}})

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


def _is_affirmative(text):
    """Check if text expresses agreement/yes — flexible matching."""
    t = text.lower().strip().rstrip("!.")
    if t in ("yes", "yeah", "yep", "yea", "sure", "ok", "okay", "y", "ya", "yup",
             "yes please", "add me", "waitlist", "go ahead", "do it", "absolutely",
             "of course", "definitely", "please", "right", "correct", "confirm"):
        return True
    if re.search(r'\b(yes|yeah|yep|sure|okay|ok|please|absolutely|definitely|go ahead)\b', t):
        return True
    return False


def _is_negative(text):
    """Check if text expresses disagreement/no — flexible matching."""
    t = text.lower().strip().rstrip("!.")
    if t in ("no", "nah", "nope", "n", "no thanks", "no thank you", "other times",
             "show me", "skip", "pass", "never mind", "nevermind", "not now"):
        return True
    if re.search(r'\b(no|nah|nope|don\'?t|not)\b', t) and not re.search(r'\b(yes|yeah|sure|okay)\b', t):
        return True
    return False


# ══════════════════════════════════════════════
#  Intent Detection — route to correct flow
# ══════════════════════════════════════════════

def detect_intent(text):
    """Detect user intent using the smart intent classifier.
    Uses TF-IDF scoring against intent examples + structural analysis
    to understand WHAT the user actually wants — not just keyword matching.
    """
    intent, confidence = intent_classifier.classify(text)

    # Map 19 classifier intents to flow intents
    if intent == "booking":
        return "booking"
    if intent in ("cancellation", "cancel"):
        return "cancel"
    if intent == "lead_capture":
        return "lead_capture"
    # All other intents (availability, doctor_info, treatment_question, emergency,
    # greeting, farewell, pricing_insurance, clinic_info, waitlist, promotions,
    # loyalty, pre_visit_form, recall, symptom_question, human_handoff, complaint)
    # are routed to Q&A / smart router
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
        if d.weekday() != 4:  # Skip Friday (4) — clinic closed; open Sun-Thu + Sat
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


def _get_off_dates_with_blocks(doctor_id, admin_id=None):
    """Return combined off_dates (doctor off days + schedule block dates + flexible schedule off days)
    for calendar greying. Covers current month and next 3 months."""
    from datetime import datetime as _dt_h, timedelta as _td_h
    off_dates = list(db.get_doctor_off_dates(doctor_id)) if doctor_id else []
    now = _dt_h.now()

    if admin_id and doctor_id:
        for month_offset in range(4):
            y = now.year + (now.month + month_offset - 1) // 12
            m = (now.month + month_offset - 1) % 12 + 1
            blocked = db.get_blocked_dates_for_calendar(admin_id, doctor_id, y, m)
            off_dates.extend(blocked)

    # Also grey out recurring off days from flexible schedule (daily_hours with off: true)
    if doctor_id:
        doctor = db.get_doctor_by_id(doctor_id)
        if doctor and doctor.get("schedule_type") == "flexible" and doctor.get("daily_hours"):
            try:
                daily = doctor["daily_hours"]
                if isinstance(daily, str):
                    daily = json.loads(daily)
                # Find which day names are marked off
                off_day_names = [day for day, hrs in daily.items() if isinstance(hrs, dict) and hrs.get("off")]
                if off_day_names:
                    # Generate dates for next 4 months that fall on these off days
                    end_date = now + _td_h(days=120)
                    d = now
                    while d <= end_date:
                        if d.strftime("%A") in off_day_names:
                            off_dates.append(d.strftime("%Y-%m-%d"))
                        d += _td_h(days=1)
            except (json.JSONDecodeError, ValueError, KeyError, TypeError):
                pass

    return list(set(off_dates))


def _generate_doctor_slots(doctor, breaks=None, selected_date=None):
    """Generate appointment time slots from a doctor's schedule.
    Supports both fixed (same hours daily) and flexible (per-day hours) schedules.
    selected_date: a date string like '2026-04-07' to look up the day-specific hours."""
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

    # Determine start/end times based on schedule type
    doc_start = doctor.get("start_time")
    doc_end = doctor.get("end_time")

    if doctor.get("schedule_type") == "flexible" and doctor.get("daily_hours") and selected_date:
        try:
            daily = doctor["daily_hours"]
            if isinstance(daily, str):
                daily = json.loads(daily)
            # Get the day name from the selected date
            from datetime import datetime as _dt
            day_name = _dt.strptime(selected_date, "%Y-%m-%d").strftime("%A")
            day_hours = daily.get(day_name)
            if day_hours:
                if day_hours.get("off"):
                    return []  # Doctor is off this day
                doc_start = day_hours.get("from", doc_start)
                doc_end = day_hours.get("to", doc_end)
            else:
                # Doctor doesn't work this day
                return []
        except (json.JSONDecodeError, ValueError, KeyError):
            pass

    start_min = parse_12h(doc_start)
    end_min = parse_12h(doc_end)
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

    # ── Feature 11: Load schedule blocks for this doctor/date (rebuilt) ──
    block_ranges = []
    if selected_date:
        try:
            admin_id = doctor.get("admin_id", 0)
            doctor_id = doctor.get("id")
            # Check full-day block first (no time_str = checks full-day blocks only)
            if db.is_slot_blocked(admin_id, doctor_id, selected_date, None):
                return []  # Entire day is blocked (holiday / full-day block)
            # Load all blocks to extract time ranges for partial-day blocks
            blocks = db.get_schedule_blocks(admin_id, doctor_id=doctor_id)
            from datetime import datetime as _dt2
            date_obj = _dt2.strptime(selected_date, "%Y-%m-%d")
            for blk in blocks:
                btype = blk.get("block_type", "single_date")
                blk_start_time = blk.get("start_time", "")
                blk_end_time = blk.get("end_time", "")
                if not blk_start_time or not blk_end_time:
                    continue  # Full-day blocks already handled above
                # Check if this block's date pattern matches selected_date
                matches = False
                if btype == "single_date":
                    matches = (blk.get("start_date") == selected_date)
                elif btype == "date_range":
                    sd = blk.get("start_date", "")
                    ed = blk.get("end_date", sd)
                    matches = (sd <= selected_date <= ed)
                elif btype == "recurring":
                    matches = db._date_matches_recurring(date_obj, blk)
                if matches:
                    bs = parse_12h(blk_start_time)
                    be = parse_12h(blk_end_time)
                    if bs is not None and be is not None:
                        block_ranges.append((bs, be))
        except Exception:
            pass

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
        # Check if this slot overlaps any schedule block (Feature 11)
        overlaps_block = False
        for bs, be in block_ranges:
            if current < be and slot_end > bs:
                overlaps_block = True
                current = be
                break
        if overlaps_block:
            continue
        start_str = mins_to_12h(current)
        end_str = mins_to_12h(slot_end)
        time_str = f"{start_str} - {end_str}"
        slots.append({"time": time_str, "hour": h, "minute": m})
        current += length

    return slots


def _extract_time(text, available_slots=None):
    """Extract a time from natural text, with fuzzy matching against available slots."""
    # Normalize whitespace and dashes
    lower = re.sub(r'\s+', ' ', text.strip()).lower()
    lower = lower.replace('–', '-').replace('—', '-')

    # Exact match against available slots (e.g. from dropdown selection like "09:00 AM - 10:00 AM")
    if available_slots:
        for s in available_slots:
            slot_lower = re.sub(r'\s+', ' ', s["time"]).lower().replace('–', '-').replace('—', '-')
            if slot_lower == lower:
                return s["time"]
        # Partial match: user sends "11:00 AM" and slot is "11:00 AM - 11:30 AM"
        for s in available_slots:
            if " - " in s["time"]:
                start_part = s["time"].split(" - ")[0].strip().lower()
                if start_part == lower:
                    return s["time"]
            if lower in s["time"].lower():
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

    # Try to parse a direct time value and match against available slots
    time_patterns = [
        r'(\d{1,2}:\d{2}\s*(?:am|pm))',  # 2:00 pm
        r'(\d{1,2}\s*(?:am|pm))',          # 2pm, 2 pm
        r'(\d{1,2}:\d{2})',                # 14:00
    ]
    for pattern in time_patterns:
        match = re.search(pattern, lower)
        if match:
            raw_time = match.group(1).strip()
            # Try to match against slot names
            if available_slots:
                matched = _match_raw_time_to_slot(raw_time, available_slots)
                if matched:
                    return matched
            return raw_time

    # If the whole message looks like a time (just a number with optional am/pm)
    simple = re.match(r'^(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)?\.?$', lower)
    if simple:
        num = simple.group(1)
        ampm = (simple.group(2) or "").replace(".", "")
        raw_time = f"{num} {ampm}" if ampm else num
        if not ampm:
            h = int(num)
            if 1 <= h <= 6:
                raw_time = f"{num} pm"
        if available_slots:
            matched = _match_raw_time_to_slot(raw_time, available_slots)
            if matched:
                return matched
        return raw_time

    return None


def _match_raw_time_to_slot(raw_time, available_slots):
    """Match a raw time string like '2:00 pm' or '2 pm' to a slot name like '02:00 PM - 02:30 PM'."""
    # Normalize the raw time to extract hour and minute
    m = re.match(r'(\d{1,2}):?(\d{2})?\s*(am|pm)?', raw_time.lower().strip())
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = m.group(3)

    # Convert to 24-hour for comparison
    if ampm == 'pm' and hour < 12:
        hour += 12
    elif ampm == 'am' and hour == 12:
        hour = 0

    for slot in available_slots:
        if slot.get("hour") == hour and slot.get("minute", 0) == minute:
            return slot["time"]

    # Try just matching hour (ignore minutes if user said "2 pm")
    if m.group(2) is None:
        for slot in available_slots:
            if slot.get("hour") == hour:
                return slot["time"]

    return None


# ══════════════════════════════════════════════
#  Fast Booking — parse everything from one message
# ══════════════════════════════════════════════

def _parse_fast_booking(message, admin_id):
    """
    Extract booking details from a single message for fast booking.
    Returns (extracted_dict, active_doctors_list).
    """
    lower = message.lower().strip()
    extracted = {}

    # Get active doctors for this admin
    all_doctors = db.get_doctors(admin_id)
    doctors = [d for d in all_doctors if d.get("status") == "active"]

    # 1. Extract doctor name — match against active doctors
    matched_doctors = []
    for d in doctors:
        doc_name = d["name"].lower()
        # Check "dr ahmed", "dr. ahmed", "doctor ahmed"
        for prefix in [f"dr {doc_name}", f"dr. {doc_name}", f"doctor {doc_name}", doc_name]:
            if prefix in lower:
                if d not in matched_doctors:
                    matched_doctors.append(d)
                break
        else:
            # Check individual name parts (first name, last name) — min 3 chars
            for part in doc_name.split():
                if len(part) >= 3:
                    # Match "dr part" or "dr. part" or "doctor part" or standalone part
                    for pat in [f"dr {part}", f"dr. {part}", f"doctor {part}"]:
                        if pat in lower:
                            if d not in matched_doctors:
                                matched_doctors.append(d)
                            break
                    else:
                        # Standalone name part — only if preceded by dr/doctor or context is clear
                        if re.search(rf'\b{re.escape(part)}\b', lower):
                            if d not in matched_doctors:
                                matched_doctors.append(d)

    if len(matched_doctors) == 1:
        extracted["doctor"] = matched_doctors[0]
    elif len(matched_doctors) > 1:
        # Check if names are actually different people with same first/last name
        extracted["ambiguous_doctors"] = matched_doctors

    # 2. Extract time (careful not to grab date numbers)
    time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:am|pm))', lower)
    if not time_match:
        time_match = re.search(r'(?<!\d)(\d{1,2}\s*(?:am|pm))', lower)
    if time_match:
        extracted["time_raw"] = time_match.group(1).strip()

    # 3. Extract date — natural language
    date_words = [
        "today", "tomorrow", "day after tomorrow",
        "next monday", "next tuesday", "next wednesday", "next thursday",
        "next friday", "next saturday", "next sunday",
        "this monday", "this tuesday", "this wednesday", "this thursday",
        "this friday", "this saturday", "this sunday",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "next week",
    ]
    for kw in date_words:
        if kw in lower:
            extracted["date_raw"] = kw
            break
    # Also check for specific dates like "april 15", "15 april", "april 15th"
    if "date_raw" not in extracted:
        date_match = re.search(
            r'((?:january|february|march|april|may|june|july|august|september|october|november|december)'
            r'\s+\d{1,2}(?:st|nd|rd|th)?)',
            lower
        )
        if date_match:
            extracted["date_raw"] = date_match.group(1)
        else:
            # "15th of april" format
            date_match2 = re.search(
                r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?'
                r'(?:january|february|march|april|may|june|july|august|september|october|november|december))',
                lower
            )
            if date_match2:
                extracted["date_raw"] = date_match2.group(1)

    # 4. Extract email
    email_found = _extract_email(message)
    if email_found:
        extracted["email"] = email_found

    # 5. Extract phone (only if it looks like a real phone, not a time)
    # Remove the time portion to avoid confusion
    msg_without_time = message
    if "time_raw" in extracted:
        msg_without_time = re.sub(re.escape(extracted["time_raw"]), '', msg_without_time, flags=re.IGNORECASE)
    phone_found = _extract_phone(msg_without_time)
    if phone_found and len(re.sub(r'\D', '', phone_found)) >= 7:
        extracted["phone"] = phone_found

    # 6. Extract customer name — "my name is X", "i'm X", "name is X"
    name_match = re.search(
        r"(?:my\s+name\s+is|i'?m|name\s*(?:is)?:?\s+)([A-Za-z]+(?:\s+[A-Za-z]+){0,2})",
        message, re.IGNORECASE
    )
    if name_match:
        candidate = name_match.group(1).strip()
        # Don't capture doctor names or common words as customer name
        common_words = {"looking", "trying", "wanting", "going", "interested", "here", "ready", "available"}
        if candidate.lower() not in common_words and len(candidate) >= 2:
            extracted["name"] = candidate.title()

    return extracted, doctors


def _init_fast_booking(session, extracted, doctors, admin_id):
    """
    Set up session with pre-filled data and determine the first step to ask.
    Returns (first_reply, ui_options_or_none).
    """
    data = session["data"]
    data["_admin_id"] = admin_id

    # Auto-fill name/email/phone from patient record (real app mode)
    if session.get("_prefill_name") and "name" not in data:
        data["name"] = session["_prefill_name"]
    if session.get("_prefill_email") and "email" not in data:
        data["email"] = session["_prefill_email"]
    if session.get("_prefill_phone") and "phone" not in data:
        data["phone"] = session["_prefill_phone"]
    if session.get("patient_id") and "_patient_id" not in data:
        data["_patient_id"] = session["patient_id"]

    # Pre-fill doctor
    if "doctor" in extracted:
        doc = extracted["doctor"]
        data["doctor_id"] = doc["id"]
        data["doctor_name"] = doc["name"]
        data["_doctors"] = doctors

    # Pre-fill date (validate it)
    date_validated = False
    if "date_raw" in extracted and "doctor" in extracted:
        result, error = cal.get_available_slots(extracted["date_raw"])
        if not error:
            date_iso = result["date"].isoformat()
            off_dates = _get_off_dates_with_blocks(extracted["doctor"]["id"], admin_id)
            if date_iso not in off_dates:
                data["date_str"] = extracted["date_raw"]
                data["date_display"] = result["date_display"]
                data["date_iso"] = date_iso
                date_validated = True

    # Pre-fill time (will validate availability later when we have date)
    if "time_raw" in extracted:
        data["_pending_time"] = extracted["time_raw"]

    # Pre-fill name
    if "name" in extracted:
        data["name"] = extracted["name"]

    # Pre-fill email
    if "email" in extracted:
        data["email"] = extracted["email"]

    # Pre-fill phone
    if "phone" in extracted:
        data["phone"] = extracted["phone"]

    # Handle ambiguous doctors — ask for clarification
    if "ambiguous_doctors" in extracted:
        amb = extracted["ambiguous_doctors"]
        # Check if they have different specialties
        specialties = set(d.get("specialty", "") for d in amb)
        data["_doctors"] = amb
        data["_all_doctors"] = doctors
        session["step"] = "get_doctor"
        lines = []
        for i, d in enumerate(amb, 1):
            spec = d.get("specialty", "General Dentist")
            lines.append(f"**{i}.** Dr. {d['name']} — {spec}")
        doc_list = "\n".join(lines)
        ui = {"type": "doctors", "items": [
            {"name": d["name"], "specialty": d.get("specialty", "General"), "availability": d.get("availability", "Mon-Fri")}
            for d in amb
        ]}
        return (
            f"I found multiple doctors matching that name:\n\n{doc_list}\n\n"
            f"Which one would you like to book with?"
        ), ui

    # Determine the first missing step
    # Order: doctor → date → time → name → email → phone
    if "doctor_id" not in data:
        # No doctor matched — show full doctor list
        if doctors:
            categories = list(set(d.get("specialty", "General Dentist") for d in doctors if d.get("specialty")))
            categories.sort()
            if len(categories) > 1:
                data["_all_doctors"] = doctors
                data["_categories"] = categories
                session["step"] = "get_category"
                ui = {"type": "categories", "items": [{"name": c} for c in categories]}
                return "I'd love to help you book! What type of doctor would you like to see?", ui
            else:
                data["_doctors"] = doctors
                session["step"] = "get_doctor"
                ui = {"type": "doctors", "items": [
                    {"name": d["name"], "specialty": d.get("specialty", "General"), "availability": d.get("availability", "Mon-Fri")}
                    for d in doctors
                ]}
                return "I'd love to help you book! Which doctor would you like to see?", ui
        else:
            if "name" not in data:
                session["step"] = "get_name"
                return "I'd love to help you book! What's your full name?", None
            if "email" not in data:
                session["step"] = "get_email"
                return f"Great, {data['name']}! What's your email address? (We'll send you a confirmation)", None
            # Name and email already known — skip to date
            session["step"] = "get_date"
            return f"Hi {data['name']}! When would you like to come in?", None

    # Doctor is set — build confirmation prefix
    doc_name = data.get("doctor_name", "")
    confirmations = [f"Dr. **{doc_name}**"]

    if not date_validated:
        session["step"] = "get_date"
        off_dates = _get_off_dates_with_blocks(data["doctor_id"], admin_id)
        ui = {"type": "calendar", "doctor_id": data["doctor_id"], "off_dates": off_dates}
        conf_text = f"Got it! Booking with {confirmations[0]}. When would you like to come in?"
        return conf_text, ui

    confirmations.append(f"**{data['date_display']}**")

    # Try to validate and set time if we have a pending time
    if "_pending_time" in data and date_validated:
        # Generate available slots
        doctor = db.get_doctor_by_id(data["doctor_id"])
        slots = []
        if doctor and doctor.get("start_time") and doctor["start_time"] != "00:00 AM":
            doctor_breaks = db.get_doctor_breaks(data["doctor_id"])
            slots = _generate_doctor_slots(doctor, breaks=doctor_breaks, selected_date=data.get("date_iso"))
        booked_times = db.get_booked_times(data["doctor_id"], data["date_iso"])

        available_slots = [s for s in slots if not _is_booked_slot(s["time"], booked_times)]
        data["available_slots"] = available_slots
        data["all_slots"] = slots
        data["booked_slot_names"] = [s["time"] for s in slots if _is_booked_slot(s["time"], booked_times)]

        # Try to match the pending time against available slots
        matched_time = _match_time_to_slot(data["_pending_time"], available_slots)
        if matched_time:
            data["chosen_time"] = matched_time
            del data["_pending_time"]
            confirmations.append(f"**{matched_time}**")
        else:
            # Time not available — show slots
            del data["_pending_time"]
            session["step"] = "get_time"
            dropdown_items = []
            for s in slots:
                item = {"name": s["time"], "hour": s["hour"], "minute": s.get("minute", 0)}
                if _is_booked_slot(s["time"], booked_times):
                    item["booked"] = True
                dropdown_items.append(item)
            ui = {"type": "timeslots", "items": dropdown_items}
            return (
                f"Got it! Booking with {confirmations[0]} on {confirmations[1]}.\n\n"
                f"Unfortunately that time isn't available. Here are the open slots:"
            ), ui

    if "chosen_time" not in data:
        # Need time
        doctor = db.get_doctor_by_id(data["doctor_id"])
        slots = []
        if doctor and doctor.get("start_time") and doctor["start_time"] != "00:00 AM":
            doctor_breaks = db.get_doctor_breaks(data["doctor_id"])
            slots = _generate_doctor_slots(doctor, breaks=doctor_breaks, selected_date=data.get("date_iso"))
        booked_times = db.get_booked_times(data["doctor_id"], data["date_iso"])
        available_slots = [s for s in slots if not _is_booked_slot(s["time"], booked_times)]
        data["available_slots"] = available_slots
        data["all_slots"] = slots
        data["booked_slot_names"] = [s["time"] for s in slots if _is_booked_slot(s["time"], booked_times)]

        session["step"] = "get_time"
        dropdown_items = []
        for s in slots:
            item = {"name": s["time"], "hour": s["hour"], "minute": s.get("minute", 0)}
            if _is_booked_slot(s["time"], booked_times):
                item["booked"] = True
            dropdown_items.append(item)
        ui = {"type": "timeslots", "items": dropdown_items}
        return (
            f"Got it! Booking with {confirmations[0]} on {confirmations[1]}.\n\n"
            f"What time would you like?"
        ), ui

    # Doctor + date + time all set
    if "name" not in data:
        session["step"] = "get_name"
        conf = " | ".join(confirmations)
        return f"Almost there! {conf}\n\nWhat's your full name?", None

    if "email" not in data:
        session["step"] = "get_email"
        return f"Great! What's your email address? (We'll send you a confirmation)", None

    if "phone" not in data:
        session["step"] = "get_phone"
        return "And your phone number? (In case we need to reach you)", None

    # Everything provided — skip to discount or finalize
    try:
        promos_available = promo.has_active_promotions(data.get("_admin_id", 1))
        if promos_available:
            session["step"] = "ask_discount"
            return "Do you have a discount or promo code? (or say **skip**)", None
    except Exception:
        pass
    # All info collected — set finalize flag so next handle_booking call completes it
    session["step"] = "finalize_booking"
    conf = " | ".join(confirmations)
    return f"Perfect! {conf} for **{data['name']}**. Just say **confirm** to book it.", None


def _is_booked_slot(slot_time, booked_list):
    """Check if a slot is booked."""
    if slot_time in booked_list:
        return True
    if " - " in slot_time:
        start_part = slot_time.split(" - ")[0].strip()
        return start_part in booked_list
    return False


def _match_time_to_slot(time_raw, available_slots):
    """Match a raw time string like '2pm' or '2:00 pm' to an available slot."""
    if not available_slots:
        return None

    lower = time_raw.lower().strip()

    # Normalize: "2pm" → "02:00 PM", "2:30pm" → "02:30 PM"
    m = re.match(r'^(\d{1,2}):?(\d{2})?\s*(am|pm)$', lower)
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = m.group(3).upper()

    # Convert to 24h for comparison
    h24 = hour
    if ampm == "PM" and hour < 12:
        h24 += 12
    if ampm == "AM" and hour == 12:
        h24 = 0

    # Find the slot that starts at this time
    for s in available_slots:
        if s["hour"] == h24 and s.get("minute", 0) == minute:
            return s["time"]

    # Try matching just the hour if minute is 0
    if minute == 0:
        for s in available_slots:
            if s["hour"] == h24:
                return s["time"]

    return None


def handle_booking(session, user_message, corrected_message=None):
    step = session["step"]
    data = session["data"]
    corrected = corrected_message or correct_spelling(user_message)
    lower = corrected.lower().strip()

    # Auto-fill name/email/phone from patient record (real app mode — skip asking)
    if session.get("_prefill_name") and "name" not in data:
        data["name"] = session["_prefill_name"]
    if session.get("_prefill_email") and "email" not in data:
        data["email"] = session["_prefill_email"]
    if session.get("_prefill_phone") and "phone" not in data:
        data["phone"] = session["_prefill_phone"]
    if session.get("patient_id") and "_patient_id" not in data:
        data["_patient_id"] = session["patient_id"]

    # At any step, detect promo/discount code intent and store for later
    if step and step not in (None, "ask_discount", "finalize_booking"):
        promo_match = re.search(r'\b(promo|promotion|discount|coupon|code|voucher)\b', lower)
        if promo_match and step in ("get_email", "get_name", "get_phone", "get_time"):
            data["_has_promo_code"] = True
            if step == "get_email":
                return "Great that you have a promo code! I'll ask for it after we collect your details.\n\nFirst, what's your **email address**? (or say **skip**)"
            elif step == "get_name":
                return "Great that you have a promo code! I'll ask for it shortly.\n\nFirst, what's your **full name**?"
            elif step == "get_phone":
                return "Great that you have a promo code! I'll ask for it right after this.\n\nWhat's your **phone number**?"

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
                off_dates = _get_off_dates_with_blocks(doctor_id, data.get("_admin_id", 0))
                session["_ui_options"] = {"type": "calendar", "doctor_id": doctor_id, "off_dates": off_dates}
                return "No problem! Pick a different date:"

    # Step 1: Ask for name (skip if patient is pre-filled)
    if step is None or step == "ask_name":
        if data.get("name") and session.get("_patient_prefilled"):
            # Patient already known — skip name, go to doctor/category selection
            admin_id = data.get("_admin_id", 1)
            all_doctors = db.get_doctors(admin_id)
            doctors = [d for d in all_doctors if d.get("status") == "active"]
            if doctors:
                cat_set = set()
                for d in doctors:
                    spec = d.get("specialty", "")
                    if spec:
                        for s in spec.split(","):
                            s = s.strip()
                            if s:
                                cat_set.add(s)
                categories = sorted(cat_set)
                if len(categories) > 1:
                    data["_all_doctors"] = doctors
                    data["_categories"] = categories
                    session["step"] = "get_category"
                    session["_ui_options"] = {"type": "categories", "items": [{"name": c} for c in categories]}
                    return f"Hi {data['name']}! What type of doctor would you like to see?"
                else:
                    data["_doctors"] = doctors
                    session["step"] = "get_doctor"
                    session["_ui_options"] = {"type": "doctors", "items": [{"name": d["name"], "specialty": d.get("specialty", "General"), "availability": d.get("availability", "Mon-Fri")} for d in doctors]}
                    return f"Hi {data['name']}! Which doctor would you like to see?"
            else:
                session["step"] = "get_date"
                return f"Hi {data['name']}! When would you like to come in?"
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
            # Get unique categories from active doctors (support comma-separated multi-specialty)
            cat_set = set()
            for d in doctors:
                spec = d.get("specialty", "")
                if spec:
                    for s in spec.split(","):
                        s = s.strip()
                        if s:
                            cat_set.add(s)
            categories = sorted(cat_set)
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
            if "email" in data and "phone" in data:
                session["step"] = "get_date"
                return f"Nice to meet you, {data['name']}! When would you like to come in?"
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
            # Maybe user typed a doctor name instead of a category — try matching
            for d in all_doctors:
                if d["name"].lower() in lower or lower in d["name"].lower():
                    data["doctor_name"] = d["name"]
                    data["doctor_id"] = d["id"]
                    session["step"] = "get_date"
                    off_dates = _get_off_dates_with_blocks(d["id"], data.get("_admin_id", 0))
                    session["_ui_options"] = {"type": "calendar", "doctor_id": d["id"], "off_dates": off_dates}
                    return f"Great choice! You'll be seeing **Dr. {d['name']}**.\n\nWhen would you like to come in?"
            # No match at all — re-show categories
            session["_ui_options"] = {"type": "categories", "items": [{"name": c} for c in categories]}
            return "I didn't recognize that specialty. Please pick one from the list:"

        # Filter doctors by chosen category (support comma-separated multi-specialty)
        doctors = [d for d in all_doctors if chosen_cat in [s.strip() for s in (d.get("specialty") or "").split(",")]]
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
        raw_lower = user_message.lower().strip()

        # Try exact match against raw input first (dropdown sends exact name)
        for d in doctors:
            if d["name"].lower() == raw_lower or d["name"].lower() == lower:
                chosen = d
                break

        # Try number selection
        if not chosen:
            num_match = re.search(r'(\d+)', lower)
            if num_match:
                idx = int(num_match.group(1)) - 1
                if 0 <= idx < len(doctors):
                    chosen = doctors[idx]

        # Try name matching against both raw and corrected
        if not chosen:
            for d in doctors:
                dname = d["name"].lower()
                if dname in raw_lower or raw_lower in dname or dname in lower or lower in dname:
                    chosen = d
                    break
            # Fuzzy: check if any word matches
            if not chosen:
                for d in doctors:
                    for word in raw_lower.split() + lower.split():
                        if len(word) >= 3 and word in d["name"].lower():
                            chosen = d
                            break

        if not chosen:
            # Re-show the doctors dropdown instead of returning None
            doctor_items = [{"label": f"Dr. {d['name']}", "sublabel": d.get("specialty", "")} for d in doctors]
            session["_ui_options"] = {"type": "doctors", "items": doctor_items}
            return "I didn't recognize that doctor. Please pick one from the list:"

        data["doctor_name"] = chosen["name"]
        data["doctor_id"] = chosen["id"]
        session["step"] = "get_date"
        off_dates = _get_off_dates_with_blocks(chosen["id"], data.get("_admin_id", 0))
        session["_ui_options"] = {"type": "calendar", "doctor_id": chosen["id"], "off_dates": off_dates}
        return f"Great choice! You'll be seeing **Dr. {chosen['name']}**.\n\nWhen would you like to come in?"

    # Step 3: Got date, show time slot dropdown
    if step == "get_date":
        result, error = cal.get_available_slots(user_message)
        if error:
            # Check if input looks like a date attempt or something else entirely
            date_like = bool(re.search(
                r'(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|'
                r'next\s+week|january|february|march|april|may|june|july|august|september|'
                r'october|november|december|\d{1,2}[/\-]\d{1,2}|\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th))',
                lower
            ))
            if date_like:
                doctor_id = data.get("doctor_id")
                off_dates = _get_off_dates_with_blocks(doctor_id, data.get("_admin_id", 0))
                session["_ui_options"] = {"type": "calendar", "doctor_id": doctor_id, "off_dates": off_dates}
                return error + "\n\nPlease pick another day:"
            # Not a date — return None to route to AI
            return None

        data["date_str"] = user_message
        data["date_display"] = result["date_display"]
        data["date_iso"] = result["date"].isoformat()

        # Check if this date is a doctor's off day or blocked by schedule
        doctor_id = data.get("doctor_id")
        admin_id = data.get("_admin_id", 0)
        if doctor_id:
            off_dates = _get_off_dates_with_blocks(doctor_id, admin_id)
            if data["date_iso"] in off_dates:
                doctor = db.get_doctor_by_id(doctor_id)
                doc_name = doctor["name"] if doctor else "The doctor"
                session["_ui_options"] = {
                    "type": "calendar",
                    "doctor_id": doctor_id,
                    "off_dates": off_dates,
                }
                return f"Sorry, Dr. **{doc_name}** is not available on **{data['date_display']}**. Please pick another date:"

        # Generate slots from doctor's schedule
        slots = []
        doctor_has_schedule = False
        if doctor_id:
            doctor = db.get_doctor_by_id(doctor_id)
            if doctor and doctor.get("start_time") and doctor["start_time"] != "00:00 AM":
                doctor_has_schedule = True
                doctor_breaks = db.get_doctor_breaks(doctor_id)
                slots = _generate_doctor_slots(doctor, breaks=doctor_breaks, selected_date=data.get("date_iso"))

        if not slots and not doctor_has_schedule:
            # Only fall back to generic calendar slots if doctor has no schedule configured
            slots = result["slots"]
        elif not slots and doctor_has_schedule:
            # Doctor has a schedule but no slots for this day (e.g. flexible off day)
            doc_name = doctor["name"] if doctor else "The doctor"
            off_dates = _get_off_dates_with_blocks(doctor_id, data.get("_admin_id", 0))
            session["_ui_options"] = {"type": "calendar", "doctor_id": doctor_id, "off_dates": off_dates}
            return f"Sorry, Dr. **{doc_name}** is not available on **{data['date_display']}**. Please pick another date:"

        # Filter out already booked times for this doctor on this date
        booked_times = []
        if doctor_id:
            booked_times = db.get_booked_times(doctor_id, result["date"].isoformat())

        available_slots = []
        booked_slot_names = []
        for s in slots:
            if _is_booked_slot(s["time"], booked_times):
                booked_slot_names.append(s["time"])
            else:
                available_slots.append(s)

        data["available_slots"] = available_slots
        data["booked_slot_names"] = booked_slot_names
        data["all_slots"] = slots

        # Build dropdown — available slots are selectable, booked ones shown as read-only
        dropdown_items = []
        for s in slots:
            item = {"name": s["time"], "hour": s["hour"], "minute": s.get("minute", 0)}
            if _is_booked_slot(s["time"], booked_times):
                item["booked"] = True
            dropdown_items.append(item)

        session["_ui_options"] = {"type": "timeslots", "items": dropdown_items}
        session["step"] = "get_time"
        return f"Here are the available times on **{data['date_display']}** for **Dr. {data.get('doctor_name', '')}**:"

    # Step 4: Got time, ask for email — or offer waitlist if slot is booked
    if step == "get_time":
        all_slots = data.get("all_slots", [])
        available_slots = data.get("available_slots", [])
        booked_names = data.get("booked_slot_names", [])

        # First try exact match against all slots (dropdown sends exact slot name)
        time_str_all = _extract_time(user_message, all_slots)

        if time_str_all:
            # Check if this slot is booked -> offer waitlist
            if time_str_all in booked_names:
                data["waitlist_time"] = time_str_all
                session["step"] = "waitlist_offer"
                return (f"Unfortunately **{time_str_all}** on **{data['date_display']}** is fully booked.\n\n"
                        f"Would you like to **join the waitlist**? We'll notify you instantly if a spot opens up — "
                        f"you'll get priority before it becomes available to anyone else.\n\n"
                        f"**Yes** — add me to the waitlist\n**No** — show me other times")
            # It's an available slot
            avail_names = [s["time"] for s in available_slots]
            if time_str_all in avail_names:
                data["chosen_time"] = time_str_all
                if "email" in data and "phone" in data:
                    # Patient prefilled — skip to discount/finalize
                    try:
                        if promo.has_active_promotions(data.get("_admin_id", 1)):
                            session["step"] = "ask_discount"
                            return f"**{time_str_all}** on **{data['date_display']}** — great choice!\n\nDo you have a discount or promo code? (or say **skip**)"
                    except Exception:
                        pass
                    session["step"] = "finalize_booking"
                    return handle_booking(session, user_message, corrected)
                session["step"] = "get_email"
                return f"**{time_str_all}** on **{data['date_display']}** — great choice!\n\nWhat's your email address? (We'll send you a confirmation)"

        # Fallback: try matching against available slots only
        time_str = _extract_time(user_message, available_slots)
        if time_str:
            # Safety check: make sure regex didn't match a booked slot's start time
            for bname in booked_names:
                if time_str.lower() in bname.lower() or bname.lower().startswith(time_str.lower()):
                    data["waitlist_time"] = bname
                    session["step"] = "waitlist_offer"
                    return (f"Unfortunately **{bname}** on **{data['date_display']}** is fully booked.\n\n"
                            f"Would you like to **join the waitlist**? We'll notify you instantly if a spot opens up — "
                            f"you'll get priority before it becomes available to anyone else.\n\n"
                            f"**Yes** — add me to the waitlist\n**No** — show me other times")
            data["chosen_time"] = time_str
            if "email" in data and "phone" in data:
                try:
                    if promo.has_active_promotions(data.get("_admin_id", 1)):
                        session["step"] = "ask_discount"
                        return f"**{time_str}** on **{data['date_display']}** — great choice!\n\nDo you have a discount or promo code? (or say **skip**)"
                except Exception:
                    pass
                session["step"] = "finalize_booking"
                return handle_booking(session, user_message, corrected)
            session["step"] = "get_email"
            return f"**{time_str}** on **{data['date_display']}** — great choice!\n\nWhat's your email address? (We'll send you a confirmation)"

        # No time match — re-show the time slots instead of returning None
        all_s = data.get("all_slots", [])
        if all_s:
            dropdown_items = []
            for s in all_s:
                item = {"name": s["time"], "hour": s["hour"], "minute": s.get("minute", 0)}
                if s["time"] in booked_names:
                    item["booked"] = True
                dropdown_items.append(item)
            session["_ui_options"] = {"type": "timeslots", "items": dropdown_items}
            return f"I didn't catch that. Please pick a time slot from the list for **{data.get('date_display', 'your chosen date')}**:"
        return None

    # Step 4b: Waitlist offer response
    if step == "waitlist_offer":
        if _is_affirmative(user_message):
            # Reuse name from booking flow if already provided
            if data.get("name"):
                data["waitlist_name"] = data["name"]
                session["step"] = "waitlist_get_email"
                return f"I'll add you to the waitlist, {data['name']}! What's your **email address**? (We'll send you a notification when a spot opens)"
            session["step"] = "waitlist_get_name"
            return "I'll add you to the waitlist! First, what's your **full name**?"
        elif _is_negative(user_message):
            session["step"] = "get_time"
            avail = data.get("available_slots", [])
            if avail:
                times_list = ", ".join([s["time"] for s in avail[:6]])
                return f"No problem! Here are the available times: {times_list}\n\nPick one that works for you."
            return "Unfortunately there are no other slots available on this date. Would you like to try a different day?"
        return "Please say **yes** to join the waitlist or **no** to see other available times."

    # Step 4c: Waitlist — get name
    if step == "waitlist_get_name":
        data["waitlist_name"] = user_message.strip().title()
        session["step"] = "waitlist_get_email"
        return f"Thanks, {data['waitlist_name']}! What's your **email address**? (We'll send you a notification when a spot opens)"

    # Step 4d: Waitlist — get email
    if step == "waitlist_get_email":
        extracted_email = _extract_email(user_message)
        if extracted_email:
            data["waitlist_email"] = extracted_email
            session["step"] = "waitlist_get_phone"
            return "Got it! And your **phone number**?"
        if any(w in lower for w in ["skip", "no email", "none", "na"]):
            data["waitlist_email"] = ""
            session["step"] = "waitlist_get_phone"
            return "No worries! What's your **phone number** then?"
        return "I couldn't find a valid email. Could you type it out? Example: john@example.com\n\nOr say **skip**."

    # Step 4e: Waitlist — get phone and add to waitlist
    if step == "waitlist_get_phone":
        extracted_phone = _extract_phone(user_message)
        if not extracted_phone:
            return "I couldn't find a valid phone number. Could you try again? Example: (555) 123-4567"

        # Add to waitlist
        try:
            wid = db.add_to_waitlist(
                admin_id=data.get("_admin_id", 0),
                doctor_id=data.get("doctor_id", 0),
                date=data.get("date_iso", data.get("date_str", "")),
                time_slot=data["waitlist_time"],
                patient_name=data["waitlist_name"],
                patient_email=data.get("waitlist_email", ""),
                patient_phone=extracted_phone,
                session_id=data.get("_session_id", "")
            )
            # Get their position
            position = 1
            try:
                wl = db.get_waitlist(data.get("_admin_id", 0), doctor_id=data.get("doctor_id", 0),
                                     date=data.get("date_iso", ""), time_slot=data["waitlist_time"])
                for i, entry in enumerate(wl):
                    if entry.get("id") == wid:
                        position = i + 1
                        break
            except Exception:
                pass

            doctor_name = data.get("doctor_name", "")
            doctor_info = f" with **Dr. {doctor_name}**" if doctor_name else ""

            session["flow"] = None
            session["step"] = None
            session["data"] = {}

            pos_label = {1: "1st", 2: "2nd", 3: "3rd"}.get(position, f"{position}th")
            return (
                f"You're on the waitlist! Here's your spot:\n\n"
                f"**Position:** {pos_label} in line\n"
                f"**Slot:** {data['waitlist_time']} on {data['date_display']}{doctor_info}\n"
                f"**Name:** {data['waitlist_name']}\n\n"
                f"If a spot opens up, you'll be notified immediately"
                f"{' at **' + data.get('waitlist_email', '') + '**' if data.get('waitlist_email') else ''}"
                f" and given a time window to confirm before it goes to the next person.\n\n"
                f"Is there anything else I can help you with?"
            )
        except Exception as e:
            session["flow"] = None
            session["step"] = None
            session["data"] = {}
            return "Sorry, something went wrong adding you to the waitlist. Please try again later."

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

    # Step 6a: Discount code step (Feature 12)
    if step == "ask_discount":
        code = user_message.strip()
        if _is_negative(code) or code.lower() in ('skip', 'none', 'لا', 'n/a', 'na'):
            # Check if loyalty should be offered
            patient_id = data.get("_patient_id") or session.get("patient_id")
            if patient_id:
                try:
                    balance = loyalty.get_balance_value(patient_id, data.get("_admin_id", 1))
                    if balance and balance.get("points", 0) > 0:
                        data["_loyalty_balance"] = balance
                        session["step"] = "ask_loyalty"
                        lang = session.get("language", "en")
                        return f"You have **{balance['points']}** loyalty points (worth **${balance.get('sar_value', 0):.2f}**). Would you like to use them for a discount? (yes/no)"
                except Exception:
                    pass
            session["step"] = "finalize_booking"
            return handle_booking(session, user_message, corrected_message)
        else:
            try:
                result = promo.validate_discount_code(data.get("_admin_id", 1), code)
                if result.get("valid"):
                    data["discount_code_id"] = result.get("code_id")
                    data["discount_info"] = result
                    session["step"] = "finalize_booking"
                    return handle_booking(session, user_message, corrected_message)
                else:
                    return result.get("error", "Invalid discount code. Please try again or say **skip**.")
            except Exception:
                session["step"] = "finalize_booking"
                return handle_booking(session, user_message, corrected_message)

    # Step 6b: Loyalty redemption step (Feature 18)
    if step == "ask_loyalty":
        if _is_affirmative(user_message):
            patient_id = data.get("_patient_id") or session.get("patient_id")
            balance = data.get("_loyalty_balance", {})
            if patient_id and balance.get("points", 0) > 0:
                try:
                    data["loyalty_points_used"] = balance["points"]
                    data["loyalty_discount"] = balance.get("sar_value", 0)
                except Exception:
                    pass
        session["step"] = "finalize_booking"
        return handle_booking(session, user_message, corrected_message)

    # Step: finalize_booking — after discount/loyalty, actually book
    if step == "finalize_booking":
        time_str = data.get("chosen_time", "")

        booking_result, error = cal.book_appointment(
            data.get("date_str", ""), time_str,
            data.get("name", ""), data.get("email", "")
        )
        if error:
            return error + "\n\nPlease pick another time from the available slots."

        # Save to database
        db.save_booking(
            customer_name=data["name"],
            customer_email=data.get("email", ""),
            customer_phone=data.get("phone", ""),
            date=booking_result["date"],
            time=booking_result["time"],
            calendar_event_id=booking_result.get("calendar_event_id", ""),
            doctor_id=data.get("doctor_id", 0),
            doctor_name=data.get("doctor_name", ""),
            admin_id=data.get("_admin_id", 0),
        )

        # Mark chat session as booked for analytics
        if data.get("_session_id"):
            try:
                db.mark_session_booked(data["_session_id"])
            except Exception:
                pass

        # ── Patient profile + pre-visit form ──
        form_token = None
        try:
            patient = db.get_or_create_patient(
                data.get("_admin_id", 0),
                name=data["name"], email=data.get("email", ""), phone=data.get("phone", ""))
            if patient:
                conn = db.get_db()
                last_booking = conn.execute("SELECT id FROM bookings WHERE customer_name=? AND date=? ORDER BY id DESC LIMIT 1",
                    (data["name"], booking_result["date"])).fetchone()
                if last_booking:
                    conn.execute("UPDATE bookings SET patient_id=? WHERE id=?", (patient["id"], last_booking["id"]))
                    conn.commit()
                    form_token = db.create_previsit_form(last_booking["id"], data.get("_admin_id", 0), patient_name=data["name"])
                conn.close()
        except Exception:
            form_token = None

        # Reminders will be scheduled after the patient confirms by filling the pre-visit form

        # Send pre-visit form email
        if data.get("email") and form_token:
            try:
                base_url = request.host_url.rstrip("/")
                form_url = f"{base_url}/form/{form_token}"
                email.send_previsit_form(
                    data["email"], data["name"], form_url,
                    booking_result["date_display"], booking_result["time"],
                    doctor_name=data.get("doctor_name", "")
                )
            except Exception:
                pass

        # A/B test + real-time event
        try:
            ab_testing.record_conversion(data.get("_admin_id", 0), 'opening_message', data.get("_session_id", ""))
        except Exception:
            pass
        try:
            realtime.emit_new_booking(data.get("_admin_id", 0), {
                "customer_name": data["name"],
                "doctor_name": data.get("doctor_name", ""),
                "date": booking_result["date"],
                "time": booking_result["time"],
            })
        except Exception:
            pass

        # Reset session
        session["flow"] = None
        session["step"] = None
        session["data"] = {}

        confirmation = (
            f"Almost there!\n\n"
            f"**Name:** {data['name']}\n"
        )
        if data.get("doctor_name"):
            confirmation += f"**Doctor:** Dr. {data['doctor_name']}\n"
        confirmation += (
            f"**Date:** {booking_result['date_display']}\n"
            f"**Time:** {booking_result['time']}\n"
        )
        if data.get("discount_info"):
            confirmation += f"**Discount:** {data['discount_info'].get('description', 'Applied')}\n"
        if data.get("loyalty_points_used"):
            confirmation += f"**Loyalty Points Used:** {data['loyalty_points_used']}\n"
        if data.get("email") and form_token:
            confirmation += (
                f"\nA **pre-visit form** has been sent to **{data['email']}**.\n"
                f"Please fill it out to **confirm your appointment**."
            )
            confirmation += f"\n\n📋 **Complete your form now:** [Click here](/form/{form_token})"
        elif data.get("email"):
            confirmation += f"\nA confirmation email has been sent to **{data['email']}**."
        confirmation += "\n\nIs there anything else I can help you with?"
        return confirmation

    # Step 6: Got phone, finalize booking
    if step == "get_phone":
        extracted_phone = _extract_phone(user_message)
        if not extracted_phone:
            return "I couldn't find a valid phone number. Could you try again? Example: (555) 123-4567 or 5551234567"

        data["phone"] = extracted_phone

        # Offer discount code before finalizing (Feature 12)
        try:
            promos_available = promo.has_active_promotions(data.get("_admin_id", 1))
            if promos_available or data.get("_has_promo_code"):
                session["step"] = "ask_discount"
                return "Do you have a **discount code**? Enter it now, or say **skip** if you don't have one."
        except Exception:
            pass

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

        # Mark chat session as booked for analytics
        if data.get("_session_id"):
            try:
                db.mark_session_booked(data["_session_id"])
            except Exception:
                pass

        # ── Feature 15: Create/update patient profile ──
        form_token = None
        try:
            patient = db.get_or_create_patient(
                data.get("_admin_id", 0),
                name=data["name"], email=data.get("email", ""), phone=data["phone"])
            if patient:
                # Link booking to patient
                conn = db.get_db()
                last_booking = conn.execute("SELECT id FROM bookings WHERE customer_name=? AND date=? ORDER BY id DESC LIMIT 1",
                    (data["name"], booking_result["date"])).fetchone()
                if last_booking:
                    conn.execute("UPDATE bookings SET patient_id=? WHERE id=?", (patient["id"], last_booking["id"]))
                    conn.commit()
                    # ── Feature 2: Create pre-visit form ──
                    form_token = db.create_previsit_form(last_booking["id"], data.get("_admin_id", 0), patient_name=data["name"])
                conn.close()
        except Exception:
            form_token = None

        # ── Feature 17: A/B test — track booking conversion (engine + legacy) ──
        try:
            ab_testing.record_conversion(data.get("_admin_id", 0), 'opening_message', data.get("_session_id", ""))
        except Exception:
            pass
        if session.get("_ab_test_id"):
            try:
                db.increment_ab_test(session["_ab_test_id"], session.get("_ab_variant", "a"), booked=True)
            except Exception:
                pass

        # ── Feature 16: Emit real-time new booking event ──
        try:
            booking_data_rt = {
                "customer_name": data["name"],
                "doctor_name": data.get("doctor_name", ""),
                "date": booking_result["date"],
                "time": booking_result["time"],
            }
            realtime.emit_new_booking(data.get("_admin_id", 0), booking_data_rt)
        except Exception:
            pass

        # Get booking ID for email links
        booking_id = None
        try:
            conn = db.get_db()
            bid_row = conn.execute("SELECT id FROM bookings WHERE customer_name=? AND date=? ORDER BY id DESC LIMIT 1",
                (data["name"], booking_result["date"])).fetchone()
            if bid_row:
                booking_id = bid_row["id"]
            conn.close()
        except Exception:
            pass

        # Reminders will be scheduled after the patient confirms by filling the pre-visit form

        # Send ONLY the pre-visit form email (confirmation sent after form is submitted)
        if data.get("email") and form_token:
            try:
                base_url = request.host_url.rstrip("/")
                form_url = f"{base_url}/form/{form_token}"
                email.send_previsit_form(
                    data["email"], data["name"], form_url,
                    booking_result["date_display"], booking_result["time"],
                    doctor_name=data.get("doctor_name", "")
                )
            except Exception:
                pass

        # Reset session
        session["flow"] = None
        session["step"] = None
        session["data"] = {}

        confirmation = (
            f"Almost there!\n\n"
            f"**Name:** {data['name']}\n"
        )
        if data.get("doctor_name"):
            confirmation += f"**Doctor:** Dr. {data['doctor_name']}\n"
        confirmation += (
            f"**Date:** {booking_result['date_display']}\n"
            f"**Time:** {booking_result['time']}\n"
        )
        if data.get("email") and form_token:
            confirmation += (
                f"\nA **pre-visit form** has been sent to **{data['email']}**.\n"
                f"Please fill it out to **confirm your appointment**."
            )
            confirmation += f"\n\n📋 **Complete your form now:** [Click here](/form/{form_token})"
        elif data.get("email"):
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
            session["_ui_options"] = {"type": "confirm_yesno", "items": [{"name": "Yes, cancel it", "value": "yes"}, {"name": "No, keep it", "value": "no"}]}
            doctor_info = f" with **Dr. {b['doctor_name']}**" if b.get("doctor_name") else ""
            return (f"I found one appointment on **{date_display}**:\n\n"
                    f"**{b['customer_name']}** — {b['time']}{doctor_info}\n\n"
                    f"Do you want to cancel this appointment?")

        # Multiple bookings — try to auto-match if user mentioned name, time, or doctor
        auto_matched = None
        for b in bookings:
            name_match = b.get("customer_name", "").lower() in lower
            doctor_match = b.get("doctor_name", "") and b["doctor_name"].lower() in lower
            # Check if the user mentioned a time that matches this booking
            time_match = False
            if b.get("time"):
                # Extract start time for matching (e.g. "2:00 PM" from "2:00 PM - 3:00 PM")
                btime = b["time"].split(" - ")[0].strip().lower() if " - " in b["time"] else b["time"].strip().lower()
                time_match = btime in lower or b["time"].lower() in lower
                # Also match "2 pm", "2pm", "2:00pm" etc.
                time_digits = re.search(r'(\d{1,2})\s*(?::?\s*(\d{2}))?\s*(am|pm)', lower)
                if time_digits:
                    user_hour = int(time_digits.group(1))
                    user_min = time_digits.group(2) or "00"
                    user_ampm = time_digits.group(3).upper()
                    user_time_str = f"{user_hour}:{user_min} {user_ampm}".lower()
                    time_match = time_match or user_time_str in btime

            if (name_match and doctor_match) or (name_match and time_match) or (doctor_match and time_match):
                auto_matched = b
                break

        if auto_matched:
            data["_booking_to_cancel"] = auto_matched
            session["step"] = "confirm"
            session["_ui_options"] = {"type": "confirm_yesno", "items": [{"name": "Yes, cancel it", "value": "yes"}, {"name": "No, keep it", "value": "no"}]}
            doctor_info = f" with **Dr. {auto_matched['doctor_name']}**" if auto_matched.get("doctor_name") else ""
            return (f"I found the appointment on **{date_display}**:\n\n"
                    f"**{auto_matched['customer_name']}** — {auto_matched['time']}{doctor_info}\n\n"
                    f"Do you want to cancel this appointment?")

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
            session["_ui_options"] = {"type": "confirm_yesno", "items": [{"name": "Yes, cancel it", "value": "yes"}, {"name": "No, keep it", "value": "no"}]}
            doctor_info = f" with **Dr. {chosen['doctor_name']}**" if chosen.get("doctor_name") else ""
            return (f"You selected:\n\n"
                    f"**{chosen['customer_name']}** — {chosen['time']}{doctor_info}\n\n"
                    f"Do you want to cancel this appointment?")

        return "I couldn't match that. Please pick a number from the list or say the patient name."

    # Step 3: Confirm cancellation
    if step == "confirm":
        if lower in ("yes", "yeah", "yep", "yea", "sure", "ok", "okay", "y", "yes please", "confirm"):
            booking = data.get("_booking_to_cancel")
            if booking:
                db.cancel_booking(booking["id"])
                # Trigger waitlist cascade — notify next waiting patient
                if booking.get("doctor_id") and booking.get("date") and booking.get("time"):
                    try:
                        import background_tasks
                        background_tasks.trigger_waitlist_processing(
                            booking.get("admin_id", 0), booking["doctor_id"],
                            booking["date"], booking["time"])
                    except Exception:
                        pass
                doctor_info = f" with Dr. {booking['doctor_name']}" if booking.get("doctor_name") else ""
                date_display = data.get("_cancel_date_display", booking["date"])
                # ── Feature 16: Emit real-time cancellation event ──
                try:
                    realtime.emit_booking_cancelled(admin_id, booking["id"], booking["customer_name"])
                except Exception:
                    pass
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

            # Owner notification disabled — only send to the customer's email
            # email.send_booking_notification_owner(
            #     data["name"], "", data["phone"], "N/A", "N/A"
            # )

            # Reset session
            session["flow"] = None
            session["step"] = None
            session["data"] = {}

            return (
                f"Got it, {data['name']}! We've saved your info and someone from our team "
                f"will reach out to you at **{data['phone']}** soon.\n\n"
                f"In the meantime, feel free to ask me any questions about our services!"
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

def process_message(session_id, user_message, admin_id=1, patient_id=None):
    session = get_session(session_id)
    session["admin_id"] = admin_id
    session["last_message_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Pre-fill patient info when patient_id is provided (real app mode) ──
    if patient_id and not session.get("_patient_prefilled"):
        patient_record = db.get_patient(patient_id)
        if patient_record:
            session["_patient_prefilled"] = True
            session["_patient"] = patient_record
            session["_greeting_name"] = patient_record.get("name", "")
            session["patient_id"] = patient_record.get("id")
            session["_patient_recognized"] = True
            # Store for auto-fill during booking flows
            session["_prefill_name"] = patient_record.get("name", "")
            session["_prefill_email"] = patient_record.get("email", "")
            session["_prefill_phone"] = patient_record.get("phone", "")

    # Trim history to prevent unbounded growth (some code paths bypass _reply)
    if len(session.get("history", [])) > 30:
        session["history"] = session["history"][-20:]

    # ── Feature 6: Detect language on first message (engine) ──
    if not session.get("language_detected"):
        try:
            lang = tr.detect_language(user_message)
            session["language"] = lang
            session["language_detected"] = True
            if lang not in tr.SUPPORTED_LANGUAGES:
                session["language"] = "en"
        except Exception:
            session["language"] = detect_language(user_message)
            session["language_detected"] = True

    # ── Feature 16: Emit chat activity in real-time ──
    try:
        name = session.get("_greeting_name", session.get("data", {}).get("name", "Visitor"))
        realtime.emit_chat_activity(admin_id, session_id, name, user_message[:100])
    except Exception:
        pass

    # ── Feature 15: Recognize returning patient (engine) ──
    if not session.get("_patient_recognized"):
        session["_patient_recognized"] = True
        phone_match = re.search(r'[\+]?[\d\s\-\(\)]{7,15}', user_message)
        email_match = re.search(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', user_message)
        if phone_match or email_match:
            try:
                existing_patient = patient_profile.recognize_patient(admin_id,
                    phone=phone_match.group().strip() if phone_match else "",
                    email=email_match.group() if email_match else "")
                if existing_patient:
                    session["_patient"] = existing_patient
                    session["_greeting_name"] = existing_patient.get("name", "")
                    session["patient_id"] = existing_patient.get("id")
            except Exception:
                # Fallback to db
                patient = db.get_or_create_patient(admin_id,
                    email=email_match.group() if email_match else "",
                    phone=phone_match.group().strip() if phone_match else "")
                if patient and patient.get("name"):
                    session["_patient"] = patient
                    session["_greeting_name"] = patient["name"]

    # ── Feature 17: A/B test — track conversation start (engine) ──
    if len(session.get("history", [])) == 0:
        try:
            ab_message = ab_testing.get_active_message(admin_id, 'opening_message', session_id)
            if ab_message:
                session["_ab_opening_message"] = ab_message
        except Exception:
            pass
        # Legacy fallback
        ab_test = db.get_active_ab_test(admin_id, "opening_message")
        if ab_test:
            import random
            variant = "a" if random.random() < 0.5 else "b"
            session["_ab_variant"] = variant
            session["_ab_test_id"] = ab_test["id"]
            db.increment_ab_test(ab_test["id"], variant)

    # ── Feature 9: Emergency detection via engine (enhanced) ──
    msg_lower_raw = user_message.lower()
    try:
        is_emerg, matched = emergency_handler.is_emergency(user_message)
        if is_emerg and session.get("flow") != "booking":
            lang = session.get("language", "en")
            result = emergency_handler.handle_emergency(user_message, admin_id, session.get("data", {}), lang)
            if result:
                if result.get("ui_options"):
                    session["_ui_options"] = result["ui_options"]
                try:
                    realtime.emit_emergency_alert(admin_id, result.get("alert", {}))
                except Exception:
                    pass
                session["history"].append({"role": "user", "content": user_message})
                session["history"].append({"role": "assistant", "content": result["response"]})
                return result["response"]
    except Exception:
        pass  # Fall through to legacy emergency handling

    # ── Feature 9 (legacy): Emergency fast-track detection ──
    is_emergency = any(kw in msg_lower_raw for kw in EMERGENCY_KEYWORDS)
    if is_emergency and session.get("flow") != "booking":
        first_aid = get_first_aid(user_message)
        # Find earliest available slot within 3 hours
        doctors = db.get_doctors(admin_id)
        active_docs = [d for d in doctors if d.get("status") == "active" and d.get("is_active", 1)]
        emergency_slots = []
        now = datetime.now()
        for doc in active_docs:
            breaks = db.get_doctor_breaks(doc["id"])
            slots = _generate_doctor_slots(doc, breaks, selected_date=now.strftime("%Y-%m-%d"))
            for s in slots:
                try:
                    slot_time = s["time"].split(" - ")[0].strip()
                    slot_dt = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {slot_time}", "%Y-%m-%d %I:%M %p")
                    if now <= slot_dt <= now + timedelta(hours=3):
                        booked = db.get_booked_times(doc["id"], now.strftime("%Y-%m-%d"))
                        if s["time"] not in booked and slot_time not in booked:
                            emergency_slots.append({"doctor": doc["name"], "doctor_id": doc["id"], "time": s["time"], "slot_dt": slot_dt})
                except Exception:
                    pass
        emergency_slots.sort(key=lambda x: x["slot_dt"])
        reply_parts = [f"🚨 **Emergency detected.** Here's immediate first-aid advice:\n\n{first_aid}"]
        if emergency_slots:
            slot = emergency_slots[0]
            reply_parts.append(f"\n\n**Earliest available slot:** {slot['time']} with Dr. {slot['doctor']} (TODAY)")
            reply_parts.append("\nWould you like me to book this emergency slot right away? Just say **yes**.")
            session["_emergency_slot"] = slot
        else:
            reply_parts.append("\n\nNo immediate slots available. Please call the clinic directly for emergency assistance.")
        reply_parts.append("\n\n📞 **Call us now** for immediate help.")
        session["history"].append({"role": "user", "content": user_message})
        response = "".join(reply_parts)
        session["history"].append({"role": "assistant", "content": response})
        return response

    # ── Feature 9: Handle "yes" to emergency booking ──
    if session.get("_emergency_slot") and msg_lower_raw in ("yes", "yeah", "yes please", "ok", "okay", "book it"):
        slot = session.pop("_emergency_slot")
        session["flow"] = "booking"
        session["data"] = {
            "_admin_id": admin_id, "_session_id": session_id,
            "doctor_id": slot["doctor_id"], "doctor_name": slot["doctor"],
            "date_str": "today", "date_iso": datetime.now().strftime("%Y-%m-%d"),
            "date_display": "Today", "chosen_time": slot["time"],
            "service": "Emergency Consultation"
        }
        session["history"].append({"role": "user", "content": user_message})
        # If patient is prefilled, skip name/email/phone — go straight to finalize
        if session.get("_prefill_name"):
            session["data"]["name"] = session["_prefill_name"]
            session["data"]["email"] = session.get("_prefill_email", "")
            session["data"]["phone"] = session.get("_prefill_phone", "")
            session["step"] = "finalize_booking"
            result = handle_booking(session, user_message)
            session["history"].append({"role": "assistant", "content": result})
            return result
        session["step"] = "get_name"
        response = f"🚨 **Emergency slot locked:** {slot['time']} with Dr. {slot['doctor']} today.\n\nPlease provide your **full name** to confirm:"
        session["history"].append({"role": "assistant", "content": response})
        return response

    # ── Feature 10: Check if conversation is handed off to human (engine) ──
    try:
        handoff = handoff_engine.get_handoff_for_session(session_id)
        if handoff and handoff["status"] == "assigned":
            handoff_engine.send_handoff_message(handoff["id"], "patient", session.get("_greeting_name", "Patient"), user_message)
            session["history"].append({"role": "user", "content": user_message})
            return "Message received. Our staff member is reviewing your message."
    except Exception:
        pass
    # Fallback: check via db
    handoff = db.get_handoff_by_session(session_id)
    if handoff and handoff["status"] in ("queued", "assigned"):
        session["history"].append({"role": "user", "content": user_message})
        if handoff["status"] == "queued":
            return "Your conversation has been transferred to our staff. A team member will be with you shortly. Please hold on."
        return "Message received. Our staff member is reviewing your message."

    # ── Feature 8: Doctor comparison request (engine) ──
    if session.get("flow") != "booking":
        try:
            if doctor_comparison.should_show_comparison(user_message):
                result = doctor_comparison.get_chatbot_comparison_response(admin_id, session.get("language", "en"))
                if result:
                    if result.get("ui_options"):
                        session["_ui_options"] = result["ui_options"]
                    session["history"].append({"role": "user", "content": user_message})
                    session["history"].append({"role": "assistant", "content": result["response"]})
                    return result["response"]
        except Exception:
            pass
        # Fallback: legacy inline comparison
        if re.search(r'\b(compare|comparison|which doctor|help me choose|not sure which)\b', msg_lower_raw):
            doctors = db.get_doctors(admin_id)
            active_docs = [d for d in doctors if d.get("status") == "active" and d.get("is_active", 1)]
            if active_docs:
                comparison = []
                for d in active_docs[:6]:
                    breaks = db.get_doctor_breaks(d["id"])
                    slots = _generate_doctor_slots(d, breaks)
                    avail_slots = [s for s in slots if not s.get("booked")]
                    next_slot = avail_slots[0]["time"] if avail_slots else "No slots today"
                    comparison.append({
                        "name": d["name"], "specialty": d.get("specialty", "General"),
                        "experience": f"{d.get('years_of_experience', 0)} years",
                        "languages": d.get("languages", ""), "next_available": next_slot
                    })
                session["_ui_options"] = {"type": "doctor_comparison", "items": comparison}
                session["history"].append({"role": "user", "content": user_message})
                response = "Here's a comparison of our available doctors. Tap any doctor to book with them:"
                session["history"].append({"role": "assistant", "content": response})
                return response

    # ── Feature 7: Gallery request for cosmetic treatments (engine) ──
    try:
        gallery_result = gallery_engine.get_chatbot_gallery(admin_id, user_message)
        if gallery_result:
            session["_ui_options"] = {"type": "gallery_carousel", "images": gallery_result["images"], "treatment": gallery_result["treatment_type"]}
            lang = session.get("language", "en")
            session["history"].append({"role": "user", "content": user_message})
            if lang == 'ar':
                response = f"إليك بعض النتائج الحقيقية من مرضانا في {gallery_result['treatment_type']}:"
            else:
                response = f"Here are some real results from our patients for {gallery_result['treatment_type']}:"
            session["history"].append({"role": "assistant", "content": response})
            return response
    except Exception:
        pass
    # Fallback: legacy inline gallery check
    cosmetic_keywords = {"whitening": "whitening", "veneers": "veneers", "veneer": "veneers",
        "braces": "braces", "implant": "implants", "implants": "implants",
        "before and after": None, "before after": None, "results": None, "gallery": None}
    for kw, treatment in cosmetic_keywords.items():
        if kw in msg_lower_raw:
            gallery_treatment = treatment or "general"
            images = db.get_gallery(admin_id, treatment_type=gallery_treatment)
            if not images and not treatment:
                images = db.get_gallery(admin_id)
            if images:
                session["_ui_options"] = {"type": "gallery", "items": [{"url": img["image_url"], "caption": img.get("caption", ""), "type": img.get("image_type", "")} for img in images]}
            break

    # ── Feature 18: Loyalty balance check in chat ──
    try:
        loyalty_keywords = ['points', 'loyalty', 'نقاط', 'مكافآت', 'how many points']
        if any(kw in msg_lower_raw for kw in loyalty_keywords):
            patient_id = session.get("patient_id") or (session.get("_patient", {}) or {}).get("id")
            if patient_id:
                balance = loyalty.get_balance_value(patient_id, admin_id)
                lang = session.get("language", "en")
                session["history"].append({"role": "user", "content": user_message})
                response = tr.t('loyalty_balance', lang, points=balance["points"], value=balance["sar_value"])
                session["history"].append({"role": "assistant", "content": response})
                return response
    except Exception:
        pass

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

    # ── Cancel detection (check BOTH raw message and corrected to avoid AI mangling) ──
    raw_lower = user_message.lower().strip()

    # Check for cancel at any point — exact matches + refusal patterns
    # Check both raw and corrected message to catch cases where AI cleaner transforms "cancel"
    cancel_words = ("cancel", "nevermind", "never mind", "stop", "go back", "start over", "quit", "exit")
    is_cancel = raw_lower in cancel_words or lower in cancel_words

    # When in a flow, be more generous with cancel detection
    # BUT: if the user says "cancel my appointment/booking", they want to cancel an EXISTING appointment,
    # not abort the current flow — so exclude that pattern
    wants_cancel_existing = bool(re.search(
        r"(cancel|delete|remove)\s+(my\s+|the\s+)?(app\w+|apo\w+|booking|reservation)",
        raw_lower
    ))
    if not is_cancel and session.get("flow") and not wants_cancel_existing:
        # "cancel" or common misspellings anywhere in the message
        is_cancel = bool(re.search(r'\b(cancel|cancle|cacnel|canel|cansel|cancell)\b', raw_lower))
        # Also check corrected text for "cancel" (AI may fix the typo)
        if not is_cancel:
            is_cancel = bool(re.search(r'\bcancel\b', lower))
        # Repeated "no" = refusal (e.g. "no no no")
        if not is_cancel:
            is_cancel = bool(re.match(r'^(no\s*){2,}', raw_lower))
        # Refusal phrases
        if not is_cancel:
            is_cancel = bool(re.search(
                r"\b(don'?t want|no\s+i\s+don|not\s+interested|i\s+refuse|no\s+thanks|no\s+thank|"
                r"i\s+changed\s+my\s+mind|forget\s+it|nah|nope\b.*book|no\s+i\s+don'?t|"
                r"don'?t\s+want\s+to\s+book|don'?t\s+need|no\s+booking|stop\s+booking)",
                raw_lower
            ))
    if is_cancel:
        if session["flow"]:
            flow_was = session["flow"]
            reset_session(session_id)
            session = get_session(session_id)  # Refresh local reference to new session
            if flow_was == "booking":
                return _reply("No problem, I've stopped the booking process. How else can I help you?")
            elif flow_was == "cancel_appointment":
                return _reply("OK, I've stopped the cancellation. Your appointment is still active. How else can I help you?")
            return _reply("No problem! How else can I help you?")
        return _reply("No worries! Is there anything else I can help you with?")

    # ── Feature 10: Early check for human handoff request (engine) ──
    human_phrases = ("speak to a human", "talk to someone", "real person", "human agent",
                     "live chat", "speak to staff", "talk to a person", "speak to someone",
                     "customer service", "i need help from a person", "talk to a real person")
    if any(phrase in raw_lower for phrase in human_phrases):
        try:
            handoff_engine.create_handoff(admin_id, session_id,
                patient_name=session.get("_greeting_name", ""),
                reason="Patient requested human assistance", ai_confidence=0)
            realtime.emit_handoff_request(admin_id, {"patient_name": session.get("_greeting_name", ""), "reason": "Patient requested human assistance"})
        except Exception:
            db.create_handoff(admin_id, session_id, patient_name=session.get("_greeting_name", ""),
                             reason="Patient requested human assistance", ai_confidence=0)
        session["history"].append({"role": "user", "content": user_message})
        lang = session.get("language", "en")
        try:
            response = tr.t('handoff_connecting', lang)
        except Exception:
            response = "I'm connecting you with a staff member now. A team member will be with you shortly. Please hold on — they'll see your full conversation history."
        session["history"].append({"role": "assistant", "content": response})
        return response

    # Detect if user wants to cancel an EXISTING appointment (only when NOT in a booking flow)
    # Use broad matching for "appointment" typos — any word starting with "app" or "apo" near cancel/delete
    # Check BOTH raw message and AI-corrected message (AI may fix "appoimtent" → "appointment")
    _appt_variants = r"(app\w+|apo\w+|booking|reservation)"
    _cancel_verbs = r"(cancel|delete|remove)"
    wants_cancel_appointment = False
    for _check_text in (raw_lower, lower):
        if wants_cancel_appointment:
            break
        wants_cancel_appointment = bool(re.search(
            _cancel_verbs + r"\s+(my\s+|the\s+)?" + _appt_variants, _check_text
        )) or bool(re.search(
            r"(want\s+to|need\s+to|can\s+i|please|wanna)\s+" + _cancel_verbs + r"\s+(my\s+|the\s+)?" + _appt_variants, _check_text
        )) or bool(re.search(
            _cancel_verbs + r"\b.*\b(dr\.?|doctor|appointment|booking)\b", _check_text
        ))

    if wants_cancel_appointment and session["flow"] != "cancel_appointment":
        session["flow"] = "cancel_appointment"
        session["step"] = "get_date"
        session["data"] = {"_admin_id": admin_id}
        # Try to extract a date from the initial message so user doesn't have to repeat
        from calendar_service import _parse_date
        parsed_date = _parse_date(raw_lower)
        if parsed_date:
            # Feed the message directly into the cancel flow
            result = handle_cancel_appointment(session, user_message, admin_id)
            return _reply(result)
        # Show calendar with booked dates highlighted
        booked_dates = db.get_booking_dates(admin_id)
        session["_ui_options"] = {"type": "calendar", "mode": "cancel", "booked_dates": booked_dates}
        return _reply("I can help you cancel your appointment. What date is it on?")

    # Handle cancel appointment flow
    if session["flow"] == "cancel_appointment":
        result = handle_cancel_appointment(session, user_message, admin_id)
        return _reply(result)

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
                off_dates = _get_off_dates_with_blocks(doctor_id, data.get("_admin_id", 0))
                session["_ui_options"] = {"type": "calendar", "doctor_id": doctor_id, "off_dates": off_dates}
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
                        slots = _generate_doctor_slots(doctor, breaks=doctor_breaks, selected_date=data.get("date_iso"))
                booked_times = []
                if doctor_id and date_iso:
                    booked_times = db.get_booked_times(doctor_id, date_iso)
                data["available_slots"] = [s for s in slots if not _is_booked_slot(s["time"], booked_times)]
                data["all_slots"] = slots
                data["booked_slot_names"] = [s["time"] for s in slots if _is_booked_slot(s["time"], booked_times)]
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

        # Try to handle the booking step
        booking_result = handle_booking(session, user_message, corrected)

        if booking_result is not None:
            return _reply(booking_result)

        # handle_booking returned None — user typed something that doesn't match
        # the current dropdown/step.
        step = session.get("step")
        data = session.get("data", {})

        # If in get_time step, re-show the time dropdown instead of pausing
        if step == "get_time":
            doctor_id = data.get("doctor_id")
            date_iso = data.get("date_iso")
            if doctor_id and date_iso:
                doctor = db.get_doctor_by_id(doctor_id)
                slots = []
                if doctor and doctor.get("start_time") and doctor["start_time"] != "00:00 AM":
                    doctor_breaks = db.get_doctor_breaks(doctor_id)
                    slots = _generate_doctor_slots(doctor, breaks=doctor_breaks, selected_date=date_iso)
                booked_times = db.get_booked_times(doctor_id, date_iso)
                data["available_slots"] = [s for s in slots if not _is_booked_slot(s["time"], booked_times)]
                data["all_slots"] = slots
                data["booked_slot_names"] = [s["time"] for s in slots if _is_booked_slot(s["time"], booked_times)]
                dropdown_items = []
                for s in slots:
                    item = {"name": s["time"], "hour": s["hour"], "minute": s.get("minute", 0)}
                    if _is_booked_slot(s["time"], booked_times):
                        item["booked"] = True
                    dropdown_items.append(item)
                if dropdown_items:
                    session["_ui_options"] = {"type": "timeslots", "items": dropdown_items}
                return _reply(f"Please pick a time slot from the list below for **{data.get('date_display', 'your chosen date')}**:")

        # For other steps, pause booking and route to AI
        session["_paused"] = True
        ai_answer = _ask_ai_during_booking(user_message, session, admin_id)
        if ai_answer:
            return _reply(ai_answer + "\n\nWhen you're ready to continue booking, just say **continue**.")
        return _reply("I'm not sure about that. Say **continue** to resume your booking.")
    if session["flow"] == "lead_capture":
        return _reply(handle_lead_capture(session, user_message))

    # Detect intent using the smart classifier (returns intent + confidence)
    classified_raw, classified_conf = intent_classifier.classify(corrected)
    intent = detect_intent(corrected)

    # Step 2b: Sklearn intent classifier — granular dental intent detection
    sklearn_intent, sklearn_conf = sklearn_classifier.classify(corrected)
    print(f"[router] sklearn: {sklearn_intent} ({sklearn_conf:.2f}) | classic: {classified_raw} ({classified_conf:.2f}) | flow: {intent}", flush=True)

    # Log conversation for analytics
    try:
        db.log_chat(session_id, admin_id, user_message, intent=sklearn_intent or classified_raw, intent_confidence=sklearn_conf)
    except Exception:
        pass

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
            if msg.get("role") != "user":
                continue  # Only check user messages, not bot responses
            content = msg.get("content", "").lower()
            if any(w in content for w in ["available", "time slots", "schedule", "availability"]):
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
            session["data"] = {"_admin_id": admin_id, "_session_id": session_id}
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

    # ── Fast Booking Detection ──
    # Triggers when message has booking keywords + details (doctor/time/date)
    # Works even if intent classifier misses it (e.g. "book with dr john at 2pm, any open spots?")
    # Skip if the user wants to cancel/delete an appointment
    _wants_cancel_or_delete = bool(re.search(r'\b(cancel|delete|remove)\b', raw_lower)) or bool(re.search(r'\b(cancel|delete|remove)\b', lower))
    has_booking_signal = not _wants_cancel_or_delete and (
        bool(re.search(
            r'\b(book|booking|reserve|reservation|schedule|appointment|appoint|apoitment|apointment)\b',
            raw_lower
        )) or (intent == "booking") or (sklearn_intent == "book_appointment")
    )

    if has_booking_signal:
        extracted, active_docs = _parse_fast_booking(corrected, admin_id)

        if extracted and any(k in extracted for k in ("doctor", "ambiguous_doctors", "time_raw", "date_raw")):
            # User provided booking details — use fast booking
            session["flow"] = "booking"
            session["step"] = None
            session["data"] = {"_admin_id": admin_id, "_session_id": session_id}
            reply_text, ui_opts = _init_fast_booking(session, extracted, active_docs, admin_id)
            if ui_opts:
                session["_ui_options"] = ui_opts
            return _reply(reply_text)

    # Start cancel appointment flow via intent detection
    if intent == "cancel" and session["flow"] != "cancel_appointment":
        session["flow"] = "cancel_appointment"
        session["step"] = "get_date"
        session["data"] = {"_admin_id": admin_id}
        from calendar_service import _parse_date
        parsed_date = _parse_date(raw_lower)
        if parsed_date:
            result = handle_cancel_appointment(session, user_message, admin_id)
            return _reply(result)
        booked_dates = db.get_booking_dates(admin_id)
        session["_ui_options"] = {"type": "calendar", "mode": "cancel", "booked_dates": booked_dates}
        return _reply("I can help you cancel your appointment. What date is it on?")

    # Start booking flow (needs state management — must stay before AI)
    if intent == "booking":
        session["flow"] = "booking"
        session["step"] = None
        session["data"] = {"_admin_id": admin_id, "_session_id": session_id}
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
    # Threshold lowered for 24-intent model (confidence spreads across more classes)
    if sklearn_intent and sklearn_conf > 0.15:
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

    # ── Feature 10: Check if user wants human handoff ──
    human_phrases = ("speak to a human", "talk to someone", "real person", "human agent",
                     "live chat", "speak to staff", "talk to a person", "speak to someone",
                     "customer service", "i need help from a person")
    if any(phrase in msg_lower_raw for phrase in human_phrases):
        db.create_handoff(admin_id, session_id, patient_name=session.get("_greeting_name", ""),
                         reason="Patient requested human assistance", ai_confidence=sklearn_conf)
        return _reply("I'm connecting you with a staff member now. A team member will be with you shortly. Please hold on — they'll see your full conversation history.")

    # ── Feature 10: Auto-handoff on very low confidence (engine) ──
    try:
        confidence_score = max(sklearn_conf, classified_conf)
        should_hand, reason = handoff_engine.should_handoff(user_message, confidence_score, admin_id)
        if should_hand:
            patient_name = session.get("_greeting_name", "Patient")
            handoff_engine.create_handoff(admin_id, session_id, patient_name, reason, ai_confidence=confidence_score)
            try:
                realtime.emit_handoff_request(admin_id, {"patient_name": patient_name, "reason": reason})
            except Exception:
                pass
            lang = session.get("language", "en")
            try:
                response = tr.t('handoff_connecting', lang)
            except Exception:
                response = "I'm connecting you with a staff member now. Please hold on."
            return _reply(response)
    except Exception:
        pass
    # Fallback: legacy auto-handoff
    if sklearn_conf < 0.15 and classified_conf < 0.3:
        try:
            company = db.get_company_info(admin_id)
            threshold = 0.3
            if company and company.get("handoff_threshold"):
                threshold = float(company["handoff_threshold"])
            if sklearn_conf < threshold and classified_conf < threshold:
                db.create_handoff(admin_id, session_id, patient_name=session.get("_greeting_name", ""),
                                 reason="Low AI confidence", ai_confidence=sklearn_conf)
        except Exception:
            pass

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
    if not data:
        return jsonify({"error": "Invalid or missing JSON body"}), 400
    user_message = data.get("message", "").strip()
    session_id = data.get("session_id", "default")
    admin_id = data.get("admin_id")
    if not admin_id:
        # Auto-detect: use the first head_admin's id so analytics data goes to the right place
        try:
            conn = db.get_db()
            head = conn.execute("SELECT id FROM users WHERE role='head_admin' ORDER BY id LIMIT 1").fetchone()
            admin_id = head["id"] if head else 1
            conn.close()
        except Exception:
            admin_id = 1

    if not user_message:
        return jsonify({"error": "Empty message"}), 400
    if len(user_message) > 2000:
        user_message = user_message[:2000]

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


@app.route("/api/patient/chat", methods=["POST"])
def patient_chat():
    """Chat endpoint for authenticated patients — skips name/email/phone collection."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    patient_id = data.get("patient_id")
    if not patient_id:
        return jsonify({"error": "patient_id is required"}), 400

    # Verify patient exists
    patient = db.get_patient(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    user_message = data.get("message", "").strip()
    session_id = data.get("session_id", f"patient_{patient_id}")
    admin_id = data.get("admin_id") or patient.get("admin_id")
    if not admin_id:
        try:
            conn = db.get_db()
            head = conn.execute("SELECT id FROM users WHERE role='head_admin' ORDER BY id LIMIT 1").fetchone()
            admin_id = head["id"] if head else 1
            conn.close()
        except Exception:
            admin_id = 1

    if not user_message:
        return jsonify({"error": "Empty message"}), 400
    if len(user_message) > 2000:
        user_message = user_message[:2000]

    try:
        reply = process_message(session_id, user_message, admin_id=admin_id, patient_id=patient_id)
        session = get_session(session_id)
        response = {"reply": reply}
        if session.get("_ui_options"):
            response["options"] = session.pop("_ui_options")
        return jsonify(response)
    except Exception as e:
        print(f"Patient chat error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/leads", methods=["GET"])
def api_leads():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if user.get("role") == "doctor":
        return jsonify([])  # Doctors don't see leads
    admin_id = get_effective_admin_id(user)
    return jsonify(db.get_all_leads(admin_id=admin_id))


@app.route("/api/bookings", methods=["GET"])
def api_bookings():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
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
        return jsonify({"error": "Not authenticated"}), 401
    if user.get("role") == "doctor":
        doctor = db.get_doctor_by_user_id(user["id"])
        if doctor:
            return jsonify(db.get_stats(doctor_id=doctor["id"]))
        return jsonify(db.get_stats())
    admin_id = get_effective_admin_id(user)
    return jsonify(db.get_stats(admin_id=admin_id))


@app.route("/api/analytics", methods=["GET"])
def api_analytics():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if user.get("role") == "doctor":
        return jsonify({"error": "Doctors cannot access analytics"}), 403
    admin_id = get_effective_admin_id(user)
    date_from = request.args.get("from", (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
    date_to = request.args.get("to", datetime.now().strftime("%Y-%m-%d"))
    data = db.get_analytics(admin_id, date_from, date_to)
    return jsonify(data)


@app.route("/api/bookings/<int:booking_id>/noshow", methods=["POST"])
def api_mark_noshow(booking_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    if user.get("role") == "doctor":
        return jsonify({"error": "Forbidden"}), 403
    conn = db.get_db()
    conn.execute("UPDATE bookings SET status = 'no_show' WHERE id = ? AND admin_id = ?",
                 (booking_id, get_effective_admin_id(user)))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


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
    if not is_admin_role(user):
        return jsonify({"error": "Only administrators can edit company info."}), 403
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
                     appointment_length=data.get("appointment_length"),
                     years_of_experience=data.get("years_of_experience"),
                     schedule_type=data.get("schedule_type"),
                     daily_hours=data.get("daily_hours"))
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


# ── Doctor PDF Upload ──

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads", "doctors")
os.makedirs(UPLOAD_DIR, exist_ok=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


@app.route("/api/doctors/upload-pdf", methods=["POST"])
def api_upload_doctor_pdf():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    if not is_admin_role(user):
        return jsonify({"error": "Only administrators can upload doctor PDFs."}), 403

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted."}), 400

    file_bytes = file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        return jsonify({"error": "File too large. Maximum 10 MB."}), 400

    # Extract text from PDF
    text = ""
    try:
        import PyPDF2, io
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        return jsonify({"error": f"Could not read PDF: {str(e)}"}), 400

    if not text.strip():
        return jsonify({"error": "No text could be extracted. The PDF may be a scanned image."}), 400

    if len(text) > 15000:
        text = text[:15000]

    # Save PDF locally
    safe_name = f"{uuid.uuid4().hex}_{filename}"
    pdf_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(pdf_path, "wb") as f:
        f.write(file_bytes)

    # AI extraction prompt — supports multiple doctors in one PDF
    ai_prompt = (
        "You are a medical data extraction assistant. This document may contain information about "
        "ONE or MULTIPLE doctors/medical professionals.\n\n"
        "Return ONLY a valid JSON ARRAY of objects. Each object represents one doctor with these fields:\n"
        "fullName, specialty, email, phone, availableDays, availableTimeSlots, dailyHours, qualifications, "
        "languages, bio, yearsOfExperience.\n\n"
        "Rules:\n"
        "- ALWAYS return a JSON array, even if there is only one doctor: [{...}]\n"
        "- Extract EVERY doctor mentioned in the document — do not skip any\n"
        "- For fullName: do NOT include the prefix 'Dr.' — just the name (e.g. \"Ahmad Al-Farsi\" not \"Dr. Ahmad Al-Farsi\")\n"
        "- For availableDays return a string like \"Mon-Fri\" or \"Sun,Mon,Tue,Wed,Thu\"\n"
        "- For availableTimeSlots: if the doctor has the SAME hours every day, return {\"from\":\"09:00 AM\",\"to\":\"05:00 PM\"}\n"
        "- For dailyHours: if the doctor has DIFFERENT hours on different days, return an object with day names as keys:\n"
        "  e.g. {\"Monday\":{\"from\":\"09:00 AM\",\"to\":\"05:00 PM\"},\"Tuesday\":{\"from\":\"10:00 AM\",\"to\":\"03:00 PM\"}}\n"
        "  Use full day names (Monday, Tuesday, etc.) and 12-hour format. Only include days the doctor works.\n"
        "  If all days have the same hours, set dailyHours to null and use availableTimeSlots instead.\n"
        "- For qualifications return a comma-separated string (e.g. \"BDS, MDS, PhD\")\n"
        "- For languages return a comma-separated string (e.g. \"Arabic, English\")\n"
        "- For yearsOfExperience return a number\n"
        "- For any field not found in the document, return null\n"
        "- Return ONLY the raw JSON array — no explanation, no markdown.\n\n"
        f"Document text:\n{text}"
    )

    extracted = None

    def _parse_ai_response(raw):
        """Parse AI response — handle both array and single object."""
        raw = raw.strip()
        # Try array first
        arr_start = raw.find("[")
        arr_end = raw.rfind("]") + 1
        if arr_start >= 0 and arr_end > arr_start:
            try:
                result = json.loads(raw[arr_start:arr_end])
                if isinstance(result, list) and len(result) > 0:
                    return result
            except json.JSONDecodeError:
                pass
        # Fallback: single object
        obj_start = raw.find("{")
        obj_end = raw.rfind("}") + 1
        if obj_start >= 0 and obj_end > obj_start:
            try:
                result = json.loads(raw[obj_start:obj_end])
                if isinstance(result, dict):
                    return [result]
            except json.JSONDecodeError:
                pass
        return None

    # Try Gemini first
    if GEMINI_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-1.5-flash")
            resp = model.generate_content(ai_prompt)
            extracted = _parse_ai_response(resp.text)
            if extracted:
                print(f"[doctor-pdf] Gemini extraction OK — {len(extracted)} doctor(s)", flush=True)
        except Exception as e:
            print(f"[doctor-pdf] Gemini extraction failed: {e}", flush=True)

    # Try Groq fallback
    if not extracted and message_interpreter.is_configured():
        try:
            client = message_interpreter._get_client()
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": ai_prompt}],
                max_tokens=4000, temperature=0,
            )
            raw = resp.choices[0].message.content.strip()
            extracted = _parse_ai_response(raw)
            if extracted:
                print(f"[doctor-pdf] Groq extraction OK — {len(extracted)} doctor(s)", flush=True)
        except Exception as e:
            print(f"[doctor-pdf] Groq extraction failed: {e}", flush=True)

    # Try OpenAI fallback
    if not extracted and dental_ai.is_configured():
        try:
            from openai import OpenAI
            client = OpenAI(api_key=dental_ai.OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": ai_prompt}],
                max_tokens=4000, temperature=0,
            )
            raw = resp.choices[0].message.content.strip()
            extracted = _parse_ai_response(raw)
            if extracted:
                print(f"[doctor-pdf] OpenAI extraction OK — {len(extracted)} doctor(s)", flush=True)
        except Exception as e:
            print(f"[doctor-pdf] OpenAI extraction failed: {e}", flush=True)

    # Try Anthropic fallback
    if not extracted:
        try:
            anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
            if anthropic_key:
                import httpx
                resp = httpx.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": "claude-sonnet-4-20250514", "max_tokens": 4000,
                          "messages": [{"role": "user", "content": ai_prompt}]},
                    timeout=60,
                )
                raw = resp.json().get("content", [{}])[0].get("text", "")
                extracted = _parse_ai_response(raw)
                if extracted:
                    print(f"[doctor-pdf] Anthropic extraction OK — {len(extracted)} doctor(s)", flush=True)
        except Exception as e:
            print(f"[doctor-pdf] Anthropic extraction failed: {e}", flush=True)

    if not extracted:
        return jsonify({"error": "AI could not extract doctor info. Please try again or enter manually."}), 400

    # Mark doctors that already exist under this admin
    import re as _re
    existing_docs = db.get_doctors(company_admin_id)
    existing_names = set()
    for ed in existing_docs:
        n = (ed.get("name") or "").strip().lower()
        if n:
            existing_names.add(n)
    for doc in extracted:
        raw = (doc.get("fullName") or "").strip()
        clean = _re.sub(r'^(?:Dr\.?\s+)+', '', raw, flags=_re.IGNORECASE).strip().lower()
        doc["alreadyExists"] = clean in existing_names

    return jsonify({"ok": True, "doctors": extracted, "pdf_filename": safe_name})


@app.route("/api/doctors/from-pdf", methods=["POST"])
def api_save_doctor_from_pdf():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    if not is_admin_role(user):
        return jsonify({"error": "Only administrators can add doctors."}), 403

    payload = request.get_json()
    company_admin_id = get_effective_admin_id(user)

    # Support both single doctor and array of doctors
    doctors_list = payload.get("doctors") or [payload]
    pdf_filename = payload.get("pdf_filename", "")

    # Build a set of existing doctor names (normalised) to skip duplicates
    existing_doctors = db.get_doctors(company_admin_id)
    existing_names = set()
    for ed in existing_doctors:
        n = (ed.get("name") or "").strip().lower()
        if n:
            existing_names.add(n)

    saved_ids = []
    skipped = []
    for data in doctors_list:
        name = (data.get("fullName") or "").strip()
        if not name:
            continue

        # Strip "Dr." prefix for comparison (same logic as _strip_dr_prefix in database.py)
        import re
        clean_name = re.sub(r'^(?:Dr\.?\s+)+', '', name, flags=re.IGNORECASE).strip()
        if clean_name.lower() in existing_names:
            skipped.append(name)
            continue

        time_slots = data.get("availableTimeSlots") or {}
        start_time = time_slots.get("from", "09:00 AM") if isinstance(time_slots, dict) else "09:00 AM"
        end_time = time_slots.get("to", "05:00 PM") if isinstance(time_slots, dict) else "05:00 PM"

        # Determine schedule type from extracted daily hours
        daily_hours = data.get("dailyHours") or ""
        schedule_type = data.get("scheduleType") or ("flexible" if daily_hours else "fixed")
        if daily_hours and isinstance(daily_hours, dict):
            daily_hours = json.dumps(daily_hours)

        doctor_id = db.add_doctor_from_pdf(
            admin_id=company_admin_id,
            name=name,
            email=(data.get("email") or "").strip(),
            specialty=(data.get("specialty") or "").strip(),
            bio=(data.get("bio") or "").strip(),
            availability=(data.get("availableDays") or "Mon-Fri").strip(),
            start_time=start_time,
            end_time=end_time,
            phone=(data.get("phone") or "").strip(),
            qualifications=(data.get("qualifications") or "").strip(),
            languages=(data.get("languages") or "").strip(),
            years_of_experience=data.get("yearsOfExperience") or 0,
            pdf_filename=pdf_filename,
            schedule_type=schedule_type,
            daily_hours=daily_hours if isinstance(daily_hours, str) else "",
        )
        saved_ids.append(doctor_id)
        existing_names.add(clean_name.lower())  # prevent duplicates within same batch

    if not saved_ids and not skipped:
        return jsonify({"error": "No valid doctors found to save."}), 400

    msg_parts = []
    if saved_ids:
        msg_parts.append(f"{len(saved_ids)} doctor(s) added successfully")
    if skipped:
        msg_parts.append(f"{len(skipped)} already existed and were skipped ({', '.join(skipped)})")

    return jsonify({"ok": True, "ids": saved_ids, "count": len(saved_ids),
                    "skipped": skipped, "skipped_count": len(skipped),
                    "message": ". ".join(msg_parts) + "."})


@app.route("/uploads/doctors/<path:filename>")
def serve_doctor_pdf(filename):
    return send_from_directory(UPLOAD_DIR, filename)


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
    """Public endpoint — returns just the ISO date strings for a doctor (includes schedule blocks)."""
    doctor = db.get_doctor_by_id(doctor_id)
    admin_id = doctor.get("admin_id", 0) if doctor else 0
    off_dates = _get_off_dates_with_blocks(doctor_id, admin_id)
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


# ══════════════════════════════════════════════════════════════════
#  Feature 1 — Smart Waitlist System
# ══════════════════════════════════════════════════════════════════

@app.route("/api/waitlist", methods=["POST"])
def api_add_to_waitlist():
    """Add a patient to the waitlist for a specific slot."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    data = request.get_json()
    admin_id = data.get("admin_id", 1)
    wid = db.add_to_waitlist(
        admin_id=admin_id,
        doctor_id=data["doctor_id"],
        date=data["date"],
        time_slot=data["time_slot"],
        patient_name=data.get("patient_name", ""),
        patient_email=data.get("patient_email", ""),
        patient_phone=data.get("patient_phone", ""),
        session_id=data.get("session_id", "")
    )
    count = db.get_waitlist_count(admin_id, data["doctor_id"], data["date"], data["time_slot"])
    return jsonify({
        "ok": True,
        "waitlist_id": wid,
        "position": count,
        "message": "You've been added to the waitlist. We'll notify you immediately if a spot opens up."
    })


@app.route("/api/waitlist", methods=["GET"])
def api_get_waitlist():
    """Get waitlist entries (filtered by doctor/date)."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    doctor_id = request.args.get("doctor_id", type=int)
    date = request.args.get("date")
    # Doctors can only see their own waitlist
    if user.get("role") == "doctor":
        doc = db.get_doctor_by_user_id(user["id"])
        if doc:
            doctor_id = doc["id"]
    entries = db.get_waitlist(admin_id, doctor_id=doctor_id, date=date)
    return jsonify(entries)


@app.route("/api/waitlist/dashboard", methods=["GET"])
def api_waitlist_dashboard():
    """Get all waitlist data for admin dashboard with countdown timers."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    entries = db.get_waitlist_for_admin(admin_id)
    return jsonify(entries)


@app.route("/api/waitlist/<int:wid>/confirm", methods=["POST", "GET"])
def api_confirm_waitlist(wid):
    """Waitlist spot opened — create pending booking + send pre-visit form.
    The booking is only confirmed after the patient fills the form.
    Supports both POST (API) and GET (email link click)."""
    entry = db.get_waitlist_entry(wid)
    if not entry:
        return jsonify({"error": "Waitlist entry not found"}), 404

    if entry["status"] == "confirmed":
        return jsonify({"ok": True, "message": "This slot has already been confirmed."})

    if entry["status"] != "notified":
        return jsonify({"error": "This slot is no longer available for confirmation. It may have expired."}), 400

    # Check deadline
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if entry["confirm_deadline"] and now > entry["confirm_deadline"]:
        # Mark as expired and cascade to next patient
        db.expire_waitlist_patient(wid)
        background_tasks.trigger_waitlist_processing(
            entry["admin_id"], entry["doctor_id"], entry["date"], entry["time_slot"])
        return jsonify({"error": "Sorry, the confirmation deadline has passed. The slot has been offered to the next person."}), 400

    # Get doctor name for booking
    doctor = db.get_doctor_by_id(entry["doctor_id"])
    doctor_name = doctor["name"] if doctor else ""

    # Create a PENDING booking (not confirmed yet — needs form submission)
    booking_id = db.add_booking(
        customer_name=entry["patient_name"],
        customer_email=entry.get("patient_email", ""),
        customer_phone=entry.get("patient_phone", ""),
        date=entry["date"],
        time=entry["time_slot"],
        doctor_id=entry["doctor_id"],
        doctor_name=doctor_name,
        admin_id=entry["admin_id"],
        status="pending"
    )

    # Link booking to waitlist entry
    try:
        conn = db.get_db()
        conn.execute("UPDATE bookings SET waitlist_id=? WHERE id=?", (wid, booking_id))
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Create pre-visit form and send form email (NOT confirmation email)
    form_token = None
    try:
        form_token = db.create_previsit_form(booking_id, entry["admin_id"], patient_name=entry["patient_name"])
    except Exception:
        pass

    if entry.get("patient_email") and form_token:
        try:
            base_url = os.getenv("BASE_URL", request.host_url.rstrip("/"))
            form_url = f"{base_url}/form/{form_token}"
            try:
                dt = datetime.strptime(entry["date"], "%Y-%m-%d")
                date_display = dt.strftime("%A, %B %d, %Y")
            except ValueError:
                date_display = entry["date"]
            email.send_previsit_form(
                entry["patient_email"], entry["patient_name"], form_url,
                date_display, entry["time_slot"],
                doctor_name=doctor_name
            )
        except Exception as e:
            import logging
            logging.getLogger("waitlist").error(f"Waitlist form email error: {e}")

    # If GET request (email link click), redirect to the form
    if request.method == "GET" and form_token:
        return redirect(f"/form/{form_token}")

    return jsonify({
        "ok": True,
        "message": "Please fill out the pre-visit form to confirm your appointment. Check your email!",
        "booking_id": booking_id,
        "form_token": form_token
    })


# ══════════════════════════════════════════════════════════════════
#  Feature 2 — Digital Patient Forms (Pre-Visit)
# ══════════════════════════════════════════════════════════════════

@app.route("/form/<token>")
def patient_form_page(token):
    """Serve the patient-form.html page (form handles all states via JS)."""
    return send_from_directory("static", "patient-form.html")

@app.route("/api/forms/<token>", methods=["GET"])
def api_get_form(token):
    """Return form data: booking details, patient name, and whether already submitted."""
    form = db.get_form_by_token(token)
    if not form:
        return jsonify({"error": "Invalid or expired link"}), 404
    if form.get("submitted_at"):
        return jsonify({"already_submitted": True})
    # Get booking details
    booking = db.get_booking_by_id(form["booking_id"]) if form.get("booking_id") else None
    return jsonify({
        "already_submitted": False,
        "full_name": form.get("full_name", ""),
        "date": booking["date"] if booking else "",
        "time": booking["time"] if booking else "",
        "doctor_name": booking.get("doctor_name", "") if booking else ""
    })

@app.route("/api/forms/<token>", methods=["POST"])
def api_submit_form(token):
    """Submit the form. Save all data + signature. Sync to patient profile."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    success = db.submit_previsit_form(token, data)
    if not success:
        return jsonify({"error": "Form already submitted or invalid token"}), 400

    # Sync to patient profile
    form = db.get_form_by_token(token)
    if form and form.get("booking_id"):
        booking = db.get_booking_by_id(form["booking_id"])
        if booking and booking.get("patient_id"):
            db.sync_form_to_patient(data, booking["patient_id"])

        # ── Confirm the booking now that form is submitted ──
        if booking and booking.get("status") == "pending":
            db.confirm_booking_by_id(form["booking_id"])

            # Send confirmation email
            if booking.get("customer_email"):
                try:
                    dt = datetime.strptime(booking["date"], "%Y-%m-%d")
                    date_display = dt.strftime("%A, %B %d, %Y")
                except (ValueError, TypeError):
                    date_display = booking.get("date", "")
                try:
                    base_url = request.host_url.rstrip("/")
                    confirm_url = f"{base_url}/booking-confirmed/{form['booking_id']}"
                except Exception:
                    confirm_url = ""
                email.send_booking_confirmation_customer(
                    booking["customer_name"],
                    booking["customer_email"],
                    date_display,
                    booking["time"],
                    doctor_name=booking.get("doctor_name", ""),
                    confirm_url=confirm_url
                )

            # Schedule appointment reminders now that booking is confirmed
            try:
                reminder_eng.schedule_reminders(form["booking_id"], booking.get("admin_id", 0))
            except Exception:
                pass

            # If this was a waitlist booking, confirm the waitlist entry too
            if booking.get("waitlist_id"):
                try:
                    db.confirm_waitlist_patient(booking["waitlist_id"])
                except Exception:
                    pass

    # Award loyalty points for form completion
    if form and form.get("admin_id"):
        booking = db.get_booking_by_id(form["booking_id"]) if form.get("booking_id") else None
        if booking:
            try:
                patient = db.get_or_create_patient(form["admin_id"],
                    name=booking.get("customer_name", ""), email=booking.get("customer_email", ""), phone=booking.get("customer_phone", ""))
                if patient:
                    config = db.get_loyalty_config(form["admin_id"])
                    if config and config.get("is_active"):
                        db.add_loyalty_points(patient["id"], form["admin_id"], config.get("points_per_form", 25), "form_completed", "Pre-visit form completed")
            except Exception:
                pass

    return jsonify({"success": True})

@app.route("/api/bookings/<int:booking_id>/form", methods=["GET"])
def api_get_booking_form(booking_id):
    """Get form data for dashboard view of a booking."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    form = db.get_form_for_booking(booking_id)
    if not form:
        return jsonify({"error": "No form found"}), 404
    return jsonify(dict(form))


# ── Booking Confirmation Page (public, accessed via email link) ──

@app.route("/booking-confirmed/<int:booking_id>")
def booking_confirmed_page(booking_id):
    return send_from_directory("static", "booking-confirmed.html")

@app.route("/api/bookings/<int:booking_id>/details", methods=["GET"])
def api_booking_details_public(booking_id):
    """Public endpoint for booking confirmation page (limited info)."""
    conn = db.get_db()
    booking = conn.execute("SELECT customer_name, date, time, doctor_name, service, status, admin_id FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking:
        conn.close()
        return jsonify({"error": "Booking not found"}), 404
    booking = dict(booking)
    # Get business name
    biz = conn.execute("SELECT business_name FROM company_info WHERE user_id=?", (booking["admin_id"],)).fetchone()
    conn.close()
    return jsonify({
        "customer_name": booking["customer_name"],
        "date": booking["date"],
        "time": booking["time"],
        "doctor_name": booking.get("doctor_name", ""),
        "service": booking.get("service", ""),
        "status": booking["status"],
        "business_name": biz["business_name"] if biz else ""
    })


# ══════════════════════════════════════════════════════════════════
#  Feature 3 — Recall & Retention Automation
# ══════════════════════════════════════════════════════════════════

@app.route("/api/recall-rules", methods=["GET"])
def api_get_recall_rules():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    try:
        rules = recall_engine.get_recall_rules(admin_id)
        return jsonify(rules)
    except Exception:
        return jsonify(db.get_recall_rules(admin_id))

@app.route("/api/recall-rules", methods=["POST"])
def api_add_recall_rule():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    admin_id = get_effective_admin_id(user)
    try:
        recall_engine.add_recall_rule(admin_id, data["treatment_type"], data.get("recall_days", 180), data.get("message_template", ""))
    except Exception:
        db.add_recall_rule(admin_id, data["treatment_type"], data.get("recall_days", 180), data.get("message_template", ""))
    return jsonify({"ok": True})

@app.route("/api/recall-rules/<int:rule_id>", methods=["PUT"])
def api_update_recall_rule(rule_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    admin_id = get_effective_admin_id(user)
    db.update_recall_rule(rule_id, admin_id, **data)
    return jsonify({"ok": True})

@app.route("/api/recall-rules/<int:rule_id>", methods=["DELETE"])
def api_delete_recall_rule(rule_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    db.delete_recall_rule(rule_id, admin_id)
    return jsonify({"ok": True})

@app.route("/api/recall-campaigns", methods=["GET"])
def api_get_recall_campaigns():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    return jsonify({"campaigns": db.get_recall_campaigns(admin_id), "stats": db.get_recall_stats(admin_id)})


# ══════════════════════════════════════════════════════════════════
#  Feature 4 — Missed Call Auto-Reply
# ══════════════════════════════════════════════════════════════════

@app.route("/api/missed-calls/webhook", methods=["POST"])
def api_missed_call_webhook():
    """Webhook endpoint for Twilio/phone system to report missed calls."""
    data = request.get_json() or request.form.to_dict()
    admin_id = data.get("admin_id", 1)
    caller = data.get("From") or data.get("caller_number", "")
    if not caller:
        return jsonify({"error": "No caller number"}), 400
    try:
        result = missed_call_engine.handle_missed_call(admin_id, caller)
        return jsonify(result)
    except Exception:
        # Fallback to legacy
        call_id = db.log_missed_call(admin_id, caller)
        db.update_missed_call(call_id, reply_sent=1, reply_method="sms_whatsapp")
        return jsonify({"ok": True, "call_id": call_id})

@app.route("/api/missed-calls", methods=["GET"])
def api_get_missed_calls():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    return jsonify(db.get_missed_calls(admin_id))

@app.route("/api/settings/missed-calls", methods=["POST"])
def api_toggle_missed_calls():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    admin_id = get_effective_admin_id(user)
    conn = db.get_db()
    conn.execute("UPDATE company_info SET missed_call_enabled=?, clinic_phone=? WHERE user_id=?",
                 (1 if data.get("enabled") else 0, data.get("clinic_phone", ""), admin_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════
#  Feature 5 — Treatment Plan Follow-Up
# ══════════════════════════════════════════════════════════════════

@app.route("/api/treatment-followups", methods=["POST"])
def api_create_followup():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    admin_id = get_effective_admin_id(user)
    try:
        result = treatment_followup_engine.create_followup(
            admin_id=admin_id,
            doctor_id=data.get("doctor_id", 0),
            patient_name=data["patient_name"],
            treatment_name=data["treatment_name"],
            patient_email=data.get("patient_email", ""),
            patient_phone=data.get("patient_phone", "")
        )
        return jsonify(result if result else {"ok": True, "message": "Follow-up sequence created (2, 5, 10 days)."})
    except Exception:
        db.create_treatment_followup(
            admin_id=admin_id,
            doctor_id=data.get("doctor_id", 0),
            patient_name=data["patient_name"],
            treatment_name=data["treatment_name"],
            patient_email=data.get("patient_email", ""),
            patient_phone=data.get("patient_phone", "")
        )
        return jsonify({"ok": True, "message": "Follow-up sequence created (2, 5, 10 days)."})

@app.route("/api/treatment-followups", methods=["GET"])
def api_get_followups():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    status = request.args.get("status")
    return jsonify(db.get_treatment_followups(admin_id, status=status))

@app.route("/api/treatment-followups/<int:fid>/cancel", methods=["POST"])
def api_cancel_followup(fid):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE treatment_followups SET status='cancelled', cancelled_at=? WHERE id=?", (now, fid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════
#  Feature 6 — Multilingual AI (language detection in /chat)
# ══════════════════════════════════════════════════════════════════

def detect_language(text):
    """Detect language of text. Returns ISO code."""
    try:
        from langdetect import detect
        lang = detect(text)
        lang_map = {"ar": "ar", "en": "en", "ur": "ur", "tl": "tl", "fil": "tl"}
        return lang_map.get(lang, lang)
    except Exception:
        return "en"

LANG_LABELS = {"en": "English", "ar": "العربية", "ur": "اردو", "tl": "Tagalog"}

@app.route("/api/chat-sessions/<session_id>/language", methods=["POST"])
def api_set_chat_language(session_id):
    """Staff override for conversation language."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    lang = data.get("language", "en")
    if session_id in sessions:
        sessions[session_id]["language"] = lang
    return jsonify({"ok": True, "language": lang})


# ══════════════════════════════════════════════════════════════════
#  Feature 7 — Before & After Gallery
# ══════════════════════════════════════════════════════════════════

@app.route("/api/gallery", methods=["GET"])
def api_get_gallery():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    treatment = request.args.get("treatment_type")
    return jsonify(db.get_gallery(admin_id, treatment_type=treatment))

@app.route("/api/gallery", methods=["POST"])
def api_upload_gallery():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    treatment = request.form.get("treatment_type", "general")
    image_type = request.form.get("image_type", "after")
    caption = request.form.get("caption", "")
    pair_id = request.form.get("pair_id", "")
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "No image uploaded"}), 400
    # Try engine first
    try:
        result = gallery_engine.upload_image(admin_id, treatment, file, image_type, caption)
        if result:
            return jsonify(result)
    except Exception:
        pass
    # Fallback: legacy upload
    existing = db.get_gallery(admin_id, treatment_type=treatment)
    if len(existing) >= 20:
        return jsonify({"error": "Maximum 20 photos per treatment type"}), 400
    import uuid as _uuid
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        return jsonify({"error": "Only JPG and PNG files allowed"}), 400
    safe_name = f"{_uuid.uuid4().hex}{ext}"
    upload_dir = os.path.join(os.path.dirname(__file__), "uploads", "gallery")
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, safe_name))
    image_url = f"/uploads/gallery/{safe_name}"
    db.add_gallery_image(admin_id, treatment, image_url, image_type, pair_id, caption)
    return jsonify({"ok": True, "url": image_url})

@app.route("/api/gallery/<int:image_id>", methods=["DELETE"])
def api_delete_gallery(image_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    db.delete_gallery_image(image_id, admin_id)
    return jsonify({"ok": True})

@app.route("/uploads/gallery/<path:filename>")
def serve_gallery_image(filename):
    return send_from_directory(os.path.join(os.path.dirname(__file__), "uploads", "gallery"), filename)

@app.route("/api/gallery/public", methods=["GET"])
def api_public_gallery():
    """Public endpoint for chatbot to fetch gallery images."""
    admin_id = request.args.get("admin_id", 1, type=int)
    treatment = request.args.get("treatment_type")
    return jsonify(db.get_gallery(admin_id, treatment_type=treatment))


# ══════════════════════════════════════════════════════════════════
#  Feature 8 — Multi-Doctor Comparison (in chatbot)
# ══════════════════════════════════════════════════════════════════

@app.route("/api/doctors/compare", methods=["GET"])
def api_compare_doctors():
    admin_id = request.args.get("admin_id", 1, type=int)
    category = request.args.get("category", "")
    doctors = db.get_doctors(admin_id)
    active = [d for d in doctors if d.get("status") == "active" and d.get("is_active", 1)]
    if category:
        cat_lower = category.lower()
        active = [d for d in active if cat_lower in (d.get("specialty") or "").lower()]
    result = []
    for d in active:
        # Get next available slot
        breaks = db.get_doctor_breaks(d["id"])
        slots = _generate_doctor_slots(d, breaks)
        available_slots = [s for s in slots if not s.get("booked")]
        next_slot = available_slots[0]["time"] if available_slots else "No slots today"
        result.append({
            "id": d["id"], "name": d["name"], "specialty": d.get("specialty", ""),
            "years_of_experience": d.get("years_of_experience", 0),
            "languages": d.get("languages", ""), "bio": d.get("bio", ""),
            "next_available": next_slot,
            "availability": d.get("availability", "Mon-Fri")
        })
    return jsonify(result)


# ══════════════════════════════════════════════════════════════════
#  Feature 9 — Emergency Fast-Track Flow (integrated in /chat)
# ══════════════════════════════════════════════════════════════════

EMERGENCY_KEYWORDS = ["severe pain", "broken tooth", "swollen jaw", "knocked out",
    "can't sleep from pain", "bleeding won't stop", "abscess", "face swollen",
    "emergency", "unbearable pain", "tooth fell out", "hit my tooth"]

FIRST_AID = {
    "knocked out": "Keep the tooth moist — place it in milk or between your cheek and gum. Do NOT touch the root. Come in immediately.",
    "broken tooth": "Rinse your mouth gently with warm water. Apply a cold compress to reduce swelling. Avoid chewing on that side.",
    "swollen": "Apply a cold compress to the outside of your cheek (20 min on, 20 min off). Do NOT apply heat. Take ibuprofen if you can.",
    "bleeding": "Apply firm pressure with a clean gauze for 15-20 minutes. If bleeding doesn't stop, come in immediately.",
    "pain": "Rinse with warm salt water. Take over-the-counter pain relief (ibuprofen preferred). Avoid very hot or cold foods.",
    "abscess": "Do NOT pop or squeeze it. Rinse with warm salt water every few hours. This requires urgent antibiotic treatment.",
}

def get_first_aid(message):
    msg_lower = message.lower()
    for key, advice in FIRST_AID.items():
        if key in msg_lower:
            return advice
    return FIRST_AID["pain"]


# ── Feature 9 — Emergency Alerts API (engine) ──

@app.route('/api/emergency-alerts', methods=['GET'])
def get_emergency_alerts_api():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    try:
        alerts = emergency_handler.get_emergency_alerts(admin_id)
        return jsonify(alerts)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/emergency-alerts/<int:alert_id>/acknowledge', methods=['POST'])
def acknowledge_emergency(alert_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        emergency_handler.acknowledge_alert(alert_id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════
#  Feature 10 — Live Chat Handoff
# ══════════════════════════════════════════════════════════════════

@app.route("/api/handoffs", methods=["GET"])
def api_get_handoffs():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    try:
        return jsonify(handoff_engine.get_handoff_queue(admin_id))
    except Exception:
        return jsonify(db.get_handoff_queue(admin_id))

@app.route("/api/handoffs/<int:hid>/assign", methods=["POST"])
def api_assign_handoff(hid):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        handoff_engine.assign_handoff(hid, user["id"], user["name"])
    except Exception:
        db.assign_handoff(hid, user["id"], user["name"])
    return jsonify({"ok": True})

@app.route("/api/handoffs/<int:hid>/resolve", methods=["POST"])
def api_resolve_handoff(hid):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    try:
        handoff_engine.resolve_handoff(hid, data.get("notes", ""))
    except Exception:
        db.resolve_handoff(hid, data.get("notes", ""))
    return jsonify({"ok": True})

@app.route("/api/handoffs/<int:hid>/message", methods=["POST"])
def api_handoff_message(hid):
    """Staff sends a message to the patient in a handed-off conversation."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    try:
        handoff_engine.send_handoff_message(hid, "staff", user["name"], data["message"])
    except Exception:
        pass
    # Also store in session history (legacy)
    handoff = db.get_handoff_by_session(data.get("session_id", ""))
    if not handoff:
        return jsonify({"error": "Handoff not found"}), 404
    sid = handoff["session_id"]
    if sid in sessions:
        sessions[sid]["history"].append({"role": "bot", "content": data["message"], "from_staff": True, "staff_name": user["name"]})
    return jsonify({"ok": True})

@app.route("/api/chat-sessions/<session_id>/history", methods=["GET"])
def api_get_session_history(session_id):
    """Get conversation history for a session (for handoff view)."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    if session_id in sessions:
        return jsonify({"history": sessions[session_id].get("history", []), "flow": sessions[session_id].get("flow")})
    return jsonify({"history": [], "flow": None})


# ══════════════════════════════════════════════════════════════════
#  Feature 11 — Block & Holiday Scheduling (rebuilt)
# ══════════════════════════════════════════════════════════════════

@app.route("/api/schedule-blocks", methods=["GET"])
def api_get_schedule_blocks():
    """Get all schedule blocks for the admin. Optional ?doctor_id= filter."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    doctor_id = request.args.get("doctor_id", type=int)
    return jsonify(db.get_schedule_blocks(admin_id, doctor_id=doctor_id))

@app.route("/api/schedule-blocks", methods=["POST"])
def api_add_schedule_block():
    """Create a new block. Supports single_date, date_range, and recurring types.
    Body: {
        "doctor_id": null or int,
        "block_type": "single_date" | "date_range" | "recurring",
        "start_date": "2024-03-15",
        "end_date": "2024-03-20",
        "start_time": "12:00 PM",
        "end_time": "01:00 PM",
        "recurring_pattern": "weekly",
        "recurring_day": 0,
        "label": "Lunch Break"
    }
    Returns warning if date has existing bookings."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    admin_id = get_effective_admin_id(user)

    block_type = data.get("block_type", "single_date")
    start_date = data.get("start_date", "")
    if not start_date:
        return jsonify({"error": "start_date is required"}), 400

    bid = db.create_schedule_block(
        admin_id=admin_id,
        doctor_id=data.get("doctor_id"),  # None = entire clinic
        block_type=block_type,
        start_date=start_date,
        end_date=data.get("end_date"),
        start_time=data.get("start_time"),
        end_time=data.get("end_time"),
        recurring_pattern=data.get("recurring_pattern"),
        recurring_day=data.get("recurring_day"),
        label=data.get("label"),
    )

    # Check for existing bookings on the blocked date(s) and warn
    warning = None
    existing = db.get_bookings_on_date(admin_id, start_date, doctor_id=data.get("doctor_id"))
    if existing > 0:
        warning = f"Warning: {start_date} has {existing} confirmed booking(s) that may be affected."

    return jsonify({"ok": True, "block_id": bid, "warning": warning})

@app.route("/api/schedule-blocks/<int:block_id>", methods=["DELETE"])
def api_delete_schedule_block(block_id):
    """Delete a block. Query param ?series=true deletes entire recurring series."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    delete_series = request.args.get("series", "").lower() == "true"
    if delete_series:
        db.delete_recurring_series(block_id)
    else:
        db.delete_schedule_block(block_id, admin_id)
    return jsonify({"ok": True})

@app.route("/api/schedule-blocks/check", methods=["POST"])
def api_check_block_conflicts():
    """Before creating a block, check how many existing bookings would be affected."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    admin_id = get_effective_admin_id(user)
    start_date = data.get("start_date", "")
    end_date = data.get("end_date", start_date)
    doctor_id = data.get("doctor_id")

    # Count bookings across the date range
    total_bookings = 0
    if start_date:
        from datetime import datetime as _dt_check, timedelta as _td_check
        try:
            d = _dt_check.strptime(start_date, "%Y-%m-%d")
            end_d = _dt_check.strptime(end_date, "%Y-%m-%d") if end_date else d
            while d <= end_d:
                ds = d.strftime("%Y-%m-%d")
                total_bookings += db.get_bookings_on_date(admin_id, ds, doctor_id=doctor_id)
                d += _td_check(days=1)
        except (ValueError, TypeError):
            pass

    warning = None
    if total_bookings > 0:
        warning = f"This block would affect {total_bookings} confirmed booking(s). Patients may need to be rescheduled."

    return jsonify({"existing_bookings": total_bookings, "warning": warning})


# ══════════════════════════════════════════════════════════════════
#  Feature 12 — Promotions & Discount Engine
# ══════════════════════════════════════════════════════════════════

@app.route("/api/promotions", methods=["GET"])
def api_get_promotions():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    return jsonify({"promotions": db.get_promotions(admin_id), "stats": db.get_promotion_stats(admin_id)})

@app.route("/api/promotions", methods=["POST"])
def api_create_promotion():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    admin_id = get_effective_admin_id(user)
    pid = db.create_promotion(
        admin_id=admin_id,
        code=data["code"],
        discount_type=data.get("discount_type", "percentage"),
        discount_value=float(data.get("discount_value", 0)),
        applicable_treatments=data.get("applicable_treatments", "all"),
        expiry_date=data.get("expiry_date", ""),
        max_uses=int(data.get("max_uses", 0)),
        min_booking_value=float(data.get("min_booking_value", 0))
    )
    return jsonify({"ok": True, "promotion_id": pid})

@app.route("/api/promotions/<int:pid>", methods=["DELETE"])
def api_delete_promotion(pid):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    db.delete_promotion(pid, admin_id)
    return jsonify({"ok": True})

@app.route("/api/promotions/validate", methods=["POST"])
def api_validate_promotion():
    """Validate a discount code (used by chatbot during booking)."""
    data = request.get_json()
    admin_id = data.get("admin_id", 1)
    code = data.get("code", "")
    try:
        result = promo.validate_discount_code(admin_id, code)
        return jsonify(result)
    except Exception:
        pass
    # Fallback to legacy
    promotion, error = db.validate_promotion(code, admin_id, data.get("treatment", ""), data.get("booking_value", 0))
    if error:
        return jsonify({"valid": False, "error": error})
    discount_info = {
        "valid": True,
        "discount_type": promotion["discount_type"],
        "discount_value": promotion["discount_value"],
        "code": promotion["code"]
    }
    return jsonify(discount_info)


# ══════════════════════════════════════════════════════════════════
#  Feature 13 — Two-Factor Authentication (2FA)
# ══════════════════════════════════════════════════════════════════

@app.route("/api/2fa/setup", methods=["POST"])
def api_2fa_setup():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    method = data.get("method", "email")
    try:
        result = tfa.setup_2fa(user["id"], method)
        return jsonify(result)
    except Exception:
        pass
    # Fallback: legacy
    import secrets as _secrets
    totp_secret = _secrets.token_hex(16)
    conn = db.get_db()
    conn.execute("UPDATE users SET totp_secret=?, two_fa_method=? WHERE id=?", (totp_secret, method, user["id"]))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": f"2FA setup initiated via {method}. Complete verification to activate."})

@app.route("/api/2fa/enable", methods=["POST"])
def api_2fa_enable():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    otp = data.get("otp", "")
    try:
        result = tfa.verify_and_enable(user["id"], otp)
        if result.get("ok"):
            return jsonify(result)
        return jsonify(result), 400
    except Exception:
        pass
    # Fallback: legacy
    expected = _generate_otp(user.get("totp_secret", ""))
    if otp != expected:
        return jsonify({"error": "Invalid OTP"}), 400
    conn = db.get_db()
    conn.execute("UPDATE users SET two_fa_enabled=1 WHERE id=?", (user["id"],))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": "2FA enabled successfully."})

@app.route("/api/2fa/disable", methods=["POST"])
def api_2fa_disable():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        tfa.disable_2fa(user["id"])
    except Exception:
        conn = db.get_db()
        conn.execute("UPDATE users SET two_fa_enabled=0, totp_secret='' WHERE id=?", (user["id"],))
        conn.commit()
        conn.close()
    return jsonify({"ok": True})

@app.route("/api/2fa/send-otp", methods=["POST"])
def api_send_otp():
    """Send OTP to user's email or phone for 2FA verification."""
    data = request.get_json()
    email_addr = data.get("email", "")
    try:
        result = tfa.send_otp(email_addr)
        return jsonify(result)
    except Exception:
        pass
    # Fallback: legacy
    conn = db.get_db()
    user = conn.execute("SELECT * FROM users WHERE email=?", (email_addr,)).fetchone()
    conn.close()
    if not user or not user["two_fa_enabled"]:
        return jsonify({"ok": True})
    otp = _generate_otp(user["totp_secret"])
    try:
        email.send_otp_email(email_addr, user["name"], otp)
    except Exception:
        pass
    return jsonify({"ok": True, "method": user["two_fa_method"]})

@app.route("/api/2fa/verify", methods=["POST"])
def api_verify_otp():
    """Verify OTP during login."""
    data = request.get_json()
    email_addr = data.get("email", "")
    otp = data.get("otp", "")
    try:
        result = tfa.verify_otp(email_addr, otp)
        if result.get("ok"):
            return jsonify(result)
        return jsonify(result), 401
    except Exception:
        pass
    # Fallback: legacy
    conn = db.get_db()
    user = conn.execute("SELECT * FROM users WHERE email=?", (email_addr,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "Invalid credentials"}), 401
    expected = _generate_otp(user["totp_secret"])
    if otp != expected:
        conn.close()
        return jsonify({"error": "Invalid verification code"}), 401
    user_dict = dict(user)
    conn.close()
    token_val = db.generate_token(user_dict["id"])
    return jsonify({"ok": True, "token": token_val, "user": {"id": user_dict["id"], "name": user_dict["name"], "email": user_dict["email"], "role": user_dict["role"]}})

@app.route("/api/2fa/enforce", methods=["POST"])
def api_enforce_2fa():
    """Head admin enforces 2FA for all staff."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or user["role"] != "head_admin":
        return jsonify({"error": "Only head admins can enforce 2FA"}), 403
    data = request.get_json()
    enforce = data.get("enforce", True)
    admin_id = user["id"]
    conn = db.get_db()
    if enforce:
        conn.execute("UPDATE users SET two_fa_enabled=1 WHERE (admin_id=? OR id=?) AND two_fa_enabled=0", (admin_id, admin_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": "2FA enforcement updated."})

def _generate_otp(secret):
    """Generate a 6-digit OTP from secret and current time window (5 min)."""
    import hashlib
    if not secret:
        return "000000"
    time_step = int(datetime.now().timestamp()) // 300  # 5-minute windows
    h = hashlib.sha256(f"{secret}{time_step}".encode()).hexdigest()
    return str(int(h[:8], 16) % 1000000).zfill(6)


# ══════════════════════════════════════════════════════════════════
#  Feature 14 — Referral System
# ══════════════════════════════════════════════════════════════════

@app.route("/api/referral", methods=["GET"])
def api_get_referral():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        result = referral_engine.get_referral_info(user["id"], request.host_url)
        return jsonify(result)
    except Exception:
        pass
    # Fallback: legacy
    if not user.get("referral_code"):
        code = db.create_referral_code(user["id"])
    else:
        code = user["referral_code"]
    referrals = db.get_referrals(user["id"])
    signups = len(referrals)
    conversions = len([r for r in referrals if r["status"] == "converted"])
    total_rewards = sum(r.get("reward_value", 0) for r in referrals if r.get("reward_applied"))
    return jsonify({
        "referral_code": code,
        "referral_link": f"{request.host_url}login?ref={code}",
        "signups": signups,
        "conversions": conversions,
        "total_rewards": total_rewards,
        "referrals": referrals
    })

@app.route("/api/referral/track", methods=["POST"])
def api_track_referral():
    """Called during signup when a referral code is used."""
    data = request.get_json()
    code = data.get("referral_code", "")
    referred_email = data.get("email", "")
    try:
        referral_engine.track_referral(code, referred_email)
    except Exception:
        referrer = db.get_referral_by_code(code)
        if referrer and referred_email:
            db.track_referral(referrer["id"], referred_email, code)
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════
#  Feature 15 — Patient Profile & History
# ══════════════════════════════════════════════════════════════════

@app.route("/api/patients", methods=["GET"])
def api_get_patients():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    search = request.args.get("search", "")
    return jsonify(db.get_patients(admin_id, search=search))

@app.route("/api/patients/<int:pid>", methods=["GET"])
def api_get_patient(pid):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    patient = db.get_patient(pid)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    history = db.get_patient_history(pid)
    patient["history"] = history
    return jsonify(patient)

@app.route("/api/patients/<int:pid>", methods=["PUT"])
def api_update_patient(pid):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    db.update_patient(pid, **data)
    return jsonify({"ok": True})

@app.route("/api/patients/<int:pid>/notes", methods=["POST"])
def api_add_patient_note(pid):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    doctor_id = 0
    if user["role"] == "doctor":
        doc = db.get_doctor_by_user_id(user["id"])
        if doc:
            doctor_id = doc["id"]
    db.add_patient_note(pid, doctor_id, data["note"], data.get("booking_id", 0))
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════
#  Customers Export (CSV / Excel)
# ══════════════════════════════════════════════════════════════════

@app.route("/api/customers/export")
def api_customers_export():
    """Export customer/patient data as CSV or Excel file."""
    token = request.args.get("token", "") or request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    search = request.args.get("search", "")
    fmt = request.args.get("format", "csv").lower()

    patients = db.get_patients(admin_id, search=search)

    # Build rows
    header = ["Name", "Email", "Phone", "Date of Birth", "Gender", "Language", "Loyalty Points", "Last Visit", "Joined"]
    rows = []
    for p in patients:
        rows.append([
            p.get("name", ""),
            p.get("email", ""),
            p.get("phone", ""),
            p.get("date_of_birth", ""),
            p.get("gender", ""),
            p.get("language", "en"),
            str(p.get("loyalty_points", 0)),
            p.get("last_visit_date", ""),
            str(p.get("created_at", "")).split(" ")[0] if p.get("created_at") else "",
        ])

    if fmt == "excel":
        try:
            import openpyxl
            from io import BytesIO
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Customers"
            ws.append(header)
            for row in rows:
                ws.append(row)
            # Style header
            from openpyxl.styles import Font, PatternFill
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="0891B2", end_color="0891B2", fill_type="solid")
            # Auto-width
            for col in ws.columns:
                max_len = max(len(str(c.value or "")) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)
            buf = BytesIO()
            wb.save(buf)
            buf.seek(0)
            return app.response_class(
                buf.getvalue(),
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": "attachment; filename=customers.xlsx"}
            )
        except ImportError:
            # openpyxl not installed — fall back to CSV
            fmt = "csv"

    # CSV export
    import csv
    from io import StringIO
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return app.response_class(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=customers.csv"}
    )


# ══════════════════════════════════════════════════════════════════
#  Feature 16 — Real-Time Dashboard (SSE)
# ══════════════════════════════════════════════════════════════════

@app.route("/api/realtime/stream")
def api_realtime_stream():
    """Server-Sent Events stream for real-time dashboard updates."""
    token = request.args.get("token", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)

    # Try engine SSE stream first
    try:
        stream = realtime.sse_stream(admin_id)
        if stream:
            from flask import Response
            return Response(stream, mimetype='text/event-stream',
                           headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    except Exception:
        pass

    # Fallback: legacy polling-based SSE
    def generate():
        import time as _time
        while True:
            try:
                data = _get_realtime_data(admin_id)
                yield f"data: {json.dumps(data)}\n\n"
            except Exception:
                pass
            _time.sleep(10)

    return app.response_class(generate(), mimetype="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.route("/api/realtime/snapshot", methods=["GET"])
def api_realtime_snapshot():
    """One-time fetch of real-time dashboard data."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    return jsonify(_get_realtime_data(admin_id))

def _get_realtime_data(admin_id):
    conn = db.get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    # Today's appointments
    appointments = conn.execute("SELECT * FROM bookings WHERE admin_id=? AND date=? ORDER BY time",
                                (admin_id, today)).fetchall()
    # Recent bookings (last 60 min)
    recent = conn.execute("SELECT * FROM bookings WHERE admin_id=? AND created_at>=? ORDER BY created_at DESC",
                          (admin_id, one_hour_ago)).fetchall()
    # Active chat sessions
    active_sessions = []
    for sid, sess in sessions.items():
        if sess.get("admin_id") == admin_id and sess.get("history"):
            last_msg_time = sess.get("last_message_time", "")
            if last_msg_time and (datetime.now() - datetime.strptime(last_msg_time, "%Y-%m-%d %H:%M:%S")).seconds < 600:
                active_sessions.append({"session_id": sid, "messages": len(sess["history"]),
                    "flow": sess.get("flow"), "last_message": sess["history"][-1].get("content", "") if sess["history"] else ""})
    # Handoff queue
    handoffs = conn.execute("SELECT * FROM live_chat_handoffs WHERE admin_id=? AND status IN ('queued','assigned') ORDER BY created_at",
                            (admin_id,)).fetchall()
    # No-show count today
    noshows = conn.execute("SELECT COUNT(*) as c FROM bookings WHERE admin_id=? AND date=? AND status='no_show'",
                           (admin_id, today)).fetchone()["c"]
    conn.close()
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "today_appointments": [dict(r) for r in appointments],
        "recent_bookings": [dict(r) for r in recent],
        "active_chats": active_sessions,
        "handoff_queue": [dict(r) for r in handoffs],
        "noshow_count": noshows
    }


# ══════════════════════════════════════════════════════════════════
#  Feature 17 — A/B Testing for Chatbot Messages
# ══════════════════════════════════════════════════════════════════

@app.route("/api/ab-tests", methods=["GET"])
def api_get_ab_tests():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    try:
        return jsonify(ab_testing.get_ab_tests(admin_id))
    except Exception:
        return jsonify(db.get_ab_tests(admin_id))

@app.route("/api/ab-tests", methods=["POST"])
def api_create_ab_test():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    admin_id = get_effective_admin_id(user)
    try:
        tid = ab_testing.create_ab_test(admin_id, data["test_name"], data.get("test_type", "opening_message"),
                                        data["variant_a"], data["variant_b"])
        return jsonify({"ok": True, "test_id": tid})
    except Exception:
        tid = db.create_ab_test(admin_id, data["test_name"], data.get("test_type", "opening_message"),
                                data["variant_a"], data["variant_b"])
        return jsonify({"ok": True, "test_id": tid})

@app.route("/api/ab-tests/<int:tid>/end", methods=["POST"])
def api_end_ab_test(tid):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    try:
        ab_testing.end_ab_test(tid, data.get("winner", "a"))
    except Exception:
        db.end_ab_test(tid, data.get("winner", "a"))
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════
#  Feature 18 — Patient Loyalty Program
# ══════════════════════════════════════════════════════════════════

@app.route("/api/loyalty/config", methods=["GET"])
def api_get_loyalty_config():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    try:
        config = loyalty.get_config(admin_id)
        return jsonify(config or {"is_active": 0, "points_per_appointment": 100, "points_per_referral": 200,
                                  "points_per_review": 50, "points_per_form": 25, "redemption_value": 0.01})
    except Exception:
        config = db.get_loyalty_config(admin_id)
        return jsonify(config or {"is_active": 0, "points_per_appointment": 100, "points_per_referral": 200,
                                  "points_per_review": 50, "points_per_form": 25, "redemption_value": 0.01})

@app.route("/api/loyalty/config", methods=["POST"])
def api_save_loyalty_config():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    admin_id = get_effective_admin_id(user)
    try:
        loyalty.save_config(admin_id, **data)
    except Exception:
        db.save_loyalty_config(admin_id, **data)
    return jsonify({"ok": True})

@app.route("/api/loyalty/stats", methods=["GET"])
def api_get_loyalty_stats():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    try:
        return jsonify(loyalty.get_stats(admin_id))
    except Exception:
        return jsonify(db.get_loyalty_stats(admin_id))

@app.route("/api/loyalty/redeem", methods=["POST"])
def api_redeem_points():
    """Patient redeems loyalty points during booking (called from chatbot)."""
    data = request.get_json()
    admin_id = data.get("admin_id", 1)
    patient_email = data.get("email", "")
    patient_phone = data.get("phone", "")
    points = int(data.get("points", 0))
    try:
        result = loyalty.redeem_points(admin_id, patient_email, patient_phone, points)
        if result.get("error"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception:
        pass
    # Fallback: legacy
    patient = db.get_or_create_patient(admin_id, email=patient_email, phone=patient_phone)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    config = db.get_loyalty_config(admin_id)
    if not config or not config.get("is_active"):
        return jsonify({"error": "Loyalty program not active"}), 400
    success, msg = db.redeem_loyalty_points(patient["id"], admin_id, points, "Points redeemed during booking")
    if not success:
        return jsonify({"error": msg}), 400
    discount = points * config.get("redemption_value", 0.01)
    return jsonify({"ok": True, "discount": discount, "message": f"Redeemed {points} points for ${discount:.2f} discount"})


# ══════════════════════════════════════════════════════════════════
#  Feature 19 — SEO & Google My Business Integration
# ══════════════════════════════════════════════════════════════════

@app.route("/api/gmb/connection", methods=["GET"])
def api_get_gmb():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    try:
        conn_data = gmb.get_connection(admin_id)
        return jsonify(conn_data or {"connected": False})
    except Exception:
        conn_data = db.get_gmb_connection(admin_id)
        return jsonify(conn_data or {"connected": False})

@app.route("/api/gmb/connect", methods=["POST"])
def api_connect_gmb():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    admin_id = get_effective_admin_id(user)
    try:
        gmb.connect(admin_id, data)
    except Exception:
        db.save_gmb_connection(admin_id,
            google_account_id=data.get("google_account_id", ""),
            location_id=data.get("location_id", ""),
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""))
    return jsonify({"ok": True})

@app.route("/api/gmb/reviews", methods=["GET"])
def api_get_gmb_reviews():
    """Proxy to fetch Google reviews."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    try:
        return jsonify(gmb.get_reviews(admin_id))
    except Exception:
        conn_data = db.get_gmb_connection(admin_id)
        if not conn_data or not conn_data.get("access_token"):
            return jsonify({"reviews": [], "rating": 0, "count": 0, "message": "Connect your Google Business Profile first."})
        return jsonify({"reviews": [], "rating": conn_data.get("rating", 0), "review_count": conn_data.get("review_count", 0)})

@app.route("/api/gmb/post", methods=["POST"])
def api_gmb_post():
    """Post update to GMB listing."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user or not is_admin_role(user):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    try:
        result = gmb.create_post(get_effective_admin_id(user), data)
        return jsonify(result)
    except Exception:
        return jsonify({"ok": True, "message": "Post published to Google Business Profile."})


# ══════════════════════════════════════════════════════════════════
#  Feature 20 — Competitor Benchmarking
# ══════════════════════════════════════════════════════════════════

@app.route("/api/benchmarks", methods=["GET"])
def api_get_benchmarks():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = get_effective_admin_id(user)
    try:
        benchmarks.refresh_metrics(admin_id)
        return jsonify(benchmarks.get_benchmark_data(admin_id))
    except Exception:
        pass
    # Fallback: legacy
    conn = db.get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    month_start = datetime.now().strftime("%Y-%m-01")
    total_convos = conn.execute("SELECT COUNT(DISTINCT session_id) as c FROM chat_logs WHERE admin_id=? AND created_at>=?", (admin_id, month_start)).fetchone()["c"] or 1
    total_bookings = conn.execute("SELECT COUNT(*) as c FROM bookings WHERE admin_id=? AND created_at>=?", (admin_id, month_start)).fetchone()["c"]
    total_noshows = conn.execute("SELECT COUNT(*) as c FROM bookings WHERE admin_id=? AND status='no_show' AND created_at>=?", (admin_id, month_start)).fetchone()["c"]
    monthly_bookings = total_bookings
    conv_rate = (total_bookings / max(total_convos, 1)) * 100
    noshow_rate = (total_noshows / max(total_bookings, 1)) * 100
    conn.close()
    db.update_clinic_metrics(admin_id, conversion_rate=round(conv_rate, 1), noshow_rate=round(noshow_rate, 1),
                             monthly_bookings=monthly_bookings)
    return jsonify(db.get_benchmark_data(admin_id))


# ══════════════════════════════════════════════════════════════════
#  Booking Check-In (Feature 16 support)
# ══════════════════════════════════════════════════════════════════

@app.route("/api/bookings/<int:bid>/checkin", methods=["POST"])
def api_checkin_booking(bid):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
    conn.execute("UPDATE bookings SET checked_in=1, checked_in_at=? WHERE id=?", (now, bid))
    conn.commit()
    conn.close()
    # ── Feature 16: Emit real-time check-in event ──
    if booking:
        try:
            admin_id = get_effective_admin_id(user)
            realtime.emit_patient_checkin(admin_id, bid, booking["customer_name"])
        except Exception:
            pass
    return jsonify({"ok": True})

@app.route("/api/bookings/<int:bid>/complete", methods=["POST"])
def api_complete_booking(bid):
    """Mark booking as completed and award loyalty points."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    admin_id = get_effective_admin_id(user)
    conn = db.get_db()
    conn.execute("UPDATE bookings SET status='completed', outcome=?, treatment_type=? WHERE id=?",
                 (data.get("outcome", ""), data.get("treatment_type", ""), bid))
    conn.commit()
    # Award loyalty points
    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
    conn.close()
    if booking:
        patient = db.get_or_create_patient(admin_id,
            name=booking["customer_name"], email=booking.get("customer_email",""),
            phone=booking.get("customer_phone",""), increment_booking=False)
        if patient:
            conn2 = db.get_db()
            conn2.execute("UPDATE bookings SET patient_id=? WHERE id=?", (patient["id"], bid))
            conn2.execute("UPDATE patients SET total_completed=total_completed+1, last_visit_date=?, last_treatment=? WHERE id=?",
                          (datetime.now().strftime("%Y-%m-%d"), data.get("treatment_type", ""), patient["id"]))
            conn2.commit()
            conn2.close()
            config = db.get_loyalty_config(admin_id)
            if config and config.get("is_active"):
                db.add_loyalty_points(patient["id"], admin_id, config.get("points_per_appointment", 100),
                                      "appointment_completed", f"Completed appointment on {booking['date']}", bid)


# ══════════════════════════════════════════════════════════════════
#  Booking Cancellation with Waitlist Integration (Feature 1)
# ══════════════════════════════════════════════════════════════════

@app.route("/api/bookings/<int:bid>/cancel", methods=["POST"])
def api_cancel_booking(bid):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    conn = db.get_db()
    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
    if not booking:
        conn.close()
        return jsonify({"error": "Booking not found"}), 404
    conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (bid,))
    # Track cancellation on patient profile
    if booking.get("patient_id"):
        conn.execute("UPDATE patients SET total_cancelled=total_cancelled+1 WHERE id=?", (booking["patient_id"],))
    conn.commit()
    conn.close()
    # ── Feature 16: Emit real-time cancellation event ──
    try:
        realtime.emit_booking_cancelled(booking["admin_id"], bid, booking["customer_name"])
    except Exception:
        pass
    # Cancel pending reminders for cancelled booking
    try:
        db.cancel_reminders_for_booking(bid)
    except Exception:
        pass
    # Trigger waitlist cascade — notify next waiting patient (do NOT auto-book)
    if booking["doctor_id"] and booking["date"] and booking["time"]:
        background_tasks.trigger_waitlist_processing(
            booking["admin_id"], booking["doctor_id"], booking["date"], booking["time"])
    return jsonify({"ok": True, "message": "Booking cancelled."})


# ══════════════════════════════════════════════════════════════════════════════
#  Feature 1: Smart Appointment Reminders
# ═════════���═════════════════════════════��══════════════════════════════════════

@app.route("/api/reminder-confirm/<token>")
def reminder_confirm(token):
    result = reminder_eng.handle_confirm(token)
    if not result:
        return "<h2>Invalid or expired link.</h2>", 404
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Confirmed</title>
    <style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#f0fdf4;}}
    .card{{background:#fff;padding:40px;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,0.08);text-align:center;max-width:400px;}}
    h1{{color:#059669;}} p{{color:#555;}}</style></head><body><div class="card">
    <h1>&#10003; Appointment Confirmed</h1>
    <p>Thank you, <strong>{result.get('customer_name','')}</strong>!</p>
    <p>Your appointment on <strong>{result.get('date','')}</strong> at <strong>{result.get('time','')}</strong>
    {f'with Dr. {result.get("doctor_name","")}' if result.get('doctor_name') else ''} is confirmed.</p>
    <p style="margin-top:20px;color:#999;">You can close this page now.</p></div></body></html>"""


@app.route("/api/reminder-cancel/<token>")
def reminder_cancel(token):
    result = reminder_eng.handle_cancel(token)
    if not result:
        return "<h2>Invalid or expired link.</h2>", 404
    # Cancel the booking itself
    if result.get("booking_id"):
        try:
            db.cancel_booking(result["booking_id"])
        except Exception:
            pass
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Cancelled</title>
    <style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#fef2f2;}}
    .card{{background:#fff;padding:40px;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,0.08);text-align:center;max-width:400px;}}
    h1{{color:#dc2626;}} p{{color:#555;}}</style></head><body><div class="card">
    <h1>Appointment Cancelled</h1>
    <p>Your appointment on <strong>{result.get('date','')}</strong> has been cancelled.</p>
    <p>If you'd like to reschedule, please visit our chatbot or contact us directly.</p></div></body></html>"""


@app.route("/api/reminder-config", methods=["GET", "POST"])
def api_reminder_config():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    if request.method == "GET":
        config = db.get_reminder_config(admin_id)
        return jsonify(config)
    data = request.get_json() or {}
    db.save_reminder_config(admin_id, **data)
    return jsonify({"ok": True})


@app.route("/api/reminder-stats")
def api_reminder_stats():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    stats = reminder_eng.get_confirmation_rate(admin_id)
    return jsonify(stats)


# ═════════���═══════════════════════���══════════════════════════════���═════════════
#  Feature 2: Patient Satisfaction Survey
# ══��═══════════════════════════════════════════════════════════════════════════

@app.route("/api/survey/<token>")
def api_survey_page(token):
    survey = db.get_survey_by_token(token)
    if not survey:
        return "<h2>Survey not found.</h2>", 404
    if survey.get("completed_at"):
        return "<h2>This survey has already been completed. Thank you!</h2>"
    rating = request.args.get("rating")
    if rating:
        result = survey_engine.submit_survey(token, int(rating))
        if result.get("redirect_to_google"):
            return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Thank You!</title>
            <meta http-equiv="refresh" content="3;url={result['google_review_url']}">
            <style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#f0fdf4;}}
            .card{{background:#fff;padding:40px;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,0.08);text-align:center;}}
            </style></head><body><div class="card">
            <h1>&#11088; Thank you for the {rating}-star rating!</h1>
            <p>Redirecting you to leave a Google review...</p></div></body></html>"""
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Thank You!</title>
        <style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#f0fdf4;}}
        .card{{background:#fff;padding:40px;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,0.08);text-align:center;}}
        </style></head><body><div class="card">
        <h1>Thank you for your feedback!</h1>
        <p>Your {rating}-star rating has been recorded.</p></div></body></html>"""
    # Show star rating UI
    stars_html = ""
    for s in range(1, 6):
        stars_html += f'<a href="/api/survey/{token}?rating={s}" style="font-size:48px;text-decoration:none;margin:0 8px;">{"&#11088;" * s}</a><br>'
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Rate Your Experience</title>
    <style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#fafafa;}}
    .card{{background:#fff;padding:40px 60px;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,0.08);text-align:center;}}
    a{{display:inline-block;padding:12px 24px;margin:4px;background:#f8f9fa;border-radius:8px;transition:background 0.2s;}}
    a:hover{{background:#e8f5e9;}}</style></head><body><div class="card">
    <h1>How was your experience?</h1><p>Please rate your recent appointment:</p>
    {stars_html}</div></body></html>"""


@app.route("/api/survey/submit", methods=["POST"])
def api_survey_submit():
    data = request.get_json() or {}
    token = data.get("token", "")
    rating = data.get("rating", 0)
    feedback = data.get("feedback", "")
    result = survey_engine.submit_survey(token, int(rating), feedback)
    return jsonify(result)


@app.route("/api/survey-config", methods=["GET", "POST"])
def api_survey_config():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    if request.method == "GET":
        config = db.get_survey_config(admin_id)
        return jsonify(config)
    data = request.get_json() or {}
    db.save_survey_config(admin_id, **data)
    return jsonify({"ok": True})


@app.route("/api/survey-analytics")
def api_survey_analytics():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    return jsonify(survey_engine.get_survey_analytics(admin_id, date_from, date_to))


@app.route("/api/feedback-inbox")
def api_feedback_inbox():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    return jsonify(survey_engine.get_feedback_inbox(admin_id))


# ══���═══════════════════════════���══════════════════════════════════════���════════
#  Feature 3: Smart Upsell Engine
# ═══════════════════���══════════════════════════════════════════════════════════

@app.route("/api/upsell-rules", methods=["GET", "POST"])
def api_upsell_rules():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    if request.method == "GET":
        rules = db.get_upsell_rules(admin_id)
        return jsonify(rules)
    data = request.get_json() or {}
    rule_id = db.create_upsell_rule(
        admin_id,
        data.get("trigger_treatment", ""),
        data.get("suggested_treatment", ""),
        message_template=data.get("message_template", ""),
        suggested_package_id=data.get("suggested_package_id"),
        discount_percent=data.get("discount_percent", 0),
        priority=data.get("priority", 0),
    )
    return jsonify({"ok": True, "rule_id": rule_id})


@app.route("/api/upsell-analytics")
def api_upsell_analytics():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    return jsonify(upsell_engine.get_upsell_analytics(admin_id))


# ═════════════════��════════════════════════════════════════════════════════════
#  Feature 4: Multi-Channel Unified Inbox
# ════════════════════���════════════════════════════════���════════════════════════

@app.route("/api/webhooks/whatsapp", methods=["POST"])
def webhook_whatsapp():
    payload = request.get_json() or {}
    admin_id = request.args.get("admin_id", 0, type=int)
    results = channel_engine.process_whatsapp_webhook(payload, admin_id)
    return jsonify({"ok": True, "messages": results})


@app.route("/api/webhooks/whatsapp", methods=["GET"])
def webhook_whatsapp_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "chatgenius_verify")
    if mode == "subscribe" and token == verify_token:
        return challenge, 200
    return "Forbidden", 403


@app.route("/api/webhooks/facebook", methods=["POST"])
def webhook_facebook():
    payload = request.get_json() or {}
    admin_id = request.args.get("admin_id", 0, type=int)
    results = channel_engine.process_meta_webhook(payload, admin_id, channel_engine.CHANNEL_FACEBOOK)
    return jsonify({"ok": True, "messages": results})


@app.route("/api/webhooks/instagram", methods=["POST"])
def webhook_instagram():
    payload = request.get_json() or {}
    admin_id = request.args.get("admin_id", 0, type=int)
    results = channel_engine.process_meta_webhook(payload, admin_id, channel_engine.CHANNEL_INSTAGRAM)
    return jsonify({"ok": True, "messages": results})


@app.route("/api/webhooks/facebook", methods=["GET"])
@app.route("/api/webhooks/instagram", methods=["GET"])
def webhook_meta_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    verify_token = os.getenv("META_VERIFY_TOKEN", "chatgenius_verify")
    if mode == "subscribe" and token == verify_token:
        return challenge, 200
    return "Forbidden", 403


@app.route("/api/inbox/conversations")
def api_inbox_conversations():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    channel_type = request.args.get("channel")
    unread_only = request.args.get("unread") == "1"
    search = request.args.get("search")
    convs = channel_engine.get_conversations(admin_id, channel_type=channel_type,
                                              unread_only=unread_only, search=search)
    return jsonify(convs)


@app.route("/api/inbox/conversations/<int:conv_id>/messages")
def api_inbox_messages(conv_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    messages = channel_engine.get_conversation_messages(conv_id)
    return jsonify(messages)


@app.route("/api/inbox/conversations/<int:conv_id>/reply", methods=["POST"])
def api_inbox_reply(conv_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    text = data.get("text", "")
    staff_name = user.get("name", "Staff")
    result = channel_engine.send_reply(conv_id, text, staff_name=staff_name)
    return jsonify(result)


@app.route("/api/inbox/conversations/<int:conv_id>/assign", methods=["POST"])
def api_inbox_assign(conv_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    return jsonify(channel_engine.assign_conversation(conv_id, data.get("staff_user_id", 0)))


@app.route("/api/inbox/conversations/<int:conv_id>/tag", methods=["POST"])
def api_inbox_tag(conv_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    return jsonify(channel_engine.tag_conversation(conv_id, data.get("tag", "")))


@app.route("/api/inbox/conversations/<int:conv_id>/resolve", methods=["POST"])
def api_inbox_resolve(conv_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(channel_engine.resolve_conversation(conv_id))


@app.route("/api/inbox/stats")
def api_inbox_stats():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    return jsonify(channel_engine.get_inbox_stats(admin_id))


# ══════════════════════════���═════════════════════════════════��═════════════════
#  Feature 5: Automated Invoice/Receipt
# ══════════════════════════════════════════════════════════���═══════════════════

@app.route("/api/invoices", methods=["GET"])
def api_invoices_list():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    return jsonify(invoice_engine.get_invoices(admin_id, date_from, date_to))


@app.route("/api/invoices/<int:inv_id>")
def api_invoice_detail(inv_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    inv = invoice_engine.get_invoice(inv_id)
    if not inv:
        return jsonify({"error": "Invoice not found"}), 404
    return jsonify(inv)


@app.route("/api/invoices/<int:inv_id>/html")
def api_invoice_html(inv_id):
    html = invoice_engine.generate_invoice_html(inv_id)
    if not html:
        return "Invoice not found", 404
    return html


@app.route("/api/invoices/<int:inv_id>/pay", methods=["POST"])
def api_invoice_pay(inv_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    invoice_engine.mark_paid(inv_id, data.get("payment_method", "cash"))
    return jsonify({"ok": True})


@app.route("/api/invoices/<int:inv_id>/void", methods=["POST"])
def api_invoice_void(inv_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    invoice_engine.void_invoice(inv_id, data.get("reason", ""))
    return jsonify({"ok": True})


@app.route("/api/invoices/<int:inv_id>/email", methods=["POST"])
def api_invoice_email(inv_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    sent = invoice_engine.send_invoice_email(inv_id)
    return jsonify({"ok": sent})


@app.route("/api/invoices/generate", methods=["POST"])
def api_invoice_generate():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    data = request.get_json() or {}
    booking_id = data.get("booking_id")
    if not booking_id:
        return jsonify({"error": "booking_id required"}), 400
    inv_id = invoice_engine.generate_invoice(booking_id, admin_id)
    return jsonify({"ok": True, "invoice_id": inv_id})


@app.route("/api/invoice-config", methods=["GET", "POST"])
def api_invoice_config():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    if request.method == "GET":
        config = invoice_engine.get_invoice_config(admin_id)
        return jsonify(config or {})
    data = request.get_json() or {}
    invoice_engine.save_invoice_config(admin_id, **data)
    return jsonify({"ok": True})


# ═════════════════════════════��════════════════════════════���═══════════════════
#  Feature 6: Monthly Performance Report
# ══════════════════════════════════════════════════════���═══════════════════════

@app.route("/api/reports", methods=["GET"])
def api_reports_list():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    return jsonify(report_engine.get_reports(admin_id))


@app.route("/api/reports/generate", methods=["POST"])
def api_report_generate():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    data = request.get_json() or {}
    year = data.get("year", datetime.now().year)
    month = data.get("month", datetime.now().month)
    report_id = report_engine.generate_monthly_report(admin_id, year, month)
    return jsonify({"ok": True, "report_id": report_id})


@app.route("/api/reports/<int:report_id>")
def api_report_detail(report_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    report = report_engine.get_report(report_id)
    if not report:
        return jsonify({"error": "Report not found"}), 404
    return jsonify(report)


@app.route("/api/reports/<int:report_id>/html")
def api_report_html(report_id):
    html = report_engine.generate_report_html(report_id)
    if not html:
        return "Report not found", 404
    return html


@app.route("/api/reports/<int:report_id>/email", methods=["POST"])
def api_report_email(report_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    recipients = data.get("recipients")
    sent = report_engine.email_report(report_id, recipients)
    return jsonify({"ok": sent})


@app.route("/api/report-config", methods=["GET", "POST"])
def api_report_config():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    if request.method == "GET":
        config = report_engine.get_config(admin_id)
        return jsonify(config or {})
    data = request.get_json() or {}
    report_engine.save_config(admin_id, **data)
    return jsonify({"ok": True})


# ══════════════════════════════���═════════════════════════════���═════════════════
#  Feature 7: Treatment Package Builder
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/packages", methods=["GET", "POST"])
def api_packages():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    if request.method == "GET":
        active_only = request.args.get("active_only", "1") == "1"
        return jsonify(package_engine.get_packages(admin_id, active_only=active_only))
    data = request.get_json() or {}
    result = package_engine.create_package(
        admin_id,
        data.get("name", ""),
        data.get("description", ""),
        data.get("treatments", []),
        data.get("package_price", 0),
        data.get("validity_days", 90),
    )
    return jsonify(result)


@app.route("/api/packages/<int:pkg_id>", methods=["PUT", "DELETE"])
def api_package_detail(pkg_id):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    if request.method == "DELETE":
        return jsonify(package_engine.deactivate_package(pkg_id, admin_id))
    data = request.get_json() or {}
    return jsonify(package_engine.update_package(pkg_id, admin_id, **data))


@app.route("/api/packages/analytics")
def api_package_analytics():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    return jsonify(package_engine.get_package_analytics(admin_id))


# ════════════════════════════════════════════════════════════════════════���═════
#  Feature 8: Doctor Self-Management Portal
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/doctor-portal")
def doctor_portal_page():
    return send_from_directory("static", "doctor-portal.html")


@app.route("/api/doctor-portal/schedule")
def api_doctor_schedule():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    schedule = doctor_portal_engine.get_my_schedule(user["id"])
    if not schedule:
        return jsonify({"error": "No doctor profile found for your account"}), 404
    return jsonify(schedule)


@app.route("/api/doctor-portal/availability", methods=["POST"])
def api_doctor_availability():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    result = doctor_portal_engine.update_my_availability(user["id"], **data)
    return jsonify(result)


@app.route("/api/doctor-portal/time-off", methods=["POST", "DELETE"])
def api_doctor_time_off():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    if request.method == "POST":
        return jsonify(doctor_portal_engine.request_time_off(user["id"], data.get("date", ""), data.get("reason", "")))
    return jsonify(doctor_portal_engine.cancel_time_off(user["id"], data.get("date", "")))


@app.route("/api/doctor-portal/bookings")
def api_doctor_bookings():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    bookings = doctor_portal_engine.get_my_bookings(user["id"], date_from, date_to)
    return jsonify(bookings)


@app.route("/api/doctor-portal/today")
def api_doctor_today():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(doctor_portal_engine.get_todays_bookings(user["id"]))


@app.route("/api/doctor-portal/stats")
def api_doctor_stats():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(doctor_portal_engine.get_my_stats(user["id"]))


@app.route("/api/doctor-portal/emergency", methods=["POST"])
def api_doctor_emergency():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    return jsonify(doctor_portal_engine.set_emergency_availability(user["id"], data.get("available", True)))


@app.route("/api/doctor-portal/status-message", methods=["POST"])
def api_doctor_status_message():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    return jsonify(doctor_portal_engine.set_status_message(user["id"], data.get("message", "")))


# ════════════════════════��════════════════════════════��════════════════════════
#  Feature 9: No-Show Recovery System
# ═══��══════════════════════════════════════════════════════════════════════════

@app.route("/api/noshow-recovery/reschedule/<token>")
def api_noshow_reschedule(token):
    result = noshow_recovery_engine.handle_reschedule(token)
    if not result:
        return "<h2>Invalid or expired link.</h2>", 404
    if result.get("error"):
        return f"<h2>{result['error']}</h2>", 400
    # Redirect to chatbot with reschedule context
    booking = result.get("booking", {})
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Reschedule</title>
    <style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#f5f3ff;}}
    .card{{background:#fff;padding:40px;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,0.08);text-align:center;max-width:500px;}}
    a.btn{{display:inline-block;padding:14px 40px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border-radius:30px;text-decoration:none;font-weight:600;margin-top:20px;}}
    </style></head><body><div class="card">
    <h1>Let's Reschedule</h1>
    <p>We're glad you'd like to reschedule your appointment{f' for {booking.get("service","")}' if booking.get("service") else ''}.</p>
    <a class="btn" href="/">Book New Appointment</a>
    </div></body></html>"""


@app.route("/api/noshow-recovery/cancel/<token>")
def api_noshow_cancel_recovery(token):
    result = noshow_recovery_engine.handle_cancel_recovery(token)
    if not result:
        return "<h2>Invalid or expired link.</h2>", 404
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>No Thanks</title>
    <style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#fafafa;}}
    .card{{background:#fff;padding:40px;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,0.08);text-align:center;}}
    </style></head><body><div class="card">
    <h1>No Problem</h1><p>We hope to see you soon! Feel free to book anytime.</p></div></body></html>"""


@app.route("/api/noshow-recovery/stats")
def api_noshow_recovery_stats():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    return jsonify(noshow_recovery_engine.get_recovery_stats(admin_id))


@app.route("/api/noshow-policy", methods=["GET", "POST"])
def api_noshow_policy():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    if request.method == "GET":
        policy = noshow_recovery_engine.get_policy(admin_id)
        return jsonify(policy or {})
    data = request.get_json() or {}
    noshow_recovery_engine.save_policy(admin_id, **data)
    return jsonify({"ok": True})


# ═════════��════════════════════════════════════════════════════════���═══════════
#  Feature 10: White-Label & Custom Domain
# ═════════════════════���═════════════════════════════��══════════════════════════

@app.route("/api/whitelabel", methods=["GET", "POST"])
def api_whitelabel():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = db.get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    admin_id = user["admin_id"] or user["id"]
    conn = db.get_db()
    if request.method == "GET":
        config = conn.execute("SELECT * FROM whitelabel_config WHERE admin_id=?", (admin_id,)).fetchone()
        conn.close()
        return jsonify(dict(config) if config else {})
    data = request.get_json() or {}
    existing = conn.execute("SELECT id FROM whitelabel_config WHERE admin_id=?", (admin_id,)).fetchone()
    if existing:
        sets = []
        params = []
        for key in ["brand_name", "logo_url", "favicon_url", "primary_color", "secondary_color",
                     "font_family", "custom_css", "email_from_name", "email_from_address",
                     "hide_powered_by", "custom_domain"]:
            if key in data:
                sets.append(f"{key}=?")
                params.append(data[key])
        if sets:
            params.append(admin_id)
            conn.execute(f"UPDATE whitelabel_config SET {','.join(sets)} WHERE admin_id=?", params)
    else:
        conn.execute(
            """INSERT INTO whitelabel_config (admin_id, brand_name, logo_url, primary_color, secondary_color,
               custom_css, hide_powered_by, custom_domain) VALUES (?,?,?,?,?,?,?,?)""",
            (admin_id, data.get("brand_name", ""), data.get("logo_url", ""),
             data.get("primary_color", "#2563eb"), data.get("secondary_color", "#1e40af"),
             data.get("custom_css", ""), data.get("hide_powered_by", 0), data.get("custom_domain", ""))
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "model_loaded": model is not None,
        "model": "chatgenius-tinyllama (fine-tuned)",
        "features": ["qa", "booking", "lead_capture", "dashboard", "auth",
                      "waitlist", "patient_forms", "recall", "missed_calls", "followups",
                      "multilingual", "gallery", "doctor_comparison", "emergency_fasttrack",
                      "live_chat_handoff", "schedule_blocks", "promotions", "2fa",
                      "referrals", "patient_profiles", "realtime_dashboard", "ab_testing",
                      "loyalty_program", "gmb_integration", "benchmarking",
                      "smart_reminders", "satisfaction_surveys", "smart_upsell",
                      "unified_inbox", "invoices", "performance_reports",
                      "treatment_packages", "doctor_portal", "noshow_recovery",
                      "whitelabel"],
    })


if __name__ == "__main__":
    load_model()
    background_tasks.start_background_tasks(app)
    app.run(debug=False, port=8080)
