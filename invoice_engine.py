"""
Invoice Generation Engine for ChatGenius.
Creates, manages, and renders invoices for dental clinic bookings.
Generates HTML invoices styled for printing (no reportlab dependency required).
Includes ZATCA QR code placeholder for Saudi compliance.
"""
import json
import logging
from datetime import datetime

logger = logging.getLogger("invoice")


# ── Invoice Generation ───────────────────────────────────────────────────────

def generate_invoice(booking_id, admin_id):
    """Create an invoice record with sequential number (INV-YYYY-NNNNN).
    Calculates line items from booking service, applies VAT (15%).
    Returns invoice_id."""
    import database as db

    booking = db.get_booking_by_id(booking_id)
    if not booking:
        logger.warning(f"Invoice: booking {booking_id} not found")
        return None

    patient_id = booking.get("patient_id", 0)

    # Get or create config for sequential numbering using atomic transaction
    # to prevent race conditions with concurrent requests
    conn = db.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        config_row = conn.execute(
            "SELECT next_invoice_number FROM invoice_config WHERE admin_id=?",
            (admin_id,)
        ).fetchone()
        next_num = config_row["next_invoice_number"] if config_row else 1
        year = datetime.now().strftime("%Y")
        invoice_number = f"INV-{year}-{next_num:05d}"

        # Increment the next invoice number atomically
        if config_row:
            conn.execute(
                "UPDATE invoice_config SET next_invoice_number=? WHERE admin_id=?",
                (next_num + 1, admin_id)
            )
        else:
            conn.execute(
                "INSERT INTO invoice_config (admin_id, next_invoice_number) VALUES (?, ?)",
                (admin_id, next_num + 1)
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # Build line items from booking
    service_name = booking.get("service", "General Consultation")
    # Default price — in a real system this would come from a service price table
    service_price = _get_service_price(service_name, admin_id)

    items = [
        {
            "description": service_name,
            "quantity": 1,
            "unit_price": service_price,
            "total": service_price,
        }
    ]
    items_json = json.dumps(items)

    subtotal = service_price
    tax_rate = 15.0
    tax_amount = round(subtotal * tax_rate / 100, 2)
    total = round(subtotal + tax_amount, 2)

    invoice_id = db.create_invoice(
        admin_id=admin_id,
        booking_id=booking_id,
        patient_id=patient_id,
        invoice_number=invoice_number,
        items_json=items_json,
        subtotal=subtotal,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        total=total,
    )

    logger.info(f"Invoice: generated {invoice_number} (id={invoice_id}) for booking {booking_id}, total={total}")
    return invoice_id


def _get_service_price(service_name, admin_id):
    """Look up service price. Falls back to a default if not found."""
    import database as db

    conn = db.get_db()
    # Try to find from a services/pricing table if it exists
    try:
        row = conn.execute(
            "SELECT pricing_insurance FROM company_info WHERE user_id=?", (admin_id,)
        ).fetchone()
        if row and row["pricing_insurance"]:
            # Try parsing pricing info for the service
            pricing = row["pricing_insurance"]
            if service_name.lower() in pricing.lower():
                # Simple extraction — in production, use structured pricing
                pass
    except Exception:
        pass
    finally:
        conn.close()

    # Default prices by common service names
    defaults = {
        "general consultation": 200.0,
        "cleaning": 300.0,
        "teeth whitening": 500.0,
        "filling": 350.0,
        "root canal": 1500.0,
        "extraction": 400.0,
        "crown": 2000.0,
        "braces consultation": 250.0,
        "implant": 5000.0,
        "x-ray": 150.0,
    }
    return defaults.get(service_name.lower(), 200.0)


# ── Invoice Retrieval ────────────────────────────────────────────────────────

def get_invoice(invoice_id):
    """Return full invoice data dict."""
    import database as db
    return db.get_invoice_by_id(invoice_id)


def get_invoices(admin_id, date_from=None, date_to=None):
    """List all invoices for an admin, optionally filtered by date range."""
    import database as db
    return db.get_invoices_list(admin_id, date_from=date_from, date_to=date_to)


# ── Payment & Voiding ───────────────────────────────────────────────────────

def mark_paid(invoice_id, payment_method="cash"):
    """Update payment status to paid."""
    import database as db

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = db.get_db()
    conn.execute(
        "UPDATE invoices SET payment_status='paid', payment_method=?, paid_at=? WHERE id=?",
        (payment_method, now, invoice_id),
    )
    conn.commit()
    conn.close()
    logger.info(f"Invoice: {invoice_id} marked as paid via {payment_method}")
    return True


def void_invoice(invoice_id, reason=""):
    """Void an invoice (never delete). Records reason and timestamp."""
    import database as db

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = db.get_db()
    conn.execute(
        "UPDATE invoices SET payment_status='voided', voided_at=?, void_reason=? WHERE id=?",
        (now, reason, invoice_id),
    )
    conn.commit()
    conn.close()
    logger.info(f"Invoice: {invoice_id} voided — reason: {reason}")
    return True


# ── HTML Invoice Rendering ───────────────────────────────────────────────────

def generate_invoice_html(invoice_id):
    """Return a styled HTML string of the invoice, suitable for printing as PDF.
    Includes ZATCA QR code placeholder."""
    import database as db

    conn = db.get_db()
    invoice = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not invoice:
        conn.close()
        return None
    invoice = dict(invoice)

    # Get config for business info
    config = db.get_invoice_config(invoice["admin_id"])
    if not config:
        config = {}

    # Get booking/patient info
    booking = db.get_booking_by_id(invoice["booking_id"]) if invoice.get("booking_id") else {}
    if not booking:
        booking = {}
    conn.close()

    items = json.loads(invoice.get("items_json", "[]"))
    business_name = config.get("business_name", "Dental Clinic")
    business_name_ar = config.get("business_name_ar", "")
    vat_number = config.get("vat_number", "")
    address = config.get("address", "")
    address_ar = config.get("address_ar", "")
    logo_url = config.get("logo_url", "")

    patient_name = booking.get("customer_name", "")
    patient_email = booking.get("customer_email", "")
    patient_phone = booking.get("customer_phone", "")
    service_date = booking.get("date", "")

    # Build items rows
    items_html = ""
    for i, item in enumerate(items, 1):
        items_html += f"""
        <tr>
            <td style="padding:10px 12px;border-bottom:1px solid #eee;color:#333;">{i}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #eee;color:#333;">{item.get('description','')}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #eee;color:#333;text-align:center;">{item.get('quantity',1)}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #eee;color:#333;text-align:right;">{item.get('unit_price',0):.2f}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #eee;color:#333;text-align:right;">{item.get('total',0):.2f}</td>
        </tr>"""

    status_color = "#28a745" if invoice["payment_status"] == "paid" else (
        "#dc3545" if invoice["payment_status"] == "voided" else "#f0ad4e"
    )
    status_label = invoice["payment_status"].upper()

    return f"""<!DOCTYPE html>
<html dir="ltr" lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Invoice {invoice['invoice_number']}</title>
<style>
    @media print {{
        body {{ margin: 0; padding: 0; }}
        .no-print {{ display: none; }}
    }}
    body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #333; background: #f5f5f5; margin: 0; padding: 20px; }}
    .invoice-container {{ max-width: 800px; margin: 0 auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); overflow: hidden; }}
    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; padding: 30px 40px; display: flex; justify-content: space-between; align-items: center; }}
    .header h1 {{ margin: 0; font-size: 28px; }}
    .header .invoice-number {{ font-size: 14px; opacity: 0.85; margin-top: 4px; }}
    .status-badge {{ display: inline-block; padding: 4px 14px; border-radius: 20px; font-size: 12px; font-weight: 600; color: #fff; }}
    .body-section {{ padding: 30px 40px; }}
    table.items {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
    table.items th {{ background: #f8f9fa; padding: 10px 12px; text-align: left; font-size: 13px; color: #666; border-bottom: 2px solid #dee2e6; }}
    .totals {{ text-align: right; margin-top: 10px; }}
    .totals td {{ padding: 6px 12px; }}
    .totals .total-row td {{ font-size: 18px; font-weight: 700; color: #333; border-top: 2px solid #333; padding-top: 10px; }}
    .qr-section {{ text-align: center; padding: 20px; border-top: 1px dashed #ddd; margin-top: 20px; }}
    .footer {{ background: #f8f9fa; padding: 20px 40px; font-size: 12px; color: #999; text-align: center; }}
</style>
</head>
<body>
<div class="invoice-container">
    <div class="header">
        <div>
            {'<img src="' + logo_url + '" alt="Logo" style="max-height:50px;margin-bottom:8px;"><br>' if logo_url else ''}
            <h1>{business_name}</h1>
            {f'<div style="font-size:16px;opacity:0.9;">{business_name_ar}</div>' if business_name_ar else ''}
            <div class="invoice-number">{invoice['invoice_number']}</div>
        </div>
        <div style="text-align:right;">
            <span class="status-badge" style="background:{status_color};">{status_label}</span>
            <div style="margin-top:10px;font-size:13px;opacity:0.85;">
                Date: {invoice.get('created_at','')[:10]}<br>
                Currency: {invoice.get('currency','SAR')}
            </div>
        </div>
    </div>

    <div class="body-section">
        <div style="display:flex;justify-content:space-between;margin-bottom:30px;">
            <div>
                <strong style="color:#666;font-size:12px;text-transform:uppercase;">Bill To</strong><br>
                <span style="font-size:16px;font-weight:600;">{patient_name}</span><br>
                <span style="color:#666;">{patient_email}</span><br>
                <span style="color:#666;">{patient_phone}</span>
            </div>
            <div style="text-align:right;">
                <strong style="color:#666;font-size:12px;text-transform:uppercase;">From</strong><br>
                <span style="font-size:14px;">{business_name}</span><br>
                <span style="color:#666;">{address}</span><br>
                {f'<span style="color:#666;">VAT: {vat_number}</span>' if vat_number else ''}
            </div>
        </div>

        {f'<div style="margin-bottom:20px;color:#666;font-size:14px;">Service Date: {service_date}</div>' if service_date else ''}

        <table class="items">
            <thead>
                <tr>
                    <th style="width:40px;">#</th>
                    <th>Description</th>
                    <th style="text-align:center;width:80px;">Qty</th>
                    <th style="text-align:right;width:120px;">Unit Price</th>
                    <th style="text-align:right;width:120px;">Total</th>
                </tr>
            </thead>
            <tbody>
                {items_html}
            </tbody>
        </table>

        <table class="totals" style="width:100%;">
            <tr><td></td><td style="color:#666;">Subtotal:</td><td style="width:120px;">{invoice['subtotal']:.2f} {invoice.get('currency','SAR')}</td></tr>
            <tr><td></td><td style="color:#666;">VAT ({invoice['tax_rate']:.0f}%):</td><td>{invoice['tax_amount']:.2f} {invoice.get('currency','SAR')}</td></tr>
            <tr class="total-row"><td></td><td>Total:</td><td>{invoice['total']:.2f} {invoice.get('currency','SAR')}</td></tr>
        </table>

        {f'<div style="margin-top:15px;color:#666;font-size:13px;">Payment Method: {invoice["payment_method"]}</div>' if invoice.get('payment_method') else ''}
        {f'<div style="color:#666;font-size:13px;">Paid At: {invoice["paid_at"]}</div>' if invoice.get('paid_at') else ''}
        {f'<div style="color:#dc3545;font-size:13px;margin-top:10px;">Voided: {invoice["void_reason"]}</div>' if invoice.get('voided_at') else ''}

        <!-- ZATCA QR Code Placeholder -->
        <div class="qr-section">
            <div style="width:120px;height:120px;margin:0 auto;border:2px dashed #ccc;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#999;font-size:11px;text-align:center;">
                ZATCA<br>QR Code<br>Placeholder
            </div>
            {f'<div style="margin-top:8px;color:#999;font-size:11px;">VAT Registration: {vat_number}</div>' if vat_number else ''}
        </div>
    </div>

    <div class="footer">
        {f'{address}' if address else ''}
        {f' | {address_ar}' if address_ar else ''}<br>
        Generated by ChatGenius AI &mdash; {invoice.get('created_at','')[:10]}
    </div>
</div>
</body>
</html>"""


# ── Send Invoice Email ───────────────────────────────────────────────────────

def send_invoice_email(invoice_id):
    """Send invoice HTML as email to the patient."""
    import database as db
    import email_service as email_svc

    conn = db.get_db()
    invoice = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not invoice:
        conn.close()
        return False
    invoice = dict(invoice)

    booking = db.get_booking_by_id(invoice["booking_id"]) if invoice.get("booking_id") else None
    conn.close()

    if not booking or not booking.get("customer_email"):
        logger.warning(f"Invoice: no email for invoice {invoice_id}")
        return False

    html = generate_invoice_html(invoice_id)
    if not html:
        return False

    subject = f"Invoice {invoice['invoice_number']} — {invoice['total']:.2f} {invoice.get('currency', 'SAR')}"
    try:
        return email_svc._send_email(booking["customer_email"], subject, html)
    except Exception as e:
        logger.error(f"Invoice: email send error: {e}")
        return False


# ── Invoice Config ───────────────────────────────────────────────────────────

def get_invoice_config(admin_id):
    """Get invoice configuration (VAT number, business name, etc.)."""
    import database as db
    return db.get_invoice_config(admin_id)


def save_invoice_config(admin_id, **kwargs):
    """Save/update invoice configuration."""
    import database as db
    return db.save_invoice_config(admin_id, **kwargs)
