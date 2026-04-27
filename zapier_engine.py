"""
Zapier Webhook Integration Engine for ChatGenius.
Sends event data to configured Zapier webhook URLs when
bookings, leads, patients, no-shows, and forms are triggered.
"""
import logging
import json
import socket
import threading
import ipaddress
from datetime import datetime
from urllib.parse import urlparse

import requests as http_requests
import database as db

logger = logging.getLogger("zapier_engine")

# Supported event types
EVENT_TYPES = [
    "new_booking",
    "booking_cancelled",
    "booking_completed",
    "new_lead",
    "new_patient",
    "no_show",
    "form_submitted",
]


# ── URL validation ─────────────────────────────────────────────

def _validate_webhook_url(url):
    """Validate that webhook URL is safe (HTTPS, no private/internal hosts).
    Returns (True, '') on success or (False, reason) on failure."""
    if not url:
        return False, "URL is empty"
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format"
    if parsed.scheme != "https":
        return False, "Only HTTPS webhook URLs are allowed"
    hostname = parsed.hostname or ""
    if not hostname:
        return False, "URL has no hostname"
    # Block localhost and common internal hostnames
    blocked_hostnames = {"localhost", "internal", "metadata", "metadata.google.internal"}
    if hostname.lower() in blocked_hostnames:
        return False, f"Blocked hostname: {hostname}"
    # Check for private/reserved IP addresses (literal IPs)
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return False, f"Private/reserved IP not allowed: {hostname}"
    except ValueError:
        # Not an IP literal — resolve the hostname and check each IP
        pass
    # DNS rebinding protection: resolve hostname and check all IPs
    try:
        addrinfos = socket.getaddrinfo(hostname, None)
        for family, _type, _proto, _canonname, sockaddr in addrinfos:
            ip_str = sockaddr[0]
            addr = ipaddress.ip_address(ip_str)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return False, f"Hostname {hostname} resolves to private/reserved IP: {ip_str}"
    except socket.gaierror:
        return False, f"Could not resolve hostname: {hostname}"
    return True, ""


# ── Webhook configuration helpers ──────────────────────────────

_tables_created = False
_table_lock = threading.Lock()

def _ensure_table():
    """Create zapier tables if they don't exist (thread-safe)."""
    global _tables_created
    if _tables_created:
        return
    with _table_lock:
        if _tables_created:
            return
        conn = db.get_db()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS zapier_config (
                id SERIAL PRIMARY KEY,
                admin_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                webhook_url TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(admin_id, event_type)
            );
            CREATE TABLE IF NOT EXISTS webhook_logs (
                id SERIAL PRIMARY KEY,
                admin_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                webhook_url TEXT DEFAULT '',
                status_code INTEGER DEFAULT 0,
                response_body TEXT DEFAULT '',
                payload TEXT DEFAULT '',
                error TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.close()
        _tables_created = True


def get_config(admin_id):
    """Return all zapier webhook configs for an admin."""
    _ensure_table()
    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM zapier_config WHERE admin_id=%s ORDER BY event_type",
            (admin_id,)
        ).fetchall()
        return [_serialize_dict(dict(r)) for r in rows]
    finally:
        conn.close()


def save_config(admin_id, event_type, webhook_url):
    """Save or update a webhook URL for a specific event type."""
    valid, reason = _validate_webhook_url(webhook_url)
    if not valid:
        raise ValueError(f"Invalid webhook URL: {reason}")
    _ensure_table()
    conn = db.get_db()
    try:
        conn.execute(
            """INSERT INTO zapier_config (admin_id, event_type, webhook_url, is_active)
               VALUES (%s, %s, %s, 1)
               ON CONFLICT(admin_id, event_type) DO UPDATE SET webhook_url=%s, is_active=1""",
            (admin_id, event_type, webhook_url, webhook_url)
        )
        conn.commit()
    finally:
        conn.close()


def remove_config(admin_id, event_type=None):
    """Remove webhook config. If event_type is None, remove all for admin."""
    _ensure_table()
    conn = db.get_db()
    try:
        if event_type:
            conn.execute(
                "DELETE FROM zapier_config WHERE admin_id=%s AND event_type=%s",
                (admin_id, event_type)
            )
        else:
            conn.execute("DELETE FROM zapier_config WHERE admin_id=%s", (admin_id,))
        conn.commit()
    finally:
        conn.close()


def get_webhook_url(admin_id, event_type):
    """Get the webhook URL for a specific event type, or None."""
    _ensure_table()
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT webhook_url FROM zapier_config WHERE admin_id=%s AND event_type=%s AND is_active=1",
            (admin_id, event_type)
        ).fetchone()
        return row["webhook_url"] if row else None
    finally:
        conn.close()


