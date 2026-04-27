"""
SMS Engine for ChatGenius — Twilio Integration.
Sends SMS for appointment reminders, booking confirmations, no-show recovery,
and general messaging.  Uses Twilio REST API.
"""
import base64
import hashlib
import logging
import os
import re
from datetime import datetime

logger = logging.getLogger("sms_engine")

# ── Token Encryption Helpers ────────────────────────────────────────────────

# Bug 4 fix: Use random runtime fallback instead of hardcoded default key
_env_key = os.environ.get("ENCRYPTION_KEY", "")
if not _env_key:
    logger.warning("[SMS] ENCRYPTION_KEY env var not set — using random runtime key. "
                   "Encrypted tokens will NOT survive restarts!")
    _ENCRYPTION_KEY = os.urandom(32).hex()
else:
    _ENCRYPTION_KEY = _env_key


def _encrypt_token(token):
    """Encrypt a token using XOR with a derived key + base64 encoding."""
    if not token:
        return token
    key = hashlib.sha256(_ENCRYPTION_KEY.encode()).digest()
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(token.encode("utf-8")))
    return "enc:" + base64.urlsafe_b64encode(encrypted).decode("utf-8")


def _decrypt_token(encrypted):
    """Decrypt a token that was encrypted with _encrypt_token."""
    if not encrypted:
        return encrypted
    if not encrypted.startswith("enc:"):
        # Legacy plaintext token — return as-is
        return encrypted
    raw = base64.urlsafe_b64decode(encrypted[4:])
    key = hashlib.sha256(_ENCRYPTION_KEY.encode()).digest()
    decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return decrypted.decode("utf-8")


# ── SMS Body Sanitization Helper (Bug 7 fix) ──────────────────────────────

def _sanitize_name(name):
    """Strip characters that aren't alphanumeric, spaces, periods, hyphens, or apostrophes.
    Truncate to 50 chars to prevent injection via long names."""
    if not name:
        return ""
    return re.sub(r"[^a-zA-Z0-9\s.\'-]", "", str(name))[:50]


# ── Twilio Client Cache (Bug 9 fix) ───────────────────────────────────────

_twilio_clients = {}  # {admin_id: (account_sid, auth_token, Client)}


def _clear_twilio_client(admin_id):
    """Remove cached Twilio client for an admin (call on config change)."""
    _twilio_clients.pop(admin_id, None)


# ── Twilio Client Helper ────────────────────────────────────────────────────

def _get_twilio_credentials(admin_id):
    """Return (account_sid, auth_token, phone_number) for the given admin.
    Checks admin-level config first, then falls back to env vars."""
    import database as db

    # Bug 6 fix: try/finally for connection leak
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT account_sid, auth_token, phone_number FROM twilio_config WHERE admin_id=%s",
            (admin_id,)
        ).fetchone()
    finally:
        conn.close()

    # Bug 5 fix: decrypt both account_sid and auth_token
    if row and row["account_sid"] and row["auth_token"] and row["phone_number"]:
        return _decrypt_token(row["account_sid"]), _decrypt_token(row["auth_token"]), row["phone_number"]

    # Fallback to environment variables
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    phone = os.getenv("TWILIO_PHONE_NUMBER", "")
    if sid and token and phone:
        return sid, token, phone

    return None, None, None


def is_configured(admin_id):
    """Check whether Twilio SMS is configured for a given admin."""
    sid, token, phone = _get_twilio_credentials(admin_id)
    return bool(sid and token and phone)


# ── Core Send ────────────────────────────────────────────────────────────────

