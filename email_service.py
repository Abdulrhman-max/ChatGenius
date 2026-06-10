"""
Email service for ChatGenius.
Clean, professional HTML emails for all system notifications.
Supports custom admin templates with configurable colors, logos, and fonts.
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
BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Our Store")


def _get_company_type(admin_id):
    """Return company type for the admin: dental, ecommerce, or real_estate."""
    if not admin_id:
        return ""
    try:
        import database as db
        return db.get_company_type(admin_id) or ""
    except Exception:
        return ""


def _send_email(to_email, subject, html_body, from_name=None, admin_id=None):
    """Send an email via the admin's own SMTP. Blocks if admin hasn't set up SMTP.
    System emails (OTP, verification) with admin_id=None use the platform SMTP."""

    if admin_id:
        # Admin emails MUST use the admin's own SMTP — no fallback
        try:
            import database as db
            admin_smtp = db.get_admin_smtp_config(admin_id)
        except Exception:
            admin_smtp = None

        if not admin_smtp:
            print(f"[Email] BLOCKED — admin {admin_id} has not set up SMTP. Email to {to_email} not sent: {subject}")
            return False

        smtp_host = admin_smtp["smtp_host"] or "smtp.gmail.com"
        smtp_port = admin_smtp["smtp_port"] or 587
        smtp_user = admin_smtp["smtp_user"]
        smtp_pass = admin_smtp["smtp_password"]
        from_email = admin_smtp["smtp_from_email"] or admin_smtp["smtp_user"]
    else:
        # System-level emails (OTP, verification) — use platform SMTP
        smtp_host, smtp_port = SMTP_HOST, SMTP_PORT
        smtp_user, smtp_pass = SMTP_USER, SMTP_PASSWORD
        from_email = SMTP_USER

    if not smtp_user or not smtp_pass:
        print(f"[Email] SMTP not configured. Would send to {to_email}: {subject}")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{from_name or BUSINESS_NAME} <{from_email}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        label = f"admin {admin_id} SMTP" if admin_id else "system SMTP"
        print(f"[Email] Sent to {to_email} via {label}: {subject}")
        return True
    except Exception as e:
        print(f"[Email] Failed to send to {to_email}: {e}")
        return False


def is_admin_smtp_configured(admin_id):
    """Check if admin has set up and verified their SMTP. Used to gate email system features."""
    if not admin_id:
        return False
    try:
        import database as db
        cfg = db.get_admin_smtp_config(admin_id)
        return cfg is not None
    except Exception:
        return False


def _get_base_url():
    """Get the server base URL for making relative URLs absolute in emails."""
    try:
        from flask import request
        return request.host_url.rstrip("/")
    except (RuntimeError, ImportError):
        # Outside request context — fall back to env or localhost
        host = os.getenv("SERVER_URL", "").rstrip("/")
        return host or "http://localhost:8080"


def _make_urls_absolute(html):
    """Convert relative src/href URLs to absolute so images load in email clients."""
    import re
    base = _get_base_url()
    def fix_url(match):
        attr = match.group(1)  # src or href
        url = match.group(2)
        if url.startswith(('data:', 'mailto:', '#', '{{', '//')):
            return match.group(0)
        # Replace localhost/127.0.0.1 URLs with the real server URL
        if url.startswith(('http://localhost', 'http://127.0.0.1')):
            path = re.sub(r'^https?://[^/]+', '', url)
            return f'{attr}="{base}{path}"'
        if url.startswith(('http://', 'https://')):
            return match.group(0)
        return f'{attr}="{base}{url}"'
    # Match src="..." or href="..." (both relative and absolute)
    return re.sub(r'(src|href)="([^"]*)"', fix_url, html)


def _get_admin_plan(admin_id):
    """Get the plan for an admin user. Returns plan string or 'free_trial'."""
    if not admin_id:
        return "free_trial"
    try:
        import database as db
        conn = db.get_db()
        row = conn.execute("SELECT plan FROM users WHERE id=%s", (admin_id,)).fetchone()
        conn.close()
        return row["plan"] if row else "free_trial"
    except Exception:
        return "free_trial"


def _strip_watermark(html):
    """Remove ChatGenius watermark from compiled HTML for paid plans."""
    import re
    # Remove the footer table containing the watermark
    html = re.sub(
        r'<table[^>]*>\s*<tr>\s*<td[^>]*text-align:\s*center[^>]*>\s*<p[^>]*>.*?Powered by.*?ChatGenius AI.*?</p>\s*</td>\s*</tr>\s*</table>',
        '', html, flags=re.DOTALL | re.IGNORECASE)
    return html


def _get_admin_business_name(admin_id):
    """Get the admin's actual business/store name from company_info."""
    if not admin_id:
        return "Our Business"
    try:
        import database as db
        ci = db.get_company_info(admin_id)
        if ci and ci.get("business_name"):
            return ci["business_name"]
        # Fallback: use admin's name from users table
        conn = db.get_db()
        user = conn.execute("SELECT name, company FROM users WHERE id=%s", (admin_id,)).fetchone()
        conn.close()
        if user:
            if user.get("company"):
                return user["company"]
            if user.get("name"):
                return user["name"]
    except Exception:
        pass
    return "Our Business"


