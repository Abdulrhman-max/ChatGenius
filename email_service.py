"""
Email service for ChatGenius.
Beautiful, luxury-styled HTML emails for all system notifications.
"""

import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv(override=True)

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
BUSINESS_EMAIL = os.getenv("BUSINESS_EMAIL", "")
BUSINESS_NAME = os.getenv("BUSINESS_NAME", "ChatGenius Demo Business")


def _send_email(to_email, subject, html_body):
    """Send an email via SMTP."""
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[Email] SMTP not configured. Would send to {to_email}: {subject}")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{BUSINESS_NAME} <{SMTP_USER}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        print(f"[Email] Sent to {to_email}: {subject}")
        return True
    except Exception as e:
        print(f"[Email] Failed to send to {to_email}: {e}")
        return False


def _wrap_luxury(content):
    """Wrap content in a luxury email shell."""
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f0f0;padding:40px 20px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.1);">
{content}
</table>
<!-- Footer -->
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;margin-top:24px;">
<tr><td style="text-align:center;padding:0 20px;">
    <p style="color:#999;font-size:12px;line-height:1.5;margin:0;">
        Powered by <strong style="color:#777;">ChatGenius AI</strong><br>
        You received this email because of your interaction with {BUSINESS_NAME}.<br>
        <span style="color:#bbb;">Please do not reply to this email.</span>
    </p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


# ── Booking Confirmation (Customer) ─────────────────────────────────────────

def send_booking_confirmation_customer(customer_name, customer_email, date_display, time_display, doctor_name="", confirm_url=""):
    """Send beautiful booking confirmation to the customer with a clickable link."""
    subject = f"Your Appointment is Confirmed — {date_display}"

    doctor_row = ""
    if doctor_name:
        doctor_row = f"""
        <tr>
            <td style="padding:8px 0;border-bottom:1px solid #f0f0f0;">
                <span style="color:#999;font-size:13px;text-transform:uppercase;letter-spacing:1px;">Doctor</span><br>
                <span style="color:#1a1a2e;font-size:16px;font-weight:600;">Dr. {doctor_name}</span>
            </td>
        </tr>"""

    btn_html = ""
    if confirm_url:
        btn_html = f"""
        <tr><td style="padding:32px 40px 0;">
            <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center">
                <a href="{confirm_url}" style="display:inline-block;background:linear-gradient(135deg,#c9a84c,#d4af37,#e8c547);color:#1a1a2e;padding:16px 48px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;letter-spacing:0.5px;box-shadow:0 8px 24px rgba(201,168,76,0.4);text-transform:uppercase;">
                    View Appointment Details
                </a>
            </td></tr>
            </table>
        </td></tr>"""

    content = f"""
    <!-- Gold accent bar -->
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>
    <!-- Header -->
    <tr><td style="background:linear-gradient(145deg,#0b1628 0%,#162040 50%,#1a2550 100%);padding:48px 40px;text-align:center;">
        <div style="width:72px;height:72px;margin:0 auto 20px;border-radius:50%;background:linear-gradient(135deg,#c9a84c,#e8c547);display:flex;align-items:center;justify-content:center;">
            <span style="font-size:36px;line-height:72px;">&#10003;</span>
        </div>
        <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:300;letter-spacing:1px;">Appointment <strong style="font-weight:700;">Confirmed</strong></h1>
        <p style="margin:12px 0 0;color:#c9a84c;font-size:14px;letter-spacing:2px;text-transform:uppercase;">Thank you for choosing us</p>
    </td></tr>
    <!-- Greeting -->
    <tr><td style="padding:36px 40px 0;">
        <p style="color:#1a1a2e;font-size:17px;line-height:1.6;margin:0;">
            Dear <strong>{customer_name}</strong>,
        </p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            Your appointment has been successfully booked. Here are your details:
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
    {btn_html}
    <!-- Tips -->
    <tr><td style="padding:32px 40px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8f9ff;border-radius:10px;border-left:4px solid #c9a84c;">
        <tr><td style="padding:20px 24px;">
            <p style="color:#1a1a2e;font-size:14px;font-weight:700;margin:0 0 8px;">Before your visit:</p>
            <p style="color:#666;font-size:13px;line-height:1.8;margin:0;">
                &bull; Please arrive 5 minutes early<br>
                &bull; Bring a valid ID and insurance card<br>
                &bull; Complete your pre-visit form if you haven't already
            </p>
        </td></tr>
        </table>
    </td></tr>
    <!-- Divider + contact -->
    <tr><td style="padding:0 40px 36px;">
        <div style="border-top:1px solid #eee;padding-top:24px;text-align:center;">
            <p style="color:#999;font-size:13px;margin:0;">
                Need to reschedule? Contact us directly.<br>
                <strong style="color:#c9a84c;">{BUSINESS_NAME}</strong>
            </p>
        </div>
    </td></tr>
    <!-- Gold bottom bar -->
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>"""

    return _send_email(customer_email, subject, _wrap_luxury(content))


