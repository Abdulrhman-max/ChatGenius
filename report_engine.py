"""
Monthly Performance Report Engine for ChatGenius.
Generates comprehensive report data from analytics, bookings, and surveys.
Renders styled HTML reports suitable for printing as PDF from browser.
No JS dependencies — uses pure CSS for charts and layout.
"""
import json
import logging
from datetime import datetime, timedelta
from calendar import monthrange

logger = logging.getLogger("report")


# ── Report Generation ────────────────────────────────────────────────────────

def generate_monthly_report(admin_id, year, month):
    """Pull data from analytics, stats, bookings. Compile comprehensive dict.
    Store in DB and return report_id."""
    import database as db

    # Date range for the month
    _, last_day = monthrange(year, month)
    date_from = f"{year}-{month:02d}-01"
    date_to = f"{year}-{month:02d}-{last_day:02d}"

    # Gather data from various sources
    analytics = {}
    try:
        analytics = db.get_analytics(admin_id, date_from, date_to)
    except Exception as e:
        logger.warning(f"Report: could not get analytics: {e}")

    stats = {}
    try:
        stats = db.get_stats(admin_id)
    except Exception as e:
        logger.warning(f"Report: could not get stats: {e}")

    # Booking breakdown
    conn = db.get_db()
    try:
        total_bookings = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id=? AND date BETWEEN ? AND ?",
            (admin_id, date_from, date_to),
        ).fetchone()["c"]

        completed = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id=? AND date BETWEEN ? AND ? AND status='completed'",
            (admin_id, date_from, date_to),
        ).fetchone()["c"]

        cancelled = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id=? AND date BETWEEN ? AND ? AND status='cancelled'",
            (admin_id, date_from, date_to),
        ).fetchone()["c"]

        no_shows = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id=? AND date BETWEEN ? AND ? AND status='no_show'",
            (admin_id, date_from, date_to),
        ).fetchone()["c"]

        confirmed = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id=? AND date BETWEEN ? AND ? AND status='confirmed'",
            (admin_id, date_from, date_to),
        ).fetchone()["c"]

        # New patients this month
        new_patients = conn.execute(
            "SELECT COUNT(*) as c FROM patients WHERE admin_id=? AND DATE(created_at) BETWEEN ? AND ?",
            (admin_id, date_from, date_to),
        ).fetchone()["c"]

        # Revenue from invoices if available
        revenue_row = None
        try:
            revenue_row = conn.execute(
                "SELECT SUM(total) as revenue, COUNT(*) as count FROM invoices "
                "WHERE admin_id=? AND payment_status='paid' AND DATE(created_at) BETWEEN ? AND ?",
                (admin_id, date_from, date_to),
            ).fetchone()
        except Exception:
            pass

        revenue = revenue_row["revenue"] if revenue_row and revenue_row["revenue"] else 0.0
        paid_invoices = revenue_row["count"] if revenue_row else 0

        # Top services
        top_services = conn.execute(
            """SELECT service, COUNT(*) as count FROM bookings
               WHERE admin_id=? AND date BETWEEN ? AND ? AND status != 'cancelled'
               GROUP BY service ORDER BY count DESC LIMIT 10""",
            (admin_id, date_from, date_to),
        ).fetchall()
        top_services = [dict(r) for r in top_services]

        # Doctor performance
        doctor_stats = conn.execute(
            """SELECT doctor_name, doctor_id,
                      COUNT(*) as total,
                      SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
                      SUM(CASE WHEN status='no_show' THEN 1 ELSE 0 END) as no_shows,
                      SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) as cancelled
               FROM bookings WHERE admin_id=? AND date BETWEEN ? AND ?
               GROUP BY doctor_id ORDER BY total DESC""",
            (admin_id, date_from, date_to),
        ).fetchall()
        doctor_stats = [dict(r) for r in doctor_stats]

        # Daily booking distribution
        daily_dist = conn.execute(
            """SELECT date, COUNT(*) as count FROM bookings
               WHERE admin_id=? AND date BETWEEN ? AND ? AND status != 'cancelled'
               GROUP BY date ORDER BY date""",
            (admin_id, date_from, date_to),
        ).fetchall()
        daily_dist = [dict(r) for r in daily_dist]

    except Exception as e:
        logger.error(f"Report: error gathering data: {e}")
        total_bookings = completed = cancelled = no_shows = confirmed = 0
        new_patients = 0
        revenue = 0.0
        paid_invoices = 0
        top_services = []
        doctor_stats = []
        daily_dist = []
    finally:
        conn.close()

    # Get company currency
    company_currency = db.get_company_currency(admin_id)

    # Compile report data
    report_data = {
        "admin_id": admin_id,
        "year": year,
        "month": month,
        "month_name": datetime(year, month, 1).strftime("%B"),
        "date_from": date_from,
        "date_to": date_to,
        "summary": {
            "total_bookings": total_bookings,
            "completed": completed,
            "cancelled": cancelled,
            "no_shows": no_shows,
            "confirmed": confirmed,
            "new_patients": new_patients,
            "revenue": revenue,
            "paid_invoices": paid_invoices,
            "currency": company_currency,
            "completion_rate": round(completed / total_bookings * 100, 1) if total_bookings > 0 else 0,
            "noshow_rate": round(no_shows / total_bookings * 100, 1) if total_bookings > 0 else 0,
            "cancellation_rate": round(cancelled / total_bookings * 100, 1) if total_bookings > 0 else 0,
        },
        "analytics": analytics,
        "top_services": top_services,
        "doctor_performance": doctor_stats,
        "daily_distribution": daily_dist,
    }

    # Store in DB
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_id = db.create_performance_report(admin_id, month, year, json.dumps(report_data), now)

    logger.info(f"Report: generated monthly report {report_id} for admin {admin_id}, {year}-{month:02d}")
    return report_id


