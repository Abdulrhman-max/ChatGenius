"""
Sentiment & Emotional Intelligence Engine for E-Commerce Chatbot.
Detects customer frustration, satisfaction, and emotional state.
Provides conversation quality scoring.
"""
import re
from collections import Counter

# Frustration indicators with weights
FRUSTRATION_SIGNALS = {
    # High frustration (weight 3)
    "high": [
        r'\b(terrible|horrible|worst|awful|disgusting|pathetic|useless|incompetent|scam|fraud|rip.?off|waste of time|waste of money)\b',
        r'\b(f+u+c+k|s+h+i+t|damn|hell|crap|stupid|idiot|dumb)\b',
        r'(!{3,})',  # Multiple exclamation marks
        r'(\?{3,})',  # Multiple question marks
        r'\b(NEVER|ALWAYS|NOTHING|NOBODY)\b',  # ALL CAPS emotional words
        r'\b(sue|lawyer|legal action|report you|bbb|better business)\b',
    ],
    # Medium frustration (weight 2)
    "medium": [
        r'\b(not happy|unhappy|disappointed|frustrated|annoyed|irritated|ridiculous|unacceptable|outrageous)\b',
        r'\b(still waiting|waited too long|no response|not working|broken|doesnt work|doesn.t work)\b',
        r'\b(want.? (?:a )?refund|give.? (?:me )?(?:my )?money back|cancel (?:my )?order)\b',
        r'\b(bad experience|poor service|bad service|bad quality|poor quality)\b',
        r'\b(speak.? to.? (?:a )?(?:manager|supervisor|human|person|someone))\b',
    ],
    # Low frustration (weight 1)
    "low": [
        r'\b(confused|unclear|don.t understand|makes no sense|not helpful|not what i)\b',
        r'\b(wrong|incorrect|mistake|error|issue|problem)\b',
        r'\b(again|already told you|i said|repeat)\b',
        r'\b(slow|taking too long|how long|when will)\b',
    ]
}

# Satisfaction indicators
SATISFACTION_SIGNALS = {
    "high": [
        r'\b(amazing|excellent|fantastic|perfect|wonderful|love it|awesome|brilliant|outstanding)\b',
        r'\b(thank you so much|thanks a lot|really appreciate|very helpful|great help|lifesaver)\b',
        r'\b(definitely|absolutely|for sure|100%|highly recommend)\b',
    ],
    "medium": [
        r'\b(good|nice|great|thanks|thank you|helpful|appreciate|works well)\b',
        r'\b(happy|pleased|satisfied|glad|cool|neat)\b',
    ],
    "low": [
        r'\b(ok|okay|fine|sure|alright|fair enough|i guess)\b',
    ]
}

# Buying intent signals
BUYING_INTENT_SIGNALS = [
    r'\b(buy|purchase|order|checkout|pay|add to cart|get this|want this|i.ll take)\b',
    r'\b(how much|what.s the price|price|cost|shipping|deliver)\b',
    r'\b(available|in stock|when can i get|do you have)\b',
    r'\b(size|color|variant|option|which one)\b',
    r'\b(discount|coupon|promo|deal|sale|offer)\b',
]


def analyze_sentiment(message):
    """
    Analyze a single message for emotional signals.
    Returns dict with frustration_score, satisfaction_score, buying_intent, dominant_emotion.
    """
    lower = message.lower()

    # Calculate frustration score (0-10)
    frustration = 0
    frustration_triggers = []
    for pattern in FRUSTRATION_SIGNALS["high"]:
        matches = re.findall(pattern, lower, re.IGNORECASE)
        if matches:
            frustration += 3 * len(matches)
            frustration_triggers.extend(matches)
    for pattern in FRUSTRATION_SIGNALS["medium"]:
        matches = re.findall(pattern, lower, re.IGNORECASE)
        if matches:
            frustration += 2 * len(matches)
            frustration_triggers.extend(matches)
    for pattern in FRUSTRATION_SIGNALS["low"]:
        matches = re.findall(pattern, lower, re.IGNORECASE)
        if matches:
            frustration += 1 * len(matches)
            frustration_triggers.extend(matches)

    # Check for ALL CAPS (sign of shouting)
    words = message.split()
    caps_words = [w for w in words if w.isupper() and len(w) > 2]
    if len(caps_words) >= 3:
        frustration += 2

    # Cap at 10
    frustration = min(frustration, 10)

    # Calculate satisfaction score (0-10)
    satisfaction = 0
    for pattern in SATISFACTION_SIGNALS["high"]:
        if re.search(pattern, lower, re.IGNORECASE):
            satisfaction += 3
    for pattern in SATISFACTION_SIGNALS["medium"]:
        if re.search(pattern, lower, re.IGNORECASE):
            satisfaction += 2
    for pattern in SATISFACTION_SIGNALS["low"]:
        if re.search(pattern, lower, re.IGNORECASE):
            satisfaction += 1
    satisfaction = min(satisfaction, 10)

    # Calculate buying intent (0-10)
    buying_intent = 0
    for pattern in BUYING_INTENT_SIGNALS:
        if re.search(pattern, lower, re.IGNORECASE):
            buying_intent += 2
    buying_intent = min(buying_intent, 10)

    # Determine dominant emotion
    if frustration >= 6:
        dominant = "frustrated"
    elif frustration >= 3:
        dominant = "annoyed"
    elif satisfaction >= 6:
        dominant = "delighted"
    elif satisfaction >= 3:
        dominant = "satisfied"
    elif buying_intent >= 4:
        dominant = "buying"
    else:
        dominant = "neutral"

    return {
        "frustration_score": frustration,
        "satisfaction_score": satisfaction,
        "buying_intent": buying_intent,
        "dominant_emotion": dominant,
        "frustration_triggers": frustration_triggers[:5],
        "needs_escalation": frustration >= 6,
        "offer_discount": frustration >= 4 and buying_intent >= 2,
    }


