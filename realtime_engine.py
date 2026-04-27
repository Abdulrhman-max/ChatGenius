"""
Real-Time Dashboard Engine for ChatGenius.
Uses Server-Sent Events (SSE) for live updates.
"""
import json
import time
import logging
import threading
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger("realtime")

# In-memory event queues per admin (cleared on disconnect)
_subscribers = defaultdict(list)  # admin_id -> list of queue objects
_lock = threading.Lock()


class EventQueue:
    """Thread-safe event queue for SSE subscribers."""

    def __init__(self, admin_id):
        self.admin_id = admin_id
        self.events = []
        self._condition = threading.Condition()
        self.active = True

    def push(self, event_type, data):
        """Push an event to this subscriber."""
        with self._condition:
            self.events.append({
                "type": event_type,
                "data": data,
                "timestamp": datetime.now().isoformat()
            })
            self._condition.notify()

    def poll(self, timeout=30):
        """Wait for events, return them, and clear the buffer."""
        with self._condition:
            if not self.events:
                self._condition.wait(timeout=timeout)
            events = self.events[:]
            self.events.clear()
            return events

    def close(self):
        """Mark as inactive and wake up any waiting poll."""
        self.active = False
        with self._condition:
            self._condition.notify()


def subscribe(admin_id):
    """Create a new SSE subscriber for an admin. Returns EventQueue."""
    queue = EventQueue(admin_id)
    with _lock:
        _subscribers[admin_id].append(queue)
    logger.info(f"New SSE subscriber for admin #{admin_id} (total: {len(_subscribers[admin_id])})")
    return queue


def unsubscribe(admin_id, queue):
    """Remove a subscriber."""
    with _lock:
        if admin_id in _subscribers:
            try:
                _subscribers[admin_id].remove(queue)
            except ValueError:
                pass
            if not _subscribers[admin_id]:
                del _subscribers[admin_id]
    queue.close()


def broadcast(admin_id, event_type, data):
    """Send an event to all subscribers of an admin."""
    with _lock:
        queues = _subscribers.get(admin_id, [])[:]

    for queue in queues:
        if queue.active:
            queue.push(event_type, data)

    if queues:
        logger.debug(f"Broadcast '{event_type}' to {len(queues)} subscribers of admin #{admin_id}")


# ── Event Types ──

def emit_new_booking(admin_id, booking_data):
    """Emit when a new booking is created."""
    broadcast(admin_id, "new_booking", {
        "id": booking_data.get("id"),
        "customer_name": booking_data.get("customer_name"),
        "date": booking_data.get("date"),
        "time": booking_data.get("time"),
        "doctor_name": booking_data.get("doctor_name"),
        "status": booking_data.get("status", "confirmed"),
        "created_at": datetime.now().isoformat()
    })


def emit_booking_cancelled(admin_id, booking_id, customer_name):
    """Emit when a booking is cancelled."""
    broadcast(admin_id, "booking_cancelled", {
        "id": booking_id,
        "customer_name": customer_name,
        "cancelled_at": datetime.now().isoformat()
    })


def emit_patient_checkin(admin_id, booking_id, customer_name):
    """Emit when a patient checks in."""
    broadcast(admin_id, "patient_checkin", {
        "booking_id": booking_id,
        "customer_name": customer_name,
        "checked_in_at": datetime.now().isoformat()
    })


def emit_noshow_alert(admin_id, booking_data):
    """Emit when a no-show is detected."""
    broadcast(admin_id, "noshow_alert", {
        "booking_id": booking_data.get("id"),
        "customer_name": booking_data.get("customer_name"),
        "time": booking_data.get("time"),
        "doctor_name": booking_data.get("doctor_name"),
        "alert_time": datetime.now().isoformat()
    })


def emit_chat_activity(admin_id, session_id, patient_name, message_preview):
    """Emit when there's chat activity."""
    broadcast(admin_id, "chat_activity", {
        "session_id": session_id,
        "patient_name": patient_name,
        "message_preview": message_preview[:100],
        "timestamp": datetime.now().isoformat()
    })


