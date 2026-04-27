"""
Reviews Engine - Local review collection without external APIs
Handles rating submission, feedback storage, and review analytics.
"""
import logging
from datetime import datetime

logger = logging.getLogger("reviews")

# Rating thresholds
HIGH_RATING_THRESHOLD = 4
AUTO_REVIEW_THRESHOLD = 4


def create_review_request(admin_id, booking_id, patient_email, patient_name, doctor_id=None):
    """
    Create a review request after appointment completion.
    Returns a unique token for the review page.
    """
    import database as db
    import secrets
    
    token = secrets.token_urlsafe(32)
    
    conn = db.get_db()
    conn.execute(
        """INSERT INTO review_requests 
           (admin_id, booking_id, patient_email, patient_name, doctor_id, token, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (admin_id, booking_id, patient_email, patient_name, doctor_id, token, 'pending')
    )
    conn.commit()
    conn.close()
    
    logger.info(f"Review request created for booking {booking_id}, token: {token}")
    return token


def submit_review(token, rating, feedback=""):
    """
    Submit a review/rating.
    Returns dict with success status and review data.
    """
    import database as db
    
    conn = db.get_db()
    
    request = conn.execute(
        "SELECT * FROM review_requests WHERE token=%s AND status='pending'",
        (token,)
    ).fetchone()
    
    if not request:
        conn.close()
        return {"error": "Invalid or expired review token", "success": False}
    
    conn.execute(
        """UPDATE review_requests 
           SET rating=%s, feedback=%s, status='completed', completed_at=%s 
           WHERE token=%s""",
        (rating, feedback, datetime.now().isoformat(), token)
    )
    
    rating_record = {
        "admin_id": request["admin_id"],
        "booking_id": request["booking_id"],
        "patient_email": request["patient_email"],
        "patient_name": request["patient_name"],
        "rating": rating,
        "feedback": feedback,
        "is_positive": rating >= HIGH_RATING_THRESHOLD,
        "created_at": datetime.now().isoformat()
    }
    
    conn.execute(
        """INSERT INTO reviews 
           (admin_id, booking_id, patient_email, patient_name, rating, feedback, is_positive)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (rating_record["admin_id"], rating_record["booking_id"], rating_record["patient_email"],
         rating_record["patient_name"], rating_record["rating"], rating_record["feedback"],
         1 if rating_record["is_positive"] else 0)
    )
    
    conn.commit()
    conn.close()
    
    logger.info(f"Review submitted: rating={rating}, positive={rating_record['is_positive']}")
    
    return {
        "success": True,
        "review": rating_record,
        "show_public_review": rating >= AUTO_REVIEW_THRESHOLD
    }


def get_reviews(admin_id, date_from=None, date_to=None, limit=100):
    """Get all reviews for an admin."""
    import database as db
    
    conn = db.get_db()
    query = "SELECT * FROM reviews WHERE admin_id=%s"
    params = [admin_id]
    
    if date_from:
        query += " AND DATE(created_at) >= %s"
        params.append(date_from)
    if date_to:
        query += " AND DATE(created_at) <= %s"
        params.append(date_to)
    
    query += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_review_analytics(admin_id, date_from=None, date_to=None):
    """Get review analytics and statistics."""
    import database as db
    
    conn = db.get_db()
    
    where = "WHERE admin_id=%s"
    params = [admin_id]
    
    if date_from:
        where += " AND DATE(created_at) >= %s"
        params.append(date_from)
    if date_to:
        where += " AND DATE(created_at) <= %s"
        params.append(date_to)
    
    total = conn.execute(f"SELECT COUNT(*) as c FROM reviews {where}", params).fetchone()["c"]
    positive = conn.execute(f"SELECT COUNT(*) as c FROM reviews {where} AND is_positive=1", params).fetchone()["c"]
    negative = conn.execute(f"SELECT COUNT(*) as c FROM reviews {where} AND is_positive=0", params).fetchone()["c"]
    
    avg_result = conn.execute(f"SELECT AVG(rating) as avg FROM reviews {where}", params).fetchone()
    avg_rating = float(avg_result["avg"]) if avg_result["avg"] else 0
    
    rating_breakdown = {}
    for i in range(1, 6):
        count = conn.execute(f"SELECT COUNT(*) as c FROM reviews {where} AND rating=%s", params + [i]).fetchone()["c"]
        rating_breakdown[i] = count
    
    recent_with_feedback = conn.execute(
        f"SELECT * FROM reviews {where} AND feedback != '' ORDER BY created_at DESC LIMIT 10", params
    ).fetchall()
    
    conn.close()
    
    return {
        "total_reviews": total,
        "positive_reviews": positive,
        "negative_reviews": negative,
        "average_rating": round(avg_rating, 2),
        "positive_percentage": round((positive / total * 100) if total > 0 else 0, 1),
        "rating_breakdown": rating_breakdown,
        "recent_feedback": [dict(r) for r in recent_with_feedback]
    }


def trigger_review_request(admin_id, booking_id, patient_email, patient_name, doctor_id=None):
    """
    Trigger review request after appointment completion.
    Called by the booking completion flow.
    """
    if not db.is_feature_enabled(admin_id, "auto_surveys"):
        logger.info(f"Auto surveys disabled for admin {admin_id}, skipping review request")
        return None
    
    try:
        token = create_review_request(admin_id, booking_id, patient_email, patient_name, doctor_id)
        
        base_url = os.getenv("BASE_URL", "http://localhost:8080")
        review_url = f"{base_url}/rating.html?token={token}"
        
        message = f"Thank you for visiting us! Please rate your experience: {review_url}"
        
        try:
            import email_service as email_svc
            email_svc.send_review_request(patient_email, patient_name, review_url)
            logger.info(f"Review request email sent to {patient_email}")
        except Exception as e:
            logger.warning(f"Failed to send review email: {e}")
        
        try:
            import realtime_engine as realtime
            realtime.emit_review_request(admin_id, {
                "booking_id": booking_id,
                "token": token,
                "patient_email": patient_email
            })
        except Exception as e:
            logger.warning(f"Failed to emit realtime event: {e}")
        
        return token
    except Exception as e:
        logger.error(f"Failed to trigger review request: {e}")
        return None
