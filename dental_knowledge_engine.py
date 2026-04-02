"""
Smart dental knowledge matching engine.
Uses TF-IDF-like scoring with keyword boosting to match patient questions
to the best answer from the dental knowledge base.
Works entirely offline — no API calls needed.
"""

import json
import os
import re
import math
from collections import Counter

_knowledge = []
_idf = {}
_doc_vectors = []
_ready = False

# Common stop words to ignore in matching
_STOP_WORDS = {
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it", "they",
    "the", "a", "an", "is", "are", "was", "were", "am", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "shall", "can", "may", "might", "must", "to", "of", "in", "for", "on", "with",
    "at", "by", "from", "as", "into", "about", "between", "through", "during",
    "before", "after", "and", "but", "or", "not", "no", "so", "if", "then",
    "that", "this", "what", "which", "who", "whom", "when", "where", "why", "how",
    "all", "each", "every", "both", "few", "more", "most", "other", "some", "such",
    "than", "too", "very", "just", "also", "only", "own", "same", "there", "here",
    "up", "down", "out", "off", "over", "under", "again", "further",
    "really", "much", "going", "get", "got", "go", "want", "need", "tell",
    "please", "thanks", "thank", "hi", "hello", "hey",
}

# Synonym expansion — maps common patient language to dental terms
_SYNONYMS = {
    "hurts": ["pain", "ache", "sore", "painful", "throbbing"],
    "hurt": ["pain", "ache", "sore", "painful"],
    "ache": ["pain", "hurt", "sore"],
    "scared": ["afraid", "fear", "anxiety", "nervous", "phobia"],
    "afraid": ["scared", "fear", "anxiety", "nervous"],
    "fix": ["treat", "repair", "restore", "cure"],
    "remove": ["extract", "pull", "take out"],
    "pull": ["extract", "remove", "take out"],
    "replace": ["implant", "bridge", "denture", "prosthetic"],
    "straighten": ["braces", "invisalign", "orthodontic", "alignment"],
    "whiten": ["whitening", "bleach", "brighten", "stain"],
    "bleed": ["bleeding", "blood"],
    "bleeding": ["bleed", "blood"],
    "swollen": ["swelling", "puffy", "inflamed"],
    "wobbly": ["loose", "wiggly", "moving"],
    "kid": ["child", "children", "pediatric", "baby"],
    "child": ["kid", "children", "pediatric", "baby"],
    "cheap": ["cost", "affordable", "price", "budget", "save money"],
    "expensive": ["cost", "price", "afford"],
    "fake": ["denture", "false teeth", "prosthetic"],
    "cap": ["crown"],
    "nerve": ["root canal", "endodontic"],
    "grill": ["veneer", "cosmetic"],
    "crooked": ["misaligned", "straighten", "braces", "orthodontic"],
    "gap": ["space", "diastema", "missing"],
    "hole": ["cavity", "decay"],
    "rotten": ["decay", "cavity", "infection"],
    "smell": ["bad breath", "halitosis", "odor"],
    "stink": ["bad breath", "halitosis", "odor"],
    "pregnant": ["pregnancy", "prenatal", "expecting"],
    "grind": ["grinding", "bruxism", "clenching"],
    "click": ["clicking", "tmj", "jaw"],
    "pop": ["popping", "tmj", "jaw"],
    "numb": ["anesthesia", "sedation", "numbness"],
    "sleep": ["sedation", "anesthesia", "sleep apnea"],
    "snore": ["snoring", "sleep apnea"],
}


def _tokenize(text):
    """Tokenize text into meaningful words, expanding synonyms."""
    text = re.sub(r'[^\w\s]', ' ', text.lower())
    words = [w for w in text.split() if w not in _STOP_WORDS and len(w) > 1]
    # Expand synonyms
    expanded = list(words)
    for w in words:
        if w in _SYNONYMS:
            expanded.extend(_SYNONYMS[w])
    return expanded


def _tokenize_simple(text):
    """Tokenize without synonym expansion (for building document vectors)."""
    text = re.sub(r'[^\w\s]', ' ', text.lower())
    return [w for w in text.split() if w not in _STOP_WORDS and len(w) > 1]


