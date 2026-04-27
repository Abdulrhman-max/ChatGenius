"""
Competitor Benchmarking Engine for ChatGenius.
Anonymously compares clinic performance against platform averages.
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("benchmarking")

MIN_CLINICS_FOR_BENCHMARK = 5
MIN_BOOKINGS_FOR_DATA = 30


def refresh_clinic_metrics(admin_id):
    """
    Recalculate and cache metrics for a single clinic.
    Called daily by background scheduler for all clinics.
    """
    import database as db
    conn = db.get_db()

    now = datetime.now()
    month_start = now.strftime("%Y-%m-01")
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    # Conversion rate: bookings / total chat sessions
    total_sessions = conn.execute(
        "SELECT COUNT(DISTINCT session_id) as c FROM chat_logs WHERE admin_id=%s AND created_at >= %s",
        (admin_id, month_ago)
    ).fetchone()["c"]

    total_bookings = conn.execute(
        "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND created_at >= %s",
        (admin_id, month_ago)
    ).fetchone()["c"]

    conversion_rate = round(total_bookings / total_sessions * 100, 1) if total_sessions > 0 else 0

    # No-show rate
    total_appointments = conn.execute(
        "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND date >= %s AND status IN ('confirmed','completed','no_show')",
        (admin_id, month_ago)
    ).fetchone()["c"]

    no_shows = conn.execute(
        "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND date >= %s AND status='no_show'",
        (admin_id, month_ago)
    ).fetchone()["c"]

    noshow_rate = round(no_shows / total_appointments * 100, 1) if total_appointments > 0 else 0

    # Average response time (from chat logs - time between patient message and bot response)
    # Simplified: use average time to first booking message
    avg_response = conn.execute(
        """SELECT AVG(response_seconds) as avg_sec FROM (
            SELECT MIN(
                (julianday(c2.created_at) - julianday(c1.created_at)) * 86400
            ) as response_seconds
            FROM chat_logs c1
            JOIN chat_logs c2 ON c1.session_id = c2.session_id AND c2.created_at > c1.created_at
            WHERE c1.admin_id=%s AND c1.created_at >= %s
            GROUP BY c1.session_id
        )""",
        (admin_id, month_ago)
    ).fetchone()
    avg_response_time = round(avg_response["avg_sec"], 0) if avg_response and avg_response["avg_sec"] else 0

    # Monthly bookings
    monthly_bookings = total_bookings

    # Review score (from GMB or internal)
    review_score = conn.execute(
        "SELECT rating FROM gmb_connections WHERE admin_id=%s", (admin_id,)
    ).fetchone()
    review_score = float(review_score["rating"]) if review_score and review_score["rating"] else 0

    # Get clinic city
    company = conn.execute("SELECT * FROM company_info WHERE user_id=%s", (admin_id,)).fetchone()
    city = ""
    if company and company.get("address"):
        # Try to extract city from address (last meaningful part)
        parts = company["address"].split(",")
        city = parts[-1].strip() if parts else ""

    # Upsert metrics
    existing = conn.execute("SELECT id FROM clinic_metrics_cache WHERE admin_id=%s", (admin_id,)).fetchone()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    if existing:
        conn.execute(
            """UPDATE clinic_metrics_cache SET
               conversion_rate=%s, noshow_rate=%s, avg_response_time=%s,
               monthly_bookings=%s, review_score=%s, city=%s, updated_at=%s
               WHERE admin_id=%s""",
            (conversion_rate, noshow_rate, avg_response_time, monthly_bookings,
             review_score, city, now_str, admin_id)
        )
    else:
        conn.execute(
            """INSERT INTO clinic_metrics_cache
               (admin_id, conversion_rate, noshow_rate, avg_response_time,
                monthly_bookings, review_score, city, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (admin_id, conversion_rate, noshow_rate, avg_response_time,
             monthly_bookings, review_score, city, now_str)
        )

    conn.commit()
    conn.close()

    return {
        "conversion_rate": conversion_rate,
        "noshow_rate": noshow_rate,
        "avg_response_time": avg_response_time,
        "monthly_bookings": monthly_bookings,
        "review_score": review_score
    }


def refresh_all_metrics():
    """Refresh metrics for all clinics. Called daily by scheduler."""
    import database as db
    conn = db.get_db()
    admins = conn.execute("SELECT id FROM users WHERE role='admin'").fetchall()
    conn.close()

    for admin in admins:
        try:
            refresh_clinic_metrics(admin["id"])
        except Exception as e:
            logger.error(f"Failed to refresh metrics for admin #{admin['id']}: {e}")


