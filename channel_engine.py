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
CHANNEL_SMS = "sms"

CHANNEL_LABELS = {
    CHANNEL_WEB: "🌐 Web",
    CHANNEL_WHATSAPP: "📱 WhatsApp",
    CHANNEL_INSTAGRAM: "📸 Instagram",
    CHANNEL_FACEBOOK: "👥 Facebook",
    CHANNEL_SMS: "💬 SMS",
}


# ── Database helpers ──

def _get_or_create_conversation(admin_id, channel_type, external_id, sender_name="", phone="", email=""):
    """Find or create a conversation for this channel contact."""
    conn = db.get_db()
    try:
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

        return conv_id
    finally:
        conn.close()


def save_message(admin_id, conversation_id, direction, sender_name, text,
                 message_type="text", media_url="", external_message_id=""):
    """Save a message to the unified inbox."""
    conn = db.get_db()
    try:
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
        return msg_id
    finally:
        conn.close()


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
        print(f"[channel_engine] WhatsApp not configured. Would send to ***{phone_number[-4:] if phone_number else ''}: {text}")
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


def send_reply(conversation_id, text, staff_name="Staff", admin_id=None):
    """Send a reply from the dashboard to the correct channel."""
    # Bug fix #5: Preserve message content - validate inputs
    if not text:
        return {"error": "Empty message"}

    conn = db.get_db()
    try:
        if admin_id:
            conv = conn.execute("SELECT * FROM channel_conversations WHERE id = %s AND admin_id = %s", (conversation_id, admin_id)).fetchone()
        else:
            conv = conn.execute("SELECT * FROM channel_conversations WHERE id = %s", (conversation_id,)).fetchone()
    except Exception as e:
        print(f"[channel_engine] DB error in send_reply: {e}")
        return {"error": "Database error"}
    finally:
        conn.close()

    if not conv:
        return {"error": "Conversation not found"}

    # Bug fix #1: Null checks on database query results
    channel = conv["channel_type"]
    external_id = conv["external_id"]
    admin_id = conv["admin_id"]

    if not channel or not external_id:
        return {"error": "Invalid conversation data: missing channel or external_id"}

    # Save outbound message
    save_failed = False
    try:
        save_message(admin_id, conversation_id, "outbound", staff_name, text)
    except Exception as e:
        # Bug fix #2: Log error instead of silently failing
        print(f"[channel_engine] Failed to save outbound message for conv {conversation_id}: {e}")
        save_failed = True

    # Bug fix #3: Handle channel send errors without crashing
    sent = False
    try:
        if channel == CHANNEL_WHATSAPP:
            sent = send_whatsapp_message(external_id, text, admin_id)
        elif channel in (CHANNEL_FACEBOOK, CHANNEL_INSTAGRAM):
            sent = _send_meta_message(external_id, text, admin_id, channel)
        elif channel == CHANNEL_SMS:
            sent = _send_sms_reply(external_id, text, admin_id)
        else:
            sent = False  # Web chat handled differently
    except Exception as e:
        print(f"[channel_engine] Channel send error ({channel}): {e}")
        sent = False

    return {"ok": True, "sent": sent, "save_failed": save_failed}


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


# ── SMS Channel Support ──

def process_inbound_sms(admin_id, from_number, message):
    """Process an incoming SMS into the unified inbox."""
    # Bug fix #1: Null checks on input parameters
    if not admin_id or not from_number:
        print(f"[channel_engine] Inbound SMS missing required params: admin_id={admin_id}, from=***{from_number[-4:] if from_number else ''}")
        return None
    # Bug fix #5: Preserve message content - default to empty string instead of None
    if message is None:
        message = ""

    try:
        conv_id = _get_or_create_conversation(
            admin_id, CHANNEL_SMS, from_number,
            sender_name=from_number, phone=from_number
        )
        msg_id = save_message(admin_id, conv_id, "inbound", from_number, message,
                              message_type="text")

        # Also save to sms inbox table for dual tracking
        try:
            db.save_sms_to_inbox(admin_id, from_number, message, "inbound", session_id=from_number)
        except Exception as e:
            # Bug fix #2: Log the error instead of silently swallowing
            print(f"[channel_engine] Dual-track SMS inbox save error: {e}")

        return {
            "conversation_id": conv_id,
            "message_id": msg_id,
            "text": message,
            "sender": from_number,
            "channel": CHANNEL_SMS,
        }
    except Exception as e:
        print(f"[channel_engine] Inbound SMS error: {e}")
        return None


def send_sms_reply(admin_id, conversation_id, message):
    """Send an SMS reply from the dashboard via Twilio and log it."""
    # Bug fix #4: Validate message length before sending SMS (Twilio limit is 1600 chars)
    if message and len(message) > 1600:
        print(f"[channel_engine] SMS message too long ({len(message)} chars), truncating to 1600")
        message = message[:1597] + "..."

    # Bug fix #5: Preserve message content on errors
    original_message = message

    conn = db.get_db()
    try:
        conv = conn.execute("SELECT * FROM channel_conversations WHERE id=%s", (conversation_id,)).fetchone()
    except Exception as e:
        print(f"[channel_engine] DB error fetching conversation {conversation_id}: {e}")
        return {"error": "Database error"}
    finally:
        conn.close()

    if not conv:
        return {"error": "Conversation not found"}

    # Bug fix #1: Null checks on database query results before accessing properties
    phone = (conv.get("phone") if hasattr(conv, 'get') else conv["phone"]) or (conv.get("external_id") if hasattr(conv, 'get') else conv["external_id"])
    if not phone:
        return {"error": "No phone number found for conversation"}

    staff_name = "Staff"

    # Save outbound message to inbox
    save_failed = False
    try:
        save_message(admin_id, conversation_id, "outbound", staff_name, original_message)
    except Exception as e:
        # Bug fix #2: Log error instead of letting it crash
        print(f"[channel_engine] Failed to save outbound SMS message: {e}")
        save_failed = True

    # Bug fix #3: Handle Twilio API errors properly
    try:
        sent = _send_sms_reply(phone, original_message, admin_id)
    except Exception as e:
        print(f"[channel_engine] Twilio SMS send exception: {e}")
        sent = False

    return {"ok": True, "sent": sent, "save_failed": save_failed}


