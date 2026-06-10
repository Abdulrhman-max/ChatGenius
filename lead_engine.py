"""
Lead Management Engine for ChatGenius.
Handles lead capture, scoring, follow-up sequences, stage progression,
and abandoned conversation detection.
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("lead_engine")

# Follow-up schedule: day offset -> template key
FOLLOWUP_SCHEDULE = [1, 3, 7]

# High-value treatments for scoring
HIGH_VALUE_TREATMENTS = [
    "implant", "invisalign", "veneer", "orthodont", "crown", "bridge",
    "denture", "root canal", "cosmetic", "smile makeover", "all-on-4",
]
MEDIUM_VALUE_TREATMENTS = [
    "whitening", "filling", "extraction", "cleaning", "checkup",
    "scaling", "fluoride", "sealant", "x-ray",
]
URGENCY_KEYWORDS = [
    "pain", "emergency", "urgent", "asap", "soon", "hurts", "broken",
    "swollen", "bleeding", "cracked", "chipped", "sensitive",
]


def score_lead(name="", phone="", email="", treatment_interest="",
               is_returning=False, message_count=0, conversation_text=""):
    """Fallback lead score (1-10) when advanced scoring engine wasn't used."""
    score = 1  # base score

    conv_lower = (conversation_text or "").lower()

    # Contact info completeness
    if email:
        score += 2
    if phone:
        score += 2
    if name and name != "Unknown":
        score += 1

    # Returning visitor
    if is_returning:
        score += 2

    # Engagement level
    if message_count >= 3:
        score += 1
    if message_count >= 8:
        score += 1

    # Purchase intent signals (generic, works for any company type)
    _buy_words = ["buy", "purchase", "order", "price", "cost", "how much",
                  "shipping", "delivery", "pay", "checkout", "cart", "stock",
                  "available", "book", "appointment", "schedule", "reserve"]
    if any(w in conv_lower for w in _buy_words):
        score += 2

    return min(10, max(1, score))


def extract_treatment_interest(conversation_history):
    """Scan conversation history for treatment mentions and return the most relevant one."""
    if not conversation_history:
        return ""

    text = " ".join(str(m) for m in conversation_history).lower()

    # Check high-value first
    for t in HIGH_VALUE_TREATMENTS:
        if t in text:
            return t.title()

    # Then medium
    for t in MEDIUM_VALUE_TREATMENTS:
        if t in text:
            return t.title()

    return ""


