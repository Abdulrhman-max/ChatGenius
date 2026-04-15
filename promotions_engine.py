"""
Promotions & Discount Engine for ChatGenius.
Handles discount code creation, validation, application, and analytics.
"""
import logging
from datetime import datetime

logger = logging.getLogger("promotions")


def validate_discount_code(admin_id, code, treatment=None, booking_value=None):
    """
    Validate a discount code. Returns a dict:
    On success: {"valid": True, "discount_type": "percentage", "discount_value": 20, "code_id": 5, "message": "..."}
    On failure: {"valid": False, "error": "specific error message"}

    Checks in order:
    1. Code exists for this admin
    2. Code is active
    3. Code is not expired
    4. Code has remaining uses
    5. Code applies to this treatment (if applicable_treatments is set)
    6. Booking value meets minimum (if min_booking_value is set)
    """
    import database as db
    conn = db.get_db()

    promo = conn.execute(
        "SELECT * FROM promotions WHERE admin_id=? AND code=? LIMIT 1",
        (admin_id, code.strip())
    ).fetchone()

    if not promo:
        conn.close()
        return {"valid": False, "error": "This code is not valid. Please check and try again."}

    promo = dict(promo)

    if not promo.get("is_active"):
        conn.close()
        return {"valid": False, "error": "This code is no longer active."}

    # Check expiry
    if promo.get("expiry_date"):
        try:
            expiry = datetime.strptime(promo["expiry_date"], "%Y-%m-%d")
            if datetime.now() > expiry:
                conn.close()
                return {"valid": False, "error": f"This code expired on {promo['expiry_date']}."}
        except ValueError:
            pass

    # Check max uses
    if promo.get("max_uses") and promo.get("max_uses") > 0:
        if promo.get("current_uses", 0) >= promo["max_uses"]:
            conn.close()
            return {"valid": False, "error": "This promotion code has already been used the maximum number of times and is no longer available."}

    # Check applicable treatments
    if promo.get("applicable_treatments") and treatment:
        applicable = [t.strip().lower() for t in promo["applicable_treatments"].split(",")]
        if treatment.lower() not in applicable and "all" not in applicable:
            treatments_display = ", ".join([t.strip() for t in promo["applicable_treatments"].split(",")])
            conn.close()
            return {"valid": False, "error": f"This code is only valid for: {treatments_display}."}

    # Check minimum booking value
    if promo.get("min_booking_value") and booking_value is not None:
        if booking_value < promo["min_booking_value"]:
            conn.close()
            currency = db.get_company_currency(admin_id)
            return {"valid": False, "error": f"This code requires a minimum booking value of {promo['min_booking_value']} {currency}."}

    conn.close()
    return {
        "valid": True,
        "code_id": promo["id"],
        "code": promo["code"],
        "discount_type": promo.get("discount_type", "percentage"),
        "discount_value": promo.get("discount_value", 0),
        "message": f"Code {promo['code']} is valid!"
    }


def apply_discount(code_id, original_amount, admin_id=0):
    """
    Calculate the discounted amount.
    Returns: {"new_total": 160, "savings": 40, "discount_description": "20% off"}
    """
    import database as db
    conn = db.get_db()
    promo = conn.execute("SELECT * FROM promotions WHERE id=?", (code_id,)).fetchone()
    conn.close()

    if not promo:
        return {"new_total": original_amount, "savings": 0, "discount_description": ""}

    promo = dict(promo)
    currency = db.get_company_currency(admin_id) if admin_id else "USD"

    if promo["discount_type"] == "percentage":
        savings = round(original_amount * promo["discount_value"] / 100, 2)
        new_total = round(original_amount - savings, 2)
        description = f"{promo['discount_value']}% off"
    elif promo["discount_type"] == "fixed":
        savings = min(promo["discount_value"], original_amount)
        new_total = round(original_amount - savings, 2)
        description = f"{savings} {currency} off"
    else:
        savings = 0
        new_total = original_amount
        description = ""

    # Ensure total doesn't go below 0
    new_total = max(0, new_total)

    return {
        "new_total": new_total,
        "savings": savings,
        "original_amount": original_amount,
        "discount_description": description
    }


