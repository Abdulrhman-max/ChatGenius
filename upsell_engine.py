"""
Smart Upsell Engine for ChatGenius.
Detects upsell opportunities during chatbot conversations and tracks conversion.
"""
import logging
from datetime import datetime

logger = logging.getLogger("upsell_engine")


def detect_upsell(admin_id, treatment_name, session_id=None):
    """
    Check upsell_rules table for a matching suggestion.
    Returns a suggestion dict or None.
    Only returns if the upsell has not already been shown in this session.
    """
    import database as db

    rules = db.get_upsell_rules(admin_id, trigger_treatment=treatment_name)
    if not rules:
        return None

    # If session_id provided, filter out already-shown upsells
    already_shown_rule_ids = set()
    if session_id:
        impressions = db.get_upsell_impressions_for_session(session_id)
        already_shown_rule_ids = {imp["upsell_rule_id"] for imp in impressions}

    for rule in rules:
        if rule["id"] in already_shown_rule_ids:
            continue

        suggestion = {
            "rule_id": rule["id"],
            "trigger_treatment": rule["trigger_treatment"],
            "suggested_treatment": rule["suggested_treatment"],
            "suggested_package_id": rule.get("suggested_package_id"),
            "message_template": rule.get("message_template", ""),
            "discount_percent": rule.get("discount_percent", 0),
        }

        logger.info(f"Upsell detected: {treatment_name} -> {rule['suggested_treatment']} (rule #{rule['id']})")
        return suggestion

    return None


def format_upsell_message(suggestion):
    """
    Returns a chatbot-friendly markdown message for the upsell suggestion.
    """
    if not suggestion:
        return ""

    template = suggestion.get("message_template", "")
    if template:
        # Replace placeholders in template
        message = template.replace("{suggested_treatment}", suggestion.get("suggested_treatment", ""))
        message = message.replace("{trigger_treatment}", suggestion.get("trigger_treatment", ""))
        discount = suggestion.get("discount_percent", 0)
        message = message.replace("{discount_percent}", str(discount))
        return message

    # Default message
    suggested = suggestion.get("suggested_treatment", "our recommended treatment")
    trigger = suggestion.get("trigger_treatment", "your treatment")
    discount = suggestion.get("discount_percent", 0)

    message = f"**Special offer!** Since you're booking {trigger}, "
    message += f"we'd like to recommend **{suggested}** as well."

    if discount > 0:
        message += f"\n\nGet **{discount}% off** when you add it to your booking!"

    message += "\n\nWould you like to add this to your appointment?"

    return message


def record_impression(rule_id, session_id):
    """
    Track that an upsell was shown to a user.
    Returns the impression_id.
    """
    import database as db

    impression_id = db.record_upsell_impression(rule_id, session_id)
    logger.info(f"Upsell impression recorded: rule #{rule_id}, session {session_id}")
    return impression_id


def record_acceptance(impression_id, booking_id):
    """
    Track that an upsell was accepted and linked to a booking.
    """
    import database as db

    db.record_upsell_acceptance(impression_id, booking_id)
    logger.info(f"Upsell accepted: impression #{impression_id}, booking #{booking_id}")
    return {"success": True}


def get_upsell_analytics(admin_id):
    """
    Returns conversion rates per upsell rule.
    Each rule includes: total_impressions, total_accepted, conversion_rate.
    """
    import database as db
    return db.get_upsell_analytics_db(admin_id)
