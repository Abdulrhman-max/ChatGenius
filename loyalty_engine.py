"""
Patient Loyalty Program Engine for ChatGenius.
Manages points earning, redemption, tier analytics, and lifecycle hooks.

Works alongside database.py loyalty functions, providing a higher-level API
with config caching, convenience hooks for the booking flow, and richer
analytics for the admin dashboard.
"""
import logging
from datetime import datetime

import database as db

logger = logging.getLogger("loyalty")

# ──────────────────────────────────────────────────────────
# Default point values — must match loyalty_config table defaults
# ──────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "points_per_appointment": 100,
    "points_per_referral": 200,
    "points_per_review": 50,
    "points_per_form": 25,
    "redemption_value": 0.01,   # SAR earned per point (1 pt = 0.01 SAR)
    "is_active": 1,
}


# ──────────────────────────────────────────────────────────
# Configuration helpers
# ──────────────────────────────────────────────────────────

def get_config(admin_id):
    """Return the loyalty config dict for *admin_id*.

    If no row exists yet the database-level defaults are used (no row is
    inserted here — ``save_loyalty_config`` in *database.py* handles upserts).
    """
    config = db.get_loyalty_config(admin_id)
    if config is None:
        # Return a copy so callers cannot mutate the module-level dict.
        return {**DEFAULT_CONFIG, "admin_id": admin_id}
    return config


def update_config(admin_id, **kwargs):
    """Persist loyalty config changes.  Delegates to ``db.save_loyalty_config``."""
    db.save_loyalty_config(admin_id, **kwargs)


def is_active(admin_id):
    """Return *True* when the loyalty programme is switched on."""
    config = get_config(admin_id)
    return bool(config.get("is_active"))


# ──────────────────────────────────────────────────────────
# Point operations
# ──────────────────────────────────────────────────────────

def award_points(patient_id, admin_id, points, action, description="", booking_id=0):
    """Award *points* to a patient.

    ``action`` should be one of: ``'appointment'``, ``'referral'``,
    ``'review'``, ``'form_completed'``, ``'manual'``.

    Returns the number of points awarded (``0`` when the programme is
    inactive or *points* is non-positive).
    """
    if points <= 0:
        return 0

    if not is_active(admin_id):
        logger.debug("Loyalty programme inactive for admin %s — skipping award", admin_id)
        return 0

    db.add_loyalty_points(patient_id, admin_id, points, action, description, booking_id)
    logger.info("Awarded %d points to patient #%d for %s", points, patient_id, action)
    return points


def revoke_points(patient_id, admin_id, points, action, description="", booking_id=0):
    """Revoke (subtract) *points* from a patient.

    A negative transaction is recorded with the action prefixed by
    ``revoke_``.  The patient balance is clamped at zero.
    """
    if points <= 0:
        return

    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO loyalty_transactions "
            "(patient_id, admin_id, points, action, description, booking_id) "
            "VALUES (?,?,?,?,?,?)",
            (patient_id, admin_id, -abs(points), f"revoke_{action}", description, booking_id),
        )
        conn.execute(
            "UPDATE patients SET loyalty_points = MAX(0, loyalty_points - ?) WHERE id=?",
            (abs(points), patient_id),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info("Revoked %d points from patient #%d for %s", points, patient_id, action)


# ──────────────────────────────────────────────────────────
# Balance & redemption
# ──────────────────────────────────────────────────────────

def get_balance(patient_id):
    """Return the patient's current loyalty-point balance (``int``)."""
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT loyalty_points FROM patients WHERE id=?", (patient_id,)
        ).fetchone()
    finally:
        conn.close()
    return (row["loyalty_points"] or 0) if row else 0


def get_balance_value(patient_id, admin_id):
    """Return balance together with its SAR equivalent.

    >>> get_balance_value(42, 1)
    {"points": 500, "sar_value": 5.0, "redemption_rate": 0.01}
    """
    points = get_balance(patient_id)
    config = get_config(admin_id)
    rate = config.get("redemption_value") or DEFAULT_CONFIG["redemption_value"]
    sar_value = round(points * rate, 2)
    return {"points": points, "sar_value": sar_value, "redemption_rate": rate}