def _wrap_luxury(content, admin_id=None, variables=None):
    """Wrap content in a professional email shell, using custom template if available."""
    template = None
    plan = _get_admin_plan(admin_id)
    hide_watermark = True  # never show ChatGenius watermark in customer emails

    if admin_id:
        try:
            import database as db
            template = db.get_email_template(admin_id)
        except Exception:
            pass

    # If the admin built a custom email via the drag-and-drop builder, use it —
    # but ONLY if the template has a {{content}} placeholder (acting as a layout wrapper).
    # If the template is a static design without {{content}}, it would replace the actual
    # email body entirely, so we skip it and use the standard wrapper instead.
    if template and template.get("compiled_html"):
        compiled = template["compiled_html"]
        if "{{content}}" in compiled:
            # Template is a layout wrapper — inject the actual email content
            html = compiled.replace("{{content}}", content)
            html = _make_urls_absolute(html)
            if hide_watermark:
                html = _strip_watermark(html)
            if variables:
                html = render_template_variables(html, variables)
            return html
        # Otherwise: template is a standalone design (e.g. follow-up template).
        # Extract actual colors used in the compiled HTML to override stale DB fields,
        # then use _wrap_custom_template to wrap the real email content with those colors.
        import re as _re
        _extracted = {}
        # Extract button/link background color (e.g. background:#059669)
        _btn_match = _re.search(r'<a\s[^>]*style="[^"]*background:\s*([#\w]+)', compiled)
        if _btn_match:
            _extracted["button_color"] = _btn_match.group(1)
            _extracted["primary_color"] = _btn_match.group(1)
        # Extract heading color
        _h_match = _re.search(r'<h[12][^>]*color:\s*([#\w]+)', compiled)
        if _h_match:
            _extracted["primary_color"] = _h_match.group(1)
        # Extract font-family
        _f_match = _re.search(r'font-family:\s*([^;"\']+)', compiled)
        if _f_match:
            _extracted["font_family"] = _f_match.group(1).strip()
        # Extract button text color
        _btc_match = _re.search(r'<a\s[^>]*style="[^"]*color:\s*([#\w]+)', compiled)
        if _btc_match:
            _extracted["button_text_color"] = _btc_match.group(1)
        # Extract button border-radius
        _br_match = _re.search(r'border-radius:\s*(\d+)', compiled)
        if _br_match:
            _extracted["button_radius"] = _br_match.group(1)
        # Extract background color
        _bg_match = _re.search(r'<body[^>]*background:\s*([#\w]+)', compiled)
        if _bg_match:
            _extracted["bg_color"] = _bg_match.group(1)
        # Override template fields with extracted values
        if _extracted:
            template = dict(template)
            template.update(_extracted)

    if template and (template.get("header_html") or template.get("footer_html") or
                     template.get("primary_color") or template.get("logo_url") or
                     template.get("font_family") or template.get("button_color")):
        html = _wrap_custom_template(content, template, hide_watermark=hide_watermark)
        if variables:
            html = render_template_variables(html, variables)
        return html

    watermark = ""
    admin_biz_name = _get_admin_business_name(admin_id)
    if not hide_watermark:
        watermark = f"""<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;margin-top:24px;">
<tr><td style="text-align:center;padding:0 20px;">
    <p style="color:#999;font-size:12px;line-height:1.5;margin:0;">
        Powered by <strong style="color:#777;">ChatGenius</strong><br>
        You received this email because of your interaction with {admin_biz_name}.<br>
        <span style="color:#bbb;">Please do not reply to this email.</span>
    </p>
</td></tr>
</table>"""

    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f0f0;padding:40px 20px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.1);">
{content}
</table>
{watermark}
</td></tr>
</table>
</body>
</html>"""
    if variables:
        html = render_template_variables(html, variables)
    return html


def _wrap_custom_template(content, template, hide_watermark=False):
    """Wrap email content using custom admin template with their colors, images, fonts."""
    bg = template.get("bg_color", "#f0f0f0") or "#f0f0f0"
    primary = template.get("primary_color", "#8b5cf6") or "#8b5cf6"
    secondary = template.get("secondary_color", "#1a1a2e") or "#1a1a2e"
    btn_color = template.get("button_color", "#8b5cf6") or "#8b5cf6"
    btn_text = template.get("button_text_color", "#ffffff") or "#ffffff"
    btn_radius = template.get("button_radius", "8") or "8"
    font = template.get("font_family", "Helvetica Neue, Helvetica, Arial, sans-serif") or "Helvetica Neue, Helvetica, Arial, sans-serif"
    content_width = template.get("content_width", "600") or "600"
    card_radius = template.get("card_radius", "8") or "8"
    card_shadow = template.get("card_shadow", "0 20px 60px rgba(0,0,0,0.1)") or "0 20px 60px rgba(0,0,0,0.1)"
    top_bar_height = template.get("top_bar_height", "4") or "4"
    line_height = template.get("line_height", "1.6") or "1.6"
    letter_spacing = template.get("letter_spacing", "0") or "0"
    header_html = template.get("header_html", "") or ""
    footer_html = template.get("footer_html", "") or ""
    logo_url = template.get("logo_url", "") or ""
    header_img = template.get("header_image_url", "") or ""

    # Build logo row
    logo_row = ""
    if logo_url:
        logo_row = f'<tr><td style="padding:20px 40px 10px;text-align:center;"><img src="{logo_url}" alt="Logo" style="max-height:60px;max-width:200px;"></td></tr>'

    # Build header image
    header_img_row = ""
    if header_img:
        header_img_row = f'<tr><td><img src="{header_img}" alt="" style="width:100%;max-height:200px;object-fit:cover;display:block;"></td></tr>'

    # Custom header content
    header_content = ""
    if header_html.strip():
        header_content = f'<tr><td style="padding:20px 40px;color:{secondary};font-family:{font};">{header_html}</td></tr>'

    # Custom footer content
    footer_content = ""
    if footer_html.strip():
        footer_content = f'<tr><td style="padding:20px 40px;color:#666;font-family:{font};font-size:13px;">{footer_html}</td></tr>'

    # Inject custom styling into content — replace default brand colors with admin's colors
    styled_content = content
    # Replace default gradient bars with admin's colors
    styled_content = styled_content.replace(
        "linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6)",
        f"linear-gradient(90deg,{primary},{btn_color},{primary})")
    # Replace default button gradients
    styled_content = styled_content.replace(
        "linear-gradient(135deg,#8b5cf6,#7c3aed,#a78bfa)",
        f"linear-gradient(135deg,{btn_color},{primary})")
    styled_content = styled_content.replace(
        "linear-gradient(135deg,#8b5cf6,#a78bfa)",
        f"linear-gradient(135deg,{btn_color},{primary})")
    styled_content = styled_content.replace(
        "linear-gradient(135deg,#8b5cf6,#7c3aed)",
        f"linear-gradient(135deg,{btn_color},{primary})")
    # Replace header dark gradient (keep the dark bg but tint with primary)
    styled_content = styled_content.replace(
        "linear-gradient(135deg,#faf8ff,#f3f0ff)",
        f"linear-gradient(135deg,#fafaff,{primary}11)")
    # Replace default border and accent colors
    styled_content = styled_content.replace("rgba(139,92,246,0.15)", f"{primary}33")
    styled_content = styled_content.replace("border-left:4px solid #8b5cf6", f"border-left:4px solid {primary}")
    styled_content = styled_content.replace("border-left:3px solid #8b5cf6", f"border-left:3px solid {primary}")
    styled_content = styled_content.replace("rgba(139,92,246,0.2)", f"{primary}33")
    styled_content = styled_content.replace("rgba(139,92,246,0.4)", f"{primary}66")
    styled_content = styled_content.replace("rgba(139,92,246,0.3)", f"{primary}4d")
    # Replace solid default color references
    styled_content = styled_content.replace("background:#8b5cf6", f"background:{btn_color}")
    styled_content = styled_content.replace("background-color:#8b5cf6", f"background-color:{btn_color}")
    styled_content = styled_content.replace("background-color:#7c3aed", f"background-color:{btn_color}")
    styled_content = styled_content.replace("background:#f8f7ff", f"background:{bg}")
    styled_content = styled_content.replace("color:#8b5cf6", f"color:{primary}")
    styled_content = styled_content.replace("color:#7c3aed", f"color:{primary}")
    # Replace default box-shadows
    styled_content = styled_content.replace(
        "box-shadow:0 8px 24px rgba(139,92,246,0.4)",
        f"box-shadow:0 8px 24px {primary}66")
    styled_content = styled_content.replace(
        "box-shadow:0 4px 25px rgba(139,92,246,0.3)",
        f"box-shadow:0 4px 25px {primary}4d")
    # Replace button text color and radius
    styled_content = styled_content.replace("color:#ffffff;padding:16px 36px", f"color:{btn_text};padding:16px 36px")
    styled_content = styled_content.replace("color:#ffffff;padding:16px 48px", f"color:{btn_text};padding:16px 48px")
    styled_content = styled_content.replace("border-radius:50px;text-decoration:none;font-weight:700", f"border-radius:{btn_radius}px;text-decoration:none;font-weight:700")

    top_bar = f'<tr><td style="height:{top_bar_height}px;background:linear-gradient(90deg,{primary},{btn_color},{primary});"></td></tr>' if top_bar_height != "0" else ""
    bot_bar = top_bar
    ls_style = f"letter-spacing:{letter_spacing}px;" if letter_spacing and letter_spacing != "0" else ""

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:{bg};font-family:'{font}';{ls_style}line-height:{line_height};">
<table width="100%" cellpadding="0" cellspacing="0" style="background:{bg};padding:40px 20px;">
<tr><td align="center">
<table width="{content_width}" cellpadding="0" cellspacing="0" style="max-width:{content_width}px;width:100%;background:#ffffff;border-radius:{card_radius}px;overflow:hidden;box-shadow:{card_shadow};">
{top_bar}
{header_img_row}
{logo_row}
{header_content}
{styled_content}
{footer_content}
{bot_bar}
</table>
{"" if hide_watermark else f'''<table width="{content_width}" cellpadding="0" cellspacing="0" style="max-width:{content_width}px;width:100%;margin-top:24px;">
<tr><td style="text-align:center;padding:0 20px;">
    <p style="color:#999;font-size:12px;line-height:1.5;margin:0;font-family:&#39;{font}&#39;;">
        Powered by <strong style="color:#777;">ChatGenius</strong>
    </p>
</td></tr>
</table>'''}
</td></tr>
</table>
</body>
</html>"""


def render_template_variables(html, variables):
    """Replace {{variable}} placeholders with actual values."""
    import re
    def replacer(match):
        key = match.group(1)
        return str(variables.get(key, match.group(0)))
    return re.sub(r'\{\{(\w+)\}\}', replacer, html)


# ── Booking Confirmation (Customer) ─────────────────────────────────────────

def send_booking_confirmation_customer(customer_name, customer_email, date_display, time_display, doctor_name="", confirm_url="", cancel_url="", service_name="", duration_minutes=0, price="", preparation_instructions="", admin_id=None):
    """Send beautiful booking confirmation to the customer with a clickable link."""
    biz_name = _get_admin_business_name(admin_id)
    subject = f"Your Appointment is Confirmed — {date_display}"

    ctype = _get_company_type(admin_id)
    doctor_row = ""
    if doctor_name:
        label = "Doctor" if ctype == "dental" else "Specialist"
        prefix = "Dr. " if ctype == "dental" else ""
        doctor_row = f"""
        <tr>
            <td style="padding:8px 0;border-bottom:1px solid #f0f0f0;">
                <span style="color:#999;font-size:13px;text-transform:uppercase;letter-spacing:1px;">{label}</span><br>
                <span style="color:#1a1a2e;font-size:16px;font-weight:600;">{prefix}{doctor_name}</span>
            </td>
        </tr>"""

    service_row = ""
    if service_name:
        details = f'<span style="color:#1a1a2e;font-size:16px;font-weight:600;">{service_name}</span>'
        extras = []
        if duration_minutes:
            extras.append(f"{duration_minutes} min")
        if price:
            extras.append(f"from {price}")
        if extras:
            details += f'<br><span style="color:#888;font-size:12px;">{" · ".join(extras)}</span>'
        service_row = f"""
        <tr>
            <td style="padding:8px 0;border-bottom:1px solid #f0f0f0;">
                <span style="color:#999;font-size:13px;text-transform:uppercase;letter-spacing:1px;">Service</span><br>
                {details}
            </td>
        </tr>"""

    btn_html = ""
    if confirm_url or cancel_url:
        btn_parts = ""
        if confirm_url:
            btn_parts += f"""
                <a href="{confirm_url}" style="display:inline-block;background:linear-gradient(135deg,#8b5cf6,#7c3aed,#a78bfa);color:#ffffff;padding:16px 36px;border-radius:50px;text-decoration:none;font-weight:700;font-size:14px;letter-spacing:0.5px;box-shadow:0 8px 24px rgba(139,92,246,0.4);text-transform:uppercase;margin:6px;">
                    View Details
                </a>"""
        if cancel_url:
            btn_parts += f"""
                <a href="{cancel_url}" style="display:inline-block;background:transparent;color:#999;padding:14px 28px;border-radius:50px;text-decoration:none;font-weight:600;font-size:13px;border:1px solid #ddd;margin:6px;">
                    Cancel Appointment
                </a>"""
        btn_html = f"""
        <tr><td style="padding:32px 40px 0;text-align:center;">
            <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center">
                {btn_parts}
            </td></tr>
            </table>
        </td></tr>"""

    prep_html = ""
    if preparation_instructions:
        prep_lines = preparation_instructions.strip().replace("\n", "<br>")
        prep_html = f"""
    <tr><td style="padding:0 40px 16px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#fffbeb,#fef3c7);border-radius:10px;border-left:4px solid #8b5cf6;">
        <tr><td style="padding:20px 24px;">
            <p style="color:#92400e;font-size:14px;font-weight:700;margin:0 0 8px;">&#9888; Preparation Instructions:</p>
            <p style="color:#78350f;font-size:13px;line-height:1.8;margin:0;">{prep_lines}</p>
        </td></tr>
        </table>
    </td></tr>"""

    content = f"""
    <!-- Accent bar -->
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>
    <!-- Header -->
    <tr><td style="background:linear-gradient(145deg,#0b1628 0%,#162040 50%,#1a2550 100%);padding:48px 40px;text-align:center;">
        <div style="width:72px;height:72px;margin:0 auto 20px;border-radius:50%;background:linear-gradient(135deg,#8b5cf6,#a78bfa);display:flex;align-items:center;justify-content:center;">
            <span style="font-size:36px;line-height:72px;">&#10003;</span>
        </div>
        <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:300;letter-spacing:1px;">Appointment <strong style="font-weight:700;">Confirmed</strong></h1>
        <p style="margin:12px 0 0;color:#8b5cf6;font-size:14px;letter-spacing:2px;text-transform:uppercase;">Thank you for choosing us</p>
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
        <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#faf8ff,#f3f0ff);border-radius:12px;border:1px solid rgba(139,92,246,0.15);overflow:hidden;">
        <tr><td style="padding:28px;">
            <table width="100%" cellpadding="0" cellspacing="0">
            {service_row}
            <tr>
                <td style="padding:8px 0;border-bottom:1px solid rgba(139,92,246,0.2);">
                    <span style="color:#999;font-size:12px;text-transform:uppercase;letter-spacing:1.5px;">Date</span><br>
                    <span style="color:#1a1a2e;font-size:18px;font-weight:700;">{date_display}</span>
                </td>
            </tr>
            <tr>
                <td style="padding:8px 0;border-bottom:1px solid rgba(139,92,246,0.2);">
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
    {prep_html}
    <!-- Tips -->
    <tr><td style="padding:32px 40px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8f9ff;border-radius:10px;border-left:4px solid #8b5cf6;">
        <tr><td style="padding:20px 24px;">
            <p style="color:#1a1a2e;font-size:14px;font-weight:700;margin:0 0 8px;">{"Before your visit:" if _get_company_type(admin_id) == "dental" else "Good to know:"}</p>
            <p style="color:#666;font-size:13px;line-height:1.8;margin:0;">
                {"&bull; Please arrive 5 minutes early<br>&bull; Bring a valid ID and insurance card<br>&bull; Complete your pre-visit form if you haven't already" if _get_company_type(admin_id) == "dental" else "&bull; You will receive a reminder before your appointment<br>&bull; Need to change your booking? Use the buttons above<br>&bull; Contact us if you have any questions"}
            </p>
        </td></tr>
        </table>
    </td></tr>
    <!-- Divider + contact -->
    <tr><td style="padding:0 40px 36px;">
        <div style="border-top:1px solid #eee;padding-top:24px;text-align:center;">
            <p style="color:#999;font-size:13px;margin:0;">
                Need to reschedule? Contact us directly.<br>
                <strong style="color:#8b5cf6;">{biz_name}</strong>
            </p>
        </div>
    </td></tr>
    <!-- Bottom bar -->
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>"""

    variables = {
        "patient_name": customer_name,
        "doctor_name": doctor_name or "",
        "date": date_display,
        "time": time_display,
        "service_name": service_name or "",
        "confirm_link": confirm_url or "#",
        "cancel_link": cancel_url or "#",
        "booking_id": "",
        "clinic_name": biz_name,
    }
    return _send_email(customer_email, subject, _wrap_luxury(content, admin_id=admin_id, variables=variables), from_name=biz_name, admin_id=admin_id)


