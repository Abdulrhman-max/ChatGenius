"""
Appointment Reminder Engine for ChatGenius.
Schedules and sends smart appointment reminders (48h / 24h / 2h),
handles patient confirm/cancel responses, and processes pending reminders.
"""

import os
import secrets
from datetime import datetime, timedelta

from dotenv import load_dotenv

import database as db
from email_service import _send_email, _wrap_luxury, BUSINESS_NAME

load_dotenv(override=True)

BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")


# ── Scheduling ───────────────────────────────────────────────────────────────

def schedule_reminders(booking_id, admin_id):
    """Schedule 48h, 24h, and 2h reminders for a booking.

    Reads the admin's reminder_config to determine offsets and quiet-hour
    boundaries.  Creates three reminder rows (one per tier) with
    ``status='pending'``.  Does NOT create APScheduler date jobs — the
    interval-based ``process_pending_reminders()`` picks them up instead.
    """
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        print(f"[Reminders] Booking {booking_id} not found, skipping.")
        return []

    config = db.get_reminder_config(admin_id)

    # Parse appointment datetime — time may be "9:00 AM - 9:30 AM" or "09:00 AM"
    raw_time = booking['time']
    start_time = raw_time.split(" - ")[0].strip() if " - " in raw_time else raw_time.strip()
    appt_dt = datetime.strptime(f"{booking['date']} {start_time}", "%Y-%m-%d %I:%M %p")

    tiers = [
        ("48h", config.get("hours_before_first", 48), config.get("reminder_48h_enabled", 1)),
        ("24h", config.get("hours_before_second", 24), config.get("reminder_24h_enabled", 1)),
        ("2h", config.get("hours_before_third", 2), config.get("reminder_2h_enabled", 1)),
    ]

    quiet_start = config.get("quiet_hours_start", 23)
    quiet_end = config.get("quiet_hours_end", 8)

    created_ids = []
    for reminder_type, hours_before, enabled in tiers:
        if not enabled:
            continue

        scheduled_for = appt_dt - timedelta(hours=hours_before)

        # Respect quiet hours — delay to quiet_end (e.g. 8am) if within range
        scheduled_for = _adjust_for_quiet_hours(scheduled_for, quiet_start, quiet_end)

        # Don't schedule reminders in the past
        if scheduled_for <= datetime.now():
            continue

        scheduled_str = scheduled_for.strftime("%Y-%m-%d %H:%M:%S")
        rid = db.create_appointment_reminder(
            booking_id=booking_id,
            admin_id=admin_id,
            reminder_type=reminder_type,
            scheduled_for=scheduled_str,
        )
        created_ids.append(rid)
        print(f"[Reminders] Scheduled {reminder_type} reminder (id={rid}) for booking {booking_id} at {scheduled_str}")

    return created_ids


def _adjust_for_quiet_hours(dt, quiet_start, quiet_end):
    """If *dt* falls inside the quiet window (e.g. 23:00-08:00), push it
    forward to quiet_end on the next appropriate day."""
    hour = dt.hour
    if quiet_start > quiet_end:
        # Wraps midnight, e.g. 23-8
        if hour >= quiet_start or hour < quiet_end:
            if hour >= quiet_start:
                dt = dt + timedelta(days=1)
            dt = dt.replace(hour=quiet_end, minute=0, second=0, microsecond=0)
    else:
        # Same-day window (unlikely but handle it)
        if quiet_start <= hour < quiet_end:
            dt = dt.replace(hour=quiet_end, minute=0, second=0, microsecond=0)
    return dt


# ── Sending ──────────────────────────────────────────────────────────────────

