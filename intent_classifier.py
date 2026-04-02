"""
Smart intent classifier using TF-IDF-like scoring.
Understands the DIFFERENCE between questions and action requests.
No hardcoded if/else — uses pattern scoring to determine intent.
"""

import re
import math
from collections import Counter

# ── Intent definitions with weighted training examples ──
# Each intent has example phrases that represent it.
# The classifier scores incoming messages against ALL intents
# and picks the highest-scoring one.

_INTENT_EXAMPLES = {
    "booking": {
        "weight": 1.0,
        "examples": [
            # Strong booking signals — first-person action statements
            "I want to book an appointment",
            "I'd like to schedule a visit",
            "Can I book an appointment",
            "I need to make an appointment",
            "Book me an appointment",
            "Schedule an appointment for me",
            "I want to reserve a slot",
            "I'd like to come in",
            "Set up a time for me",
            "I want to see a doctor",
            "I need to see the dentist",
            "Book appointment",
            "Make an appointment",
            "Schedule a visit",
            "Reserve a time slot",
            "I want to come in for a checkup",
            "Can I get an appointment",
            "I need an appointment with the dentist",
            "Let's book",
            "I want to book",
            "Help me schedule",
            "I'd like to make a booking",
            "Book now",
            "I want to schedule for tomorrow",
            "Can I book with doctor",
            "Set up an appointment please",
            "I want to reserve a time",
        ],
    },
    "availability_question": {
        "weight": 1.0,
        "examples": [
            # Questions ABOUT availability — not booking, just asking
            "What times are available",
            "What are the available slots",
            "What is the available bookings",
            "When is the doctor available",
            "What days is the doctor free",
            "What are the open times",
            "When can I see doctor",
            "What slots are open",
            "Is the doctor available tomorrow",
            "What is the schedule for the doctor",
            "When does the doctor have openings",
            "Show me the available times",
            "What bookings are available",
            "Are there any free slots",
            "What times does the dentist have",
            "Is there availability this week",
            "When is the next available appointment",
            "What hours does doctor work",
            "Does the doctor have availability",
            "I want to know the available hours for the doctor",
            "Just want to know the available hours",
            "What are the available hours for today",
            "I just want to know when doctor is free",
            "Tell me the available times for doctor",
            "What hours is the doctor available today",
            "I want to know the schedule for doctor",
            "For doctor only what times are available",
            "When is doctor free today",
            "Available hours for doctor today",
        ],
    },
    "question": {
        "weight": 1.0,
        "examples": [
            # General dental / office questions
            "What services do you offer",
            "How much does a cleaning cost",
            "What are your hours",
            "Where are you located",
            "Do you accept insurance",
            "What is a root canal",
            "How long does whitening take",
            "Can I visit the dentist while pregnant",
            "What should I do for a toothache",
            "How often should I brush",
            "Does teeth whitening hurt",
            "What are veneers",
            "How much do braces cost",
            "Is it safe to get dental x-rays",
            "What do I do if my tooth falls out",
            "Tell me about your services",
            "Explain the procedure for implants",
            "How does invisalign work",
            "What causes bad breath",
            "Who are your doctors",
            "What doctors do you have",
            "What specialists are available",
            "List your doctors",
            # Symptom questions — asking what doctor/type they need
            "If my teeth are hurting what type of doctor do I need",
            "What doctor should I see for a toothache",
            "What kind of dentist do I need for braces",
            "Which specialist should I go to for gum pain",
            "My tooth hurts what type of doctor do I need",
            "What doctor do I need for a broken tooth",
            "I have tooth pain what should I do",
            "What type of dentist handles root canals",
            "Who should I see for bleeding gums",
            "What kind of doctor is best for wisdom teeth",
            "My jaw hurts which doctor should I visit",
            "What specialist do I need for teeth grinding",
            "I need a doctor for tooth pain",
            "What type of doctor should I go to",
            "Which doctor should I see for swollen gums",
            "What doctor do I need if my teeth hurt",
        ],
    },
    "lead_capture": {
        "weight": 1.0,
        "examples": [
            "Call me back",
            "Here is my phone number",
            "Contact me later",
            "I want to leave my number",
            "Can you reach me at",
            "Get back to me",
            "Leave my contact info",
            "I'm not ready to book yet but take my number",
            "Send me more information",
            "Follow up with me",
            "My number is",
            "My phone is",
        ],
    },
    "cancel": {
        "weight": 1.2,  # Slightly higher weight — cancel should win when present
        "examples": [
            "Cancel",
            "Never mind",
            "Stop",
            "Go back",
            "Start over",
            "Quit",
            "Exit",
            "I changed my mind",
            "Forget it",
            "I don't want to book",
            "I don't want to book an appointment",
            "No I don't want to book",
            "No thanks I don't need an appointment",
            "I don't want an appointment",
            "Not interested in booking",
            "No booking",
            "Stop booking",
        ],
    },
    "greeting": {
        "weight": 1.0,
        "examples": [
            "Hi",
            "Hello",
            "Hey",
            "Good morning",
            "Good afternoon",
            "Good evening",
            "Hi there",
            "Hey there",
            "Greetings",
        ],
    },
    "farewell": {
        "weight": 1.0,
        "examples": [
            "Bye",
            "Goodbye",
            "Thanks",
            "Thank you",
            "See you later",
            "Have a good day",
            "That's all",
            "Bye bye",
        ],
    },
}