def load():
    """Load the dental knowledge base and build search index."""
    global _knowledge, _idf, _doc_vectors, _ready

    kb_path = os.path.join(os.path.dirname(__file__), "data", "dental_knowledge.json")
    if not os.path.exists(kb_path):
        print("[dental_knowledge_engine] Knowledge base not found")
        return False

    with open(kb_path) as f:
        _knowledge = json.load(f)

    if not _knowledge:
        return False

    # Build document corpus from keywords + patterns + answer text
    docs = []
    for entry in _knowledge:
        text_parts = []
        # Keywords are high-value — include multiple times for boosting
        text_parts.extend(entry.get("keywords", []) * 3)
        text_parts.extend(entry.get("patterns", []) * 2)
        text_parts.append(entry.get("answer", ""))
        text_parts.append(entry.get("category", ""))
        full_text = " ".join(text_parts)
        docs.append(_tokenize_simple(full_text))

    # Calculate IDF (inverse document frequency)
    n_docs = len(docs)
    df = Counter()  # document frequency
    for doc in docs:
        unique_words = set(doc)
        for word in unique_words:
            df[word] += 1

    _idf = {}
    for word, freq in df.items():
        _idf[word] = math.log((n_docs + 1) / (freq + 1)) + 1

    # Build TF-IDF vectors for each document
    _doc_vectors = []
    for doc in docs:
        tf = Counter(doc)
        max_tf = max(tf.values()) if tf else 1
        vector = {}
        for word, count in tf.items():
            # Normalized TF * IDF
            vector[word] = (0.5 + 0.5 * count / max_tf) * _idf.get(word, 1)
        _doc_vectors.append(vector)

    _ready = True
    print(f"[dental_knowledge_engine] Loaded {len(_knowledge)} entries")
    return True


def _cosine_similarity(vec1, vec2):
    """Compute cosine similarity between two sparse vectors (dicts)."""
    common = set(vec1.keys()) & set(vec2.keys())
    if not common:
        return 0.0

    dot = sum(vec1[w] * vec2[w] for w in common)
    mag1 = math.sqrt(sum(v * v for v in vec1.values()))
    mag2 = math.sqrt(sum(v * v for v in vec2.values()))

    if mag1 == 0 or mag2 == 0:
        return 0.0

    return dot / (mag1 * mag2)


def _keyword_boost(query_words, entry):
    """Give bonus score for direct keyword matches."""
    score = 0
    query_set = set(query_words)
    query_text = " ".join(query_words)

    # Direct keyword hits (high value)
    for kw in entry.get("keywords", []):
        kw_lower = kw.lower()
        if kw_lower in query_text:
            score += 3.0  # Multi-word keyword found in query
        elif any(w in query_set for w in kw_lower.split()):
            score += 1.0  # Single word from keyword found

    # Pattern matching (check if query resembles any pattern)
    for pattern in entry.get("patterns", []):
        pattern_words = set(_tokenize_simple(pattern))
        overlap = query_set & pattern_words
        if len(overlap) >= 2:
            score += 2.0 * len(overlap) / len(pattern_words)

    return score


def find_best_answer(user_message, min_confidence=0.15):
    """
    Find the best matching answer from the dental knowledge base.

    Args:
        user_message: The patient's message/question
        min_confidence: Minimum score threshold (0-1 range for cosine, but boosted)

    Returns:
        dict with 'answer', 'follow_up', 'category', 'confidence' or None
    """
    if not _ready:
        if not load():
            return None

    # Tokenize with synonym expansion
    query_words = _tokenize(user_message)
    if not query_words:
        return None

    # Build query TF-IDF vector
    tf = Counter(query_words)
    max_tf = max(tf.values()) if tf else 1
    query_vec = {}
    for word, count in tf.items():
        query_vec[word] = (0.5 + 0.5 * count / max_tf) * _idf.get(word, 1)

    # Score each knowledge entry
    best_score = 0
    best_idx = -1

    for i, doc_vec in enumerate(_doc_vectors):
        # TF-IDF cosine similarity
        sim = _cosine_similarity(query_vec, doc_vec)

        # Keyword boost
        boost = _keyword_boost(query_words, _knowledge[i])

        # Combined score
        total = sim + boost * 0.3  # Weight keyword boost

        if total > best_score:
            best_score = total
            best_idx = i

    if best_idx < 0 or best_score < min_confidence:
        return None

    entry = _knowledge[best_idx]
    return {
        "answer": entry["answer"],
        "follow_up": entry.get("follow_up", ""),
        "category": entry.get("category", ""),
        "confidence": round(best_score, 3),
    }


# Auto-load on import
load()
