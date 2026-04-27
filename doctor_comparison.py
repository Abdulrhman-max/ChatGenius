"""
Multi-Doctor Comparison Engine for ChatGenius.
Provides side-by-side doctor comparison cards for the chatbot.
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("doctor_comparison")

# Keywords that trigger doctor comparison
COMPARISON_KEYWORDS = [
    "which doctor", "who are your doctors", "compare doctors",
    "not sure which doctor", "help me choose", "available doctors",
    "doctor options", "who should i see", "recommend a doctor",
    # Arabic
    "أي دكتور", "من هم الأطباء", "مقارنة", "اختيار دكتور", "أنصحني",
]


def should_show_comparison(message):
    """Check if the message is asking for doctor comparison."""
    lower = message.lower()
    for keyword in COMPARISON_KEYWORDS:
        if keyword in lower:
            return True
    return False


def get_doctor_comparison(admin_id):
    """
    Get comparison data for all active doctors.
    Returns list of doctor cards with: name, photo, specialty, experience,
    languages, next available slot, price range.
    """
    import database as db
    conn = db.get_db()

    doctors = conn.execute(
        "SELECT * FROM doctors WHERE admin_id=%s AND status='active' ORDER BY name",
        (admin_id,)
    ).fetchall()

    cards = []
    today = datetime.now().strftime("%Y-%m-%d")

    for doc in doctors:
        doc = dict(doc)

        # Find next available slot
        next_slot = _find_next_available(doc, conn, today)

        # Build card
        card = {
            "id": doc["id"],
            "name": doc["name"],
            "specialty": doc.get("specialty", "General Dentist"),
            "bio": doc.get("bio", ""),
            "years_of_experience": doc.get("years_of_experience"),
            "languages": _parse_languages(doc.get("languages", "")),
            "qualifications": doc.get("qualifications", ""),
            "photo_url": doc.get("avatar_url") or doc.get("photo_url"),
            "next_available": next_slot,
            "availability": doc.get("availability", "Mon-Fri"),
        }
        cards.append(card)

    conn.close()
    return cards


def _find_next_available(doctor, conn, start_date):
    """Find the next available time slot for a doctor."""
    import database as db

    doctor_id = doctor["id"]
    start_time = doctor.get("start_time", "09:00 AM")
    end_time = doctor.get("end_time", "05:00 PM")
    appt_length = doctor.get("appointment_length", 30)

    # Check today + next 7 days
    for day_offset in range(8):
        check_date = (datetime.now() + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        check_dt = datetime.strptime(check_date, "%Y-%m-%d")

        # Skip weekends
        if check_dt.weekday() >= 5:
            continue

        # Skip off days
        off_day = conn.execute(
            "SELECT id FROM doctor_off_days WHERE doctor_id=%s AND off_date=%s",
            (doctor_id, check_date)
        ).fetchone()
        if off_day:
            continue

        # Get booked times
        booked = conn.execute(
            "SELECT time FROM bookings WHERE doctor_id=%s AND date=%s AND status IN ('confirmed','pending')",
            (doctor_id, check_date)
        ).fetchall()
        booked_times = set(b["time"] for b in booked)

        # Generate slots
        try:
            slot_start = datetime.strptime(f"{check_date} {start_time}", "%Y-%m-%d %I:%M %p")
            slot_end = datetime.strptime(f"{check_date} {end_time}", "%Y-%m-%d %I:%M %p")
        except ValueError:
            continue

        current = slot_start
        now = datetime.now()

        while current + timedelta(minutes=appt_length) <= slot_end:
            if current > now:  # Must be in the future
                slot_label = current.strftime("%I:%M %p").lstrip("0")
                end_label = (current + timedelta(minutes=appt_length)).strftime("%I:%M %p").lstrip("0")
                full_label = f"{slot_label} - {end_label}"

                if full_label not in booked_times and slot_label not in booked_times:
                    # Format display
                    if day_offset == 0:
                        day_display = "Today"
                    elif day_offset == 1:
                        day_display = "Tomorrow"
                    else:
                        day_display = check_dt.strftime("%A, %b %d")

                    return {
                        "date": check_date,
                        "time": full_label,
                        "display": f"{day_display} at {slot_label}"
                    }

            current += timedelta(minutes=appt_length)

    return {"display": "No availability this week", "date": None, "time": None}


def _parse_languages(languages_str):
    """Parse comma-separated languages into a list."""
    if not languages_str:
        return ["English"]
    return [lang.strip() for lang in languages_str.split(",") if lang.strip()]


def get_chatbot_comparison_response(admin_id, lang='en'):
    """
    Build the chatbot response with doctor comparison.
    Returns: {"response": str, "ui_options": dict}
    """
    cards = get_doctor_comparison(admin_id)

    if not cards:
        if lang == 'ar':
            return {"response": "عذراً، لا يوجد أطباء متاحون حالياً.", "ui_options": None}
        return {"response": "Sorry, no doctors are available at the moment.", "ui_options": None}

    if lang == 'ar':
        response = "بالتأكيد! إليك مقارنة بين أطبائنا المتاحين:"
    else:
        response = "No problem! Here's a comparison of our available doctors:"

    ui_options = {
        "type": "doctor_comparison",
        "cards": cards
    }

    return {"response": response, "ui_options": ui_options}
