"""
Patient Satisfaction Survey Engine for ChatGenius.
Handles survey scheduling, sending, submission, and analytics.
"""
import logging
import os
import secrets
from datetime import datetime, timedelta

logger = logging.getLogger("survey_engine")

BASE_URL = os.getenv("BASE_URL", "http://localhost:8080")


def schedule_survey(booking_id, admin_id):
    """
    Create a survey row in the DB, scheduled to send 2 hours after the appointment.
    Returns the survey_id.
    """
    import database as db

    conn = db.get_db()
    booking = conn.execute("SELECT * FROM bookings WHERE id = %s", (booking_id,)).fetchone()
    if not booking:
        conn.close()
        return None
    booking = dict(booking)
    conn.close()

    token = secrets.token_urlsafe(32)
    patient_id = booking.get("patient_id", 0)
    doctor_id = booking.get("doctor_id", 0)
    treatment_type = booking.get("treatment_type", "") or booking.get("service", "")

    survey_id = db.create_survey(
        admin_id=admin_id,
        booking_id=booking_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        token=token,
        treatment_type=treatment_type,
    )

    logger.info(f"Survey #{survey_id} scheduled for booking #{booking_id}")
    return survey_id


def send_survey(survey_id):
    """
    Send an email with star rating links (1-5).
    Each star links to /api/survey/{token}?rating=N.
    Returns True if sent, False otherwise.
    """
    import database as db

    conn = db.get_db()
    survey = conn.execute("SELECT * FROM surveys WHERE id = %s", (survey_id,)).fetchone()
    if not survey:
        conn.close()
        return False
    survey = dict(survey)

    if survey.get("sent_at"):
        conn.close()
        logger.info(f"Survey #{survey_id} already sent")
        return False

    token = survey["token"]

    # Build star rating links
    rating_links = {}
    for star in range(1, 6):
        rating_links[star] = f"{BASE_URL}/api/survey/{token}?rating={star}"

    # Get patient info for email
    patient = None
    if survey.get("patient_id"):
        patient = conn.execute("SELECT * FROM patients WHERE id = %s", (survey["patient_id"],)).fetchone()
        if patient:
            patient = dict(patient)

    # Mark as sent
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE surveys SET sent_at = %s WHERE id = %s", (now, survey_id))
    conn.commit()
    conn.close()

    # In a real implementation, this would send an actual email
    # For now, log the action
    patient_name = patient["name"] if patient else "Patient"
    logger.info(f"Survey email sent to {patient_name} for survey #{survey_id} with token {token}")

    return True


def submit_survey(token, star_rating, feedback_text=""):
    """
    Record a survey rating and optional feedback.
    Returns a dict with {redirect_to_google: bool} (true if rating meets threshold).
    """
    import database as db

    survey = db.get_survey_by_token(token)
    if not survey:
        return {"error": "Survey not found or invalid token."}

    if survey.get("completed_at"):
        return {"error": "This survey has already been completed.", "already_completed": True}

    if star_rating < 1 or star_rating > 5:
        return {"error": "Rating must be between 1 and 5."}

    # Check config for google review redirect threshold
    config = db.get_survey_config(survey.get("admin_id", 0))
    min_rating = config.get("min_rating_for_review", 4)
    google_url = config.get("google_review_url", "")

    redirect_to_google = star_rating >= min_rating and bool(google_url)

    google_clicked = 0  # Only set to 1 when user actually clicks the Google review link
    db.submit_survey_response(token, star_rating, feedback_text, google_clicked)

    logger.info(f"Survey {token} submitted: {star_rating} stars")

    result = {
        "success": True,
        "star_rating": star_rating,
        "redirect_to_google": redirect_to_google,
    }
    if redirect_to_google:
        result["google_review_url"] = google_url

    return result


def record_google_review_click(token):
    """
    Record that the user actually clicked the Google review link.
    Called when the user follows through to the Google review page.
    """
    import database as db

    survey = db.get_survey_by_token(token)
    if not survey:
        return {"error": "Survey not found or invalid token."}

    conn = db.get_db()
    conn.execute("UPDATE surveys SET google_review_clicked = 1 WHERE token = %s", (token,))
    conn.commit()
    conn.close()

    logger.info(f"Survey {token}: Google review click recorded")
    return {"success": True}


def get_survey_analytics(admin_id, date_from=None, date_to=None):
    """
    Returns avg rating, NPS, per-doctor avg, per-treatment avg,
    response rate, and trend data.
    """
    import database as db

    data = db.get_survey_analytics_db(admin_id, date_from, date_to)
    stats = data.get("stats", {})

    total_surveys = stats.get("total_surveys", 0) or 0
    completed = stats.get("completed", 0) or 0
    avg_rating = stats.get("avg_rating")
    if avg_rating is not None:
        avg_rating = round(avg_rating, 2)

    response_rate = round(completed / total_surveys * 100, 1) if total_surveys > 0 else 0

    # Calculate NPS: promoters (4-5) - detractors (1-3) as percentage
    conn = db.get_db()
    params = [admin_id]
    date_filter = ""
    if date_from:
        date_filter += " AND completed_at >= %s"
        params.append(date_from)
    if date_to:
        date_filter += " AND completed_at <= %s"
        params.append(date_to)

    nps_data = conn.execute(
        f"""SELECT
            SUM(CASE WHEN star_rating >= 4 THEN 1 ELSE 0 END) as promoters,
            SUM(CASE WHEN star_rating <= 2 THEN 1 ELSE 0 END) as detractors,
            COUNT(*) as total
        FROM surveys WHERE admin_id = %s AND star_rating IS NOT NULL {date_filter}""",
        params,
    ).fetchone()
    conn.close()

    nps_data = dict(nps_data) if nps_data else {}
    nps_total = nps_data.get("total", 0) or 0
    if nps_total > 0:
        promoters_pct = ((nps_data.get("promoters", 0) or 0) / nps_total) * 100
        detractors_pct = ((nps_data.get("detractors", 0) or 0) / nps_total) * 100
        nps = round(promoters_pct - detractors_pct, 1)
    else:
        nps = 0

    return {
        "total_surveys": total_surveys,
        "completed": completed,
        "avg_rating": avg_rating,
        "response_rate": response_rate,
        "nps": nps,
        "google_review_clicks": stats.get("google_clicks", 0) or 0,
        "per_doctor": data.get("doctor_stats", []),
        "per_treatment": data.get("treatment_stats", []),
        "trend": data.get("trend", []),
    }


def get_feedback_inbox(admin_id):
    """
    Returns surveys with rating <= 3 (negative feedback for follow-up).
    """
    import database as db
    return db.get_feedback_inbox_db(admin_id)
