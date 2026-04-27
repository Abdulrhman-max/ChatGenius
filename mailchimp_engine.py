"""
Mailchimp Email Marketing Integration Engine for ChatGenius.
Manages Mailchimp connection, audience sync, and subscriber tagging.
Uses Mailchimp Marketing REST API with API key authentication.
"""
import logging
import hashlib
from datetime import datetime

import requests as http_requests

logger = logging.getLogger("mailchimp")


# ── Helpers ──

def _get_dc(api_key):
    """Extract datacenter from Mailchimp API key (e.g., 'us21')."""
    if "-" in api_key:
        return api_key.split("-")[-1]
    return ""


def _base_url(api_key):
    dc = _get_dc(api_key)
    return f"https://{dc}.api.mailchimp.com/3.0"


def _auth(api_key):
    return ("anystring", api_key)


def _subscriber_hash(email):
    """MD5 hash of lowercase email (Mailchimp subscriber identifier)."""
    return hashlib.md5(email.lower().strip().encode()).hexdigest()


def _get_config(admin_id):
    """Load Mailchimp config from database."""
    import database as db
    conn = db.get_db()
    row = conn.execute("SELECT * FROM mailchimp_connections WHERE admin_id=%s", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Connection Management ──

def connect_mailchimp(api_key, admin_id):
    """Validate API key, store it, and return account info."""
    import database as db

    if not api_key or "-" not in api_key:
        return {"error": "Invalid API key format. Mailchimp keys end with a datacenter suffix (e.g., -us21)."}

    # Validate by calling the API root
    try:
        resp = http_requests.get(
            f"{_base_url(api_key)}/",
            auth=_auth(api_key),
            timeout=10
        )
        if resp.status_code == 401:
            return {"error": "Invalid API key. Please check and try again."}
        resp.raise_for_status()
        account = resp.json()
    except http_requests.exceptions.RequestException as e:
        logger.error(f"[mailchimp] Connection failed for admin #{admin_id}: {e}")
        return {"error": f"Could not connect to Mailchimp: {str(e)}"}

    # Store credentials
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = conn.execute("SELECT id FROM mailchimp_connections WHERE admin_id=%s", (admin_id,)).fetchone()

    if existing:
        conn.execute(
            """UPDATE mailchimp_connections SET
               api_key=%s, account_name=%s, datacenter=%s, connected_at=%s
               WHERE admin_id=%s""",
            (api_key, account.get("account_name", ""), _get_dc(api_key), now, admin_id)
        )
    else:
        conn.execute(
            """INSERT INTO mailchimp_connections
               (admin_id, api_key, account_name, datacenter, connected_at, created_at)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (admin_id, api_key, account.get("account_name", ""), _get_dc(api_key), now, now)
        )
    conn.commit()
    conn.close()

    logger.info(f"[mailchimp] Connected for admin #{admin_id}: {account.get('account_name', 'N/A')}")
    return {
        "connected": True,
        "account_name": account.get("account_name", ""),
        "email": account.get("email", ""),
    }


def disconnect(admin_id):
    """Remove Mailchimp connection."""
    import database as db
    conn = db.get_db()
    conn.execute("DELETE FROM mailchimp_connections WHERE admin_id=%s", (admin_id,))
    conn.commit()
    conn.close()
    logger.info(f"[mailchimp] Disconnected for admin #{admin_id}")
    return {"disconnected": True}


# ── Lists / Audiences ──

def get_lists(admin_id):
    """Fetch available Mailchimp audiences/lists."""
    config = _get_config(admin_id)
    if not config or not config.get("api_key"):
        return {"error": "Mailchimp not connected"}

    api_key = config["api_key"]
    try:
        resp = http_requests.get(
            f"{_base_url(api_key)}/lists",
            auth=_auth(api_key),
            params={"count": 100, "fields": "lists.id,lists.name,lists.stats.member_count"},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        lists = [
            {
                "id": lst["id"],
                "name": lst["name"],
                "member_count": lst.get("stats", {}).get("member_count", 0)
            }
            for lst in data.get("lists", [])
        ]
        return {"lists": lists}
    except http_requests.exceptions.RequestException as e:
        logger.error(f"[mailchimp] Failed to fetch lists for admin #{admin_id}: {e}")
        return {"error": f"Failed to fetch lists: {str(e)}"}


def configure(admin_id, list_id, auto_sync=False):
    """Set which list to sync to and auto-sync toggle."""
    import database as db
    conn = db.get_db()
    conn.execute(
        "UPDATE mailchimp_connections SET list_id=%s, auto_sync=%s WHERE admin_id=%s",
        (list_id, 1 if auto_sync else 0, admin_id)
    )
    conn.commit()
    conn.close()
    logger.info(f"[mailchimp] Configured list={list_id} auto_sync={auto_sync} for admin #{admin_id}")
    return {"ok": True, "list_id": list_id, "auto_sync": auto_sync}


# ── Subscriber Sync ──

def sync_patient_to_mailchimp(patient_data, admin_id):
    """Add or update a patient as a Mailchimp subscriber.
    patient_data should have: name, email, phone (optional)."""
    config = _get_config(admin_id)
    if not config or not config.get("api_key") or not config.get("list_id"):
        return {"error": "Mailchimp not configured"}

    email = (patient_data.get("email") or "").strip()
    if not email:
        return {"skipped": True, "reason": "No email address"}

    api_key = config["api_key"]
    list_id = config["list_id"]
    sub_hash = _subscriber_hash(email)

    # Split name into first/last
    name = (patient_data.get("name") or "").strip()
    parts = name.split(" ", 1)
    first_name = parts[0] if parts else ""
    last_name = parts[1] if len(parts) > 1 else ""

    payload = {
        "email_address": email,
        "status_if_new": "subscribed",
        "merge_fields": {
            "FNAME": first_name,
            "LNAME": last_name,
        }
    }
    if patient_data.get("phone"):
        payload["merge_fields"]["PHONE"] = patient_data["phone"]

    try:
        resp = http_requests.put(
            f"{_base_url(api_key)}/lists/{list_id}/members/{sub_hash}",
            auth=_auth(api_key),
            json=payload,
            timeout=10
        )
        if resp.status_code in (200, 201):
            logger.info(f"[mailchimp] Synced {email} for admin #{admin_id}")
            return {"synced": True, "email": email}
        else:
            error_detail = resp.json().get("detail", resp.text[:200])
            logger.warning(f"[mailchimp] Sync failed for {email}: {error_detail}")
            return {"error": error_detail, "email": email}
    except http_requests.exceptions.RequestException as e:
        logger.error(f"[mailchimp] Sync error for {email}: {e}")
        return {"error": str(e), "email": email}


def sync_all_patients(admin_id):
    """Bulk sync all patients for an admin to the configured Mailchimp list."""
    import database as db

    config = _get_config(admin_id)
    if not config or not config.get("api_key") or not config.get("list_id"):
        return {"error": "Mailchimp not configured"}

    patients = db.get_patients(admin_id)
    synced = 0
    skipped = 0
    errors = 0

    for p in patients:
        result = sync_patient_to_mailchimp(p, admin_id)
        if result.get("synced"):
            synced += 1
        elif result.get("skipped"):
            skipped += 1
        else:
            errors += 1

    # Update last sync time
    conn = db.get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE mailchimp_connections SET last_synced_at=%s, total_synced=%s WHERE admin_id=%s",
        (now, synced, admin_id)
    )
    conn.commit()
    conn.close()

    logger.info(f"[mailchimp] Bulk sync for admin #{admin_id}: {synced} synced, {skipped} skipped, {errors} errors")
    return {
        "ok": True,
        "synced": synced,
        "skipped": skipped,
        "errors": errors,
        "total_patients": len(patients),
        "last_synced_at": now,
    }


# ── Tags ──

def add_tags(email, tags, admin_id):
    """Add tags to a subscriber (e.g., 'new-patient', 'no-show', 'vip')."""
    config = _get_config(admin_id)
    if not config or not config.get("api_key") or not config.get("list_id"):
        return {"error": "Mailchimp not configured"}

    if not email:
        return {"error": "No email provided"}

    api_key = config["api_key"]
    list_id = config["list_id"]
    sub_hash = _subscriber_hash(email)

    tag_payload = {
        "tags": [{"name": t, "status": "active"} for t in tags]
    }

    try:
        resp = http_requests.post(
            f"{_base_url(api_key)}/lists/{list_id}/members/{sub_hash}/tags",
            auth=_auth(api_key),
            json=tag_payload,
            timeout=10
        )
        if resp.status_code in (200, 204):
            logger.info(f"[mailchimp] Tags {tags} added to {email} for admin #{admin_id}")
            return {"ok": True, "email": email, "tags": tags}
        else:
            error_detail = resp.json().get("detail", resp.text[:200]) if resp.text else "Unknown error"
            return {"error": error_detail}
    except http_requests.exceptions.RequestException as e:
        logger.error(f"[mailchimp] Tag error for {email}: {e}")
        return {"error": str(e)}


# ── Stats ──

def get_sync_stats(admin_id):
    """Return sync statistics and connection status."""
    config = _get_config(admin_id)
    if not config:
        return {"connected": False}

    return {
        "connected": True,
        "account_name": config.get("account_name", ""),
        "list_id": config.get("list_id", ""),
        "auto_sync": bool(config.get("auto_sync", 0)),
        "last_synced_at": config.get("last_synced_at", ""),
        "total_synced": config.get("total_synced", 0),
    }


# ── Auto-sync Hook ──

def auto_sync_if_enabled(patient_data, admin_id):
    """Hook to call after a patient/lead is created. Only syncs if auto_sync is on."""
    try:
        config = _get_config(admin_id)
        if not config or not config.get("auto_sync") or not config.get("list_id"):
            return None
        result = sync_patient_to_mailchimp(patient_data, admin_id)
        if result.get("synced"):
            # Tag as new-patient automatically
            email = (patient_data.get("email") or "").strip()
            if email:
                add_tags(email, ["new-patient"], admin_id)
        return result
    except Exception as e:
        logger.error(f"[mailchimp] Auto-sync error for admin #{admin_id}: {e}")
        return None
