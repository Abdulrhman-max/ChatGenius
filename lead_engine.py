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
    """Calculate a lead score from 1-10 based on available data."""
    score = 1  # base score

    ti_lower = (treatment_interest or "").lower()
    conv_lower = (conversation_text or "").lower()

    # Treatment value
    if any(t in ti_lower or t in conv_lower for t in HIGH_VALUE_TREATMENTS):
        score += 3
    elif any(t in ti_lower or t in conv_lower for t in MEDIUM_VALUE_TREATMENTS):
        score += 2
    else:
        score += 1

    # Returning patient
    if is_returning:
        score += 2

    # Contact info completeness
    if email:
        score += 1
    if phone:
        score += 1

    # Engagement level
    if message_count >= 3:
        score += 1

    # Urgency signals
    if any(kw in conv_lower for kw in URGENCY_KEYWORDS):
        score += 1

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
    """Auto-capture a lead from a chatbot session. Returns lead_id or None."""
    import database as db

    data = session.get("data", {})
    name = (session.get("_prefill_name") or data.get("name") or
            data.get("waitlist_name") or "").strip()
    email = (session.get("_prefill_email") or data.get("email") or
             data.get("waitlist_email") or "").strip()
    phone = (session.get("_prefill_phone") or data.get("phone") or
             data.get("waitlist_phone") or "").strip()

    if not name and not phone and not email:
        return None  # Not enough info to create a lead

    session_id = session.get("_session_id", "")

    # Don't create duplicate leads for the same session
    if session_id:
        existing = db.get_lead_by_session(session_id)
        if existing:
            return existing["id"]

    # Extract treatment interest from conversation history
    history = session.get("history", [])
    treatment = data.get("treatment_interest", "") or extract_treatment_interest(history)

    is_returning = 1 if session.get("_patient_recognized") else 0
    preferred_time = data.get("preferred_time", "")

    # Calculate score
    lead_score = score_lead(
        name=name, phone=phone, email=email,
        treatment_interest=treatment, is_returning=bool(is_returning),
        message_count=len(history),
        conversation_text=" ".join(str(m) for m in history),
    )

    lead_id = db.save_lead_enriched(
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
    )

    db.update_lead_score(lead_id, lead_score)

    # Create follow-up sequence if we have an email
    if email:
        create_followup_sequence(lead_id, admin_id)

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

    # new -> engaged: has followups sent and score >= 5
    conn.execute("""
        UPDATE leads SET stage='engaged', last_activity_at=?
        WHERE stage='new' AND score >= 5
        AND id IN (SELECT DISTINCT lead_id FROM lead_followups WHERE status='sent')
    """, (now_str,))

    # Any lead silent for 14+ days -> cold
    cutoff_cold = (now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        UPDATE leads SET stage='cold'
        WHERE stage IN ('new','engaged','warm')
        AND last_activity_at != '' AND last_activity_at < ?
    """, (cutoff_cold,))

    conn.commit()
    conn.close()
    logger.info("Lead stage auto-progression completed")
