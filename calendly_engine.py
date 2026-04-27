"""
Calendly Integration Engine for ChatGenius.
Manages Calendly connection, event types, availability, and webhook sync.
Uses Calendly API v2 (https://api.calendly.com/) with Bearer token auth.
"""
import logging
import os
import base64
import hashlib
import requests
from datetime import datetime, timedelta

import database as db

logger = logging.getLogger("calendly")

CALENDLY_API_BASE = "https://api.calendly.com"

# ── Token Encryption Helpers ──

_ENCRYPTION_KEY = os.environ.get("CALENDLY_TOKEN_KEY", "")
if not _ENCRYPTION_KEY:
    _ENCRYPTION_KEY = os.urandom(32).hex()
    logger.warning("[calendly] CALENDLY_TOKEN_KEY env var not set — using random runtime key. Tokens will not survive restarts.")


def _derive_key(key_str):
    """Derive a 32-byte key from a string using SHA-256."""
    return hashlib.sha256(key_str.encode("utf-8")).digest()


def _encrypt_token(token):
    """Encrypt a token using XOR with a derived key, then base64-encode.
    Returns 'enc:' prefixed string so we can detect encrypted vs plaintext."""
    if not token:
        return token
    key = _derive_key(_ENCRYPTION_KEY)
    token_bytes = token.encode("utf-8")
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(token_bytes))
    return "enc:" + base64.b64encode(encrypted).decode("utf-8")


def _decrypt_token(encrypted):
    """Decrypt a token. Handles both encrypted ('enc:' prefix) and legacy plaintext."""
    if not encrypted:
        return encrypted
    if not encrypted.startswith("enc:"):
        # Legacy plaintext token — return as-is
        return encrypted
    key = _derive_key(_ENCRYPTION_KEY)
    encrypted_bytes = base64.b64decode(encrypted[4:])
    decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(encrypted_bytes))
    return decrypted.decode("utf-8")


def verify_webhook_org(payload, admin_id_hint=None):
    """Verify that the organization in the webhook payload matches a known admin.
    Returns (True, admin_id) if verified, (False, None) otherwise."""
    event_payload = payload.get("payload", {})
    # Organization can be in event_type or scheduled_event
    org_uri = (
        event_payload.get("event_type", {}).get("organization", "")
        or event_payload.get("scheduled_event", {}).get("organization", "")
        or ""
    )

    if not org_uri:
        # Try to extract from the event's URI pattern
        event = event_payload.get("event", {}) or event_payload.get("scheduled_event", {}) or {}
        event_uri = event.get("uri", "")
        # Calendly event URIs contain the organization UUID — but we can't reliably extract org from it
        # Without org_uri, we cannot verify — reject
        if admin_id_hint:
            # If we have an admin_id hint (from URL), verify the admin exists
            conn = db.get_db()
            row = conn.execute(
                "SELECT organization_uri FROM calendly_connections WHERE admin_id=%s AND connected=1",
                (admin_id_hint,),
            ).fetchone()
            if not row:
                # Bug 8 fix: also check doctor connections (handles multiple mode with mode-only row)
                row = conn.execute(
                    "SELECT admin_id FROM calendly_doctor_connections WHERE admin_id=%s AND connected=1 LIMIT 1",
                    (admin_id_hint,),
                ).fetchone()
            conn.close()
            if row:
                return True, admin_id_hint
        logger.warning("[calendly] Webhook rejected: no organization_uri in payload and no valid admin hint")
        return False, None

    conn = db.get_db()
    # Check admin connections
    row = conn.execute(
        "SELECT admin_id FROM calendly_connections WHERE organization_uri=%s AND connected=1",
        (org_uri,),
    ).fetchone()
    if not row:
        # Check doctor connections
        row = conn.execute(
            "SELECT admin_id FROM calendly_doctor_connections WHERE organization_uri=%s AND connected=1 LIMIT 1",
            (org_uri,),
        ).fetchone()
    conn.close()

    if row:
        found_admin_id = row["admin_id"]
        # If admin_id_hint provided, verify it matches
        if admin_id_hint and found_admin_id != admin_id_hint:
            logger.warning(f"[calendly] Webhook org mismatch: payload org belongs to admin #{found_admin_id} but hint is #{admin_id_hint}")
            return False, None
        return True, found_admin_id

    logger.warning(f"[calendly] Webhook rejected: unknown organization_uri {org_uri}")
    return False, None


