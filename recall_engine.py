"""
Recall & Retention Automation Engine for ChatGenius.
Handles recall rules, birthday greetings, re-engagement campaigns,
and campaign analytics.
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("recall")


# ── Recall Rules Management ──

def create_recall_rule(admin_id, treatment_type, recall_days, message_template=None):
    """Create a recall rule: 'Send recall X days after treatment Y'."""
    import database as db
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not message_template:
        message_template = (
            "Hi {patient_name}! It's been {recall_days} days since your last {treatment_type} "
            "with Dr. {doctor_name}. Time for your next visit — book here: {booking_url}"
        )

    conn.execute(
        """INSERT INTO recall_rules (admin_id, treatment_type, recall_days, message_template, is_active, created_at)
           VALUES (?,?,?,?,1,?)""",
        (admin_id, treatment_type, recall_days, message_template, now)
    )
    conn.commit()
    rule_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {"id": rule_id}


def get_recall_rules(admin_id):
    """Get all recall rules for an admin."""
    import database as db
    conn = db.get_db()
    rules = conn.execute("SELECT * FROM recall_rules WHERE admin_id=? ORDER BY created_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rules]


def update_recall_rule(rule_id, **kwargs):
    """Update a recall rule. Accepts: treatment_type, recall_days, message_template, is_active."""
    import database as db
    allowed = ['treatment_type', 'recall_days', 'message_template', 'is_active']
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    conn = db.get_db()
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [rule_id]
    conn.execute(f"UPDATE recall_rules SET {set_clause} WHERE id=?", values)
    conn.commit()
    conn.close()


def delete_recall_rule(rule_id):
    """Delete a recall rule and cancel all pending campaigns for it."""
    import database as db
    conn = db.get_db()
    conn.execute("UPDATE recall_campaigns SET status='cancelled' WHERE rule_id=? AND status='pending'", (rule_id,))
    conn.execute("DELETE FROM recall_rules WHERE id=?", (rule_id,))
    conn.commit()
    conn.close()


# ── Campaign Processing (called by background scheduler) ──

def process_recall_campaigns(admin_id=None):
    """
    Main job: find patients due for recall and create/send campaigns.
    Called periodically by the background scheduler.
    """
    import database as db
    import email_service as email_svc

    conn = db.get_db()

    # Get all active recall rules (optionally filtered by admin)
    if admin_id:
        if not db.is_feature_enabled(admin_id, "auto_recall"):
            conn.close()
            return
        rules = conn.execute("SELECT * FROM recall_rules WHERE admin_id=? AND is_active=1", (admin_id,)).fetchall()
    else:
        # Process all admins - filter by feature flag
        all_admins = conn.execute("SELECT DISTINCT admin_id FROM recall_rules WHERE is_active=1").fetchall()
        rules = []
        for admin_row in all_admins:
            a_id = admin_row["admin_id"]
            if db.is_feature_enabled(a_id, "auto_recall"):
                admin_rules = conn.execute("SELECT * FROM recall_rules WHERE admin_id=? AND is_active=1", (a_id,)).fetchall()
                rules.extend(admin_rules)

    today = datetime.now().strftime("%Y-%m-%d")

    for rule in rules:
        rule = dict(rule)
        recall_date = (datetime.now() - timedelta(days=rule["recall_days"])).strftime("%Y-%m-%d")

        # Find completed bookings from recall_days ago for this treatment
        bookings = conn.execute(
            """SELECT b.*, p.email as patient_email, p.name as patient_name, p.phone as patient_phone
               FROM bookings b
               LEFT JOIN patients p ON b.patient_id = p.id
               WHERE b.admin_id=? AND b.status='completed'
               AND b.date=? AND (b.service LIKE ? OR b.treatment_type LIKE ?)""",
            (rule["admin_id"], recall_date,
             f"%{rule['treatment_type']}%", f"%{rule['treatment_type']}%")
        ).fetchall()

        for booking in bookings:
            booking = dict(booking)
            patient_email = booking.get("patient_email") or booking.get("customer_email")
            patient_name = booking.get("patient_name") or booking.get("customer_name")

            if not patient_email:
                continue

            # Check if a campaign already exists for this patient+rule
            existing = conn.execute(
                "SELECT id FROM recall_campaigns WHERE rule_id=? AND patient_email=? AND status IN ('pending','sent')",
                (rule["id"], patient_email)
            ).fetchone()
            if existing:
                continue

            # Create campaign with unique booking token
            doctor_name = booking.get("doctor_name", "")
            campaign = db.add_recall_campaign(
                admin_id=rule["admin_id"], rule_id=rule["id"],
                patient_name=patient_name, patient_email=patient_email,
                patient_phone=booking.get("patient_phone") or booking.get("customer_phone") or "",
                recall_type="recall", service_name=rule["treatment_type"],
                doctor_name=doctor_name
            )
            recall_token = campaign["recall_token"]

            # Build booking URL using recall token
            import os
            from flask import request as _req
            try:
                base = _req.host_url.rstrip("/")
            except Exception:
                base = os.environ.get("SERVER_URL", "http://localhost:8080")
            booking_url = f"{base}/recall-book/{recall_token}"

            message = rule.get("message_template", "")
            if message:
                try:
                    message = message.format(
                        patient_name=patient_name,
                        recall_days=rule["recall_days"],
                        treatment_type=rule["treatment_type"],
                        doctor_name=doctor_name or "your doctor",
                        booking_url=booking_url
                    )
                except Exception:
                    pass

            try:
                email_svc.send_recall_email(
                    patient_email, patient_name,
                    rule["treatment_type"], message, booking_url,
                    admin_id=rule["admin_id"]
                )
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "UPDATE recall_campaigns SET status='sent', sent_at=? WHERE id=?",
                    (now, campaign["id"])
                )
                conn.commit()
                logger.info(f"Recall sent to {patient_email} for {rule['treatment_type']}")
            except Exception as e:
                logger.error(f"Failed to send recall to {patient_email}: {e}")

    conn.close()


def process_second_reminders():
    """Send second reminder 2 weeks after first recall if patient hasn't booked."""
    import database as db
    import email_service as email_svc

    conn = db.get_db()
    two_weeks_ago = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")

    # Find campaigns sent > 14 days ago with no booking
    campaigns = conn.execute(
        """SELECT rc.*, rr.treatment_type, rr.admin_id
           FROM recall_campaigns rc
           JOIN recall_rules rr ON rc.rule_id = rr.id
           WHERE rc.status='sent' AND rc.sent_at <= ? AND rc.booked_at IS NULL
           AND rc.recall_type='recall'""",
        (two_weeks_ago,)
    ).fetchall()

    for camp in campaigns:
        camp = dict(camp)
        # Use recall token if available, otherwise fallback
        recall_token = camp.get("recall_token", "")
        if recall_token:
            import os
            base = os.environ.get("SERVER_URL", "http://localhost:8080")
            booking_url = f"{base}/recall-book/{recall_token}"
        else:
            booking_url = "#"
        message = (
            f"Hi {camp['patient_name']}! Just a gentle reminder — it's time for your "
            f"{camp['treatment_type']} appointment. Book your visit today!"
        )

        try:
            email_svc.send_recall_email(
                camp["patient_email"], camp["patient_name"],
                camp["treatment_type"], message, booking_url,
                admin_id=camp.get("admin_id"),
            )
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE recall_campaigns SET recall_type='second_reminder', sent_at=? WHERE id=?",
                (now, camp["id"])
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Second reminder failed for {camp['patient_email']}: {e}")

    conn.close()


