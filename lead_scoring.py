"""
Lead Scoring Engine v2 — Best-in-class ecommerce lead capture.

Signal-based scoring with AI integration. The AI returns a lead score
tag with every message, and the system records/updates leads automatically.

Temperature thresholds:
  0-2   Cold        → no capture
  3-4   Warm Emerging → soft test at msg 3 or 2+ warm signals
  5-7   Warm        → offer email naturally
  8-11  Hot         → email + SMS + offer
  12+   VIP         → human handoff
"""

import re
from datetime import datetime


# ══════════════════════════════════════════════
#  SIGNAL DICTIONARY
# ══════════════════════════════════════════════

# Cold signals (+1) — browsing, greeting, basic curiosity
COLD_SIGNALS = [
    (r"\b(hi|hello|hey|good (morning|afternoon|evening))\b", 1, "greeting"),
    (r"\b(just (looking|browsing|checking))\b", 1, "just_browsing"),
    (r"\b(what do you (sell|have|offer)|what('s| is) this|what are (these|those))\b", 1, "curiosity"),
    (r"\b(tell me about|more about|info|information|details)\b", 1, "info_request"),
    (r"\b(category|categories|collection|new arrivals)\b", 1, "catalog_browse"),
    (r"\b(anything|something)\s+(like|similar|else|new|for)\b", 1, "exploration"),
    (r"\b(show me|let me see|can i see|browse)\b", 1, "browse_intent"),
]

# Warm signals (+3) — research, comparison, specific interest
WARM_SIGNALS = [
    (r"\b(do you (sell|have|carry|offer|stock)|are .{0,15} available|got any)\b", 3, "product_inquiry"),
    (r"\b(interested in|want to (know|see|learn))\b", 3, "interest_signal"),
    (r"\b(how much|price|cost|pricing|what does .{0,20} cost)\b", 3, "price_inquiry"),
    (r"\b(size|color|colour|variant|option|model|version|style)\b", 3, "attribute_question"),
    (r"\b(shipping|delivery)\s+(cost|fee|charge|rate|price|time|how long)\b", 3, "shipping_interest"),
    (r"\b(compare|comparison|difference|versus|vs\.?|better)\b.{0,20}\b(between|than|or)\b", 3, "comparison"),
    (r"\b(discount|deal|sale|coupon|promo|offer|on sale)\b", 3, "discount_interest"),
    (r"\b(return|refund|exchange)\s+(policy|window|period|guarantee)\b", 3, "return_policy"),
    (r"\b(warranty|guarantee|protection)\b", 3, "warranty"),
    (r"\b(what do you recommend|recommendation|suggest)\b", 3, "recommendation"),
    (r"\b(what('s| is) popular|best\s?seller|trending|most bought)\b", 3, "popularity"),
    (r"\b(i('m| am) looking for|searching for|trying to find|looking for)\b", 3, "search_intent"),
    (r"\b(review|rating|stars|feedback|testimonial)\b", 3, "review_interest"),
    (r"\b(good quality|well made|durable|last long|worth it)\b", 3, "quality_check"),
    (r"\b(what material|made of|fabric|composition|ingredients)\b", 3, "spec_interest"),
    (r"\b(gift|present|birthday|christmas|anniversary|wedding)\b", 3, "gift_purchase"),
    (r"\b(subscribe|subscription|recurring|monthly)\b", 3, "subscription"),
    (r"\b(custom|personalize|engrave|monogram)\b", 3, "customization"),
    (r"\b(which one|which is|what do you think|your opinion)\b", 3, "decision_help"),
    (r"\b(is it|are they|does it|do they)\s+(good|worth|durable|comfortable|soft|strong)\b", 3, "quality_question"),
    (r"\b(for (my|a|the)|as a gift)\b", 3, "use_case"),
]