def get_benchmarks(admin_id):
    """
    Get benchmarking data for a clinic.
    Compares against same-city clinics (anonymized).
    """
    import database as db
    conn = db.get_db()

    # Get this clinic's metrics
    my_metrics = conn.execute(
        "SELECT * FROM clinic_metrics_cache WHERE admin_id=%s", (admin_id,)
    ).fetchone()

    if not my_metrics:
        # Refresh first
        conn.close()
        refresh_clinic_metrics(admin_id)
        conn = db.get_db()
        my_metrics = conn.execute(
            "SELECT * FROM clinic_metrics_cache WHERE admin_id=%s", (admin_id,)
        ).fetchone()

    if not my_metrics:
        conn.close()
        return {"error": "Unable to calculate metrics"}

    my_metrics = dict(my_metrics)

    # Check minimum bookings
    total_bookings = conn.execute(
        "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s", (admin_id,)
    ).fetchone()["c"]

    if total_bookings < MIN_BOOKINGS_FOR_DATA:
        conn.close()
        return {
            "not_enough_data": True,
            "message": f"Not enough data yet. Check back after your first {MIN_BOOKINGS_FOR_DATA} bookings.",
            "current_bookings": total_bookings,
            "required_bookings": MIN_BOOKINGS_FOR_DATA
        }

    # Get same-city clinics
    city = my_metrics.get("city", "")
    if city:
        peers = conn.execute(
            "SELECT * FROM clinic_metrics_cache WHERE city=%s AND admin_id != %s",
            (city, admin_id)
        ).fetchall()
    else:
        peers = conn.execute(
            "SELECT * FROM clinic_metrics_cache WHERE admin_id != %s",
            (admin_id,)
        ).fetchall()

    peers = [dict(p) for p in peers]

    if len(peers) < MIN_CLINICS_FOR_BENCHMARK - 1:
        conn.close()
        return {
            "not_enough_peers": True,
            "message": f"Benchmarking requires at least {MIN_CLINICS_FOR_BENCHMARK} clinics in your area. Currently {len(peers) + 1} clinics.",
        }

    conn.close()

    # Calculate averages and top 10%
    def calc_metric(field, lower_is_better=False):
        values = [p[field] for p in peers if p.get(field) is not None]
        if not values:
            return {"yours": my_metrics.get(field, 0), "average": 0, "top_10": 0}

        avg = round(sum(values) / len(values), 1)
        sorted_vals = sorted(values, reverse=not lower_is_better)
        top_10_idx = max(0, len(sorted_vals) // 10)
        top_10 = sorted_vals[top_10_idx] if sorted_vals else 0

        return {
            "yours": my_metrics.get(field, 0),
            "average": avg,
            "top_10": round(top_10, 1)
        }

    return {
        "not_enough_data": False,
        "not_enough_peers": False,
        "city": city or "All Cities",
        "peer_count": len(peers),
        "metrics": {
            "conversion_rate": {
                **calc_metric("conversion_rate"),
                "label": "Conversion Rate",
                "unit": "%",
                "description": "Percentage of chat sessions that result in a booking"
            },
            "noshow_rate": {
                **calc_metric("noshow_rate", lower_is_better=True),
                "label": "No-Show Rate",
                "unit": "%",
                "description": "Percentage of confirmed appointments where patient didn't show up"
            },
            "avg_response_time": {
                **calc_metric("avg_response_time", lower_is_better=True),
                "label": "Avg Response Time",
                "unit": "sec",
                "description": "Average time to respond to patient messages"
            },
            "monthly_bookings": {
                **calc_metric("monthly_bookings"),
                "label": "Monthly Bookings",
                "unit": "",
                "description": "Total bookings in the last 30 days"
            },
            "review_score": {
                **calc_metric("review_score"),
                "label": "Review Score",
                "unit": "/5",
                "description": "Average patient review rating"
            }
        },
        "last_updated": my_metrics.get("updated_at")
    }


def get_super_admin_benchmarks():
    """Non-anonymized benchmarks for super admin only."""
    import database as db
    conn = db.get_db()

    metrics = conn.execute(
        """SELECT c.*, u.name as clinic_name, u.email as clinic_email,
                  ci.business_name
           FROM clinic_metrics_cache c
           JOIN users u ON c.admin_id = u.id
           LEFT JOIN company_info ci ON c.admin_id = ci.user_id
           ORDER BY c.conversion_rate DESC"""
    ).fetchall()

    conn.close()
    return [dict(m) for m in metrics]