# ── Booking Notification (Owner) ─────────────────────────────────────────────

def send_booking_notification_owner(customer_name, customer_email, customer_phone, date_display, time_display):
    """Notify the business owner of a new booking."""
    if not BUSINESS_EMAIL:
        print("[Email] No BUSINESS_EMAIL configured, skipping owner notification.")
        return False

    subject = f"New Booking: {customer_name} — {date_display} at {time_display}"
    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#2563eb,#7c3aed,#2563eb);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628,#162040);padding:36px 40px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:24px;font-weight:300;">New <strong>Appointment</strong> Booked</h1>
        <p style="margin:8px 0 0;color:#7c93c3;font-size:13px;">Via ChatGenius AI Chatbot</p>
    </td></tr>
    <tr><td style="padding:32px 40px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8f9fa;border-radius:10px;">
        <tr><td style="padding:24px;">
            <p style="margin:6px 0;font-size:14px;color:#555;"><strong style="color:#1a1a2e;">Customer:</strong> {customer_name}</p>
            <p style="margin:6px 0;font-size:14px;color:#555;"><strong style="color:#1a1a2e;">Email:</strong> {customer_email or 'Not provided'}</p>
            <p style="margin:6px 0;font-size:14px;color:#555;"><strong style="color:#1a1a2e;">Phone:</strong> {customer_phone or 'Not provided'}</p>
            <p style="margin:6px 0;font-size:14px;color:#555;"><strong style="color:#1a1a2e;">Date:</strong> {date_display}</p>
            <p style="margin:6px 0;font-size:14px;color:#555;"><strong style="color:#1a1a2e;">Time:</strong> {time_display}</p>
        </td></tr>
        </table>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#2563eb,#7c3aed,#2563eb);"></td></tr>"""

    return _send_email(BUSINESS_EMAIL, subject, _wrap_luxury(content))


# ── 2FA OTP Email ────────────────────────────────────────────────────────────

def send_otp_email(to_email, user_name, otp_code):
    """Send 2FA OTP code to user."""
    subject = f"Your verification code: {otp_code}"
    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628,#162040);padding:48px 40px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:24px;font-weight:300;">Verification <strong>Code</strong></h1>
        <p style="margin:8px 0 0;color:#c9a84c;font-size:13px;letter-spacing:2px;text-transform:uppercase;">Secure Login</p>
    </td></tr>
    <tr><td style="padding:36px 40px;text-align:center;">
        <p style="color:#555;font-size:15px;margin:0 0 24px;">Hi <strong style="color:#1a1a2e;">{user_name}</strong>, here is your one-time code:</p>
        <div style="background:linear-gradient(135deg,#fafaf5,#f5f3eb);border:2px solid #e8dfc5;border-radius:12px;padding:24px;display:inline-block;">
            <span style="font-size:36px;font-weight:800;letter-spacing:12px;color:#1a1a2e;font-family:'Courier New',monospace;">{otp_code}</span>
        </div>
        <p style="color:#e53e3e;font-size:13px;margin:20px 0 0;font-weight:600;">Expires in 5 minutes. Do not share this code.</p>
    </td></tr>
    <tr><td style="padding:0 40px 36px;text-align:center;">
        <p style="color:#999;font-size:12px;margin:0;">If you didn't request this, please ignore this email.</p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content))


