"""
Patient Profile & History Engine for ChatGenius.
Every patient has a persistent profile that grows automatically.
Returning patients are recognized and greeted by name.
"""
import logging
from datetime import datetime

logger = logging.getLogger("patient_profile")


def recognize_patient(admin_id, phone=None, email=None):
    """
    Try to recognize a returning patient by phone or email.
    Returns patient dict if found, None if new patient.
    """
    import database as db
    conn = db.get_db()

    patient = None
    if phone:
        # Normalize phone: remove spaces, dashes, leading zeros
        clean_phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        patient = conn.execute(
            "SELECT * FROM patients WHERE admin_id=? AND (phone=? OR phone=?)",
            (admin_id, phone, clean_phone)
        ).fetchone()

    if not patient and email:
        patient = conn.execute(
            "SELECT * FROM patients WHERE admin_id=? AND email=?",
            (admin_id, email.strip().lower())
        ).fetchone()

    conn.close()
    return dict(patient) if patient else None


def get_or_create_patient(admin_id, name, phone=None, email=None, increment_booking=True):
    """
    Find existing patient or create new one.
    If found, optionally increment booking count.
    Returns patient dict.
    """
    import database as db

    # Try to find existing
    patient = recognize_patient(admin_id, phone=phone, email=email)

    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if patient:
        # Update name if provided and different
        updates = {}
        if name and name != patient.get("name"):
            updates["name"] = name
        if email and email != patient.get("email"):
            updates["email"] = email
        if phone and phone != patient.get("phone"):
            updates["phone"] = phone

        if increment_booking:
            conn.execute(
                "UPDATE patients SET total_bookings = COALESCE(total_bookings, 0) + 1 WHERE id=?",
                (patient["id"],)
            )

        if updates:
            for key, val in updates.items():
                conn.execute(f"UPDATE patients SET {key}=? WHERE id=?", (val, patient["id"]))

        conn.commit()

        # Re-fetch
        patient = conn.execute("SELECT * FROM patients WHERE id=?", (patient["id"],)).fetchone()
        conn.close()
        return dict(patient)

    # Create new patient
    conn.execute(
        """INSERT INTO patients
           (admin_id, name, email, phone, total_bookings, total_completed, total_cancelled, total_no_shows, loyalty_points, created_at)
           VALUES (?,?,?,?,?,0,0,0,0,?)""",
        (admin_id, name, email, phone, 1 if increment_booking else 0, now)
    )
    conn.commit()
    patient_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    patient = conn.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone()
    conn.close()

    logger.info(f"New patient created: {name} (#{patient_id})")
    return dict(patient)


def get_patient_profile(patient_id):
    """Get complete patient profile with all history."""
    import database as db
    conn = db.get_db()

    patient = conn.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone()
    if not patient:
        conn.close()
        return None

    patient = dict(patient)

    # Appointments history
    appointments = conn.execute(
        """SELECT id, date, time, doctor_name, service, treatment_type, status, created_at
           FROM bookings WHERE patient_id=? ORDER BY date DESC, time DESC""",
        (patient_id,)
    ).fetchall()
    patient["appointments"] = [dict(a) for a in appointments]

    # Upcoming appointments
    today = datetime.now().strftime("%Y-%m-%d")
    upcoming = conn.execute(
        """SELECT id, date, time, doctor_name, service, status
           FROM bookings WHERE patient_id=? AND date >= ? AND status='confirmed'
           ORDER BY date, time""",
        (patient_id, today)
    ).fetchall()
    patient["upcoming_appointments"] = [dict(u) for u in upcoming]

    # Doctor notes
    notes = conn.execute(
        """SELECT pn.*, u.name as doctor_name
           FROM patient_notes pn
           LEFT JOIN users u ON pn.doctor_id = u.id
           WHERE pn.patient_id=? ORDER BY pn.created_at DESC""",
        (patient_id,)
    ).fetchall()
    patient["notes"] = [dict(n) for n in notes]

    # Pre-visit forms
    forms = conn.execute(
        """SELECT pf.id, pf.booking_id, pf.submitted_at, pf.full_name
           FROM patient_forms pf
           JOIN bookings b ON pf.booking_id = b.id
           WHERE b.patient_id=? AND pf.submitted_at IS NOT NULL
           ORDER BY pf.submitted_at DESC""",
        (patient_id,)
    ).fetchall()
    patient["submitted_forms"] = [dict(f) for f in forms]

    # Loyalty history
    loyalty = conn.execute(
        "SELECT * FROM loyalty_transactions WHERE patient_id=? ORDER BY created_at DESC LIMIT 20",
        (patient_id,)
    ).fetchall()
    patient["loyalty_history"] = [dict(l) for l in loyalty]

    conn.close()
    return patient