# ── Booking Notification (Owner) ─────────────────────────────────────────────

def send_booking_notification_owner(customer_name, customer_email, customer_phone, date_display, time_display, admin_id=None):
    """Notify the business owner of a new booking."""
    if not BUSINESS_EMAIL:
        print("[Email] No BUSINESS_EMAIL configured, skipping owner notification.")
        return False

    biz_name = _get_admin_business_name(admin_id)
    subject = f"New Booking: {customer_name} — {date_display} at {time_display}"
    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#2563eb,#7c3aed,#2563eb);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628,#162040);padding:36px 40px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:24px;font-weight:300;">New <strong>Appointment</strong> Booked</h1>
        <p style="margin:8px 0 0;color:#7c93c3;font-size:13px;">Via {biz_name} Chatbot</p>
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

    return _send_email(BUSINESS_EMAIL, subject, _wrap_luxury(content, admin_id=admin_id), from_name=biz_name, admin_id=admin_id)


# ── 2FA OTP Email ────────────────────────────────────────────────────────────

def send_otp_email(to_email, user_name, otp_code):
    """Send 2FA OTP code to user."""
    subject = f"Your verification code: {otp_code}"
    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628,#162040);padding:48px 40px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:24px;font-weight:300;">Verification <strong>Code</strong></h1>
        <p style="margin:8px 0 0;color:#8b5cf6;font-size:13px;letter-spacing:2px;text-transform:uppercase;">Secure Login</p>
    </td></tr>
    <tr><td style="padding:36px 40px;text-align:center;">
        <p style="color:#555;font-size:15px;margin:0 0 24px;">Hi <strong style="color:#1a1a2e;">{user_name}</strong>, here is your one-time code:</p>
        <div style="background:linear-gradient(135deg,#faf8ff,#f3f0ff);border:2px solid rgba(139,92,246,0.15);border-radius:12px;padding:24px;display:inline-block;">
            <span style="font-size:36px;font-weight:800;letter-spacing:12px;color:#1a1a2e;font-family:'Courier New',monospace;">{otp_code}</span>
        </div>
        <p style="color:#e53e3e;font-size:13px;margin:20px 0 0;font-weight:600;">Expires in 5 minutes. Do not share this code.</p>
    </td></tr>
    <tr><td style="padding:0 40px 36px;text-align:center;">
        <p style="color:#999;font-size:12px;margin:0;">If you didn't request this, please ignore this email.</p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content))


# ── Customer Verification Email ──────────────────────────────────────────────

def send_customer_verification(to_email, business_name, verification_url):
    """Send email verification to new SaaS customer."""
    subject = f"Verify your account — {business_name}"
    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628,#162040);padding:48px 40px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:28px;font-weight:300;">Welcome to <strong>ChatGenius</strong></h1>
        <p style="margin:12px 0 0;color:#8b5cf6;font-size:14px;letter-spacing:2px;text-transform:uppercase;">One step to go</p>
    </td></tr>
    <tr><td style="padding:36px 40px;text-align:center;">
        <p style="color:#555;font-size:15px;line-height:1.6;margin:0 0 28px;">
            Hi <strong style="color:#1a1a2e;">{business_name}</strong>,<br>
            Please verify your email to activate your account and start using the platform.
        </p>
        <a href="{verification_url}" style="display:inline-block;background:linear-gradient(135deg,#8b5cf6,#7c3aed,#a78bfa);color:#ffffff;padding:16px 48px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;letter-spacing:0.5px;box-shadow:0 8px 24px rgba(139,92,246,0.4);text-transform:uppercase;">
            Verify My Account
        </a>
        <p style="color:#999;font-size:12px;margin:24px 0 0;">Or copy this link:<br>
            <a href="{verification_url}" style="color:#8b5cf6;word-break:break-all;font-size:11px;">{verification_url}</a>
        </p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content))


# ── Pre-Visit Form Email ────────────────────────────────────────────────────