# ── Customer Verification Email ──────────────────────────────────────────────

def send_customer_verification(to_email, business_name, verification_url):
    """Send email verification to new SaaS customer."""
    subject = f"Verify your account — {business_name}"
    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628,#162040);padding:48px 40px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:28px;font-weight:300;">Welcome to <strong>ChatGenius</strong></h1>
        <p style="margin:12px 0 0;color:#c9a84c;font-size:14px;letter-spacing:2px;text-transform:uppercase;">One step to go</p>
    </td></tr>
    <tr><td style="padding:36px 40px;text-align:center;">
        <p style="color:#555;font-size:15px;line-height:1.6;margin:0 0 28px;">
            Hi <strong style="color:#1a1a2e;">{business_name}</strong>,<br>
            Please verify your email to activate your account and start using the platform.
        </p>
        <a href="{verification_url}" style="display:inline-block;background:linear-gradient(135deg,#c9a84c,#d4af37,#e8c547);color:#1a1a2e;padding:16px 48px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;letter-spacing:0.5px;box-shadow:0 8px 24px rgba(201,168,76,0.4);text-transform:uppercase;">
            Verify My Account
        </a>
        <p style="color:#999;font-size:12px;margin:24px 0 0;">Or copy this link:<br>
            <a href="{verification_url}" style="color:#c9a84c;word-break:break-all;font-size:11px;">{verification_url}</a>
        </p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content))


# ── Pre-Visit Form Email ────────────────────────────────────────────────────

def send_previsit_form(to_email, patient_name, form_url, date_display, time_display, doctor_name=""):
    """Send pre-visit form link to patient before appointment."""
    doctor_line = f" with <strong>Dr. {doctor_name}</strong>" if doctor_name else ""
    subject = f"Complete Your Pre-Visit Form — {date_display}"
    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628,#162040);padding:48px 40px;text-align:center;">
        <div style="width:64px;height:64px;margin:0 auto 16px;border-radius:50%;background:linear-gradient(135deg,#c9a84c,#e8c547);line-height:64px;">
            <span style="font-size:28px;">&#128203;</span>
        </div>
        <h1 style="margin:0;color:#fff;font-size:24px;font-weight:300;">Pre-Visit <strong>Form</strong></h1>
    </td></tr>
    <tr><td style="padding:36px 40px;">
        <p style="color:#555;font-size:15px;line-height:1.6;margin:0;">
            Dear <strong style="color:#1a1a2e;">{patient_name}</strong>,
        </p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            You have an upcoming appointment on <strong style="color:#1a1a2e;">{date_display}</strong>
            at <strong style="color:#1a1a2e;">{time_display}</strong>{doctor_line}.
        </p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            To ensure a smooth visit, please complete your pre-visit form:
        </p>
    </td></tr>
    <tr><td style="padding:0 40px 16px;text-align:center;">
        <a href="{form_url}" style="display:inline-block;background:linear-gradient(135deg,#c9a84c,#d4af37,#e8c547);color:#1a1a2e;padding:16px 48px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;letter-spacing:0.5px;box-shadow:0 8px 24px rgba(201,168,76,0.4);text-transform:uppercase;">
            Complete Form Now
        </a>
    </td></tr>
    <tr><td style="padding:16px 40px 36px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8f9ff;border-radius:10px;border-left:4px solid #c9a84c;">
        <tr><td style="padding:16px 20px;">
            <p style="color:#666;font-size:13px;line-height:1.6;margin:0;">
                Takes about <strong>2 minutes</strong> to complete. Your information is kept secure and confidential.
            </p>
        </td></tr>
        </table>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content))


# ── Waitlist Notification Email ──────────────────────────────────────────────