def add_note(patient_id, doctor_id, note, booking_id=None):
    """Add a doctor's note to a patient's profile."""
    import database as db
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        "INSERT INTO patient_notes (patient_id, doctor_id, booking_id, note, created_at) VALUES (?,?,?,?,?)",
        (patient_id, doctor_id, booking_id, note, now)
    )
    conn.commit()
    note_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {"id": note_id}


def update_patient(patient_id, **kwargs):
    """Update patient profile fields."""
    import database as db
    allowed = ['name', 'email', 'phone', 'date_of_birth', 'gender', 'language',
               'medical_history', 'medications', 'allergies', 'insurance_provider',
               'insurance_policy', 'conditions', 'notes']
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return

    conn = db.get_db()
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [patient_id]
    conn.execute(f"UPDATE patients SET {set_clause} WHERE id=?", values)
    conn.commit()
    conn.close()


def search_patients(admin_id, query):
    """Search patients by name, phone, or email."""
    import database as db
    conn = db.get_db()

    search = f"%{query}%"
    patients = conn.execute(
        """SELECT id, name, email, phone, total_bookings, last_visit_date, loyalty_points
           FROM patients WHERE admin_id=? AND (name LIKE ? OR phone LIKE ? OR email LIKE ?)
           ORDER BY name LIMIT 50""",
        (admin_id, search, search, search)
    ).fetchall()

    conn.close()
    return [dict(p) for p in patients]


def delete_patient(patient_id, admin_id):
    """
    Delete a patient and all associated data.
    Requires admin_id match for safety.
    """
    import database as db
    conn = db.get_db()

    # Verify ownership
    patient = conn.execute(
        "SELECT id FROM patients WHERE id=? AND admin_id=?", (patient_id, admin_id)
    ).fetchone()
    if not patient:
        conn.close()
        return {"error": "Patient not found"}

    # Delete associated data
    conn.execute("DELETE FROM patient_notes WHERE patient_id=?", (patient_id,))
    conn.execute("DELETE FROM loyalty_transactions WHERE patient_id=?", (patient_id,))
    conn.execute("UPDATE bookings SET patient_id=NULL WHERE patient_id=?", (patient_id,))
    conn.execute("DELETE FROM patients WHERE id=?", (patient_id,))
    conn.commit()
    conn.close()

    logger.info(f"Patient #{patient_id} deleted with all associated data")
    return {"success": True}


def record_visit(patient_id):
    """Update last_visit_date when patient completes an appointment."""
    import database as db
    conn = db.get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    conn.execute("UPDATE patients SET last_visit_date=? WHERE id=?", (today, patient_id))
    conn.commit()
    conn.close()


def get_welcome_message(patient, lang='en'):
    """Generate personalized welcome message for returning patient."""
    name = patient.get("name", "")
    visits = patient.get("total_bookings", 0)

    if lang == 'ar':
        return f"مرحباً مجدداً {name}! سعداء بعودتك. كيف يمكنني مساعدتك؟"
    return f"Welcome back, {name}! Great to hear from you again. How can I help?"
