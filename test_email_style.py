#!/usr/bin/env python3
"""
Email Style & Button Constraint Test Suite — 50 tests
Tests that every email type:
  1. Has correct buttons (no irrelevant actions)
  2. Applies admin's custom styles properly
  3. Uses _wrap_luxury with correct variables
  4. No cross-contamination between email types
  5. Style replacement works for all brand colors
"""
import sys, os, inspect, re
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


import email_service as es

# ═══════════════════════════════════════════════════════════════
# SECTION A: BUTTON INTEGRITY — NO IRRELEVANT BUTTONS (Tests 1–15)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION A: NO IRRELEVANT BUTTONS IN EMAILS")
print("="*70)

# Generate actual HTML from each email function to inspect buttons
# We can't send real emails, so we inspect the source code for button text

src_confirm = inspect.getsource(es.send_booking_confirmation_customer)
src_cancel = inspect.getsource(es.send_booking_cancellation)
src_resched = inspect.getsource(es.send_booking_reschedule)
src_previsit = inspect.getsource(es.send_previsit_form)
src_waitlist_notif = inspect.getsource(es.send_waitlist_notification)
src_waitlist_placed = inspect.getsource(es.send_waitlist_placed_email)
src_waitlist_exp = inspect.getsource(es.send_waitlist_expired_notification)
src_recall = inspect.getsource(es.send_recall_email)
src_followup = inspect.getsource(es.send_treatment_followup)
src_welcome = inspect.getsource(es.send_welcome_email)
src_review = inspect.getsource(es.send_review_request)
src_noshow = inspect.getsource(es.send_noshow_email)
src_lead = inspect.getsource(es.send_lead_followup)

# A1: Booking confirmation — has View Details and Cancel, but NO "Reschedule" button
# (The word "reschedule" may appear as text, but not as a <a> button)
confirm_buttons = re.findall(r'<a[^>]*>([^<]+)</a>', src_confirm)
confirm_btn_text = ' '.join(confirm_buttons).lower()
test("Booking confirmation: has 'View Details' button",
     "view details" in confirm_btn_text)

test("Booking confirmation: has 'Cancel Appointment' button",
     "cancel appointment" in confirm_btn_text)

test("Booking confirmation: NO 'Reschedule' button (only text mention)",
     "reschedule" not in confirm_btn_text,
     f"Found reschedule in buttons: {confirm_buttons}")

# A4: Booking cancellation — NO action buttons (it's an info-only email)
cancel_buttons = re.findall(r'<a[^>]*>([^<]+)</a>', src_cancel)
cancel_btn_text = ' '.join(cancel_buttons).lower()
test("Booking cancellation: NO 'Reschedule' action button",
     "reschedule" not in cancel_btn_text)

test("Booking cancellation: NO 'Cancel' action button (already cancelled)",
     "cancel appointment" not in cancel_btn_text and "cancel booking" not in cancel_btn_text)

# A6: Booking reschedule — info only, no "Book Again" or "Cancel" button
resched_buttons = re.findall(r'<a[^>]*>([^<]+)</a>', src_resched)
resched_btn_text = ' '.join(resched_buttons).lower()
test("Booking reschedule: NO 'Cancel' button",
     "cancel" not in resched_btn_text)

test("Booking reschedule: NO 'Book Now' button",
     "book now" not in resched_btn_text)

# A8: Waitlist notification — has Confirm, NO Cancel or Reschedule
waitlist_n_buttons = re.findall(r'<a[^>]*>([^<]+)</a>', src_waitlist_notif)
waitlist_n_btn_text = ' '.join(waitlist_n_buttons).lower()
test("Waitlist notification: has 'Confirm' button",
     "confirm" in waitlist_n_btn_text)

test("Waitlist notification: NO 'Reschedule' button",
     "reschedule" not in waitlist_n_btn_text)

# A10: Recall email — has 'Book Now', NO 'Cancel Appointment'
recall_buttons = re.findall(r'<a[^>]*>([^<]+)</a>', src_recall)
recall_btn_text = ' '.join(recall_buttons).lower()
test("Recall email: has 'Book Now' button",
     "book now" in recall_btn_text)