def _send_sms_reply(phone, text, admin_id):
    """Internal: send SMS via Twilio sms_engine."""
    # Bug fix #1: Null checks before sending
    if not phone or not text:
        print(f"[channel_engine] SMS send skipped: missing phone=***{phone[-4:] if phone else ''} or text is empty")
        return False
    # Bug fix #4: Validate message length for SMS (Twilio limit)
    if len(text) > 1600:
        print(f"[channel_engine] SMS text too long ({len(text)} chars), truncating")
        text = text[:1597] + "..."
    try:
        import sms_engine
        result = sms_engine.send_sms(phone, text, admin_id)
        # Bug fix #1: Handle None result from sms_engine
        if result is None:
            print(f"[channel_engine] sms_engine.send_sms returned None for phone=***{phone[-4:] if phone else ''}")
            return False
        return result.get("success", False)
    except Exception as e:
        # Bug fix #3: Properly handle Twilio API errors
        print(f"[channel_engine] SMS send error (phone=***{phone[-4:] if phone else ''}, admin={admin_id}): {e}")
        return False


# ── Inbox Queries ──

def get_conversations(admin_id, channel_type=None, unread_only=False,
                      assigned_to=None, search=None, limit=50, offset=0):
    """Get conversations for the unified inbox."""
    conn = db.get_db()
    try:
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
            # Escape LIKE wildcard characters in user input
            escaped_search = search.replace("%", "\\%").replace("_", "\\_")
            query += " AND (sender_name LIKE %s OR phone LIKE %s OR email LIKE %s)"
            params.extend([f"%{escaped_search}%"] * 3)

        query += " ORDER BY last_message_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    conversations = []
    for r in rows:
        conv = dict(r)
        conv["channel_label"] = CHANNEL_LABELS.get(conv["channel_type"], conv["channel_type"])
        conversations.append(conv)

    return conversations


def get_conversation_messages(conversation_id, limit=50, offset=0, admin_id=None):
    """Get messages for a conversation."""
    conn = db.get_db()
    try:
        if admin_id:
            rows = conn.execute(
                "SELECT * FROM channel_messages WHERE conversation_id = %s AND admin_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (conversation_id, admin_id, limit, offset)
            ).fetchall()
            # Mark as read
            conn.execute(
                "UPDATE channel_conversations SET unread_count = 0 WHERE id = %s AND admin_id = %s",
                (conversation_id, admin_id)
            )
        else:
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
    finally:
        conn.close()

    return [dict(r) for r in reversed(rows)]


def assign_conversation(conversation_id, staff_user_id, admin_id=None):
    """Assign a conversation to a staff member."""
    conn = db.get_db()
    try:
        if admin_id:
            conn.execute(
                "UPDATE channel_conversations SET assigned_to = %s WHERE id = %s AND admin_id = %s",
                (staff_user_id, conversation_id, admin_id)
            )
        else:
            conn.execute(
                "UPDATE channel_conversations SET assigned_to = %s WHERE id = %s",
                (staff_user_id, conversation_id)
            )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


def tag_conversation(conversation_id, tag, admin_id=None):
    """Add a tag to a conversation."""
    conn = db.get_db()
    try:
        if admin_id:
            conv = conn.execute("SELECT tags FROM channel_conversations WHERE id = %s AND admin_id = %s", (conversation_id, admin_id)).fetchone()
        else:
            conv = conn.execute("SELECT tags FROM channel_conversations WHERE id = %s", (conversation_id,)).fetchone()
        if conv:
            existing = conv["tags"] or ""
            tags = [t.strip() for t in existing.split(",") if t.strip()]
            if tag not in tags:
                tags.append(tag)
            if admin_id:
                conn.execute(
                    "UPDATE channel_conversations SET tags = %s WHERE id = %s AND admin_id = %s",
                    (",".join(tags), conversation_id, admin_id)
                )
            else:
                conn.execute(
                    "UPDATE channel_conversations SET tags = %s WHERE id = %s",
                    (",".join(tags), conversation_id)
                )
            conn.commit()
    except Exception as e:
        # Bug fix #2: Log error instead of silently ignoring
        print(f"[channel_engine] Tag conversation error: {e}")
        return {"ok": False, "error": "Failed to tag conversation"}
    finally:
        conn.close()
    return {"ok": True}


def resolve_conversation(conversation_id, admin_id=None):
    """Mark conversation as resolved."""
    conn = db.get_db()
    try:
        if admin_id:
            conn.execute(
                "UPDATE channel_conversations SET status = 'resolved', resolved_at = %s WHERE id = %s AND admin_id = %s",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), conversation_id, admin_id)
            )
        else:
            conn.execute(
                "UPDATE channel_conversations SET status = 'resolved', resolved_at = %s WHERE id = %s",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), conversation_id)
            )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


def get_inbox_stats(admin_id):
    """Get inbox statistics."""
    conn = db.get_db()
    try:
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
    finally:
        conn.close()

    return {
        "total_conversations": total,
        "unread": unread,
        "by_channel": {r["channel_type"]: r["c"] for r in by_channel},
    }
