"""
ChatGenius Support Bot Engine.
A Groq-powered chatbot that answers questions about the ChatGenius platform.
When a user is logged in, it also answers questions about their account data.
Completely separate from the AI chatbot installed on users' websites.
"""
import os
import logging
from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger("support_bot")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "llama-3.1-8b-instant"

_groq_client = None


def _get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client


# ═══════════════════════════════════════════════════════════════
#  ChatGenius Platform Knowledge Base (static)
# ═══════════════════════════════════════════════════════════════

PLATFORM_KNOWLEDGE = """You are the ChatGenius Support Assistant — a helpful, friendly AI that answers questions about the ChatGenius platform.

STRICT RULES (you MUST follow ALL of these — violations are unacceptable):

1. ZERO HALLUCINATION: You must NEVER invent, fabricate, or assume any account data. If the ACCOUNT DATA section says "Count: 0" or "None yet", you MUST say exactly that. Do NOT make up example names, times, or numbers. If data says 0 bookings, say "You have no bookings today" — do NOT create fictional bookings.

2. DATA BOUNDARY: You may ONLY reference data explicitly listed in the ACCOUNT DATA section below. If something is not in the data, say "I don't have that information available — please check your dashboard."

3. SENSITIVE DATA — NEVER REVEAL:
   - Passwords, password hashes, or password reset tokens
   - Authentication tokens, session tokens, API keys, or secrets
   - Internal database IDs, SQL queries, or system internals
   - Customer credit card numbers, CVVs, bank account details, payment method details
   - Environment variables, server configuration, database connection strings
   - Webhook secrets, Stripe keys, Twilio auth tokens, or any integration credentials
   If asked for any of these, firmly refuse and explain you cannot share sensitive data.

   NON-SENSITIVE DATA (OK to share with admins):
   - Revenue, earnings, total sales, ROI metrics, plan costs
   - Booking counts, completion/no-show/cancellation rates and stats
   - Patient/customer names, emails, phones (admins manage these — this is operational data)
   - Lead counts, conversion rates, pipeline stages
   - Doctor names, schedules, specialties, performance stats
   - Service names, prices, durations
   - Analytics: peak hours, chatbot conversations, AI resolution rate
   - Invoice totals, order totals (not payment method details)
   - Integration connection status (connected/not — never the actual keys)

4. ROLE ENFORCEMENT:
   - NOT LOGGED IN: ONLY answer questions about ChatGenius platform features, pricing, plans, and setup. If they ask about account data, tell them to log in first.
   - LOGGED IN as admin/head_admin: Answer about ChatGenius AND their full account data — bookings, doctors, patients, leads, staff, services, company info, revenue, analytics, ROI, everything non-sensitive.
   - LOGGED IN as doctor: ONLY share that doctor's own data (their bookings, their schedule, their stats). REFUSE any request for other doctors' data, all patients list, all leads, staff list, or admin-level data. Say "As a doctor, I can only show your own information."

5a. COMPANY TYPE AWARENESS: The ACCOUNT DATA includes the user's company type (dental, ecommerce, real_estate, salon, etc.). You MUST tailor your language and feature references to THEIR company type ONLY:
   - DENTAL: Use terms like "patients", "doctors", "appointments", "treatments", "dental clinic"
   - E-COMMERCE: Use "customers", "orders", "products", "store", "cart recovery", "shipping"
   - REAL ESTATE: Use "clients", "agents", "listings", "showings", "properties"
   - SALON/SPA: Use "clients", "stylists", "appointments", "services", "salon"
   Do NOT mention features or terms from other company types. A dental user should never hear about "products" or "cart recovery". An e-commerce user should never hear about "doctors" or "dental treatments".
   If company type is not set, ask them to set it up first: [[nav:company-type|Choose Company Type]]

6. TONE: Concise, professional, friendly. Use bullet points for lists. Present data conversationally ("You have 3 doctors on your team" not raw data dumps).

7. OFF-TOPIC: If someone asks about anything unrelated to ChatGenius or their account, politely redirect: "I'm here to help with ChatGenius questions! Is there anything about our platform I can help with?"

8. ACTIONABLE NAVIGATION: When you tell the user to do something, ALWAYS include the direct navigation link using this exact syntax: [[nav:page-name|Button Label]]. This renders as a clickable button in the chat. Use it whenever directing users to a dashboard section. Examples:
   - "You can manage your doctors here: [[nav:doctors|Go to Doctors]]"
   - "Set up your company profile: [[nav:company|Open Company Info]]"
   You can include multiple nav links in one message. ALWAYS prefer giving a nav link over just saying "go to X".

9. PROBLEM-SOLVING FIRST: When users describe a problem, give a clear step-by-step solution with nav links. Don't just describe features — help them fix the issue. Lead with the action, not the explanation.

DASHBOARD NAVIGATION MAP (use these page names in [[nav:page-name|Label]] links):
- overview — Main dashboard overview
- bookings — Upcoming bookings/appointments
- previous-bookings — Past booking history
- waitlist — Waitlist queue management (Growth+)
- schedule-blocks — Doctor holidays & schedule blocks
- leads — Lead pipeline & contacts
- company — Company info & business profile (head admin only)
- services — Service catalog setup
- customers — Customer/patient database
- doctors — Doctor directory & profiles
- manage — Manage doctor schedules & availability
- admins — Team/admin management (head admin only)
- changes — Audit log (head admin only)
- analytics — Full analytics dashboard
- flow-builder — Visual chatbot flow builder
- demo — Try/test the chatbot
- recall — Recall & retention campaigns (Growth+)
- followups — Automated follow-up sequences
- handoffs — Live chat handoff queue
- canned-responses — Quick reply templates
- ai-performance — AI resolution metrics
- roi — ROI dashboard
- config — Feature configuration & toggles
- security — 2FA & access control settings
- proactive-config — Proactive engagement triggers (Pro+)
- email-style — Email template builder
- chatbot-customize — Chatbot widget appearance
- pms — PMS/external system integrations
- whatsapp — WhatsApp Business API setup
- instagram — Instagram DM auto-reply
- twilio-sms — Twilio SMS setup
- mailchimp — Mailchimp email marketing
- zapier — Zapier webhook automation
- calendly — Calendly scheduling sync
- google-calendar — Google Calendar sync
- profile — User profile settings
- plan — Plan & subscription management
- promotions — Promo codes & offers (e-commerce)
- products — Product catalog (e-commerce)
- orders — Order management (e-commerce)
- cart-recovery — Abandoned cart automation (e-commerce)
- staff-permissions — Staff permission management

TROUBLESHOOTING GUIDES — use these when users ask about common problems:

PROBLEM: "Chatbot not showing on my website"
SOLUTION:
1. Make sure you've copied the embed code from your dashboard [[nav:config|Open Configuration]]
2. Paste the <script> tag just before </body> on your website
3. Check that your plan supports chatbots (Free = 1, Basic = 1, Growth = 2, Pro = 3)
4. Clear your browser cache and hard-refresh the page
5. If still not working, try the demo first to verify your chatbot works [[nav:demo|Test Chatbot Demo]]

PROBLEM: "Patients/customers not getting reminders"
SOLUTION:
1. Check that email reminders are enabled in [[nav:config|Configuration]]
2. For SMS reminders (Growth+), verify Twilio is connected [[nav:twilio-sms|Twilio SMS Setup]]
3. Verify the booking has a valid email/phone for the customer
4. Check the booking status — only pending/confirmed bookings get reminders

PROBLEM: "WhatsApp not working"
SOLUTION:
1. Go to [[nav:whatsapp|WhatsApp Setup]] and verify your Business API credentials
2. Make sure your WhatsApp number is verified with Meta
3. WhatsApp requires Growth plan or higher
4. Check that the webhook URL is correctly configured in your Meta Business dashboard

PROBLEM: "Want to reduce no-shows"
SOLUTION:
1. Enable multi-stage reminders (48h + 24h + 2h) in [[nav:config|Configuration]]
2. Enable SMS reminders via [[nav:twilio-sms|Twilio SMS]] (Growth+) — SMS has higher open rates
3. Turn on no-show recovery emails in [[nav:config|Configuration]]
4. On Pro plan, enable deposit requirements to reduce casual cancellations
5. View your no-show analytics in [[nav:analytics|Analytics Dashboard]]

PROBLEM: "How to set up the chatbot"
SOLUTION:
1. First, add your company info [[nav:company|Company Info]]
2. Add your doctors/staff [[nav:doctors|Add Doctors]]
3. Set up your services [[nav:services|Service Catalog]]
4. Configure doctor schedules [[nav:manage|Doctor Schedules]]
5. Test your chatbot [[nav:demo|Try Demo]]
6. Copy the embed code from [[nav:config|Configuration]] and paste it on your website

PROBLEM: "Need to add or manage doctors"
SOLUTION:
1. Go to [[nav:doctors|Doctors]] to add new doctor profiles
2. Set their weekly schedule, breaks, and off-days in [[nav:manage|Manage Doctors]]
3. Block specific dates/holidays in [[nav:schedule-blocks|Doctor Holidays]]
4. Doctors can be invited to create their own login from [[nav:admins|Team Management]]

PROBLEM: "Lead management / converting leads"
SOLUTION:
1. View all leads in [[nav:leads|Lead Pipeline]]
2. Leads are auto-captured from chatbot conversations
3. On Growth+, auto follow-ups send 3 messages (Day 1, 3, 7) — configure in [[nav:followups|Follow-Ups]]
4. Track conversion rates in [[nav:analytics|Analytics]]
5. Export leads as CSV from the leads page

PROBLEM: "How to upgrade my plan"
SOLUTION:
1. Go to [[nav:plan|My Plan]] to see all available plans and compare features
2. Select a plan and complete checkout
3. Your new features will be available immediately after upgrade

PROBLEM: "Google Calendar sync"
SOLUTION:
1. Go to [[nav:google-calendar|Google Calendar]] to connect your Google account
2. Each doctor can sync their own calendar
3. Requires Growth plan or higher
4. Bookings will automatically appear in Google Calendar

PROBLEM: "Setting up 2FA / security"
SOLUTION:
1. Go to [[nav:security|Security Settings]] to enable two-factor authentication
2. Choose between email OTP or SMS OTP
3. On Pro plan, head admins can enforce 2FA for all staff
4. Sessions auto-expire after 8 hours of inactivity

PROBLEM: "Chatbot not answering correctly"
SOLUTION:
1. Check your FAQ/knowledge base in [[nav:config|Configuration]]
2. Add more canned responses for common questions [[nav:canned-responses|Canned Responses]]
3. On Pro plan, you can do custom AI training with your clinic-specific data
4. View AI resolution metrics in [[nav:ai-performance|AI Performance]]
5. Set up live handoff for complex questions [[nav:handoffs|Live Chat Handoffs]]

PROBLEM: "Want to customize chatbot appearance"
SOLUTION:
1. Go to [[nav:chatbot-customize|Chatbot Style]] to change colors, position, avatar
2. Growth+ plans offer 3 widget styles: Default, Pill, Glassmorphic
3. Pro+ can remove the "Powered by ChatGenius" watermark (white-label)
4. Preview changes in [[nav:demo|Try Demo]]

---

ChatGenius is a multi-tenant SaaS platform for healthcare clinics, dental practices, medical offices, salons/spas, and e-commerce businesses. It provides an AI-powered chatbot, appointment management, patient/customer engagement, and business intelligence — all accessible through a single dashboard.

PRICING PLANS:

FREE — $0/month:
- 1 chatbot widget (with "Powered by ChatGenius" branding, non-removable)
- 50 conversations/month
- Basic FAQ (5 questions): hours, location, phone
- 1 doctor profile
- Basic appointment booking (date + time only, no doctor choice)
- Email reminders only
- 1 location
- Patient database (max 20 patients)
- Basic analytics (chat count only)
- Hard limits: 20 patients, 50 chats, 1 doctor, no AI, no SMS, no custom colors

BASIC — $23/month ($18/month annually):
- Chatbot: Unlimited conversations, 1 chatbot, multi-language (3), NLU, canned responses, AI guardrails, proactive engagement (1 trigger), treatment education (15 topics)
- Booking: Smart booking (service -> date -> time), conflict detection, reschedule, cancellation, doctor schedule (weekly only), 1 appointment length
- Reminders: Email reminders (24h + 2h only), quiet hours
- Patient Mgmt: Unlimited patients, basic profiles (name, phone, email), visit history (last 3 visits)
- Lead Capture: Auto extraction from chat, basic scoring (hot/cold), hot lead alerts
- Forms: Pre-visit forms (standard fields only), in-chat rendering
- Analytics: Conversation count, booking count, basic dashboard
- Email: 3 email templates, merge variables, ChatGenius sender domain
- Doctor Portal: Today's patient list, availability on/off
- Staff: 2 roles (Admin, Doctor), 1 staff account + 1 doctor
- Live Chat: Live handoff to human, basic queue
- Customization: Colors only (3 presets), 1 widget style (Default), default avatar
- Security: AES-256, TLS 1.3, basic login

GROWTH — $79/month ($63/month annually) [MOST POPULAR]:
Everything in Basic PLUS:
- 2 chatbot widgets
- Chatbot: Multi-language (10), smart patient recognition, AI confidence scoring, sentiment analysis, upsell detection, treatment education (61 topics), before/after gallery, celebration animation
- Booking: Service-based + appointment-based booking, doctor breaks, off-days, schedule blocks, flexible lengths, daily overrides, waitlist, check-in, revenue tracking
- Reminders: SMS reminders (Twilio), 48h + 24h + 2h, one-click confirm/cancel
- No-Show: Auto-flagging, recovery email, reason collection, policy config, count tracking
- Patient: Full profiles (DOB, gender, address, language), medical history, insurance, notes, search, loyalty points
- Lead: Lead scoring with multipliers, lead revenue at risk, auto follow-ups (3-message: Day 1, 3, 7), pipeline view, export CSV, routing
- Forms: Custom form fields (10), one-time form option, digital signatures
- Treatment & Recall: Follow-up (basic), recall rules, automatic campaigns, birthday greetings, re-engagement
- Loyalty & Referral: Loyalty program (basic points), referral program (basic tracking)
- Promotions: Promo codes (10 active), basic validation
- Analytics: Full dashboard, booking analytics, conversion rate, peak hours, doctor revenue, monthly reports, lead analytics, AI resolution rate
- Surveys: Post-visit surveys, star ratings, Google review redirect
- Invoicing: Auto-generation, manual creation, line items, tax calc, email send, mark paid/void
- Email: 10 templates, WYSIWYG preview, image upload, custom styling
- Doctor Portal: Full dashboard, personal stats, specialization, profile
- Staff: 3 roles, granular permissions, 5 staff accounts
- Live Chat: Handoff queue with assignment, typing indicators, unified inbox (Web + WhatsApp)
- Integrations: Google Calendar, Calendly, Twilio SMS, Stripe, Zapier, REST API
- Customization: All widget styles (Default, Pill, Glassmorphic), custom avatar, font size, colors, calendar styling, launcher icon options
- Security: 2FA optional, audit log (90 days)
- Limits: 3 doctors, 1 location, 10 promo codes, 10 custom form fields

PRO — $299/month ($239/month annually):
Everything in Growth PLUS:
- 3 chatbot widgets
- Chatbot: Custom AI training (clinic-specific data), voice input, copilot suggestions for agents
- Booking: Booking type choice, require login (configurable), appointment API
- Reminders: High-risk patient extra reminders, patient response tracking
- No-Show: Deposit requirement, AI no-show prediction, predictive extra reminders
- Forms: Unlimited custom form fields
- Treatment: Multi-day follow-ups (configurable), treatment packages, package redemption, upsell engine, upsell tracking
- Loyalty: Customizable points per action, points redemption, loyalty analytics, referral conversion tracking
- Promotions: Unlimited active codes, treatment-specific promos, promotion analytics & ROI
- Analytics: Real-time SSE notifications, ROI dashboard, handoff analytics, survey analytics, upsell analytics, clinic benchmarking
- Surveys: Open-ended feedback, survey delay configuration, review collection tracking
- Invoicing: Multi-currency, bilingual (Arabic + English), custom logo
- Email: Own email sender domain, unlimited templates
- Staff: 4 roles (Head Admin, Admin, Doctor, Staff), 2FA enforcement, session timeout
- Live Chat: Handoff timeout escalation, conversation assignment & tagging, unified inbox (Web + WhatsApp + Facebook + Instagram)
- Integrations: Google My Business, Mailchimp, external customer database API, full webhook system
- Customization: White-label (custom domain + remove all ChatGenius branding)
- Security: Cross-tenant isolation, audit log (1 year), failed login protection
- Missed Calls: Detection, auto-reply with booking link, logging & analytics
- A/B Testing: Opening message A/B test, booking flow A/B test, custom traffic split, metric tracking
- Limits: 10 doctors, 3 locations, 15 staff

ENTERPRISE — $699/month ($559/month annually, 12-month contract, $6,708/yr):
Everything in Pro PLUS:
- Unlimited chatbot widgets
- Dedicated exclusive account manager, custom AI training (dedicated model), voice input (advanced), PMS integration (Dentrix, Open Dental, Eaglesoft), EMR/EHR integration, full appointment API, full chatbot customization, SOC 2 Type II compliance, GDPR/CCPA ready, HIPAA readiness, SLA guarantee, quarterly business reviews, priority feature requests, custom development (10 hours/quarter), executive sponsor
- No limits: Unlimited doctors, locations, staff

CORE FEATURES:

1. AI Chatbot Engine:
- Embeds on any website via a single <script> tag
- Natural language understanding for patient questions about services, pricing, availability, insurance, treatments
- Smart appointment booking: guides patients through selecting service, doctor, date, time — books directly
- Multi-language support: English, Arabic, Urdu, Tagalog, Spanish, French, Chinese — with automatic detection
- Dental/medical knowledge base with 61+ entries
- Intent classification routing to correct engine
- Treatment education, insurance/coverage calculations
- Upsell detection (suggests complementary treatments)
- Lead capture from conversations
- Before/after gallery shown during chats
- Patient recognition for returning patients
- Live handoff to human staff when AI can't help

2. Chatbot Customization (Growth+):
- Widget styles: Default, Pill, Glassmorphic
- Custom colors, position (left/right), avatar, font size, animations
- Watermark removable on Pro+

3. Appointment & Booking:
- Manual, chatbot, and API-based booking
- Statuses: pending > confirmed > checked-in > completed | cancelled | no-show
- Check-in, completion with revenue tracking, cancellation with reason
- Doctor schedule management: weekly schedule, breaks, off days, schedule blocks, recurring blocks
- Conflict detection prevents double-booking

4. Smart Waitlist (Growth+):
- Automatic waitlist when slots full
- Slot release notification via email
- Confirmation window with token-based secure links

5. Pre-Visit Forms (Basic+):
- Auto-sent after booking confirmation
- Standard fields on Basic+, custom fields on Growth+ (10), Pro+ (unlimited)
- Digital signatures on Growth+

6. Lead Management (Basic+):
- Automatic capture from chatbot conversations
- Lead scoring and manual override
- Stages: new > engaged > warm > converted
- 3-message follow-up sequences on Growth+

7. Treatment Follow-Ups (Growth+):
- Doctor-recommended follow-up sequences
- Auto-cancel when patient books

8. Patient Management:
- Auto-created profiles from bookings/forms
- Fields: name, email, phone, DOB, address, insurance, allergies, medications, history

9. Omnichannel Inbox (Growth+):
- WhatsApp on Growth+, Facebook Messenger + Instagram DM on Pro+
- Unified inbox, conversation assignment, tagging

10. SMS (Growth+ via Twilio):
- Appointment reminders, booking confirmations, no-show recovery SMS

11. Email System:
- Transactional emails for all events
- Template builder (3 on Basic, 10 on Growth, unlimited on Pro+)

12. Live Chat Handoff (Basic+):
- AI detects frustration/complex questions
- Queue with priority, context, assignment

13. Appointment Reminders:
- Multi-stage: 48h, 24h, 2h (configurable)
- Confirm/cancel via email links

14. No-Show Recovery (Growth+):
- Auto-detection, recovery email with rebooking link
- Deposit requirement on Pro+

15. Recall & Retention (Growth+):
- Treatment-based recall rules
- Auto campaigns, birthday greetings, re-engagement

16. Promotions (Growth+):
- Promo codes (percentage/fixed), 10 on Growth, unlimited on Pro+

17. Referral Program (Growth+):
- Unique codes/links, signup/conversion tracking

18. Loyalty Program (Growth+):
- Points per booking, referral, review, form submission
- Configurable redemption value

19. A/B Testing (Pro+):
- Test chatbot messages, welcome messages, booking flows

20. Upsell Engine (Pro+):
- Rule-based upsell suggestions in chatbot

21. Survey & Feedback (Growth+):
- Post-visit surveys with rating
- Google review redirect for high ratings

22. Invoice System (Growth+):
- Auto-generate from bookings, manual creation, email, multi-currency on Pro+

23. Reporting:
- Dashboard analytics, ROI dashboard, monthly performance reports, audit log

24. Real-Time Dashboard (Growth+):
- Server-sent events: new bookings, cancellations, check-ins, alerts

25. Doctor Portal:
- Schedule, bookings, today's patients, availability, stats

26. Integrations (Growth+):
- Google Calendar, Calendly, Twilio SMS, Stripe, Zapier, REST API
- Pro+: Google My Business, Mailchimp, Facebook/Instagram
- Enterprise: PMS (Dentrix, Open Dental, Eaglesoft), EMR/EHR

27. Security:
- 2FA (email OTP), role-based access, token auth, cross-tenant isolation, audit logging

28. White-Label (Pro+):
- Custom branding, custom domain, remove all ChatGenius branding

29. Gallery (Growth+):
- Before/after treatment photos, chatbot integration

30. Missed Call Handling (Pro+):
- Auto-reply with booking link, logging, stats

PLAN COMPARISON TABLE:
| Feature | Free | Basic $23 | Growth $79 | Pro $299 | Enterprise $699 |
|---|---|---|---|---|---|
| Conversations | 50 | Unlimited | Unlimited | Unlimited | Unlimited |
| Chatbots | 1 | 1 | 2 | 3 | Unlimited |
| Doctors | 1 | 1 | 3 | 10 | Unlimited |
| Locations | 1 | 1 | 1 | 3 | Unlimited |
| Languages | 1 | 3 | 10 | 10 | 10 |
| SMS | No | No | Yes | Yes | Yes |
| WhatsApp | No | No | Yes | Yes | Yes |
| Facebook/Instagram | No | No | No | Yes | Yes |
| White-label | No | No | No | Yes | Yes |
| PMS Integration | No | No | No | No | Yes |
| SOC 2/HIPAA | No | No | No | No | Yes |
| A/B Testing | No | No | No | Yes | Yes |
| API Access | No | No | Yes | Yes | Yes |
| Staff Accounts | 1 | 2 | 5 | 15 | Unlimited |
"""