def send_previsit_form(to_email, patient_name, form_url, date_display, time_display, doctor_name="", admin_id=None):
    """Send pre-visit form link to patient before appointment."""
    biz_name = _get_admin_business_name(admin_id)
    doctor_line = f" with <strong>Dr. {doctor_name}</strong>" if doctor_name else ""
    subject = f"Complete Your Pre-Visit Form — {date_display}"
    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628,#162040);padding:48px 40px;text-align:center;">
        <div style="width:64px;height:64px;margin:0 auto 16px;border-radius:50%;background:linear-gradient(135deg,#8b5cf6,#a78bfa);line-height:64px;">
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
        <a href="{form_url}" style="display:inline-block;background:linear-gradient(135deg,#8b5cf6,#7c3aed,#a78bfa);color:#ffffff;padding:16px 48px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;letter-spacing:0.5px;box-shadow:0 8px 24px rgba(139,92,246,0.4);text-transform:uppercase;">
            Complete Form Now
        </a>
    </td></tr>
    <tr><td style="padding:16px 40px 36px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8f9ff;border-radius:10px;border-left:4px solid #8b5cf6;">
        <tr><td style="padding:16px 20px;">
            <p style="color:#666;font-size:13px;line-height:1.6;margin:0;">
                Takes about <strong>2 minutes</strong> to complete. Your information is kept secure and confidential.
            </p>
        </td></tr>
        </table>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>"""

    variables = {"patient_name": patient_name, "doctor_name": doctor_name or "", "date": date_display, "time": time_display, "clinic_name": biz_name, "confirm_link": form_url}
    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id, variables=variables), from_name=biz_name, admin_id=admin_id)


# ── Waitlist Notification Email ──────────────────────────────────────────────

def send_waitlist_notification(to_email, patient_name, date_display, time_slot, confirm_deadline, confirm_url="", doctor_name="", admin_id=None):
    """Notify waitlisted patient that a slot opened up.
    Includes patient name, doctor name, date/time, deadline, and confirm link."""
    biz_name = _get_admin_business_name(admin_id)
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

    variables = {"patient_name": patient_name, "doctor_name": doctor_name or "", "date": date_display, "time": time_slot, "clinic_name": biz_name, "confirm_link": confirm_url or "#"}
    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id, variables=variables), from_name=biz_name, admin_id=admin_id)


# ── External Waitlist Placement Email ────────────────────────────────────────

def send_waitlist_placed_email(to_email, patient_name, date_display, time_slot, doctor_name="", confirm_url="", remove_url="", position=1, admin_id=None):
    """Notify patient from external booking that they've been placed on a waitlist.
    Includes confirm (stay on waitlist) and remove (leave waitlist) buttons."""
    biz_name = _get_admin_business_name(admin_id)
    subject = f"You've Been Placed on a Waitlist — {date_display}"

    doctor_html = ""
    if doctor_name:
        doctor_html = f'<p style="margin:4px 0;font-size:15px;"><strong style="color:#92400e;">Doctor:</strong> <span style="color:#1a1a2e;">Dr. {doctor_name}</span></p>'

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#d97706,#f59e0b,#fbbf24,#f59e0b,#d97706);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#78350f,#92400e);padding:48px 40px;text-align:center;">
        <div style="width:64px;height:64px;margin:0 auto 16px;border-radius:50%;background:linear-gradient(135deg,#fbbf24,#f59e0b);line-height:64px;">
            <span style="font-size:28px;">&#9200;</span>
        </div>
        <h1 style="margin:0;color:#fff;font-size:24px;font-weight:300;">You're on the <strong>Waitlist</strong></h1>
    </td></tr>
    <tr><td style="padding:36px 40px;">
        <p style="color:#555;font-size:15px;line-height:1.6;margin:0;">
            Hi <strong style="color:#1a1a2e;">{patient_name}</strong>,
            the time slot you requested is currently taken. You've been placed on the waitlist at <strong>position #{position}</strong>.
            If the current appointment is cancelled, you'll be automatically moved in.
        </p>
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#fffbeb;border-radius:12px;border:1px solid #fde68a;margin:20px 0;">
        <tr><td style="padding:24px;">
            {doctor_html}
            <p style="margin:4px 0;font-size:15px;"><strong style="color:#92400e;">Date:</strong> <span style="color:#1a1a2e;">{date_display}</span></p>
            <p style="margin:4px 0;font-size:15px;"><strong style="color:#92400e;">Time:</strong> <span style="color:#1a1a2e;">{time_slot}</span></p>
            <p style="margin:4px 0;font-size:15px;"><strong style="color:#92400e;">Position:</strong> <span style="color:#1a1a2e;">#{position} in queue</span></p>
        </td></tr>
        </table>
    </td></tr>
    <tr><td style="padding:0 40px 12px;text-align:center;">
        <a href="{confirm_url}" style="display:inline-block;background:linear-gradient(135deg,#059669,#10b981);color:#fff;padding:16px 40px;border-radius:50px;text-decoration:none;font-weight:700;font-size:14px;box-shadow:0 8px 24px rgba(5,150,105,0.3);margin-right:12px;">
            Yes, Keep Me on Waitlist
        </a>
    </td></tr>
    <tr><td style="padding:0 40px 36px;text-align:center;">
        <a href="{remove_url}" style="display:inline-block;background:linear-gradient(135deg,#dc2626,#ef4444);color:#fff;padding:16px 40px;border-radius:50px;text-decoration:none;font-weight:700;font-size:14px;box-shadow:0 8px 24px rgba(220,38,38,0.3);">
            No, Remove Me from Waitlist
        </a>
    </td></tr>
    <tr><td style="padding:0 40px 24px;text-align:center;">
        <p style="color:#999;font-size:12px;margin:0;">If you do nothing, you'll remain on the waitlist.</p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#d97706,#f59e0b,#fbbf24,#f59e0b,#d97706);"></td></tr>"""

    variables = {"patient_name": patient_name, "doctor_name": doctor_name or "", "date": date_display, "time": time_slot, "clinic_name": biz_name, "confirm_link": confirm_url or "#", "cancel_link": remove_url or "#", "waitlist_position": str(position)}
    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id, variables=variables), from_name=biz_name, admin_id=admin_id)


# ── Waitlist Expired Notification ────────────────────────────────────────────

def send_waitlist_expired_notification(to_email, patient_name, date_display, time_slot, doctor_name="", admin_id=None):
    """Send email to patient who didn't fill the pre-visit form in time."""
    biz_name = _get_admin_business_name(admin_id)
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
            <strong style="color:#8b5cf6;">{biz_name}</strong>
        </p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#dc2626,#ef4444,#f87171,#ef4444,#dc2626);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id), from_name=biz_name, admin_id=admin_id)


# ── Recall / Retention Email ─────────────────────────────────────────────────

def send_recall_email(to_email, patient_name, treatment_type, message="", booking_url="", admin_id=None):
    """Send recall reminder to patient for follow-up treatment."""
    biz_name = _get_admin_business_name(admin_id)
    subject = f"Time for Your {treatment_type} Check-Up"
    if not message:
        message = f"It's been a while since your last {treatment_type}. We recommend scheduling a follow-up to keep your dental health in perfect shape."

    btn_html = ""
    if booking_url:
        btn_html = f"""
        <tr><td style="padding:0 40px 8px;text-align:center;">
            <a href="{booking_url}" style="display:inline-block;background:linear-gradient(135deg,#8b5cf6,#7c3aed,#a78bfa);color:#ffffff;padding:16px 48px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;box-shadow:0 8px 24px rgba(139,92,246,0.4);text-transform:uppercase;">
                Book Now
            </a>
        </td></tr>"""

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628,#162040);padding:48px 40px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:28px;font-weight:300;">We <strong>Miss You!</strong></h1>
        <p style="margin:12px 0 0;color:#8b5cf6;font-size:14px;letter-spacing:1px;">It's time for a check-up</p>
    </td></tr>
    <tr><td style="padding:36px 40px;">
        <p style="color:#555;font-size:15px;line-height:1.6;margin:0;">
            Dear <strong style="color:#1a1a2e;">{patient_name}</strong>,
        </p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">{message}</p>
    </td></tr>
    {btn_html}
    <tr><td style="padding:24px 40px 36px;text-align:center;">
        <p style="color:#999;font-size:13px;margin:0;">— {biz_name}</p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>"""

    variables = {"patient_name": patient_name, "clinic_name": biz_name, "recall_treatment": treatment_type or "", "confirm_link": booking_url or "#"}
    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id, variables=variables), from_name=biz_name, admin_id=admin_id)


# ── Treatment Follow-Up Email ────────────────────────────────────────────────

def send_treatment_followup(to_email, patient_name, treatment_name, day_number, booking_url="", admin_id=None):
    """Send treatment follow-up check-in email."""
    biz_name = _get_admin_business_name(admin_id)
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
            <a href="{booking_url}" style="display:inline-block;background:linear-gradient(135deg,#8b5cf6,#7c3aed,#a78bfa);color:#ffffff;padding:16px 48px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;box-shadow:0 8px 24px rgba(139,92,246,0.4);text-transform:uppercase;">
                Book Follow-Up
            </a>
        </td></tr>"""

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>
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
        <p style="color:#999;font-size:13px;margin:0;">Your health is our priority.<br><strong style="color:#8b5cf6;">{biz_name}</strong></p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>"""

    variables = {"patient_name": patient_name, "clinic_name": biz_name, "confirm_link": booking_url or "#", "followup_date": ""}
    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id, variables=variables), from_name=biz_name, admin_id=admin_id)


# ── Booking Cancellation (Customer) ─────────────────────────────────────────

def send_booking_cancellation(to_email, customer_name, date_display, time_display, doctor_name="", reason="", admin_id=None):
    """Notify the customer that their appointment has been cancelled by the clinic."""
    biz_name = _get_admin_business_name(admin_id)
    ctype = _get_company_type(admin_id)
    subject = f"Your Appointment Has Been Cancelled — {date_display}"

    doctor_row = ""
    if doctor_name:
        _lbl = "Doctor" if ctype == "dental" else "Specialist"
        _pfx = "Dr. " if ctype == "dental" else ""
        doctor_row = f"""
        <tr><td style="padding:8px 0;border-bottom:1px solid #f0f0f0;">
            <span style="color:#999;font-size:13px;text-transform:uppercase;letter-spacing:1px;">{_lbl}</span><br>
            <span style="color:#1a1a2e;font-size:16px;font-weight:600;">{_pfx}{doctor_name}</span>
        </td></tr>"""

    reason_block = ""
    if reason:
        reason_block = f"""
        <tr><td style="padding:20px 40px 0;">
            <div style="background:#fff8e1;border-left:4px solid #8b5cf6;padding:14px 18px;border-radius:6px;">
                <div style="color:#999;font-size:12px;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Reason</div>
                <div style="color:#1a1a2e;font-size:14px;line-height:1.5;">{reason}</div>
            </div>
        </td></tr>"""

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>
    <tr><td style="padding:40px 40px 16px;text-align:center;">
        <h1 style="color:#1a1a2e;font-size:24px;margin:0 0 8px;font-weight:700;">Appointment Cancelled</h1>
        <p style="color:#666;font-size:15px;margin:0;">Dear {customer_name},</p>
    </td></tr>
    <tr><td style="padding:16px 40px;">
        <p style="color:#444;font-size:15px;line-height:1.6;margin:0;">
            Unfortunately, we had to cancel your appointment scheduled for
            <strong>{date_display}</strong> at <strong>{time_display}</strong>.
            We sincerely apologize for any inconvenience this may cause.
        </p>
    </td></tr>
    <tr><td style="padding:8px 40px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#fafafa;border-radius:10px;padding:20px;">
            {doctor_row}
            <tr><td style="padding:8px 0;border-bottom:1px solid #f0f0f0;">
                <span style="color:#999;font-size:13px;text-transform:uppercase;letter-spacing:1px;">Date</span><br>
                <span style="color:#1a1a2e;font-size:16px;font-weight:600;">{date_display}</span>
            </td></tr>
            <tr><td style="padding:8px 0;">
                <span style="color:#999;font-size:13px;text-transform:uppercase;letter-spacing:1px;">Time</span><br>
                <span style="color:#1a1a2e;font-size:16px;font-weight:600;">{time_display}</span>
            </td></tr>
        </table>
    </td></tr>
    {reason_block}
    <tr><td style="padding:24px 40px 40px;text-align:center;">
        <p style="color:#666;font-size:14px;line-height:1.6;margin:0 0 12px;">
            You're welcome to book a new appointment at any time that suits you.
        </p>
        <p style="color:#999;font-size:13px;margin:0;">Thank you for your understanding.<br><strong style="color:#8b5cf6;">{biz_name}</strong></p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>"""

    variables = {"patient_name": customer_name, "doctor_name": doctor_name or "", "date": date_display, "time": time_display, "clinic_name": biz_name}
    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id, variables=variables), from_name=biz_name, admin_id=admin_id)


