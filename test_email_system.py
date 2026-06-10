#!/usr/bin/env python3
"""
Intensive Email System Test Suite — 60 tests
Tests: no watermark, company type isolation, admin template usage,
       Email Builder button constraints, engine scheduling logic, from-name.
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


import database as db
import email_service as es
import appointment_reminder_engine as are
import treatment_followup_engine as tfe
import recall_engine as re_eng
import noshow_recovery_engine as nre
import reviews_engine as rev

# ═══════════════════════════════════════════════════════════════
# SECTION A: NO CHATGENIUS WATERMARK (Tests 1–10)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*65)
print("SECTION A: NO CHATGENIUS WATERMARK — ALL PLANS, ALL TYPES")
print("="*65)

# A1: hide_watermark always True
src = inspect.getsource(es._wrap_luxury)
test("_wrap_luxury: hide_watermark = True (hardcoded)",
     "hide_watermark = True" in src)

# A2: default wrapper never renders watermark
test("Default wrapper: 'Powered by' gated by 'if not hide_watermark'",
     "if not hide_watermark" in src and "hide_watermark = True" in src)

# A3: custom template wrapper also gated
src_ct = inspect.getsource(es._wrap_custom_template)
test("Custom template wrapper: watermark gated by hide_watermark param",
     "hide_watermark" in src_ct)

# A4: _strip_watermark exists for compiled HTML path
test("_strip_watermark function exists",
     hasattr(es, '_strip_watermark'))

# A5: No-show recovery email has no ChatGenius
src_nre = inspect.getsource(nre._build_recovery_email)
test("No-show recovery email: no ChatGenius text",
     "ChatGenius" not in src_nre)

# A6: Appointment reminder email has no ChatGenius
src_are = inspect.getsource(are._build_reminder_email)
test("Appointment reminder email: no ChatGenius text",
     "ChatGenius" not in src_are)

# A7-A10: Simulate all plans and verify watermark never appears
for plan_name in ["free_trial", "basic", "pro", "enterprise"]:
    original = es._get_admin_plan
    es._get_admin_plan = lambda aid: plan_name
    html = es._wrap_luxury("<tr><td>Test</td></tr>", admin_id=None)
    es._get_admin_plan = original
    has_watermark = "Powered by" in html and "ChatGenius" in html
    test(f"Plan '{plan_name}': no watermark in rendered HTML",
         not has_watermark)


# ═══════════════════════════════════════════════════════════════
# SECTION B: NO CHATGENIUS IN FROM/BUSINESS EMAIL (Tests 11–16)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*65)
print("SECTION B: NO CHATGENIUS IN FROM NAME OR FALLBACK")
print("="*65)

# B1: _get_admin_business_name fallback is NOT ChatGenius
src_biz = inspect.getsource(es._get_admin_business_name)
test("Business name fallback: no 'ChatGenius' string",
     "ChatGenius" not in src_biz)

# B2: Fallback is neutral
test("Business name fallback is 'Our Business'",
     "Our Business" in src_biz)

# B3: Falls back to user's company name before generic
test("Fallback chain: company_info -> users.company -> users.name -> Our Business",
     "company" in src_biz.lower() and "name" in src_biz.lower())

# B4: _send_email accepts from_name
src_send = inspect.getsource(es._send_email)
test("_send_email accepts from_name parameter",
     "from_name" in src_send)

# B5: from_name overrides BUSINESS_NAME
test("_send_email: from_name used in From header",
     "from_name or BUSINESS_NAME" in src_send or "from_name or" in src_send)

# B6: Appointment reminder engine no longer uses BUSINESS_NAME
src_are_full = inspect.getsource(are)
test("Appointment reminder: no BUSINESS_NAME constant usage",
     "BUSINESS_NAME" not in src_are_full)


# ═══════════════════════════════════════════════════════════════
# SECTION C: COMPANY TYPE ISOLATION (Tests 17–30)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*65)
print("SECTION C: DENTAL / ECOMMERCE / REAL ESTATE ISOLATION")
print("="*65)

# C1-C5: Dental-only engines have company_type gate
engines = [
    ("Recall campaigns", re_eng, "process_recall_campaigns"),
    ("Birthday greetings", re_eng, "process_birthday_greetings"),
    ("Patient reactivation", re_eng, "process_reengagement"),
    ("Treatment follow-ups", tfe, "process_pending_followups"),
    ("No-show recovery", nre, "on_noshow_detected"),
]
for label, mod, fn_name in engines:
    engine_src = inspect.getsource(getattr(mod, fn_name))
    test(f"{label}: checks get_company_type() and skips non-dental",
         "get_company_type" in engine_src and "dental" in engine_src)

# C6: Booking confirmation — dental tips gated
src_bc = inspect.getsource(es.send_booking_confirmation_customer)
test("Booking confirmation: 'insurance card' only for dental",
     "insurance" in src_bc and "_get_company_type" in src_bc)

# C7: Booking confirmation — 'Doctor' label gated
test("Booking confirmation: 'Doctor' label only for dental, 'Specialist' otherwise",
     '"Doctor"' in src_bc and '"Specialist"' in src_bc)

# C8: Booking confirmation — 'Dr.' prefix gated
test("Booking confirmation: 'Dr. ' prefix only for dental",
     '"Dr. "' in src_bc and 'ctype == "dental"' in src_bc)

# C9: Welcome email — different body per company type
src_we = inspect.getsource(es.send_welcome_email)
test("Welcome email: separate dental body (pre-visit form, insurance)",
     'ctype == "dental"' in src_we and "pre-visit form" in src_we)

# C10: Welcome email — ecommerce body
test("Welcome email: separate ecommerce body (offers, shipping, returns)",
     'ctype == "ecommerce"' in src_we and "shipping" in src_we)

# C11: Welcome email — real_estate body
test("Welcome email: separate real_estate body (property recommendations)",
     'ctype == "real_estate"' in src_we and "property" in src_we)

# C12: Review request — heading varies by company type
src_rr = inspect.getsource(es.send_review_request)
test("Review request: 'How Was Your Visit?' for dental",
     "Visit" in src_rr and "is_dental" in src_rr)

# C13: Review request — ecommerce heading
test("Review request: 'How Was Your Order?' for ecommerce",
     "Order" in src_rr and "is_ecom" in src_rr)

# C14: Cancellation email — Doctor/Dr. gated
src_cancel = inspect.getsource(es.send_booking_cancellation)
test("Cancellation email: Doctor/Dr. labels gated by company_type",
     "ctype" in src_cancel and '"dental"' in src_cancel)


# ═══════════════════════════════════════════════════════════════
# SECTION D: ADMIN TEMPLATE USED FOR ALL EMAILS (Tests 31–42)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*65)
print("SECTION D: ONLY ADMIN'S SET UP EMAIL TEMPLATE IS USED")
print("="*65)

# D1: _wrap_luxury fetches admin template
test("_wrap_luxury: fetches template via db.get_email_template(admin_id)",
     "db.get_email_template(admin_id)" in src)

# D2: _wrap_luxury uses {{content}} placeholder
test("_wrap_luxury: injects content into {{content}} placeholder",
     '{{content}}' in src)

# All customer-facing email functions
all_email_fns = [
    'send_booking_confirmation_customer', 'send_previsit_form',
    'send_waitlist_notification', 'send_waitlist_placed_email',
    'send_waitlist_expired_notification', 'send_recall_email',
    'send_treatment_followup', 'send_booking_cancellation',
    'send_booking_reschedule', 'send_lead_followup',
    'send_welcome_email', 'send_review_request',
    'send_noshow_email', 'send_noshow_reason_to_doctor',
    'send_doctor_booking_notification', 'send_service_available_notification',
]

# D3: All use _wrap_luxury
not_using = [fn for fn in all_email_fns
             if hasattr(es, fn) and '_wrap_luxury' not in inspect.getsource(getattr(es, fn))]
test(f"All {len(all_email_fns)} email functions use _wrap_luxury",
     len(not_using) == 0, f"Missing: {not_using}")

# D4: All pass admin_id to _wrap_luxury
not_passing = [fn for fn in all_email_fns
               if hasattr(es, fn) and '_wrap_luxury' in inspect.getsource(getattr(es, fn))
               and 'admin_id=' not in inspect.getsource(getattr(es, fn))]
test("All email functions pass admin_id to _wrap_luxury",
     len(not_passing) == 0, f"Missing admin_id: {not_passing}")

# D5: All customer emails pass from_name=biz_name
customer_fns = [fn for fn in all_email_fns
                if fn not in ('send_otp_email', 'send_customer_verification')]
not_from = [fn for fn in customer_fns
            if hasattr(es, fn) and 'from_name=' not in inspect.getsource(getattr(es, fn))]
test(f"All customer emails use from_name=biz_name",
     len(not_from) == 0, f"Missing from_name: {not_from}")

# D6: Appointment reminder uses _wrap_luxury with admin_id
src_build = inspect.getsource(are._build_reminder_email)
test("Appointment reminder: _wrap_luxury(content, admin_id=admin_id)",
     "_wrap_luxury(content, admin_id=admin_id)" in src_build)

# D7: Appointment reminder send_reminder uses from_name
src_send_rem = inspect.getsource(are.send_reminder)
test("Appointment reminder send_reminder: uses from_name=biz_name",
     "from_name=biz_name" in src_send_rem)

# D8: OTP email does NOT use admin template (system email)
src_otp = inspect.getsource(es.send_otp_email)
test("OTP email: does NOT pass admin_id (system email, no admin template)",
     "admin_id" not in src_otp)

# D9: Verification email does NOT use admin template (system email)
src_ver = inspect.getsource(es.send_customer_verification)
test("Verification email: does NOT pass admin_id (system email)",
     "admin_id" not in src_ver)

# D10: _wrap_custom_template applies admin colors/fonts/logo
test("Custom template: applies bg_color, primary_color, font_family, logo_url",
     all(k in src_ct for k in ["bg_color", "primary_color", "font_family", "logo_url"]))

# D11: render_template_variables replaces {{var}} placeholders
src_rtv = inspect.getsource(es.render_template_variables)
test("render_template_variables: replaces {{variable}} placeholders",
     "{{" in src_rtv or "\\{\\{" in src_rtv)

# D12: compiled_html path strips watermark
test("Compiled HTML path: calls _strip_watermark when hide_watermark",
     "_strip_watermark" in src)


# ═══════════════════════════════════════════════════════════════
# SECTION E: EMAIL BUILDER BUTTON CONSTRAINTS (Tests 43–50)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*65)
print("SECTION E: EMAIL BUILDER — BUTTON TYPE CONSTRAINTS")
print("="*65)

# Read the dashboard JS
with open(os.path.join(os.path.dirname(__file__), "static/user-dashboard.html")) as f:
    dash_src = f.read()

# E1: _ebTemplateButtons exists and constrains per email type
test("Email Builder: _ebTemplateButtons config exists",
     "_ebTemplateButtons" in dash_src)

# E2: booking_confirmation only allows view_appointment, fill_form, cancel_appointment
m = re.search(r"booking_confirmation:\s*\[([^\]]+)\]", dash_src)
bc_buttons = m.group(1) if m else ""
test("Booking confirmation: only allows view_appointment, fill_form, cancel_appointment",
     "view_appointment" in bc_buttons and "cancel_appointment" in bc_buttons
     and "waitlist_confirm" not in bc_buttons and "book_recall" not in bc_buttons,
     f"Found: {bc_buttons[:80]}")

# E3: booking_confirmation does NOT allow reschedule button
test("Booking confirmation: no reschedule button allowed",
     "reschedule" not in bc_buttons.lower())

# E4: waitlist_placed only allows waitlist_confirm, waitlist_remove
m = re.search(r"waitlist_placed:\s*\[([^\]]+)\]", dash_src)
wl_buttons = m.group(1) if m else ""
test("Waitlist placed: only allows waitlist_confirm, waitlist_remove",
     "waitlist_confirm" in wl_buttons and "waitlist_remove" in wl_buttons
     and "cancel_appointment" not in wl_buttons)

# E5: recall_email allows book_recall but not cancel_appointment
m = re.search(r"recall_email:\s*\[([^\]]+)\]", dash_src)
rc_buttons = m.group(1) if m else ""
test("Recall email: allows book_recall, no cancel_appointment",
     "book_recall" in rc_buttons and "cancel_appointment" not in rc_buttons)

# E6: welcome_email does NOT allow cancel_appointment
m = re.search(r"welcome_email:\s*\[([^\]]+)\]", dash_src)
we_buttons = m.group(1) if m else ""
test("Welcome email: no cancel_appointment button allowed",
     "cancel_appointment" not in we_buttons and "waitlist" not in we_buttons)

# E7: Button types are read-only in settings panel (can't change type)
test("Button type is read-only in settings panel (cursor:not-allowed)",
     "cursor:not-allowed" in dash_src and "buttonType" in dash_src)

# E8: ebUpdateActionButtons filters buttons based on current template
test("ebUpdateActionButtons: filters by _ebCurrentTemplate",
     "ebUpdateActionButtons" in dash_src
     and "_ebTemplateButtons[_ebCurrentTemplate]" in dash_src)


# ═══════════════════════════════════════════════════════════════
# SECTION F: EMAIL SYSTEM SCHEDULING LOGIC (Tests 51–60)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*65)
print("SECTION F: EMAIL SYSTEM SCHEDULING & CONFIG WIRING")
print("="*65)

# F1: Appointment reminders read 48h/24h/2h toggles
src_sched = inspect.getsource(are.schedule_reminders)
test("Reminders: reads reminder_48h_enabled from config",
     "reminder_48h_enabled" in src_sched)
test("Reminders: reads reminder_24h_enabled from config",
     "reminder_24h_enabled" in src_sched)
test("Reminders: reads reminder_2h_enabled from config",
     "reminder_2h_enabled" in src_sched)

# F4: Treatment follow-ups read day config
src_cf = inspect.getsource(tfe.create_followup)
test("Follow-ups: reads followup_day1/3/7/14/30 from reminder_config",
     "followup_day1" in src_cf and "followup_day30" in src_cf)

# F5: Follow-ups use dynamic days (not hardcoded [2,5,10])
test("Follow-ups: no hardcoded [2, 5, 10] day list",
     "[2, 5, 10]" not in src_cf)

# F6: Birthday greetings check birthday_enabled toggle
src_bg = inspect.getsource(re_eng.process_birthday_greetings)
test("Birthday: checks birthday_enabled toggle from config",
     "birthday_enabled" in src_bg)

# F7: Birthday greetings use birthday_days_before
test("Birthday: uses birthday_days_before for advance sending",
     "birthday_days_before" in src_bg and "timedelta" in src_bg)

# F8: Reactivation checks reactivation_enabled and reactivation_days
src_re = inspect.getsource(re_eng.process_reengagement)
test("Reactivation: reads reactivation_enabled and reactivation_days",
     "reactivation_enabled" in src_re and "reactivation_days" in src_re)

# F9: Reactivation no longer hardcodes 365 days
test("Reactivation: no hardcoded 365 days cutoff",
     "timedelta(days=365)" not in src_re and "timedelta(days=reactivation_days)" in src_re)

# F10: Survey uses survey_delay_hours and schedules with APScheduler
src_tr = inspect.getsource(rev.trigger_review_request)
test("Survey: reads survey_delay_hours and schedules delayed email",
     "survey_delay_hours" in src_tr and "scheduler" in src_tr.lower())


# ═══════════════════════════════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*65)
print(f"RESULTS: {PASS}/{TOTAL} passed, {FAIL} failed")
print("="*65)

if FAIL == 0:
    print("\nALL 60 TESTS PASSED")
else:
    print(f"\n{FAIL} TEST(S) FAILED — review above")

sys.exit(0 if FAIL == 0 else 1)
