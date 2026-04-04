"""
A/B Testing Engine for ChatGenius Chatbot Messages.
Allows clinic admins to test two versions of chatbot messages
and automatically declare a winner based on conversion rates.
"""
import random
import logging
from datetime import datetime

logger = logging.getLogger("ab_testing")

# Test types that can be A/B tested
TEST_TYPES = {
    'opening_message': 'The first message shown when a patient opens the chatbot',
    'booking_prompt': 'The message that prompts the user to book an appointment',
    'followup_message': 'The follow-up message after booking is complete',
}

MIN_CONVERSATIONS_FOR_WINNER = 100  # Each variant needs this many before declaring winner


def create_test(admin_id, test_name, test_type, variant_a, variant_b):
    """
    Create a new A/B test.
    Returns: {"id": 5, "test_name": "Opening Message Test"} or {"error": "..."}

    Rules:
    - Only one active test per test_type per admin at a time
    """
    import database as db

    if test_type not in TEST_TYPES:
        return {"error": f"Invalid test type. Must be one of: {', '.join(TEST_TYPES.keys())}"}

    conn = db.get_db()

    # Check for existing active test of this type
    existing = conn.execute(
        "SELECT id FROM ab_tests WHERE admin_id=? AND test_type=? AND status='running'",
        (admin_id, test_type)
    ).fetchone()

    if existing:
        conn.close()
        return {"error": f"There is already an active A/B test for {test_type}. End it first before creating a new one."}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO ab_tests
           (admin_id, test_name, test_type, variant_a, variant_b,
            variant_a_conversations, variant_a_bookings,
            variant_b_conversations, variant_b_bookings,
            status, created_at)
           VALUES (?,?,?,?,?,0,0,0,0,'running',?)""",
        (admin_id, test_name, test_type, variant_a, variant_b, now)
    )
    conn.commit()
    test_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    logger.info(f"A/B test #{test_id} created: {test_name}")
    return {"id": test_id, "test_name": test_name}


def get_variant_for_session(admin_id, test_type, session_id):
    """
    Assign a variant to a session. Once assigned, always returns the same variant.
    Returns: {"variant": "A", "message": "Hi! I'm Sara..."} or None if no active test.
    """
    import database as db
    conn = db.get_db()

    # Find active test
    test = conn.execute(
        "SELECT * FROM ab_tests WHERE admin_id=? AND test_type=? AND status='running' LIMIT 1",
        (admin_id, test_type)
    ).fetchone()

    if not test:
        conn.close()
        return None

    test = dict(test)

    # Check if session already has an assignment
    existing = conn.execute(
        "SELECT variant FROM ab_assignments WHERE test_id=? AND session_id=?",
        (test["id"], session_id)
    ).fetchone()

    if existing:
        variant = existing["variant"]
    else:
        # Randomly assign 50/50
        variant = random.choice(["A", "B"])
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO ab_assignments (test_id, session_id, variant, created_at) VALUES (?,?,?,?)",
            (test["id"], session_id, variant, now)
        )
        # Increment conversation count
        if variant == "A":
            conn.execute("UPDATE ab_tests SET variant_a_conversations = variant_a_conversations + 1 WHERE id=?", (test["id"],))
        else:
            conn.execute("UPDATE ab_tests SET variant_b_conversations = variant_b_conversations + 1 WHERE id=?", (test["id"],))
        conn.commit()

    conn.close()

    message = test["variant_a"] if variant == "A" else test["variant_b"]
    return {"variant": variant, "message": message, "test_id": test["id"]}


def record_conversion(admin_id, test_type, session_id):
    """
    Record that a session converted (made a booking).
    Call this when a booking is completed.
    """
    import database as db
    conn = db.get_db()

    test = conn.execute(
        "SELECT id FROM ab_tests WHERE admin_id=? AND test_type=? AND status='running' LIMIT 1",
        (admin_id, test_type)
    ).fetchone()

    if not test:
        conn.close()
        return

    test_id = test["id"]

    assignment = conn.execute(
        "SELECT id, variant, converted FROM ab_assignments WHERE test_id=? AND session_id=?",
        (test_id, session_id)
    ).fetchone()

    if not assignment or assignment["converted"]:
        conn.close()
        return  # No assignment or already converted

    variant = assignment["variant"]
    conn.execute("UPDATE ab_assignments SET converted=1 WHERE id=?", (assignment["id"],))

    if variant == "A":
        conn.execute("UPDATE ab_tests SET variant_a_bookings = variant_a_bookings + 1 WHERE id=?", (test_id,))
    else:
        conn.execute("UPDATE ab_tests SET variant_b_bookings = variant_b_bookings + 1 WHERE id=?", (test_id,))

    conn.commit()
    conn.close()

    # Check if we should auto-declare a winner
    _check_auto_winner(test_id)


def _check_auto_winner(test_id):
    """Check if both variants have enough data to declare a winner."""
    import database as db
    conn = db.get_db()
    test = conn.execute("SELECT * FROM ab_tests WHERE id=?", (test_id,)).fetchone()

    if not test:
        conn.close()
        return

    test = dict(test)
    a_conv = test["variant_a_conversations"]
    b_conv = test["variant_b_conversations"]

    if a_conv >= MIN_CONVERSATIONS_FOR_WINNER and b_conv >= MIN_CONVERSATIONS_FOR_WINNER:
        a_rate = test["variant_a_bookings"] / a_conv if a_conv > 0 else 0
        b_rate = test["variant_b_bookings"] / b_conv if b_conv > 0 else 0

        # Only auto-declare if there's a meaningful difference (>5% points)
        if abs(a_rate - b_rate) > 0.05:
            winner = "A" if a_rate > b_rate else "B"
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE ab_tests SET status='completed', winner=?, completed_at=? WHERE id=?",
                (winner, now, test_id)
            )
            conn.commit()
            logger.info(f"A/B test #{test_id} auto-completed. Winner: Variant {winner}")

    conn.close()


def end_test(test_id, winner=None):
    """
    Manually end a test. Admin can specify a winner or let the system choose based on data.
    Returns: {"winner": "B", "results": {...}}
    """
    import database as db
    conn = db.get_db()
    test = conn.execute("SELECT * FROM ab_tests WHERE id=?", (test_id,)).fetchone()

    if not test:
        conn.close()
        return {"error": "Test not found"}

    test = dict(test)

    if test["status"] != "running":
        conn.close()
        return {"error": "Test is not running"}

    a_conv = test["variant_a_conversations"]
    b_conv = test["variant_b_conversations"]
    a_rate = test["variant_a_bookings"] / a_conv if a_conv > 0 else 0
    b_rate = test["variant_b_bookings"] / b_conv if b_conv > 0 else 0

    if not winner:
        winner = "A" if a_rate >= b_rate else "B"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE ab_tests SET status='completed', winner=?, completed_at=? WHERE id=?",
        (winner, now, test_id)
    )
    conn.commit()
    conn.close()

    winning_message = test["variant_a"] if winner == "A" else test["variant_b"]

    return {
        "winner": winner,
        "winning_message": winning_message,
        "results": {
            "variant_a": {
                "message": test["variant_a"],
                "conversations": a_conv,
                "bookings": test["variant_a_bookings"],
                "conversion_rate": round(a_rate * 100, 1)
            },
            "variant_b": {
                "message": test["variant_b"],
                "conversations": b_conv,
                "bookings": test["variant_b_bookings"],
                "conversion_rate": round(b_rate * 100, 1)
            }
        }
    }


def apply_winner(test_id, admin_id):
    """Apply the winning variant as the permanent message."""
    import database as db
    conn = db.get_db()
    test = conn.execute("SELECT * FROM ab_tests WHERE id=? AND admin_id=?", (test_id, admin_id)).fetchone()

    if not test:
        conn.close()
        return {"error": "Test not found"}

    test = dict(test)
    if not test.get("winner"):
        conn.close()
        return {"error": "No winner declared yet"}

    winning_message = test["variant_a"] if test["winner"] == "A" else test["variant_b"]
    test_type = test["test_type"]

    # Save to company_info or a config table
    conn.execute(
        "UPDATE ab_tests SET status='applied' WHERE id=?", (test_id,)
    )

    # Store the winning message in company_info based on test_type
    if test_type == "opening_message":
        conn.execute(
            "UPDATE company_info SET chatbot_welcome_msg = ? WHERE user_id = ?",
            (winning_message, admin_id)
        )

    conn.commit()
    conn.close()

    return {"applied": True, "message": winning_message, "test_type": test_type}


def get_tests(admin_id):
    """Get all A/B tests for an admin (running + archived)."""
    import database as db
    conn = db.get_db()
    tests = conn.execute(
        "SELECT * FROM ab_tests WHERE admin_id=? ORDER BY created_at DESC",
        (admin_id,)
    ).fetchall()
    conn.close()

    result = []
    for t in tests:
        t = dict(t)
        a_conv = t["variant_a_conversations"]
        b_conv = t["variant_b_conversations"]
        result.append({
            "id": t["id"],
            "test_name": t["test_name"],
            "test_type": t["test_type"],
            "variant_a": t["variant_a"],
            "variant_b": t["variant_b"],
            "variant_a_stats": {
                "conversations": a_conv,
                "bookings": t["variant_a_bookings"],
                "conversion_rate": round((t["variant_a_bookings"] / a_conv * 100) if a_conv > 0 else 0, 1)
            },
            "variant_b_stats": {
                "conversations": b_conv,
                "bookings": t["variant_b_bookings"],
                "conversion_rate": round((t["variant_b_bookings"] / b_conv * 100) if b_conv > 0 else 0, 1)
            },
            "status": t["status"],
            "winner": t.get("winner"),
            "created_at": t["created_at"],
            "completed_at": t.get("completed_at")
        })

    return result


def get_active_message(admin_id, test_type, session_id):
    """
    Get the message to show. If there's an active A/B test, return the assigned variant.
    If no test, return None (caller should use default).
    """
    result = get_variant_for_session(admin_id, test_type, session_id)
    if result:
        return result["message"]
    return None