# ── Booking Reschedule Notification ──────────────────────────────────────────

def send_booking_reschedule(to_email, customer_name, old_date, old_time, new_date, new_time, doctor_name="", service_name="", admin_id=None):
    """Notify the customer that their appointment has been rescheduled by the clinic."""
    biz_name = _get_admin_business_name(admin_id)
    ctype = _get_company_type(admin_id)
    subject = f"Your Appointment Has Been Rescheduled — {new_date}"

    doctor_row = ""
    if doctor_name:
        _lbl = "Doctor" if ctype == "dental" else "Specialist"
        _pfx = "Dr. " if ctype == "dental" else ""
        doctor_row = f"""
        <tr><td style="padding:8px 0;border-bottom:1px solid #f0f0f0;">
            <span style="color:#999;font-size:13px;text-transform:uppercase;letter-spacing:1px;">{_lbl}</span><br>
            <span style="color:#1a1a2e;font-size:16px;font-weight:600;">{_pfx}{doctor_name}</span>
        </td></tr>"""

    service_row = ""
    if service_name:
        service_row = f"""
        <tr><td style="padding:8px 0;border-bottom:1px solid #f0f0f0;">
            <span style="color:#999;font-size:13px;text-transform:uppercase;letter-spacing:1px;">Service</span><br>
            <span style="color:#1a1a2e;font-size:16px;font-weight:600;">{service_name}</span>
        </td></tr>"""

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628 0%,#162040 50%,#1a2550 100%);padding:48px 40px;text-align:center;">
        <div style="width:72px;height:72px;margin:0 auto 20px;border-radius:50%;background:linear-gradient(135deg,#8b5cf6,#a78bfa);display:flex;align-items:center;justify-content:center;">
            <span style="font-size:36px;line-height:72px;">&#128197;</span>
        </div>
        <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:300;letter-spacing:1px;">Appointment <strong style="font-weight:700;">Rescheduled</strong></h1>
        <p style="margin:12px 0 0;color:#8b5cf6;font-size:14px;letter-spacing:2px;text-transform:uppercase;">Updated Details Below</p>
    </td></tr>
    <tr><td style="padding:32px 40px 8px;">
        <p style="color:#444;font-size:15px;line-height:1.6;margin:0;">
            Dear {customer_name},<br><br>
            Your appointment has been rescheduled. Please see the updated details below.
        </p>
    </td></tr>
    <tr><td style="padding:8px 40px;">
        <div style="background:#fff8e1;border-left:4px solid #8b5cf6;padding:14px 18px;border-radius:6px;margin-bottom:16px;">
            <div style="color:#999;font-size:12px;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Previous Appointment</div>
            <div style="color:#666;font-size:14px;text-decoration:line-through;">{old_date} at {old_time}</div>
        </div>
    </td></tr>
    <tr><td style="padding:0 40px 16px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0fdf4;border-radius:10px;padding:20px;border:1px solid #bbf7d0;">
            <tr><td style="padding:8px 0;border-bottom:1px solid #dcfce7;">
                <span style="color:#16a34a;font-size:13px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">&#10003; New Appointment</span>
            </td></tr>
            <tr><td style="padding:8px 0;border-bottom:1px solid #dcfce7;">
                <span style="color:#999;font-size:13px;text-transform:uppercase;letter-spacing:1px;">Date</span><br>
                <span style="color:#1a1a2e;font-size:16px;font-weight:600;">{new_date}</span>
            </td></tr>
            <tr><td style="padding:8px 0;border-bottom:1px solid #dcfce7;">
                <span style="color:#999;font-size:13px;text-transform:uppercase;letter-spacing:1px;">Time</span><br>
                <span style="color:#1a1a2e;font-size:16px;font-weight:600;">{new_time}</span>
            </td></tr>
            {doctor_row}
            {service_row}
        </table>
    </td></tr>
    <tr><td style="padding:16px 40px 40px;text-align:center;">
        <p style="color:#666;font-size:14px;line-height:1.6;margin:0 0 12px;">
            If you have any questions or need to make further changes, please don't hesitate to contact us.
        </p>
        <p style="color:#999;font-size:13px;margin:0;">Thank you for your understanding.<br><strong style="color:#8b5cf6;">{biz_name}</strong></p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>"""

    variables = {"patient_name": customer_name, "doctor_name": doctor_name or "", "date": new_date, "time": new_time, "clinic_name": biz_name}
    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id, variables=variables), from_name=biz_name, admin_id=admin_id)


# ── Lead Follow-Up Email ──────────────────────────────────────────────────────

def send_lead_followup(to_email, lead_name, treatment_interest="", day_number=1, admin_id=None):
    """Send a personalized follow-up email to a lead based on day number."""
    biz_name = _get_admin_business_name(admin_id)
    first_name = (lead_name or "there").split()[0]
    treatment = treatment_interest or "dental care"

    if day_number <= 1:
        subject = f"Thanks for your interest, {first_name}!"
        heading = "We&#8217;d Love to Help You"
        message = (f"Hi {first_name},<br><br>"
            f"Thanks for reaching out to us about <strong>{treatment}</strong>! "
            "We&#8217;d love to help you take the next step toward a healthier, brighter smile.<br><br>"
            "If you have any questions &#8212; about the procedure, pricing, or what to expect &#8212; our team "
            "is here to help. We also offer <strong>flexible payment plans</strong> to make treatment easy on your budget.<br><br>"
            "Ready to get started? Book a consultation at your convenience &#8212; no commitment needed.")
    elif day_number <= 3:
        subject = f"Still thinking about {treatment}, {first_name}?"
        heading = "Your Smile Journey Awaits"
        message = (f"Hi {first_name},<br><br>"
            f"We noticed you were interested in <strong>{treatment}</strong> and wanted to follow up.<br><br>"
            "Many of our patients had questions before their first visit too &#8212; and they&#8217;re glad they took "
            "the step! Our doctors take the time to explain everything and make sure you&#8217;re completely "
            "comfortable before any treatment begins.<br><br>"
            "Would you like to book a <strong>free consultation</strong>? It&#8217;s a great way to get all your "
            "questions answered with zero pressure.")
    else:
        subject = f"We're here whenever you're ready, {first_name}"
        heading = "One Last Thought"
        message = (f"Hi {first_name},<br><br>"
            f"Just a gentle follow-up about <strong>{treatment}</strong>. We know life gets busy, "
            "so we wanted to let you know our door is always open.<br><br>"
            "If timing or cost is a concern, we&#8217;d be happy to work with you on a plan that fits "
            "your schedule and budget. Many patients are surprised at how affordable and quick the "
            "process can be.<br><br>"
            "Whenever you&#8217;re ready, we&#8217;d love to see you. No rush at all.")

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>
    <tr><td style="padding:40px 40px 20px;text-align:center;">
        <h1 style="color:#1a1a2e;font-size:22px;margin:0;">{heading}</h1>
    </td></tr>
    <tr><td style="padding:10px 40px 30px;">
        <p style="color:#555;font-size:15px;line-height:1.7;margin:0;">{message}</p>
    </td></tr>
    <tr><td style="padding:0 40px 30px;text-align:center;">
        <p style="color:#999;font-size:13px;margin:0;">
            We look forward to welcoming you.<br>
            <strong style="color:#8b5cf6;">{biz_name}</strong>
        </p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id), from_name=biz_name, admin_id=admin_id)


def _parse_product_images(imgs):
    """Safely parse product images field."""
    import json
    if isinstance(imgs, list):
        return imgs
    if isinstance(imgs, str):
        try:
            return json.loads(imgs)
        except Exception:
            return []
    return []


def send_lead_outreach(to_email, lead_name, business_name=None, product_interest="",
                       hero_product=None, related_products=None, company_info=None, admin_id=None):
    """Send a conversion-focused sales email with product showcase, discount code, and action buttons."""
    import json
    first_name = (lead_name or "there").split()[0]
    ci = company_info or {}
    biz = business_name or _get_admin_business_name(admin_id)
    logo = ci.get("logo_url", "")
    store_img = ci.get("store_image", "")
    domain = ci.get("domain", "")
    store_url = f"https://{domain}" if domain else ""
    phone = ci.get("phone", "")
    related = related_products or []

    # ── Subject line ──
    if hero_product:
        hname = hero_product.get("product_name", "")
        subject = f"\U0001f525 {first_name}, your {hname} is still in stock — grab it before it's gone!"
    elif product_interest:
        subject = f"\u23F0 {first_name}, your {product_interest} won't last long!"
    else:
        subject = f"\U0001f381 {first_name}, we saved something special for you"

    # ── Logo ──
    logo_html = (f'<img src="{logo}" alt="{biz}" style="height:40px;max-width:180px;display:block">'
                 if logo else f'<span style="font-size:22px;font-weight:900;color:#111;letter-spacing:-0.5px">{biz}</span>')

    # ── Hero product ──
    hero_html = ""
    if hero_product:
        hp = hero_product
        imgs = _parse_product_images(hp.get("product_images", "[]"))
        hero_img = imgs[0] if imgs else ""
        hero_name = hp.get("product_name", "")
        hero_desc = hp.get("product_short_description", "") or ""
        hero_desc = hero_desc[:150]
        price = float(hp.get("product_price", 0))
        compare = float(hp.get("compare_at_price", 0))
        hero_url = hp.get("product_url", "") or store_url
        category = hp.get("product_category", "")
        stock = int(hp.get("inventory_quantity", 0))
        ships_free = hp.get("ships_free", False)
        rating = float(hp.get("product_rating", 0))
        review_count = int(hp.get("product_review_count", 0))

        # Price
        if compare > price and compare > 0:
            save_amt = compare - price
            price_html = (f'<span style="font-size:28px;font-weight:900;color:#111">${price:.2f}</span>'
                          f'<span style="text-decoration:line-through;color:#999;font-size:16px;margin-left:8px">${compare:.2f}</span>')
            save_badge = f'<span style="display:inline-block;background:#fee2e2;color:#dc2626;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:800;margin-left:8px">SAVE ${save_amt:.0f}</span>'
        else:
            price_html = f'<span style="font-size:28px;font-weight:900;color:#111">${price:.2f}</span>'
            save_badge = ""

        # Stars
        stars = ""
        if rating > 0:
            full = int(rating)
            stars = (f'<div style="margin:8px 0">'
                     f'<span style="color:#f59e0b;font-size:16px;letter-spacing:2px">{"\u2605" * full}{"\u2606" * (5 - full)}</span>'
                     f'<span style="color:#666;font-size:12px;margin-left:6px">{rating:.1f} ({review_count} reviews)</span>'
                     f'</div>')

        # Stock urgency
        stock_html = ""
        if 0 < stock <= 10:
            stock_html = f'<div style="margin-top:12px;padding:10px 16px;background:#fef3c7;border-radius:8px;border:1px solid #fde68a"><span style="font-size:13px;color:#92400e;font-weight:600">\u23F0 Only {stock} left in stock — order soon!</span></div>'
        elif stock == 0:
            stock_html = '<div style="margin-top:12px;padding:10px 16px;background:#fef2f2;border-radius:8px;border:1px solid #fecaca"><span style="font-size:13px;color:#991b1b;font-weight:600">\U0001f525 Almost sold out — hurry!</span></div>'

        # Free shipping
        ship_html = '<div style="margin-top:8px"><span style="font-size:12px;color:#059669;font-weight:600">\U0001f69a Free shipping on this item</span></div>' if ships_free else ''

        # Gallery
        gallery = ""
        if len(imgs) > 1:
            thumbs = "".join(
                f'<td style="padding:4px"><img src="{im}" style="width:100%;height:80px;object-fit:cover;border-radius:8px;display:block;border:1px solid #eee"></td>'
                for im in imgs[1:4]
            )
            gallery = f'<table style="width:100%;border-collapse:collapse;margin-top:12px"><tr>{thumbs}</tr></table>'

        hero_html = f'''
    <tr><td style="padding:0 24px 20px">
        <table style="width:100%;border-collapse:collapse;border-radius:16px;overflow:hidden;border:1px solid #f0f0f0;box-shadow:0 4px 20px rgba(0,0,0,0.06)" cellpadding="0" cellspacing="0">
            <!-- Product image -->
            {"<tr><td style='padding:0;background:#f8f8f8'><img src='" + hero_img + "' alt='" + hero_name + "' style='width:100%;max-height:360px;object-fit:contain;display:block;margin:0 auto'></td></tr>" if hero_img else ""}
            {gallery}
            <!-- Product info -->
            <tr><td style="padding:24px 28px">
                {"<div style='margin-bottom:6px'><span style='font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#888;font-weight:700'>" + category + "</span></div>" if category else ""}
                <h2 style="margin:0 0 4px;font-size:22px;font-weight:900;color:#111;line-height:1.3">{hero_name}</h2>
                {stars}
                <div style="margin:12px 0">{price_html}{save_badge}</div>
                {"<p style='margin:0 0 12px;font-size:14px;color:#555;line-height:1.6'>" + hero_desc + "</p>" if hero_desc else ""}
                {ship_html}
                {stock_html}
                <!-- CTA Button -->
                <div style="margin-top:20px">
                    <a href="{hero_url}" style="display:inline-block;padding:16px 48px;background:#111;color:#fff;text-decoration:none;border-radius:50px;font-size:15px;font-weight:800;letter-spacing:0.5px;text-transform:uppercase;box-shadow:0 4px 14px rgba(0,0,0,0.2)">\U0001f6d2 Complete Your Order</a>
                </div>
            </td></tr>
        </table>
    </td></tr>'''

    # ── Discount code section ──
    discount_html = ""
    if hero_product:
        compare = float(hero_product.get("compare_at_price", 0))
        price = float(hero_product.get("product_price", 0))
        if compare > price and compare > 0:
            code = "COMEBACK10"
            discount_html = f'''
    <tr><td style="padding:0 24px 20px">
        <table style="width:100%;border-collapse:collapse;background:linear-gradient(135deg,#111 0%,#1a1a2e 100%);border-radius:12px;overflow:hidden" cellpadding="0" cellspacing="0">
            <tr><td style="padding:24px 28px;text-align:center">
                <div style="font-size:28px;margin-bottom:8px">\U0001f381</div>
                <div style="font-size:12px;text-transform:uppercase;letter-spacing:2px;color:#999;font-weight:700;margin-bottom:6px">Exclusive Offer</div>
                <div style="font-size:24px;font-weight:900;color:#fff;margin-bottom:4px">10% OFF Your Order</div>
                <div style="font-size:13px;color:#f59e0b;margin-bottom:16px">\u23F0 Expires in 48 hours</div>
                <div style="display:inline-block;padding:12px 32px;background:rgba(255,255,255,0.1);border:2px dashed rgba(255,255,255,0.3);border-radius:8px;margin-bottom:12px">
                    <span style="font-size:20px;font-weight:900;color:#fff;letter-spacing:3px;font-family:monospace">{code}</span>
                </div>
                <div>
                    <a href="{hero_product.get('product_url', '') or store_url}" style="display:inline-block;padding:12px 32px;background:#f59e0b;color:#111;text-decoration:none;border-radius:50px;font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:0.5px">Apply & Shop Now \u2192</a>
                </div>
            </td></tr>
        </table>
    </td></tr>'''

    # ── Related products ──
    related_html = ""
    if related:
        cards = ""
        for rp in related[:3]:
            rimgs = _parse_product_images(rp.get("product_images", "[]"))
            rimg = rimgs[0] if rimgs else ""
            rname = rp.get("product_name", "")
            rprice = float(rp.get("product_price", 0))
            rurl = rp.get("product_url", "") or store_url

            cards += f'''<td style="width:33.33%;padding:0 6px;vertical-align:top">
                <table style="width:100%;border-collapse:collapse" cellpadding="0" cellspacing="0">
                    <tr><td style="padding:0">{"<img src='" + rimg + "' style='width:100%;height:140px;object-fit:cover;border-radius:10px;display:block;border:1px solid #eee'>" if rimg else "<div style='height:140px;background:#f5f5f5;border-radius:10px;display:flex;align-items:center;justify-content:center'><span style='font-size:32px'>\U0001f6cd\ufe0f</span></div>"}</td></tr>
                    <tr><td style="padding:10px 2px 0">
                        <p style="margin:0 0 4px;font-size:12px;font-weight:700;color:#111;line-height:1.3">{rname[:35]}{"..." if len(rname) > 35 else ""}</p>
                        <p style="margin:0 0 8px;font-size:14px;font-weight:900;color:#111">${rprice:.2f}</p>
                        <a href="{rurl}" style="display:inline-block;padding:8px 16px;background:#111;color:#fff;text-decoration:none;border-radius:20px;font-size:11px;font-weight:700">View</a>
                    </td></tr>
                </table>
            </td>'''

        related_html = f'''
    <tr><td style="padding:4px 24px 4px">
        <div style="border-top:1px solid #eee;margin-bottom:16px"></div>
        <h3 style="margin:0 0 14px;font-size:15px;font-weight:900;color:#111">You Might Also Like \U0001f447</h3>
    </td></tr>
    <tr><td style="padding:0 18px 24px">
        <table style="width:100%;border-collapse:collapse" cellpadding="0" cellspacing="0"><tr>{cards}</tr></table>
    </td></tr>'''

    # ── Help section ──
    help_html = f'''
    <tr><td style="padding:0 24px 24px">
        <table style="width:100%;border-collapse:collapse;background:#f8f9fa;border-radius:12px;overflow:hidden" cellpadding="0" cellspacing="0">
            <tr><td style="padding:20px 24px;text-align:center">
                <div style="font-size:16px;font-weight:800;color:#111;margin-bottom:10px">\U0001f4ac Need help deciding?</div>
                <div style="display:inline-block">
                    {"<a href='" + store_url + "' style='display:inline-block;padding:10px 24px;background:#111;color:#fff;text-decoration:none;border-radius:20px;font-size:12px;font-weight:700;margin:0 4px'>Chat With Us</a>" if store_url else ""}
                    {"<a href='tel:" + phone + "' style='display:inline-block;padding:10px 24px;background:#fff;color:#111;text-decoration:none;border-radius:20px;font-size:12px;font-weight:700;border:2px solid #111;margin:0 4px'>\u260E Call Us</a>" if phone else ""}
                    <a href="mailto:{SMTP_USER}" style="display:inline-block;padding:10px 24px;background:#fff;color:#111;text-decoration:none;border-radius:20px;font-size:12px;font-weight:700;border:2px solid #111;margin:0 4px">\u2709 Email</a>
                </div>
            </td></tr>
        </table>
    </td></tr>'''

    # ── Trust bar ──
    trust_html = f'''
    <tr><td style="padding:0 24px 20px">
        <table style="width:100%;border-collapse:collapse" cellpadding="0" cellspacing="0">
            <tr>
                <td style="text-align:center;padding:8px"><span style="font-size:13px;color:#666">\U0001f69a Free Shipping</span></td>
                <td style="text-align:center;padding:8px"><span style="font-size:13px;color:#666">\U0001f504 Easy Returns</span></td>
                <td style="text-align:center;padding:8px"><span style="font-size:13px;color:#666">\U0001f512 Secure Payment</span></td>
            </tr>
        </table>
    </td></tr>'''

    # ── Full email ──
    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
<div style="display:none;max-height:0;overflow:hidden;font-size:1px;color:#f0f0f0">
    {first_name}, {"your " + hero_product.get("product_name", "") + " is waiting" if hero_product else "we picked something for you"} + 10% off inside&nbsp;&zwnj;&nbsp;&zwnj;
</div>

<table style="width:100%;max-width:600px;margin:0 auto;background:#ffffff" cellpadding="0" cellspacing="0">

    <!-- Header -->
    <tr><td style="padding:24px 28px;border-bottom:1px solid #f0f0f0">
        <table style="width:100%;border-collapse:collapse" cellpadding="0" cellspacing="0"><tr>
            <td>{logo_html}</td>
            <td style="text-align:right">
                {"<a href='" + store_url + "' style='color:#111;text-decoration:none;font-size:13px;font-weight:700'>Shop \u2192</a>" if store_url else ""}
            </td>
        </tr></table>
    </td></tr>

    <!-- Hero greeting -->
    <tr><td style="padding:32px 28px 24px">
        <h1 style="margin:0 0 12px;font-size:28px;font-weight:900;color:#111;line-height:1.2">
            Hey {first_name}! \U0001f44b
        </h1>
        <p style="margin:0;font-size:16px;color:#555;line-height:1.7">
            {"Your <strong>" + (hero_product.get("product_name", "") if hero_product else product_interest) + "</strong> picks are waiting. We saved them + added <strong style='color:#dc2626'>10% off</strong>." if (hero_product or product_interest) else "We picked some items just for you \u2014 and added a little something extra inside \U0001f381"}
        </p>
    </td></tr>

    {hero_html}

    {discount_html}

    {related_html}

    {help_html}

    {trust_html}

    <!-- Footer -->
    <tr><td style="padding:24px 28px;background:#111;text-align:center">
        <p style="margin:0 0 8px;font-size:14px;font-weight:700;color:#fff">{biz}</p>
        {"<p style='margin:0 0 12px;font-size:12px;color:#888'>" + domain + "</p>" if domain else ""}
        <p style="margin:0;font-size:11px;color:#666">
            {"<a href='" + store_url + "' style='color:#888;text-decoration:underline;margin:0 8px'>Shop</a>" if store_url else ""}
            <a href="mailto:{SMTP_USER}" style="color:#888;text-decoration:underline;margin:0 8px">Contact</a>
            <a href="mailto:{SMTP_USER}?subject=Unsubscribe" style="color:#666;text-decoration:underline;margin:0 8px">Unsubscribe</a>
        </p>
    </td></tr>

</table>
</body></html>'''
    return _send_email(to_email, subject, html, from_name=biz, admin_id=admin_id)


def send_service_available_notification(to_email, patient_name, service_name, doctor_names=None, admin_id=None):
    """Notify a patient that a doctor is now available for a service they were interested in."""
    biz_name = _get_admin_business_name(admin_id)
    subject = f"Great News — {service_name} Now Available!"
    docs_text = ""
    if doctor_names:
        if len(doctor_names) == 1:
            docs_text = f"<p style='color:#555;font-size:15px;line-height:1.7;margin:10px 0;'>Our specialist <strong style=\"color:#8b5cf6;\">{doctor_names[0]}</strong> is now available to help you.</p>"
        else:
            names_list = ", ".join(doctor_names[:-1]) + f" and {doctor_names[-1]}"
            docs_text = f"<p style='color:#555;font-size:15px;line-height:1.7;margin:10px 0;'>Our specialists <strong style=\"color:#8b5cf6;\">{names_list}</strong> are now available to help you.</p>"

    content = f"""
    <tr><td style="padding:30px 40px 10px;">
        <h2 style="color:#1a1a1a;font-size:22px;margin:0;">Great News, {patient_name}!</h2>
    </td></tr>
    <tr><td style="padding:10px 40px 20px;">
        <p style="color:#555;font-size:15px;line-height:1.7;margin:0;">
            You previously expressed interest in <strong style="color:#8b5cf6;">{service_name}</strong>,
            and we're happy to let you know that this service is now available at our clinic!
        </p>
        {docs_text}
        <p style="color:#555;font-size:15px;line-height:1.7;margin:10px 0;">
            We'd love to help you get started. Feel free to book your appointment at your convenience.
        </p>
    </td></tr>
    <tr><td style="padding:0 40px 30px;text-align:center;">
        <p style="color:#999;font-size:13px;margin:0;">
            We look forward to seeing you!<br>
            <strong style="color:#8b5cf6;">{biz_name}</strong>
        </p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id), from_name=biz_name, admin_id=admin_id)