def redeem_points(patient_id, admin_id, points_to_redeem, booking_id=0):
    """Redeem points for a discount.

    Returns a dict:
    * On success: ``{"success": True, "redeemed": 350, "sar_value": 3.5}``
    * On failure: ``{"success": False, "error": "..."}``
    """
    if not is_active(admin_id):
        return {"success": False, "error": "Loyalty program is not active."}

    if points_to_redeem <= 0:
        return {"success": False, "error": "Points to redeem must be positive."}

    balance = get_balance(patient_id)
    if points_to_redeem > balance:
        return {"success": False, "error": f"Insufficient points. You have {balance} points."}

    config = get_config(admin_id)
    rate = config.get("redemption_value") or DEFAULT_CONFIG["redemption_value"]
    sar_value = round(points_to_redeem * rate, 2)

    description = f"Redeemed {points_to_redeem} points for {sar_value} SAR discount"
    success, msg = db.redeem_loyalty_points(
        patient_id, admin_id, points_to_redeem, description, booking_id
    )

    if not success:
        return {"success": False, "error": msg}

    logger.info("Patient #%d redeemed %d points (%.2f SAR)", patient_id, points_to_redeem, sar_value)
    return {"success": True, "redeemed": points_to_redeem, "sar_value": sar_value}


# ──────────────────────────────────────────────────────────
# History & analytics
# ──────────────────────────────────────────────────────────

def get_patient_history(patient_id):
    """Return the full points-transaction history for a patient (newest first)."""
    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM loyalty_transactions WHERE patient_id=? ORDER BY created_at DESC",
            (patient_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_admin_stats(admin_id):
    """Return loyalty-programme dashboard statistics.

    Augments ``db.get_loyalty_stats`` with the full config block and an
    ``is_active`` flag so the front-end has everything in one call.
    """
    config = get_config(admin_id)
    raw_stats = db.get_loyalty_stats(admin_id)

    return {
        "is_active": bool(config.get("is_active")),
        "config": config,
        "active_members": raw_stats.get("total_members", 0),
        "points_issued_this_month": raw_stats.get("issued_this_month", 0),
        "points_redeemed_this_month": raw_stats.get("redeemed_this_month", 0),
        "top_patients": raw_stats.get("top_patients", []),
    }


# ──────────────────────────────────────────────────────────
# Booking-flow lifecycle hooks
# ──────────────────────────────────────────────────────────

def on_appointment_completed(patient_id, admin_id, booking_id):
    """Award points when an appointment is completed."""
    config = get_config(admin_id)
    points = config.get("points_per_appointment", DEFAULT_CONFIG["points_per_appointment"])
    return award_points(
        patient_id, admin_id, points, "appointment",
        "Points earned for completing appointment", booking_id,
    )


def on_referral_booked(patient_id, admin_id):
    """Award points when a referred friend books an appointment."""
    config = get_config(admin_id)
    points = config.get("points_per_referral", DEFAULT_CONFIG["points_per_referral"])
    return award_points(
        patient_id, admin_id, points, "referral",
        "Points earned for successful referral",
    )


def on_review_submitted(patient_id, admin_id):
    """Award points for leaving a review."""
    config = get_config(admin_id)
    points = config.get("points_per_review", DEFAULT_CONFIG["points_per_review"])
    return award_points(
        patient_id, admin_id, points, "review",
        "Points earned for leaving a review",
    )


def on_form_submitted(patient_id, admin_id):
    """Award points for submitting a pre-visit form."""
    config = get_config(admin_id)
    points = config.get("points_per_form", DEFAULT_CONFIG["points_per_form"])
    return award_points(
        patient_id, admin_id, points, "form_completed",
        "Points earned for submitting pre-visit form",
    )


def on_booking_cancelled(patient_id, admin_id, booking_id):
    """Reverse any points that were earned for *booking_id*."""
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(points), 0) AS total "
            "FROM loyalty_transactions "
            "WHERE patient_id=? AND booking_id=? AND points > 0",
            (patient_id, booking_id),
        ).fetchone()
    finally:
        conn.close()

    earned = row["total"] if row else 0
    if earned > 0:
        revoke_points(
            patient_id, admin_id, earned, "cancellation",
            "Points reversed due to booking cancellation", booking_id,
        )