# ── Birthday Greetings ──

def process_birthday_greetings():
    """Send birthday greetings to patients whose birthday is today."""
    import database as db
    import email_service as email_svc

    conn = db.get_db()
    today_md = datetime.now().strftime("%m-%d")  # e.g., "03-15"
    year = datetime.now().strftime("%Y")

    # Find patients with birthday today (matching month-day from date_of_birth)
    patients = conn.execute(
        """SELECT p.*,
                  (SELECT user_id FROM company_info WHERE user_id = p.admin_id) as admin_user_id
           FROM patients p
           WHERE p.date_of_birth IS NOT NULL
           AND SUBSTR(p.date_of_birth, 6) = ?""",
        (today_md,)
    ).fetchall()

    for patient in patients:
        patient = dict(patient)
        if not patient.get("email"):
            continue

        # Check if already sent this year
        existing = conn.execute(
            "SELECT id FROM recall_campaigns WHERE patient_email=? AND recall_type='birthday' AND created_at LIKE ?",
            (patient["email"], f"{year}%")
        ).fetchone()
        if existing:
            continue

        # Generate unique discount code
        from promotions_engine import generate_unique_code, create_promotion
        code = generate_unique_code(patient["admin_id"], prefix="BDAY")
        if code:
            create_promotion(
                patient["admin_id"], code, "percentage", 15,
                expiry_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                max_uses=1
            )

        # Get business name
        company = conn.execute("SELECT business_name FROM company_info WHERE user_id=?", (patient["admin_id"],)).fetchone()
        business_name = company["business_name"] if company else "our clinic"

        booking_url = f"https://chatgenius.com/book/{patient['admin_id']}"
        message = (
            f"Happy Birthday from {business_name}! \U0001f382\n\n"
            f"Enjoy 15% off your next visit this month.\n"
            f"Use code: {code} at checkout.\n\n"
            f"Book your appointment: {booking_url}"
        )

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO recall_campaigns
               (admin_id, rule_id, patient_name, patient_email, patient_phone,
                recall_type, status, sent_at, created_at)
               VALUES (?,0,?,?,?,?,?,?,?)""",
            (patient["admin_id"], patient["name"], patient["email"], patient.get("phone"),
             "birthday", "sent", now, now)
        )
        conn.commit()

        try:
            email_svc.send_recall_email(
                patient["email"], patient["name"],
                "Birthday Special", message, booking_url,
                admin_id=patient["admin_id"],
            )
            logger.info(f"Birthday greeting sent to {patient['email']}")
        except Exception as e:
            logger.error(f"Birthday greeting failed for {patient['email']}: {e}")

    conn.close()


# ── Re-engagement ──

def process_reengagement():
    """Contact patients who haven't visited in 12+ months."""
    import database as db
    import email_service as email_svc

    conn = db.get_db()
    cutoff = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    patients = conn.execute(
        """SELECT * FROM patients
           WHERE last_visit_date IS NOT NULL AND last_visit_date <= ?
           AND email IS NOT NULL AND email != ''""",
        (cutoff,)
    ).fetchall()

    for patient in patients:
        patient = dict(patient)

        # Check if already sent reengagement recently (within 30 days)
        recent = conn.execute(
            "SELECT id FROM recall_campaigns WHERE patient_email=? AND recall_type='reengagement' AND created_at >= ?",
            (patient["email"], (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"))
        ).fetchone()
        if recent:
            continue

        company = conn.execute("SELECT business_name FROM company_info WHERE user_id=?", (patient["admin_id"],)).fetchone()
        business_name = company["business_name"] if company else "our clinic"

        booking_url = f"https://chatgenius.com/book/{patient['admin_id']}"
        message = (
            f"We miss you at {business_name}! It's been over a year since your last visit. "
            f"Book a checkup today — your smile deserves it: {booking_url}"
        )

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO recall_campaigns
               (admin_id, rule_id, patient_name, patient_email, patient_phone,
                recall_type, status, sent_at, created_at)
               VALUES (?,0,?,?,?,?,?,?,?)""",
            (patient["admin_id"], patient["name"], patient["email"], patient.get("phone"),
             "reengagement", "sent", now, now)
        )
        conn.commit()

        try:
            email_svc.send_recall_email(
                patient["email"], patient["name"],
                "We Miss You", message, booking_url,
                admin_id=patient["admin_id"],
            )
            logger.info(f"Re-engagement sent to {patient['email']}")
        except Exception as e:
            logger.error(f"Re-engagement failed for {patient['email']}: {e}")

    conn.close()


# ── Analytics ──

def get_campaign_analytics(admin_id):
    """Get recall campaign analytics."""
    import database as db
    conn = db.get_db()

    total_sent = conn.execute(
        "SELECT COUNT(*) as c FROM recall_campaigns WHERE admin_id=? AND status='sent'", (admin_id,)
    ).fetchone()["c"]

    total_opened = conn.execute(
        "SELECT COUNT(*) as c FROM recall_campaigns WHERE admin_id=? AND opened_at IS NOT NULL", (admin_id,)
    ).fetchone()["c"]

    total_booked = conn.execute(
        "SELECT COUNT(*) as c FROM recall_campaigns WHERE admin_id=? AND booked_at IS NOT NULL", (admin_id,)
    ).fetchone()["c"]

    # By type
    by_type = conn.execute(
        """SELECT recall_type, COUNT(*) as total,
                  SUM(CASE WHEN booked_at IS NOT NULL THEN 1 ELSE 0 END) as converted
           FROM recall_campaigns WHERE admin_id=?
           GROUP BY recall_type""",
        (admin_id,)
    ).fetchall()

    conn.close()

    return {
        "total_sent": total_sent,
        "total_opened": total_opened,
        "total_booked": total_booked,
        "conversion_rate": round(total_booked / total_sent * 100, 1) if total_sent > 0 else 0,
        "by_type": [dict(r) for r in by_type]
    }


def mark_campaign_opened(campaign_id):
    """Mark a campaign as opened (called from email tracking pixel)."""
    import database as db
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE recall_campaigns SET opened_at=? WHERE id=? AND opened_at IS NULL", (now, campaign_id))
    conn.commit()
    conn.close()


def mark_campaign_booked(patient_email, admin_id, booking_id):
    """Mark the most recent campaign for this patient as converted."""
    import database as db
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """UPDATE recall_campaigns SET booked_at=?, booking_id=?
           WHERE patient_email=? AND admin_id=? AND booked_at IS NULL
           ORDER BY created_at DESC LIMIT 1""",
        (now, booking_id, patient_email, admin_id)
    )
    conn.commit()
    conn.close()


def toggle_all_recalls(admin_id, active):
    """Pause or resume all recall rules for an admin."""
    import database as db
    conn = db.get_db()
    conn.execute("UPDATE recall_rules SET is_active=? WHERE admin_id=?", (1 if active else 0, admin_id))
    conn.commit()
    conn.close()