def send_doctor_booking_notification(to_email, doctor_name, patient_name, service_name,
                                     date_display, time_display, patient_notes="", admin_id=None):
    """Notify doctor about a new service booking assigned to them."""
    subject = f"New Service Booking — {service_name}"
    notes_html = ""
    if patient_notes:
        notes_html = f"""
        <tr><td style="padding:0 40px 20px;">
            <div style="background:#f8f7ff;border-left:3px solid #8b5cf6;padding:12px 16px;border-radius:4px;">
                <p style="color:#888;font-size:12px;margin:0 0 4px;text-transform:uppercase;letter-spacing:0.5px;">Patient Notes</p>
                <p style="color:#333;font-size:14px;margin:0;line-height:1.5;">{patient_notes}</p>
            </div>
        </td></tr>"""

    content = f"""
    <tr><td style="padding:30px 40px 10px;">
        <h2 style="color:#1a1a1a;font-size:22px;margin:0;">New Service Booking</h2>
    </td></tr>
    <tr><td style="padding:10px 40px 20px;">
        <p style="color:#555;font-size:15px;line-height:1.7;margin:0;">Hi Dr. {doctor_name},</p>
        <p style="color:#555;font-size:15px;line-height:1.7;margin:10px 0;">A new appointment has been booked for you.</p>
    </td></tr>
    <tr><td style="padding:0 40px 20px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8f7ff;border-radius:10px;padding:20px;">
            <tr><td style="padding:10px 20px;border-bottom:1px solid rgba(139,92,246,0.15);">
                <span style="color:#888;font-size:12px;">PATIENT</span><br>
                <span style="color:#1a1a1a;font-size:15px;font-weight:600;">{patient_name}</span>
            </td></tr>
            <tr><td style="padding:10px 20px;border-bottom:1px solid rgba(139,92,246,0.15);">
                <span style="color:#888;font-size:12px;">SERVICE</span><br>
                <span style="color:#1a1a1a;font-size:15px;font-weight:600;">{service_name}</span>
            </td></tr>
            <tr><td style="padding:10px 20px;border-bottom:1px solid rgba(139,92,246,0.15);">
                <span style="color:#888;font-size:12px;">DATE</span><br>
                <span style="color:#1a1a1a;font-size:15px;">{date_display}</span>
            </td></tr>
            <tr><td style="padding:10px 20px;">
                <span style="color:#888;font-size:12px;">TIME</span><br>
                <span style="color:#1a1a1a;font-size:15px;">{time_display}</span>
            </td></tr>
        </table>
    </td></tr>
    {notes_html}
    <tr><td style="padding:0 40px 30px;">
        <p style="color:#555;font-size:14px;line-height:1.6;margin:0;">Please review and prepare accordingly.</p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id), from_name=_get_admin_business_name(admin_id), admin_id=admin_id)


# ── No-Show Email (Patient) ──────────────────────────────────────────────────

def send_noshow_email(to_email, patient_name, date_display, time_display, doctor_name="", reason_url="", admin_id=None):
    """Ask patient why they missed their appointment, with a link to provide a reason."""
    biz_name = _get_admin_business_name(admin_id)
    subject = f"We Missed You — {date_display}"

    doctor_row = ""
    if doctor_name:
        doctor_row = f"""
        <tr><td style="padding:8px 0;border-bottom:1px solid #f0f0f0;">
            <span style="color:#999;font-size:13px;text-transform:uppercase;letter-spacing:1px;">Doctor</span><br>
            <span style="color:#1a1a2e;font-size:16px;font-weight:600;">Dr. {doctor_name}</span>
        </td></tr>"""

    reason_btn = ""
    if reason_url:
        reason_btn = f"""
        <tr><td style="padding:24px 40px 0;text-align:center;">
            <a href="{reason_url}" style="display:inline-block;background:linear-gradient(135deg,#8b5cf6,#7c3aed);color:#fff;
            text-decoration:none;padding:14px 32px;border-radius:30px;font-weight:700;font-size:15px;">
            Let Us Know Why</a>
        </td></tr>"""

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>
    <tr><td style="padding:40px 40px 16px;text-align:center;">
        <h1 style="color:#1a1a2e;font-size:24px;margin:0 0 8px;font-weight:700;">We Missed You!</h1>
        <p style="color:#666;font-size:15px;margin:0;">Dear {patient_name},</p>
    </td></tr>
    <tr><td style="padding:16px 40px;">
        <p style="color:#444;font-size:15px;line-height:1.6;margin:0;">
            We noticed you weren't able to make it to your appointment on
            <strong>{date_display}</strong> at <strong>{time_display}</strong>.
            We hope everything is okay!
        </p>
    </td></tr>
    <tr><td style="padding:8px 40px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#fafafa;border-radius:10px;padding:20px;">
            {doctor_row}
            <tr><td style="padding:8px 0;border-bottom:1px solid #f0f0f0;">
                <span style="color:#999;font-size:13px;text-transform:uppercase;letter-spacing:1px;">Date</span><br>
                <span style="color:#1a1a2e;font-size:16px;font-weight:600;">{date_display}</span>
            </td></tr>
            <tr><td style="padding:8px 0;">
                <span style="color:#999;font-size:13px;text-transform:uppercase;letter-spacing:1px;">Time</span><br>
                <span style="color:#1a1a2e;font-size:16px;font-weight:600;">{time_display}</span>
            </td></tr>
        </table>
    </td></tr>
    <tr><td style="padding:16px 40px;">
        <p style="color:#444;font-size:15px;line-height:1.6;margin:0;">
            We'd love to understand what happened so we can serve you better.
            Could you take a moment to let us know?
        </p>
    </td></tr>
    {reason_btn}
    <tr><td style="padding:24px 40px 40px;text-align:center;">
        <p style="color:#666;font-size:14px;line-height:1.6;margin:0 0 12px;">
            If you'd like to reschedule, we're happy to find a time that works for you.
        </p>
        <p style="color:#999;font-size:13px;margin:0;">We care about your health.<br><strong style="color:#8b5cf6;">{biz_name}</strong></p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>"""

    variables = {"patient_name": patient_name, "doctor_name": doctor_name or "", "date": date_display, "time": time_display, "clinic_name": biz_name}
    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id, variables=variables), from_name=biz_name, admin_id=admin_id)