def emit_form_submitted(admin_id, patient_name, booking_date, booking_time):
    """Emit when a pre-visit form is submitted."""
    broadcast(admin_id, "form_submitted", {
        "patient_name": patient_name,
        "booking_date": booking_date,
        "booking_time": booking_time,
        "submitted_at": datetime.now().isoformat()
    })


def emit_emergency_alert(admin_id, alert_data):
    """Emit emergency alert."""
    broadcast(admin_id, "emergency_alert", alert_data)


def emit_handoff_request(admin_id, handoff_data):
    """Emit when a chat needs human handoff."""
    broadcast(admin_id, "handoff_request", handoff_data)


def emit_payment_received(admin_id, booking_id, amount):
    """Emit when a payment is received."""
    broadcast(admin_id, "payment_received", {
        "booking_id": booking_id,
        "amount": amount,
        "received_at": datetime.now().isoformat()
    })


# ── SSE Stream Generator ──

def sse_stream(admin_id):
    """
    Generator that yields SSE-formatted events.
    Used by Flask route to stream events to the client.
    """
    queue = subscribe(admin_id)

    try:
        # Send initial snapshot
        snapshot = get_dashboard_snapshot(admin_id)
        yield f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n"

        # Send heartbeat immediately
        yield f"event: heartbeat\ndata: {json.dumps({'time': datetime.now().isoformat()})}\n\n"

        while queue.active:
            events = queue.poll(timeout=25)

            if not events:
                # Send heartbeat to keep connection alive
                yield f"event: heartbeat\ndata: {json.dumps({'time': datetime.now().isoformat()})}\n\n"
                continue

            for event in events:
                yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"

    except GeneratorExit:
        pass
    finally:
        unsubscribe(admin_id, queue)


def get_dashboard_snapshot(admin_id):
    """Get current state snapshot for initial load or reconnection."""
    import database as db
    conn = db.get_db()

    today = datetime.now().strftime("%Y-%m-%d")
    hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

    # Today's appointments
    todays_appointments = conn.execute(
        """SELECT id, customer_name, date, time, doctor_name, status, checked_in, checked_in_at
           FROM bookings WHERE admin_id=%s AND date=%s
           ORDER BY time""",
        (admin_id, today)
    ).fetchall()

    # Recent bookings (last 60 minutes)
    recent_bookings = conn.execute(
        """SELECT id, customer_name, date, time, doctor_name, status, created_at
           FROM bookings WHERE admin_id=%s AND created_at >= %s
           ORDER BY created_at DESC""",
        (admin_id, hour_ago)
    ).fetchall()

    # Active chat sessions (last 10 minutes)
    ten_min_ago = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    active_chats = conn.execute(
        """SELECT session_id, MAX(created_at) as last_msg, COUNT(*) as msg_count
           FROM chat_logs WHERE admin_id=%s AND created_at >= %s
           GROUP BY session_id
           ORDER BY last_msg DESC""",
        (admin_id, ten_min_ago)
    ).fetchall()

    # Pending handoffs
    pending_handoffs = conn.execute(
        "SELECT * FROM live_chat_handoffs WHERE admin_id=%s AND status='queued' ORDER BY created_at",
        (admin_id,)
    ).fetchall()

    # No-show candidates (10+ min past, not checked in)
    noshow_candidates = []
    now = datetime.now()
    for appt in todays_appointments:
        appt = dict(appt)
        if appt["status"] == "confirmed" and not appt.get("checked_in"):
            try:
                time_str = appt["time"].split(" - ")[0].strip()
                appt_time = datetime.strptime(f"{today} {time_str}", "%Y-%m-%d %I:%M %p")
                if now > appt_time + timedelta(minutes=10):
                    noshow_candidates.append(appt)
            except (ValueError, IndexError):
                pass

    conn.close()

    return {
        "todays_appointments": [dict(a) for a in todays_appointments],
        "recent_bookings": [dict(b) for b in recent_bookings],
        "active_chats": [dict(c) for c in active_chats],
        "pending_handoffs": [dict(h) for h in pending_handoffs],
        "noshow_alerts": noshow_candidates,
        "timestamp": datetime.now().isoformat()
    }