def send_reminder(reminder_id):
    """Fetch the reminder + booking, generate tokens, send the email,
    and mark the reminder as 'sent'."""
    reminder = db.get_reminder_by_id(reminder_id)
    if not reminder:
        print(f"[Reminders] Reminder {reminder_id} not found.")
        return False

    booking = db.get_booking_by_id(reminder["booking_id"])
    if not booking:
        print(f"[Reminders] Booking {reminder['booking_id']} not found for reminder {reminder_id}.")
        db.update_reminder_status(reminder_id, "skipped")
        return False

    # Skip if booking already cancelled
    if booking.get("status") == "cancelled":
        db.update_reminder_status(reminder_id, "skipped")
        print(f"[Reminders] Booking {booking['id']} is cancelled, skipping reminder {reminder_id}.")
        return False

    # Skip if patient already confirmed via an earlier reminder
    existing_reminders = db.get_reminders_for_booking(reminder["booking_id"])
    already_confirmed = any(r.get("patient_response") == "confirmed" for r in existing_reminders)
    if already_confirmed:
        db.update_reminder_status(reminder_id, "skipped")
        print(f"[Reminders] Booking {booking['id']} already confirmed, skipping reminder {reminder_id}.")
        return False

    # Generate confirm / cancel tokens
    confirm_token = secrets.token_urlsafe(32)
    cancel_token = secrets.token_urlsafe(32)
    db.update_reminder_tokens(reminder_id, confirm_token, cancel_token)

    # Build email
    confirm_url = f"{BASE_URL}/api/reminder-confirm/{confirm_token}"
    cancel_url = f"{BASE_URL}/api/reminder-cancel/{cancel_token}"

    customer_name = booking.get("customer_name", "Patient")
    doctor_name = booking.get("doctor_name", "")
    date_display = booking.get("date", "")
    time_display = booking.get("time", "")
    customer_email = booking.get("customer_email", "")

    if not customer_email:
        print(f"[Reminders] No email for booking {booking['id']}, skipping reminder {reminder_id}.")
        db.update_reminder_status(reminder_id, "skipped")
        return False

    subject = f"Appointment Reminder — {date_display}"
    html = _build_reminder_email(
        customer_name=customer_name,
        doctor_name=doctor_name,
        date_display=date_display,
        time_display=time_display,
        confirm_url=confirm_url,
        cancel_url=cancel_url,
    )

    success = _send_email(customer_email, subject, html)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if success:
        db.update_reminder_status(reminder_id, "sent", sent_at=now_str)
        print(f"[Reminders] Sent {reminder['reminder_type']} reminder to {customer_email} for booking {booking['id']}.")
    else:
        db.update_reminder_status(reminder_id, "failed")
        print(f"[Reminders] Failed to send reminder {reminder_id} to {customer_email}.")

    return success


def _build_reminder_email(customer_name, doctor_name, date_display, time_display, confirm_url, cancel_url):
    """Return full HTML for the appointment-reminder email, matching the
    luxury style used throughout email_service.py."""

    doctor_row = ""
    if doctor_name:
        doctor_row = f"""
            <tr>
                <td style="padding:8px 0;border-bottom:1px solid rgba(201,168,76,0.2);">
                    <span style="color:#999;font-size:12px;text-transform:uppercase;letter-spacing:1.5px;">Doctor</span><br>
                    <span style="color:#1a1a2e;font-size:18px;font-weight:700;">Dr. {doctor_name}</span>
                </td>
            </tr>"""

    content = f"""
    <!-- Gold accent bar -->
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>
    <!-- Header -->
    <tr><td style="background:linear-gradient(145deg,#0b1628 0%,#162040 50%,#1a2550 100%);padding:48px 40px;text-align:center;">
        <div style="width:72px;height:72px;margin:0 auto 20px;border-radius:50%;background:linear-gradient(135deg,#c9a84c,#e8c547);display:flex;align-items:center;justify-content:center;">
            <span style="font-size:36px;line-height:72px;">&#128339;</span>
        </div>
        <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:300;letter-spacing:1px;">Appointment <strong style="font-weight:700;">Reminder</strong></h1>
        <p style="margin:12px 0 0;color:#c9a84c;font-size:14px;letter-spacing:2px;text-transform:uppercase;">Don't forget your upcoming visit</p>
    </td></tr>
    <!-- Greeting -->
    <tr><td style="padding:36px 40px 0;">
        <p style="color:#1a1a2e;font-size:17px;line-height:1.6;margin:0;">
            Dear <strong>{customer_name}</strong>,
        </p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            This is a friendly reminder about your upcoming appointment. Please confirm or cancel using the buttons below.
        </p>
    </td></tr>
    <!-- Appointment Card -->
    <tr><td style="padding:24px 40px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#fafaf5,#f5f3eb);border-radius:12px;border:1px solid #e8dfc5;overflow:hidden;">
        <tr><td style="padding:28px;">
            <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
                <td style="padding:8px 0;border-bottom:1px solid rgba(201,168,76,0.2);">
                    <span style="color:#999;font-size:12px;text-transform:uppercase;letter-spacing:1.5px;">Date</span><br>
                    <span style="color:#1a1a2e;font-size:18px;font-weight:700;">{date_display}</span>
                </td>
            </tr>
            <tr>
                <td style="padding:8px 0;border-bottom:1px solid rgba(201,168,76,0.2);">
                    <span style="color:#999;font-size:12px;text-transform:uppercase;letter-spacing:1.5px;">Time</span><br>
                    <span style="color:#1a1a2e;font-size:18px;font-weight:700;">{time_display}</span>
                </td>
            </tr>
            {doctor_row}
            </table>
        </td></tr>
        </table>
    </td></tr>
    <!-- Action Buttons -->
    <tr><td style="padding:8px 40px 0;">
        <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
            <td align="center" style="padding:8px;">
                <a href="{confirm_url}" style="display:inline-block;background:linear-gradient(135deg,#059669,#10b981);color:#ffffff;padding:16px 44px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;letter-spacing:0.5px;box-shadow:0 8px 24px rgba(5,150,105,0.35);text-transform:uppercase;">
                    &#10003;&ensp;Confirm Appointment
                </a>
            </td>
        </tr>
        <tr>
            <td align="center" style="padding:8px;">
                <a href="{cancel_url}" style="display:inline-block;background:#ffffff;color:#e53e3e;padding:14px 44px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;letter-spacing:0.5px;border:2px solid #e53e3e;text-transform:uppercase;">
                    &#10007;&ensp;Cancel Appointment
                </a>
            </td>
        </tr>
        </table>
    </td></tr>
    <!-- Bottom text -->
    <tr><td style="padding:28px 40px 36px;">
        <div style="border-top:1px solid #eee;padding-top:24px;text-align:center;">
            <p style="color:#999;font-size:13px;margin:0;">
                Need to reschedule? Call us at <strong style="color:#c9a84c;">(555) 123-4567</strong><br>
                <strong style="color:#c9a84c;">{BUSINESS_NAME}</strong>
            </p>
        </div>
    </td></tr>
    <!-- Gold bottom bar -->
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>"""

    return _wrap_luxury(content)


