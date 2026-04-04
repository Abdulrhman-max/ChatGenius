"""
Background task scheduler for ChatGenius.
Uses APScheduler with SQLite job store for persistence across restarts.
"""

import logging
import os
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

logger = logging.getLogger("background_tasks")

DB_DIR = os.path.dirname(__file__)
SCHEDULER_DB_PATH = os.path.join(DB_DIR, "scheduler.db")

_scheduler = None


# ── Deadline calculation ─────────────────────────────────────────────────────

def _calculate_confirm_deadline(appointment_date_str, appointment_time_str):
    """Calculate how long a patient has to confirm based on appointment proximity.
    - Appointment > 1 day away  -> 2 hours to confirm
    - Appointment is tomorrow   -> 30 minutes to confirm
    - Appointment is today      -> 10 minutes to confirm
    """
    now = datetime.now()
    try:
        appt_date = datetime.strptime(appointment_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        # Fallback: 30 minutes
        return (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

    days_until = (appt_date - now.date()).days

    if days_until <= 0:
        # Today
        deadline = now + timedelta(minutes=10)
    elif days_until == 1:
        # Tomorrow
        deadline = now + timedelta(minutes=30)
    else:
        # More than 1 day away
        deadline = now + timedelta(hours=2)

    return deadline.strftime("%Y-%m-%d %H:%M:%S")


def _format_deadline_display(deadline_str):
    """Convert a deadline timestamp to a human-readable string."""
    try:
        deadline = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        diff = deadline - now
        total_minutes = int(diff.total_seconds() / 60)
        if total_minutes >= 60:
            hours = total_minutes // 60
            mins = total_minutes % 60
            if mins > 0:
                return f"{hours} hour{'s' if hours > 1 else ''} and {mins} minute{'s' if mins > 1 else ''}"
            return f"{hours} hour{'s' if hours > 1 else ''}"
        elif total_minutes > 0:
            return f"{total_minutes} minute{'s' if total_minutes > 1 else ''}"
        else:
            return "a few seconds"
    except (ValueError, TypeError):
        return "the allotted time"


# ── Notify a single waitlist patient ─────────────────────────────────────────

def _notify_next_patient(admin_id, doctor_id, date, time_slot):
    """Find the next waiting patient for a slot, notify them, and send email.
    Returns True if a patient was notified, False if no one is waiting."""
    import database as db
    import email_service as email_svc

    patient = db.get_next_waiting_patient(admin_id, doctor_id, date, time_slot)
    if not patient:
        # No more waiting patients — release the slot back to public
        db.release_held_slot(admin_id, doctor_id, date, time_slot)
        logger.info(f"Waitlist: no more patients for {date} {time_slot} — slot released to public")
        return False

    # Calculate deadline
    deadline = _calculate_confirm_deadline(date, time_slot)
    db.notify_waitlist_patient(patient["id"], deadline)
    logger.info(f"Waitlist: notified {patient['patient_name']} (id={patient['id']}) for {date} {time_slot}, deadline={deadline}")

    # Send notification email
    if patient.get("patient_email"):
        try:
            # Get doctor name
            doctor = db.get_doctor_by_id(doctor_id)
            doctor_name = doctor["name"] if doctor else ""

            # Format date for display
            try:
                dt = datetime.strptime(date, "%Y-%m-%d")
                date_display = dt.strftime("%A, %B %d, %Y")
            except ValueError:
                date_display = date

            deadline_display = _format_deadline_display(deadline)

            # Build confirm URL
            confirm_url = f"/api/waitlist/{patient['id']}/confirm"

            email_svc.send_waitlist_notification(
                to_email=patient["patient_email"],
                patient_name=patient["patient_name"],
                date_display=date_display,
                time_slot=time_slot,
                confirm_deadline=deadline_display,
                confirm_url=confirm_url,
                doctor_name=doctor_name
            )
            logger.info(f"Waitlist: notification email sent to {patient['patient_email']}")
        except Exception as e:
            logger.error(f"Waitlist: failed to send notification email to {patient.get('patient_email')}: {e}")

    return True


# ── Scheduled jobs ───────────────────────────────────────────────────────────

def _process_expired_waitlist_notifications():
    """Check for expired waitlist notifications and cascade to next patient.
    Runs every 30 seconds via APScheduler."""
    import database as db

    try:
        expired = db.get_active_waitlist_notifications()
        if not expired:
            return

        logger.info(f"Waitlist: found {len(expired)} expired notification(s) to process")

        for entry in expired:
            # Mark as expired
            db.expire_waitlist_patient(entry["id"])
            logger.info(f"Waitlist: expired entry id={entry['id']} ({entry['patient_name']})")

            # Try to notify the next waiting patient for this slot
            _notify_next_patient(
                entry["admin_id"], entry["doctor_id"],
                entry["date"], entry["time_slot"]
            )
    except Exception as e:
        logger.error(f"Waitlist expiry check error: {e}")


def _process_noshow_detection():
    """Detect no-shows: appointments 10+ minutes past start time without check-in."""
    import database as db

    conn = db.get_db()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT * FROM bookings WHERE date=? AND status='confirmed' AND checked_in=0",
        (today,)
    ).fetchall()
    for row in rows:
        row = dict(row)
        try:
            time_str = row["time"].split(" - ")[0].strip() if " - " in row["time"] else row["time"].strip()
            appt_time = datetime.strptime(f"{today} {time_str}", "%Y-%m-%d %I:%M %p")
            if now > appt_time + timedelta(minutes=10):
                conn.execute("UPDATE bookings SET status='no_show' WHERE id=? AND status='confirmed'", (row["id"],))
                if row.get("patient_id"):
                    conn.execute("UPDATE patients SET total_no_shows=total_no_shows+1 WHERE id=?", (row["patient_id"],))
                conn.commit()
                logger.info(f"No-show detected: booking {row['id']} for {row['customer_name']}")
        except (ValueError, IndexError):
            pass
    conn.close()


# ── Public API ───────────────────────────────────────────────────────────────

def trigger_waitlist_processing(admin_id, doctor_id, date, time_slot):
    """Called when a cancellation happens — immediately starts the waitlist cascade for that slot.
    Finds the first waiting patient, calculates deadline, notifies them."""
    return _notify_next_patient(admin_id, doctor_id, date, time_slot)


def process_cancellation_waitlist(admin_id, doctor_id, date, time_slot):
    """Legacy alias for trigger_waitlist_processing."""
    return trigger_waitlist_processing(admin_id, doctor_id, date, time_slot)


def start_background_tasks(app):
    """Start APScheduler with persistent SQLite job store."""
    global _scheduler
    if _scheduler is not None:
        return

    jobstores = {
        "default": SQLAlchemyJobStore(url=f"sqlite:///{SCHEDULER_DB_PATH}")
    }
    executors = {
        "default": ThreadPoolExecutor(4)
    }
    job_defaults = {
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 60,
    }

    _scheduler = BackgroundScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
    )

    # Waitlist expiry check — every 30 seconds
    _scheduler.add_job(
        _process_expired_waitlist_notifications,
        "interval",
        seconds=30,
        id="waitlist_expiry_check",
        replace_existing=True,
        name="Check expired waitlist notifications",
    )

    # No-show detection — every 60 seconds
    _scheduler.add_job(
        _process_noshow_detection,
        "interval",
        seconds=60,
        id="noshow_detection",
        replace_existing=True,
        name="Detect no-show appointments",
    )

    # ── New engine scheduled jobs ──

    # Recall engine — daily campaigns
    try:
        import recall_engine
        _scheduler.add_job(
            recall_engine.process_recall_campaigns,
            "cron", hour=9, minute=0,
            id="recall_campaigns", replace_existing=True,
            name="Process recall campaigns (daily 9am)",
        )
        _scheduler.add_job(
            recall_engine.process_birthday_greetings,
            "cron", hour=8, minute=0,
            id="birthday_greetings", replace_existing=True,
            name="Process birthday greetings (daily 8am)",
        )
        _scheduler.add_job(
            recall_engine.process_reengagement,
            "cron", hour=10, minute=0,
            id="reengagement", replace_existing=True,
            name="Process re-engagement (daily 10am)",
        )
        _scheduler.add_job(
            recall_engine.process_second_reminders,
            "cron", hour=9, minute=30,
            id="second_reminders", replace_existing=True,
            name="Process second reminders (daily 9:30am)",
        )
        logger.info("Recall engine jobs registered")
    except Exception as e:
        logger.warning(f"Could not register recall engine jobs: {e}")

    # Treatment follow-up engine — daily processing
    try:
        import treatment_followup_engine
        _scheduler.add_job(
            treatment_followup_engine.process_pending_followups,
            "cron", hour=9, minute=0,
            id="treatment_followups", replace_existing=True,
            name="Process pending treatment follow-ups (daily 9am)",
        )
        logger.info("Treatment follow-up engine job registered")
    except Exception as e:
        logger.warning(f"Could not register treatment follow-up job: {e}")

    # Benchmarking engine — daily metrics refresh
    try:
        import benchmarking_engine as _benchmarks
        _scheduler.add_job(
            _benchmarks.refresh_all_metrics,
            "cron", hour=2, minute=0,
            id="benchmark_refresh", replace_existing=True,
            name="Refresh all benchmark metrics (daily 2am)",
        )
        logger.info("Benchmarking engine job registered")
    except Exception as e:
        logger.warning(f"Could not register benchmarking job: {e}")

    # Handoff engine — timeout check
    try:
        import handoff_engine as _handoff
        _scheduler.add_job(
            _handoff.check_handoff_timeout,
            "interval", seconds=60,
            id="handoff_timeout_check", replace_existing=True,
            name="Check handoff timeouts (every 60s)",
        )
        logger.info("Handoff timeout check job registered")
    except Exception as e:
        logger.warning(f"Could not register handoff timeout job: {e}")

    _scheduler.start()
    logger.info("APScheduler started with waitlist expiry (30s), no-show detection (60s), and engine jobs")


def stop_background_tasks():
    """Shut down the scheduler gracefully."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("APScheduler shut down")