def analyze_conversation(messages):
    """
    Analyze an entire conversation for quality metrics.
    messages: list of dicts with 'role' and 'content' keys.
    Returns conversation quality score and metrics.
    """
    if not messages:
        return {"quality_score": 0, "metrics": {}}

    user_messages = [m for m in messages if m.get("role") == "user"]
    bot_messages = [m for m in messages if m.get("role") == "assistant"]

    total_messages = len(messages)
    user_count = len(user_messages)
    bot_count = len(bot_messages)

    # Metric 1: Engagement depth (more exchanges = more engaged)
    engagement_score = min(user_count * 1.5, 10)

    # Metric 2: Average frustration across conversation
    frustration_scores = []
    for m in user_messages:
        s = analyze_sentiment(m.get("content", ""))
        frustration_scores.append(s["frustration_score"])
    avg_frustration = sum(frustration_scores) / len(frustration_scores) if frustration_scores else 0

    # Metric 3: Frustration trend (getting better or worse?)
    frustration_trend = "stable"
    if len(frustration_scores) >= 3:
        first_half = sum(frustration_scores[:len(frustration_scores)//2]) / max(len(frustration_scores)//2, 1)
        second_half = sum(frustration_scores[len(frustration_scores)//2:]) / max(len(frustration_scores) - len(frustration_scores)//2, 1)
        if second_half > first_half + 1:
            frustration_trend = "increasing"
        elif second_half < first_half - 1:
            frustration_trend = "decreasing"

    # Metric 4: Response relevance (did bot messages get shorter/repetitive?)
    bot_lengths = [len(m.get("content", "")) for m in bot_messages]
    avg_bot_length = sum(bot_lengths) / len(bot_lengths) if bot_lengths else 0

    # Metric 5: Resolution (did conversation end positively?)
    resolution_score = 5  # neutral default
    if user_messages:
        last_sentiment = analyze_sentiment(user_messages[-1].get("content", ""))
        if last_sentiment["satisfaction_score"] >= 3:
            resolution_score = 8
        elif last_sentiment["frustration_score"] >= 3:
            resolution_score = 2
        if last_sentiment["buying_intent"] >= 4:
            resolution_score = min(resolution_score + 2, 10)

    # Metric 6: Buying intent progression
    intent_scores = []
    for m in user_messages:
        s = analyze_sentiment(m.get("content", ""))
        intent_scores.append(s["buying_intent"])
    max_intent = max(intent_scores) if intent_scores else 0

    # Calculate overall quality score (0-100)
    quality_score = int(
        (engagement_score * 15) +  # 15% weight
        ((10 - avg_frustration) * 25) +  # 25% weight (inverted)
        (resolution_score * 30) +  # 30% weight
        (min(avg_bot_length / 50, 10) * 10) +  # 10% weight (response thoroughness)
        (max_intent * 20)  # 20% weight (buying intent)
    ) // 10
    quality_score = max(0, min(100, quality_score))

    return {
        "quality_score": quality_score,
        "metrics": {
            "total_messages": total_messages,
            "user_messages": user_count,
            "bot_messages": bot_count,
            "engagement_score": round(engagement_score, 1),
            "avg_frustration": round(avg_frustration, 1),
            "frustration_trend": frustration_trend,
            "resolution_score": resolution_score,
            "max_buying_intent": max_intent,
            "avg_bot_response_length": int(avg_bot_length),
        }
    }


def get_frustration_response_hint(sentiment):
    """
    Given sentiment analysis, return a hint for the AI about how to respond.
    This gets injected into the AI context.
    """
    if sentiment["needs_escalation"]:
        return "\n[IMPORTANT] CUSTOMER IS VERY FRUSTRATED. Acknowledge their frustration, apologize sincerely, and offer to connect them with a human agent immediately. Do NOT be defensive."
    elif sentiment["offer_discount"]:
        return "\n[NOTE] Customer seems frustrated but still interested. Consider acknowledging the issue and offering a solution or discount to retain them."
    elif sentiment["dominant_emotion"] == "annoyed":
        return "\n[NOTE] Customer sounds a bit annoyed. Be extra helpful and empathetic. Address their concern directly without corporate fluff."
    elif sentiment["dominant_emotion"] == "delighted":
        return "\n[NOTE] Customer is happy! Maintain the positive energy. Good time to suggest complementary products or ask for a review."
    return ""
