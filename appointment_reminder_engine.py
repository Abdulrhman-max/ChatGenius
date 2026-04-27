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

def _is_high_risk_patient(booking, admin_id, threshold=4):
    """Check if patient has threshold+ cancellations (cancelled + no-shows).
    Returns True if high risk."""
    patient_id = booking.get("patient_id")
    if patient_id:
        conn = db.get_db()
        row = conn.execute(
            "SELECT total_cancelled, total_no_shows FROM patients WHERE id=%s",
            (patient_id,)
        ).fetchone()
        conn.close()
        if row:
            total = (row["total_cancelled"] or 0) + (row["total_no_shows"] or 0)
            return total >= threshold
    # Fallback: check by email/phone from bookings table
    email = booking.get("customer_email", "")
    phone = booking.get("customer_phone", "")
    if email or phone:
        conn = db.get_db()
        cancelled_count = 0
        if email:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND customer_email=%s AND status IN ('cancelled','no_show')",
                (admin_id, email)
            ).fetchone()
            cancelled_count = row["c"] if row else 0
        if not cancelled_count and phone:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND customer_phone=%s AND status IN ('cancelled','no_show')",
                (admin_id, phone)
            ).fetchone()
            cancelled_count = row["c"] if row else 0
        conn.close()
        return cancelled_count >= threshold
    return False


def schedule_reminders(booking_id, admin_id):
    """Schedule reminders for a booking based on cancellation risk.

    Normal patients: 24h reminder only.
    High-risk patients (4+ cancellations/no-shows): 48h + 24h + 6h reminders.

    Reads the admin's reminder_config for quiet-hour boundaries.
    Creates reminder rows with ``status='pending'``.
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

    # Determine cancellation risk (only if high-risk reminders are enabled)
    high_risk_enabled = config.get("high_risk_enabled", 1)
    high_risk_threshold = config.get("high_risk_threshold", 4)
    high_risk = False
    if high_risk_enabled:
        high_risk = _is_high_risk_patient(booking, admin_id, threshold=high_risk_threshold)
    if high_risk:
        print(f"[Reminders] Booking {booking_id}: HIGH RISK patient (threshold={high_risk_threshold}) — scheduling 48h + 24h + 6h reminders")

    # Build tiers based on risk level
    if high_risk:
        tiers = [
            ("48h", 48, True),
            ("24h", 24, True),
            ("6h", 6, True),
        ]
    else:
        tiers = [
            ("24h", 24, True),
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

    # Fetch preparation instructions if this is a service booking
    prep_instructions = ""
    if booking.get("service_id"):
        try:
            svc = db.get_company_service_by_id(booking["service_id"])
            if svc and svc.get("preparation_instructions"):
                prep_instructions = svc["preparation_instructions"]
        except Exception:
            pass

    is_high_risk_reminder = reminder["reminder_type"] == "6h"
    if is_high_risk_reminder:
        subject = f"Your Appointment is in 6 Hours — Please Confirm"
    else:
        subject = f"Appointment Reminder — {date_display}"

    html = _build_reminder_email(
        customer_name=customer_name,
        doctor_name=doctor_name,
        date_display=date_display,
        time_display=time_display,
        confirm_url=confirm_url,
        cancel_url=cancel_url,
        preparation_instructions=prep_instructions,
        is_urgent=is_high_risk_reminder,
    )

    success = _send_email(customer_email, subject, html)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if success:
        db.update_reminder_status(reminder_id, "sent", sent_at=now_str)
        print(f"[Reminders] Sent {reminder['reminder_type']} reminder to {customer_email} for booking {booking['id']}.")
    else:
        db.update_reminder_status(reminder_id, "failed")
        print(f"[Reminders] Failed to send reminder {reminder_id} to {customer_email}.")

    # Also send SMS reminder if Twilio is configured and SMS reminders are enabled
    try:
        admin_id = reminder.get("admin_id", 0)
        if db.is_feature_enabled(admin_id, "sms_appointment_reminder"):
            import sms_engine
            if sms_engine.is_configured(admin_id):
                sms_sent = sms_engine.send_appointment_reminder_sms(booking["id"])
                if sms_sent:
                    print(f"[Reminders] SMS reminder also sent for booking {booking['id']}.")
    except Exception as sms_err:
        print(f"[Reminders] SMS reminder failed for booking {booking['id']}: {sms_err}")

    return success


def _build_reminder_email(customer_name, doctor_name, date_display, time_display, confirm_url, cancel_url, preparation_instructions="", is_urgent=False):
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

    prep_html = ""
    if preparation_instructions:
        prep_lines = preparation_instructions.strip().replace("\n", "<br>")
        prep_html = f"""
    <tr><td style="padding:0 40px 16px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#fffbeb,#fef3c7);border-radius:10px;border-left:4px solid #d4af37;">
        <tr><td style="padding:20px 24px;">
            <p style="color:#92400e;font-size:14px;font-weight:700;margin:0 0 8px;">&#9888; Preparation Instructions:</p>
            <p style="color:#78350f;font-size:13px;line-height:1.8;margin:0;">{prep_lines}</p>
        </td></tr>
        </table>
    </td></tr>"""

    content = f"""
    <!-- Gold accent bar -->
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>
    <!-- Header -->
    <tr><td style="background:linear-gradient(145deg,#0b1628 0%,#162040 50%,#1a2550 100%);padding:48px 40px;text-align:center;">
        <div style="width:72px;height:72px;margin:0 auto 20px;border-radius:50%;background:linear-gradient(135deg,#c9a84c,#e8c547);display:flex;align-items:center;justify-content:center;">
            <span style="font-size:36px;line-height:72px;">&#128339;</span>
        </div>
        <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:300;letter-spacing:1px;">{'<strong style="font-weight:700;">Urgent</strong> Reminder' if is_urgent else 'Appointment <strong style="font-weight:700;">Reminder</strong>'}</h1>
        <p style="margin:12px 0 0;color:#c9a84c;font-size:14px;letter-spacing:2px;text-transform:uppercase;">{'Your appointment is just hours away' if is_urgent else "Don't forget your upcoming visit"}</p>
    </td></tr>
    <!-- Greeting -->
    <tr><td style="padding:36px 40px 0;">
        <p style="color:#1a1a2e;font-size:17px;line-height:1.6;margin:0;">
            Dear <strong>{customer_name}</strong>,
        </p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            {'Your appointment is coming up <strong>very soon</strong>. We have reserved this time specifically for you and our team is preparing for your visit. Please confirm your attendance below, or let us know if you need to reschedule.' if is_urgent else 'This is a friendly reminder about your upcoming appointment. Please confirm or cancel using the buttons below.'}
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
    {prep_html}
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
