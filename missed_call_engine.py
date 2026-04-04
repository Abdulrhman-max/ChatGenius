"""
Missed Call Auto-Reply Engine for ChatGenius.
When nobody answers a clinic call, auto-sends SMS + WhatsApp with booking link.
Uses Twilio (stubbed for now).
"""
import logging
from datetime import datetime

logger = logging.getLogger("missed_calls")


def handle_missed_call(admin_id, caller_number, call_time=None):
    """
    Process a missed call. Called from webhook.
    1. Log the missed call
    2. Determine if within business hours
    3. Send appropriate auto-reply
    Returns: {"logged": True, "reply_sent": True/False}
    """
    import database as db

    if not call_time:
        call_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Check if feature is enabled
    conn = db.get_db()
    company = conn.execute("SELECT * FROM company_info WHERE user_id=?", (admin_id,)).fetchone()
    conn.close()

    if not company:
        return {"logged": False, "error": "Clinic not found"}

    company = dict(company)
    if not company.get("missed_call_enabled"):
        return {"logged": False, "error": "Missed call feature is disabled"}

    # Log the call
    conn = db.get_db()
    conn.execute(
        "INSERT INTO missed_calls (admin_id, caller_number, call_time, reply_sent, reply_method, created_at) VALUES (?,?,?,0,'',?)",
        (admin_id, caller_number, call_time, call_time)
    )
    conn.commit()
    call_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    # Determine message based on business hours
    business_name = company.get("business_name", "our clinic")
    booking_url = f"https://chatgenius.com/book/{admin_id}"

    is_open = _is_within_business_hours(company.get("business_hours", ""))

    if is_open:
        message = (
            f"Hi! Sorry we missed your call at {business_name}. "
            f"You can book an appointment instantly here: {booking_url}. "
            f"We'll also call you back as soon as possible."
        )
    else:
        message = (
            f"Hi! We are currently closed at {business_name}. "
            f"Book your appointment here and we will confirm it first thing tomorrow: {booking_url}"
        )

    # Send reply
    sent = _send_sms(caller_number, message)

    # Update log
    conn = db.get_db()
    conn.execute(
        "UPDATE missed_calls SET reply_sent=?, reply_method=? WHERE id=?",
        (1 if sent else 0, "sms" if sent else "", call_id)
    )
    conn.commit()
    conn.close()

    logger.info(f"Missed call from {caller_number} for admin #{admin_id}, reply_sent={sent}")
    return {"logged": True, "reply_sent": sent, "call_id": call_id}


def _is_within_business_hours(hours_str):
    """Check if current time is within business hours. Simple heuristic."""
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()

    # Default: Mon-Fri 9am-5pm, Sat 9am-1pm, Sun closed
    if weekday == 6:  # Sunday
        return False
    if weekday == 5:  # Saturday
        return 9 <= hour < 13
    return 9 <= hour < 17


def _send_sms(phone_number, message):
    """
    Send SMS via Twilio (STUBBED).
    Replace this with actual Twilio integration when ready.
    """
    # STUB: Log the message that would be sent
    logger.info(f"[SMS STUB] To: {phone_number}, Message: {message[:80]}...")

    # In production, this would be:
    # from twilio.rest import Client
    # client = Client(TWILIO_SID, TWILIO_TOKEN)
    # client.messages.create(body=message, from_=TWILIO_NUMBER, to=phone_number)

    return True  # Stub always succeeds


def mark_as_booked(call_id, booking_id):
    """Mark a missed call as subsequently booked."""
    import database as db
    conn = db.get_db()
    conn.execute(
        "UPDATE missed_calls SET subsequently_booked=1, booking_id=? WHERE id=?",
        (booking_id, call_id)
    )
    conn.commit()
    conn.close()


def get_missed_calls(admin_id, limit=50):
    """Get missed call log for dashboard."""
    import database as db
    conn = db.get_db()
    calls = conn.execute(
        "SELECT * FROM missed_calls WHERE admin_id=? ORDER BY call_time DESC LIMIT ?",
        (admin_id, limit)
    ).fetchall()
    conn.close()
    return [dict(c) for c in calls]


def get_missed_call_stats(admin_id):
    """Get missed call statistics."""
    import database as db
    conn = db.get_db()

    total = conn.execute("SELECT COUNT(*) as c FROM missed_calls WHERE admin_id=?", (admin_id,)).fetchone()["c"]
    replied = conn.execute("SELECT COUNT(*) as c FROM missed_calls WHERE admin_id=? AND reply_sent=1", (admin_id,)).fetchone()["c"]
    booked = conn.execute("SELECT COUNT(*) as c FROM missed_calls WHERE admin_id=? AND subsequently_booked=1", (admin_id,)).fetchone()["c"]

    conn.close()
    return {
        "total_missed": total,
        "replies_sent": replied,
        "converted_to_booking": booked,
        "conversion_rate": round(booked / total * 100, 1) if total > 0 else 0
    }


def toggle_feature(admin_id, enabled):
    """Enable or disable missed call auto-reply."""
    import database as db
    conn = db.get_db()
    conn.execute("UPDATE company_info SET missed_call_enabled=? WHERE user_id=?", (1 if enabled else 0, admin_id))
    conn.commit()
    conn.close()
    return {"enabled": enabled}
