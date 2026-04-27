"""
Multi-Channel Unified Inbox Engine (Feature 4).
Aggregates conversations from WhatsApp, Instagram, Facebook into one inbox.
Supports inbound webhooks and outbound messaging.
"""
import json
import os
import secrets
from datetime import datetime
import database as db

# Channel types
CHANNEL_WEB = "web"
CHANNEL_WHATSAPP = "whatsapp"
CHANNEL_INSTAGRAM = "instagram"
CHANNEL_FACEBOOK = "facebook"

CHANNEL_LABELS = {
    CHANNEL_WEB: "🌐 Web",
    CHANNEL_WHATSAPP: "📱 WhatsApp",
    CHANNEL_INSTAGRAM: "📸 Instagram",
    CHANNEL_FACEBOOK: "👥 Facebook",
}


# ── Database helpers ──

def _get_or_create_conversation(admin_id, channel_type, external_id, sender_name="", phone="", email=""):
    """Find or create a conversation for this channel contact."""
    conn = db.get_db()

    row = conn.execute(
        "SELECT * FROM channel_conversations WHERE admin_id = %s AND channel_type = %s AND external_id = %s",
        (admin_id, channel_type, external_id)
    ).fetchone()

    if row:
        # Update last message time
        conn.execute(
            "UPDATE channel_conversations SET last_message_at = %s, unread_count = unread_count + 1 WHERE id = %s",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row["id"])
        )
        conn.commit()
        conv_id = row["id"]
    else:
        _ins_cur = conn.execute(
            """INSERT INTO channel_conversations
            (admin_id, channel_type, external_id, sender_name, phone, email, last_message_at, unread_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1) RETURNING id""",
            (admin_id, channel_type, external_id, sender_name, phone, email,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conv_id = _ins_cur.fetchone()['id']
        conn.commit()

    conn.close()
    return conv_id


def save_message(admin_id, conversation_id, direction, sender_name, text,
                 message_type="text", media_url="", external_message_id=""):
    """Save a message to the unified inbox."""
    conn = db.get_db()
    _ins_cur = conn.execute(
        """INSERT INTO channel_messages
        (admin_id, conversation_id, direction, sender_name, message_text,
         message_type, media_url, external_message_id, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (admin_id, conversation_id, direction, sender_name, text,
         message_type, media_url, external_message_id,
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    msg_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return msg_id


# ── Webhook Processing ──

def process_whatsapp_webhook(payload, admin_id):
    """Process incoming WhatsApp Business API webhook."""
    try:
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        results = []
        for msg in messages:
            sender_id = msg.get("from", "")
            text = ""
            msg_type = "text"

            if msg.get("type") == "text":
                text = msg["text"].get("body", "")
            elif msg.get("type") == "image":
                text = "[Image]"
                msg_type = "image"
            elif msg.get("type") == "document":
                text = "[Document]"
                msg_type = "document"
            elif msg.get("type") == "interactive":
                # Button clicks
                interactive = msg.get("interactive", {})
                if interactive.get("type") == "button_reply":
                    text = interactive["button_reply"].get("title", "")
                elif interactive.get("type") == "list_reply":
                    text = interactive["list_reply"].get("title", "")

            if text:
                # Get contact name
                contacts = value.get("contacts", [])
                sender_name = contacts[0].get("profile", {}).get("name", sender_id) if contacts else sender_id

                conv_id = _get_or_create_conversation(
                    admin_id, CHANNEL_WHATSAPP, sender_id,
                    sender_name=sender_name, phone=sender_id
                )
                msg_id = save_message(admin_id, conv_id, "inbound", sender_name, text,
                                      message_type=msg_type, external_message_id=msg.get("id", ""))

                results.append({
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                    "text": text,
                    "sender": sender_name,
                    "channel": CHANNEL_WHATSAPP,
                })

        return results
    except Exception as e:
        print(f"[channel_engine] WhatsApp webhook error: {e}")
        return []


def process_meta_webhook(payload, admin_id, channel_type=CHANNEL_FACEBOOK):
    """Process incoming Facebook/Instagram webhook."""
    try:
        results = []
        for entry in payload.get("entry", []):
            messaging = entry.get("messaging", [])
            for event in messaging:
                sender_id = event.get("sender", {}).get("id", "")
                message = event.get("message", {})

                if not message:
                    continue

                text = message.get("text", "")
                msg_type = "text"

                if message.get("attachments"):
                    att = message["attachments"][0]
                    msg_type = att.get("type", "file")
                    text = text or f"[{msg_type.title()}]"

                if text:
                    conv_id = _get_or_create_conversation(
                        admin_id, channel_type, sender_id,
                        sender_name=sender_id
                    )
                    msg_id = save_message(admin_id, conv_id, "inbound", sender_id, text,
                                          message_type=msg_type, external_message_id=message.get("mid", ""))

                    results.append({
                        "conversation_id": conv_id,
                        "message_id": msg_id,
                        "text": text,
                        "sender": sender_id,
                        "channel": channel_type,
                    })

        return results
    except Exception as e:
        print(f"[channel_engine] Meta webhook error: {e}")
        return []


# ── Outbound Messaging ──

def send_whatsapp_message(phone_number, text, admin_id):
    """Send a WhatsApp message via WhatsApp Business API."""
    # Check for Twilio/WhatsApp config
    wa_token = os.getenv("WHATSAPP_TOKEN", "")
    wa_phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

    if not wa_token or not wa_phone_id:
        print(f"[channel_engine] WhatsApp not configured. Would send to {phone_number}: {text}")
        return False

    try:
        import httpx
        response = httpx.post(
            f"https://graph.facebook.com/v18.0/{wa_phone_id}/messages",
            headers={"Authorization": f"Bearer {wa_token}", "Content-Type": "application/json"},
            json={
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "text",
                "text": {"body": text}
            },
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        print(f"[channel_engine] WhatsApp send error: {e}")
        return False


def send_reply(conversation_id, text, staff_name="Staff"):
    """Send a reply from the dashboard to the correct channel."""
    conn = db.get_db()
    conv = conn.execute("SELECT * FROM channel_conversations WHERE id = %s", (conversation_id,)).fetchone()
    conn.close()

    if not conv:
        return {"error": "Conversation not found"}

    channel = conv["channel_type"]
    external_id = conv["external_id"]
    admin_id = conv["admin_id"]

    # Save outbound message
    save_message(admin_id, conversation_id, "outbound", staff_name, text)

    # Send via channel
    if channel == CHANNEL_WHATSAPP:
        sent = send_whatsapp_message(external_id, text, admin_id)
    elif channel in (CHANNEL_FACEBOOK, CHANNEL_INSTAGRAM):
        sent = _send_meta_message(external_id, text, admin_id, channel)
    else:
        sent = False  # Web chat handled differently

    return {"ok": True, "sent": sent}


def _send_meta_message(recipient_id, text, admin_id, channel_type):
    """Send message via Facebook/Instagram Messaging API."""
    page_token = os.getenv("META_PAGE_TOKEN", "")
    if not page_token:
        print(f"[channel_engine] Meta API not configured. Would send to {recipient_id}: {text}")
        return False

    try:
        import httpx
        response = httpx.post(
            "https://graph.facebook.com/v18.0/me/messages",
            headers={"Authorization": f"Bearer {page_token}", "Content-Type": "application/json"},
            json={
                "recipient": {"id": recipient_id},
                "message": {"text": text}
            },
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        print(f"[channel_engine] Meta send error: {e}")
        return False


# ── Inbox Queries ──

def get_conversations(admin_id, channel_type=None, unread_only=False,
                      assigned_to=None, search=None, limit=50, offset=0):
    """Get conversations for the unified inbox."""
    conn = db.get_db()
    query = "SELECT * FROM channel_conversations WHERE admin_id = %s"
    params = [admin_id]

    if channel_type:
        query += " AND channel_type = %s"
        params.append(channel_type)
    if unread_only:
        query += " AND unread_count > 0"
    if assigned_to:
        query += " AND assigned_to = %s"
        params.append(assigned_to)
    if search:
        query += " AND (sender_name LIKE %s OR phone LIKE %s OR email LIKE %s)"
        params.extend([f"%{search}%"] * 3)

    query += " ORDER BY last_message_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()

    conversations = []
    for r in rows:
        conv = dict(r)
        conv["channel_label"] = CHANNEL_LABELS.get(conv["channel_type"], conv["channel_type"])
        conversations.append(conv)

    return conversations


def get_conversation_messages(conversation_id, limit=50, offset=0):
    """Get messages for a conversation."""
    conn = db.get_db()
    rows = conn.execute(
        "SELECT * FROM channel_messages WHERE conversation_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
        (conversation_id, limit, offset)
    ).fetchall()

    # Mark as read
    conn.execute(
        "UPDATE channel_conversations SET unread_count = 0 WHERE id = %s",
        (conversation_id,)
    )
    conn.commit()
    conn.close()

    return [dict(r) for r in reversed(rows)]


def assign_conversation(conversation_id, staff_user_id):
    """Assign a conversation to a staff member."""
    conn = db.get_db()
    conn.execute(
        "UPDATE channel_conversations SET assigned_to = %s WHERE id = %s",
        (staff_user_id, conversation_id)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def tag_conversation(conversation_id, tag):
    """Add a tag to a conversation."""
    conn = db.get_db()
    conv = conn.execute("SELECT tags FROM channel_conversations WHERE id = %s", (conversation_id,)).fetchone()
    if conv:
        existing = conv["tags"] or ""
        tags = [t.strip() for t in existing.split(",") if t.strip()]
        if tag not in tags:
            tags.append(tag)
        conn.execute(
            "UPDATE channel_conversations SET tags = %s WHERE id = %s",
            (",".join(tags), conversation_id)
        )
        conn.commit()
    conn.close()
    return {"ok": True}


def resolve_conversation(conversation_id):
    """Mark conversation as resolved."""
    conn = db.get_db()
    conn.execute(
        "UPDATE channel_conversations SET status = 'resolved', resolved_at = %s WHERE id = %s",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), conversation_id)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def get_inbox_stats(admin_id):
    """Get inbox statistics."""
    conn = db.get_db()

    total = conn.execute(
        "SELECT COUNT(*) as c FROM channel_conversations WHERE admin_id = %s", (admin_id,)
    ).fetchone()["c"]

    unread = conn.execute(
        "SELECT COUNT(*) as c FROM channel_conversations WHERE admin_id = %s AND unread_count > 0",
        (admin_id,)
    ).fetchone()["c"]

    by_channel = conn.execute(
        "SELECT channel_type, COUNT(*) as c FROM channel_conversations WHERE admin_id = %s GROUP BY channel_type",
        (admin_id,)
    ).fetchall()

    conn.close()

    return {
        "total_conversations": total,
        "unread": unread,
        "by_channel": {r["channel_type"]: r["c"] for r in by_channel},
    }
