"""
No-Show Recovery Engine for ChatGenius.
Automatically reaches out to no-show patients with empathetic messaging,
offers rescheduling, and tracks recovery metrics.
"""
import logging
import os
import secrets
from datetime import datetime, timedelta

logger = logging.getLogger("noshow_recovery")

BASE_URL = os.getenv("BASE_URL", "http://localhost:8080")


# ── No-Show Detection Hook ──────────────────────────────────────────────────

def on_noshow_detected(booking_id):
    """Called when a booking is marked as no-show.
    Looks up patient no-show count, creates recovery record,
    and schedules a recovery message (15 min delay)."""
    import database as db

    booking = db.get_booking_by_id(booking_id)
    if not booking:
        logger.warning(f"No-show recovery: booking {booking_id} not found")
        return None

    admin_id = booking.get("admin_id", 0)
    patient_id = booking.get("patient_id", 0)

    # Get patient no-show count
    noshow_count = 1
    if patient_id:
        conn = db.get_db()
        patient = conn.execute("SELECT total_no_shows FROM patients WHERE id=?", (patient_id,)).fetchone()
        if patient:
            noshow_count = patient["total_no_shows"] or 1
        conn.close()

    # Get policy for delay
    policy = db.get_noshow_policy(admin_id)
    if not policy or not policy.get("auto_recovery_enabled", 1):
        logger.info(f"No-show recovery: auto-recovery disabled for admin {admin_id}")
        return None

    delay_minutes = policy.get("recovery_delay_minutes", 15)

    # Create recovery record
    reschedule_token = secrets.token_urlsafe(32)
    cancel_token = secrets.token_urlsafe(32)

    recovery_id = db.create_noshow_recovery(
        booking_id=booking_id,
        patient_id=patient_id,
        admin_id=admin_id,
        reschedule_token=reschedule_token,
        cancel_token=cancel_token,
        noshow_count=noshow_count,
    )

    logger.info(f"No-show recovery: created recovery {recovery_id} for booking {booking_id} "
                f"(patient noshow count: {noshow_count}, delay: {delay_minutes}m)")

    # Schedule the recovery message
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        import background_tasks
        if background_tasks._scheduler:
            run_date = datetime.now() + timedelta(minutes=delay_minutes)
            background_tasks._scheduler.add_job(
                send_recovery_message,
                "date",
                run_date=run_date,
                args=[recovery_id],
                id=f"noshow_recovery_{recovery_id}",
                replace_existing=True,
                name=f"No-show recovery message for recovery {recovery_id}",
            )
            logger.info(f"No-show recovery: message scheduled for {run_date}")
    except Exception as e:
        logger.warning(f"No-show recovery: could not schedule message, sending now: {e}")
        send_recovery_message(recovery_id)

    return recovery_id


# ── Send Recovery Message ────────────────────────────────────────────────────

def send_recovery_message(recovery_id):
    """Send empathetic email to the no-show patient offering rescheduling."""
    import database as db
    import email_service as email_svc

    conn = db.get_db()
    recovery = conn.execute("SELECT * FROM noshow_recovery WHERE id=?", (recovery_id,)).fetchone()
    if not recovery:
        conn.close()
        logger.warning(f"No-show recovery: recovery {recovery_id} not found")
        return False

    recovery = dict(recovery)
    if recovery["recovery_status"] != "pending":
        conn.close()
        logger.info(f"No-show recovery: recovery {recovery_id} already {recovery['recovery_status']}")
        return False

    booking = db.get_booking_by_id(recovery["booking_id"])
    if not booking:
        conn.close()
        return False

    patient_email = booking.get("customer_email", "")
    patient_name = booking.get("customer_name", "Patient")

    if not patient_email:
        conn.close()
        logger.warning(f"No-show recovery: no email for booking {recovery['booking_id']}")
        return False

    reschedule_url = f"{BASE_URL}/api/noshow-recovery/reschedule/{recovery['reschedule_token']}"
    cancel_url = f"{BASE_URL}/api/noshow-recovery/cancel/{recovery['cancel_token']}"

    # Send the email
    subject = "We missed you today — would you like to reschedule?"
    html_body = _build_recovery_email(patient_name, booking, reschedule_url, cancel_url)

    try:
        sent = email_svc._send_email(patient_email, subject, html_body)
    except Exception as e:
        logger.error(f"No-show recovery: email send error: {e}")
        sent = False

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if sent:
        conn.execute("UPDATE noshow_recovery SET recovery_status='sent', message_sent_at=? WHERE id=?",
                      (now, recovery_id))
    else:
        conn.execute("UPDATE noshow_recovery SET recovery_status='send_failed' WHERE id=?", (recovery_id,))

    conn.commit()
    conn.close()
    logger.info(f"No-show recovery: message {'sent' if sent else 'failed'} for recovery {recovery_id}")
    return sent


