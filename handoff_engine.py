"""
Live Chat Handoff Engine for ChatGenius.
Handles seamless AI-to-human conversation transfer.
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("handoff")

# Keywords that trigger handoff
HUMAN_REQUEST_KEYWORDS = [
    'speak to a human', 'talk to someone', 'real person', 'human agent',
    'customer service', 'speak to staff', 'talk to a person', 'representative',
    'connect me', 'operator',
    # Arabic
    'أريد التحدث مع شخص', 'موظف', 'خدمة العملاء', 'شخص حقيقي',
]

DEFAULT_CONFIDENCE_THRESHOLD = 0.6
HANDOFF_TIMEOUT_MINUTES = 5


def should_handoff(message, confidence_score, admin_id=None):
    """
    Determine if conversation should be handed off to a human.
    Returns: (should_handoff: bool, reason: str)

    Triggers:
    1. Patient explicitly asks for a human
    2. AI confidence score is below threshold
    """
    lower = message.lower()

    # Check for explicit human request
    for keyword in HUMAN_REQUEST_KEYWORDS:
        if keyword in lower:
            return True, "patient_requested"

    # Check confidence threshold
    threshold = DEFAULT_CONFIDENCE_THRESHOLD
    if admin_id:
        import database as db
        conn = db.get_db()
        try:
            company = conn.execute("SELECT handoff_threshold FROM company_info WHERE user_id=%s", (admin_id,)).fetchone()
        finally:
            conn.close()
        if company and company["handoff_threshold"]:
            try:
                threshold = float(company["handoff_threshold"])
            except (ValueError, TypeError):
                pass

    if confidence_score < threshold:
        return True, "low_confidence"

    return False, ""


def create_handoff(admin_id, session_id, patient_name, reason, conversation_history=None, ai_confidence=None):
    """
    Create a handoff request. Puts the conversation in the queue for staff pickup.
    Returns: handoff dict with id and status.
    """
    import database as db
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Use INSERT...ON CONFLICT to avoid race condition between check and insert
        _ins_cur = conn.execute(
            """INSERT INTO live_chat_handoffs
               (admin_id, session_id, patient_name, reason, status, ai_confidence, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (session_id) WHERE status IN ('queued','assigned')
               DO UPDATE SET session_id = live_chat_handoffs.session_id
               RETURNING id, status, (xmax = 0) AS inserted""",
            (admin_id, session_id, patient_name, reason, "queued", ai_confidence, now)
        )
        row = _ins_cur.fetchone()
        handoff_id = row['id']
        was_inserted = row['inserted']
        status = row['status']
        conn.commit()
    finally:
        conn.close()

    if not was_inserted:
        return {"id": handoff_id, "status": status, "already_exists": True}

    logger.info(f"Handoff #{handoff_id} created for {patient_name} (reason: {reason})")
    return {"id": handoff_id, "status": "queued", "created_at": now}


def assign_handoff(handoff_id, staff_user_id, staff_name, admin_id=None):
    """Staff member takes over a conversation."""
    import database as db
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Use WHERE status='queued' to atomically prevent race condition
        if admin_id:
            cur = conn.execute(
                "UPDATE live_chat_handoffs SET status='assigned', staff_user_id=%s, staff_name=%s, assigned_at=%s WHERE id=%s AND status='queued' AND admin_id=%s",
                (staff_user_id, staff_name, now, handoff_id, admin_id)
            )
        else:
            cur = conn.execute(
                "UPDATE live_chat_handoffs SET status='assigned', staff_user_id=%s, staff_name=%s, assigned_at=%s WHERE id=%s AND status='queued'",
                (staff_user_id, staff_name, now, handoff_id)
            )

        if cur.rowcount == 0:
            # Either not found or not in queued status
            handoff = conn.execute("SELECT status FROM live_chat_handoffs WHERE id=%s", (handoff_id,)).fetchone()
            if not handoff:
                return {"error": "Handoff not found"}
            return {"error": f"Handoff is already {handoff['status']}"}

        conn.commit()
    finally:
        conn.close()

    logger.info(f"Handoff #{handoff_id} assigned to {staff_name}")
    return {"success": True, "staff_name": staff_name}


def resolve_handoff(handoff_id, resolution_notes="", admin_id=None):
    """Staff resolves the handoff, AI resumes."""
    import database as db
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        if admin_id:
            conn.execute(
                "UPDATE live_chat_handoffs SET status='resolved', resolved_at=%s, resolution_notes=%s WHERE id=%s AND admin_id=%s",
                (now, resolution_notes, handoff_id, admin_id)
            )
        else:
            conn.execute(
                "UPDATE live_chat_handoffs SET status='resolved', resolved_at=%s, resolution_notes=%s WHERE id=%s",
                (now, resolution_notes, handoff_id)
            )
        conn.commit()
    finally:
        conn.close()

    logger.info(f"Handoff #{handoff_id} resolved")
    return {"success": True}


def send_handoff_message(handoff_id, sender_type, sender_name, message, admin_id=None):
    """
    Send a message in a handoff conversation.
    sender_type: 'staff' or 'patient'

    Messages are stored in chat_logs with is_human_handled flag.
    """
    import database as db
    conn = db.get_db()

    try:
        if admin_id:
            handoff = conn.execute("SELECT * FROM live_chat_handoffs WHERE id=%s AND admin_id=%s", (handoff_id, admin_id)).fetchone()
        else:
            handoff = conn.execute("SELECT * FROM live_chat_handoffs WHERE id=%s", (handoff_id,)).fetchone()
        if not handoff:
            return {"error": "Handoff not found"}

        handoff = dict(handoff)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Store in chat_logs
        conn.execute(
            """INSERT INTO chat_logs
               (session_id, admin_id, message, intent, is_human_handled, handler_user_id, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (handoff["session_id"], handoff["admin_id"],
             f"[{sender_type.upper()}:{sender_name}] {message}",
             "handoff_message", 1,
             handoff.get("staff_user_id") if sender_type == "staff" else None,
             now)
        )
        conn.commit()
    finally:
        conn.close()

    return {"success": True, "timestamp": now}


def get_handoff_queue(admin_id):
    """Get all pending and active handoffs for the dashboard, ordered by wait time."""
    import database as db
    conn = db.get_db()

    try:
        handoffs = conn.execute(
            """SELECT h.*,
                      EXTRACT(EPOCH FROM (NOW() - h.created_at)) / 60 as wait_minutes
               FROM live_chat_handoffs h
               WHERE h.admin_id=%s AND h.status IN ('queued', 'assigned')
               ORDER BY CASE h.status WHEN 'queued' THEN 0 ELSE 1 END, h.created_at ASC""",
            (admin_id,)
        ).fetchall()

        result = []
        for h in handoffs:
            h = dict(h)
            # Get conversation history preview (last 3 messages)
            history = conn.execute(
                "SELECT message, created_at FROM chat_logs WHERE session_id=%s ORDER BY created_at DESC LIMIT 3",
                (h["session_id"],)
            ).fetchall()

            h["conversation_preview"] = [dict(msg) for msg in reversed(history)]
            h["wait_time_display"] = _format_wait_time(h.get("wait_minutes", 0))

            # Typing indicator: agent is typing if typing_at is within last 10 seconds
            typing_at = h.get("typing_at")
            h["agent_typing"] = False
            if typing_at:
                try:
                    if isinstance(typing_at, str):
                        typing_at = datetime.strptime(typing_at, "%Y-%m-%d %H:%M:%S")
                    h["agent_typing"] = (datetime.now() - typing_at).total_seconds() < 10
                except Exception:
                    pass

            # Priority based on reason
            reason = (h.get("reason") or "").lower()
            if "complaint" in reason or "urgent" in reason:
                h["priority"] = "urgent"
            elif "patient_requested" in reason or "human" in reason:
                h["priority"] = "normal"
            else:
                h["priority"] = "low"

            result.append(h)
    finally:
        conn.close()

    return result


def get_handoff_for_session(session_id):
    """Check if a session has an active handoff."""
    import database as db
    conn = db.get_db()
    try:
        handoff = conn.execute(
            "SELECT * FROM live_chat_handoffs WHERE session_id=%s AND status IN ('queued','assigned') LIMIT 1",
            (session_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(handoff) if handoff else None


def check_handoff_timeout():
    """
    Check for handoffs waiting > 5 minutes with no staff pickup.
    Called by background scheduler.
    Returns list of timed-out handoff IDs for notification.
    """
    import database as db
    conn = db.get_db()

    try:
        cutoff = (datetime.now() - timedelta(minutes=HANDOFF_TIMEOUT_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")

        timed_out = conn.execute(
            "SELECT * FROM live_chat_handoffs WHERE status='queued' AND created_at <= %s",
            (cutoff,)
        ).fetchall()

        results = []
        for h in timed_out:
            h = dict(h)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE live_chat_handoffs SET status='timeout', resolved_at=%s WHERE id=%s",
                (now, h["id"])
            )
            logger.info(f"Handoff #{h['id']} for {h.get('patient_name', 'Unknown')} timed out after {HANDOFF_TIMEOUT_MINUTES} minutes with no staff pickup")
            results.append(h)

        conn.commit()
    finally:
        conn.close()
    return results


def get_handoff_stats(admin_id):
    """Get handoff statistics for dashboard."""
    import database as db
    conn = db.get_db()

    try:
        total = conn.execute(
            "SELECT COUNT(*) as c FROM live_chat_handoffs WHERE admin_id=%s", (admin_id,)
        ).fetchone()["c"]

        queued = conn.execute(
            "SELECT COUNT(*) as c FROM live_chat_handoffs WHERE admin_id=%s AND status='queued'", (admin_id,)
        ).fetchone()["c"]

        resolved = conn.execute(
            "SELECT COUNT(*) as c FROM live_chat_handoffs WHERE admin_id=%s AND status='resolved'", (admin_id,)
        ).fetchone()["c"]

        # Average resolution time
        avg_time = conn.execute(
            """SELECT AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 60) as avg_min
               FROM live_chat_handoffs WHERE admin_id=%s AND status='resolved' AND resolved_at IS NOT NULL""",
            (admin_id,)
        ).fetchone()
    finally:
        conn.close()

    return {
        "total_handoffs": total,
        "currently_queued": queued,
        "resolved": resolved,
        "avg_resolution_minutes": round(avg_time["avg_min"], 1) if avg_time and avg_time["avg_min"] else 0
    }


def smart_escalation_check(session, message, admin_id):
    """Enhanced escalation detection beyond simple keywords.
    Returns (should_escalate: bool, reason: str, urgency: str)"""
    import re

    msg_lower = message.lower()
    history = session.get("history", [])

    # 1. Explicit human request (existing behavior)
    for keyword in HUMAN_REQUEST_KEYWORDS:
        if keyword in msg_lower:
            return True, "customer_requested", "high"

    # 2. Frustration signals — multiple negative messages in a row
    negative_count = 0
    for h in history[-5:]:
        if h.get("role") == "user":
            hmsg = (h.get("content") or "").lower()
            if re.search(r'\b(frustrated|angry|upset|terrible|awful|worst|ridiculous|unacceptable|horrible|useless)\b', hmsg):
                negative_count += 1
    if negative_count >= 2:
        return True, "customer_frustration", "high"

    # 3. Repeated questions — customer asking the same thing 3+ times
    if len(history) >= 6:
        recent_user_msgs = [h["content"].lower().strip() for h in history[-6:] if h.get("role") == "user"]
        if len(recent_user_msgs) >= 3:
            # Check for similarity between messages
            for i, m1 in enumerate(recent_user_msgs):
                similar_count = sum(1 for m2 in recent_user_msgs[i+1:] if _message_similarity(m1, m2) > 0.6)
                if similar_count >= 2:
                    return True, "repeated_question", "medium"

    # 4. Complex issue indicators
    complex_indicators = [
        r'\b(legal|lawyer|sue|lawsuit|attorney)\b',
        r'\b(complaint|formal complaint|report|escalate)\b',
        r'\b(manager|supervisor|boss|higher up)\b',
        r'\b(fraud|scam|stolen|unauthorized)\b',
    ]
    for pattern in complex_indicators:
        if re.search(pattern, msg_lower):
            return True, "complex_issue", "high"

    # 5. Failed resolution — bot said "I can't" or "I don't know" recently
    for h in history[-3:]:
        if h.get("role") == "assistant":
            amsg = (h.get("content") or "").lower()
            if re.search(r"(i can't|i cannot|i'm unable|i don't have|i'm not sure|i don't know how|beyond my ability)", amsg):
                if re.search(r'\b(still|again|but|yet)\b', msg_lower):
                    return True, "bot_unable_to_resolve", "medium"

    return False, "", ""


def generate_copilot_suggestions(admin_id, session_id, session=None):
    """Generate AI-powered response suggestions for the human agent.
    Analyzes conversation history and provides contextual recommendations."""
    import database as db

    suggestions = []
    history = (session or {}).get("history", [])

    if not history:
        return suggestions

    # Extract key info from conversation
    customer_name = (session or {}).get("_prefill_name", "")
    customer_email = (session or {}).get("_prefill_email", "")
    cart = (session or {}).get("_cart", [])

    # Analyze the issue from recent messages
    recent_user_msgs = [h["content"] for h in history[-6:] if h.get("role") == "user"]
    combined = " ".join(recent_user_msgs).lower()

    # Issue categorization and suggested responses
    import re

    if re.search(r'\b(order|tracking|package|delivery|ship)\b', combined):
        suggestions.append({
            "type": "order_lookup",
            "text": f"Let me look up your order details right away, {customer_name or 'there'}. Could you confirm your order number?",
            "action": "Check order status in the Orders tab",
        })
        if re.search(r'\b(late|delayed|slow|hasn\'t arrived|not received|where)\b', combined):
            suggestions.append({
                "type": "shipping_delay",
                "text": "I apologize for the delay. Let me check with our shipping team and get you an updated delivery estimate.",
                "action": "Contact carrier for tracking update",
            })

    if re.search(r'\b(refund|return|exchange|money back|send back)\b', combined):
        suggestions.append({
            "type": "return_request",
            "text": f"I'd be happy to help with your return. I'll initiate the return process for you right away.",
            "action": "Create return authorization in Orders tab",
        })

    if re.search(r'\b(broken|damaged|defective|wrong item|missing|not what I ordered)\b', combined):
        suggestions.append({
            "type": "quality_issue",
            "text": "I'm sorry to hear about this issue. We'll make it right — I can arrange a replacement or full refund for you.",
            "action": "Offer replacement or refund; request photos if needed",
        })

    if re.search(r'\b(payment|charge|charged|billing|invoice|overcharged)\b', combined):
        suggestions.append({
            "type": "billing",
            "text": "Let me review your billing details. I can see your account and will sort this out for you.",
            "action": "Check payment records in Stripe dashboard",
        })

    if cart:
        cart_total = sum(i["price"] * i["qty"] for i in cart)
        suggestions.append({
            "type": "cart_assist",
            "text": f"I see you have items in your cart ({len(cart)} items, total: ${cart_total:.2f}). Is there anything I can help you with regarding your purchase?",
            "action": f"Customer has {len(cart)} items worth ${cart_total:.2f} in cart",
        })

    # Default suggestion
    if not suggestions:
        suggestions.append({
            "type": "general",
            "text": f"Hi {customer_name or 'there'}, I'm here to help. How can I assist you today?",
            "action": "Review conversation history for context",
        })

    # Add context summary
    if customer_email:
        # Check for order history
        try:
            orders = db.get_ecom_orders_by_customer(admin_id, customer_email)
            if orders:
                suggestions.append({
                    "type": "customer_context",
                    "text": f"Customer has {len(orders)} previous order(s). Most recent: #{orders[0].get('order_number', '')} ({orders[0].get('order_status', 'unknown')})",
                    "action": "View full order history",
                })
        except Exception:
            pass

    return suggestions


def _message_similarity(msg1, msg2):
    """Simple word-overlap similarity between two messages."""
    words1 = set(msg1.split())
    words2 = set(msg2.split())
    if not words1 or not words2:
        return 0
    overlap = len(words1 & words2)
    return overlap / max(len(words1), len(words2))


def _format_wait_time(minutes):
    """Format wait time for display."""
    if not minutes:
        return "Just now"
    minutes = float(minutes)
    if minutes < 1:
        return "Just now"
    if minutes < 60:
        return f"{int(minutes)} min"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"{hours}h {mins}m"