# ═══════════════════════════════════════════════════════════════
#  Dynamic User Context Builder
# ═══════════════════════════════════════════════════════════════

def _rollback(conn):
    """Rollback transaction so conn stays usable after an error."""
    try:
        conn.rollback()
    except Exception:
        pass


def _safe_query(conn, sql, params=()):
    """Run a query, return result or None on error. Rolls back on failure to keep conn usable."""
    try:
        return conn.execute(sql, params)
    except Exception as e:
        logger.error(f"Query error: {e}")
        _rollback(conn)
        return None


def _count(conn, sql, params=()):
    """Run a COUNT query and return the integer. Rolls back on failure to keep conn usable."""
    try:
        row = conn.execute(sql, params).fetchone()
        return row["c"] if row else 0
    except Exception:
        _rollback(conn)
        return 0


def _fetch_one(conn, sql, params=()):
    """Run a query and return first row as dict, or None. Rolls back on failure."""
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    except Exception:
        _rollback(conn)
        return None


def _fetch_all(conn, sql, params=()):
    """Run a query and return all rows as list of dicts. Rolls back on failure."""
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        _rollback(conn)
        return []


def build_user_context(user, admin_id, role):
    """Build a non-sensitive context string about the logged-in user's account."""
    import database as db
    from datetime import timedelta

    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    week_end = (today + timedelta(days=6 - today.weekday())).strftime("%Y-%m-%d")
    month_start = today.replace(day=1).strftime("%Y-%m-%d")

    lines = []
    lines.append(f"\n---\nACCOUNT DATA (this is the ONLY data you may reference — do NOT invent or assume any data beyond this):")
    lines.append(f"User: {user.get('name', 'Unknown')}")
    lines.append(f"Role: {role}")
    plan = (user.get('plan') or 'free').lower()
    lines.append(f"Current plan: {plan.upper()}")
    lines.append(f"Today's date: {today_str}")

    # Company type
    company_type = db.get_company_type(admin_id) or ""
    type_labels = {"dental": "Dental/Healthcare", "ecommerce": "E-Commerce", "real_estate": "Real Estate", "salon": "Salon/Spa"}
    lines.append(f"Company type: {type_labels.get(company_type, company_type or 'Not set')}")
    if not company_type:
        lines.append("WARNING: Company type not set — user should configure this at [[nav:company-type|Choose Company Type]]")

    is_doctor = role == "doctor"
    is_ecommerce = company_type == "ecommerce"

    if is_doctor:
        # ── Doctor context ──
        doctor = db.get_doctor_by_user_id(user["id"])
        if not doctor:
            lines.append("[Doctor profile not linked to this account]")
            lines.append("\n--- END OF ACCOUNT DATA ---")
            return "\n".join(lines)

        lines.append(f"\n[DOCTOR PROFILE]")
        lines.append(f"Name: Dr. {doctor.get('name', '')}")
        lines.append(f"Specialty: {doctor.get('specialty', 'General')}")
        lines.append(f"Status: {doctor.get('status', 'active')}")
        doctor_id = doctor["id"]

        try:
            conn = db.get_db()

            # Today's bookings
            today_rows = _fetch_all(conn,
                "SELECT customer_name, date, time, service, status FROM bookings WHERE doctor_id=%s AND date=%s ORDER BY time",
                (doctor_id, today_str))
            lines.append(f"\n[YOUR BOOKINGS TODAY — {today_str}]")
            if today_rows:
                lines.append(f"Count: {len(today_rows)}")
                for b in today_rows:
                    lines.append(f"  - {b.get('time','?')} | {b.get('customer_name','Unknown')} | {b.get('service','Appointment')} | {b.get('status','pending')}")
            else:
                lines.append("Count: 0 — No bookings scheduled for today.")

            # Tomorrow's bookings
            tmrw_count = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE doctor_id=%s AND date=%s", (doctor_id, tomorrow_str))
            lines.append(f"[TOMORROW] Bookings: {tmrw_count}")

            # This week
            week_count = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE doctor_id=%s AND date BETWEEN %s AND %s", (doctor_id, week_start, week_end))
            lines.append(f"[THIS WEEK] Bookings: {week_count}")

            # All-time stats
            total = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE doctor_id=%s", (doctor_id,))
            completed = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE doctor_id=%s AND status='completed'", (doctor_id,))
            noshow = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE doctor_id=%s AND status='no-show'", (doctor_id,))
            cancelled = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE doctor_id=%s AND status='cancelled'", (doctor_id,))
            lines.append(f"[ALL-TIME STATS] Total: {total} | Completed: {completed} | No-shows: {noshow} | Cancelled: {cancelled}")
            if total > 0:
                noshow_rate = round(noshow / total * 100, 1)
                lines.append(f"No-show rate: {noshow_rate}%")

            # Upcoming bookings (next 5 future)
            upcoming = _fetch_all(conn,
                "SELECT customer_name, date, time, service FROM bookings WHERE doctor_id=%s AND date >= %s AND status IN ('pending','confirmed') ORDER BY date, time LIMIT 5",
                (doctor_id, today_str))
            if upcoming:
                lines.append(f"\n[UPCOMING BOOKINGS — next 5]")
                for u in upcoming:
                    lines.append(f"  - {u.get('date','?')} {u.get('time','?')} | {u.get('customer_name','?')} | {u.get('service','Appt')}")

            conn.close()
        except Exception as e:
            lines.append("[Bookings data unavailable]")
            logger.error(f"Error fetching doctor data: {e}")

    else:
        # ── Admin / Head Admin context ──
        company = db.get_company_info(admin_id)
        setup_missing = []

        if company:
            lines.append(f"\n[COMPANY INFO]")
            cname = company.get('company_name') or ''
            lines.append(f"Company name: {cname or 'Not set'}")
            ctype = company.get('company_type') or ''
            lines.append(f"Company type: {ctype or 'Not set'}")
            lines.append(f"Phone: {company.get('phone') or 'Not set'}")
            lines.append(f"Address: {company.get('address') or 'Not set'}")
            lines.append(f"Working hours: {company.get('working_hours') or 'Not set'}")
            if company.get('website'):
                lines.append(f"Website: {company['website']}")
            if not cname: setup_missing.append("company name")
            if not company.get('phone'): setup_missing.append("phone number")
            if not company.get('working_hours'): setup_missing.append("working hours")
        else:
            lines.append("\n[COMPANY INFO] Not configured yet.")
            setup_missing.append("company profile")

        plan_labels = {"free": "Free ($0)", "basic": "Basic ($23/mo)", "growth": "Growth ($79/mo)", "pro": "Pro ($299/mo)", "enterprise": "Enterprise ($699/mo)"}
        lines.append(f"Active plan: {plan_labels.get(plan, plan)}")

        try:
            conn = db.get_db()

            # ── Doctors ──
            doctors = db.get_doctors(admin_id)
            lines.append(f"\n[DOCTORS] Count: {len(doctors)}")
            if doctors:
                for doc in doctors:
                    lines.append(f"  - Dr. {doc.get('name','?')} | Specialty: {doc.get('specialty','General')} | Status: {doc.get('status','active')}")
            else:
                lines.append("  None added yet.")
                setup_missing.append("at least one doctor")

            # ── Today's bookings ──
            today_rows = _fetch_all(conn,
                "SELECT customer_name, doctor_name, date, time, service, status FROM bookings WHERE admin_id=%s AND date=%s ORDER BY time",
                (admin_id, today_str))
            lines.append(f"\n[TODAY'S BOOKINGS — {today_str}]")
            if today_rows:
                lines.append(f"Count: {len(today_rows)}")
                for b in today_rows:
                    lines.append(f"  - {b.get('time','?')} | {b.get('customer_name','Unknown')} | Dr. {b.get('doctor_name','?')} | {b.get('service','Appt')} | {b.get('status','pending')}")
            else:
                lines.append("Count: 0 — No bookings scheduled for today.")

            # ── Tomorrow ──
            tmrw_count = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND date=%s", (admin_id, tomorrow_str))
            lines.append(f"[TOMORROW] Bookings: {tmrw_count}")

            # ── This week / month ──
            week_count = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND date BETWEEN %s AND %s", (admin_id, week_start, week_end))
            month_count = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND date >= %s", (admin_id, month_start))
            lines.append(f"[THIS WEEK] Bookings: {week_count}")
            lines.append(f"[THIS MONTH] Bookings: {month_count}")

            # ── Booking stats ──
            total_bookings = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s", (admin_id,))
            pending = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND status='pending'", (admin_id,))
            confirmed = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND status='confirmed'", (admin_id,))
            completed = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND status='completed'", (admin_id,))
            noshow = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND status='no-show'", (admin_id,))
            cancelled = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND status='cancelled'", (admin_id,))
            lines.append(f"[BOOKING STATS] Total: {total_bookings} | Pending: {pending} | Confirmed: {confirmed} | Completed: {completed} | No-shows: {noshow} | Cancelled: {cancelled}")
            if total_bookings > 0:
                noshow_rate = round(noshow / total_bookings * 100, 1)
                completion_rate = round(completed / total_bookings * 100, 1)
                lines.append(f"No-show rate: {noshow_rate}% | Completion rate: {completion_rate}%")

            # ── Patients ──
            patient_count = _count(conn, "SELECT COUNT(*) as c FROM patients WHERE admin_id=%s", (admin_id,))
            lines.append(f"\n[PATIENTS] Total: {patient_count}")

            # ── Leads ──
            lead_total = _count(conn, "SELECT COUNT(*) as c FROM leads WHERE admin_id=%s", (admin_id,))
            lead_new = _count(conn, "SELECT COUNT(*) as c FROM leads WHERE admin_id=%s AND stage='new'", (admin_id,))
            lead_warm = _count(conn, "SELECT COUNT(*) as c FROM leads WHERE admin_id=%s AND stage IN ('warm','engaged')", (admin_id,))
            lead_converted = _count(conn, "SELECT COUNT(*) as c FROM leads WHERE admin_id=%s AND stage='converted'", (admin_id,))
            lead_cold = _count(conn, "SELECT COUNT(*) as c FROM leads WHERE admin_id=%s AND stage='cold'", (admin_id,))
            lines.append(f"[LEADS] Total: {lead_total} | New: {lead_new} | Warm/Engaged: {lead_warm} | Converted: {lead_converted} | Cold: {lead_cold}")
            if lead_total > 0:
                conv_rate = round(lead_converted / lead_total * 100, 1)
                lines.append(f"Lead conversion rate: {conv_rate}%")

            # ── Staff ──
            staff_rows = _fetch_all(conn,
                "SELECT name, role FROM users WHERE admin_id=%s AND id != %s", (admin_id, admin_id))
            lines.append(f"\n[STAFF MEMBERS] Count: {len(staff_rows)}")
            if staff_rows:
                for s in staff_rows:
                    lines.append(f"  - {s.get('name','?')} | Role: {s.get('role','staff')}")
            else:
                lines.append("  None added yet.")

            # ── Services ──
            svc_rows = _fetch_all(conn,
                "SELECT name, duration_minutes, price FROM company_services WHERE admin_id=%s AND is_active=1 ORDER BY name",
                (admin_id,))
            lines.append(f"\n[SERVICES] Count: {len(svc_rows)}")
            if svc_rows:
                for svc in svc_rows:
                    p = f"${svc['price']}" if svc.get('price') else "No price"
                    d = f"{svc['duration_minutes']} min" if svc.get('duration_minutes') else ""
                    lines.append(f"  - {svc.get('name','?')} | {d} | {p}")
            else:
                lines.append("  None configured yet.")
                setup_missing.append("services")

            # ── Website Visitors ──
            try:
                vstats = db.get_visitor_stats(admin_id)
                if vstats and vstats.get("all_total", 0) > 0:
                    lines.append(f"\n[WEBSITE VISITORS]")
                    lines.append(f"Today: {vstats['today_unique']} unique / {vstats['today_total']} page views")
                    lines.append(f"This week: {vstats['week_unique']} unique / {vstats['week_total']} page views")
                    lines.append(f"This month: {vstats['month_unique']} unique / {vstats['month_total']} page views")
                    lines.append(f"All-time: {vstats['all_unique']} unique / {vstats['all_total']} page views")
                    if vstats.get("top_pages"):
                        lines.append(f"Top pages (30d):")
                        for tp in vstats["top_pages"]:
                            lines.append(f"  - {tp.get('page_path','/')} — {tp['views']} views, {tp['unique_visitors']} unique")
                    if vstats.get("devices"):
                        dev_parts = [f"{d['device_type']}: {d['visits']}" for d in vstats["devices"]]
                        lines.append(f"Devices (30d): {' | '.join(dev_parts)}")
                    if vstats.get("top_referrers"):
                        ref_parts = [f"{r.get('referrer','direct')}: {r['visits']}" for r in vstats["top_referrers"][:3]]
                        lines.append(f"Top referrers: {' | '.join(ref_parts)}")
                else:
                    lines.append(f"\n[WEBSITE VISITORS] No visitor data yet. The tracking pixel is embedded in your chatbot widget — visitors will be tracked automatically on pages where the widget is installed.")
            except Exception as e:
                logger.error(f"Error fetching visitor stats: {e}")

            # ── Chatbot sessions (last 30 days) ──
            thirty_days_ago = (today - timedelta(days=30)).strftime("%Y-%m-%d")
            chat_count = _count(conn, "SELECT COUNT(*) as c FROM chat_sessions WHERE admin_id=%s AND created_at >= %s", (admin_id, thirty_days_ago))
            if chat_count > 0:
                lines.append(f"\n[CHATBOT USAGE — last 30 days] Conversations: {chat_count}")

            # ── Live chat handoffs ──
            handoff_count = _count(conn, "SELECT COUNT(*) as c FROM live_handoffs WHERE admin_id=%s AND status='active'", (admin_id,))
            if handoff_count > 0:
                lines.append(f"[LIVE CHAT] Active handoffs: {handoff_count}")

            # ── Loyalty program ──
            loy = _fetch_one(conn, "SELECT is_active FROM loyalty_config WHERE admin_id=%s", (admin_id,))
            if loy:
                lines.append(f"[LOYALTY PROGRAM] {'Active' if loy.get('is_active') else 'Inactive'}")

            # ── Revenue & ROI ──
            try:
                roi = db.get_roi_data(admin_id)
                if roi:
                    cur = roi.get("currency_symbol", "$")
                    money = roi.get("money_generated", 0)
                    cost = roi.get("total_cost", 0)
                    profit = roi.get("profit", 0)
                    roi_pct = roi.get("roi", 0)
                    lines.append(f"\n[REVENUE & ROI]")
                    lines.append(f"Total revenue generated: {cur}{money:,.2f}")
                    lines.append(f"Total ChatGenius cost: ${cost:,.2f} (USD)")
                    lines.append(f"Profit: {cur}{profit:,.2f}")
                    lines.append(f"ROI: {roi_pct}%")
                    lines.append(f"Current plan cost: ${roi.get('plan_cost', 0)}/mo")
                    tb = roi.get("total_bookings", 0)
                    if tb > 0 and money > 0:
                        lines.append(f"Avg revenue per {'order' if is_ecommerce else 'booking'}: {cur}{money/tb:,.2f}")
                    lines.append(f"Chatbot conversations (all-time): {roi.get('total_sessions', 0)}")
            except Exception as e:
                logger.error(f"Error fetching ROI: {e}")

            # ── E-commerce specific ──
            if is_ecommerce:
                total_orders = _count(conn, "SELECT COUNT(*) as c FROM ecom_orders WHERE admin_id=%s", (admin_id,))
                pending_orders = _count(conn, "SELECT COUNT(*) as c FROM ecom_orders WHERE admin_id=%s AND order_status='pending'", (admin_id,))
                processing_orders = _count(conn, "SELECT COUNT(*) as c FROM ecom_orders WHERE admin_id=%s AND order_status='processing'", (admin_id,))
                shipped_orders = _count(conn, "SELECT COUNT(*) as c FROM ecom_orders WHERE admin_id=%s AND order_status='shipped'", (admin_id,))
                delivered_orders = _count(conn, "SELECT COUNT(*) as c FROM ecom_orders WHERE admin_id=%s AND order_status='delivered'", (admin_id,))
                cancelled_orders = _count(conn, "SELECT COUNT(*) as c FROM ecom_orders WHERE admin_id=%s AND order_status IN ('cancelled','refunded')", (admin_id,))
                lines.append(f"\n[ORDERS] Total: {total_orders} | Pending: {pending_orders} | Processing: {processing_orders} | Shipped: {shipped_orders} | Delivered: {delivered_orders} | Cancelled/Refunded: {cancelled_orders}")

                recent_orders = _fetch_all(conn,
                    "SELECT order_number, customer_name, order_total, order_status FROM ecom_orders WHERE admin_id=%s ORDER BY created_at DESC LIMIT 5",
                    (admin_id,))
                if recent_orders:
                    lines.append(f"[RECENT ORDERS — last 5]")
                    for o in recent_orders:
                        lines.append(f"  - #{o.get('order_number','?')} | {o.get('customer_name','?')} | ${o.get('order_total',0)} | {o.get('order_status','?')}")

                product_count = _count(conn, "SELECT COUNT(*) as c FROM ecom_products WHERE admin_id=%s", (admin_id,))
                lines.append(f"\n[PRODUCTS] Total: {product_count}")

                abandoned = _count(conn, "SELECT COUNT(*) as c FROM abandoned_carts WHERE admin_id=%s AND recovery_status='abandoned'", (admin_id,))
                recovered = _count(conn, "SELECT COUNT(*) as c FROM abandoned_carts WHERE admin_id=%s AND recovery_status='recovered'", (admin_id,))
                if abandoned > 0 or recovered > 0:
                    lines.append(f"[CART RECOVERY] Abandoned: {abandoned} | Recovered: {recovered}")

            # ── Integration status ──
            integrations = []
            wa = _fetch_one(conn, "SELECT phone_number_id FROM whatsapp_config WHERE admin_id=%s", (admin_id,))
            if wa and wa.get("phone_number_id"):
                integrations.append("WhatsApp: Connected")
            else:
                integrations.append("WhatsApp: Not configured — set up in [[nav:whatsapp|WhatsApp Setup]]")
            tw = _fetch_one(conn, "SELECT account_sid FROM twilio_config WHERE admin_id=%s", (admin_id,))
            if tw and tw.get("account_sid"):
                integrations.append("Twilio SMS: Connected")
            else:
                integrations.append("Twilio SMS: Not configured — set up in [[nav:twilio-sms|SMS Setup]]")
            gc = _fetch_one(conn, "SELECT id FROM google_calendar_tokens WHERE admin_id=%s LIMIT 1", (admin_id,))
            if gc:
                integrations.append("Google Calendar: Connected")
            else:
                integrations.append("Google Calendar: Not connected — set up in [[nav:google-calendar|Google Calendar]]")
            lines.append(f"\n[INTEGRATIONS STATUS]")
            for intg in integrations:
                lines.append(f"  - {intg}")

            # ── Recent bookings (last 5) ──
            recent = _fetch_all(conn,
                "SELECT customer_name, doctor_name, date, time, service, status FROM bookings WHERE admin_id=%s ORDER BY created_at DESC LIMIT 5",
                (admin_id,))
            if recent:
                lines.append(f"\n[RECENT BOOKINGS — last 5]")
                for r in recent:
                    lines.append(f"  - {r.get('date','?')} {r.get('time','?')} | {r.get('customer_name','?')} | Dr. {r.get('doctor_name','?')} | {r.get('status','?')}")
            else:
                lines.append(f"\n[RECENT BOOKINGS] None yet.")

            # ── Upcoming bookings (next 5) ──
            upcoming = _fetch_all(conn,
                "SELECT customer_name, doctor_name, date, time, service FROM bookings WHERE admin_id=%s AND date >= %s AND status IN ('pending','confirmed') ORDER BY date, time LIMIT 5",
                (admin_id, today_str))
            if upcoming:
                lines.append(f"\n[UPCOMING BOOKINGS — next 5]")
                for u in upcoming:
                    lines.append(f"  - {u.get('date','?')} {u.get('time','?')} | {u.get('customer_name','?')} | Dr. {u.get('doctor_name','?')} | {u.get('service','Appt')}")

            conn.close()
        except Exception as e:
            lines.append("[Data fetch error]")
            logger.error(f"Error building admin context: {e}")

        # ── No-show / cancellation flags ──
        try:
            if total_bookings > 0 and noshow > 0 and noshow_rate > 10:
                lines.append(f"\n[ALERT] No-show rate is {noshow_rate}% — above the 10% industry average. Recommend enabling SMS reminders and multi-stage reminder sequences.")
        except NameError:
            pass

        # ── Setup checklist (with nav pages) ──
        lines.append(f"\n[SETUP CHECKLIST]")
        setup_items = []
        if "company profile" in setup_missing or "company name" in setup_missing:
            setup_items.append("Company profile incomplete — direct to [[nav:company|Set Up Company Info]]")
        if "phone number" in setup_missing:
            setup_items.append("Phone number missing — direct to [[nav:company|Add Phone Number]]")
        if "working hours" in setup_missing:
            setup_items.append("Working hours not set — direct to [[nav:company|Set Working Hours]]")
        if "at least one doctor" in setup_missing:
            setup_items.append("No doctors added yet — direct to [[nav:doctors|Add First Doctor]]")
        if "services" in setup_missing:
            setup_items.append("No services configured — direct to [[nav:services|Set Up Services]]")
        if setup_items:
            lines.append(f"Missing items ({len(setup_items)}):")
            for item in setup_items:
                lines.append(f"  - {item}")
        else:
            lines.append("All basic setup is complete.")

        # ── Plan upgrade suggestions ──
        upgrade_map = {
            "free": "You're on the Free plan. Upgrading to Basic ($23/mo) unlocks unlimited conversations, smart booking, lead capture, pre-visit forms, live chat handoff, and 3 email templates. [[nav:plan|View Plans & Upgrade]]",
            "basic": "You're on Basic. Upgrading to Growth ($79/mo) unlocks SMS reminders, waitlist, loyalty/referral, surveys, full analytics, WhatsApp, Google Calendar, Zapier, and 10 languages. [[nav:plan|View Plans & Upgrade]]",
            "growth": "You're on Growth. Upgrading to Pro ($299/mo) unlocks custom AI training, voice input, white-label, A/B testing, missed call handling, Facebook/Instagram inbox, and treatment packages. [[nav:plan|View Plans & Upgrade]]",
            "pro": "You're on Pro. Upgrading to Enterprise ($699/mo) adds PMS integration, EMR/EHR, HIPAA/SOC2, dedicated account manager, SLA guarantee, and custom development hours. [[nav:plan|View Plans & Upgrade]]",
        }
        if plan in upgrade_map:
            lines.append(f"\n[UPGRADE INFO] {upgrade_map[plan]}")

    lines.append("\n--- END OF ACCOUNT DATA ---")
    return "\n".join(lines)