# ── No-Show Reason → Doctor Notification ─────────────────────────────────────

def send_noshow_reason_to_doctor(to_email, doctor_name, patient_name, date_display, time_display, reason="", admin_id=None):
    """Forward the patient's no-show reason to the doctor."""
    subject = f"No-Show Reason from {patient_name} — {date_display}"

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>
    <tr><td style="padding:40px 40px 16px;text-align:center;">
        <h1 style="color:#1a1a2e;font-size:24px;margin:0 0 8px;font-weight:700;">No-Show Reason Received</h1>
        <p style="color:#666;font-size:15px;margin:0;">Dr. {doctor_name},</p>
    </td></tr>
    <tr><td style="padding:16px 40px;">
        <p style="color:#444;font-size:15px;line-height:1.6;margin:0;">
            <strong>{patient_name}</strong> provided a reason for missing their appointment
            on <strong>{date_display}</strong> at <strong>{time_display}</strong>:
        </p>
    </td></tr>
    <tr><td style="padding:8px 40px;">
        <div style="background:#fafafa;border-left:4px solid #8b5cf6;padding:16px 20px;border-radius:6px;">
            <div style="color:#1a1a2e;font-size:15px;line-height:1.6;">{reason}</div>
        </div>
    </td></tr>
    <tr><td style="padding:24px 40px 40px;text-align:center;">
        <p style="color:#999;font-size:13px;margin:0;"><strong style="color:#8b5cf6;">{_get_admin_business_name(admin_id)}</strong></p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6);"></td></tr>"""

    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id), from_name=_get_admin_business_name(admin_id), admin_id=admin_id)