# ── Report Retrieval ─────────────────────────────────────────────────────────

def get_report(report_id):
    """Return full report data (parsed from JSON)."""
    import database as db
    return db.get_performance_report(report_id)


def get_reports(admin_id):
    """List all reports for an admin."""
    import database as db
    return db.get_performance_reports(admin_id)


# ── HTML Report Rendering ────────────────────────────────────────────────────

def generate_report_html(report_id):
    """Return a nicely styled HTML report with summary cards, tables,
    and CSS-only charts. No JS dependencies."""
    import database as db

    report = db.get_performance_report(report_id)
    if not report:
        return None

    data = report.get("report_data", {})
    if isinstance(data, str):
        data = json.loads(data)

    summary = data.get("summary", {})
    month_name = data.get("month_name", "")
    year = data.get("year", "")
    top_services = data.get("top_services", [])
    doctor_perf = data.get("doctor_performance", [])
    daily_dist = data.get("daily_distribution", [])

    # Build summary cards
    cards = [
        ("Total Bookings", summary.get("total_bookings", 0), "#667eea"),
        ("Completed", summary.get("completed", 0), "#28a745"),
        ("No-Shows", summary.get("no_shows", 0), "#dc3545"),
        ("Cancelled", summary.get("cancelled", 0), "#f0ad4e"),
        ("New Patients", summary.get("new_patients", 0), "#17a2b8"),
        ("Revenue", f"{summary.get('revenue', 0):,.2f} {summary.get('currency', 'USD')}", "#6f42c1"),
    ]

    cards_html = ""
    for label, value, color in cards:
        cards_html += f"""
        <div style="flex:1;min-width:140px;background:#fff;border-radius:10px;padding:20px;margin:6px;
                     box-shadow:0 2px 8px rgba(0,0,0,0.06);border-left:4px solid {color};">
            <div style="font-size:12px;color:#888;text-transform:uppercase;letter-spacing:0.5px;">{label}</div>
            <div style="font-size:24px;font-weight:700;color:{color};margin-top:6px;">{value}</div>
        </div>"""

    # Rate cards
    rates_html = ""
    for label, key, color in [
        ("Completion Rate", "completion_rate", "#28a745"),
        ("No-Show Rate", "noshow_rate", "#dc3545"),
        ("Cancellation Rate", "cancellation_rate", "#f0ad4e"),
    ]:
        rate = summary.get(key, 0)
        rates_html += f"""
        <div style="flex:1;min-width:180px;margin:6px;background:#fff;border-radius:10px;padding:20px;
                     box-shadow:0 2px 8px rgba(0,0,0,0.06);">
            <div style="font-size:12px;color:#888;text-transform:uppercase;">{label}</div>
            <div style="font-size:22px;font-weight:700;color:{color};margin:6px 0;">{rate}%</div>
            <div style="background:#eee;border-radius:4px;height:8px;overflow:hidden;">
                <div style="background:{color};width:{min(rate, 100)}%;height:100%;border-radius:4px;"></div>
            </div>
        </div>"""

    # Top services table
    services_rows = ""
    for svc in top_services:
        services_rows += f"""
        <tr>
            <td style="padding:10px 12px;border-bottom:1px solid #f0f0f0;">{svc.get('service','')}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #f0f0f0;text-align:center;">{svc.get('count',0)}</td>
        </tr>"""

    # Doctor performance table
    doctor_rows = ""
    for doc in doctor_perf:
        doctor_rows += f"""
        <tr>
            <td style="padding:10px 12px;border-bottom:1px solid #f0f0f0;">{doc.get('doctor_name','Unassigned')}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #f0f0f0;text-align:center;">{doc.get('total',0)}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #f0f0f0;text-align:center;color:#28a745;">{doc.get('completed',0)}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #f0f0f0;text-align:center;color:#dc3545;">{doc.get('no_shows',0)}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #f0f0f0;text-align:center;color:#f0ad4e;">{doc.get('cancelled',0)}</td>
        </tr>"""

    # CSS bar chart for daily distribution
    max_count = max((d.get("count", 0) for d in daily_dist), default=1) or 1
    bars_html = ""
    for d in daily_dist:
        pct = round(d.get("count", 0) / max_count * 100)
        day = d.get("date", "")[-2:]
        bars_html += f"""
        <div style="flex:1;min-width:16px;display:flex;flex-direction:column;align-items:center;margin:0 1px;">
            <div style="font-size:9px;color:#888;margin-bottom:2px;">{d.get('count',0)}</div>
            <div style="width:100%;max-width:24px;background:linear-gradient(180deg,#667eea,#764ba2);
                         height:{pct}px;min-height:2px;border-radius:3px 3px 0 0;"></div>
            <div style="font-size:9px;color:#aaa;margin-top:2px;">{day}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Monthly Report — {month_name} {year}</title>
<style>
    @media print {{
        body {{ margin: 0; padding: 0; background: #fff; }}
        .container {{ box-shadow: none; }}
    }}
    body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background: #f0f2f5; margin: 0; padding: 20px; color: #333; }}
    .container {{ max-width: 900px; margin: 0 auto; }}
    h2 {{ color: #333; font-size: 18px; margin: 30px 0 15px; padding-bottom: 8px; border-bottom: 2px solid #eee; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
    th {{ background: #f8f9fa; padding: 10px 12px; text-align: left; font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
</style>
</head>
<body>
<div class="container">
    <!-- Header -->
    <div style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:30px 40px;border-radius:12px;margin-bottom:24px;">
        <h1 style="margin:0;font-size:26px;">Monthly Performance Report</h1>
        <div style="opacity:0.85;margin-top:8px;font-size:16px;">{month_name} {year}</div>
        <div style="opacity:0.7;margin-top:4px;font-size:13px;">Generated: {report.get('generated_at','')}</div>
    </div>

    <!-- Summary Cards -->
    <div style="display:flex;flex-wrap:wrap;margin:-6px;">
        {cards_html}
    </div>

    <!-- Rate Cards -->
    <h2>Key Rates</h2>
    <div style="display:flex;flex-wrap:wrap;margin:-6px;">
        {rates_html}
    </div>

    <!-- Daily Distribution Chart -->
    <h2>Daily Bookings</h2>
    <div style="background:#fff;border-radius:10px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
        <div style="display:flex;align-items:flex-end;height:120px;padding:0 4px;">
            {bars_html if bars_html else '<div style="color:#999;font-size:14px;">No booking data for this period.</div>'}
        </div>
    </div>

    <!-- Top Services -->
    <h2>Top Services</h2>
    <table>
        <thead><tr><th>Service</th><th style="text-align:center;width:100px;">Bookings</th></tr></thead>
        <tbody>
            {services_rows if services_rows else '<tr><td colspan="2" style="padding:20px;text-align:center;color:#999;">No service data</td></tr>'}
        </tbody>
    </table>

    <!-- Doctor Performance -->
    <h2>Doctor Performance</h2>
    <table>
        <thead>
            <tr><th>Doctor</th><th style="text-align:center;">Total</th><th style="text-align:center;">Completed</th><th style="text-align:center;">No-Shows</th><th style="text-align:center;">Cancelled</th></tr>
        </thead>
        <tbody>
            {doctor_rows if doctor_rows else '<tr><td colspan="5" style="padding:20px;text-align:center;color:#999;">No doctor data</td></tr>'}
        </tbody>
    </table>

    <!-- Footer -->
    <div style="text-align:center;margin-top:40px;padding:20px;color:#999;font-size:12px;">
        Generated by ChatGenius AI &mdash; {month_name} {year}
    </div>
</div>
</body>
</html>"""


