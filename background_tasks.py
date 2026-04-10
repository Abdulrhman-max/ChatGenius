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

def _calculate_confirm_deadline(appointment_date_str, appointment_time_str, is_only_on_waitlist=False):
    """Calculate how long a patient has to fill the pre-visit form.
    - Only person on waitlist     -> 5 hours to fill form
    - Appointment <= 24 hours away -> 3 hours to fill form
    - Appointment > 24 hours away  -> 5 hours to fill form
    """
    now = datetime.now()

    # If only person on waitlist, always give 5 hours
    if is_only_on_waitlist:
        return (now + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")

    try:
        appt_date = datetime.strptime(appointment_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        # Fallback: 5 hours
        return (now + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")

    # Calculate hours until appointment
    try:
        # Try to parse the time for a more accurate calculation
        time_part = appointment_time_str.split(" - ")[0].strip() if " - " in appointment_time_str else appointment_time_str.strip()
        appt_dt = datetime.strptime(f"{appointment_date_str} {time_part}", "%Y-%m-%d %I:%M %p")
    except (ValueError, TypeError):
        appt_dt = datetime.combine(appt_date, datetime.min.time().replace(hour=9))

    hours_until = (appt_dt - now).total_seconds() / 3600

    if hours_until <= 24:
        deadline = now + timedelta(hours=3)
    else:
        deadline = now + timedelta(hours=5)

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

    # Check if this patient is the only one remaining on waitlist for this slot
    is_only = False
    try:
        remaining = db.get_waitlist_count(admin_id, doctor_id, date, time_slot)
        is_only = (remaining <= 1)
    except Exception:
        pass

    # Calculate deadline with new rules
    deadline = _calculate_confirm_deadline(date, time_slot, is_only_on_waitlist=is_only)
    db.notify_waitlist_patient(patient["id"], deadline)
    logger.info(f"Waitlist: notified {patient['patient_name']} (id={patient['id']}) for {date} {time_slot}, deadline={deadline}, only_on_waitlist={is_only}")

    # Send notification email with link to confirm (which redirects to form)
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

            # Build confirm URL — this will create a pending booking + form and redirect to form
            base_url = os.getenv("BASE_URL", "http://localhost:8080")
            confirm_url = f"{base_url}/api/waitlist/{patient['id']}/confirm"

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
    import email_service as email_svc

    try:
        expired = db.get_active_waitlist_notifications()
        if not expired:
            return

        logger.info(f"Waitlist: found {len(expired)} expired notification(s) to process")

        for entry in expired:
            # Mark as expired
            db.expire_waitlist_patient(entry["id"])
            logger.info(f"Waitlist: expired entry id={entry['id']} ({entry['patient_name']})")

            # Cancel any pending booking created for this waitlist entry
            try:
                conn = db.get_db()
                pending = conn.execute(
                    "SELECT id FROM bookings WHERE waitlist_id=? AND status='pending'",
                    (entry["id"],)).fetchone()
                if pending:
                    conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (pending["id"],))
                    conn.commit()
                    logger.info(f"Waitlist: cancelled pending booking {pending['id']} for expired entry {entry['id']}")
                conn.close()
            except Exception as e:
                logger.error(f"Waitlist: error cancelling pending booking for entry {entry['id']}: {e}")

            # Send "you took too long" email to the expired patient
            if entry.get("patient_email"):
                try:
                    try:
                        dt = datetime.strptime(entry["date"], "%Y-%m-%d")
                        date_display = dt.strftime("%A, %B %d, %Y")
                    except ValueError:
                        date_display = entry["date"]
                    doctor = db.get_doctor_by_id(entry["doctor_id"])
                    doctor_name = doctor["name"] if doctor else ""
                    email_svc.send_waitlist_expired_notification(
                        entry["patient_email"], entry["patient_name"],
                        date_display, entry["time_slot"], doctor_name=doctor_name
                    )
                except Exception as e:
                    logger.error(f"Waitlist: failed to send expiry email to {entry.get('patient_email')}: {e}")

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
    try:
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
                    # Trigger no-show recovery
                    try:
                        import noshow_recovery_engine
                        noshow_recovery_engine.on_noshow_detected(row["id"])
                    except Exception as e:
                        logger.warning(f"No-show recovery trigger failed for booking {row['id']}: {e}")
            except (ValueError, IndexError):
                pass
    finally:
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

    # Lead follow-up engine — daily processing + stage progression
    try:
        import lead_engine as _leads
        _scheduler.add_job(
            _leads.process_pending_followups,
            "cron", hour=9, minute=15,
            id="lead_followups", replace_existing=True,
            name="Process pending lead follow-ups (daily 9:15am)",
        )
        _scheduler.add_job(
            _leads.auto_progress_stages,
            "cron", hour=10, minute=0,
            id="lead_stage_progression", replace_existing=True,
            name="Auto-progress lead stages (daily 10am)",
        )
        logger.info("Lead engine jobs registered")
    except Exception as e:
        logger.warning(f"Could not register lead engine jobs: {e}")

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

    # ── Feature 1: Smart Appointment Reminders — process pending every 60s ──
    try:
        import appointment_reminder_engine as _reminder_eng
        _scheduler.add_job(
            _reminder_eng.process_pending_reminders,
            "interval", seconds=60,
            id="reminder_processing", replace_existing=True,
            name="Process pending appointment reminders (every 60s)",
        )
        logger.info("Appointment reminder processing job registered")
    except Exception as e:
        logger.warning(f"Could not register reminder processing job: {e}")

    # ── Feature 6: Monthly Performance Report — auto-generate on 1st of month ──
    try:
        import report_engine as _report_eng
        _scheduler.add_job(
            _report_eng.generate_all_monthly_reports,
            "cron", day=1, hour=6, minute=0,
            id="monthly_report_generation", replace_existing=True,
            name="Generate monthly performance reports (1st of month, 6am)",
        )
        logger.info("Monthly report generation job registered")
    except Exception as e:
        logger.warning(f"Could not register monthly report job: {e}")

    # ── Feature 9: No-Show Recovery — expire stale recoveries every 5 min ──
    try:
        import noshow_recovery_engine as _noshow_eng
        _scheduler.add_job(
            _noshow_eng.process_expired_recoveries,
            "interval", minutes=5,
            id="noshow_recovery_expiry", replace_existing=True,
            name="Expire stale no-show recovery records (every 5min)",
        )
        logger.info("No-show recovery expiry job registered")
    except Exception as e:
        logger.warning(f"Could not register no-show recovery job: {e}")

    _scheduler.start()
    logger.info("APScheduler started with all background jobs")


def stop_background_tasks():
    """Shut down the scheduler gracefully."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("APScheduler shut down")