# ── Review / Survey Request Email ──────────────────────────────────────────

def send_review_request(to_email, customer_name, review_url, admin_id=None):
    """Send a satisfaction survey / review request to a customer."""
    biz_name = _get_admin_business_name(admin_id)
    ctype = _get_company_type(admin_id)
    is_dental = ctype == "dental"
    is_ecom = ctype == "ecommerce"
    heading = "How Was Your Visit?" if is_dental else ("How Was Your Order?" if is_ecom else "How Was Your Experience?")
    body_text = (f"Thank you for visiting <strong style=\"color:#1a1a2e;\">{biz_name}</strong>! We hope you had a great experience." if is_dental
                 else f"Thank you for shopping with <strong style=\"color:#1a1a2e;\">{biz_name}</strong>! We hope you love your purchase." if is_ecom
                 else f"Thank you for choosing <strong style=\"color:#1a1a2e;\">{biz_name}</strong>! We hope you had a great experience.")
    subject = f"{heading} — {biz_name}"

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#f59e0b,#d97706,#fbbf24,#d97706,#f59e0b);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628,#162040);padding:48px 40px;text-align:center;">
        <div style="width:64px;height:64px;margin:0 auto 16px;border-radius:50%;background:linear-gradient(135deg,#f59e0b,#fbbf24);line-height:64px;">
            <span style="font-size:28px;">&#11088;</span>
        </div>
        <h1 style="margin:0;color:#fff;font-size:24px;font-weight:300;">{heading.replace(heading.split()[-1], '<strong>' + heading.split()[-1] + '</strong>')}</h1>
    </td></tr>
    <tr><td style="padding:36px 40px;">
        <p style="color:#555;font-size:15px;line-height:1.6;margin:0;">
            Dear <strong style="color:#1a1a2e;">{customer_name}</strong>,
        </p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            {body_text}
            Your feedback helps us improve our service.
        </p>
    </td></tr>
    <tr><td style="padding:0 40px 16px;text-align:center;">
        <a href="{review_url}" style="display:inline-block;background:linear-gradient(135deg,#f59e0b,#d97706);color:#ffffff;padding:16px 48px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;letter-spacing:0.5px;box-shadow:0 8px 24px rgba(245,158,11,0.4);text-transform:uppercase;">
            Rate Your Experience
        </a>
    </td></tr>
    <tr><td style="padding:16px 40px 36px;text-align:center;">
        <p style="color:#999;font-size:13px;margin:0;">Takes less than a minute. We truly value your opinion.</p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#f59e0b,#d97706,#fbbf24,#d97706,#f59e0b);"></td></tr>"""

    variables = {"patient_name": customer_name, "clinic_name": biz_name}
    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id, variables=variables), from_name=biz_name, admin_id=admin_id)


# ── Welcome Email ──────────────────────────────────────────────────────────

def send_welcome_email(to_email, customer_name, admin_id=None):
    """Send a welcome email to a new customer on their first booking."""
    biz_name = _get_admin_business_name(admin_id)
    ctype = _get_company_type(admin_id)
    subject = f"Welcome to {biz_name}!"

    if ctype == "dental":
        welcome_body = f"""
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            Thank you for choosing <strong style="color:#1a1a2e;">{biz_name}</strong>! We're delighted to welcome you as a new patient
            and look forward to providing you with excellent care.
        </p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            Here's what to expect on your first visit:
        </p>
        <ul style="color:#555;font-size:14px;line-height:2;margin:12px 0 0;padding-left:20px;">
            <li>Arrive <strong>10 minutes early</strong> to complete any paperwork</li>
            <li>Bring a <strong>valid ID</strong> and insurance card (if applicable)</li>
            <li>Complete your <strong>pre-visit form</strong> if you received one</li>
        </ul>"""
    elif ctype == "ecommerce":
        welcome_body = f"""
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            Thank you for shopping with <strong style="color:#1a1a2e;">{biz_name}</strong>! We're thrilled to have you as a customer.
        </p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            Here's what you can look forward to:
        </p>
        <ul style="color:#555;font-size:14px;line-height:2;margin:12px 0 0;padding-left:20px;">
            <li>Exclusive <strong>offers and deals</strong> for our customers</li>
            <li>Fast shipping and <strong>easy returns</strong></li>
            <li>Priority <strong>customer support</strong> whenever you need help</li>
        </ul>"""
    elif ctype == "real_estate":
        welcome_body = f"""
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            Thank you for choosing <strong style="color:#1a1a2e;">{biz_name}</strong>! We're excited to help you find the perfect property.
        </p>
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            Here's what to expect:
        </p>
        <ul style="color:#555;font-size:14px;line-height:2;margin:12px 0 0;padding-left:20px;">
            <li>Personalized <strong>property recommendations</strong> based on your needs</li>
            <li>Dedicated <strong>agent support</strong> throughout your journey</li>
            <li>Up-to-date <strong>market insights</strong> and new listings</li>
        </ul>"""
    else:
        welcome_body = f"""
        <p style="color:#555;font-size:15px;line-height:1.6;margin:12px 0 0;">
            Thank you for choosing <strong style="color:#1a1a2e;">{biz_name}</strong>! We're glad to have you as a customer
            and look forward to serving you.
        </p>"""

    content = f"""
    <tr><td style="height:4px;background:linear-gradient(90deg,#059669,#10b981,#34d399,#10b981,#059669);"></td></tr>
    <tr><td style="background:linear-gradient(145deg,#0b1628,#162040);padding:48px 40px;text-align:center;">
        <div style="width:64px;height:64px;margin:0 auto 16px;border-radius:50%;background:linear-gradient(135deg,#34d399,#10b981);line-height:64px;">
            <span style="font-size:28px;">&#128075;</span>
        </div>
        <h1 style="margin:0;color:#fff;font-size:24px;font-weight:300;">Welcome to <strong>{biz_name}</strong></h1>
    </td></tr>
    <tr><td style="padding:36px 40px;">
        <p style="color:#555;font-size:15px;line-height:1.6;margin:0;">
            Dear <strong style="color:#1a1a2e;">{customer_name}</strong>,
        </p>
        {welcome_body}
    </td></tr>
    <tr><td style="padding:16px 40px 36px;text-align:center;">
        <p style="color:#999;font-size:13px;margin:0;">We're here to help! Reach out anytime with questions.<br>
        <strong style="color:#10b981;">{biz_name}</strong></p>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#059669,#10b981,#34d399,#10b981,#059669);"></td></tr>"""

    variables = {"patient_name": customer_name, "clinic_name": biz_name}
    return _send_email(to_email, subject, _wrap_luxury(content, admin_id=admin_id, variables=variables), from_name=biz_name, admin_id=admin_id)
