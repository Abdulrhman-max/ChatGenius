#!/usr/bin/env python3
"""
Email System Mock Test Suite — 60 tests
Actually renders emails by mocking _send_email and database calls,
then inspects the generated HTML for correctness.
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))

PASS = 0
FAIL = 0
TOTAL = 0

def test(name, condition, detail=""):
    global PASS, FAIL, TOTAL
    TOTAL += 1
    if condition:
        PASS += 1
        print(f"  [{TOTAL:02d}] PASS  {name}")
    else:
        FAIL += 1
        print(f"  [{TOTAL:02d}] FAIL  {name}  — {detail}")


# ── Mock Setup ───────────────────────────────────────────────────────────────
# Capture emails instead of sending them
_captured_emails = []
_mock_company_type = "dental"
_mock_template = None
_mock_smtp_config = None

import email_service as es
import database as db

# Save originals
_orig_send = es._send_email
_orig_get_company_type = es._get_company_type
_orig_get_biz_name = es._get_admin_business_name
_orig_get_plan = es._get_admin_plan
_orig_get_template = None
_orig_get_smtp = None

def _mock_send_email(to_email, subject, html_body, from_name=None, admin_id=None):
    _captured_emails.append({
        "to": to_email, "subject": subject, "html": html_body,
        "from_name": from_name, "admin_id": admin_id
    })
    return True

def _mock_company_type_fn(admin_id):
    return _mock_company_type

def _mock_biz_name(admin_id):
    return "Bright Smile Dental"

def _mock_plan(admin_id):
    return "pro"

def _mock_get_template(admin_id):
    return _mock_template

def _mock_get_smtp(admin_id):
    return _mock_smtp_config

# Patch
es._send_email = _mock_send_email
es._get_company_type = _mock_company_type_fn
es._get_admin_business_name = _mock_biz_name
es._get_admin_plan = _mock_plan

# Patch db functions used inside _wrap_luxury
try:
    _orig_get_template = db.get_email_template
    db.get_email_template = _mock_get_template
    _orig_get_smtp = db.get_admin_smtp_config
    db.get_admin_smtp_config = _mock_get_smtp
except:
    pass

def clear():
    _captured_emails.clear()

def last_html():
    return _captured_emails[-1]["html"] if _captured_emails else ""

def last_subject():
    return _captured_emails[-1]["subject"] if _captured_emails else ""

def last_from():
    return _captured_emails[-1]["from_name"] if _captured_emails else ""


# ═══════════════════════════════════════════════════════════════════════════
# SECTION A: BOOKING CONFIRMATION — RENDERED HTML (Tests 1–10)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION A: BOOKING CONFIRMATION — RENDERED HTML")
print("="*70)

clear()
_mock_company_type = "dental"
es.send_booking_confirmation_customer(
    "John Doe", "john@test.com", "June 15, 2026", "10:00 AM",
    doctor_name="Sarah Smith", confirm_url="https://example.com/view",
    cancel_url="https://example.com/cancel", service_name="Teeth Cleaning",
    duration_minutes=45, price="$120", preparation_instructions="Brush before visit",
    admin_id=1
)
html = last_html()

test("Booking confirm: contains patient name",
     "John Doe" in html)

test("Booking confirm: contains date",
     "June 15, 2026" in html)

test("Booking confirm: contains time",
     "10:00 AM" in html)

test("Booking confirm: contains service name",
     "Teeth Cleaning" in html)

test("Booking confirm: contains 'View Details' button with confirm_url",
     "View Details" in html and "https://example.com/view" in html)

test("Booking confirm: contains 'Cancel Appointment' button with cancel_url",
     "Cancel Appointment" in html and "https://example.com/cancel" in html)

test("Booking confirm: NO 'Reschedule' button (only text)",
     'Reschedule' not in re.sub(r'Need to reschedule\?[^<]*', '', html))

test("Booking confirm: dental shows 'Doctor' label and 'Dr.' prefix",
     "Doctor" in html and "Dr. Sarah Smith" in html)

test("Booking confirm: dental shows 'insurance card' tip",
     "insurance card" in html.lower())

test("Booking confirm: contains preparation instructions",
     "Brush before visit" in html)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION B: ECOMMERCE ISOLATION (Tests 11–18)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION B: ECOMMERCE — NO DENTAL CONTENT")
print("="*70)

clear()
_mock_company_type = "ecommerce"
es.send_booking_confirmation_customer(
    "Jane Shop", "jane@test.com", "June 20, 2026", "2:00 PM",
    doctor_name="Mike Expert", service_name="Consultation",
    confirm_url="https://example.com/view", cancel_url="https://example.com/cancel",
    admin_id=2
)
html = last_html()

test("Ecommerce confirm: NO 'Doctor' label",
     ">Doctor<" not in html)

test("Ecommerce confirm: NO 'Dr.' prefix",
     "Dr. Mike" not in html)

test("Ecommerce confirm: shows 'Specialist' label",
     "Specialist" in html)

test("Ecommerce confirm: NO 'insurance card' tip",
     "insurance card" not in html.lower())

test("Ecommerce confirm: shows generic tips, not dental",
     "Good to know" in html)

# Welcome email — ecommerce version
clear()
es.send_welcome_email("jane@test.com", "Jane Shop", admin_id=2)
html = last_html()

test("Ecommerce welcome: NO 'pre-visit form' content",
     "pre-visit" not in html.lower())

test("Ecommerce welcome: has ecommerce content (shipping/offers/returns)",
     any(w in html.lower() for w in ["shipping", "offers", "returns", "order"]))

test("Ecommerce welcome: NO 'insurance' content",
     "insurance" not in html.lower())


# ═══════════════════════════════════════════════════════════════════════════
# SECTION C: NO WATERMARK, NO CHATGENIUS (Tests 19–24)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION C: NO WATERMARK / NO CHATGENIUS IN ANY EMAIL")
print("="*70)

_mock_company_type = "dental"
email_fns = [
    ("booking_confirm", lambda: es.send_booking_confirmation_customer("A","a@t.com","D","T",admin_id=1)),
    ("cancellation", lambda: es.send_booking_cancellation("a@t.com","A","D","T",admin_id=1)),
    ("reschedule", lambda: es.send_booking_reschedule("a@t.com","A","D1","T1","D2","T2",admin_id=1)),
    ("welcome", lambda: es.send_welcome_email("a@t.com","A",admin_id=1)),
    ("review", lambda: es.send_review_request("a@t.com","A","https://r.com",admin_id=1)),
    ("recall", lambda: es.send_recall_email("a@t.com","A","Cleaning",admin_id=1)),
]

for label, fn in email_fns:
    clear()
    fn()
    html = last_html()
    test(f"{label}: no 'Powered by' watermark",
         "Powered by" not in html)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION D: FROM NAME = BUSINESS NAME (Tests 25–30)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION D: FROM NAME IS ALWAYS BUSINESS NAME")
print("="*70)

fns_to_check = [
    ("booking_confirm", lambda: es.send_booking_confirmation_customer("A","a@t.com","D","T",admin_id=1)),
    ("cancellation", lambda: es.send_booking_cancellation("a@t.com","A","D","T",admin_id=1)),
    ("reschedule", lambda: es.send_booking_reschedule("a@t.com","A","D1","T1","D2","T2",admin_id=1)),
    ("recall", lambda: es.send_recall_email("a@t.com","A","Cleaning",admin_id=1)),
    ("welcome", lambda: es.send_welcome_email("a@t.com","A",admin_id=1)),
    ("review", lambda: es.send_review_request("a@t.com","A","https://r.com",admin_id=1)),
]

for label, fn in fns_to_check:
    clear()
    fn()
    from_name = last_from()
    test(f"{label}: from_name is 'Bright Smile Dental'",
         from_name == "Bright Smile Dental", f"Got: {from_name}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION E: BUTTON INTEGRITY — RENDERED HTML (Tests 31–40)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION E: BUTTON INTEGRITY IN RENDERED EMAILS")
print("="*70)

# E1: Cancellation email — no action buttons
clear()
es.send_booking_cancellation("a@t.com", "John", "June 15", "10 AM",
                             doctor_name="Smith", reason="Patient request", admin_id=1)
html = last_html()
# Extract all <a> button texts (exclude plain text links)
buttons = [m.strip() for m in re.findall(r'<a[^>]*style="[^"]*(?:background|padding)[^"]*"[^>]*>\s*([^<]+?)\s*</a>', html)]
test("Cancellation: no 'Reschedule' button in rendered HTML",
     not any("reschedule" in b.lower() for b in buttons), f"Buttons: {buttons}")

test("Cancellation: no 'Cancel' button (already cancelled)",
     not any("cancel" in b.lower() for b in buttons), f"Buttons: {buttons}")

# E3: Reschedule email — info only
clear()
es.send_booking_reschedule("a@t.com", "John", "June 10", "9 AM", "June 15", "11 AM",
                           doctor_name="Smith", admin_id=1)
html = last_html()
buttons = [m.strip() for m in re.findall(r'<a[^>]*style="[^"]*(?:background|padding)[^"]*"[^>]*>\s*([^<]+?)\s*</a>', html)]
test("Reschedule: no 'Cancel' button",
     not any("cancel" in b.lower() for b in buttons), f"Buttons: {buttons}")

test("Reschedule: no 'Book Now' button",
     not any("book now" in b.lower() for b in buttons), f"Buttons: {buttons}")

# E5: Recall email — has Book Now, no Cancel
clear()
es.send_recall_email("a@t.com", "John", "Cleaning", booking_url="https://book.com", admin_id=1)
html = last_html()
test("Recall: contains 'Book Now' button",
     "Book Now" in html)

test("Recall: no 'Cancel Appointment' button",
     "Cancel Appointment" not in html)

# E7: Waitlist placed — has confirm + remove, no cancel appointment
clear()
es.send_waitlist_placed_email("a@t.com", "John", "June 15", "10 AM",
                               confirm_url="https://c.com", remove_url="https://r.com", admin_id=1)
html = last_html()
test("Waitlist placed: has confirm URL",
     "https://c.com" in html)

test("Waitlist placed: has remove URL",
     "https://r.com" in html)

test("Waitlist placed: no 'Reschedule' button",
     "Reschedule" not in html)

# E10: No-show email — no booking buttons
clear()
es.send_noshow_email("a@t.com", "John", "June 15", "10 AM", reason_url="https://reason.com", admin_id=1)
html = last_html()
test("No-show: no 'Cancel Appointment' button",
     "Cancel Appointment" not in html)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION F: CUSTOM TEMPLATE STYLING — RENDERED (Tests 41–50)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION F: CUSTOM TEMPLATE COLORS APPLIED IN RENDERED HTML")
print("="*70)

# Set up a mock template with custom colors
_mock_template = {
    "primary_color": "#e63946",
    "button_color": "#e63946",
    "button_text_color": "#ffffff",
    "button_radius": "24",
    "bg_color": "#f1faee",
    "font_family": "Georgia, serif",
    "logo_url": "https://example.com/logo.png",
    "header_html": "<p>Welcome from our clinic!</p>",
    "footer_html": "<p>Thanks for choosing us</p>",
    "content_width": "640",
    "card_radius": "12",
    "card_shadow": "0 10px 30px rgba(0,0,0,0.05)",
    "line_height": "1.8",
    "letter_spacing": "0.5",
    "compiled_html": None,  # no compiled HTML, use _wrap_custom_template path
}

clear()
es.send_booking_confirmation_customer(
    "Alice", "alice@test.com", "July 1, 2026", "3:00 PM",
    service_name="Checkup", admin_id=1
)
html = last_html()

test("Custom template: background uses admin bg_color #f1faee",
     "#f1faee" in html)

test("Custom template: uses admin primary_color #e63946",
     "#e63946" in html)

test("Custom template: uses admin font Georgia",
     "Georgia" in html)

test("Custom template: logo image rendered",
     "https://example.com/logo.png" in html)

test("Custom template: header HTML injected",
     "Welcome from our clinic!" in html)

test("Custom template: footer HTML injected",
     "Thanks for choosing us" in html)

test("Custom template: content_width is 640",
     "640" in html)

test("Custom template: card_radius is 12px",
     "12px" in html)

test("Custom template: letter_spacing applied",
     "letter-spacing:0.5px" in html)

test("Custom template: no 'Powered by' even with custom template",
     "Powered by" not in html)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION G: COMPILED HTML TEMPLATE PATH (Tests 51–56)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION G: COMPILED HTML (DRAG-AND-DROP) TEMPLATE PATH")
print("="*70)

# Test with compiled HTML that has {{content}} placeholder
_mock_template = {
    "compiled_html": """<html><body style="background:#1a1a2e">
        <div style="font-family:Inter,sans-serif;max-width:600px;margin:auto;background:#fff;border-radius:16px">
            <div style="background:#059669;padding:20px;text-align:center;color:#fff">
                <h1>My Custom Header</h1>
            </div>
            {{content}}
            <div style="padding:10px;text-align:center;color:#999">Custom Footer Text</div>
        </div>
    </body></html>""",
    "primary_color": "#059669",
}

clear()
es.send_booking_confirmation_customer(
    "Bob", "bob@test.com", "July 5, 2026", "11:00 AM",
    service_name="Dental Exam", admin_id=1
)
html = last_html()

test("Compiled template: content injected (patient name visible)",
     "Bob" in html)

test("Compiled template: custom header preserved",
     "My Custom Header" in html)

test("Compiled template: custom footer preserved",
     "Custom Footer Text" in html)

test("Compiled template: {{content}} placeholder replaced (not in output)",
     "{{content}}" not in html)

test("Compiled template: no 'Powered by' watermark",
     "Powered by" not in html)

test("Compiled template: original layout colors preserved (#059669)",
     "#059669" in html)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION H: SUBJECT LINES & VARIABLE REPLACEMENT (Tests 57–60)
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION H: SUBJECT LINES & TEMPLATE VARIABLES")
print("="*70)

# Reset template to None for clean subject tests
_mock_template = None

clear()
es.send_booking_confirmation_customer(
    "Charlie", "c@t.com", "Aug 1, 2026", "9 AM", admin_id=1)
test("Subject: booking confirm includes date",
     "Aug 1, 2026" in last_subject())

clear()
es.send_booking_cancellation("c@t.com", "Charlie", "Aug 1, 2026", "9 AM", admin_id=1)
test("Subject: cancellation includes date",
     "Aug 1, 2026" in last_subject())

clear()
es.send_booking_reschedule("c@t.com", "Charlie", "Aug 1", "9 AM", "Aug 5, 2026", "11 AM", admin_id=1)
test("Subject: reschedule includes NEW date",
     "Aug 5, 2026" in last_subject())

# Variable replacement test with compiled template
_mock_template = {
    "compiled_html": "<html><body>Hello {{patient_name}}, your appointment on {{date}} at {{time}} is confirmed. {{clinic_name}} {{content}}</body></html>",
}
clear()
es.send_booking_confirmation_customer(
    "Diana", "d@t.com", "Sep 10, 2026", "2 PM", admin_id=1)
html = last_html()
test("Variables: {{patient_name}} replaced with 'Diana'",
     "Diana" in html and "{{patient_name}}" not in html)


# ═══════════════════════════════════════════════════════════════════════════
# Cleanup — restore originals
# ═══════════════════════════════════════════════════════════════════════════
es._send_email = _orig_send
es._get_company_type = _orig_get_company_type
es._get_admin_business_name = _orig_get_biz_name
es._get_admin_plan = _orig_get_plan
if _orig_get_template:
    db.get_email_template = _orig_get_template
if _orig_get_smtp:
    db.get_admin_smtp_config = _orig_get_smtp

# ═══════════════════════════════════════════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print(f"RESULTS: {PASS}/{TOTAL} passed, {FAIL} failed")
print("="*70)

if FAIL > 0:
    print(f"\n{FAIL} TEST(S) FAILED — review above")
    sys.exit(1)
else:
    print("\nALL 60 MOCK TESTS PASSED")