def record_usage(code_id, booking_id, patient_name, patient_email, discount_amount, original_amount):
    """Record that a discount code was used. Increments current_uses."""
    import database as db
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """INSERT INTO promotion_usage
           (promotion_id, booking_id, patient_name, patient_email, discount_amount, original_amount, used_at)
           VALUES (?,?,?,?,?,?,?)""",
        (code_id, booking_id, patient_name, patient_email, discount_amount, original_amount, now)
    )
    conn.execute("UPDATE promotions SET current_uses = current_uses + 1 WHERE id=?", (code_id,))
    conn.commit()
    conn.close()
    logger.info(f"Discount code #{code_id} used by {patient_name} on booking #{booking_id}, saved {discount_amount}")


def get_promotion_analytics(admin_id):
    """Get analytics for all promotions.
    Returns list of promotions with: code, total_uses, total_revenue_influenced, total_savings, remaining_uses.
    """
    import database as db
    conn = db.get_db()

    promos = conn.execute("SELECT * FROM promotions WHERE admin_id=? ORDER BY created_at DESC", (admin_id,)).fetchall()
    result = []

    for p in promos:
        p = dict(p)
        usage = conn.execute(
            "SELECT COUNT(*) as total_uses, COALESCE(SUM(original_amount),0) as total_revenue, COALESCE(SUM(discount_amount),0) as total_savings FROM promotion_usage WHERE promotion_id=?",
            (p["id"],)
        ).fetchone()
        usage = dict(usage) if usage else {}

        remaining = None
        if p.get("max_uses") and p["max_uses"] > 0:
            remaining = max(0, p["max_uses"] - p.get("current_uses", 0))

        is_expired = False
        if p.get("expiry_date"):
            try:
                is_expired = datetime.now() > datetime.strptime(p["expiry_date"], "%Y-%m-%d")
            except ValueError:
                pass

        result.append({
            "id": p["id"],
            "code": p["code"],
            "discount_type": p.get("discount_type", "percentage"),
            "discount_value": p.get("discount_value", 0),
            "applicable_treatments": p.get("applicable_treatments", "All"),
            "expiry_date": p.get("expiry_date"),
            "is_expired": is_expired,
            "max_uses": p.get("max_uses"),
            "current_uses": p.get("current_uses", 0),
            "remaining_uses": remaining,
            "is_active": bool(p.get("is_active")),
            "total_uses": usage.get("total_uses", 0),
            "total_revenue_influenced": usage.get("total_revenue", 0),
            "total_savings": usage.get("total_savings", 0),
            "created_at": p.get("created_at")
        })

    conn.close()
    return result


def create_promotion(admin_id, code, discount_type, discount_value,
                     applicable_treatments=None, expiry_date=None,
                     max_uses=None, min_booking_value=None):
    """Create a new promotion code."""
    import database as db
    conn = db.get_db()

    # Check if code already exists for this admin
    existing = conn.execute(
        "SELECT id FROM promotions WHERE admin_id=? AND code=?",
        (admin_id, code.strip())
    ).fetchone()
    if existing:
        conn.close()
        return {"error": "A promotion with this code already exists."}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO promotions
           (admin_id, code, discount_type, discount_value, applicable_treatments,
            expiry_date, max_uses, current_uses, min_booking_value, is_active, created_at)
           VALUES (?,?,?,?,?,?,?,0,?,1,?)""",
        (admin_id, code.strip(), discount_type, discount_value,
         applicable_treatments, expiry_date, max_uses, min_booking_value, now)
    )
    conn.commit()
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {"id": new_id, "code": code.strip()}


def deactivate_promotion(promotion_id):
    """Deactivate a promotion code."""
    import database as db
    conn = db.get_db()
    conn.execute("UPDATE promotions SET is_active=0 WHERE id=?", (promotion_id,))
    conn.commit()
    conn.close()


def generate_unique_code(admin_id, prefix=""):
    """Generate a unique promotion code like 'SUMMER20' or 'BDAY-A3X9'."""
    import random
    import string
    import database as db

    for _ in range(10):  # Max 10 attempts
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        code = f"{prefix}{suffix}" if prefix else suffix
        conn = db.get_db()
        existing = conn.execute(
            "SELECT id FROM promotions WHERE admin_id=? AND code=?", (admin_id, code)
        ).fetchone()
        conn.close()
        if not existing:
            return code
    return None