def send_sms(to_number, message, admin_id):
    """Send a single SMS via Twilio.
    Returns dict with 'success', 'sid' (message SID), and optional 'error'."""
    import database as db

    # Bug 3 fix: Normalize and validate recipient phone number
    to_number = re.sub(r'[^\d+]', '', to_number)
    if not to_number.startswith('+'):
        to_number = '+1' + to_number  # US default
    if not re.match(r'^\+[1-9]\d{9,14}$', to_number):
        logger.warning(f"[SMS] Invalid recipient number after normalization: {to_number}")
        return {"success": False, "error": "Invalid recipient phone number"}

    sid, token, phone = _get_twilio_credentials(admin_id)
    if not sid or not token or not phone:
        logger.warning(f"[SMS] Twilio not configured for admin {admin_id}")
        return {"success": False, "error": "Twilio not configured"}

    try:
        from twilio.rest import Client

        # Bug 9 fix: Cache Twilio Client per admin_id
        cached = _twilio_clients.get(admin_id)
        if cached and cached[0] == sid and cached[1] == token:
            client = cached[2]
        else:
            client = Client(sid, token)
            _twilio_clients[admin_id] = (sid, token, client)

        msg = client.messages.create(
            body=message,
            from_=phone,
            to=to_number,
        )
        logger.info(f"[SMS] Sent to {to_number}, SID={msg.sid}")

        # Log to sms_log table
        _log_sms(admin_id, to_number, message, "sent", msg.sid)

        return {"success": True, "sid": msg.sid}

    except Exception as e:
        logger.error(f"[SMS] Failed to send to {to_number}: {e}")
        _log_sms(admin_id, to_number, message, "failed", error=str(e))
        return {"success": False, "error": "Failed to send SMS. Please check your Twilio configuration."}


def _log_sms(admin_id, to_number, message, status, sid="", error=""):
    """Insert a row into sms_log for tracking."""
    import database as db

    # Bug 8 fix: Truncate message to 50 chars to avoid PII retention
    truncated_message = (message[:50] + "...") if len(message) > 50 else message

    # Bug 6 fix: try/finally for connection leak
    conn = db.get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO sms_log (admin_id, to_number, message, status, twilio_sid, error, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (admin_id, to_number, truncated_message, status, sid, error, now)
        )
        conn.commit()
    finally:
        conn.close()


# ── Appointment Reminder SMS ────────────────────────────────────────────────

def send_appointment_reminder_sms(booking_id):
    """Send an appointment reminder as SMS. Returns True/False."""
    import database as db

    booking = db.get_booking_by_id(booking_id)
    if not booking:
        logger.warning(f"[SMS] Booking {booking_id} not found for reminder SMS")
        return False

    phone = booking.get("customer_phone", "")
    if not phone:
        logger.info(f"[SMS] No phone for booking {booking_id}, skipping SMS reminder")
        return False

    admin_id = booking.get("admin_id", 0)
    if not is_configured(admin_id):
        return False

    # Bug 7 fix: Sanitize user-supplied names
    customer_name = _sanitize_name(booking.get("customer_name", ""))
    date_display = booking.get("date", "")
    time_display = booking.get("time", "")
    doctor_name = _sanitize_name(booking.get("doctor_name", ""))

    message = (
        f"Hi {customer_name}, this is a reminder about your appointment"
        f"{f' with Dr. {doctor_name}' if doctor_name else ''} "
        f"on {date_display} at {time_display}. "
        f"Reply CONFIRM to confirm or call us to reschedule."
    )

    result = send_sms(phone, message, admin_id)
    return result.get("success", False)


# ── Booking Confirmation SMS ────────────────────────────────────────────────

def send_booking_confirmation_sms(booking_id):
    """Send a booking confirmation SMS. Returns True/False."""
    import database as db

    booking = db.get_booking_by_id(booking_id)
    if not booking:
        logger.warning(f"[SMS] Booking {booking_id} not found for confirmation SMS")
        return False

    phone = booking.get("customer_phone", "")
    if not phone:
        return False

    admin_id = booking.get("admin_id", 0)
    if not is_configured(admin_id):
        return False

    # Bug 7 fix: Sanitize user-supplied names
    customer_name = _sanitize_name(booking.get("customer_name", ""))
    date_display = booking.get("date", "")
    time_display = booking.get("time", "")
    doctor_name = _sanitize_name(booking.get("doctor_name", ""))
    service_name = _sanitize_name(booking.get("service", ""))

    message = (
        f"Hi {customer_name}, your appointment"
        f"{f' for {service_name}' if service_name else ''}"
        f"{f' with Dr. {doctor_name}' if doctor_name else ''} "
        f"is confirmed for {date_display} at {time_display}. "
        f"See you then!"
    )

    result = send_sms(phone, message, admin_id)
    return result.get("success", False)