# ── Patient Response Handlers ────────────────────────────────────────────────

def handle_confirm(token):
    """Look up the reminder by its confirm token, record the response, and
    cancel remaining pending reminders for the same booking.

    Returns a dict with booking info on success, or None.
    """
    reminder = db.get_reminder_by_token(token)
    if not reminder:
        return None

    # Verify it's actually the confirm token
    if reminder.get("confirm_token") != token:
        return None

    db.record_reminder_response(reminder["id"], "confirmed")
    db.cancel_reminders_for_booking(reminder["booking_id"])

    booking = db.get_booking_by_id(reminder["booking_id"])
    return {
        "status": "confirmed",
        "booking_id": reminder["booking_id"],
        "customer_name": booking.get("customer_name", "") if booking else "",
        "date": booking.get("date", "") if booking else "",
        "time": booking.get("time", "") if booking else "",
        "doctor_name": booking.get("doctor_name", "") if booking else "",
    }


def handle_cancel(token):
    """Look up the reminder by its cancel token and record the response.

    Actual booking cancellation is handled by the caller (app.py).
    Returns a dict with booking info on success, or None.
    """
    reminder = db.get_reminder_by_token(token)
    if not reminder:
        return None

    # Verify it's actually the cancel token
    if reminder.get("cancel_token") != token:
        return None

    db.record_reminder_response(reminder["id"], "cancelled")

    booking = db.get_booking_by_id(reminder["booking_id"])
    return {
        "status": "cancelled",
        "booking_id": reminder["booking_id"],
        "customer_name": booking.get("customer_name", "") if booking else "",
        "date": booking.get("date", "") if booking else "",
        "time": booking.get("time", "") if booking else "",
        "doctor_name": booking.get("doctor_name", "") if booking else "",
    }


# ── Background Processing ────────────────────────────────────────────────────

def process_pending_reminders():
    """Fetch all pending reminders whose scheduled_for time has passed and
    send each one.  Intended to be called every ~60 seconds by a background
    task / interval job."""
    pending = db.get_pending_reminders()
    if not pending:
        return

    print(f"[Reminders] Processing {len(pending)} pending reminder(s)...")
    for reminder in pending:
        try:
            send_reminder(reminder["id"])
        except Exception as exc:
            print(f"[Reminders] Error sending reminder {reminder['id']}: {exc}")
            db.update_reminder_status(reminder["id"], "failed")


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_confirmation_rate(admin_id):
    """Return today's confirmation statistics for an admin.

    Returns dict with keys: total, confirmed, at_risk, pending,
    confirmation_rate (percentage string).
    """
    stats = db.get_todays_confirmation_stats(admin_id)
    total = stats.get("total", 0)
    confirmed = stats.get("confirmed", 0)
    rate = f"{round(confirmed / total * 100)}%" if total > 0 else "N/A"
    stats["confirmation_rate"] = rate
    return stats