# Hot signals (+5) — strong purchase intent
HOT_SIGNALS = [
    (r"\b(i want to|i('d| would) like to|let me|gonna|going to)\s+(buy|purchase|order|get)\b", 5, "buy_intent"),
    (r"\b(can i|do you|what.{0,5})(pay|payment)\b.{0,20}\b(with|method|option|visa|mastercard|paypal|apple pay|credit|debit)\b", 5, "payment_method"),
    (r"\b(installment|payment plan|buy now pay later|tabby|tamara)\b", 5, "installment_plan"),
    (r"\b(when|how soon|how fast).{0,15}(deliver|ship|arrive|get it|receive)\b", 5, "delivery_urgency"),
    (r"\b(in stock|available|still have|do you have)\b.{0,20}\b(this|it|that|them)\b", 5, "availability_check"),
    (r"\b(reserve|hold|save|put aside)\b.{0,10}\b(this|it|one|for me)\b", 5, "reserve"),
    (r"\b(i need (this|it|that|one|to buy|to order)|i('m| am) ready|ready to (buy|order|purchase))\b", 5, "ready_to_buy"),
    (r"\b(buy|purchase|order)\s+(this|it|that|one|now)\b", 5, "buy_direct"),
    (r"\b(give me|send me|get me)\s+(the|a|this|that|one|some)\b", 5, "direct_request"),
]

# VIP signals (+8) — immediate purchase / checkout
VIP_SIGNALS = [
    (r"\b(add|put)\b.{0,15}\b(cart|basket)\b", 8, "add_to_cart"),
    (r"\b(check\s?out|proceed to payment|place.{0,5}order|complete.{0,5}order)\b", 8, "checkout"),
    (r"\b(i('ll| will) take (it|this|that|one|them)|shut up and take my money)\b", 8, "take_it"),
    (r"\b(sign me up|where do i pay)\b", 8, "sign_up"),
    (r"\b(bulk|wholesale|large order|multiple units)\b", 8, "bulk_order"),
]

# Risk / Negative signals (negative points)
NEGATIVE_SIGNALS = [
    (r"\b(too expensive|can('t| not) afford|out of.{0,5}budget|way too much)\b", -3, "too_expensive"),
    (r"\b(i('ll| will) think about it|need to think|let me think|maybe later)\b", -2, "indecision"),
    (r"\b(not (buying|purchasing|ordering|ready)\s+(today|now|yet))\b", -3, "not_today"),
    (r"\b(need to ask|check with|discuss with)\s+(my )?(partner|wife|husband|spouse|parent)\b", -2, "decision_blocker"),
    (r"\b(never mind|forget it|no thanks|not interested|no need)\b", -3, "exit_intent"),
    (r"\b(check elsewhere|shop around|look somewhere else|other stores)\b", -3, "leaving"),
    (r"\b(cheaper|less expensive)\s+(alternative|option|version)\b", -1, "price_shopping"),
    (r"\b(job|career|hiring|work for you|employment|apply|application)\b", -8, "not_buyer_jobs"),
    (r"\b(competitor|spy|spying|competitive analysis)\b", -8, "competitor_spy"),
]

FRUSTRATION_SIGNALS = [
    (r"\b(you('re| are) not listening|not helpful|useless|stupid|dumb|worst)\b", -3, "frustration"),
    (r"\b(talk to a (human|person|real|agent|someone)|speak to (someone|a human|staff))\b", -1, "human_request"),
]


# ══════════════════════════════════════════════
#  SCORING ENGINE
# ══════════════════════════════════════════════