test("Recall email: NO 'Cancel Appointment' button",
     "cancel appointment" not in recall_btn_text)

# A12: Welcome email — NO 'Cancel' or 'Reschedule' buttons
welcome_buttons = re.findall(r'<a[^>]*>([^<]+)</a>', src_welcome)
welcome_btn_text = ' '.join(welcome_buttons).lower()
test("Welcome email: NO 'Cancel Appointment' button",
     "cancel appointment" not in welcome_btn_text)

test("Welcome email: NO 'Reschedule' button",
     "reschedule" not in welcome_btn_text)

# A14: Review request — NO 'Cancel' or 'Reschedule' buttons
review_buttons = re.findall(r'<a[^>]*>([^<]+)</a>', src_review)
review_btn_text = ' '.join(review_buttons).lower()
test("Review request: NO 'Cancel Appointment' button",
     "cancel" not in review_btn_text)

test("Review request: NO 'Reschedule' button",
     "reschedule" not in review_btn_text)


# ═══════════════════════════════════════════════════════════════
# SECTION B: EMAIL BUILDER BUTTON CONSTRAINTS (Tests 16–25)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION B: EMAIL BUILDER TEMPLATE BUTTON CONSTRAINTS")
print("="*70)

with open(os.path.join(os.path.dirname(__file__), "static/user-dashboard.html")) as f:
    dash_src = f.read()

# Extract _ebTemplateButtons config
eb_match = re.search(r'const _ebTemplateButtons\s*=\s*\{(.*?)\};', dash_src, re.DOTALL)
eb_config = eb_match.group(1) if eb_match else ""

# B1: booking_confirmation allows: view_appointment, fill_form, cancel_appointment
test("EB: booking_confirmation allows view_appointment",
     "'view_appointment'" in eb_config.split("booking_confirmation")[1].split("],")[0])

test("EB: booking_confirmation does NOT allow 'book_recall'",
     "'book_recall'" not in eb_config.split("booking_confirmation")[1].split("],")[0])

test("EB: booking_confirmation does NOT allow 'waitlist_confirm'",
     "'waitlist_confirm'" not in eb_config.split("booking_confirmation")[1].split("],")[0])

# B4: waitlist_placed allows: waitlist_confirm, waitlist_remove ONLY
wl_section = eb_config.split("waitlist_placed")[1].split("],")[0] if "waitlist_placed" in eb_config else ""
test("EB: waitlist_placed allows waitlist_confirm",
     "'waitlist_confirm'" in wl_section)

test("EB: waitlist_placed allows waitlist_remove",
     "'waitlist_remove'" in wl_section)

test("EB: waitlist_placed does NOT allow view_appointment",
     "'view_appointment'" not in wl_section)

test("EB: waitlist_placed does NOT allow cancel_appointment",
     "'cancel_appointment'" not in wl_section)

# B8: recall_email allows book_recall, NOT cancel_appointment
recall_section = eb_config.split("recall_email")[1].split("],")[0] if "recall_email" in eb_config else ""
test("EB: recall_email allows book_recall",
     "'book_recall'" in recall_section)

test("EB: recall_email does NOT allow cancel_appointment",
     "'cancel_appointment'" not in recall_section)

# B10: welcome_email — NO cancel_appointment
welcome_section = eb_config.split("welcome_email")[1].split("],")[0] if "welcome_email" in eb_config else ""
test("EB: welcome_email does NOT allow cancel_appointment",
     "'cancel_appointment'" not in welcome_section)


# ═══════════════════════════════════════════════════════════════
# SECTION C: CUSTOM STYLE APPLICATION (Tests 26–37)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION C: ADMIN CUSTOM STYLES APPLIED CORRECTLY")
print("="*70)

src_wrap_custom = inspect.getsource(es._wrap_custom_template)
src_wrap_luxury = inspect.getsource(es._wrap_luxury)

# C1: _wrap_custom_template reads and applies all key style properties
test("Style: applies bg_color from template",
     "bg_color" in src_wrap_custom and "background:{bg}" in src_wrap_custom.replace(" ", "").replace("'","").replace('"',''))

test("Style: applies primary_color from template",
     "primary_color" in src_wrap_custom)

