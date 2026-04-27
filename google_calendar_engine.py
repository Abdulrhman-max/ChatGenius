"""
Google Calendar integration engine for per-doctor OAuth2 calendar sync.
Creates/deletes Google Calendar events when bookings are created or cancelled,
and fetches busy slots from a doctor's Google Calendar.
"""

import os
import json
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta
import database as db

# Secret key for HMAC signing of OAuth state
# Generate a random secret per process if env var is not set (acceptable since OAuth states are short-lived)
_STATE_SECRET = os.environ.get("SECRET_KEY", "").encode("utf-8") or os.urandom(32)

# Nonce store for OAuth state replay protection: {nonce: expiry_datetime}
_oauth_nonces = {}

# Google API scopes required
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# OAuth2 endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _get_oauth_settings(admin_id):
    """Retrieve Google OAuth client_id and client_secret from admin settings (internal use only)."""
    return db.get_gcal_settings(admin_id, include_secret=True)


def _get_doctor_tokens(doctor_id):
    """Retrieve stored Google Calendar tokens for a doctor."""
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT gcal_refresh_token, gcal_calendar_id FROM doctors WHERE id=%s",
            (doctor_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    data = dict(row)
    if not data.get("gcal_refresh_token"):
        return None
    return data


def _build_credentials(admin_id, doctor_id):
    """Build Google OAuth2 credentials from stored refresh token."""
    settings = _get_oauth_settings(admin_id)
    if not settings:
        return None

    tokens = _get_doctor_tokens(doctor_id)
    if not tokens:
        return None

    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=None,
            refresh_token=tokens["gcal_refresh_token"],
            token_uri=GOOGLE_TOKEN_URL,
            client_id=settings["gcal_client_id"],
            client_secret=settings["gcal_client_secret"],
            scopes=SCOPES,
        )
        return creds
    except Exception as e:
        print(f"[gcal] Failed to build credentials for doctor {doctor_id}: {e}", flush=True)
        return None


def _get_calendar_service(admin_id, doctor_id):
    """Build a Google Calendar API service client with automatic token refresh."""
    creds = _build_credentials(admin_id, doctor_id)
    if not creds:
        return None

    try:
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        # Refresh token if expired
        if not creds.valid:
            creds.refresh(Request())

        service = build("calendar", "v3", credentials=creds)
        return service
    except Exception as e:
        print(f"[gcal] Failed to build calendar service for doctor {doctor_id}: {e}", flush=True)
        return None


def _create_nonce():
    """Create a short-lived nonce for OAuth state replay protection."""
    # Prune expired nonces
    now = datetime.utcnow()
    expired = [k for k, v in _oauth_nonces.items() if v < now]
    for k in expired:
        del _oauth_nonces[k]
    nonce = secrets.token_urlsafe(24)
    _oauth_nonces[nonce] = now + timedelta(minutes=10)
    return nonce


def _verify_nonce(nonce):
    """Verify and consume a nonce. Returns True if valid, False otherwise."""
    now = datetime.utcnow()
    expiry = _oauth_nonces.pop(nonce, None)
    if expiry is None:
        return False
    return now < expiry


def _sign_state(state_dict):
    """Create an HMAC-signed JSON state string."""
    state_json = json.dumps(state_dict, sort_keys=True)
    signature = hmac.new(_STATE_SECRET, state_json.encode("utf-8"), hashlib.sha256).hexdigest()
    signed = {"data": state_dict, "sig": signature}
    return json.dumps(signed)