# ── Email Report ─────────────────────────────────────────────────────────────

def email_report(report_id, recipients=None):
    """Send report HTML via email to the specified recipients list."""
    import database as db
    import email_service as email_svc

    report = db.get_performance_report(report_id)
    if not report:
        return False

    data = report.get("report_data", {})
    if isinstance(data, str):
        data = json.loads(data)

    month_name = data.get("month_name", "")
    year = data.get("year", "")

    html = generate_report_html(report_id)
    if not html:
        return False

    if not recipients:
        # Try to get from report config
        config = db.get_report_config(report.get("admin_id", 0))
        if config and config.get("recipients_json"):
            try:
                recipients = json.loads(config["recipients_json"])
            except (json.JSONDecodeError, TypeError):
                recipients = []

    if not recipients:
        logger.warning(f"Report: no recipients for report {report_id}")
        return False

    subject = f"Monthly Performance Report — {month_name} {year}"
    sent_count = 0
    for email in recipients:
        try:
            if email_svc._send_email(email, subject, html):
                sent_count += 1
        except Exception as e:
            logger.error(f"Report: failed to email report to {email}: {e}")

    if sent_count > 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = db.get_db()
        conn.execute("UPDATE performance_reports SET emailed_at=? WHERE id=?", (now, report_id))
        conn.commit()
        conn.close()

    logger.info(f"Report: emailed report {report_id} to {sent_count}/{len(recipients)} recipients")
    return sent_count > 0