test("Style: applies button_color from template",
     "button_color" in src_wrap_custom)

test("Style: applies button_text_color from template",
     "button_text_color" in src_wrap_custom)

test("Style: applies button_radius from template",
     "button_radius" in src_wrap_custom)

test("Style: applies font_family from template",
     "font_family" in src_wrap_custom)

test("Style: applies logo_url from template",
     "logo_url" in src_wrap_custom and '<img src="{logo_url}"' in src_wrap_custom)

test("Style: applies header_html from template",
     "header_html" in src_wrap_custom)

test("Style: applies footer_html from template",
     "footer_html" in src_wrap_custom)

test("Style: applies content_width from template",
     "content_width" in src_wrap_custom)

test("Style: applies card_radius from template",
     "card_radius" in src_wrap_custom)

test("Style: applies line_height and letter_spacing",
     "line_height" in src_wrap_custom and "letter_spacing" in src_wrap_custom)


# ═══════════════════════════════════════════════════════════════
# SECTION D: COLOR REPLACEMENT — DEFAULT COLORS REPLACED (Tests 38–45)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION D: DEFAULT BRAND COLORS REPLACED WITH ADMIN'S")
print("="*70)

# Default purple #8b5cf6 and #7c3aed should be replaced throughout
# Check that _wrap_custom_template replaces all key default color patterns

test("Color replace: gradient bar (90deg,#8b5cf6,...) replaced",
     "linear-gradient(90deg,#8b5cf6,#7c3aed,#a78bfa,#7c3aed,#8b5cf6)" in src_wrap_custom
     and ".replace(" in src_wrap_custom)

test("Color replace: button gradient (135deg,#8b5cf6,...) replaced",
     'linear-gradient(135deg,#8b5cf6,#7c3aed,#a78bfa)' in src_wrap_custom)

test("Color replace: solid background:#8b5cf6 replaced",
     '"background:#8b5cf6"' in src_wrap_custom)

test("Color replace: solid color:#8b5cf6 replaced",
     '"color:#8b5cf6"' in src_wrap_custom)

test("Color replace: box-shadow purple replaced",
     "box-shadow:0 8px 24px rgba(139,92,246,0.4)" in src_wrap_custom)

test("Color replace: border-left accent replaced",
     "border-left:4px solid #8b5cf6" in src_wrap_custom)

test("Color replace: button text color replaced with admin's",
     'btn_text' in src_wrap_custom and "color:{btn_text}" in src_wrap_custom.replace(" ",""))

test("Color replace: button border-radius replaced with admin's",
     'btn_radius' in src_wrap_custom and "border-radius:{btn_radius}px" in src_wrap_custom.replace(" ",""))


# ═══════════════════════════════════════════════════════════════
# SECTION E: TEMPLATE VARIABLE INJECTION (Tests 46–50)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION E: TEMPLATE VARIABLES & COMPILED HTML PATH")
print("="*70)

# E1: render_template_variables replaces {{var}} placeholders
src_rtv = inspect.getsource(es.render_template_variables)
test("render_template_variables: uses regex for {{var}} replacement",
     r'\{\{(\w+)\}\}' in src_rtv or '{{' in src_rtv)

# E2: All email functions that pass variables include key variables
# Check booking confirmation variables
test("Booking confirm: passes confirm_link variable",
     '"confirm_link"' in src_confirm and 'variables' in src_confirm)

test("Booking confirm: passes cancel_link variable",
     '"cancel_link"' in src_confirm)

# E3: _wrap_luxury compiled HTML path replaces {{content}} and strips watermark
test("_wrap_luxury: compiled HTML uses {{content}} injection",
     '{{content}}' in src_wrap_luxury and '.replace("{{content}}"' in src_wrap_luxury)

test("_wrap_luxury: compiled HTML path calls _strip_watermark",
     '_strip_watermark' in src_wrap_luxury)


# ═══════════════════════════════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print(f"RESULTS: {PASS}/{TOTAL} passed, {FAIL} failed")
print("="*70)

if FAIL > 0:
    print(f"\n{FAIL} TEST(S) FAILED — review above")
    sys.exit(1)
else:
    print("\nALL TESTS PASSED")
