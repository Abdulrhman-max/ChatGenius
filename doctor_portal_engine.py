"""
Doctor Self-Management Portal Engine (Feature 8).
Allows doctors to manage their own availability, view schedule, and see stats.
"""
import json
from datetime import datetime, timedelta
import database as db


def get_doctor_for_user(user_id):
    """Get the doctor record linked to a user account."""
    conn = db.get_db()
    row = conn.execute(
        "SELECT * FROM doctors WHERE user_id = %s", (user_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_my_schedule(user_id):
    """Get doctor's full schedule: hours, breaks, off-days."""
    doctor = get_doctor_for_user(user_id)
    if not doctor:
        return None

    breaks = db.get_doctor_breaks(doctor["id"])
    off_days = list(db.get_doctor_off_dates(doctor["id"]))

    daily_hours = {}
    if doctor.get("daily_hours"):
        try:
            daily_hours = json.loads(doctor["daily_hours"]) if isinstance(doctor["daily_hours"], str) else doctor["daily_hours"]
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "doctor": {
            "id": doctor["id"],
            "name": doctor["name"],
            "specialty": doctor.get("specialty", ""),
            "schedule_type": doctor.get("schedule_type", "fixed"),
            "start_time": doctor.get("start_time", "09:00 AM"),
            "end_time": doctor.get("end_time", "05:00 PM"),
            "appointment_length": doctor.get("appointment_length", 60),
            "daily_hours": daily_hours,
            "availability": doctor.get("availability", "Sun-Thu"),
            "status": doctor.get("status", "active"),
        },
        "breaks": breaks,
        "off_days": off_days,
    }


def update_my_availability(user_id, start_time=None, end_time=None,
                           schedule_type=None, daily_hours=None,
                           appointment_length=None):
    """Doctor updates their own working hours."""
    doctor = get_doctor_for_user(user_id)
    if not doctor:
        return {"error": "Doctor profile not found"}

    conn = db.get_db()
    updates = []
    params = []

    if start_time:
        updates.append("start_time = ?")
        params.append(start_time)
    if end_time:
        updates.append("end_time = ?")
        params.append(end_time)
    if schedule_type:
        updates.append("schedule_type = ?")
        params.append(schedule_type)
    if daily_hours is not None:
        updates.append("daily_hours = ?")
        params.append(json.dumps(daily_hours) if isinstance(daily_hours, dict) else daily_hours)
    if appointment_length:
        updates.append("appointment_length = ?")
        params.append(appointment_length)

    if updates:
        params.append(doctor["id"])
        conn.execute(f"UPDATE doctors SET {', '.join(updates)} WHERE id = %s", params)
        conn.commit()

    conn.close()
    return {"ok": True}


def request_time_off(user_id, date, reason=""):
    """Doctor requests a day off."""
    doctor = get_doctor_for_user(user_id)
    if not doctor:
        return {"error": "Doctor profile not found"}

    conn = db.get_db()
    # Check if already off
    existing = conn.execute(
        "SELECT id FROM doctor_off_days WHERE doctor_id = %s AND off_date = %s",
        (doctor["id"], date)
    ).fetchone()

    if existing:
        conn.close()
        return {"error": "Already marked as off for this date"}

    conn.execute(
        "INSERT INTO doctor_off_days (doctor_id, off_date, reason) VALUES (%s, %s, %s)",
        (doctor["id"], date, reason)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def cancel_time_off(user_id, date):
    """Doctor cancels a day off request."""
    doctor = get_doctor_for_user(user_id)
    if not doctor:
        return {"error": "Doctor profile not found"}

    conn = db.get_db()
    conn.execute(
        "DELETE FROM doctor_off_days WHERE doctor_id = %s AND off_date = %s",
        (doctor["id"], date)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def get_my_bookings(user_id, date_from=None, date_to=None):
    """Get doctor's own bookings for a date range."""
    doctor = get_doctor_for_user(user_id)
    if not doctor:
        return []

    conn = db.get_db()
    if date_from and date_to:
        rows = conn.execute(
            "SELECT * FROM bookings WHERE doctor_id = %s AND date BETWEEN %s AND %s ORDER BY date, time",
            (doctor["id"], date_from, date_to)
        ).fetchall()
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT * FROM bookings WHERE doctor_id = %s AND date >= %s ORDER BY date, time",
            (doctor["id"], today)
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def get_todays_bookings(user_id):
    """Get doctor's bookings for today."""
    today = datetime.now().strftime("%Y-%m-%d")
    return get_my_bookings(user_id, today, today)


def get_my_stats(user_id):
    """Get doctor's personal performance stats."""
    doctor = get_doctor_for_user(user_id)
    if not doctor:
        return {}

    conn = db.get_db()
    now = datetime.now()
    month_start = now.replace(day=1).strftime("%Y-%m-%d")
    month_end = now.strftime("%Y-%m-%d")

    # Bookings this month
    bookings_count = conn.execute(
        "SELECT COUNT(*) as c FROM bookings WHERE doctor_id = %s AND date BETWEEN %s AND %s",
        (doctor["id"], month_start, month_end)
    ).fetchone()["c"]

    # No-shows this month
    noshow_count = conn.execute(
        "SELECT COUNT(*) as c FROM bookings WHERE doctor_id = %s AND date BETWEEN %s AND %s AND status = 'no_show'",
        (doctor["id"], month_start, month_end)
    ).fetchone()["c"]

    # Completed this month
    completed_count = conn.execute(
        "SELECT COUNT(*) as c FROM bookings WHERE doctor_id = %s AND date BETWEEN %s AND %s AND status = 'completed'",
        (doctor["id"], month_start, month_end)
    ).fetchone()["c"]

    # Average satisfaction (from surveys if table exists)
    avg_rating = None
    try:
        rating_row = conn.execute(
            "SELECT AVG(star_rating) as avg FROM surveys WHERE doctor_id = %s AND star_rating IS NOT NULL AND completed_at IS NOT NULL",
            (doctor["id"],)
        ).fetchone()
        if rating_row and rating_row["avg"]:
            avg_rating = round(rating_row["avg"], 1)
    except Exception:
        pass

    conn.close()

    return {
        "bookings_this_month": bookings_count,
        "completed_this_month": completed_count,
        "noshow_this_month": noshow_count,
        "noshow_rate": round(noshow_count / bookings_count * 100, 1) if bookings_count > 0 else 0,
        "avg_satisfaction": avg_rating,
    }


def set_emergency_availability(user_id, available=True):
    """Toggle doctor's emergency availability."""
    doctor = get_doctor_for_user(user_id)
    if not doctor:
        return {"error": "Doctor profile not found"}

    conn = db.get_db()
    conn.execute(
        "UPDATE doctors SET emergency_available = %s WHERE id = %s",
        (1 if available else 0, doctor["id"])
    )
    conn.commit()
    conn.close()
    return {"ok": True, "emergency_available": available}


def set_status_message(user_id, message=""):
    """Set a custom status message for the doctor."""
    doctor = get_doctor_for_user(user_id)
    if not doctor:
        return {"error": "Doctor profile not found"}

    conn = db.get_db()
    conn.execute(
        "UPDATE doctors SET status_message = %s WHERE id = %s",
        (message, doctor["id"])
    )
    conn.commit()
    conn.close()
    return {"ok": True}
