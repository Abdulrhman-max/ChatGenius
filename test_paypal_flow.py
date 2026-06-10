"""
Test PayPal subscription flow — verifies all plan prices are correct
and the subscription endpoints work properly.
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

FAKE_PRODUCT_ID = "PROD-MOCK-001"
_sub_counter = 0

def _next_sub_id():
    global _sub_counter
    _sub_counter += 1
    return f"I-MOCK-SUB-{_sub_counter:06d}"

# Expected prices for every paid plan
EXPECTED_PRICES = {
    "basic": "23.00",
    "growth": "79.00",
    "pro": "299.00",
    "enterprise": "699.00",
}

# Collect PayPal API calls for inspection
_captured_calls = []


def mock_paypal_post(url, **kwargs):
    """Fake PayPal API responses. Records all calls for price verification."""
    _captured_calls.append({"url": url, "kwargs": kwargs})
    resp = MagicMock()

    if "/oauth2/token" in url:
        resp.status_code = 200
        resp.json.return_value = {"access_token": "MOCK-ACCESS-TOKEN"}

    elif "/v1/catalogs/products" in url:
        resp.status_code = 201
        resp.json.return_value = {"id": FAKE_PRODUCT_ID}

    elif "/v1/billing/plans" in url:
        # Extract plan price from request body for verification
        body = kwargs.get("json", {})
        cycles = body.get("billing_cycles", [])
        price = cycles[0]["pricing_scheme"]["fixed_price"]["value"] if cycles else "0"
        plan_name = body.get("name", "")
        plan_id = f"P-MOCK-{plan_name.upper().replace(' ', '-')}"
        resp.status_code = 201
        resp.json.return_value = {"id": plan_id}

    elif "/v1/billing/subscriptions" in url and "/activate" not in url:
        # Create subscription
        sub_id = _next_sub_id()
        resp.status_code = 201
        resp.json.return_value = {
            "id": sub_id,
            "status": "APPROVAL_PENDING",
            "links": [
                {"rel": "approve", "href": "https://www.sandbox.paypal.com/webapps/billing/subscriptions?ba_token=MOCK"},
                {"rel": "self", "href": f"https://api-m.sandbox.paypal.com/v1/billing/subscriptions/{sub_id}"}
            ]
        }

    elif "/v1/billing/subscriptions/" in url:
        # GET subscription details (for activate verification)
        resp.status_code = 200
        resp.json.return_value = {
            "id": "I-MOCK-SUB-DETAIL",
            "status": "ACTIVE",
            "plan_id": "P-MOCK-PLAN",
            "billing_info": {
                "last_payment": {"amount": {"value": "23.00", "currency_code": "USD"}}
            }
        }

    else:
        resp.status_code = 404
        resp.json.return_value = {"error": "unknown"}

    return resp


def mock_paypal_get(url, **kwargs):
    """Fake PayPal GET responses."""
    _captured_calls.append({"url": url, "kwargs": kwargs})
    resp = MagicMock()
    if "/v1/billing/subscriptions/" in url:
        resp.status_code = 200
        resp.json.return_value = {
            "id": "I-MOCK-SUB-DETAIL",
            "status": "ACTIVE",
            "plan_id": "P-MOCK-PLAN",
        }
    else:
        resp.status_code = 404
        resp.json.return_value = {}
    return resp


def run_test():
    passed = 0
    failed = 0
    warnings = 0

    def ok(msg):
        nonlocal passed; passed += 1; print(f"  PASS - {msg}")

    def fail(msg):
        nonlocal failed; failed += 1; print(f"  FAIL - {msg}")

    def warn(msg):
        nonlocal warnings; warnings += 1; print(f"  WARN - {msg}")

    print("=" * 65)
    print("  PAYPAL PRICING & SUBSCRIPTION FLOW TEST (all mocked)")
    print("=" * 65)

    # ================================================================
    # TEST 1: Verify PLAN_PRICES constant matches expected prices
    # ================================================================
    print("\n[1] Verify PLAN_PRICES constant in app.py")

    with patch("requests.post", side_effect=mock_paypal_post):
        with patch("requests.get", side_effect=mock_paypal_get):
            from app import app, PLAN_PRICES

    for plan_key, expected_price in EXPECTED_PRICES.items():
        actual = PLAN_PRICES.get(plan_key)
        if actual == expected_price:
            ok(f"{plan_key}: ${actual}")
        else:
            fail(f"{plan_key}: expected ${expected_price}, got ${actual}")

    # Check no extra plans snuck in
    extra = set(PLAN_PRICES.keys()) - set(EXPECTED_PRICES.keys())
    if extra:
        fail(f"Unexpected plans in PLAN_PRICES: {extra}")
    else:
        ok("No unexpected plans in PLAN_PRICES")

    # Check 'free' is NOT in PLAN_PRICES (free has no PayPal billing)
    if "free" not in PLAN_PRICES:
        ok("'free' correctly excluded from PLAN_PRICES")
    else:
        fail("'free' should not be in PLAN_PRICES")

    # ================================================================
    # TEST 2: Verify PayPal billing plan creation sends correct prices
    # ================================================================
    print("\n[2] Verify PayPal billing plans are created with correct prices")

    _captured_calls.clear()
    # Reset the cached plan IDs so _ensure_paypal_plans runs fresh
    import app as app_module
    app_module._paypal_plan_ids = {}
    # Clear DB-cached plan IDs so it actually calls PayPal API
    try:
        conn = db.get_db()
        conn.execute("DELETE FROM paypal_billing_plans")
        conn.commit()
        conn.close()
    except Exception:
        pass

    with patch("requests.post", side_effect=mock_paypal_post):
        result = app_module._ensure_paypal_plans()

    # Extract billing plan creation calls
    plan_creation_calls = [c for c in _captured_calls if "/v1/billing/plans" in c["url"]]

    if len(plan_creation_calls) == len(EXPECTED_PRICES):
        ok(f"Created {len(plan_creation_calls)} billing plans (one per paid tier)")
    else:
        fail(f"Expected {len(EXPECTED_PRICES)} plan creation calls, got {len(plan_creation_calls)}")

    for call in plan_creation_calls:
        body = call["kwargs"].get("json", {})
        name = body.get("name", "")
        cycles = body.get("billing_cycles", [])
        if not cycles:
            fail(f"No billing cycles in plan: {name}")
            continue
        price_val = cycles[0]["pricing_scheme"]["fixed_price"]["value"]
        currency = cycles[0]["pricing_scheme"]["fixed_price"]["currency_code"]

        # Match plan key from name
        plan_key = None
        for k in EXPECTED_PRICES:
            if k in name.lower():
                plan_key = k
                break

        if plan_key:
            if price_val == EXPECTED_PRICES[plan_key] and currency == "USD":
                ok(f"PayPal plan '{name}': ${price_val} {currency}")
            else:
                fail(f"PayPal plan '{name}': expected ${EXPECTED_PRICES[plan_key]} USD, got ${price_val} {currency}")
        else:
            warn(f"Could not match plan name '{name}' to a known plan key")

    # Verify all plans got IDs back
    for plan_key in EXPECTED_PRICES:
        if plan_key in result:
            ok(f"Got PayPal plan ID for {plan_key}: {result[plan_key]}")
        else:
            fail(f"Missing PayPal plan ID for {plan_key}")

    # ================================================================
    # TEST 3: Subscription creation endpoint
    # ================================================================
    print("\n[3] Test /api/paypal/create-subscription endpoint")

    # Get a head_admin user
    import secrets
    from datetime import datetime, timedelta
    conn = db.get_db()
    test_user = conn.execute(
        "SELECT * FROM users WHERE role='head_admin' LIMIT 1"
    ).fetchone()
    if not test_user:
        fail("No head_admin user found in database")
        conn.close()
        print_summary(passed, failed, warnings)
        return

    user_id = test_user["id"]
    old_plan = test_user["plan"]
    old_token = test_user["token"]
    old_token_expires = test_user["token_expires_at"]

    token = secrets.token_hex(32)
    expires = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE users SET token=%s, token_expires_at=%s, plan='free_trial' WHERE id=%s",
                 (token, expires, user_id))
    conn.commit()
    conn.close()

    print(f"  Test user: {test_user['name']} (ID: {user_id})")

    # Reset subscription counter and clean up stale mock data
    global _sub_counter
    _sub_counter = 0
    # Clean up any stale mock checkout sessions from previous test runs
    try:
        conn2 = db.get_db()
        conn2.execute("DELETE FROM checkout_sessions WHERE token LIKE 'I-MOCK-SUB-%%'")
        conn2.commit()
        conn2.close()
    except Exception:
        pass

    app.config["TESTING"] = True
    client = app.test_client()

    # Test subscription creation for each plan
    for plan_key in EXPECTED_PRICES:
        with patch("requests.post", side_effect=mock_paypal_post):
            with patch("requests.get", side_effect=mock_paypal_get):
                resp = client.post("/api/paypal/create-subscription",
                    json={"plan": plan_key},
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

        data = resp.get_json()
        if resp.status_code in (200, 201) and data.get("subscription_id"):
            ok(f"create-subscription({plan_key}): got subscription_id={data['subscription_id']}")
        else:
            fail(f"create-subscription({plan_key}): status={resp.status_code}, response={data}")

    # ================================================================
    # TEST 4: Invalid plan rejected
    # ================================================================
    print("\n[4] Test invalid plan rejection")

    for bad_plan in ["free", "diamond", "platinum", ""]:
        with patch("requests.post", side_effect=mock_paypal_post):
            resp = client.post("/api/paypal/create-subscription",
                json={"plan": bad_plan},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        if resp.status_code == 400:
            ok(f"Rejected invalid plan '{bad_plan}'")
        else:
            fail(f"Did not reject invalid plan '{bad_plan}' (status={resp.status_code})")

    # ================================================================
    # TEST 5: Unauthorized access rejected
    # ================================================================
    print("\n[5] Test unauthorized access")

    with patch("requests.post", side_effect=mock_paypal_post):
        resp = client.post("/api/paypal/create-subscription",
            json={"plan": "basic"},
            headers={"Content-Type": "application/json"})
    if resp.status_code == 401:
        ok("Rejected request without auth token")
    else:
        fail(f"Did not reject unauthorized request (status={resp.status_code})")

    # ================================================================
    # TEST 6: Verify checkout.html PLANS match backend prices
    # ================================================================
    print("\n[6] Verify checkout.html frontend prices match backend")

    checkout_prices = {
        "free": "$0",
        "basic": "$23",
        "growth": "$79",
        "pro": "$299",
        "agency": "$699",      # enterprise uses 'agency' key in checkout
    }
    checkout_path = os.path.join(os.path.dirname(__file__), "static", "checkout.html")
    with open(checkout_path, "r") as f:
        checkout_content = f.read()

    for plan_key, expected_price in checkout_prices.items():
        # Check that the price string appears in the plan block
        if f"price: '{expected_price}'" in checkout_content:
            ok(f"checkout.html {plan_key}: {expected_price}")
        else:
            fail(f"checkout.html {plan_key}: expected price: '{expected_price}' not found")

    # Verify backend PLAN_PRICES align with checkout display prices
    for plan_key, backend_price in PLAN_PRICES.items():
        display = "$" + str(int(float(backend_price)))
        found = False
        for ck, cp in checkout_prices.items():
            if cp.rstrip("+") == display.rstrip("+"):
                if plan_key == "enterprise" and ck == "agency":
                    found = True
                elif plan_key == ck:
                    found = True
        if found:
            ok(f"Backend {plan_key} (${backend_price}) matches frontend display")
        else:
            fail(f"Backend {plan_key} (${backend_price}) has no matching frontend price")

    # ================================================================
    # TEST 7: Verify billing cycle is monthly for all plans
    # ================================================================
    print("\n[7] Verify all billing cycles are MONTH/1")

    plan_creation_calls = [c for c in _captured_calls if "/v1/billing/plans" in c["url"]]
    for call in plan_creation_calls:
        body = call["kwargs"].get("json", {})
        name = body.get("name", "")
        cycles = body.get("billing_cycles", [])
        if cycles:
            freq = cycles[0].get("frequency", {})
            if freq.get("interval_unit") == "MONTH" and freq.get("interval_count") == 1:
                ok(f"{name}: monthly billing cycle")
            else:
                fail(f"{name}: expected MONTH/1, got {freq}")
            if cycles[0].get("total_cycles") == 0:
                ok(f"{name}: infinite renewal (total_cycles=0)")
            else:
                warn(f"{name}: total_cycles={cycles[0].get('total_cycles')} (expected 0 for auto-renewal)")

    # ── Restore original state ──
    restore_user(user_id, old_plan, old_token, old_token_expires)

    print_summary(passed, failed, warnings)


def print_summary(passed, failed, warnings):
    print("\n" + "=" * 65)
    total = passed + failed
    print(f"  RESULTS: {passed}/{total} passed", end="")
    if warnings:
        print(f", {warnings} warnings", end="")
    if failed == 0:
        print(" -- ALL PASSED")
    else:
        print(f" -- {failed} FAILED")
    print("=" * 65)


def restore_user(user_id, plan, token, token_expires):
    conn = db.get_db()
    conn.execute("UPDATE users SET plan=%s, token=%s, token_expires_at=%s WHERE id=%s",
                 (plan, token or None, token_expires or None, user_id))
    conn.commit()
    conn.close()
    print(f"\n  Restored user back to plan='{plan}'")


if __name__ == "__main__":
    run_test()
