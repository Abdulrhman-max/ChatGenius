"""
Treatment Plan Follow-Up Engine for ChatGenius.
Automates follow-up messages when a doctor recommends a treatment
that the patient hasn't booked yet.
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("treatment_followup")

# Follow-up schedule: day number -> message template
FOLLOWUP_SCHEDULE = {
    2: {
        'en': "Hi {patient_name}! Dr. {doctor_name} recommended a {treatment_name} consultation for you. Ready to take the next step? Book here: {booking_url}",
        'ar': "مرحباً {patient_name}! أوصى د. {doctor_name} باستشارة {treatment_name} لك. هل أنت مستعد للخطوة التالية؟ احجز هنا: {booking_url}",
    },
    5: {
        'en': "Just a reminder — Dr. {doctor_name}'s {treatment_name} recommendation is still waiting for you. Many patients see great results. Book here: {booking_url}",
        'ar': "مجرد تذكير — توصية د. {doctor_name} بخصوص {treatment_name} لا تزال بانتظارك. كثير من المرضى يرون نتائج رائعة. احجز هنا: {booking_url}",
    },
    10: {
        'en': "Final reminder — Dr. {doctor_name} recommended a {treatment_name} consultation for you. We're here whenever you're ready: {booking_url}",
        'ar': "تذكير أخير — أوصى د. {doctor_name} باستشارة {treatment_name} لك. نحن هنا متى ما كنت مستعداً: {booking_url}",
    },
}


def create_followup(admin_id, doctor_id, doctor_name, patient_name, patient_email, patient_phone, treatment_name):
    """
    Create a follow-up sequence for a recommended treatment.
    Creates 3 entries (Day 2, 5, 10) in the treatment_followups table.
    Returns list of created followup IDs.
    """
    import database as db
    conn = db.get_db()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    ids = []

    for day in [2, 5, 10]:
        conn.execute(
            """INSERT INTO treatment_followups
               (admin_id, doctor_id, patient_name, patient_email, patient_phone,
                treatment_name, recommended_date, followup_day, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (admin_id, doctor_id, patient_name, patient_email, patient_phone,
             treatment_name, now_str, day, "pending", now_str)
        )
        ids.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    conn.commit()
    conn.close()
    logger.info(f"Follow-up sequence created for {patient_name}: {treatment_name} (3 messages)")
    return ids