def get_quick_actions(logged_in, role, plan):
    """Return contextual quick-action suggestions for the chat widget."""
    if not logged_in:
        return [
            {"label": "Compare plans", "msg": "Compare all pricing plans for me"},
            {"label": "How does the chatbot work?", "msg": "How does the ChatGenius AI chatbot work?"},
            {"label": "Free trial?", "msg": "Is there a free trial or free plan?"},
            {"label": "Setup guide", "msg": "How do I set up ChatGenius on my website step by step?"},
            {"label": "Integrations", "msg": "What integrations does ChatGenius support?"},
        ]
    if role == "doctor":
        return [
            {"label": "My bookings today", "msg": "Show me my bookings for today"},
            {"label": "This week's schedule", "msg": "How many bookings do I have this week?"},
            {"label": "My stats", "msg": "Show me my all-time booking stats and no-show rate"},
            {"label": "Upcoming appointments", "msg": "What are my upcoming appointments?"},
        ]
    # Admin/Head Admin
    actions = [
        {"label": "Today's overview", "msg": "Give me a full overview of today — bookings, leads, patients"},
        {"label": "Setup checklist", "msg": "What do I still need to set up? Show me what's missing with links to fix each item."},
        {"label": "Reduce no-shows", "msg": "How can I reduce patient no-shows? Give me steps."},
        {"label": "Chatbot not working?", "msg": "My chatbot isn't showing on my website. How do I fix it?"},
        {"label": "Lead conversion help", "msg": "How can I improve my lead conversion rate? Show me my stats and what to do."},
        {"label": "Website visitors", "msg": "How many visitors has my website had today and this month?"},
    ]
    if plan in ("free", "basic"):
        actions.append({"label": "What should I upgrade to?", "msg": "What features would I unlock if I upgrade my plan?"})
    return actions