def verify_state(state_raw):
    """Verify HMAC signature and nonce on OAuth state. Returns the state dict or None if invalid."""
    try:
        outer = json.loads(state_raw)
        data = outer.get("data", {})
        sig = outer.get("sig", "")
        state_json = json.dumps(data, sort_keys=True)
        expected = hmac.new(_STATE_SECRET, state_json.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        # Verify and consume the nonce to prevent replay
        nonce = data.get("nonce")
        if not nonce or not _verify_nonce(nonce):
            return None
        return data
    except Exception:
        return None


def get_auth_url(admin_id, redirect_uri, doctor_id):
    """Generate Google OAuth2 authorization URL."""
    settings = _get_oauth_settings(admin_id)
    if not settings or not settings.get("gcal_client_id"):
        return None

    import urllib.parse
    params = {
        "client_id": settings["gcal_client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": _sign_state({"doctor_id": doctor_id, "admin_id": admin_id, "nonce": _create_nonce()}),
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(admin_id, code, redirect_uri):
    """Exchange authorization code for access and refresh tokens."""
    settings = _get_oauth_settings(admin_id)
    if not settings:
        return None

    try:
        import requests as http_req
        resp = http_req.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings["gcal_client_id"],
            "client_secret": settings["gcal_client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        if resp.status_code == 200:
            return resp.json()
        print(f"[gcal] Token exchange failed: {resp.status_code} {resp.text}", flush=True)
        return None
    except Exception as e:
        print(f"[gcal] Token exchange error: {e}", flush=True)
        return None


def save_doctor_tokens(doctor_id, refresh_token, calendar_id="primary"):
    """Store Google Calendar tokens for a doctor."""
    conn = db.get_db()
    conn.execute(
        "UPDATE doctors SET gcal_refresh_token=%s, gcal_calendar_id=%s WHERE id=%s",
        (refresh_token, calendar_id, doctor_id)
    )
    conn.commit()
    conn.close()


def remove_doctor_tokens(doctor_id):
    """Remove Google Calendar tokens for a doctor (disconnect).
    Also revokes the token at Google to fully de-authorize access."""
    # First, retrieve the current refresh token so we can revoke it
    tokens = _get_doctor_tokens(doctor_id)
    refresh_token = tokens.get("gcal_refresh_token") if tokens else None

    # Revoke at Google before clearing from DB
    if refresh_token:
        try:
            import requests as http_req
            http_req.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": refresh_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            print(f"[gcal] Revoked token for doctor {doctor_id}", flush=True)
        except Exception as e:
            print(f"[gcal] Failed to revoke token for doctor {doctor_id} (proceeding with disconnect): {e}", flush=True)

    conn = db.get_db()
    try:
        conn.execute(
            "UPDATE doctors SET gcal_refresh_token=NULL, gcal_calendar_id=NULL WHERE id=%s",
            (doctor_id,)
        )
        conn.commit()
    finally:
        conn.close()


def is_connected(doctor_id):
    """Check if a doctor has a Google Calendar connection."""
    tokens = _get_doctor_tokens(doctor_id)
    return tokens is not None


def _get_admin_timezone(admin_id):
    """Get timezone from admin's company_info, default to UTC."""
    try:
        info = db.get_company_info(admin_id)
        if info and info.get("timezone"):
            return info["timezone"]
    except Exception:
        pass
    return "UTC"


def sync_booking_to_gcal(booking_id, duration_minutes=None, timezone=None):
    """Create a Google Calendar event when a booking is created.
    Returns the Google Calendar event ID or None on failure.
    duration_minutes: appointment length (default 60).
    timezone: IANA timezone string (default from admin settings or UTC)."""
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        print(f"[gcal] Booking {booking_id} not found", flush=True)
        return None

    doctor_id = booking.get("doctor_id", 0)
    admin_id = booking.get("admin_id", 0)
    if not doctor_id:
        print(f"[gcal] Booking {booking_id} has no doctor_id, skipping gcal sync", flush=True)
        return None

    if not is_connected(doctor_id):
        return None

    service = _get_calendar_service(admin_id, doctor_id)
    if not service:
        return None

    tokens = _get_doctor_tokens(doctor_id)
    calendar_id = tokens.get("gcal_calendar_id") or "primary"

    # Resolve duration: use provided, or try booking/service duration, default 60
    if duration_minutes is None:
        duration_minutes = booking.get("duration_minutes") or booking.get("duration") or 60

    # Resolve timezone
    if not timezone:
        timezone = _get_admin_timezone(admin_id)

    try:
        # Parse date and time
        date_str = booking["date"]  # e.g. "2026-04-25"
        time_str = booking["time"]  # e.g. "10:00" or "10:00 AM"

        # Normalize time format
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %I:%M %p")

        end_dt = dt + timedelta(minutes=int(duration_minutes))

        summary = f"Appointment: {booking.get('customer_name', 'Patient')}"
        description = (
            f"Service: {booking.get('service', 'General Consultation')}\n"
            f"Patient: {booking.get('customer_name', '')}\n"
            f"Email: {booking.get('customer_email', '')}\n"
            f"Phone: {booking.get('customer_phone', '')}\n"
            f"Booking ID: {booking_id}"
        )

        event = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": dt.isoformat(),
                "timeZone": timezone,
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": timezone,
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 30},
                ],
            },
        }

        created = service.events().insert(calendarId=calendar_id, body=event).execute()
        gcal_event_id = created.get("id", "")

        # Store the event ID on the booking for later deletion
        if gcal_event_id:
            conn = db.get_db()
            try:
                conn.execute(
                    "UPDATE bookings SET gcal_event_id=%s WHERE id=%s",
                    (gcal_event_id, booking_id)
                )
                conn.commit()
            finally:
                conn.close()

        print(f"[gcal] Created event {gcal_event_id} for booking {booking_id}", flush=True)
        return gcal_event_id

    except Exception as e:
        print(f"[gcal] Failed to create event for booking {booking_id}: {e}", flush=True)
        return None