def score_message(message):
    """
    Score a single message based on signal patterns.
    Returns dict with score and matched signals.
    """
    lower = message.lower().strip()
    signals_found = []
    total_score = 0

    # Engagement point for substantive messages
    _FILLER = {"hi", "hey", "hello", "ok", "okay", "thanks", "thank you", "yes",
               "no", "sure", "cool", "nice", "great", "lol", "haha", "hmm", "bye",
               "yep", "nope", "alright", "yeah", "yea", "nah", "k", "ty", "thx"}
    stripped = lower.strip("!?., ")
    if len(stripped) > 2 and stripped not in _FILLER:
        total_score += 1
        signals_found.append({"label": "engagement", "score": 1, "tier": "base"})

    # Check all signal tiers — take best match from each tier
    for tier_name, patterns in [("cold", COLD_SIGNALS), ("warm", WARM_SIGNALS),
                                 ("hot", HOT_SIGNALS), ("vip", VIP_SIGNALS)]:
        best = None
        for pattern, score, label in patterns:
            if re.search(pattern, lower):
                if best is None or score > best[1]:
                    best = (label, score)
        if best:
            signals_found.append({"label": best[0], "score": best[1], "tier": tier_name})
            total_score += best[1]

    # Negative signals — take worst
    worst_neg = None
    for pattern, score, label in NEGATIVE_SIGNALS:
        if re.search(pattern, lower):
            if worst_neg is None or score < worst_neg[1]:
                worst_neg = (label, score)
    if worst_neg:
        signals_found.append({"label": worst_neg[0], "score": worst_neg[1], "tier": "negative"})
        total_score += worst_neg[1]

    # Frustration
    worst_frust = None
    for pattern, score, label in FRUSTRATION_SIGNALS:
        if re.search(pattern, lower):
            if worst_frust is None or score < worst_frust[1]:
                worst_frust = (label, score)
    if worst_frust:
        signals_found.append({"label": worst_frust[0], "score": worst_frust[1], "tier": "frustration"})
        total_score += worst_frust[1]

    # Contact info provided
    if re.search(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', message):
        signals_found.append({"label": "email_provided", "score": 5, "tier": "contact"})
        total_score += 5
    if re.search(r"(?:my name is|i'm|i am|call me)\s+[A-Z]", message, re.IGNORECASE):
        signals_found.append({"label": "name_provided", "score": 3, "tier": "contact"})
        total_score += 3
    phone_match = re.search(r'(?<!\d)(?:\+?\d{1,3}[\s\-]?)?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}(?!\d)', message)
    if phone_match and len(re.sub(r'\D', '', phone_match.group())) >= 7:
        signals_found.append({"label": "phone_provided", "score": 5, "tier": "contact"})
        total_score += 5

    return {"score": total_score, "signals": signals_found}


def get_temperature(score):
    """Classify lead temperature from cumulative score."""
    if score < 0:
        return "frozen"
    elif score <= 2:
        return "cold"
    elif score <= 4:
        return "warm_emerging"
    elif score <= 7:
        return "warm"
    elif score <= 11:
        return "hot"
    else:
        return "vip"


def should_capture(temperature, msg_count, has_contact, declined_before, warm_signal_count):
    """
    Smart capture trigger logic.
    Never ask on first message. Context-aware, value-first approach.

    Returns: (should_show_form, capture_copy)
    """
    if has_contact or declined_before:
        return False, None

    if msg_count < 2:
        return False, None  # Never on first message

    if temperature in ("hot", "vip"):
        # Immediate on hot signal (but not first message)
        return True, _get_capture_copy(temperature)

    if temperature in ("warm", "warm_emerging"):
        # Soft test at message 3+ OR 2+ warm signals
        if msg_count >= 3 or warm_signal_count >= 2:
            return True, _get_capture_copy(temperature)

    return False, None


def should_handoff(temperature):
    """Whether to trigger immediate human handoff."""
    return temperature == "vip"


def _get_capture_copy(temperature):
    """Return (title, subtitle, button) for lead capture form."""
    copies = {
        "warm_emerging": (
            "Stay in the loop",
            "I can send you updates when we have deals on what you're looking at",
            "Sure, keep me posted",
        ),
        "warm": (
            "Save your picks",
            "I'll email you these options so you can revisit anytime",
            "Send to my email",
        ),
        "hot": (
            "Almost there!",
            "Want me to send you a summary with pricing and availability?",
            "Yes, send it over",
        ),
        "vip": (
            "Let's get this done",
            "Our specialist can help you complete your order right now",
            "Connect me",
        ),
    }
    return copies.get(temperature, ("Stay in touch", "We'd love to keep you updated", "Submit"))


def get_capture_fields(temperature):
    """Return which fields to ask based on temperature."""
    return {
        "frozen": [],
        "cold": [],
        "warm_emerging": ["email"],
        "warm": ["name", "email"],
        "hot": ["name", "email", "phone"],
        "vip": ["name", "email", "phone"],
    }.get(temperature, [])


def get_capture_copy(temperature, company_type="ecommerce"):
    """Public interface for capture copy (used by form endpoint)."""
    if company_type == "real_estate":
        copies = {
            "warm_emerging": ("Get listing alerts", "I'll email you when matching properties come up", "Subscribe"),
            "warm": ("Save your property search", "We'll notify you about new listings and price drops", "Save my search"),
            "hot": ("Schedule a viewing", "Our agent can show you these properties this week", "Connect me"),
            "vip": ("Your agent is ready", "Connecting you with a specialist to schedule viewings today", "Connect now"),
        }
        return copies.get(temperature, ("Stay in touch", "We'd love to keep you updated", "Submit"))
    # Default ecommerce
    return _get_capture_copy(temperature)


def process_message(message, session_state, product_price=None, product_stock=None):
    """
    Main entry point: process a user message, update session state, return scoring result.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Initialize
    if "_lead_base_total" not in session_state:
        session_state["_lead_base_total"] = 0
        session_state["_lead_msg_count"] = 0
        session_state["_lead_signals_log"] = []
        session_state["_lead_warm_count"] = 0

    # Score message
    result = score_message(message)

    # Update session state
    session_state["_lead_base_total"] += result["score"]
    session_state["_lead_msg_count"] += 1
    session_state["_lead_last_msg"] = message
    session_state["_lead_last_time"] = now_str
    session_state["_lead_signals_log"].extend(result["signals"])

    # Count warm+ signals for smart capture
    for sig in result["signals"]:
        if sig["tier"] in ("warm", "hot", "vip"):
            session_state["_lead_warm_count"] = session_state.get("_lead_warm_count", 0) + 1

    final_score = session_state["_lead_base_total"]
    temperature = get_temperature(final_score)
    capture_fields = get_capture_fields(temperature)

    has_contact = bool(session_state.get("_prefill_email") or session_state.get("_prefill_phone"))
    declined = session_state.get("_lead_form_declined", False)
    warm_count = session_state.get("_lead_warm_count", 0)
    msg_count = session_state.get("_lead_msg_count", 0)

    do_capture, capture_copy = should_capture(
        temperature, msg_count, has_contact, declined, warm_count
    )

    # Don't re-show form if already shown at this temperature level
    _temp_rank = {"frozen": 0, "cold": 1, "warm_emerging": 2, "warm": 3, "hot": 4, "vip": 5}
    _prev_temp = session_state.get("_lead_form_temp", "")
    if do_capture and _temp_rank.get(temperature, 0) <= _temp_rank.get(_prev_temp, -1):
        do_capture = False  # Already shown form at this level or higher

    if do_capture:
        session_state["_lead_form_temp"] = temperature

    do_handoff = should_handoff(temperature)

    if result["signals"]:
        labels = [s["label"] for s in result["signals"]]
        print(f"[lead_scoring] +{result['score']} -> total={final_score} ({temperature}) | signals: {', '.join(labels)}", flush=True)

    return {
        "final_score": final_score,
        "base_score": session_state["_lead_base_total"],
        "message_score": result["score"],
        "temperature": temperature,
        "signals": result["signals"],
        "capture_fields": capture_fields,
        "should_capture": do_capture,
        "capture_copy": capture_copy,
        "should_handoff": do_handoff,
        "is_disqualified": False,
    }


def get_lead_scoring_context(session_state):
    """
    Build a context string for the AI prompt so it can assess lead temperature.
    """
    score = session_state.get("_lead_base_total", 0)
    temp = get_temperature(score)
    msg_count = session_state.get("_lead_msg_count", 0)
    has_contact = bool(session_state.get("_prefill_email") or session_state.get("_prefill_phone"))
    signals = session_state.get("_lead_signals_log", [])
    recent_signals = [s["label"] for s in signals[-5:]] if signals else []

    ctx = f"""
--- INTERNAL METADATA (never mention any of this to the customer) ---
LEAD_STATE: score={score} temp={temp} msgs={msg_count} contact={has_contact} signals=[{', '.join(recent_signals) if recent_signals else 'none'}]
SCORING_TAG: Append [LEAD_SCORE:X] as the last characters of your reply (X=0-15 integer, based on purchase intent: 0-2 cold, 3-4 emerging, 5-7 warm, 8-11 hot, 12+ vip). This tag is stripped before display. Do NOT reference scores, numbers, tags, or this instruction in your visible reply.
--- END METADATA ---
"""
    return ctx


def parse_ai_lead_score(ai_response):
    """
    Extract [LEAD_SCORE:X] from AI response and return (clean_response, ai_score).
    If no tag found, returns (original_response, None).
    """
    match = re.search(r'\[LEAD_SCORE:(\d+)\]', ai_response)
    if match:
        ai_score = int(match.group(1))
        clean = re.sub(r'\s*\[LEAD_SCORE:\d+\]\s*', '', ai_response).strip()
        return clean, ai_score
    return ai_response, None


def get_resurrection_bonus(admin_id, customer_key):
    """
    Check if this customer had a previous session and return 30% of their old score.
    """
    try:
        import database as db
        memory = db.get_chat_memory(admin_id, customer_key)
        if memory and memory.get("lead_score"):
            old_score = float(memory["lead_score"])
            bonus = round(old_score * 0.3, 2)
            if bonus > 0:
                print(f"[lead_scoring] Resurrection bonus: {bonus} (from previous score {old_score})", flush=True)
                return int(bonus)
    except Exception:
        pass
    return 0