def build_proactive_greeting(user, admin_id, role):
    """Build a smart greeting with key highlights from the user's account."""
    import database as db
    from datetime import timedelta

    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    hour = datetime.now().hour
    if hour < 12:
        time_greeting = "Good morning"
    elif hour < 17:
        time_greeting = "Good afternoon"
    else:
        time_greeting = "Good evening"

    name = user.get("name", "")
    plan = (user.get("plan") or "free").lower()
    highlights = []

    company_type = db.get_company_type(admin_id) or ""
    is_ecommerce = company_type == "ecommerce"

    try:
        conn = db.get_db()

        if role == "doctor":
            doctor = db.get_doctor_by_user_id(user["id"])
            if doctor:
                doctor_id = doctor["id"]
                today_count = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE doctor_id=%s AND date=%s", (doctor_id, today_str))
                if today_count > 0:
                    highlights.append(f"You have **{today_count} appointment{'s' if today_count != 1 else ''}** today")
                else:
                    highlights.append("No appointments scheduled for today")
                pending = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE doctor_id=%s AND date=%s AND status='pending'", (doctor_id, today_str))
                if pending > 0:
                    highlights.append(f"**{pending}** still pending confirmation")
        else:
            # Admin highlights — company-type aware
            if is_ecommerce:
                # E-commerce highlights
                try:
                    pending_orders = _count(conn, "SELECT COUNT(*) as c FROM ecom_orders WHERE admin_id=%s AND order_status='pending'", (admin_id,))
                    if pending_orders > 0:
                        highlights.append(f"**{pending_orders} pending order{'s' if pending_orders != 1 else ''}**")
                    processing = _count(conn, "SELECT COUNT(*) as c FROM ecom_orders WHERE admin_id=%s AND order_status='processing'", (admin_id,))
                    if processing > 0:
                        highlights.append(f"**{processing}** processing")
                except Exception:
                    pass
                try:
                    abandoned = _count(conn, "SELECT COUNT(*) as c FROM abandoned_carts WHERE admin_id=%s AND recovery_status='abandoned'", (admin_id,))
                    if abandoned > 0:
                        highlights.append(f"**{abandoned} abandoned cart{'s' if abandoned != 1 else ''}**")
                except Exception:
                    pass
            else:
                # Dental/Salon/etc. highlights
                today_count = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND date=%s", (admin_id, today_str))
                if today_count > 0:
                    highlights.append(f"**{today_count} appointment{'s' if today_count != 1 else ''}** today")
                else:
                    highlights.append("No appointments today")
                pending = _count(conn, "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND status='pending' AND date >= %s", (admin_id, today_str))
                if pending > 0:
                    highlights.append(f"**{pending}** pending confirmation")

            # Common admin highlights
            try:
                hot_leads = _count(conn, "SELECT COUNT(*) as c FROM leads WHERE admin_id=%s AND stage IN ('new','engaged') AND score >= 70", (admin_id,))
                if hot_leads > 0:
                    highlights.append(f"**{hot_leads} hot lead{'s' if hot_leads != 1 else ''}** waiting")
            except Exception:
                pass

            try:
                handoffs = _count(conn, "SELECT COUNT(*) as c FROM live_handoffs WHERE admin_id=%s AND status='active'", (admin_id,))
                if handoffs > 0:
                    highlights.append(f"**{handoffs} live chat{'s' if handoffs != 1 else ''}** need attention")
            except Exception:
                pass

            # Website visitor highlight
            try:
                vstats = db.get_visitor_stats(admin_id)
                if vstats and vstats.get("today_unique", 0) > 0:
                    highlights.append(f"**{vstats['today_unique']} website visitor{'s' if vstats['today_unique'] != 1 else ''}** today")
            except Exception:
                pass

        conn.close()
    except Exception as e:
        logger.error(f"Error building proactive greeting: {e}")

    greeting = f"{time_greeting}"
    if name:
        greeting += f", **{name}**"
    greeting += "!"

    if highlights:
        greeting += " Here's your snapshot: " + " · ".join(highlights) + "."
    greeting += " How can I help you?"

    return greeting