# Stop words to skip during matching
_STOP_WORDS = {
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it", "they",
    "the", "a", "an", "is", "are", "was", "were", "am", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "shall", "can", "may", "might", "must", "to", "of", "in", "for", "on", "with",
    "at", "by", "from", "as", "into", "about", "and", "but", "or", "not", "no",
    "so", "if", "then", "that", "this", "there", "here", "up", "down", "out",
    "off", "over", "under", "again", "very", "just", "also", "only",
    "really", "much", "going", "get", "got", "go", "please",
}

# ── Build index at import time ──
_idf = {}
_intent_vectors = {}  # intent_name -> list of doc vectors
_ready = False


def _tokenize(text):
    """Tokenize text into meaningful words."""
    text = re.sub(r'[^\w\s]', ' ', text.lower())
    return [w for w in text.split() if w not in _STOP_WORDS and len(w) > 1]


def _build_index():
    """Build TF-IDF vectors for all intent examples."""
    global _idf, _intent_vectors, _ready

    # Collect all documents
    all_docs = []
    doc_to_intent = []
    for intent_name, intent_data in _INTENT_EXAMPLES.items():
        for example in intent_data["examples"]:
            tokens = _tokenize(example)
            all_docs.append(tokens)
            doc_to_intent.append(intent_name)

    # Calculate IDF
    n_docs = len(all_docs)
    df = Counter()
    for doc in all_docs:
        for word in set(doc):
            df[word] += 1

    _idf = {}
    for word, freq in df.items():
        _idf[word] = math.log((n_docs + 1) / (freq + 1)) + 1

    # Build TF-IDF vectors grouped by intent
    _intent_vectors = {}
    for i, doc in enumerate(all_docs):
        intent_name = doc_to_intent[i]
        if intent_name not in _intent_vectors:
            _intent_vectors[intent_name] = []

        tf = Counter(doc)
        max_tf = max(tf.values()) if tf else 1
        vector = {}
        for word, count in tf.items():
            vector[word] = (0.5 + 0.5 * count / max_tf) * _idf.get(word, 1)
        _intent_vectors[intent_name].append(vector)

    _ready = True


def _cosine_similarity(vec1, vec2):
    """Compute cosine similarity between two sparse vectors."""
    common = set(vec1.keys()) & set(vec2.keys())
    if not common:
        return 0.0
    dot = sum(vec1[w] * vec2[w] for w in common)
    mag1 = math.sqrt(sum(v * v for v in vec1.values()))
    mag2 = math.sqrt(sum(v * v for v in vec2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


def _structural_signals(text):
    """
    Analyze sentence structure to detect question vs action.
    Returns a dict of signal scores that boost/penalize intents.
    """
    lower = text.lower().strip()
    signals = {}

    # Question structure detection
    is_question_form = bool(
        "?" in text or
        re.match(r'^(what|how|why|when|where|who|which|is|are|do|does|can|could|will|would|tell|explain|show)\b', lower)
    )

    # Action/desire detection — first person + action verb
    is_action_request = bool(
        re.search(r'\b(i want|i\'d like|i need|let\'s|lets|help me|book me|schedule me|can i get)\b', lower)
    )

    # "What is" / "What are" pattern — strongly informational
    is_what_is = bool(re.match(r'^(what|how|when|where|who|which)\s+(is|are|does|do|was|were|can|could|will|would)\b', lower))

    if is_question_form and not is_action_request:
        # Question without action intent → boost question intents, penalize booking
        signals["booking"] = -0.3
        signals["availability_question"] = 0.2
        signals["question"] = 0.15

    if is_what_is:
        signals["booking"] = signals.get("booking", 0) - 0.2
        signals["availability_question"] = signals.get("availability_question", 0) + 0.1
        signals["question"] = signals.get("question", 0) + 0.1

    if is_action_request:
        signals["booking"] = signals.get("booking", 0) + 0.3

    # Very short messages (1-2 words) — likely greetings, farewells, or commands
    word_count = len(lower.split())
    if word_count <= 2:
        signals["greeting"] = signals.get("greeting", 0) + 0.1
        signals["farewell"] = signals.get("farewell", 0) + 0.1
        signals["cancel"] = signals.get("cancel", 0) + 0.1

    return signals


def classify(text, min_confidence=0.1):
    """
    Classify user message into an intent.

    Returns:
        tuple: (intent_name, confidence_score)
        intent_name is one of: "booking", "availability_question", "question",
                               "lead_capture", "cancel", "greeting", "farewell"
    """
    if not _ready:
        _build_index()

    tokens = _tokenize(text)
    if not tokens:
        return "question", 0.0

    # Build query vector
    tf = Counter(tokens)
    max_tf = max(tf.values()) if tf else 1
    query_vec = {}
    for word, count in tf.items():
        query_vec[word] = (0.5 + 0.5 * count / max_tf) * _idf.get(word, 1)

    # Score each intent: best matching example * intent weight
    intent_scores = {}
    for intent_name, examples in _intent_vectors.items():
        weight = _INTENT_EXAMPLES[intent_name]["weight"]
        # Take the best matching example for this intent
        best_sim = 0
        for doc_vec in examples:
            sim = _cosine_similarity(query_vec, doc_vec)
            if sim > best_sim:
                best_sim = sim
        intent_scores[intent_name] = best_sim * weight

    # Apply structural signals (question form, action form, etc.)
    signals = _structural_signals(text)
    for intent_name, boost in signals.items():
        if intent_name in intent_scores:
            intent_scores[intent_name] += boost

    # Pick the winner
    best_intent = max(intent_scores, key=intent_scores.get)
    best_score = intent_scores[best_intent]

    # If confidence is too low, default to "question"
    if best_score < min_confidence:
        return "question", best_score

    return best_intent, best_score


# Build index on import
_build_index()