# ── Monthly Auto-Generation ──────────────────────────────────────────────────

def generate_all_monthly_reports():
    """Called on 1st of month by background task.
    Generates reports for all active admins for the previous month."""
    import database as db

    now = datetime.now()
    # Previous month
    if now.month == 1:
        target_year = now.year - 1
        target_month = 12
    else:
        target_year = now.year
        target_month = now.month - 1

    conn = db.get_db()
    admins = conn.execute("SELECT id FROM users WHERE role IN ('admin', 'head_admin')").fetchall()
    conn.close()

    count = 0
    for admin in admins:
        admin_id = admin["id"]
        # Check feature flag first
        if not db.is_feature_enabled(admin_id, "auto_reports"):
            continue
        # Check if auto-generate is enabled
        config = db.get_report_config(admin_id)
        if config and not config.get("auto_generate", 1):
            continue

        # Check if already generated
        conn2 = db.get_db()
        existing = conn2.execute(
            "SELECT id FROM performance_reports WHERE admin_id=? AND month=? AND year=?",
            (admin_id, target_month, target_year),
        ).fetchone()
        conn2.close()

        if existing:
            continue

        try:
            report_id = generate_monthly_report(admin_id, target_year, target_month)
            if report_id and config and config.get("recipients_json"):
                email_report(report_id)
            count += 1
        except Exception as e:
            logger.error(f"Report: failed to generate for admin {admin_id}: {e}")

    logger.info(f"Report: generated {count} monthly reports for {target_year}-{target_month:02d}")
    return count


# ── Report Config ────────────────────────────────────────────────────────────

def get_config(admin_id):
    """Get report configuration for an admin."""
    import database as db
    return db.get_report_config(admin_id)


def save_config(admin_id, **kwargs):
    """Save/update report configuration."""
    import database as db
    return db.save_report_config(admin_id, **kwargs)