def get_follow_up_suggestions(bot_answer):
    """Analyze the bot's last answer and return contextual follow-up chip suggestions."""
    answer_lower = (bot_answer or "").lower()
    suggestions = []

    # Topic detection with follow-up suggestions
    topic_map = [
        (["booking", "appointment", "schedule"], [
            {"label": "View all bookings", "msg": "Show me all my upcoming bookings"},
            {"label": "Reduce no-shows", "msg": "How can I reduce no-shows?"},
        ]),
        (["no-show", "noshow", "no show"], [
            {"label": "Set up SMS reminders", "msg": "How do I set up SMS reminders to reduce no-shows?"},
            {"label": "Deposit requirement", "msg": "How does the deposit requirement work for no-shows?"},
        ]),
        (["lead", "conversion", "pipeline"], [
            {"label": "Set up follow-ups", "msg": "How do I set up automatic lead follow-ups?"},
            {"label": "View lead pipeline", "msg": "Show me my lead pipeline breakdown"},
        ]),
        (["doctor", "staff", "team"], [
            {"label": "Doctor schedules", "msg": "How do I manage doctor schedules and availability?"},
            {"label": "Invite staff", "msg": "How do I invite new team members?"},
        ]),
        (["whatsapp", "sms", "twilio", "instagram", "facebook"], [
            {"label": "All integrations", "msg": "What integrations are available on my plan?"},
            {"label": "Integration status", "msg": "Show me which integrations I have connected"},
        ]),
        (["plan", "upgrade", "pricing", "price"], [
            {"label": "Compare all plans", "msg": "Compare all plans side by side"},
            {"label": "What do I get?", "msg": "What specific features would I unlock if I upgrade?"},
        ]),
        (["chatbot", "widget", "embed", "script"], [
            {"label": "Test my chatbot", "msg": "How do I test my chatbot?"},
            {"label": "Customize appearance", "msg": "How do I customize the chatbot's appearance?"},
        ]),
        (["setup", "checklist", "missing", "configure"], [
            {"label": "Full setup guide", "msg": "Give me a complete step-by-step setup guide"},
            {"label": "What's missing?", "msg": "What do I still need to set up?"},
        ]),
        (["security", "2fa", "authentication", "password"], [
            {"label": "Enable 2FA", "msg": "How do I enable two-factor authentication?"},
            {"label": "Enforce for team", "msg": "Can I enforce 2FA for all my staff?"},
        ]),
        (["email", "template", "reminder"], [
            {"label": "Email templates", "msg": "How do I create and customize email templates?"},
            {"label": "Reminder settings", "msg": "How do I configure appointment reminder timing?"},
        ]),
        (["analytics", "report", "stats", "performance"], [
            {"label": "ROI dashboard", "msg": "Tell me about the ROI dashboard"},
            {"label": "AI performance", "msg": "How do I check my chatbot's AI performance metrics?"},
        ]),
        (["loyalty", "referral", "promo", "promotion"], [
            {"label": "Loyalty setup", "msg": "How do I set up the loyalty points program?"},
            {"label": "Create promo code", "msg": "How do I create a promotional code?"},
        ]),
        (["survey", "feedback", "review", "rating"], [
            {"label": "Post-visit surveys", "msg": "How do I set up post-visit surveys?"},
            {"label": "Google review redirect", "msg": "How does the Google review redirect work?"},
        ]),
        (["invoice", "billing", "payment"], [
            {"label": "Auto-generate invoices", "msg": "How do I auto-generate invoices from bookings?"},
            {"label": "Multi-currency", "msg": "Does ChatGenius support multi-currency invoicing?"},
        ]),
        (["order", "cart", "product", "store", "shipping", "ecommerce"], [
            {"label": "Order management", "msg": "How do I manage and track orders?"},
            {"label": "Cart recovery", "msg": "How does abandoned cart recovery work?"},
            {"label": "Product catalog", "msg": "How do I set up my product catalog?"},
        ]),
        (["recall", "retention", "re-engage", "birthday"], [
            {"label": "Recall campaigns", "msg": "How do I set up recall and retention campaigns?"},
            {"label": "Birthday greetings", "msg": "How do automated birthday greetings work?"},
        ]),
        (["waitlist", "slot", "queue"], [
            {"label": "Set up waitlist", "msg": "How does the smart waitlist work?"},
            {"label": "Notifications", "msg": "How are patients notified when a slot opens?"},
        ]),
        (["form", "pre-visit", "signature"], [
            {"label": "Custom form fields", "msg": "How do I add custom fields to pre-visit forms?"},
            {"label": "Digital signatures", "msg": "Does the form support digital signatures?"},
        ]),
        (["handoff", "live chat", "human"], [
            {"label": "Handoff settings", "msg": "How do I configure the live chat handoff?"},
            {"label": "Handoff queue", "msg": "Show me my current handoff queue status"},
        ]),
        (["visitor", "traffic", "page view", "website visit"], [
            {"label": "Visitor breakdown", "msg": "Show me my website visitor stats — today, this week, this month"},
            {"label": "Top pages", "msg": "What are the most visited pages on my website?"},
            {"label": "Traffic sources", "msg": "Where is my website traffic coming from?"},
        ]),
    ]

    for keywords, follow_ups in topic_map:
        if any(kw in answer_lower for kw in keywords):
            suggestions.extend(follow_ups)
            if len(suggestions) >= 3:
                break

    # Trim to max 3 unique suggestions
    seen = set()
    unique = []
    for s in suggestions:
        if s["label"] not in seen:
            seen.add(s["label"])
            unique.append(s)
        if len(unique) >= 3:
            break

    return unique