def _build_recovery_email(patient_name, booking, reschedule_url, cancel_url):
    """Build empathetic HTML email for no-show recovery."""
    date_display = booking.get("date", "")
    time_display = booking.get("time", "")
    doctor_name = booking.get("doctor_name", "your doctor")
    service = booking.get("service", "your appointment")

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f0f0;padding:40px 20px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.1);">
<tr><td style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:40px 40px 30px;text-align:center;">
    <h1 style="color:#fff;margin:0;font-size:24px;font-weight:600;">We Missed You</h1>
    <p style="color:rgba(255,255,255,0.85);margin:10px 0 0;font-size:15px;">We hope everything is okay</p>
</td></tr>
<tr><td style="padding:40px;">
    <p style="color:#333;font-size:16px;line-height:1.6;margin:0 0 20px;">
        Hi <strong>{patient_name}</strong>,
    </p>
    <p style="color:#555;font-size:15px;line-height:1.6;margin:0 0 20px;">
        We noticed you missed your appointment for <strong>{service}</strong>
        {f'with Dr. {doctor_name}' if doctor_name and doctor_name != 'your doctor' else ''}
        on <strong>{date_display}</strong> at <strong>{time_display}</strong>.
    </p>
    <p style="color:#555;font-size:15px;line-height:1.6;margin:0 0 30px;">
        We understand that things come up. Would you like to reschedule at a time that works better for you?
    </p>
    <div style="text-align:center;margin:30px 0;">
        <a href="{reschedule_url}" style="display:inline-block;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:14px 40px;border-radius:30px;text-decoration:none;font-weight:600;font-size:15px;margin:0 8px;">
            Reschedule Appointment
        </a>
    </div>
    <p style="text-align:center;margin:20px 0 0;">
        <a href="{cancel_url}" style="color:#999;font-size:13px;text-decoration:underline;">
            No thanks, I don't need to reschedule
        </a>
    </p>
</td></tr>
</table>
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;margin-top:24px;">
<tr><td style="text-align:center;padding:0 20px;">
    <p style="color:#999;font-size:12px;line-height:1.5;margin:0;">
        Powered by <strong style="color:#777;">ChatGenius AI</strong><br>
        <span style="color:#bbb;">Please do not reply to this email.</span>
    </p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


# ── Token Handlers ───────────────────────────────────────────────────────────

def handle_reschedule(token):
    """Look up recovery by reschedule token, return booking info for rescheduling flow."""
    import database as db

    recovery = db.get_recovery_by_token(token, "reschedule")
    if not recovery:
        return None

    if recovery["recovery_status"] in ("expired", "cancelled", "rescheduled"):
        return {"error": "This link has expired or already been used."}

    booking = db.get_booking_by_id(recovery["booking_id"])
    if not booking:
        return {"error": "Original booking not found."}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.update_recovery_status(recovery["id"], "rescheduling", responded_at=now)

    return {
        "recovery_id": recovery["id"],
        "booking": booking,
        "patient_id": recovery["patient_id"],
        "admin_id": recovery["admin_id"],
    }


def handle_cancel_recovery(token):
    """Mark recovery as expired (patient declined to reschedule)."""
    import database as db

    recovery = db.get_recovery_by_token(token, "cancel")
    if not recovery:
        return None

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.update_recovery_status(recovery["id"], "expired", responded_at=now)

    return {"status": "expired", "message": "Recovery cancelled. We hope to see you soon!"}


# ── Deposit Check ────────────────────────────────────────────────────────────

def check_deposit_required(patient_id, admin_id):
    """Return True if patient has reached the max no-show threshold for deposit requirement."""
    import database as db

    policy = db.get_noshow_policy(admin_id)
    max_noshows = policy.get("max_noshows_before_deposit", 2) if policy else 2

    conn = db.get_db()
    patient = conn.execute("SELECT total_no_shows FROM patients WHERE id=?", (patient_id,)).fetchone()
    conn.close()

    if not patient:
        return False

    return (patient["total_no_shows"] or 0) >= max_noshows


# ── Recovery Stats ───────────────────────────────────────────────────────────

def get_recovery_stats(admin_id):
    """Return recovery rate, revenue recovered, and flagged patients."""
    import database as db
    return db.get_recovery_stats(admin_id)


# ── Expired Recovery Cleanup ─────────────────────────────────────────────────

def process_expired_recoveries():
    """Mark recoveries older than 2 hours as expired. Called by background task."""
    import database as db

    conn = db.get_db()
    cutoff = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    result = conn.execute(
        """UPDATE noshow_recovery SET recovery_status='expired'
           WHERE recovery_status IN ('pending', 'sent') AND created_at < ?""",
        (cutoff,)
    )
    count = result.rowcount
    conn.commit()
    conn.close()

    if count > 0:
        logger.info(f"No-show recovery: expired {count} stale recovery records")
    return count


# ── Policy Management ────────────────────────────────────────────────────────

def get_policy(admin_id):
    """Get no-show policy for an admin."""
    import database as db
    return db.get_noshow_policy(admin_id)


def save_policy(admin_id, **kwargs):
    """Save/update no-show policy for an admin."""
    import database as db
    return db.save_noshow_policy(admin_id, **kwargs)
