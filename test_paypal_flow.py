"""
Test PayPal checkout flow WITHOUT making real PayPal API calls.
All PayPal responses are mocked — no money is charged.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch, MagicMock
import json

# Mock heavy imports so app.py loads fast without GPU/models
mock_sklearn_classifier = MagicMock()
mock_sklearn_classifier.classify = MagicMock(return_value=("greeting", 0.9))
sys.modules["sklearn_classifier"] = mock_sklearn_classifier

for mod in ["torch", "transformers", "datasets", "peft", "accelerate",
            "sentencepiece", "google.generativeai",
            "sklearn", "sklearn.feature_extraction",
            "sklearn.feature_extraction.text", "sklearn.linear_model",
            "sklearn.pipeline", "sklearn.base"]:
    sys.modules.setdefault(mod, MagicMock())

import database as db

FAKE_ORDER_ID = "MOCK-ORDER-123456"
FAKE_TXN_ID = "MOCK-TXN-789"


def mock_paypal_post(url, **kwargs):
    """Fake PayPal API responses."""
    resp = MagicMock()
    if "/oauth2/token" in url:
        resp.status_code = 200
        resp.json.return_value = {"access_token": "MOCK-ACCESS-TOKEN"}
    elif "/v2/checkout/orders" in url and "/capture" not in url:
        # Create order
        resp.status_code = 201
        resp.json.return_value = {"id": FAKE_ORDER_ID, "status": "CREATED"}
    elif "/capture" in url:
        # Capture order
        resp.status_code = 201
        resp.json.return_value = {
            "status": "COMPLETED",
            "purchase_units": [{
                "payments": {
                    "captures": [{"id": FAKE_TXN_ID, "amount": {"value": "149.00", "currency_code": "USD"}}]
                }
            }]
        }
    else:
        resp.status_code = 404
        resp.json.return_value = {"error": "unknown"}
    return resp


def run_test():
    print("=" * 60)
    print("  PAYPAL CHECKOUT FLOW TEST (all mocked, no real charges)")
    print("=" * 60)

    # Step 0: Find a head_admin user and give them a valid token
    import secrets
    from datetime import datetime, timedelta
    conn = db.get_db()
    test_user = conn.execute(
        "SELECT * FROM users WHERE role='head_admin' LIMIT 1"
    ).fetchone()
    if not test_user:
        print("\n❌ FAIL: No head_admin user found in database")
        conn.close()
        return

    user_id = test_user["id"]
    old_plan = test_user["plan"]
    old_token = test_user["token"]
    old_token_expires = test_user["token_expires_at"]

    # Generate a valid test token
    token = secrets.token_hex(32)
    expires = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE users SET token=%s, token_expires_at=%s, plan='free_trial' WHERE id=%s",
                 (token, expires, user_id))
    conn.commit()
    conn.close()

    print(f"\nTest user: {test_user['name']} ({test_user['email']})")
    print(f"Original plan: {old_plan}")
    print(f"User ID: {user_id}")
    print("→ Reset to free_trial with temp token for test\n")

    # Import app for test client
    with patch("requests.post", side_effect=mock_paypal_post):
        # Need to patch inside the endpoint functions too
        from app import app
        app.config["TESTING"] = True
        client = app.test_client()

        # ── TEST 1: Create order ──
        print("TEST 1: POST /api/paypal/create-order (plan=basic)")
        with patch("requests.post", side_effect=mock_paypal_post):
            resp = client.post("/api/paypal/create-order",
                json={"plan": "basic"},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        print(f"  Response: {json.dumps(data, indent=2)}")

        if resp.status_code in (200, 201) and data.get("id"):
            print("  ✅ PASS — Order created")
            order_id = data["id"]
        else:
            print("  ❌ FAIL — Could not create order")
            restore_user(user_id, old_plan, old_token, old_token_expires)
            return

        # ── TEST 2: Capture order (simulates user completing payment) ──
        print(f"\nTEST 2: POST /api/paypal/capture-order (order_id={order_id})")
        with patch("requests.post", side_effect=mock_paypal_post):
            resp = client.post("/api/paypal/capture-order",
                json={"order_id": order_id},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        print(f"  Response: {json.dumps(data, indent=2)}")

        if resp.status_code == 200 and data.get("ok"):
            print("  ✅ PASS — Payment captured and plan activated")
        else:
            print("  ❌ FAIL — Payment capture failed")
            restore_user(user_id, old_plan, old_token, old_token_expires)
            return

        # ── TEST 3: Verify plan changed in DB ──
        print(f"\nTEST 3: Verify plan updated in database")
        conn = db.get_db()
        updated_user = conn.execute("SELECT plan, plan_started_at, plan_expires_at FROM users WHERE id=%s", (user_id,)).fetchone()
        conn.close()

        print(f"  Plan: {updated_user['plan']}")
        print(f"  Started: {updated_user['plan_started_at']}")
        print(f"  Expires: {updated_user['plan_expires_at']}")

        if updated_user["plan"] == "basic":
            print("  ✅ PASS — Plan is now 'basic'")
        else:
            print(f"  ❌ FAIL — Expected 'basic', got '{updated_user['plan']}'")

        # ── TEST 4: Replay attack — try capturing same order again ──
        print(f"\nTEST 4: Replay attack — capture same order_id again")
        with patch("requests.post", side_effect=mock_paypal_post):
            resp = client.post("/api/paypal/capture-order",
                json={"order_id": order_id},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        print(f"  Response: {json.dumps(data, indent=2)}")

        if resp.status_code == 400 and "Invalid" in data.get("error", ""):
            print("  ✅ PASS — Replay blocked (session already used)")
        else:
            print("  ⚠️  WARNING — Replay was not blocked")

        # ── TEST 5: Invalid plan ──
        print(f"\nTEST 5: Create order with invalid plan")
        with patch("requests.post", side_effect=mock_paypal_post):
            resp = client.post("/api/paypal/create-order",
                json={"plan": "diamond"},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 400:
            print("  ✅ PASS — Invalid plan rejected")
        else:
            print("  ❌ FAIL — Invalid plan was not rejected")

        # ── TEST 6: Unauthorized user ──
        print(f"\nTEST 6: Create order without auth token")
        with patch("requests.post", side_effect=mock_paypal_post):
            resp = client.post("/api/paypal/create-order",
                json={"plan": "basic"},
                headers={"Content-Type": "application/json"})

        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 401:
            print("  ✅ PASS — Unauthorized rejected")
        else:
            print("  ❌ FAIL — Unauthorized was not rejected")

        # ── TEST 7: Fake order_id ──
        print(f"\nTEST 7: Capture with fake order_id")
        with patch("requests.post", side_effect=mock_paypal_post):
            resp = client.post("/api/paypal/capture-order",
                json={"order_id": "FAKE-DOES-NOT-EXIST"},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 400:
            print("  ✅ PASS — Fake order rejected")
        else:
            print("  ❌ FAIL — Fake order was not rejected")

    # ── Restore original state ──
    restore_user(user_id, old_plan, old_token, old_token_expires)

    print("\n" + "=" * 60)
    print("  ALL TESTS COMPLETE")
    print("=" * 60)


def restore_user(user_id, plan, token, token_expires):
    conn = db.get_db()
    conn.execute("UPDATE users SET plan=%s, token=%s, token_expires_at=%s WHERE id=%s",
                 (plan, token or '', token_expires or '', user_id))
    conn.commit()
    conn.close()
    print(f"\n→ Restored user back to plan='{plan}'")


if __name__ == "__main__":
    run_test()
