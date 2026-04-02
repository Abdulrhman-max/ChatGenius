"""
Email confirmation service using SMTP.
Sends booking confirmations to both customer and business owner.
"""

import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

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


def send_booking_confirmation_customer(customer_name, customer_email, date_display, time_display):
    """Send booking confirmation to the customer."""
    subject = f"Appointment Confirmed — {date_display} at {time_display}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #0b1628, #162040); padding: 24px; border-radius: 12px; color: white; text-align: center;">
            <h1 style="margin: 0; font-size: 24px;">Appointment Confirmed!</h1>
        </div>
        <div style="padding: 24px; background: #f8f9fa; border-radius: 0 0 12px 12px;">
            <p>Hi <strong>{customer_name}</strong>,</p>
            <p>Your appointment has been confirmed:</p>
            <div style="background: white; border-left: 4px solid #00d4ff; padding: 16px; margin: 16px 0; border-radius: 4px;">
                <p style="margin: 4px 0;"><strong>Date:</strong> {date_display}</p>
                <p style="margin: 4px 0;"><strong>Time:</strong> {time_display}</p>
            </div>
            <p>If you need to reschedule or cancel, please contact us directly.</p>
            <p style="color: #666; font-size: 13px; margin-top: 24px;">— {BUSINESS_NAME}<br>Booked via ChatGenius AI</p>
        </div>
    </div>
    """
    return _send_email(customer_email, subject, html)


def send_booking_notification_owner(customer_name, customer_email, customer_phone, date_display, time_display):
    """Notify the business owner of a new booking."""
    if not BUSINESS_EMAIL:
        print("[Email] No BUSINESS_EMAIL configured, skipping owner notification.")
        return False

    subject = f"New Booking: {customer_name} — {date_display} at {time_display}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #0b1628, #162040); padding: 24px; border-radius: 12px; color: white; text-align: center;">
            <h1 style="margin: 0; font-size: 24px;">New Appointment Booked</h1>
        </div>
        <div style="padding: 24px; background: #f8f9fa; border-radius: 0 0 12px 12px;">
            <p>A new appointment was booked through your ChatGenius chatbot:</p>
            <div style="background: white; border-left: 4px solid #00d4ff; padding: 16px; margin: 16px 0; border-radius: 4px;">
                <p style="margin: 4px 0;"><strong>Customer:</strong> {customer_name}</p>
                <p style="margin: 4px 0;"><strong>Email:</strong> {customer_email or 'Not provided'}</p>
                <p style="margin: 4px 0;"><strong>Phone:</strong> {customer_phone or 'Not provided'}</p>
                <p style="margin: 4px 0;"><strong>Date:</strong> {date_display}</p>
                <p style="margin: 4px 0;"><strong>Time:</strong> {time_display}</p>
            </div>
            <p style="color: #666; font-size: 13px; margin-top: 24px;">— ChatGenius AI Booking System</p>
        </div>
    </div>
    """
    return _send_email(BUSINESS_EMAIL, subject, html)