def capture_lead_from_session(session, admin_id, capture_trigger="chatbot"):
    """Auto-capture a lead from a chatbot session. Returns lead_id or None.
    Each session creates its own lead — multiple leads per user is fine."""
    import database as db

    session_id = session.get("_session_id", "")

    data = session.get("data", {})
    name = (session.get("_prefill_name") or data.get("name") or
            data.get("waitlist_name") or "").strip()
    email = (session.get("_prefill_email") or data.get("email") or
             data.get("waitlist_email") or "").strip()
    phone = (session.get("_prefill_phone") or data.get("phone") or
             data.get("waitlist_phone") or "").strip()

    # Allow anonymous leads — use session_id as identifier if no contact info
    if not name and not phone and not email:
        if not session_id:
            return None
        name = "Anonymous Visitor"

    # Same session → update existing lead (don't create duplicates per message)
    if session_id:
        existing = db.get_lead_by_session(session_id)
        if existing:
            lead_id = existing["id"]
            # Update score on existing lead
            lead_score = session.get("_lead_score", 0)
            lead_temperature = session.get("_lead_temperature")
            if lead_score and lead_score > 0:
                db.update_lead_score(lead_id, lead_score, temperature=lead_temperature)
            # Update contact info if newly captured (was missing before)
            updates = {}
            if name and name != "Anonymous Visitor" and (not existing.get("name") or existing["name"] in ("Unknown", "Anonymous Visitor")):
                updates["name"] = name
            if email and not existing.get("email"):
                updates["email"] = email
            if phone and not existing.get("phone"):
                updates["phone"] = phone
            treatment = data.get("treatment_interest", "") or extract_treatment_interest(session.get("history", []))
            if treatment and not existing.get("treatment_interest"):
                updates["treatment_interest"] = treatment
            if updates:
                db.update_lead_fields(lead_id, updates)
            return lead_id

    # Extract treatment interest from conversation history
    history = session.get("history", [])
    treatment = data.get("treatment_interest", "") or extract_treatment_interest(history)

    is_returning = 1 if session.get("_patient_recognized") else 0
    preferred_time = data.get("preferred_time", "")
    budget = data.get("budget", "").strip()

    # Use advanced lead scoring engine score if available, else fallback to simple scoring
    lead_score = session.get("_lead_score")
    if not lead_score or lead_score <= 0:
        lead_score = score_lead(
            name=name, phone=phone, email=email,
            treatment_interest=treatment, is_returning=bool(is_returning),
            message_count=len(history),
            conversation_text=" ".join(str(m) for m in history),
        )

    # Create new lead for this session (no email dedup — each session = new lead)
    lead_id = db.create_lead_for_session(
        name=name or "Unknown",
        phone=phone,
        email=email,
        admin_id=admin_id,
        source="chatbot",
        capture_trigger=capture_trigger,
        treatment_interest=treatment,
        is_returning=is_returning,
        preferred_time=preferred_time,
        session_id=session_id,
        budget=budget,
    )

    lead_temperature = session.get("_lead_temperature", None)
    db.update_lead_score(lead_id, lead_score, temperature=lead_temperature)

    # Save score breakdown and cart for dashboard detail view
    try:
        import json as _json

        # Score breakdown from signals log
        signals_log = session.get("_lead_signals_log", [])
        breakdown = {}
        for sig in signals_log:
            label = sig.get("label", "unknown")
            pts = sig.get("score", 0)
            if label in breakdown:
                breakdown[label] = {"score": breakdown[label]["score"] + pts, "tier": sig.get("tier", ""), "count": breakdown[label].get("count", 1) + 1}
            else:
                breakdown[label] = {"score": pts, "tier": sig.get("tier", ""), "count": 1}
        breakdown_json = _json.dumps(breakdown)

        # Cart data
        cart = session.get("_cart", [])
        cart_json = _json.dumps(cart) if cart else ""
        cart_total = sum(i.get("price", 0) * i.get("qty", 1) for i in cart) if cart else 0

        conn = db.get_db()
        conn.execute("""UPDATE leads SET score_breakdown=%s, cart_data=%s, revenue_at_risk=%s
                        WHERE id=%s""",
                     (breakdown_json, cart_json, cart_total, lead_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to save lead detail data for #{lead_id}: {e}")

    # Create follow-up sequence for new leads with email
    if email:
        create_followup_sequence(lead_id, admin_id)

    # Hot lead alert: score 12+ OR temperature is hot/vip
    temperature = lead_temperature or get_temperature_from_score(lead_score)
    if lead_score >= 12 or temperature in ("hot", "vip"):
        try:
            db.create_hot_lead_alert(lead_id, admin_id, name, lead_score, temperature, treatment)
        except Exception:
            pass

    # Queue timed outreach email: hot=5min, warm=1hr
    if email:
        try:
            queue_timed_lead_email(lead_id, admin_id, temperature)
        except Exception:
            pass

    # Mailchimp auto-sync hook
    try:
        import mailchimp_engine as mailchimp
        mailchimp.auto_sync_if_enabled({"name": name, "email": email, "phone": phone}, admin_id)
    except Exception:
        pass

    # ── Zapier webhook: new lead ──
    try:
        import zapier_engine
        zapier_engine.trigger_new_lead(admin_id, {
            "id": lead_id, "name": name, "phone": phone, "email": email,
            "source": "chatbot", "score": lead_score,
            "treatment_interest": treatment, "capture_trigger": capture_trigger,
        })
    except Exception:
        pass

    logger.info(f"Lead #{lead_id} captured: {name} (score={lead_score}, trigger={capture_trigger})")
    return lead_id


def create_followup_sequence(lead_id, admin_id):
    """Create follow-up entries for day 1, 3, 7."""
    import database as db
    now = datetime.now()
    for day in FOLLOWUP_SCHEDULE:
        scheduled = now + timedelta(days=day)
        scheduled_str = scheduled.strftime("%Y-%m-%d 09:00:00")
        db.create_lead_followup(lead_id, admin_id, day, scheduled_str)
    logger.info(f"Follow-up sequence created for lead #{lead_id}: days {FOLLOWUP_SCHEDULE}")


def process_pending_followups():
    """Process all due lead follow-ups. Called by background scheduler."""
    import database as db
    import email_service as email

    pending = db.get_pending_lead_followups()
    sent_count = 0

    for fu in pending:
        # Skip if lead already converted or cold
        if fu.get("stage") in ("converted", "cold"):
            db.mark_lead_followup_sent(fu["id"])
            continue

        # Skip if no email
        if not fu.get("email"):
            continue

        try:
            email.send_lead_followup(
                to_email=fu["email"],
                lead_name=fu.get("name", ""),
                treatment_interest=fu.get("treatment_interest", ""),
                day_number=fu["day_number"],
                admin_id=fu.get("admin_id"),
            )
            db.mark_lead_followup_sent(fu["id"])
            sent_count += 1
            logger.info(f"Lead follow-up sent: lead #{fu['lead_id']}, day {fu['day_number']}")
        except Exception as e:
            logger.warning(f"Failed to send lead follow-up #{fu['id']}: {e}")

    if sent_count:
        logger.info(f"Processed {sent_count} lead follow-ups")


def on_booking_completed(admin_id, session_id, booking_id):
    """Called when a booking is completed — converts the lead if one exists."""
    import database as db
    if not session_id:
        return
    lead = db.get_lead_by_session(session_id)
    if lead and lead.get("stage") != "converted":
        db.convert_lead(lead["id"], booking_id)
        logger.info(f"Lead #{lead['id']} converted via booking #{booking_id}")


def auto_progress_stages():
    """Auto-progress lead stages. Called daily by scheduler."""
    import database as db
    conn = db.get_db()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # new -> engaged: score indicates warm+ temperature (>= 6) OR has followups sent
    conn.execute("""
        UPDATE leads SET stage='engaged', last_activity_at=%s
        WHERE stage='new' AND (
            score >= 6
            OR id IN (SELECT DISTINCT lead_id FROM lead_followups WHERE status='sent')
        )
    """, (now_str,))

    # Any uncontacted lead silent for 14+ days -> cold
    cutoff_cold = (now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        UPDATE leads SET stage='cold'
        WHERE stage IN ('new','engaged','warm')
        AND last_activity_at != '' AND last_activity_at < %s
    """, (cutoff_cold,))

    # Contacted leads go cold after 30 days of no activity
    cutoff_contacted = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        UPDATE leads SET stage='cold'
        WHERE stage = 'contacted'
        AND last_activity_at != '' AND last_activity_at < %s
    """, (cutoff_contacted,))

    conn.commit()
    conn.close()
    logger.info("Lead stage auto-progression completed")


def get_temperature_from_score(score):
    """Convert numeric score to temperature label."""
    if score < 0: return "frozen"
    if score <= 2: return "cold"
    if score <= 5: return "cool"
    if score <= 8: return "warm"
    if score <= 11: return "hot"
    if score <= 15: return "very_hot"
    return "scorching"


def queue_timed_lead_email(lead_id, admin_id, temperature):
    """Queue an outreach email based on lead temperature.
    hot/very_hot/scorching = 5 minutes, warm = 1 hour, cool = 4 hours."""
    import database as db
    now = datetime.now()

    delay_map = {
        "scorching": timedelta(minutes=5),
        "very_hot": timedelta(minutes=5),
        "hot": timedelta(minutes=5),
        "warm": timedelta(hours=1),
        "cool": timedelta(hours=4),
    }
    delay = delay_map.get(temperature)
    if not delay:
        return  # cold/frozen don't get emails

    send_at = (now + delay).strftime("%Y-%m-%d %H:%M:%S")
    db.queue_lead_email(lead_id, admin_id, send_at)
    logger.info(f"Lead #{lead_id} email queued for {send_at} (temperature={temperature})")


def process_queued_lead_emails():
    """Process all due queued lead emails. Called by background scheduler."""
    import database as db

    pending = db.get_pending_lead_emails()
    sent = 0

    for item in pending:
        if not item.get("email"):
            db.mark_lead_email_sent(item["id"])
            continue

        try:
            import email_service
            admin_id = item["admin_id"]
            ci = db.get_company_info(admin_id) or {}
            all_products = db.get_products(admin_id, status="active")
            interest = (item.get("treatment_interest") or "").lower()

            hero = None
            related = []
            if interest:
                for p in all_products:
                    pname = (p.get("product_name") or "").lower()
                    pcat = (p.get("product_category") or "").lower()
                    if interest in pname or interest in pcat:
                        if not hero:
                            hero = p
                        else:
                            related.append(p)
            if not hero and all_products:
                hero = all_products[0]
                related = all_products[1:4]

            email_service.send_lead_outreach(
                item["email"], item.get("name", "there"),
                business_name=ci.get("business_name"),
                product_interest=item.get("treatment_interest", ""),
                hero_product=hero, related_products=related[:3],
                company_info=ci, admin_id=admin_id
            )
            db.mark_lead_email_sent(item["id"])
            sent += 1
            logger.info(f"Queued lead email sent: lead #{item['lead_id']}")
        except Exception as e:
            logger.warning(f"Failed to send queued lead email #{item['id']}: {e}")
            # Mark as failed after 3 attempts to prevent infinite retry
            retry_count = item.get("retry_count", 0) or 0
            if retry_count >= 2:
                try:
                    db.mark_lead_email_failed(item["id"])
                    logger.info(f"Queued lead email #{item['id']} marked as failed after {retry_count+1} attempts")
                except Exception:
                    pass
            else:
                try:
                    db.increment_lead_email_retry(item["id"])
                except Exception:
                    pass

    if sent:
        logger.info(f"Processed {sent} queued lead emails")