def send_waitlist_notification(to_email, patient_name, date_display, time_slot, confirm_deadline, confirm_url="", doctor_name=""):
    """Notify waitlisted patient that a slot opened up.
    Includes patient name, doctor name, date/time, deadline, and confirm link."""
    subject = f"A Slot Opened Up — {date_display} at {time_slot}"

    doctor_html = ""
    if doctor_name:
        doctor_html = f'<p style="margin:4px 0;font-size:15px;"><strong style="color:#065f46;">Doctor:</strong> <span style="color:#1a1a2e;">Dr. {doctor_name}</span></p>'

    btn_html = ""
    if confirm_url:
        btn_html = f"""
        <tr><td style="padding:0 40px 8px;text-align:center;">
            <a href="{confirm_url}" style="display:inline-block;background:linear-gradient(135deg,#059669,#10b981);color:#fff;padding:16px 48px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;box-shadow:0 8px 24px rgba(5,150,105,0.3);text-transform:uppercase;">
                Confirm My Spot
            </a>
        </td></tr>"""

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#059669,#10b981,#34d399,#10b981,#059669);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#064e3b,#065f46);padding:48px 40px;text-align:center;">
        <div style="width:64px;height:64px;margin:0 auto 16px;border-radius:50%;background:linear-gradient(135deg,#34d399,#10b981);line-height:64px;">
            <span style="font-size:28px;">&#127881;</span>
        </div>
        <h1 style="margin:0;color:#fff;font-size:24px;font-weight:300;">Slot <strong>Available!</strong></h1>
    </td></tr>
    <tr><td style="padding:36px 40px;">
        <p style="color:#555;font-size:15px;line-height:1.6;margin:0;">
            Great news <strong style="color:#1a1a2e;">{patient_name}</strong>!
            A slot has just opened up for the appointment you were waiting for:
        </p>
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0fdf4;border-radius:12px;border:1px solid #bbf7d0;margin:20px 0;">
        <tr><td style="padding:24px;">
            {doctor_html}
            <p style="margin:4px 0;font-size:15px;"><strong style="color:#065f46;">Date:</strong> <span style="color:#1a1a2e;">{date_display}</span></p>
            <p style="margin:4px 0;font-size:15px;"><strong style="color:#065f46;">Time:</strong> <span style="color:#1a1a2e;">{time_slot}</span></p>
        </td></tr>
        </table>
    </td></tr>
    {btn_html}
    <tr><td style="padding:16px 40px 36px;text-align:center;">
        <p style="color:#e53e3e;font-size:14px;font-weight:600;margin:0;">You have {confirm_deadline} to confirm</p>
        <p style="color:#999;font-size:12px;margin:4px 0 0;">Otherwise the slot will be offered to the next person in line.</p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#059669,#10b981,#34d399,#10b981,#059669);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content))


# ── Waitlist Expired Notification ────────────────────────────────────────────

def send_waitlist_expired_notification(to_email, patient_name, date_display, time_slot, doctor_name=""):
    """Send email to patient who didn't fill the pre-visit form in time."""
    subject = f"Your Waitlist Reservation Has Expired — {date_display}"

    doctor_html = ""
    if doctor_name:
        doctor_html = f'<p style="margin:4px 0;font-size:15px;"><strong>Doctor:</strong> Dr. {doctor_name}</p>'

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#dc2626,#ef4444,#f87171,#ef4444,#dc2626);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#450a0a,#7f1d1d);padding:48px 40px;text-align:center;">
        <div style="width:64px;height:64px;margin:0 auto 16px;border-radius:50%;background:linear-gradient(135deg,#f87171,#ef4444);line-height:64px;">
            <span style="font-size:28px;">&#9200;</span>
        </div>
        <h1 style="margin:0;color:#fff;font-size:24px;font-weight:300;">Reservation <strong>Expired</strong></h1>
    </td></tr>
    <tr><td style="padding:36px 40px;">
        <p style="color:#555;font-size:15px;line-height:1.6;margin:0;">
            Dear <strong style="color:#1a1a2e;">{patient_name}</strong>,
        </p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            Unfortunately, the time to complete your pre-visit form has expired and your waitlist reservation for the following appointment has been released:
        </p>
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#fef2f2;border-radius:12px;border:1px solid #fecaca;margin:20px 0;">
        <tr><td style="padding:24px;">
            {doctor_html}
            <p style="margin:4px 0;font-size:15px;"><strong>Date:</strong> {date_display}</p>
            <p style="margin:4px 0;font-size:15px;"><strong>Time:</strong> {time_slot}</p>
        </td></tr>
        </table>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            The slot has been offered to the next person on the waitlist. If you'd still like to book, please contact us or visit our chatbot to check available times.
        </p>
    </td></tr>
    <tr><td style="padding:0 40px 36px;text-align:center;">
        <p style="color:#999;font-size:13px;margin:0;">
            We hope to see you soon!<br>
            <strong style="color:#c9a84c;">{BUSINESS_NAME}</strong>
        </p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#dc2626,#ef4444,#f87171,#ef4444,#dc2626);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content))