def ask_support_bot(user_message, conversation_history=None, user_context=None):
    """
    Send a question to Groq with ChatGenius context and return the answer.
    conversation_history: list of {"role": "user"|"assistant", "content": "..."} dicts
    user_context: optional string with logged-in user's account data
    """
    if not GROQ_API_KEY:
        return {"error": "Support bot is not configured. Missing API key."}

    system_content = PLATFORM_KNOWLEDGE
    if user_context:
        system_content += "\n" + user_context

    messages = [{"role": "system", "content": system_content}]
    if conversation_history:
        for msg in conversation_history[-20:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        client = _get_groq()
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=1500,
            temperature=0.5,
        )
        answer = resp.choices[0].message.content
        follow_ups = get_follow_up_suggestions(answer)
        result = {"answer": answer}
        if follow_ups:
            result["follow_ups"] = follow_ups
        return result

    except Exception as e:
        error_str = str(e)
        logger.error(f"Support bot error: {error_str}")

        # If rate limited on primary model, try fallback
        if "rate_limit" in error_str or "429" in error_str:
            try:
                logger.info(f"Retrying with fallback model {FALLBACK_MODEL}")
                resp = client.chat.completions.create(
                    model=FALLBACK_MODEL,
                    messages=messages,
                    max_tokens=1200,
                    temperature=0.5,
                )
                answer = resp.choices[0].message.content
                follow_ups = get_follow_up_suggestions(answer)
                result = {"answer": answer}
                if follow_ups:
                    result["follow_ups"] = follow_ups
                return result
            except Exception as e2:
                logger.error(f"Fallback model also failed: {e2}")

        return {"error": "Sorry, I'm having trouble right now. Please try again in a few minutes."}
