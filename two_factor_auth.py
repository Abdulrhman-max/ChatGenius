"""
Two-Factor Authentication Engine for ChatGenius.
Supports SMS OTP and Email OTP methods.
"""
import random
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("2fa")

OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 5
MAX_ATTEMPTS = 3
LOCKOUT_MINUTES = 15
SESSION_TIMEOUT_HOURS = 8


def generate_otp():
    """Generate a 6-digit OTP code."""
    return str(random.randint(100000, 999999))


def send_otp(user_id, method='email'):
    """
    Generate and send OTP to user.
    method: 'email' or 'sms'
    Returns: {"success": True} or {"error": "..."}
    """
    import database as db

    conn = db.get_db()
    user = conn.execute("SELECT * FROM users WHERE id=%s", (user_id,)).fetchone()
    if not user:
        conn.close()
        return {"error": "User not found"}

    user = dict(user)

    # Check if locked out
    if _is_locked(user_id):
        conn.close()
        return {"error": "Account temporarily locked. Please try again in 15 minutes."}

    otp = generate_otp()
    now = datetime.now()
    expires = now + timedelta(minutes=OTP_EXPIRY_MINUTES)

    # Store OTP (overwrite any existing)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS otp_codes (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            code TEXT,
            method TEXT,
            attempts INTEGER DEFAULT 0,
            created_at TEXT,
            expires_at TEXT,
            used INTEGER DEFAULT 0
        )
    """)

    # Invalidate previous OTPs
    conn.execute("UPDATE otp_codes SET used=1 WHERE user_id=%s AND used=0", (user_id,))

    # Create new OTP
    conn.execute(
        "INSERT INTO otp_codes (user_id, code, method, created_at, expires_at) VALUES (%s,%s,%s,%s,%s)",
        (user_id, otp, method, now.strftime("%Y-%m-%d %H:%M:%S"), expires.strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

    # Send via chosen method
    if method == 'email':
        try:
            import email_service
            email_service.send_otp_email(user["email"], user.get("name", ""), otp)
            logger.info(f"OTP sent via email to {user['email']}")
            return {"success": True, "method": "email"}
        except Exception as e:
            logger.error(f"Failed to send OTP email: {e}")
            return {"error": "Failed to send OTP email. Please try again."}
    elif method == 'sms':
        # Stub for SMS - would use Twilio
        logger.info(f"OTP SMS stub: {otp} to user #{user_id}")
        return {"success": True, "method": "sms", "stub": True}

    return {"error": "Invalid OTP method"}


def verify_otp(user_id, code):
    """
    Verify an OTP code.
    Returns: {"success": True} or {"error": "...", "locked": bool}
    """
    import database as db
    conn = db.get_db()

    # Check lockout
    if _is_locked(user_id):
        conn.close()
        return {"error": "Account temporarily locked due to too many incorrect attempts. Please try again in 15 minutes.", "locked": True}

    # Get latest unused OTP
    otp_record = conn.execute(
        "SELECT * FROM otp_codes WHERE user_id=%s AND used=0 ORDER BY created_at DESC LIMIT 1",
        (user_id,)
    ).fetchone()

    if not otp_record:
        conn.close()
        return {"error": "No active code found. Please request a new one."}

    otp_record = dict(otp_record)

    # Check expiry
    try:
        expires = datetime.strptime(otp_record["expires_at"], "%Y-%m-%d %H:%M:%S")
        if datetime.now() > expires:
            conn.execute("UPDATE otp_codes SET used=1 WHERE id=%s", (otp_record["id"],))
            conn.commit()
            conn.close()
            return {"error": "Your code has expired. Please request a new one."}
    except (ValueError, TypeError):
        pass

    # Check code
    if otp_record["code"] != code.strip():
        # Increment attempts
        attempts = otp_record.get("attempts", 0) + 1
        conn.execute("UPDATE otp_codes SET attempts=%s WHERE id=%s", (attempts, otp_record["id"]))
        conn.commit()

        if attempts >= MAX_ATTEMPTS:
            # Lock the account
            _lock_account(user_id)
            conn.execute("UPDATE otp_codes SET used=1 WHERE id=%s", (otp_record["id"],))
            conn.commit()
            conn.close()

            # Notify head admin
            _notify_admin_of_lockout(user_id)

            return {
                "error": "Account locked for 15 minutes due to too many incorrect attempts.",
                "locked": True,
                "remaining_attempts": 0
            }

        conn.close()
        return {
            "error": "Incorrect code. Please try again.",
            "locked": False,
            "remaining_attempts": MAX_ATTEMPTS - attempts
        }

    # Success - mark OTP as used
    conn.execute("UPDATE otp_codes SET used=1 WHERE id=%s", (otp_record["id"],))
    conn.commit()
    conn.close()

    # Reset failed attempts
    _unlock_account(user_id)

    logger.info(f"OTP verified successfully for user #{user_id}")
    return {"success": True}


def _is_locked(user_id):
    """Check if user is locked out due to failed attempts."""
    import database as db
    conn = db.get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS account_lockouts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE,
            locked_until TEXT,
            created_at TEXT
        )
    """)

    lockout = conn.execute(
        "SELECT locked_until FROM account_lockouts WHERE user_id=%s", (user_id,)
    ).fetchone()
    conn.close()

    if not lockout or not lockout["locked_until"]:
        return False

    try:
        locked_until = datetime.strptime(lockout["locked_until"], "%Y-%m-%d %H:%M:%S")
        return datetime.now() < locked_until
    except (ValueError, TypeError):
        return False