def _serialize_dict(d):
    """Convert datetime values in a dict to ISO format strings for JSON serialization."""
    result = {}
    for k, v in d.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def _mask_url(url):
    """Mask a webhook URL to hide embedded secrets. Show only host and first path segment."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        path_parts = parsed.path.strip("/").split("/")
        masked_path = path_parts[0] if path_parts and path_parts[0] else ""
        return f"{parsed.scheme}://{parsed.hostname}/{masked_path}/***"
    except Exception:
        return "***"


def get_logs(admin_id, limit=50):
    """Return recent webhook delivery logs (without full webhook URLs)."""
    _ensure_table()
    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT id, admin_id, event_type, status_code, response_body, payload, error, created_at "
            "FROM webhook_logs WHERE admin_id=%s ORDER BY created_at DESC LIMIT %s",
            (admin_id, limit)
        ).fetchall()
        return [_serialize_dict(dict(r)) for r in rows]
    finally:
        conn.close()


def _log_delivery(admin_id, event_type, webhook_url, status_code, response_body, payload, error=""):
    """Log a webhook delivery attempt."""
    conn = None
    try:
        masked_url = _mask_url(webhook_url)
        conn = db.get_db()
        conn.execute(
            """INSERT INTO webhook_logs (admin_id, event_type, webhook_url, status_code, response_body, payload, error)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (admin_id, event_type, masked_url, status_code,
             str(response_body)[:500], json.dumps(payload)[:2000], str(error)[:500])
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"[zapier] Failed to log delivery: {e}")
    finally:
        if conn:
            conn.close()


# ── Event formatters ───────────────────────────────────────────

def format_booking_event(booking):
    """Format booking data for webhook payload."""
    return {
        "booking_id": booking.get("id", ""),
        "patient_name": booking.get("customer_name", ""),
        "patient_email": booking.get("customer_email", ""),
        "patient_phone": booking.get("customer_phone", ""),
        "date": booking.get("date", ""),
        "time": booking.get("time", ""),
        "service": booking.get("service", ""),
        "doctor_name": booking.get("doctor_name", ""),
        "doctor_id": booking.get("doctor_id", ""),
        "status": booking.get("status", ""),
        "notes": booking.get("notes", ""),
        "created_at": booking.get("created_at", ""),
    }


def format_lead_event(lead):
    """Format lead data for webhook payload."""
    return {
        "lead_id": lead.get("id", ""),
        "name": lead.get("name", ""),
        "phone": lead.get("phone", ""),
        "email": lead.get("email", ""),
        "source": lead.get("source", ""),
        "score": lead.get("score", 0),
        "stage": lead.get("stage", "new"),
        "treatment_interest": lead.get("treatment_interest", ""),
        "capture_trigger": lead.get("capture_trigger", ""),
        "created_at": lead.get("created_at", ""),
    }


def format_patient_event(patient):
    """Format patient data for webhook payload."""
    return {
        "patient_id": patient.get("id", ""),
        "name": patient.get("name", ""),
        "email": patient.get("email", ""),
        "phone": patient.get("phone", ""),
        "total_bookings": patient.get("total_bookings", 0),
        "total_completed": patient.get("total_completed", 0),
        "last_visit_date": patient.get("last_visit_date", ""),
        "created_at": patient.get("created_at", ""),
    }


# ── Core webhook sender ───────────────────────────────────────

def send_webhook(event_type, data, admin_id):
    """Send event data to the configured Zapier webhook URL.
    Fire-and-forget: catches all exceptions so it never breaks the main flow.
    Returns True if sent successfully, False otherwise."""
    try:
        url = get_webhook_url(admin_id, event_type)
        if not url:
            return False

        valid, reason = _validate_webhook_url(url)
        if not valid:
            logger.warning(f"[zapier] Blocked unsafe webhook URL for {event_type}: {reason}")
            return False

        payload = {
            "event": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        }

        resp = http_requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=5,
            allow_redirects=False,
        )

        if 300 <= resp.status_code < 400:
            logger.warning(f"[zapier] Blocked redirect ({resp.status_code}) for {event_type}")
            _log_delivery(
                admin_id, event_type, url,
                resp.status_code, "Redirect blocked", payload, "Redirect not followed"
            )
            return False

        _log_delivery(
            admin_id, event_type, url,
            resp.status_code, resp.text[:500], payload
        )

        return 200 <= resp.status_code < 300

    except Exception as e:
        logger.warning(f"[zapier] Webhook failed for {event_type}: {e}")
        try:
            _log_delivery(admin_id, event_type, url or "", 0, "", data, str(e))
        except Exception:
            pass
        return False