# ── Connection Management ──

def connect_calendly(api_key, admin_id):
    """Validate personal access token and store it.
    Returns dict with user info and event types on success, or error dict."""
    if not api_key or not api_key.strip():
        return {"error": "API token is required"}

    api_key = api_key.strip()

    # Validate token by fetching current user
    try:
        resp = requests.get(
            f"{CALENDLY_API_BASE}/users/me",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if resp.status_code == 401:
            return {"error": "Invalid Calendly API token"}
        resp.raise_for_status()
        user_data = resp.json().get("resource", {})
    except requests.RequestException as e:
        logger.error(f"[calendly] Failed to validate token for admin {admin_id}: {e}")
        return {"error": f"Could not connect to Calendly: {str(e)}"}

    user_uri = user_data.get("uri", "")
    user_name = user_data.get("name", "")
    user_email = user_data.get("email", "")
    org_uri = user_data.get("current_organization", "")

    # Store credentials in DB
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = conn.execute(
        "SELECT id FROM calendly_connections WHERE admin_id=%s", (admin_id,)
    ).fetchone()

    encrypted_key = _encrypt_token(api_key)
    if existing:
        conn.execute(
            """UPDATE calendly_connections SET
               api_token=%s, user_uri=%s, user_name=%s, user_email=%s, organization_uri=%s,
               connected=1, last_synced_at=%s, updated_at=%s
               WHERE admin_id=%s""",
            (encrypted_key, user_uri, user_name, user_email, org_uri, now, now, admin_id),
        )
    else:
        conn.execute(
            """INSERT INTO calendly_connections
               (admin_id, api_token, user_uri, user_name, user_email, organization_uri,
                connected, last_synced_at, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,1,%s,%s,%s)""",
            (admin_id, encrypted_key, user_uri, user_name, user_email, org_uri, now, now, now),
        )
    conn.commit()
    conn.close()

    # Fetch event types
    event_types = get_event_types(admin_id)

    logger.info(f"[calendly] Connected admin #{admin_id} as {user_name} ({user_email})")
    return {
        "ok": True,
        "connected": True,
        "user_name": user_name,
        "user_email": user_email,
        "user_uri": user_uri,
        "event_types": event_types,
    }


def get_connection(admin_id):
    """Get current Calendly connection status."""
    conn = db.get_db()
    row = conn.execute(
        "SELECT * FROM calendly_connections WHERE admin_id=%s", (admin_id,)
    ).fetchone()
    conn.close()
    if not row:
        return {"connected": False, "calendly_mode": "single"}
    data = dict(row)
    # Never expose the raw token
    data.pop("api_token", None)
    data["connected"] = bool(data.get("connected"))
    data["calendly_mode"] = data.get("calendly_mode", "single") or "single"
    return data


# ── Mode Management ──

def set_calendly_mode(admin_id, mode):
    """Set Calendly mode to 'single' or 'multiple'."""
    if mode not in ("single", "multiple"):
        return {"error": "Invalid mode. Must be 'single' or 'multiple'."}
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = conn.execute(
        "SELECT id FROM calendly_connections WHERE admin_id=%s", (admin_id,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE calendly_connections SET calendly_mode=%s, updated_at=%s WHERE admin_id=%s",
            (mode, now, admin_id),
        )
    else:
        conn.execute(
            "INSERT INTO calendly_connections (admin_id, calendly_mode, created_at, updated_at) VALUES (%s,%s,%s,%s)",
            (admin_id, mode, now, now),
        )
    conn.commit()
    conn.close()
    logger.info(f"[calendly] Admin #{admin_id} set mode to '{mode}'")
    return {"ok": True, "mode": mode}


def get_calendly_mode(admin_id):
    """Get current Calendly mode for an admin."""
    conn = db.get_db()
    row = conn.execute(
        "SELECT calendly_mode FROM calendly_connections WHERE admin_id=%s", (admin_id,)
    ).fetchone()
    conn.close()
    return (row["calendly_mode"] if row and row["calendly_mode"] else "single")


# ── Per-Doctor Connection Management ──

def connect_doctor_calendly(api_key, admin_id, doctor_id):
    """Validate and store a per-doctor Calendly token."""
    if not api_key or not api_key.strip():
        return {"error": "API token is required"}
    api_key = api_key.strip()

    try:
        resp = requests.get(
            f"{CALENDLY_API_BASE}/users/me",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if resp.status_code == 401:
            return {"error": "Invalid Calendly API token"}
        resp.raise_for_status()
        user_data = resp.json().get("resource", {})
    except requests.RequestException as e:
        logger.error(f"[calendly] Doctor token validation failed: {e}")
        return {"error": "Could not connect to Calendly"}

    user_uri = user_data.get("uri", "")
    user_name = user_data.get("name", "")
    user_email = user_data.get("email", "")
    org_uri = user_data.get("current_organization", "")

    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = conn.execute(
        "SELECT id FROM calendly_doctor_connections WHERE admin_id=%s AND doctor_id=%s",
        (admin_id, doctor_id),
    ).fetchone()

    encrypted_key = _encrypt_token(api_key)
    if existing:
        conn.execute(
            """UPDATE calendly_doctor_connections SET
               api_token=%s, user_uri=%s, user_name=%s, user_email=%s, organization_uri=%s,
               connected=1, updated_at=%s
               WHERE admin_id=%s AND doctor_id=%s""",
            (encrypted_key, user_uri, user_name, user_email, org_uri, now, admin_id, doctor_id),
        )
    else:
        conn.execute(
            """INSERT INTO calendly_doctor_connections
               (admin_id, doctor_id, api_token, user_uri, user_name, user_email, organization_uri,
                connected, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s,%s)""",
            (admin_id, doctor_id, encrypted_key, user_uri, user_name, user_email, org_uri, now, now),
        )
    conn.commit()
    conn.close()

    logger.info(f"[calendly] Doctor #{doctor_id} (admin #{admin_id}) connected as {user_name}")
    return {
        "ok": True,
        "connected": True,
        "user_name": user_name,
        "user_email": user_email,
    }


def disconnect_doctor_calendly(admin_id, doctor_id):
    """Remove per-doctor Calendly connection."""
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT api_token, webhook_uri FROM calendly_doctor_connections WHERE admin_id=%s AND doctor_id=%s",
            (admin_id, doctor_id),
        ).fetchone()

        if row and row["webhook_uri"]:
            try:
                requests.delete(
                    row["webhook_uri"],
                    headers={"Authorization": f"Bearer {_decrypt_token(row['api_token'])}"},
                    timeout=10,
                )
            except Exception as e:
                logger.warning(f"[calendly] Failed to delete doctor webhook: {e}")

        conn.execute(
            "DELETE FROM calendly_doctor_connections WHERE admin_id=%s AND doctor_id=%s",
            (admin_id, doctor_id),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info(f"[calendly] Doctor #{doctor_id} (admin #{admin_id}) disconnected")
    return {"ok": True, "disconnected": True}


def get_doctor_connection(admin_id, doctor_id):
    """Get per-doctor Calendly connection status."""
    conn = db.get_db()
    row = conn.execute(
        "SELECT * FROM calendly_doctor_connections WHERE admin_id=%s AND doctor_id=%s",
        (admin_id, doctor_id),
    ).fetchone()
    conn.close()
    if not row:
        return {"connected": False}
    data = dict(row)
    data.pop("api_token", None)
    data["connected"] = bool(data.get("connected"))
    return data


def get_all_doctor_connections(admin_id):
    """Get all per-doctor Calendly connections for an admin."""
    conn = db.get_db()
    rows = conn.execute(
        """SELECT dc.doctor_id, dc.user_name, dc.user_email, dc.connected, dc.last_synced_at,
                  d.name as doctor_name
           FROM calendly_doctor_connections dc
           LEFT JOIN doctors d ON d.id = dc.doctor_id
           WHERE dc.admin_id=%s""",
        (admin_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]



def disconnect_calendly(admin_id):
    """Remove Calendly credentials, webhook subscription, and all doctor connections."""
    conn = db.get_db()
    row = conn.execute(
        "SELECT api_token, webhook_uri FROM calendly_connections WHERE admin_id=%s",
        (admin_id,),
    ).fetchone()

    if row and row["webhook_uri"]:
        # Unsubscribe webhook
        try:
            requests.delete(
                row["webhook_uri"],
                headers={"Authorization": f"Bearer {_decrypt_token(row['api_token'])}"},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"[calendly] Failed to delete webhook for admin {admin_id}: {e}")

    # Also clean up per-doctor connections and their webhooks
    doc_rows = conn.execute(
        "SELECT doctor_id, api_token, webhook_uri FROM calendly_doctor_connections WHERE admin_id=%s",
        (admin_id,),
    ).fetchall()
    for dr in doc_rows:
        if dr["webhook_uri"]:
            try:
                requests.delete(
                    dr["webhook_uri"],
                    headers={"Authorization": f"Bearer {_decrypt_token(dr['api_token'])}"},
                    timeout=10,
                )
            except Exception as e:
                logger.warning(f"[calendly] Failed to delete doctor webhook for doctor #{dr['doctor_id']}: {e}")

    conn.execute("DELETE FROM calendly_connections WHERE admin_id=%s", (admin_id,))
    conn.execute("DELETE FROM calendly_event_mappings WHERE admin_id=%s", (admin_id,))
    conn.execute("DELETE FROM calendly_doctor_connections WHERE admin_id=%s", (admin_id,))
    conn.commit()
    conn.close()

    logger.info(f"[calendly] Disconnected admin #{admin_id} (including doctor connections)")
    return {"ok": True, "disconnected": True}


# ── Event Types ──

def get_event_types(admin_id):
    """Fetch available Calendly event types for the connected user."""
    conn = db.get_db()
    row = conn.execute(
        "SELECT api_token, user_uri FROM calendly_connections WHERE admin_id=%s AND connected=1",
        (admin_id,),
    ).fetchone()
    conn.close()

    if not row:
        return []

    try:
        resp = requests.get(
            f"{CALENDLY_API_BASE}/event_types",
            headers={"Authorization": f"Bearer {_decrypt_token(row['api_token'])}"},
            params={"user": row["user_uri"], "active": "true"},
            timeout=15,
        )
        resp.raise_for_status()
        collection = resp.json().get("collection", [])
        return [
            {
                "uri": et.get("uri", ""),
                "name": et.get("name", ""),
                "slug": et.get("slug", ""),
                "duration": et.get("duration", 0),
                "scheduling_url": et.get("scheduling_url", ""),
                "description_plain": et.get("description_plain", ""),
                "active": et.get("active", False),
            }
            for et in collection
        ]
    except requests.RequestException as e:
        logger.error(f"[calendly] Failed to fetch event types for admin {admin_id}: {e}")
        return []


# ── Available Slots ──

def get_available_slots(event_type_uri, date_range, admin_id):
    """Get available time slots from Calendly for a given event type and date range.
    date_range: dict with 'start' and 'end' in ISO format (YYYY-MM-DD)."""
    conn = db.get_db()
    row = conn.execute(
        "SELECT api_token FROM calendly_connections WHERE admin_id=%s AND connected=1",
        (admin_id,),
    ).fetchone()
    conn.close()

    if not row:
        return {"error": "Calendly not connected"}

    start_date = date_range.get("start", datetime.now().strftime("%Y-%m-%dT00:00:00Z"))
    end_date = date_range.get(
        "end", (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59Z")
    )

    # Ensure ISO format with timezone
    if "T" not in start_date:
        start_date = f"{start_date}T00:00:00Z"
    if "T" not in end_date:
        end_date = f"{end_date}T23:59:59Z"

    try:
        resp = requests.get(
            f"{CALENDLY_API_BASE}/event_type_available_times",
            headers={"Authorization": f"Bearer {_decrypt_token(row['api_token'])}"},
            params={
                "event_type": event_type_uri,
                "start_time": start_date,
                "end_time": end_date,
            },
            timeout=15,
        )
        resp.raise_for_status()
        collection = resp.json().get("collection", [])
        return {
            "slots": [
                {
                    "start_time": slot.get("start_time", ""),
                    "status": slot.get("status", "available"),
                    "invitees_remaining": slot.get("invitees_remaining", 1),
                }
                for slot in collection
            ]
        }
    except requests.RequestException as e:
        logger.error(f"[calendly] Failed to fetch slots for admin {admin_id}: {e}")
        return {"error": str(e), "slots": []}


# ── Webhook Subscription ──

def create_webhook_subscription(admin_id, callback_url):
    """Subscribe to Calendly events (invitee.created, invitee.canceled)."""
    conn = db.get_db()
    row = conn.execute(
        "SELECT api_token, organization_uri, webhook_uri FROM calendly_connections WHERE admin_id=%s AND connected=1",
        (admin_id,),
    ).fetchone()

    if not row:
        conn.close()
        return {"error": "Calendly not connected"}

    # Delete existing webhook if present
    if row["webhook_uri"]:
        try:
            requests.delete(
                row["webhook_uri"],
                headers={"Authorization": f"Bearer {_decrypt_token(row['api_token'])}"},
                timeout=10,
            )
        except Exception:
            pass

    try:
        resp = requests.post(
            f"{CALENDLY_API_BASE}/webhook_subscriptions",
            headers={
                "Authorization": f"Bearer {_decrypt_token(row['api_token'])}",
                "Content-Type": "application/json",
            },
            json={
                "url": callback_url,
                "events": ["invitee.created", "invitee.canceled"],
                "organization": row["organization_uri"],
                "scope": "organization",
            },
            timeout=15,
        )
        resp.raise_for_status()
        webhook_data = resp.json().get("resource", {})
        webhook_uri = webhook_data.get("uri", "")

        # Save webhook URI
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE calendly_connections SET webhook_uri=%s, updated_at=%s WHERE admin_id=%s",
            (webhook_uri, now, admin_id),
        )
        conn.commit()
        conn.close()

        logger.info(f"[calendly] Webhook created for admin #{admin_id}: {webhook_uri}")
        return {"ok": True, "webhook_uri": webhook_uri}
    except requests.RequestException as e:
        conn.close()
        logger.error(f"[calendly] Failed to create webhook for admin {admin_id}: {e}")
        return {"error": str(e)}


# ── Webhook Processing ──

def process_webhook(payload, doctor_id=None, admin_id_hint=None):
    """Handle incoming Calendly webhooks and create/cancel bookings in ChatGenius.
    doctor_id: if set, this webhook came from a per-doctor connection.
    admin_id_hint: if set, scopes the doctor lookup to this admin.
    Returns dict with processing result."""
    event_type = payload.get("event", "")
    event_payload = payload.get("payload", {})

    if event_type == "invitee.created":
        return _handle_invitee_created(event_payload, forced_doctor_id=doctor_id, admin_id_hint=admin_id_hint)
    elif event_type == "invitee.canceled":
        return _handle_invitee_canceled(event_payload, admin_id=admin_id_hint)
    else:
        logger.warning(f"[calendly] Unknown webhook event: {event_type}")
        return {"ok": True, "action": "ignored", "event": event_type}


def _handle_invitee_created(payload, forced_doctor_id=None, admin_id_hint=None):
    """Process a new Calendly booking and create it in ChatGenius.
    forced_doctor_id: if set, assign booking to this doctor (from per-doctor webhook).
    admin_id_hint: if set, scopes the doctor lookup to this admin."""
    invitee = payload.get("invitee", {}) or {}
    event = payload.get("event", {}) or payload.get("scheduled_event", {}) or {}
    event_type_uri = event.get("event_type", "") or payload.get("event_type", {}).get("uri", "")

    invitee_name = invitee.get("name", "Calendly Guest")
    invitee_email = invitee.get("email", "")

    # Extract phone from questions_and_answers if available
    invitee_phone = ""
    for qa in invitee.get("questions_and_answers", []):
        if "phone" in qa.get("question", "").lower():
            invitee_phone = qa.get("answer", "")
            break

    # Parse event start time
    start_time_str = event.get("start_time", "")
    end_time_str = event.get("end_time", "")

    if not start_time_str:
        logger.warning("[calendly] No start_time in invitee.created webhook")
        return {"ok": False, "error": "No start_time in event"}

    try:
        start_dt = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_time_str.replace("Z", "+00:00")) if end_time_str else start_dt + timedelta(hours=1)
        booking_date = start_dt.strftime("%Y-%m-%d")
        booking_time = f"{start_dt.strftime('%I:%M %p')} - {end_dt.strftime('%I:%M %p')}"
    except (ValueError, TypeError) as e:
        logger.error(f"[calendly] Failed to parse event time: {e}")
        return {"ok": False, "error": f"Invalid time format: {e}"}

    admin_id = admin_id_hint
    doctor_id = forced_doctor_id
    doctor_name = ""
    service_name = ""

    if forced_doctor_id:
        # Per-doctor webhook: look up admin from doctor connection
        conn = db.get_db()
        if admin_id_hint:
            # Scoped lookup: use admin_id from the webhook URL for exact match
            row = conn.execute(
                "SELECT admin_id FROM calendly_doctor_connections WHERE admin_id=%s AND doctor_id=%s AND connected=1",
                (admin_id_hint, forced_doctor_id),
            ).fetchone()
        else:
            # Legacy URL without admin_id: best-effort lookup by doctor_id only
            row = conn.execute(
                "SELECT admin_id FROM calendly_doctor_connections WHERE doctor_id=%s AND connected=1",
                (forced_doctor_id,),
            ).fetchone()
        if row:
            admin_id = row["admin_id"]
        # Get doctor name
        doc_row = conn.execute("SELECT name FROM doctors WHERE id=%s", (forced_doctor_id,)).fetchone()
        if doc_row:
            doctor_name = doc_row["name"]
        conn.close()
    else:
        # Single mode: resolve via event type mapping
        admin_id, doctor_id, doctor_name, service_name = _resolve_mapping(event_type_uri)
        # Bug 1 fix: if mapping failed but we have admin_id_hint from webhook verification, use it
        if not admin_id and admin_id_hint:
            admin_id = admin_id_hint

    if not admin_id:
        # Try to find admin by organization
        org_uri = payload.get("event_type", {}).get("organization", "")
        if org_uri:
            conn = db.get_db()
            row = conn.execute(
                "SELECT admin_id FROM calendly_connections WHERE organization_uri=%s",
                (org_uri,),
            ).fetchone()
            if not row:
                # Also check doctor connections
                row = conn.execute(
                    "SELECT admin_id FROM calendly_doctor_connections WHERE organization_uri=%s LIMIT 1",
                    (org_uri,),
                ).fetchone()
            conn.close()
            if row:
                admin_id = row["admin_id"]

    if not admin_id:
        logger.warning("[calendly] Could not determine admin_id for webhook event")
        return {"ok": False, "error": "No admin mapping found for this event type"}

    # Bug 10 fix: when doctor_id is missing/0, mark as unassigned
    if not doctor_id and not forced_doctor_id:
        logger.warning(f"[calendly] No doctor mapping for event type {event_type_uri} — booking will be unassigned (doctor_id=0)")
        doctor_name = "Unassigned"

    # Create booking in ChatGenius
    calendly_event_uri = event.get("uri", "") or payload.get("uri", "")
    booking_id = db.save_booking(
        customer_name=invitee_name,
        customer_email=invitee_email,
        customer_phone=invitee_phone,
        date=booking_date,
        time=booking_time,
        service=service_name or "Calendly Appointment",
        calendar_event_id=f"calendly:{calendly_event_uri}",
        doctor_id=doctor_id or 0,
        doctor_name=doctor_name or "Unassigned",
        admin_id=admin_id,
        status="confirmed",
    )

    # Update last synced timestamp
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE calendly_connections SET last_synced_at=%s, last_synced_event=%s WHERE admin_id=%s",
        (now, f"Booking created: {invitee_name} on {booking_date}", admin_id),
    )
    # Also update doctor connection sync timestamp if applicable
    if forced_doctor_id:
        conn.execute(
            "UPDATE calendly_doctor_connections SET last_synced_at=%s WHERE admin_id=%s AND doctor_id=%s",
            (now, admin_id, forced_doctor_id),
        )
    conn.commit()
    conn.close()

    logger.info(
        f"[calendly] Created booking #{booking_id} for admin #{admin_id} doctor #{doctor_id}: "
        f"{invitee_name} on {booking_date} {booking_time}"
    )
    return {"ok": True, "action": "booking_created", "booking_id": booking_id}


def _handle_invitee_canceled(payload, admin_id=None):
    """Process a Calendly cancellation and cancel the corresponding ChatGenius booking.
    admin_id: if provided, scopes the booking lookup to this admin (Bug 4 fix)."""
    event = payload.get("event", {}) or payload.get("scheduled_event", {}) or {}
    calendly_event_uri = event.get("uri", "") or payload.get("uri", "")

    if not calendly_event_uri:
        return {"ok": False, "error": "No event URI in cancellation payload"}

    # Bug 4 fix: scope booking lookup by admin_id when available
    conn = db.get_db()
    try:
        if admin_id:
            booking = conn.execute(
                "SELECT id, admin_id FROM bookings WHERE calendar_event_id=%s AND admin_id=%s AND status != 'cancelled'",
                (f"calendly:{calendly_event_uri}", admin_id),
            ).fetchone()
        else:
            booking = conn.execute(
                "SELECT id, admin_id FROM bookings WHERE calendar_event_id=%s AND status != 'cancelled'",
                (f"calendly:{calendly_event_uri}",),
            ).fetchone()

        if not booking:
            logger.warning(f"[calendly] No matching booking found for cancelled event: {calendly_event_uri}")
            return {"ok": True, "action": "no_matching_booking"}

        booking_id = booking["id"]
        admin_id = booking["admin_id"]
        db.cancel_booking(booking_id, admin_id=admin_id)

        # Update last synced timestamp
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE calendly_connections SET last_synced_at=%s, last_synced_event=%s WHERE admin_id=%s",
            (now, f"Booking #{booking_id} cancelled via Calendly", admin_id),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(f"[calendly] Cancelled booking #{booking_id} for admin #{admin_id}")
    return {"ok": True, "action": "booking_cancelled", "booking_id": booking_id}


def _resolve_mapping(event_type_uri):
    """Find the admin, doctor, and service mapped to a Calendly event type.
    Returns (admin_id, doctor_id, doctor_name, service_name) or (None, None, None, None)."""
    if not event_type_uri:
        return None, None, None, None

    conn = db.get_db()
    row = conn.execute(
        """SELECT m.admin_id, m.doctor_id, m.service_name, d.name as doctor_name
           FROM calendly_event_mappings m
           LEFT JOIN doctors d ON d.id = m.doctor_id
           WHERE m.event_type_uri=%s""",
        (event_type_uri,),
    ).fetchone()
    conn.close()

    if row:
        return row["admin_id"], row["doctor_id"], row["doctor_name"], row["service_name"]
    return None, None, None, None


# ── Event Type Mapping ──

def save_event_mappings(admin_id, mappings):
    """Save mappings between Calendly event types and ChatGenius doctors/services.
    mappings: list of {event_type_uri, event_type_name, doctor_id, service_name}."""
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Clear existing mappings for this admin
    conn.execute("DELETE FROM calendly_event_mappings WHERE admin_id=%s", (admin_id,))

    # Bug 8 fix: count actual insertions (skip empty URIs)
    inserted_count = 0
    for m in mappings:
        event_type_uri = m.get("event_type_uri", "").strip()
        if not event_type_uri:
            continue
        conn.execute(
            """INSERT INTO calendly_event_mappings
               (admin_id, event_type_uri, event_type_name, doctor_id, service_name, created_at)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (
                admin_id,
                event_type_uri,
                m.get("event_type_name", ""),
                int(m.get("doctor_id", 0) or 0),
                m.get("service_name", ""),
                now,
            ),
        )
        inserted_count += 1

    conn.commit()
    conn.close()
    logger.info(f"[calendly] Saved {inserted_count} event mappings for admin #{admin_id}")
    return {"ok": True, "count": inserted_count}


def get_event_mappings(admin_id):
    """Get saved event type mappings for an admin."""
    conn = db.get_db()
    rows = conn.execute(
        """SELECT m.*, d.name as doctor_name
           FROM calendly_event_mappings m
           LEFT JOIN doctors d ON d.id = m.doctor_id
           WHERE m.admin_id=%s""",
        (admin_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Sync Helper ──

def sync_event_to_booking(calendly_event, admin_id):
    """Convert a Calendly scheduled event dict to a ChatGenius booking.
    Used for manual sync or initial import."""
    event_type_uri = calendly_event.get("event_type", "")
    _, doctor_id, doctor_name, service_name = _resolve_mapping(event_type_uri)

    start_time_str = calendly_event.get("start_time", "")
    end_time_str = calendly_event.get("end_time", "")

    if not start_time_str:
        return {"error": "No start_time in event"}

    try:
        start_dt = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_time_str.replace("Z", "+00:00")) if end_time_str else start_dt + timedelta(hours=1)
        booking_date = start_dt.strftime("%Y-%m-%d")
        booking_time = f"{start_dt.strftime('%I:%M %p')} - {end_dt.strftime('%I:%M %p')}"
    except (ValueError, TypeError) as e:
        return {"error": f"Invalid time format: {e}"}

    # Get invitee info
    invitees = calendly_event.get("invitees", [])
    invitee_name = invitees[0].get("name", "Calendly Guest") if invitees else "Calendly Guest"
    invitee_email = invitees[0].get("email", "") if invitees else ""

    # Extract phone from invitee questions_and_answers if available
    invitee_phone = ""
    if invitees:
        for qa in invitees[0].get("questions_and_answers", []):
            if "phone" in qa.get("question", "").lower():
                invitee_phone = qa.get("answer", "")
                break

    calendly_event_uri = calendly_event.get("uri", "")

    # Check for duplicate
    conn = db.get_db()
    existing = conn.execute(
        "SELECT id FROM bookings WHERE calendar_event_id=%s AND status != 'cancelled'",
        (f"calendly:{calendly_event_uri}",),
    ).fetchone()
    conn.close()

    if existing:
        return {"ok": True, "action": "already_exists", "booking_id": existing["id"]}

    booking_id = db.save_booking(
        customer_name=invitee_name,
        customer_email=invitee_email,
        customer_phone=invitee_phone,
        date=booking_date,
        time=booking_time,
        service=service_name or "Calendly Appointment",
        calendar_event_id=f"calendly:{calendly_event_uri}",
        doctor_id=doctor_id or 0,
        doctor_name=doctor_name or "",
        admin_id=admin_id,
        status="confirmed",
    )

    return {"ok": True, "action": "created", "booking_id": booking_id}


# ── Per-Doctor Webhook Subscription ──

def create_doctor_webhook_subscription(admin_id, doctor_id, callback_url):
    """Subscribe to Calendly events for a per-doctor connection."""
    conn = db.get_db()
    row = conn.execute(
        "SELECT api_token, organization_uri, webhook_uri FROM calendly_doctor_connections WHERE admin_id=%s AND doctor_id=%s AND connected=1",
        (admin_id, doctor_id),
    ).fetchone()

    if not row:
        conn.close()
        return {"error": "Doctor Calendly not connected"}

    # Delete existing webhook
    if row["webhook_uri"]:
        try:
            requests.delete(
                row["webhook_uri"],
                headers={"Authorization": f"Bearer {_decrypt_token(row['api_token'])}"},
                timeout=10,
            )
        except Exception:
            pass

    try:
        resp = requests.post(
            f"{CALENDLY_API_BASE}/webhook_subscriptions",
            headers={
                "Authorization": f"Bearer {_decrypt_token(row['api_token'])}",
                "Content-Type": "application/json",
            },
            json={
                "url": callback_url,
                "events": ["invitee.created", "invitee.canceled"],
                "organization": row["organization_uri"],
                "scope": "organization",
            },
            timeout=15,
        )
        resp.raise_for_status()
        webhook_data = resp.json().get("resource", {})
        webhook_uri = webhook_data.get("uri", "")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE calendly_doctor_connections SET webhook_uri=%s, updated_at=%s WHERE admin_id=%s AND doctor_id=%s",
            (webhook_uri, now, admin_id, doctor_id),
        )
        conn.commit()
        conn.close()
        logger.info(f"[calendly] Doctor webhook created for doctor #{doctor_id} admin #{admin_id}")
        return {"ok": True, "webhook_uri": webhook_uri}
    except requests.RequestException as e:
        conn.close()
        logger.error(f"[calendly] Failed to create doctor webhook: {e}")
        return {"error": "Failed to create webhook"}