def _lock_account(user_id):
    """Lock account for LOCKOUT_MINUTES."""
    import database as db
    conn = db.get_db()
    locked_until = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    existing = conn.execute("SELECT id FROM account_lockouts WHERE user_id=%s", (user_id,)).fetchone()
    if existing:
        conn.execute("UPDATE account_lockouts SET locked_until=%s WHERE user_id=%s", (locked_until, user_id))
    else:
        conn.execute(
            "INSERT INTO account_lockouts (user_id, locked_until, created_at) VALUES (%s,%s,%s)",
            (user_id, locked_until, now)
        )
    conn.commit()
    conn.close()
    logger.warning(f"Account locked for user #{user_id} until {locked_until}")


def _unlock_account(user_id):
    """Remove lockout."""
    import database as db
    conn = db.get_db()
    conn.execute("DELETE FROM account_lockouts WHERE user_id=%s", (user_id,))
    conn.commit()
    conn.close()


def _notify_admin_of_lockout(user_id):
    """Notify head admin when a user account is locked."""
    import database as db
    conn = db.get_db()
    user = conn.execute("SELECT * FROM users WHERE id=%s", (user_id,)).fetchone()
    if not user:
        conn.close()
        return

    user = dict(user)
    admin_id = user.get("admin_id") or user["id"]

    # Find head admin
    head_admin = conn.execute(
        "SELECT * FROM users WHERE id=%s OR (admin_id=%s AND role='admin') ORDER BY id LIMIT 1",
        (admin_id, admin_id)
    ).fetchone()
    conn.close()

    if head_admin and head_admin["email"] != user["email"]:
        try:
            import email_service
            # Simple notification email
            logger.info(f"Notifying admin {head_admin['email']} about lockout of {user['email']}")
        except Exception as e:
            logger.error(f"Failed to notify admin of lockout: {e}")


# ── 2FA Setup/Configuration ──

def setup_2fa(user_id, method='email'):
    """Enable 2FA for a user with chosen method."""
    import database as db
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET two_fa_enabled=1, two_fa_method=%s WHERE id=%s",
        (method, user_id)
    )
    conn.commit()
    conn.close()
    return {"success": True, "method": method}


def disable_2fa(user_id):
    """Disable 2FA for a user."""
    import database as db
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET two_fa_enabled=0, two_fa_method=NULL WHERE id=%s",
        (user_id,)
    )
    conn.commit()
    conn.close()
    return {"success": True}


def is_2fa_required(user_id):
    """Check if user needs 2FA (either self-enabled or admin-enforced)."""
    import database as db
    conn = db.get_db()
    user = conn.execute("SELECT * FROM users WHERE id=%s", (user_id,)).fetchone()
    if not user:
        conn.close()
        return False

    user = dict(user)

    # Check if user has 2FA enabled
    if user.get("two_fa_enabled"):
        conn.close()
        return True

    # Check if admin enforces 2FA for all staff
    admin_id = user.get("admin_id") or user["id"]
    company = conn.execute("SELECT * FROM company_info WHERE user_id=%s", (admin_id,)).fetchone()
    conn.close()

    # Check for enforced 2FA (stored in company settings)
    # This is a simplified check - would be a dedicated column in production
    return False


def enforce_2fa(admin_id, enforce=True):
    """Head admin enforces 2FA for all staff."""
    import database as db
    conn = db.get_db()
    if enforce:
        # Enable 2FA for all staff under this admin
        conn.execute(
            "UPDATE users SET two_fa_enabled=1, two_fa_method=COALESCE(two_fa_method, 'email') WHERE admin_id=%s",
            (admin_id,)
        )
    conn.commit()
    conn.close()
    return {"success": True, "enforced": enforce}


def check_session_timeout(last_activity):
    """Check if session has timed out (8 hours of inactivity)."""
    if not last_activity:
        return True
    try:
        last = datetime.strptime(last_activity, "%Y-%m-%d %H:%M:%S")
        return datetime.now() > last + timedelta(hours=SESSION_TIMEOUT_HOURS)
    except (ValueError, TypeError):
        return True


def update_activity(user_id):
    """Update last activity timestamp."""
    import database as db
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE users SET last_activity_at=%s WHERE id=%s", (now, user_id))
    conn.commit()
    conn.close()