def send_test_webhook(admin_id, event_type=None):
    """Send a test webhook with sample data. If event_type is None, tests all configured."""
    sample_data = {
        "new_booking": {
            "booking_id": 999,
            "patient_name": "Test Patient",
            "patient_email": "test@example.com",
            "patient_phone": "(555) 123-4567",
            "date": "2026-04-25",
            "time": "10:00 AM - 10:30 AM",
            "service": "General Consultation",
            "doctor_name": "Dr. Test",
            "status": "confirmed",
        },
        "booking_cancelled": {
            "booking_id": 999,
            "patient_name": "Test Patient",
            "date": "2026-04-25",
            "time": "10:00 AM - 10:30 AM",
            "reason": "Patient requested cancellation",
        },
        "booking_completed": {
            "booking_id": 999,
            "patient_name": "Test Patient",
            "date": "2026-04-25",
            "time": "10:00 AM - 10:30 AM",
            "outcome": "Successful",
        },
        "new_lead": {
            "lead_id": 999,
            "name": "Test Lead",
            "phone": "(555) 987-6543",
            "email": "lead@example.com",
            "source": "chatbot",
            "score": 7,
            "treatment_interest": "teeth whitening",
        },
        "new_patient": {
            "patient_id": 999,
            "name": "Test Patient",
            "email": "patient@example.com",
            "phone": "(555) 111-2222",
            "total_bookings": 1,
        },
        "no_show": {
            "booking_id": 999,
            "patient_name": "Test Patient",
            "date": "2026-04-25",
            "time": "10:00 AM - 10:30 AM",
            "doctor_name": "Dr. Test",
        },
        "form_submitted": {
            "form_id": 999,
            "patient_name": "Test Patient",
            "booking_id": 999,
            "submitted_at": datetime.now().isoformat(),
        },
    }

    results = {}
    types_to_test = [event_type] if event_type else EVENT_TYPES

    for et in types_to_test:
        url = get_webhook_url(admin_id, et)
        if not url:
            results[et] = {"status": "skipped", "reason": "not configured"}
            continue
        data = sample_data.get(et, {"test": True})
        ok = send_webhook(et, data, admin_id)
        results[et] = {"status": "success" if ok else "failed", "url": _mask_url(url)}

    return results


# ── Trigger helpers (called from app.py flows) ─────────────────

def trigger_new_booking(admin_id, booking_dict):
    """Fire webhook for a new booking. Non-blocking."""
    try:
        data = format_booking_event(booking_dict)
        send_webhook("new_booking", data, admin_id)
    except Exception:
        pass


def trigger_booking_cancelled(admin_id, booking_dict, reason=""):
    """Fire webhook for a cancelled booking."""
    try:
        data = format_booking_event(booking_dict)
        data["cancellation_reason"] = reason
        send_webhook("booking_cancelled", data, admin_id)
    except Exception:
        pass


def trigger_booking_completed(admin_id, booking_dict):
    """Fire webhook for a completed booking."""
    try:
        data = format_booking_event(booking_dict)
        send_webhook("booking_completed", data, admin_id)
    except Exception:
        pass


def trigger_new_lead(admin_id, lead_dict):
    """Fire webhook for a new lead."""
    try:
        data = format_lead_event(lead_dict)
        send_webhook("new_lead", data, admin_id)
    except Exception:
        pass


def trigger_new_patient(admin_id, patient_dict):
    """Fire webhook for a new patient."""
    try:
        data = format_patient_event(patient_dict)
        send_webhook("new_patient", data, admin_id)
    except Exception:
        pass


def trigger_no_show(admin_id, booking_dict):
    """Fire webhook for a no-show."""
    try:
        data = format_booking_event(booking_dict)
        data["status"] = "no_show"
        send_webhook("no_show", data, admin_id)
    except Exception:
        pass


def trigger_form_submitted(admin_id, form_dict, booking_dict=None):
    """Fire webhook for a form submission."""
    try:
        data = {
            "form_id": form_dict.get("id", ""),
            "booking_id": form_dict.get("booking_id", ""),
            "patient_name": form_dict.get("patient_name", ""),
            "admin_id": admin_id,
            "submitted_at": datetime.now().isoformat(),
        }
        if booking_dict:
            data["patient_email"] = booking_dict.get("customer_email", "")
            data["date"] = booking_dict.get("date", "")
            data["time"] = booking_dict.get("time", "")
        send_webhook("form_submitted", data, admin_id)
    except Exception:
        pass