# ── No-Show Recovery SMS ────────────────────────────────────────────────────

def send_noshow_recovery_sms(booking_id):
    """Send a no-show recovery link via SMS. Returns True/False."""
    import database as db

    booking = db.get_booking_by_id(booking_id)
    if not booking:
        return False

    phone = booking.get("customer_phone", "")
    if not phone:
        return False

    admin_id = booking.get("admin_id", 0)
    if not is_configured(admin_id):
        return False

    # Bug 7 fix: Sanitize user-supplied names
    customer_name = _sanitize_name(booking.get("customer_name", ""))
    booking_url = f"{os.getenv('BASE_URL', 'http://localhost:8080')}/book/{admin_id}"

    message = (
        f"Hi {customer_name}, we missed you at your appointment today. "
        f"We hope everything is okay! You can easily reschedule here: {booking_url}"
    )

    result = send_sms(phone, message, admin_id)
    return result.get("success", False)


# ── SMS Stats ───────────────────────────────────────────────────────────────

def get_sms_stats(admin_id):
    """Return SMS usage stats: total sent, delivered, failed."""
    import database as db

    # Bug 6 fix: try/finally for connection leak
    conn = db.get_db()
    try:
        total = conn.execute(
            "SELECT COUNT(*) as c FROM sms_log WHERE admin_id=%s", (admin_id,)
        ).fetchone()["c"]
        sent = conn.execute(
            "SELECT COUNT(*) as c FROM sms_log WHERE admin_id=%s AND status='sent'", (admin_id,)
        ).fetchone()["c"]
        failed = conn.execute(
            "SELECT COUNT(*) as c FROM sms_log WHERE admin_id=%s AND status='failed'", (admin_id,)
        ).fetchone()["c"]
    finally:
        conn.close()

    return {
        "total": total,
        "sent": sent,
        "failed": failed,
        "delivery_rate": round(sent / total * 100, 1) if total > 0 else 0,
    }


# ── Configuration Management ────────────────────────────────────────────────

def save_twilio_config(admin_id, account_sid, auth_token, phone_number):
    """Save or update Twilio credentials for an admin."""
    import database as db

    # Bug 5 fix: Encrypt both account_sid and auth_token
    encrypted_sid = _encrypt_token(account_sid)
    encrypted_token = _encrypt_token(auth_token)

    # Bug 6 fix: try/finally for connection leak
    conn = db.get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM twilio_config WHERE admin_id=%s", (admin_id,)
        ).fetchone()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if existing:
            conn.execute(
                """UPDATE twilio_config SET account_sid=%s, auth_token=%s, phone_number=%s, updated_at=%s
                   WHERE admin_id=%s""",
                (encrypted_sid, encrypted_token, phone_number, now, admin_id)
            )
        else:
            conn.execute(
                """INSERT INTO twilio_config (admin_id, account_sid, auth_token, phone_number, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (admin_id, encrypted_sid, encrypted_token, phone_number, now, now)
            )
        conn.commit()
    finally:
        conn.close()

    # Bug 9 fix: Clear cached client when credentials change
    _clear_twilio_client(admin_id)
    logger.info(f"[SMS] Twilio config saved for admin {admin_id}")


def delete_twilio_config(admin_id):
    """Remove Twilio credentials for an admin (disconnect)."""
    import database as db

    # Bug 6 fix: try/finally for connection leak
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM twilio_config WHERE admin_id=%s", (admin_id,))
        conn.commit()
    finally:
        conn.close()

    # Bug 9 fix: Clear cached client on disconnect
    _clear_twilio_client(admin_id)
    logger.info(f"[SMS] Twilio config deleted for admin {admin_id}")


def test_sms(admin_id, to_number):
    """Send a test SMS to verify configuration. Returns result dict."""
    if not is_configured(admin_id):
        return {"success": False, "error": "Twilio not configured. Please save your credentials first."}

    message = "This is a test message from ChatGenius. Your Twilio SMS integration is working correctly!"
    return send_sms(to_number, message, admin_id)