def delete_gcal_event(booking_id):
    """Delete a Google Calendar event when a booking is cancelled.
    Returns True on success, False on failure."""
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        return False

    doctor_id = booking.get("doctor_id", 0)
    admin_id = booking.get("admin_id", 0)
    gcal_event_id = booking.get("gcal_event_id", "")

    if not doctor_id or not gcal_event_id:
        return False

    if not is_connected(doctor_id):
        return False

    service = _get_calendar_service(admin_id, doctor_id)
    if not service:
        return False

    tokens = _get_doctor_tokens(doctor_id)
    calendar_id = tokens.get("gcal_calendar_id") or "primary"

    try:
        service.events().delete(calendarId=calendar_id, eventId=gcal_event_id).execute()
        print(f"[gcal] Deleted event {gcal_event_id} for booking {booking_id}", flush=True)

        # Clear the event ID from the booking
        conn = db.get_db()
        try:
            conn.execute("UPDATE bookings SET gcal_event_id='' WHERE id=%s", (booking_id,))
            conn.commit()
        finally:
            conn.close()
        return True

    except Exception as e:
        print(f"[gcal] Failed to delete event {gcal_event_id} for booking {booking_id}: {e}", flush=True)
        return False


def get_busy_slots(doctor_id, date, admin_id=None, timezone=None):
    """Fetch busy time slots from Google Calendar for a doctor on a given date.
    Returns a list of dicts: [{"start": "10:00", "end": "10:30"}, ...]"""
    if not is_connected(doctor_id):
        return []

    # Resolve admin_id from doctor if not provided
    if not admin_id:
        conn = db.get_db()
        try:
            doc = conn.execute("SELECT admin_id FROM doctors WHERE id=%s", (doctor_id,)).fetchone()
        finally:
            conn.close()
        if doc:
            admin_id = doc["admin_id"]
        else:
            return []

    service = _get_calendar_service(admin_id, doctor_id)
    if not service:
        return []

    tokens = _get_doctor_tokens(doctor_id)
    calendar_id = tokens.get("gcal_calendar_id") or "primary"

    # Resolve timezone
    if not timezone:
        timezone = _get_admin_timezone(admin_id)

    try:
        # Parse the date string
        if isinstance(date, str):
            day = datetime.strptime(date, "%Y-%m-%d")
        else:
            day = date

        # Use timezone-aware boundaries so Google returns correct day's events
        # Format: YYYY-MM-DDT00:00:00 with timeZone param lets Google handle conversion
        time_min = day.replace(hour=0, minute=0, second=0).isoformat()
        time_max = day.replace(hour=23, minute=59, second=59).isoformat()

        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            timeZone=timezone,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = events_result.get("items", [])
        busy = []
        for event in events:
            start = event.get("start", {}).get("dateTime", "")
            end = event.get("end", {}).get("dateTime", "")
            if start and end:
                try:
                    s = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    e = datetime.fromisoformat(end.replace("Z", "+00:00"))
                    # Convert to admin timezone before formatting
                    try:
                        import pytz
                        tz = pytz.timezone(timezone)
                        s = s.astimezone(tz)
                        e = e.astimezone(tz)
                    except Exception:
                        pass  # If pytz unavailable or invalid tz, fall back to raw offset
                    busy.append({
                        "start": s.strftime("%H:%M"),
                        "end": e.strftime("%H:%M"),
                    })
                except Exception:
                    pass
        return busy

    except Exception as e:
        print(f"[gcal] Failed to fetch busy slots for doctor {doctor_id}: {e}", flush=True)
        return []
