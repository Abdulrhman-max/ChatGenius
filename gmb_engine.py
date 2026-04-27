"""
Google My Business Integration Engine for ChatGenius.
Manages GMB connection, reviews, and posts.
Requires Google Business Profile API credentials (stubbed for now).
"""
import logging
from datetime import datetime

logger = logging.getLogger("gmb")


# ── Connection Management ──

def get_connection(admin_id):
    """Get current GMB connection status."""
    import database as db
    conn = db.get_db()
    gmb = conn.execute("SELECT * FROM gmb_connections WHERE admin_id=%s", (admin_id,)).fetchone()
    conn.close()
    return dict(gmb) if gmb else None


def connect_account(admin_id, google_account_id, location_id, access_token, refresh_token):
    """Save GMB connection after OAuth flow."""
    import database as db
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    existing = conn.execute("SELECT id FROM gmb_connections WHERE admin_id=%s", (admin_id,)).fetchone()

    if existing:
        conn.execute(
            """UPDATE gmb_connections SET
               google_account_id=%s, location_id=%s, access_token=%s, refresh_token=%s, last_synced_at=%s
               WHERE admin_id=%s""",
            (google_account_id, location_id, access_token, refresh_token, now, admin_id)
        )
    else:
        conn.execute(
            """INSERT INTO gmb_connections
               (admin_id, google_account_id, location_id, access_token, refresh_token, last_synced_at, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (admin_id, google_account_id, location_id, access_token, refresh_token, now, now)
        )
    conn.commit()
    conn.close()
    return {"connected": True}


def disconnect_account(admin_id):
    """Remove GMB connection."""
    import database as db
    conn = db.get_db()
    conn.execute("DELETE FROM gmb_connections WHERE admin_id=%s", (admin_id,))
    conn.commit()
    conn.close()
    return {"disconnected": True}


# ── Reviews ──

def sync_reviews(admin_id):
    """
    Fetch latest reviews from Google.
    STUB: In production, calls Google Business Profile API.
    """
    connection = get_connection(admin_id)
    if not connection:
        return {"error": "Google account not connected"}

    # STUB: Would call Google API
    # GET https://mybusinessaccountmanagement.googleapis.com/v1/{location}/reviews
    logger.info(f"[GMB STUB] Syncing reviews for admin #{admin_id}")
    return {"synced": True, "reviews_count": 0, "stub": True}


def reply_to_review(admin_id, review_id, reply_text):
    """
    Reply to a Google review.
    STUB: In production, calls Google API.
    """
    connection = get_connection(admin_id)
    if not connection:
        return {"error": "Google account not connected"}

    # STUB: Would call Google API
    # PUT https://mybusinessaccountmanagement.googleapis.com/v1/{review}/reply
    logger.info(f"[GMB STUB] Reply to review #{review_id}: {reply_text[:50]}...")
    return {"replied": True, "stub": True}


def get_reviews(admin_id):
    """Get cached reviews for dashboard display."""
    connection = get_connection(admin_id)
    if not connection:
        return {"connected": False, "reviews": []}

    return {
        "connected": True,
        "rating": connection.get("rating", 0),
        "review_count": connection.get("review_count", 0),
        "reviews": [],  # Would be populated from cache
        "last_synced": connection.get("last_synced_at")
    }


# ── Posts ──

def create_post(admin_id, content, expiry_date=None):
    """
    Create a GMB post (update on Google listing).
    STUB: In production, calls Google API.
    """
    connection = get_connection(admin_id)
    if not connection:
        return {"error": "Google account not connected"}

    # STUB: Would call Google API
    # POST https://mybusinessaccountmanagement.googleapis.com/v1/{location}/localPosts
    logger.info(f"[GMB STUB] Creating post for admin #{admin_id}: {content[:50]}...")
    return {"posted": True, "stub": True}


# ── Schema Markup ──

def generate_schema_markup(admin_id):
    """
    Generate JSON-LD schema markup for DentalClinic/MedicalBusiness.
    This should be embedded in the chatbot page's <head>.
    """
    import database as db
    conn = db.get_db()

    company = conn.execute("SELECT * FROM company_info WHERE user_id=%s", (admin_id,)).fetchone()
    if not company:
        conn.close()
        return ""

    company = dict(company)

    # Get doctors
    doctors = conn.execute(
        "SELECT name, specialty FROM doctors WHERE admin_id=%s AND status='active'", (admin_id,)
    ).fetchall()

    conn.close()

    import json

    schema = {
        "@context": "https://schema.org",
        "@type": ["DentalClinic", "MedicalBusiness"],
        "name": company.get("business_name", ""),
        "address": {
            "@type": "PostalAddress",
            "streetAddress": company.get("address", "")
        },
        "telephone": company.get("phone", ""),
        "openingHours": company.get("business_hours", "Mo-Fr 09:00-17:00"),
        "potentialAction": {
            "@type": "ReserveAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"https://chatgenius.com/book/{admin_id}",
                "actionPlatform": [
                    "https://schema.org/DesktopWebPlatform",
                    "https://schema.org/MobileWebPlatform"
                ]
            },
            "result": {
                "@type": "Reservation",
                "name": "Dental Appointment"
            }
        }
    }

    if doctors:
        schema["employee"] = [
            {
                "@type": "Dentist",
                "name": f"Dr. {d['name']}",
                "medicalSpecialty": d.get("specialty", "General Dentistry")
            }
            for d in doctors
        ]

    # Get GMB rating
    connection = get_connection(admin_id)
    if connection and connection.get("rating"):
        schema["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": str(connection["rating"]),
            "reviewCount": str(connection.get("review_count", 0))
        }

    return f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>'