def process_pending_followups():
    """
    Main job: find and send due follow-up messages.
    Called periodically by the background scheduler (daily).
    """
    import database as db
    import email_service as email_svc

    conn = db.get_db()
    now = datetime.now()

    pending = conn.execute(
        "SELECT * FROM treatment_followups WHERE status='pending'"
    ).fetchall()

    for fu in pending:
        fu = dict(fu)
        try:
            recommended = datetime.strptime(fu["recommended_date"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue

        due_date = recommended + timedelta(days=fu["followup_day"])

        if now >= due_date:
            # Check if patient has booked this treatment since recommendation
            booked = conn.execute(
                """SELECT id FROM bookings
                   WHERE admin_id=? AND customer_email=?
                   AND (service LIKE ? OR treatment_type LIKE ?)
                   AND created_at > ? AND status != 'cancelled'""",
                (fu["admin_id"], fu["patient_email"],
                 f"%{fu['treatment_name']}%", f"%{fu['treatment_name']}%",
                 fu["recommended_date"])
            ).fetchone()

            if booked:
                # Patient already booked — cancel all remaining followups
                cancel_sequence_by_patient(fu["admin_id"], fu["patient_email"], fu["treatment_name"])
                continue

            # Send the follow-up
            booking_url = f"https://chatgenius.com/book/{fu['admin_id']}"

            # Get doctor name
            doctor = conn.execute("SELECT name FROM doctors WHERE id=?", (fu["doctor_id"],)).fetchone()
            doctor_name = doctor["name"] if doctor else "your doctor"

            try:
                email_svc.send_treatment_followup(
                    fu["patient_email"], fu["patient_name"],
                    fu["treatment_name"], fu["followup_day"], booking_url
                )
                now_str = now.strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "UPDATE treatment_followups SET status='sent', sent_at=? WHERE id=?",
                    (now_str, fu["id"])
                )
                conn.commit()
                logger.info(f"Follow-up Day {fu['followup_day']} sent to {fu['patient_email']} for {fu['treatment_name']}")
            except Exception as e:
                logger.error(f"Follow-up send failed: {e}")

    conn.close()


def cancel_sequence(followup_id):
    """Cancel a single follow-up and all subsequent ones in the same sequence."""
    import database as db
    conn = db.get_db()

    fu = conn.execute("SELECT * FROM treatment_followups WHERE id=?", (followup_id,)).fetchone()
    if not fu:
        conn.close()
        return {"error": "Follow-up not found"}

    fu = dict(fu)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Cancel all pending followups for this patient+treatment
    conn.execute(
        """UPDATE treatment_followups SET status='cancelled', cancelled_at=?
           WHERE admin_id=? AND patient_email=? AND treatment_name=? AND status='pending'""",
        (now, fu["admin_id"], fu["patient_email"], fu["treatment_name"])
    )
    conn.commit()
    conn.close()
    logger.info(f"Follow-up sequence cancelled for {fu['patient_email']}: {fu['treatment_name']}")
    return {"success": True}


def cancel_sequence_by_patient(admin_id, patient_email, treatment_name=None):
    """Cancel all pending followups for a patient (optionally for a specific treatment)."""
    import database as db
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if treatment_name:
        conn.execute(
            """UPDATE treatment_followups SET status='cancelled', cancelled_at=?
               WHERE admin_id=? AND patient_email=? AND treatment_name=? AND status='pending'""",
            (now, admin_id, patient_email, treatment_name)
        )
    else:
        conn.execute(
            """UPDATE treatment_followups SET status='cancelled', cancelled_at=?
               WHERE admin_id=? AND patient_email=? AND status='pending'""",
            (now, admin_id, patient_email)
        )
    conn.commit()
    conn.close()


def on_patient_booked(admin_id, patient_email):
    """Called when a patient books — cancels any pending followups for treatments they've now booked."""
    cancel_sequence_by_patient(admin_id, patient_email)


def get_followups(admin_id, status=None):
    """Get all follow-up sequences for dashboard display."""
    import database as db
    conn = db.get_db()

    if status:
        rows = conn.execute(
            "SELECT * FROM treatment_followups WHERE admin_id=? AND status=? ORDER BY created_at DESC",
            (admin_id, status)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM treatment_followups WHERE admin_id=? ORDER BY created_at DESC",
            (admin_id,)
        ).fetchall()
    conn.close()

    # Group by patient+treatment
    sequences = {}
    for row in rows:
        row = dict(row)
        key = f"{row['patient_email']}_{row['treatment_name']}"
        if key not in sequences:
            sequences[key] = {
                "patient_name": row["patient_name"],
                "patient_email": row["patient_email"],
                "treatment_name": row["treatment_name"],
                "recommended_date": row["recommended_date"],
                "messages": []
            }
        sequences[key]["messages"].append({
            "id": row["id"],
            "day": row["followup_day"],
            "status": row["status"],
            "sent_at": row.get("sent_at"),
            "cancelled_at": row.get("cancelled_at")
        })

    return list(sequences.values())


def get_followup_stats(admin_id):
    """Get follow-up statistics."""
    import database as db
    conn = db.get_db()

    total = conn.execute("SELECT COUNT(*) as c FROM treatment_followups WHERE admin_id=?", (admin_id,)).fetchone()["c"]
    sent = conn.execute("SELECT COUNT(*) as c FROM treatment_followups WHERE admin_id=? AND status='sent'", (admin_id,)).fetchone()["c"]
    pending = conn.execute("SELECT COUNT(*) as c FROM treatment_followups WHERE admin_id=? AND status='pending'", (admin_id,)).fetchone()["c"]
    cancelled = conn.execute("SELECT COUNT(*) as c FROM treatment_followups WHERE admin_id=? AND status='cancelled'", (admin_id,)).fetchone()["c"]

    # Count unique patients with active sequences
    active_patients = conn.execute(
        "SELECT COUNT(DISTINCT patient_email) as c FROM treatment_followups WHERE admin_id=? AND status='pending'",
        (admin_id,)
    ).fetchone()["c"]

    conn.close()
    return {
        "total_messages": total,
        "sent": sent,
        "pending": pending,
        "cancelled": cancelled,
        "active_sequences": active_patients
    }
