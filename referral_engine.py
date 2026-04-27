"""
Referral System Engine for ChatGenius.
Each clinic gets a unique referral link. Referring clinic gets rewarded
when the referred clinic completes their first paid month.
"""
import logging
import string
import random
from datetime import datetime

logger = logging.getLogger("referral")


def get_or_create_referral_code(admin_id):
    """Get existing referral code for an admin, or create one."""
    import database as db
    conn = db.get_db()

    user = conn.execute("SELECT referral_code FROM users WHERE id=%s", (admin_id,)).fetchone()
    if user and user["referral_code"]:
        conn.close()
        return user["referral_code"]

    # Generate unique code
    code = _generate_code(admin_id)
    conn.execute("UPDATE users SET referral_code=%s WHERE id=%s", (code, admin_id))
    conn.commit()
    conn.close()
    return code


def _generate_code(admin_id):
    """Generate a unique referral code based on business name or random."""
    import database as db
    conn = db.get_db()
    company = conn.execute("SELECT business_name FROM company_info WHERE user_id=%s", (admin_id,)).fetchone()
    conn.close()

    if company and company["business_name"]:
        # Create code from business name: "Bright Smile" -> "BRIGHTSMILE"
        base = ''.join(c for c in company["business_name"].upper() if c.isalnum())[:10]
    else:
        base = ''.join(random.choices(string.ascii_uppercase, k=6))

    # Ensure uniqueness
    import database as db
    conn = db.get_db()
    existing = conn.execute("SELECT id FROM users WHERE referral_code=%s", (base,)).fetchone()
    if existing:
        base = base + ''.join(random.choices(string.digits, k=3))
    conn.close()
    return base


def get_referral_link(admin_id, base_url="https://chatgenius.com"):
    """Get the full referral link for an admin."""
    code = get_or_create_referral_code(admin_id)
    return f"{base_url}/signup?ref={code}"


def track_signup(referred_email, referral_code):
    """
    Track when a new clinic signs up using a referral code.
    Called during signup. Creates a pending referral record.
    Returns: referrer admin_id or None.
    """
    import database as db
    conn = db.get_db()

    # Find the referrer
    referrer = conn.execute("SELECT id FROM users WHERE referral_code=%s", (referral_code,)).fetchone()
    if not referrer:
        conn.close()
        return None

    referrer_id = referrer["id"]

    # Prevent self-referral
    referred_user = conn.execute("SELECT id FROM users WHERE email=%s", (referred_email,)).fetchone()
    if referred_user and referred_user["id"] == referrer_id:
        conn.close()
        return None

    # Check if referral already tracked
    existing = conn.execute(
        "SELECT id FROM referrals WHERE referrer_admin_id=%s AND referred_email=%s",
        (referrer_id, referred_email)
    ).fetchone()
    if existing:
        conn.close()
        return referrer_id

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO referrals
           (referrer_admin_id, referred_email, referral_code, status, reward_type, reward_value, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (referrer_id, referred_email, referral_code, "pending", "free_month", 1, now)
    )
    conn.commit()
    conn.close()

    logger.info(f"Referral tracked: {referral_code} -> {referred_email}")
    return referrer_id


def convert_referral(referred_email, referred_admin_id):
    """
    Mark a referral as converted when the referred clinic completes first paid month.
    Awards the referrer their reward.
    """
    import database as db
    conn = db.get_db()

    referral = conn.execute(
        "SELECT * FROM referrals WHERE referred_email=%s AND status='pending' LIMIT 1",
        (referred_email,)
    ).fetchone()

    if not referral:
        conn.close()
        return None

    referral = dict(referral)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """UPDATE referrals SET status='converted', referred_admin_id=%s,
           converted_at=%s, reward_applied=0 WHERE id=%s""",
        (referred_admin_id, now, referral["id"])
    )
    conn.commit()
    conn.close()

    # Apply reward
    _apply_reward(referral["referrer_admin_id"], referral["id"])

    logger.info(f"Referral converted: {referred_email} (referrer: admin #{referral['referrer_admin_id']})")
    return referral


def _apply_reward(admin_id, referral_id):
    """Apply the referral reward to the referrer's next invoice."""
    import database as db
    conn = db.get_db()

    referral = conn.execute("SELECT * FROM referrals WHERE id=%s", (referral_id,)).fetchone()
    if not referral:
        conn.close()
        return

    referral = dict(referral)

    # Mark reward as applied
    conn.execute("UPDATE referrals SET reward_applied=1 WHERE id=%s", (referral_id,))
    conn.commit()
    conn.close()

    logger.info(f"Reward applied for admin #{admin_id}: {referral['reward_type']} ({referral['reward_value']})")


def cancel_referral(referred_email):
    """Cancel a referral if the referred clinic cancels before paying."""
    import database as db
    conn = db.get_db()
    conn.execute(
        "UPDATE referrals SET status='cancelled' WHERE referred_email=%s AND status='pending'",
        (referred_email,)
    )
    conn.commit()
    conn.close()


def get_referral_stats(admin_id):
    """Get referral dashboard data for an admin."""
    import database as db
    conn = db.get_db()

    code = get_or_create_referral_code(admin_id)

    total_sent = conn.execute(
        "SELECT COUNT(*) as c FROM referrals WHERE referrer_admin_id=%s", (admin_id,)
    ).fetchone()["c"]

    converted = conn.execute(
        "SELECT COUNT(*) as c FROM referrals WHERE referrer_admin_id=%s AND status='converted'", (admin_id,)
    ).fetchone()["c"]

    rewards_earned = conn.execute(
        "SELECT COUNT(*) as c FROM referrals WHERE referrer_admin_id=%s AND reward_applied=1", (admin_id,)
    ).fetchone()["c"]

    pending = conn.execute(
        "SELECT COUNT(*) as c FROM referrals WHERE referrer_admin_id=%s AND status='pending'", (admin_id,)
    ).fetchone()["c"]

    referrals_list = conn.execute(
        "SELECT * FROM referrals WHERE referrer_admin_id=%s ORDER BY created_at DESC",
        (admin_id,)
    ).fetchall()

    conn.close()

    return {
        "referral_code": code,
        "referral_link": f"/signup?ref={code}",
        "total_sent": total_sent,
        "converted": converted,
        "pending": pending,
        "rewards_earned": rewards_earned,
        "referrals": [dict(r) for r in referrals_list]
    }


def get_referral_tree(super_admin=True):
    """
    Get full referral tree for super admin.
    Shows: who referred who, conversion status, rewards.
    """
    if not super_admin:
        return {"error": "Unauthorized"}

    import database as db
    conn = db.get_db()

    referrals = conn.execute(
        """SELECT r.*,
                  u1.name as referrer_name, u1.email as referrer_email,
                  u2.name as referred_name
           FROM referrals r
           LEFT JOIN users u1 ON r.referrer_admin_id = u1.id
           LEFT JOIN users u2 ON r.referred_admin_id = u2.id
           ORDER BY r.created_at DESC"""
    ).fetchall()

    total_rewards = conn.execute(
        "SELECT COUNT(*) as c FROM referrals WHERE reward_applied=1"
    ).fetchone()["c"]

    conn.close()

    return {
        "referrals": [dict(r) for r in referrals],
        "total_rewards_given": total_rewards
    }