# ── Recall / Retention Email ─────────────────────────────────────────────────

def send_recall_email(to_email, patient_name, treatment_type, message="", booking_url=""):
    """Send recall reminder to patient for follow-up treatment."""
    subject = f"Time for Your {treatment_type} Check-Up"
    if not message:
        message = f"It's been a while since your last {treatment_type}. We recommend scheduling a follow-up to keep your dental health in perfect shape."

    btn_html = ""
    if booking_url:
        btn_html = f"""
        <tr><td style="padding:0 40px 8px;text-align:center;">
            <a href="{booking_url}" style="display:inline-block;background:linear-gradient(135deg,#c9a84c,#d4af37,#e8c547);color:#1a1a2e;padding:16px 48px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;box-shadow:0 8px 24px rgba(201,168,76,0.4);text-transform:uppercase;">
                Book Now
            </a>
        </td></tr>"""

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628,#162040);padding:48px 40px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:28px;font-weight:300;">We <strong>Miss You!</strong></h1>
        <p style="margin:12px 0 0;color:#c9a84c;font-size:14px;letter-spacing:1px;">It's time for a check-up</p>
    </td></tr>
    <tr><td style="padding:36px 40px;">
        <p style="color:#555;font-size:15px;line-height:1.6;margin:0;">
            Dear <strong style="color:#1a1a2e;">{patient_name}</strong>,
        </p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">{message}</p>
    </td></tr>
    {btn_html}
    <tr><td style="padding:24px 40px 36px;text-align:center;">
        <p style="color:#999;font-size:13px;margin:0;">— {BUSINESS_NAME}</p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content))


# ── Treatment Follow-Up Email ────────────────────────────────────────────────

def send_treatment_followup(to_email, patient_name, treatment_name, day_number, booking_url=""):
    """Send treatment follow-up check-in email."""
    if day_number <= 2:
        subject = f"How Are You Feeling After Your {treatment_name}?"
        intro = f"We hope you're recovering well after your {treatment_name}. We wanted to check in and see how you're doing."
    elif day_number <= 5:
        subject = f"Quick Check-In — {treatment_name} Follow-Up"
        intro = f"It's been a few days since your {treatment_name}. We hope everything is going smoothly."
    else:
        subject = f"Follow-Up Reminder — {treatment_name}"
        intro = f"It's been {day_number} days since your {treatment_name}. We recommend scheduling a follow-up visit."

    btn_html = ""
    if booking_url:
        btn_html = f"""
        <tr><td style="padding:0 40px 8px;text-align:center;">
            <a href="{booking_url}" style="display:inline-block;background:linear-gradient(135deg,#c9a84c,#d4af37,#e8c547);color:#1a1a2e;padding:16px 48px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;box-shadow:0 8px 24px rgba(201,168,76,0.4);text-transform:uppercase;">
                Book Follow-Up
            </a>
        </td></tr>"""

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628,#162040);padding:48px 40px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:24px;font-weight:300;">Follow-Up <strong>Check-In</strong></h1>
    </td></tr>
    <tr><td style="padding:36px 40px;">
        <p style="color:#555;font-size:15px;line-height:1.6;margin:0;">
            Dear <strong style="color:#1a1a2e;">{patient_name}</strong>,
        </p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">{intro}</p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            If you're experiencing any discomfort or have questions, please don't hesitate to reach out.
        </p>
    </td></tr>
    {btn_html}
    <tr><td style="padding:24px 40px 36px;text-align:center;">
        <p style="color:#999;font-size:13px;margin:0;">Your health is our priority.<br><strong style="color:#c9a84c;">{BUSINESS_NAME}</strong></p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#c9a84c,#d4af37,#e8c547,#d4af37,#c9a84c);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content))
