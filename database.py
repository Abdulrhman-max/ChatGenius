"""
PostgreSQL database for leads, bookings, users (admin/doctor roles), doctor requests.
"""

import psycopg2
import psycopg2.extras
import psycopg2.errors
import os
import json
import hashlib
import hmac
import secrets
import bcrypt
from datetime import datetime, timedelta

TOKEN_LIFETIME = timedelta(hours=16)  # 16 hours

# ── SQL column whitelist for dynamic queries ──
_SAFE_COLUMNS = frozenset({
    'name', 'email', 'phone', 'company', 'role', 'specialty', 'bio', 'avatar_url',
    'plan', 'auto_renew', 'status', 'notes', 'service', 'date', 'time', 'end_time',
    'doctor_name', 'patient_name', 'patient_email', 'patient_phone',
    'confirm_token', 'cancel_token', 'action',
    'stage', 'source', 'score', 'tags', 'assigned_to',
    'frequency', 'min_days_since_visit', 'message_template', 'enabled', 'channels',
    'missed_at', 'caller_phone', 'caller_name', 'followup_status', 'followup_notes',
    'first_name', 'last_name', 'date_of_birth', 'gender', 'address', 'insurance_provider',
    'insurance_id', 'medical_notes', 'preferred_doctor', 'preferred_time', 'communication_pref',
    'loyalty_enabled', 'points_per_visit', 'points_per_referral', 'points_per_dollar',
    'reward_threshold', 'reward_type', 'reward_value',
    'gmb_account_id', 'gmb_location_id', 'gmb_access_token', 'gmb_refresh_token',
    'total_patients', 'new_patients_month', 'avg_revenue_per_patient', 'no_show_rate',
    'patient_satisfaction', 'avg_wait_time', 'chair_utilization', 'treatment_acceptance',
    'primary_color', 'secondary_color', 'bg_color', 'button_color', 'button_text_color',
    'button_radius', 'font_family', 'blocks_json',
    'theme_color', 'header_bg_color', 'header_text_color', 'message_bg_color',
    'launcher_bg_color', 'launcher_icon',
    'sms_enabled', 'sms_confirm', 'sms_reminder', 'sms_followup', 'sms_noshow',
    'reminder_1_hours', 'reminder_2_hours', 'reminder_1_enabled', 'reminder_2_enabled',
    'followup_enabled', 'followup_delay_hours', 'noshow_enabled', 'noshow_delay_hours',
    'confirm_message', 'reminder_message', 'followup_message', 'noshow_message',
    'fee_amount', 'fee_type', 'grace_minutes', 'max_noshows', 'policy_text',
    'recovery_email_enabled', 'recovery_sms_enabled', 'recovery_delay_hours', 'recovery_message',
    'business_name_ar', 'vat_number', 'address_ar', 'next_invoice_number', 'auto_generate',
    'enabled', 'prefix', 'due_days', 'footer_note', 'auto_send', 'company_name',
    'company_email', 'company_phone', 'company_address', 'logo_url', 'tax_label', 'tax_rate',
    'auto_weekly', 'auto_monthly', 'email_recipients', 'include_revenue', 'include_bookings',
    'include_patients', 'include_noshow', 'include_channel',
    'description', 'price', 'sessions_included', 'validity_days', 'is_active',
    'logo_url', 'primary_color', 'domain', 'business_name', 'support_email',
    'custom_css', 'hide_branding', 'custom_login_title', 'custom_login_subtitle',
    'updated_at',
    # chatbot customization columns
    'msg_bot_bg', 'msg_bot_color', 'msg_user_bg', 'msg_user_color',
    'chatbot_bg_color', 'header_bg', 'input_bg', 'input_text_color',
    'send_btn_color', 'chatbot_title', 'msg_animation', 'celebration_enabled',
    'doctor_show_experience', 'doctor_show_languages', 'doctor_show_gender',
    'doctor_show_qualifications', 'doctor_show_category', 'calendar_style',
    'calendar_marker_color', 'launcher_bg', 'msg_font_size', 'dropdown_style',
    'admin_id', 'header_text_color', 'launcher_icon',
    'company_type',
    # email template extended fields
    'content_width', 'card_radius', 'card_shadow', 'top_bar_height',
    'line_height', 'letter_spacing', 'preheader',
    'header_html', 'body_html', 'footer_html', 'button_size',
    'header_image_url', 'footer_image_url', 'body_image_url',
    'source_type', 'compiled_html',
    # email system / reminder config extended
    'reminder_48h_enabled', 'reminder_24h_enabled', 'reminder_2h_enabled',
    'recall_interval_days', 'recall_message', 'recall_enabled',
    'followup_day1', 'followup_day3', 'followup_day7', 'followup_day14', 'followup_day30',
    'survey_delay_hours', 'survey_enabled',
    'noshow_recovery_delay_hours', 'noshow_recovery_message', 'noshow_recovery_enabled',
    'birthday_enabled', 'birthday_days_before',
    'reactivation_enabled', 'reactivation_days',
    'welcome_enabled', 'welcome_delay_minutes',
    'previsit_enabled', 'previsit_hours_before',
    # per-admin SMTP
    'smtp_host', 'smtp_port', 'smtp_user', 'smtp_password', 'smtp_from_email', 'smtp_verified',
})


def _safe_column(col):
    """Validate a column name against the whitelist. Raises ValueError if not allowed."""
    col = col.strip()
    if col not in _SAFE_COLUMNS:
        raise ValueError(f"Invalid column name: {col}")
    return col


# ── Failed login tracking (in-memory) ──
_failed_logins = {}  # {email: {"count": int, "locked_until": datetime}}
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'port': os.environ.get('DB_PORT', '5433'),
    'database': os.environ.get('DB_NAME', 'chatgenius'),
    'user': os.environ.get('DB_USER', 'chatgenius_admin'),
    'password': os.environ.get('DB_PASSWORD', 'ChatGenius2026'),
}


class PgConnection:
    """Wrapper around psycopg2 connection to provide sqlite3-compatible API."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        cur = self._conn.cursor()
        cur.execute(sql, params or ())
        return cur

    def executescript(self, sql):
        old_autocommit = self._conn.autocommit
        self._conn.autocommit = True
        cur = self._conn.cursor()
        cur.execute(sql)
        self._conn.autocommit = old_autocommit
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def cursor(self):
        return self._conn.cursor()

    @property
    def autocommit(self):
        return self._conn.autocommit

    @autocommit.setter
    def autocommit(self, val):
        self._conn.autocommit = val


def get_db():
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=psycopg2.extras.RealDictCursor)
    return PgConnection(conn)


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS leads (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            source TEXT DEFAULT 'chatbot',
            notes TEXT DEFAULT '',
            admin_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id SERIAL PRIMARY KEY,
            customer_name TEXT NOT NULL,
            customer_email TEXT DEFAULT '',
            customer_phone TEXT DEFAULT '',
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            service TEXT DEFAULT 'General Consultation',
            status TEXT DEFAULT 'confirmed',
            calendar_event_id TEXT DEFAULT '',
            doctor_id INTEGER DEFAULT 0,
            doctor_name TEXT DEFAULT '',
            admin_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT DEFAULT '',
            company TEXT DEFAULT '',
            role TEXT DEFAULT 'admin',
            plan TEXT DEFAULT 'free_trial',
            provider TEXT DEFAULT 'email',
            provider_id TEXT DEFAULT '',
            avatar_url TEXT DEFAULT '',
            admin_id INTEGER DEFAULT 0,
            token TEXT DEFAULT '',
            token_expires_at TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_verified INTEGER DEFAULT 1,
            verification_code TEXT DEFAULT '',
            verification_code_expires TIMESTAMP DEFAULT NULL,
            company_type TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS company_info (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL,
            business_name TEXT DEFAULT '',
            address TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            business_hours TEXT DEFAULT '',
            services TEXT DEFAULT '',
            pricing_insurance TEXT DEFAULT '',
            emergency_info TEXT DEFAULT '',
            about TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS doctors (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            user_id INTEGER DEFAULT 0,
            name TEXT NOT NULL,
            email TEXT DEFAULT '',
            specialty TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            availability TEXT DEFAULT 'Mon-Fri',
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS doctor_breaks (
            id SERIAL PRIMARY KEY,
            doctor_id INTEGER NOT NULL,
            break_name TEXT DEFAULT 'Break',
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            day_of_week TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS doctor_off_days (
            id SERIAL PRIMARY KEY,
            doctor_id INTEGER NOT NULL,
            off_date TEXT NOT NULL,
            reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS doctor_requests (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            admin_name TEXT DEFAULT '',
            business_name TEXT DEFAULT '',
            doctor_email TEXT NOT NULL,
            doctor_user_id INTEGER DEFAULT 0,
            doctor_record_id INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS admin_requests (
            id SERIAL PRIMARY KEY,
            head_admin_id INTEGER NOT NULL,
            head_admin_name TEXT DEFAULT '',
            business_name TEXT DEFAULT '',
            admin_email TEXT NOT NULL,
            admin_user_id INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS staff_permissions (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            staff_user_id INTEGER NOT NULL,
            permission_key TEXT NOT NULL,
            enabled INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(admin_id, staff_user_id, permission_key)
        );

        CREATE TABLE IF NOT EXISTS chat_logs (
            id SERIAL PRIMARY KEY,
            session_id TEXT NOT NULL,
            admin_id INTEGER DEFAULT 0,
            message TEXT NOT NULL,
            intent TEXT DEFAULT '',
            intent_confidence REAL DEFAULT 0,
            resulted_in_booking INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Checkout Sessions (for PayPal payment verification)
        CREATE TABLE IF NOT EXISTS checkout_sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            transaction_id TEXT DEFAULT '',
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            activated_at TIMESTAMP DEFAULT NULL
        );

        -- Admin Audit Log
        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            user_name TEXT DEFAULT '',
            user_email TEXT DEFAULT '',
            action TEXT NOT NULL,
            details TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 1: Smart Waitlist
        CREATE TABLE IF NOT EXISTS waitlist (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            doctor_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            time_slot TEXT NOT NULL,
            patient_name TEXT NOT NULL,
            patient_email TEXT DEFAULT '',
            patient_phone TEXT DEFAULT '',
            position INTEGER DEFAULT 0,
            status TEXT DEFAULT 'waiting',
            notified_at TIMESTAMP DEFAULT NULL,
            confirm_deadline TIMESTAMP DEFAULT NULL,
            confirmed_at TIMESTAMP DEFAULT NULL,
            expired_at TIMESTAMP DEFAULT NULL,
            session_id TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 2: Digital Patient Forms
        CREATE TABLE IF NOT EXISTS patient_forms (
            id SERIAL PRIMARY KEY,
            booking_id INTEGER NOT NULL,
            admin_id INTEGER DEFAULT 0,
            token TEXT UNIQUE NOT NULL,
            full_name TEXT DEFAULT '',
            date_of_birth TEXT DEFAULT '',
            gender TEXT DEFAULT '',
            medical_history TEXT DEFAULT '',
            medications TEXT DEFAULT '',
            allergies TEXT DEFAULT '',
            insurance_provider TEXT DEFAULT '',
            insurance_policy TEXT DEFAULT '',
            signature_data TEXT DEFAULT '',
            submitted_at TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 3: Recall & Retention
        CREATE TABLE IF NOT EXISTS recall_rules (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            treatment_type TEXT NOT NULL,
            recall_days INTEGER NOT NULL DEFAULT 180,
            message_template TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS recall_campaigns (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            rule_id INTEGER DEFAULT 0,
            patient_name TEXT NOT NULL,
            patient_email TEXT DEFAULT '',
            patient_phone TEXT DEFAULT '',
            recall_type TEXT DEFAULT 'appointment',
            status TEXT DEFAULT 'pending',
            sent_at TIMESTAMP DEFAULT NULL,
            opened_at TIMESTAMP DEFAULT NULL,
            booked_at TIMESTAMP DEFAULT NULL,
            booking_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 4: Missed Call Auto-Reply
        CREATE TABLE IF NOT EXISTS missed_calls (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            caller_number TEXT NOT NULL,
            call_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reply_sent INTEGER DEFAULT 0,
            reply_method TEXT DEFAULT '',
            subsequently_booked INTEGER DEFAULT 0,
            booking_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 5: Treatment Plan Follow-Up
        CREATE TABLE IF NOT EXISTS treatment_followups (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            doctor_id INTEGER DEFAULT 0,
            patient_name TEXT NOT NULL,
            patient_email TEXT DEFAULT '',
            patient_phone TEXT DEFAULT '',
            treatment_name TEXT NOT NULL,
            recommended_date TEXT DEFAULT '',
            followup_day INTEGER NOT NULL DEFAULT 2,
            status TEXT DEFAULT 'pending',
            sent_at TIMESTAMP DEFAULT NULL,
            booked_at TIMESTAMP DEFAULT NULL,
            cancelled_at TIMESTAMP DEFAULT NULL,
            booking_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 7: Before & After Gallery
        CREATE TABLE IF NOT EXISTS gallery (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            treatment_type TEXT NOT NULL,
            image_url TEXT NOT NULL,
            image_type TEXT DEFAULT 'after',
            pair_id TEXT DEFAULT '',
            caption TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 10: Live Chat Handoff
        CREATE TABLE IF NOT EXISTS live_chat_handoffs (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            patient_name TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            status TEXT DEFAULT 'queued',
            staff_user_id INTEGER DEFAULT 0,
            staff_name TEXT DEFAULT '',
            assigned_at TIMESTAMP DEFAULT NULL,
            resolved_at TIMESTAMP DEFAULT NULL,
            resolution_notes TEXT DEFAULT '',
            ai_confidence REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 11: Block & Holiday Scheduling (rebuilt)
        CREATE TABLE IF NOT EXISTS schedule_blocks (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            doctor_id INTEGER DEFAULT NULL,
            block_type TEXT DEFAULT 'single_date',
            start_date TEXT NOT NULL DEFAULT '',
            end_date TEXT DEFAULT '',
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            recurring_pattern TEXT DEFAULT '',
            recurring_day INTEGER DEFAULT NULL,
            label TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 12: Promotions & Discount Engine
        CREATE TABLE IF NOT EXISTS promotions (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            discount_type TEXT DEFAULT 'percentage',
            discount_value REAL DEFAULT 0,
            applicable_treatments TEXT DEFAULT 'all',
            expiry_date TEXT DEFAULT '',
            max_uses INTEGER DEFAULT 0,
            current_uses INTEGER DEFAULT 0,
            min_booking_value REAL DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS promotion_usage (
            id SERIAL PRIMARY KEY,
            promotion_id INTEGER NOT NULL,
            booking_id INTEGER DEFAULT 0,
            patient_name TEXT DEFAULT '',
            patient_email TEXT DEFAULT '',
            discount_amount REAL DEFAULT 0,
            original_amount REAL DEFAULT 0,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 14: Referral System
        CREATE TABLE IF NOT EXISTS referrals (
            id SERIAL PRIMARY KEY,
            referrer_admin_id INTEGER NOT NULL,
            referred_email TEXT NOT NULL,
            referred_admin_id INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'pending',
            reward_type TEXT DEFAULT 'percentage',
            reward_value REAL DEFAULT 10,
            reward_applied INTEGER DEFAULT 0,
            converted_at TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 15: Patient Profile
        CREATE TABLE IF NOT EXISTS patients (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            date_of_birth TEXT DEFAULT '',
            gender TEXT DEFAULT '',
            language TEXT DEFAULT 'en',
            loyalty_points INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            last_visit_date TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS patient_notes (
            id SERIAL PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            doctor_id INTEGER DEFAULT 0,
            booking_id INTEGER DEFAULT 0,
            note TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 17: A/B Testing
        CREATE TABLE IF NOT EXISTS ab_tests (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            test_name TEXT NOT NULL,
            test_type TEXT DEFAULT 'opening_message',
            variant_a TEXT NOT NULL,
            variant_b TEXT NOT NULL,
            variant_a_conversations INTEGER DEFAULT 0,
            variant_a_bookings INTEGER DEFAULT 0,
            variant_b_conversations INTEGER DEFAULT 0,
            variant_b_bookings INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running',
            winner TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 18: Loyalty Program
        CREATE TABLE IF NOT EXISTS loyalty_config (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE NOT NULL,
            points_per_appointment INTEGER DEFAULT 100,
            points_per_referral INTEGER DEFAULT 200,
            points_per_review INTEGER DEFAULT 50,
            points_per_form INTEGER DEFAULT 25,
            redemption_value REAL DEFAULT 0.01,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS loyalty_transactions (
            id SERIAL PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,
            points INTEGER NOT NULL,
            action TEXT NOT NULL,
            description TEXT DEFAULT '',
            booking_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 19: GMB Integration
        CREATE TABLE IF NOT EXISTS gmb_connections (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE NOT NULL,
            google_account_id TEXT DEFAULT '',
            location_id TEXT DEFAULT '',
            access_token TEXT DEFAULT '',
            refresh_token TEXT DEFAULT '',
            rating REAL DEFAULT 0,
            review_count INTEGER DEFAULT 0,
            last_synced_at TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Google Calendar OAuth settings (per admin/company)
        CREATE TABLE IF NOT EXISTS gcal_settings (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE NOT NULL,
            gcal_client_id TEXT DEFAULT '',
            gcal_client_secret TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 20: Competitor Benchmarking
        CREATE TABLE IF NOT EXISTS clinic_metrics_cache (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE NOT NULL,
            conversion_rate REAL DEFAULT 0,
            noshow_rate REAL DEFAULT 0,
            avg_response_time REAL DEFAULT 0,
            monthly_bookings INTEGER DEFAULT 0,
            review_score REAL DEFAULT 0,
            city TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- SaaS Customers (clinics/businesses that subscribe to the chatbot platform)
        CREATE TABLE IF NOT EXISTS customers (
            id SERIAL PRIMARY KEY,
            business_name TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT DEFAULT '',
            website TEXT DEFAULT '',
            country TEXT DEFAULT '',
            city TEXT DEFAULT '',
            address TEXT DEFAULT '',
            industry TEXT DEFAULT 'dental',
            logo_url TEXT DEFAULT '',
            -- Subscription & billing
            plan TEXT DEFAULT 'free_trial',
            plan_started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            plan_expires_at TIMESTAMP DEFAULT NULL,
            billing_cycle TEXT DEFAULT 'monthly',
            paypal_customer_id TEXT DEFAULT '',
            paypal_subscription_id TEXT DEFAULT '',
            -- Verification & status
            is_verified INTEGER DEFAULT 0,
            verified_at TIMESTAMP DEFAULT NULL,
            verification_token TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            -- API & integration
            api_key TEXT UNIQUE DEFAULT '',
            api_secret TEXT DEFAULT '',
            webhook_url TEXT DEFAULT '',
            allowed_domains TEXT DEFAULT '',
            -- Chatbot config
            chatbot_name TEXT DEFAULT 'AI Assistant',
            chatbot_color TEXT DEFAULT '#2563eb',
            chatbot_position TEXT DEFAULT 'bottom-right',
            chatbot_language TEXT DEFAULT 'en',
            chatbot_welcome_msg TEXT DEFAULT 'Hello! How can I help you today%s',
            -- Limits
            max_admins INTEGER DEFAULT 3,
            max_doctors INTEGER DEFAULT 10,
            max_monthly_chats INTEGER DEFAULT 1000,
            max_bookings INTEGER DEFAULT 500,
            -- Linking to existing users system
            head_admin_user_id INTEGER DEFAULT 0,
            -- Timestamps
            last_active_at TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Customer usage tracking
        CREATE TABLE IF NOT EXISTS customer_usage (
            id SERIAL PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            total_chats INTEGER DEFAULT 0,
            total_bookings INTEGER DEFAULT 0,
            total_leads INTEGER DEFAULT 0,
            total_api_calls INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Customer invoices
        CREATE TABLE IF NOT EXISTS customer_invoices (
            id SERIAL PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            invoice_number TEXT UNIQUE NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            currency TEXT DEFAULT 'USD',
            status TEXT DEFAULT 'pending',
            paypal_invoice_id TEXT DEFAULT '',
            period_start TEXT DEFAULT '',
            period_end TEXT DEFAULT '',
            paid_at TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Smart Appointment Reminders
        CREATE TABLE IF NOT EXISTS appointment_reminders (
            id SERIAL PRIMARY KEY,
            booking_id INTEGER,
            admin_id INTEGER DEFAULT 0,
            reminder_type TEXT DEFAULT '48h',
            channel TEXT DEFAULT 'email',
            scheduled_for TEXT,
            sent_at TEXT,
            status TEXT DEFAULT 'pending',
            patient_response TEXT DEFAULT 'none',
            responded_at TEXT,
            job_id TEXT,
            confirm_token TEXT DEFAULT '',
            cancel_token TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reminder_config (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE,
            reminder_48h_enabled INTEGER DEFAULT 1,
            reminder_24h_enabled INTEGER DEFAULT 1,
            reminder_2h_enabled INTEGER DEFAULT 1,
            hours_before_first INTEGER DEFAULT 48,
            hours_before_second INTEGER DEFAULT 24,
            hours_before_third INTEGER DEFAULT 2,
            quiet_hours_start INTEGER DEFAULT 23,
            quiet_hours_end INTEGER DEFAULT 8,
            high_risk_enabled INTEGER DEFAULT 1,
            high_risk_threshold INTEGER DEFAULT 4,
            recall_interval_days INTEGER DEFAULT 180,
            recall_message TEXT DEFAULT '',
            recall_enabled INTEGER DEFAULT 1,
            followup_day1 INTEGER DEFAULT 1,
            followup_day3 INTEGER DEFAULT 1,
            followup_day7 INTEGER DEFAULT 1,
            followup_day14 INTEGER DEFAULT 0,
            followup_day30 INTEGER DEFAULT 0,
            survey_delay_hours INTEGER DEFAULT 24,
            survey_enabled INTEGER DEFAULT 1,
            noshow_recovery_delay_hours INTEGER DEFAULT 2,
            noshow_recovery_message TEXT DEFAULT '',
            noshow_recovery_enabled INTEGER DEFAULT 1,
            birthday_enabled INTEGER DEFAULT 0,
            birthday_days_before INTEGER DEFAULT 1,
            reactivation_enabled INTEGER DEFAULT 0,
            reactivation_days INTEGER DEFAULT 90,
            welcome_enabled INTEGER DEFAULT 1,
            welcome_delay_minutes INTEGER DEFAULT 0,
            previsit_enabled INTEGER DEFAULT 1,
            previsit_hours_before INTEGER DEFAULT 24,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature: Patient Satisfaction Surveys
        CREATE TABLE IF NOT EXISTS surveys (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER DEFAULT 0,
            booking_id INTEGER,
            patient_id INTEGER,
            doctor_id INTEGER,
            token TEXT UNIQUE,
            star_rating INTEGER,
            feedback_text TEXT DEFAULT '',
            treatment_type TEXT DEFAULT '',
            sent_at TEXT,
            completed_at TEXT,
            google_review_clicked INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS survey_config (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE,
            auto_send_enabled INTEGER DEFAULT 1,
            send_delay_hours INTEGER DEFAULT 2,
            google_review_url TEXT DEFAULT '',
            min_rating_for_review INTEGER DEFAULT 4,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature: Treatment Packages
        CREATE TABLE IF NOT EXISTS treatment_packages (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER DEFAULT 0,
            name TEXT,
            description TEXT,
            treatments_json TEXT,
            package_price REAL,
            individual_total REAL,
            savings REAL,
            validity_days INTEGER DEFAULT 90,
            max_redemptions INTEGER DEFAULT 0,
            current_redemptions INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS package_redemptions (
            id SERIAL PRIMARY KEY,
            package_id INTEGER,
            patient_id INTEGER,
            booking_id INTEGER,
            treatment_name TEXT,
            redeemed_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature: Smart Upsell
        CREATE TABLE IF NOT EXISTS upsell_rules (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER DEFAULT 0,
            trigger_treatment TEXT,
            suggested_treatment TEXT,
            suggested_package_id INTEGER,
            message_template TEXT,
            discount_percent REAL DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS upsell_impressions (
            id SERIAL PRIMARY KEY,
            upsell_rule_id INTEGER,
            session_id TEXT,
            shown_at TEXT DEFAULT CURRENT_TIMESTAMP,
            accepted INTEGER DEFAULT 0,
            booking_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- No-Show Recovery Engine
        CREATE TABLE IF NOT EXISTS noshow_recovery (
            id SERIAL PRIMARY KEY,
            booking_id INTEGER,
            patient_id INTEGER,
            admin_id INTEGER DEFAULT 0,
            recovery_status TEXT DEFAULT 'pending',
            reschedule_token TEXT,
            cancel_token TEXT,
            message_sent_at TEXT,
            responded_at TEXT,
            new_booking_id INTEGER,
            noshow_count INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS noshow_policy (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE,
            max_noshows_before_deposit INTEGER DEFAULT 2,
            deposit_amount REAL DEFAULT 50,
            recovery_delay_minutes INTEGER DEFAULT 15,
            auto_recovery_enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Invoice Engine
        CREATE TABLE IF NOT EXISTS invoices (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER DEFAULT 0,
            booking_id INTEGER,
            patient_id INTEGER,
            invoice_number TEXT UNIQUE,
            items_json TEXT,
            subtotal REAL DEFAULT 0,
            tax_rate REAL DEFAULT 15,
            tax_amount REAL DEFAULT 0,
            total REAL DEFAULT 0,
            currency TEXT DEFAULT 'SAR',
            payment_method TEXT DEFAULT '',
            payment_status TEXT DEFAULT 'pending',
            paid_at TEXT,
            voided_at TEXT,
            void_reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS invoice_config (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE,
            business_name TEXT DEFAULT '',
            business_name_ar TEXT DEFAULT '',
            vat_number TEXT DEFAULT '',
            address TEXT DEFAULT '',
            address_ar TEXT DEFAULT '',
            logo_url TEXT DEFAULT '',
            next_invoice_number INTEGER DEFAULT 1,
            auto_generate INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Monthly Performance Report Engine
        CREATE TABLE IF NOT EXISTS performance_reports (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER,
            month INTEGER,
            year INTEGER,
            report_data_json TEXT,
            generated_at TEXT,
            emailed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(admin_id, month, year)
        );

        CREATE TABLE IF NOT EXISTS report_config (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE,
            auto_generate INTEGER DEFAULT 1,
            send_day_of_month INTEGER DEFAULT 1,
            recipients_json TEXT DEFAULT '[]',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Multi-Channel Unified Inbox
        CREATE TABLE IF NOT EXISTS channel_conversations (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER DEFAULT 0,
            channel_type TEXT DEFAULT 'web',
            external_id TEXT DEFAULT '',
            sender_name TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            last_message_at TEXT,
            unread_count INTEGER DEFAULT 0,
            assigned_to INTEGER DEFAULT 0,
            tags TEXT DEFAULT '',
            status TEXT DEFAULT 'open',
            resolved_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS channel_messages (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER DEFAULT 0,
            conversation_id INTEGER,
            direction TEXT DEFAULT 'inbound',
            sender_name TEXT DEFAULT '',
            message_text TEXT DEFAULT '',
            message_type TEXT DEFAULT 'text',
            media_url TEXT DEFAULT '',
            external_message_id TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature Configuration (toggles for emails, auto-features, etc.)
        CREATE TABLE IF NOT EXISTS feature_config (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            feature_key TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(admin_id, feature_key)
        );

        CREATE TABLE IF NOT EXISTS form_config (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            send_form_after_booking INTEGER DEFAULT 1,
            one_time_form INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(admin_id)
        );

        CREATE TABLE IF NOT EXISTS form_fields_config (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            field_key TEXT NOT NULL,
            enabled INTEGER DEFAULT 0,
            required INTEGER DEFAULT 1,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(admin_id, field_key)
        );

        CREATE TABLE IF NOT EXISTS form_custom_fields (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            field_type TEXT DEFAULT 'text',
            required INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Chatbot Customization
        CREATE TABLE IF NOT EXISTS chatbot_customization (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE NOT NULL,
            dropdown_style TEXT DEFAULT 'default',
            msg_font_size INTEGER DEFAULT 13,
            msg_bot_bg TEXT DEFAULT '',
            msg_bot_color TEXT DEFAULT '',
            msg_user_bg TEXT DEFAULT '',
            msg_user_color TEXT DEFAULT '',
            chatbot_bg_color TEXT DEFAULT '',
            header_bg TEXT DEFAULT '',
            header_text_color TEXT DEFAULT '',
            input_bg TEXT DEFAULT '',
            input_text_color TEXT DEFAULT '',
            send_btn_color TEXT DEFAULT '',
            chatbot_title TEXT DEFAULT '',
            msg_animation TEXT DEFAULT 'slide_up',
            celebration_enabled INTEGER DEFAULT 0,
            doctor_show_experience INTEGER DEFAULT 0,
            doctor_show_languages INTEGER DEFAULT 0,
            doctor_show_gender INTEGER DEFAULT 0,
            doctor_show_qualifications INTEGER DEFAULT 0,
            doctor_show_category INTEGER DEFAULT 0,
            calendar_style TEXT DEFAULT 'default',
            calendar_marker_color TEXT DEFAULT '#f87171',
            launcher_bg TEXT DEFAULT '',
            launcher_icon TEXT DEFAULT 'chat',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Active chatbot domains — tracks which domains have the chatbot embedded
        CREATE TABLE IF NOT EXISTS chatbot_active_domains (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            domain TEXT NOT NULL,
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            UNIQUE(admin_id, domain)
        );

        -- Twilio SMS Configuration
        CREATE TABLE IF NOT EXISTS twilio_config (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE,
            account_sid TEXT DEFAULT '',
            auth_token TEXT DEFAULT '',
            phone_number TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- WhatsApp Business API Configuration
        CREATE TABLE IF NOT EXISTS whatsapp_config (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE,
            access_token TEXT DEFAULT '',
            phone_number_id TEXT DEFAULT '',
            verify_token TEXT DEFAULT '',
            business_account_id TEXT DEFAULT '',
            connected INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Instagram Integration Configuration
        CREATE TABLE IF NOT EXISTS instagram_config (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE NOT NULL,
            page_access_token TEXT NOT NULL,
            instagram_account_id TEXT NOT NULL DEFAULT '',
            page_id TEXT NOT NULL DEFAULT '',
            verify_token TEXT NOT NULL DEFAULT '',
            connected INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- SMS Log
        CREATE TABLE IF NOT EXISTS sms_log (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            to_number TEXT NOT NULL,
            message TEXT DEFAULT '',
            status TEXT DEFAULT 'sent',
            twilio_sid TEXT DEFAULT '',
            error TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- White-Label Configuration
        CREATE TABLE IF NOT EXISTS whitelabel_config (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE,
            custom_domain TEXT DEFAULT '',
            domain_verified INTEGER DEFAULT 0,
            brand_name TEXT DEFAULT '',
            logo_url TEXT DEFAULT '',
            favicon_url TEXT DEFAULT '',
            primary_color TEXT DEFAULT '#2563eb',
            secondary_color TEXT DEFAULT '#1e40af',
            font_family TEXT DEFAULT '',
            custom_css TEXT DEFAULT '',
            email_from_name TEXT DEFAULT '',
            email_from_address TEXT DEFAULT '',
            hide_powered_by INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Mailchimp Email Marketing Integration
        CREATE TABLE IF NOT EXISTS mailchimp_connections (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER UNIQUE NOT NULL,
            api_key TEXT DEFAULT '',
            account_name TEXT DEFAULT '',
            datacenter TEXT DEFAULT '',
            list_id TEXT DEFAULT '',
            auto_sync INTEGER DEFAULT 0,
            total_synced INTEGER DEFAULT 0,
            last_synced_at TIMESTAMP DEFAULT NULL,
            connected_at TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Migration: add new columns to existing tables
    migrations = [
        ("users", "role", "TEXT DEFAULT 'admin'"),
        ("users", "admin_id", "INTEGER DEFAULT 0"),
        ("users", "token_expires_at", "TIMESTAMP DEFAULT NULL"),
        ("bookings", "doctor_id", "INTEGER DEFAULT 0"),
        ("bookings", "doctor_name", "TEXT DEFAULT ''"),
        ("bookings", "admin_id", "INTEGER DEFAULT 0"),
        ("leads", "admin_id", "INTEGER DEFAULT 0"),
        ("doctors", "admin_id", "INTEGER DEFAULT 0"),
        ("doctors", "user_id", "INTEGER DEFAULT 0"),
        ("doctors", "email", "TEXT DEFAULT ''"),
        ("doctors", "status", "TEXT DEFAULT 'pending'"),
        ("users", "specialty", "TEXT DEFAULT ''"),
        ("doctors", "start_time", "TEXT DEFAULT '00:00 AM'"),
        ("doctors", "end_time", "TEXT DEFAULT '00:00 AM'"),
        ("doctors", "is_active", "INTEGER DEFAULT 1"),
        ("doctors", "appointment_length", "INTEGER DEFAULT 60"),
        ("doctors", "phone", "TEXT DEFAULT ''"),
        ("doctors", "qualifications", "TEXT DEFAULT ''"),
        ("doctors", "languages", "TEXT DEFAULT ''"),
        ("doctors", "years_of_experience", "INTEGER DEFAULT 0"),
        ("doctors", "pdf_filename", "TEXT DEFAULT ''"),
        ("doctors", "schedule_type", "TEXT DEFAULT 'fixed'"),
        ("doctors", "daily_hours", "TEXT DEFAULT ''"),
        # Feature 2: link forms to bookings
        ("bookings", "form_token", "TEXT DEFAULT ''"),
        ("bookings", "form_submitted", "INTEGER DEFAULT 0"),
        # Feature 6: Multilingual
        ("chat_logs", "language", "TEXT DEFAULT 'en'"),
        # Feature 10: Live Chat
        ("chat_logs", "is_human_handled", "INTEGER DEFAULT 0"),
        ("chat_logs", "handler_user_id", "INTEGER DEFAULT 0"),
        ("chat_logs", "sender", "TEXT DEFAULT 'user'"),
        # Feature 13: 2FA
        ("users", "totp_secret", "TEXT DEFAULT ''"),
        ("users", "two_fa_enabled", "INTEGER DEFAULT 0"),
        ("users", "two_fa_method", "TEXT DEFAULT 'email'"),
        ("users", "last_activity_at", "TIMESTAMP DEFAULT NULL"),
        # Feature 14: Referral
        ("users", "referral_code", "TEXT DEFAULT ''"),
        ("users", "referred_by", "TEXT DEFAULT ''"),
        # Feature 15: Patient Profile
        ("bookings", "patient_id", "INTEGER DEFAULT 0"),
        ("bookings", "outcome", "TEXT DEFAULT ''"),
        ("bookings", "treatment_type", "TEXT DEFAULT ''"),
        # Feature 16: Real-time dashboard
        ("bookings", "checked_in", "INTEGER DEFAULT 0"),
        ("bookings", "checked_in_at", "TIMESTAMP DEFAULT NULL"),
        # Promotion code applied to booking (empty string = none)
        ("bookings", "promotion_code", "TEXT DEFAULT ''"),
        # Feature 4: Missed calls
        ("company_info", "missed_call_enabled", "INTEGER DEFAULT 0"),
        ("company_info", "clinic_phone", "TEXT DEFAULT ''"),
        # Feature 10: Live chat threshold
        ("company_info", "handoff_threshold", "REAL DEFAULT 0.3"),
        # Feature 11: Schedule blocks
        ("company_info", "blocked_dates", "TEXT DEFAULT ''"),
        # Feature 11 rebuild: new schedule_blocks columns
        ("schedule_blocks", "block_type", "TEXT DEFAULT 'single_date'"),
        ("schedule_blocks", "start_date", "TEXT NOT NULL DEFAULT ''"),
        ("schedule_blocks", "end_date", "TEXT DEFAULT ''"),
        ("schedule_blocks", "recurring_pattern", "TEXT DEFAULT ''"),
        ("schedule_blocks", "recurring_day", "INTEGER DEFAULT NULL"),
        ("schedule_blocks", "is_active", "INTEGER DEFAULT 1"),
        # Customer linking
        ("users", "customer_id", "INTEGER DEFAULT 0"),
        # Patient profile — medical & booking history
        ("patients", "medical_history", "TEXT DEFAULT ''"),
        ("patients", "medications", "TEXT DEFAULT ''"),
        ("patients", "allergies", "TEXT DEFAULT ''"),
        ("patients", "insurance_provider", "TEXT DEFAULT ''"),
        ("patients", "insurance_policy", "TEXT DEFAULT ''"),
        ("patients", "total_bookings", "INTEGER DEFAULT 0"),
        ("patients", "total_completed", "INTEGER DEFAULT 0"),
        ("patients", "total_cancelled", "INTEGER DEFAULT 0"),
        ("patients", "total_no_shows", "INTEGER DEFAULT 0"),
        ("patients", "conditions", "TEXT DEFAULT ''"),
        ("patients", "last_treatment", "TEXT DEFAULT ''"),
        # Feature 1: Waitlist — expired_at column
        ("waitlist", "expired_at", "TIMESTAMP DEFAULT NULL"),
        # Feature 2: Patient Forms — signature_data column (replaces consent_signature)
        ("patient_forms", "signature_data", "TEXT DEFAULT ''"),
        # Feature 17: A/B Testing — completed_at column
        ("ab_tests", "completed_at", "TIMESTAMP DEFAULT NULL"),
        # Doctor Portal — emergency availability & status message
        ("doctors", "emergency_available", "INTEGER DEFAULT 0"),
        ("doctors", "status_message", "TEXT DEFAULT ''"),
        # Waitlist-to-booking linkage
        ("bookings", "waitlist_id", "INTEGER DEFAULT 0"),
        # Customer API integration — fetch customers from external database
        ("company_info", "customers_api_url", "TEXT DEFAULT ''"),
        ("company_info", "customers_api_key", "TEXT DEFAULT ''"),
        ("company_info", "currency", "TEXT DEFAULT 'USD'"),
        ("company_info", "logo_url", "TEXT DEFAULT ''"),
        ("company_info", "store_image", "TEXT DEFAULT ''"),
        ("company_info", "domain", "TEXT DEFAULT ''"),
        # Public GUID for embed code (never expose numeric IDs)
        ("users", "public_id", "TEXT DEFAULT ''"),
        # Service-doctor mapping + description
        ("company_services", "description", "TEXT DEFAULT ''"),
        # Service enhancements
        ("company_services", "category", "TEXT DEFAULT ''"),
        ("company_services", "duration_minutes", "INTEGER DEFAULT 60"),
        ("company_services", "preparation_instructions", "TEXT DEFAULT ''"),
        ("company_services", "is_active", "INTEGER DEFAULT 1"),
        # Doctor enhancements
        ("doctors", "gender", "TEXT DEFAULT ''"),
        ("doctors", "photo_url", "TEXT DEFAULT ''"),
        # Booking enhancements for service flow
        ("bookings", "notes", "TEXT DEFAULT ''"),
        ("bookings", "patient_type", "TEXT DEFAULT ''"),
        ("bookings", "service_id", "INTEGER DEFAULT 0"),
        # Lead management enrichment
        ("leads", "email", "TEXT DEFAULT ''"),
        ("leads", "stage", "TEXT DEFAULT 'new'"),
        ("leads", "score", "INTEGER DEFAULT 0"),
        ("leads", "treatment_interest", "TEXT DEFAULT ''"),
        ("leads", "is_returning", "INTEGER DEFAULT 0"),
        ("leads", "preferred_time", "TEXT DEFAULT ''"),
        ("leads", "capture_trigger", "TEXT DEFAULT 'manual'"),
        ("leads", "session_id", "TEXT DEFAULT ''"),
        ("leads", "temperature", "TEXT DEFAULT 'cold'"),
        ("leads", "last_activity_at", "TIMESTAMP DEFAULT NULL"),
        ("leads", "converted_at", "TIMESTAMP DEFAULT NULL"),
        ("leads", "converted_booking_id", "INTEGER DEFAULT 0"),
        ("leads", "last_action", "TEXT DEFAULT ''"),
        ("leads", "last_action_at", "TIMESTAMP DEFAULT NULL"),
        ("leads", "budget", "TEXT DEFAULT ''"),
        ("leads", "score_breakdown", "TEXT DEFAULT ''"),
        ("leads", "cart_data", "TEXT DEFAULT ''"),
        ("leads", "multipliers", "TEXT DEFAULT ''"),
        ("leads", "revenue_at_risk", "NUMERIC DEFAULT 0"),
        ("lead_email_queue", "retry_count", "INTEGER DEFAULT 0"),
        ("doctor_breaks", "day_of_week", "TEXT DEFAULT ''"),
        # ROI: average appointment price per doctor
        ("doctors", "avg_appointment_price", "REAL DEFAULT 20.0"),
        ("doctors", "avg_appointment_currency", "TEXT DEFAULT 'USD'"),
        # ROI: revenue amount tracked per booking
        ("bookings", "revenue_amount", "REAL DEFAULT 0"),
        ("bookings", "cancelled_at", "TIMESTAMP DEFAULT NULL"),
        # External API key for PMS / external booking integrations
        ("company_info", "external_api_key", "TEXT DEFAULT ''"),
        # Waitlist email action tokens
        ("waitlist", "confirm_token", "TEXT DEFAULT ''"),
        ("waitlist", "remove_token", "TEXT DEFAULT ''"),
        # Booking cancel token for email links
        ("bookings", "cancel_token", "TEXT DEFAULT ''"),
        # Subscription management
        ("users", "plan_started_at", "TIMESTAMP DEFAULT NULL"),
        ("users", "plan_expires_at", "TIMESTAMP DEFAULT NULL"),
        ("users", "billing_cycle", "TEXT DEFAULT 'monthly'"),
        ("users", "auto_renew", "INTEGER DEFAULT 1"),
        ("users", "pending_plan", "TEXT DEFAULT ''"),
        # Recall booking tokens
        ("recall_campaigns", "recall_token", "TEXT DEFAULT ''"),
        ("recall_campaigns", "service_name", "TEXT DEFAULT ''"),
        ("recall_campaigns", "doctor_name", "TEXT DEFAULT ''"),
        # Followup booking tokens
        ("treatment_followups", "followup_token", "TEXT DEFAULT ''"),
        ("users", "is_verified", "INTEGER DEFAULT 1"),
        ("users", "verification_code", "TEXT DEFAULT ''"),
        ("users", "verification_code_expires", "TIMESTAMP DEFAULT NULL"),
        ("reminder_config", "high_risk_enabled", "INTEGER DEFAULT 1"),
        ("reminder_config", "high_risk_threshold", "INTEGER DEFAULT 4"),
        ("reminder_config", "recall_interval_days", "INTEGER DEFAULT 180"),
        ("reminder_config", "recall_message", "TEXT DEFAULT ''"),
        ("reminder_config", "recall_enabled", "INTEGER DEFAULT 1"),
        ("reminder_config", "followup_day1", "INTEGER DEFAULT 1"),
        ("reminder_config", "followup_day3", "INTEGER DEFAULT 1"),
        ("reminder_config", "followup_day7", "INTEGER DEFAULT 1"),
        ("reminder_config", "followup_day14", "INTEGER DEFAULT 0"),
        ("reminder_config", "followup_day30", "INTEGER DEFAULT 0"),
        ("reminder_config", "survey_delay_hours", "INTEGER DEFAULT 24"),
        ("reminder_config", "survey_enabled", "INTEGER DEFAULT 1"),
        ("reminder_config", "noshow_recovery_delay_hours", "INTEGER DEFAULT 2"),
        ("reminder_config", "noshow_recovery_message", "TEXT DEFAULT ''"),
        ("reminder_config", "noshow_recovery_enabled", "INTEGER DEFAULT 1"),
        ("reminder_config", "birthday_enabled", "INTEGER DEFAULT 0"),
        ("reminder_config", "birthday_days_before", "INTEGER DEFAULT 1"),
        ("reminder_config", "reactivation_enabled", "INTEGER DEFAULT 0"),
        ("reminder_config", "reactivation_days", "INTEGER DEFAULT 90"),
        ("reminder_config", "welcome_enabled", "INTEGER DEFAULT 1"),
        ("reminder_config", "welcome_delay_minutes", "INTEGER DEFAULT 0"),
        ("reminder_config", "previsit_enabled", "INTEGER DEFAULT 1"),
        ("reminder_config", "previsit_hours_before", "INTEGER DEFAULT 24"),
        # Legacy column (kept for backward compatibility)
        ("users", "paypal_plan_status", "TEXT DEFAULT ''"),
        # Google Calendar integration (per-doctor OAuth)
        ("doctors", "gcal_refresh_token", "TEXT DEFAULT ''"),
        ("doctors", "gcal_calendar_id", "TEXT DEFAULT ''"),
        ("bookings", "gcal_event_id", "TEXT DEFAULT ''"),
        # PayPal Subscriptions
        ("users", "paypal_subscription_id", "TEXT DEFAULT ''"),
        # Enhanced Handoff: typing indicator
        ("live_chat_handoffs", "typing_at", "TIMESTAMP DEFAULT NULL"),
        # Multi-industry support
        ("users", "company_type", "TEXT DEFAULT ''"),
        # Per-admin SMTP configuration (send emails from their own domain)
        ("company_info", "smtp_host", "TEXT DEFAULT ''"),
        ("company_info", "smtp_port", "INTEGER DEFAULT 587"),
        ("company_info", "smtp_user", "TEXT DEFAULT ''"),
        ("company_info", "smtp_password", "TEXT DEFAULT ''"),
        ("company_info", "smtp_from_email", "TEXT DEFAULT ''"),
        ("company_info", "smtp_verified", "INTEGER DEFAULT 0"),
    ]
    for table, col, col_type in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            conn.commit()
        except Exception:
            conn.rollback()

    # Migrate leads.score from INTEGER to REAL for advanced lead scoring
    try:
        conn.execute("ALTER TABLE leads ALTER COLUMN score TYPE REAL")
        conn.commit()
    except Exception:
        conn.rollback()

    # Backfill external_api_key for existing companies that don't have one
    companies_without_key = conn.execute("SELECT id FROM company_info WHERE external_api_key IS NULL OR external_api_key = ''").fetchall()
    for c in companies_without_key:
        conn.execute("UPDATE company_info SET external_api_key = %s WHERE id = %s", (secrets.token_hex(32), c["id"]))
    if companies_without_key:
        conn.commit()

    # Backfill public_id for existing users that don't have one
    import uuid as _uuid
    users_without_pid = conn.execute("SELECT id FROM users WHERE public_id IS NULL OR public_id = ''").fetchall()
    for u in users_without_pid:
        conn.execute("UPDATE users SET public_id = %s WHERE id = %s", (str(_uuid.uuid4()), u["id"]))
    if users_without_pid:
        conn.commit()

    # Feature 17: A/B Testing — session assignment tracking
    conn.execute("""CREATE TABLE IF NOT EXISTS ab_assignments (
        id SERIAL PRIMARY KEY,
        test_id INTEGER,
        session_id TEXT,
        variant TEXT,
        converted INTEGER DEFAULT 0,
        created_at TEXT
    )""")
    conn.commit()

    # Service-doctor mapping (which doctors perform which services)
    conn.execute("""CREATE TABLE IF NOT EXISTS service_doctors (
        id SERIAL PRIMARY KEY,
        service_id INTEGER NOT NULL,
        doctor_id INTEGER NOT NULL,
        admin_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(service_id, doctor_id)
    )""")
    conn.commit()

    # Service interest notifications — when user wants a service with no doctors yet
    conn.execute("""CREATE TABLE IF NOT EXISTS service_interests (
        id SERIAL PRIMARY KEY,
        service_id INTEGER NOT NULL,
        service_name TEXT NOT NULL,
        patient_name TEXT DEFAULT '',
        patient_email TEXT DEFAULT '',
        patient_phone TEXT DEFAULT '',
        admin_id INTEGER NOT NULL,
        status TEXT DEFAULT 'waiting',
        notified_at TIMESTAMP DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # Lead follow-up sequences
    conn.execute("""CREATE TABLE IF NOT EXISTS lead_followups (
        id SERIAL PRIMARY KEY,
        lead_id INTEGER NOT NULL,
        admin_id INTEGER NOT NULL,
        day_number INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        scheduled_at TIMESTAMP NOT NULL,
        sent_at TIMESTAMP DEFAULT NULL,
        cancelled_at TIMESTAMP DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS hot_lead_alerts (
        id SERIAL PRIMARY KEY,
        lead_id INTEGER NOT NULL,
        admin_id INTEGER NOT NULL,
        lead_name TEXT DEFAULT '',
        score REAL DEFAULT 0,
        temperature TEXT DEFAULT '',
        product_interest TEXT DEFAULT '',
        seen INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS lead_email_queue (
        id SERIAL PRIMARY KEY,
        lead_id INTEGER NOT NULL,
        admin_id INTEGER NOT NULL,
        send_at TIMESTAMP NOT NULL,
        status TEXT DEFAULT 'pending',
        sent_at TIMESTAMP DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # Plan history — track plan changes for ROI cost calculation
    conn.execute("""CREATE TABLE IF NOT EXISTS plan_history (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        plan TEXT NOT NULL,
        monthly_cost REAL NOT NULL DEFAULT 0,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # Calendly Integration
    conn.execute("""CREATE TABLE IF NOT EXISTS calendly_connections (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        api_token TEXT DEFAULT '',
        user_uri TEXT DEFAULT '',
        user_name TEXT DEFAULT '',
        user_email TEXT DEFAULT '',
        organization_uri TEXT DEFAULT '',
        webhook_uri TEXT DEFAULT '',
        connected INTEGER DEFAULT 0,
        calendly_mode TEXT DEFAULT 'single',
        last_synced_at TIMESTAMP DEFAULT NULL,
        last_synced_event TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # Add calendly_mode column if missing (migration for existing DBs)
    try:
        conn.execute("ALTER TABLE calendly_connections ADD COLUMN calendly_mode TEXT DEFAULT 'single'")
        conn.commit()
    except Exception:
        conn.rollback()

    conn.execute("""CREATE TABLE IF NOT EXISTS calendly_event_mappings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        event_type_uri TEXT NOT NULL,
        event_type_name TEXT DEFAULT '',
        doctor_id INTEGER DEFAULT 0,
        service_name TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # Per-doctor Calendly connections (for "multiple" mode)
    conn.execute("""CREATE TABLE IF NOT EXISTS calendly_doctor_connections (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        doctor_id INTEGER NOT NULL,
        api_token TEXT DEFAULT '',
        user_uri TEXT DEFAULT '',
        user_name TEXT DEFAULT '',
        user_email TEXT DEFAULT '',
        organization_uri TEXT DEFAULT '',
        webhook_uri TEXT DEFAULT '',
        connected INTEGER DEFAULT 0,
        last_synced_at TIMESTAMP DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(admin_id, doctor_id)
    )""")
    conn.commit()

    # EMR/EHR Integration Requests
    conn.execute("""CREATE TABLE IF NOT EXISTS integration_requests (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER DEFAULT 0,
        integration_name TEXT NOT NULL,
        status TEXT DEFAULT 'requested',
        contact_email TEXT DEFAULT '',
        practice_size TEXT DEFAULT '',
        current_system TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # EMR/EHR Integration Configurations
    conn.execute("""CREATE TABLE IF NOT EXISTS emr_integrations (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        integration_type TEXT NOT NULL,
        api_endpoint TEXT DEFAULT '',
        api_key_encrypted TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        last_sync TIMESTAMP DEFAULT NULL,
        sync_enabled BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS pms_sync_log (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        pms_type TEXT NOT NULL,
        booking_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        error_message TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # Proactive engagement configuration
    conn.execute("""CREATE TABLE IF NOT EXISTS proactive_config (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        enabled INTEGER DEFAULT 1,
        dwell_time_seconds INTEGER DEFAULT 30,
        scroll_depth_percent INTEGER DEFAULT 60,
        exit_intent_enabled INTEGER DEFAULT 1,
        trigger_message TEXT DEFAULT '',
        trigger_pages TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # Chatbot Flow Builder
    conn.execute("""CREATE TABLE IF NOT EXISTS chatbot_flows (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        description TEXT DEFAULT '',
        flow_data JSONB DEFAULT '{}',
        is_active BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # Canned Responses for Live Chat Handoff
    conn.execute("""CREATE TABLE IF NOT EXISTS canned_responses (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL DEFAULT '',
        category TEXT DEFAULT 'Custom',
        shortcut TEXT DEFAULT '',
        usage_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # Partner applications table
    conn.execute("""CREATE TABLE IF NOT EXISTS partner_applications (
        id SERIAL PRIMARY KEY,
        agency_name TEXT NOT NULL,
        contact_name TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT DEFAULT '',
        website TEXT DEFAULT '',
        client_count INTEGER DEFAULT 0,
        referral_source TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # Seed default categories for admin_id=0 (global defaults)
    DEFAULT_CATEGORIES = [
        "General Dentist", "Pediatric Dentist", "Orthodontist", "Endodontist",
        "Periodontist", "Oral & Maxillofacial Surgeon", "Prosthodontist",
        "Oral Pathologist", "Oral Radiologist", "Dental Anesthesiologist",
        "Orofacial Pain Specialist", "Dental Public Health Specialist",
        "Cosmetic Dentist", "Family Dentist"
    ]
    existing_defaults = conn.execute("SELECT COUNT(*) AS cnt FROM categories WHERE admin_id = 0").fetchone()['cnt']
    if existing_defaults == 0:
        for cat in DEFAULT_CATEGORIES:
            conn.execute("INSERT INTO categories (admin_id, name) VALUES (0, %s)", (cat,))
        conn.commit()

    # Mobile app interest signups
    conn.execute("""CREATE TABLE IF NOT EXISTS mobile_app_interest (
        id SERIAL PRIMARY KEY,
        email TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # ── E-commerce Tables ──

    conn.execute("""CREATE TABLE IF NOT EXISTS store_settings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        store_name TEXT DEFAULT '',
        store_logo TEXT DEFAULT '',
        brand_primary_color TEXT DEFAULT '#000000',
        brand_secondary_color TEXT DEFAULT '',
        store_timezone TEXT DEFAULT 'UTC',
        store_currency TEXT DEFAULT 'USD',
        currency_format TEXT DEFAULT 'symbol_before',
        default_language TEXT DEFAULT 'en',
        supported_languages TEXT DEFAULT '',
        store_contact_email TEXT DEFAULT '',
        store_contact_phone TEXT DEFAULT '',
        store_address TEXT DEFAULT '',
        business_hours TEXT DEFAULT '',
        chatbot_name TEXT DEFAULT '',
        chatbot_avatar TEXT DEFAULT '',
        chatbot_tone TEXT DEFAULT 'friendly',
        welcome_message TEXT DEFAULT '',
        offline_message TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # Migration: add missing store_settings columns
    for col, default in [
        ("store_url", "TEXT DEFAULT ''"),
        ("default_shipping_rate", "DECIMAL(10,2) DEFAULT 0"),
        ("return_policy", "TEXT DEFAULT ''"),
        ("shipping_zones", "TEXT DEFAULT ''"),
        ("payment_methods", "TEXT DEFAULT ''"),
        ("tax_rate", "DECIMAL(5,2) DEFAULT 0"),
        ("free_shipping_threshold", "DECIMAL(10,2) DEFAULT 0"),
        ("ecommerce_type", "TEXT DEFAULT ''"),
        ("brand_voice", "TEXT DEFAULT 'casual'"),
        ("bot_name", "TEXT DEFAULT 'Sales Assistant'"),
        ("target_audience", "TEXT DEFAULT ''"),
        ("cart_add_url", "TEXT DEFAULT ''"),
        ("bundle_enabled", "BOOLEAN DEFAULT FALSE"),
        ("bundle_min_items", "INTEGER DEFAULT 3"),
        ("bundle_discount_pct", "DECIMAL(5,2) DEFAULT 10"),
        ("cart_integration_mode", "TEXT DEFAULT 'product_link'"),
        ("cart_integration_done", "BOOLEAN DEFAULT FALSE"),
    ]:
        try:
            conn.execute(f"ALTER TABLE store_settings ADD COLUMN IF NOT EXISTS {col} {default}")
            conn.commit()
        except Exception:
            pass

    conn.execute("""CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        product_id TEXT DEFAULT '',
        product_name TEXT NOT NULL,
        product_description TEXT DEFAULT '',
        product_short_description TEXT DEFAULT '',
        product_images TEXT DEFAULT '[]',
        product_price DECIMAL(10,2) DEFAULT 0,
        compare_at_price DECIMAL(10,2) DEFAULT 0,
        cost_price DECIMAL(10,2) DEFAULT 0,
        product_status TEXT DEFAULT 'active',
        inventory_quantity INTEGER DEFAULT 0,
        inventory_policy TEXT DEFAULT 'deny',
        low_stock_threshold INTEGER DEFAULT 5,
        backorder_status TEXT DEFAULT 'no',
        product_category TEXT DEFAULT '',
        product_subcategory TEXT DEFAULT '',
        product_tags TEXT DEFAULT '',
        product_weight DECIMAL(10,2) DEFAULT 0,
        product_dimensions TEXT DEFAULT '',
        product_material TEXT DEFAULT '',
        product_brand TEXT DEFAULT '',
        product_rating DECIMAL(3,2) DEFAULT 0,
        product_review_count INTEGER DEFAULT 0,
        product_barcode TEXT DEFAULT '',
        product_url TEXT DEFAULT '',
        product_highlights TEXT DEFAULT '',
        product_benefits TEXT DEFAULT '',
        target_customer TEXT DEFAULT '',
        product_specs TEXT DEFAULT '[]',
        use_cases TEXT DEFAULT '',
        sale_start_date TEXT DEFAULT '',
        sale_end_date TEXT DEFAULT '',
        related_complementary TEXT DEFAULT '[]',
        related_similar TEXT DEFAULT '[]',
        search_keywords TEXT DEFAULT '',
        ships_free BOOLEAN DEFAULT FALSE,
        shipping_class TEXT DEFAULT 'standard',
        return_eligibility TEXT DEFAULT 'standard',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # Migrate existing products tables
    for col, default in [
        ("product_url", "TEXT DEFAULT ''"),
        ("product_highlights", "TEXT DEFAULT ''"),
        ("product_benefits", "TEXT DEFAULT ''"),
        ("target_customer", "TEXT DEFAULT ''"),
        ("product_specs", "TEXT DEFAULT '[]'"),
        ("use_cases", "TEXT DEFAULT ''"),
        ("sale_start_date", "TEXT DEFAULT ''"),
        ("sale_end_date", "TEXT DEFAULT ''"),
        ("related_complementary", "TEXT DEFAULT '[]'"),
        ("related_similar", "TEXT DEFAULT '[]'"),
        ("search_keywords", "TEXT DEFAULT ''"),
        ("ships_free", "BOOLEAN DEFAULT FALSE"),
        ("shipping_class", "TEXT DEFAULT 'standard'"),
        ("return_eligibility", "TEXT DEFAULT 'standard'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE products ADD COLUMN IF NOT EXISTS {col} {default}")
        except Exception:
            pass
    conn.commit()

    # Backfill auto product_id for products missing one
    try:
        conn.execute("UPDATE products SET product_id = 'PROD-' || id WHERE product_id IS NULL OR product_id = ''")
        conn.commit()
    except Exception:
        pass

    conn.execute("""CREATE TABLE IF NOT EXISTS product_variants (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        variant_name TEXT DEFAULT '',
        option_1_name TEXT DEFAULT '',
        option_1_value TEXT DEFAULT '',
        option_2_name TEXT DEFAULT '',
        option_2_value TEXT DEFAULT '',
        option_3_name TEXT DEFAULT '',
        option_3_value TEXT DEFAULT '',
        variant_price DECIMAL(10,2) DEFAULT 0,
        variant_sku TEXT DEFAULT '',
        variant_inventory_qty INTEGER DEFAULT 0,
        variant_barcode TEXT DEFAULT '',
        variant_image TEXT DEFAULT '',
        variant_weight DECIMAL(10,2) DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS cart_recovery_settings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        cart_recovery_enabled INTEGER DEFAULT 0,
        exit_intent_trigger INTEGER DEFAULT 1,
        exit_intent_delay INTEGER DEFAULT 0,
        scroll_up_trigger INTEGER DEFAULT 0,
        time_on_page_trigger INTEGER DEFAULT 0,
        cart_value_minimum DECIMAL(10,2) DEFAULT 0,
        cart_value_maximum DECIMAL(10,2) DEFAULT 0,
        mobile_swipe_up_trigger INTEGER DEFAULT 0,
        tab_switch_trigger INTEGER DEFAULT 0,
        recovery_message_1 TEXT DEFAULT '',
        recovery_message_1_delay INTEGER DEFAULT 0,
        recovery_message_2 TEXT DEFAULT '',
        recovery_message_2_delay INTEGER DEFAULT 60,
        recovery_message_3 TEXT DEFAULT '',
        recovery_message_3_delay INTEGER DEFAULT 180,
        discount_enabled INTEGER DEFAULT 0,
        discount_type TEXT DEFAULT 'percentage',
        discount_value DECIMAL(10,2) DEFAULT 0,
        discount_minimum_cart_value DECIMAL(10,2) DEFAULT 0,
        discount_maximum_cap DECIMAL(10,2) DEFAULT 0,
        discount_code_prefix TEXT DEFAULT 'CHAT',
        single_use_codes INTEGER DEFAULT 1,
        urgency_timer_enabled INTEGER DEFAULT 0,
        urgency_timer_duration INTEGER DEFAULT 30,
        email_followup_enabled INTEGER DEFAULT 0,
        email_1_timing INTEGER DEFAULT 1,
        email_1_template TEXT DEFAULT '',
        email_2_timing INTEGER DEFAULT 24,
        email_2_template TEXT DEFAULT '',
        email_3_timing INTEGER DEFAULT 72,
        email_3_template TEXT DEFAULT '',
        sms_followup_enabled INTEGER DEFAULT 0,
        sms_timing INTEGER DEFAULT 4,
        sms_template TEXT DEFAULT '',
        whatsapp_enabled INTEGER DEFAULT 0,
        whatsapp_timing INTEGER DEFAULT 6,
        whatsapp_template TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS recommendation_settings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        recommendations_enabled INTEGER DEFAULT 1,
        recommendation_engine TEXT DEFAULT 'hybrid',
        cross_sell_enabled INTEGER DEFAULT 0,
        cross_sell_rules TEXT DEFAULT '{}',
        upsell_enabled INTEGER DEFAULT 0,
        upsell_rules TEXT DEFAULT '{}',
        bundle_recommendations INTEGER DEFAULT 0,
        bundle_rules TEXT DEFAULT '{}',
        trending_products_enabled INTEGER DEFAULT 0,
        recently_viewed_enabled INTEGER DEFAULT 0,
        purchase_based_enabled INTEGER DEFAULT 0,
        max_recommendations_in_chat INTEGER DEFAULT 4,
        recommendation_card_style TEXT DEFAULT 'detailed',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS order_shipping_settings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        order_status_integration INTEGER DEFAULT 0,
        supported_carriers TEXT DEFAULT '[]',
        tracking_url_format TEXT DEFAULT '',
        shipping_zones TEXT DEFAULT '{}',
        free_shipping_threshold DECIMAL(10,2) DEFAULT 0,
        free_shipping_message TEXT DEFAULT '',
        express_shipping_option INTEGER DEFAULT 0,
        express_shipping_cost DECIMAL(10,2) DEFAULT 0,
        local_delivery_enabled INTEGER DEFAULT 0,
        local_delivery_radius INTEGER DEFAULT 0,
        bopis_enabled INTEGER DEFAULT 0,
        bopis_locations TEXT DEFAULT '[]',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS return_settings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        return_policy_enabled INTEGER DEFAULT 1,
        return_window_days INTEGER DEFAULT 30,
        return_eligibility_rules TEXT DEFAULT '',
        exchange_enabled INTEGER DEFAULT 1,
        exchange_window_days INTEGER DEFAULT 45,
        return_label_auto_generate INTEGER DEFAULT 0,
        return_label_provider TEXT DEFAULT '',
        refund_method TEXT DEFAULT 'original_payment',
        refund_timeline TEXT DEFAULT '3-5 business days',
        restocking_fee_percentage DECIMAL(5,2) DEFAULT 0,
        final_sale_items TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS shipping_zones (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        zone_name TEXT NOT NULL DEFAULT '',
        countries TEXT NOT NULL DEFAULT '[]',
        shipping_fee DECIMAL(10,2) DEFAULT 0,
        free_shipping_threshold DECIMAL(10,2) DEFAULT 0,
        estimated_days TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS store_discounts (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        discount_name TEXT NOT NULL DEFAULT '',
        discount_code TEXT NOT NULL DEFAULT '',
        discount_type TEXT DEFAULT 'percentage',
        discount_value DECIMAL(10,2) DEFAULT 0,
        applies_to TEXT DEFAULT 'all',
        product_ids TEXT DEFAULT '[]',
        category_names TEXT DEFAULT '[]',
        min_order_amount DECIMAL(10,2) DEFAULT 0,
        min_quantity INTEGER DEFAULT 0,
        start_date TEXT DEFAULT '',
        end_date TEXT DEFAULT '',
        max_uses INTEGER DEFAULT 0,
        current_uses INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS ecom_orders (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        order_number TEXT NOT NULL,
        customer_name TEXT DEFAULT '',
        customer_email TEXT DEFAULT '',
        customer_phone TEXT DEFAULT '',
        order_status TEXT DEFAULT 'pending',
        order_total DECIMAL(10,2) DEFAULT 0,
        subtotal DECIMAL(10,2) DEFAULT 0,
        tax_amount DECIMAL(10,2) DEFAULT 0,
        shipping_cost DECIMAL(10,2) DEFAULT 0,
        discount_amount DECIMAL(10,2) DEFAULT 0,
        discount_code TEXT DEFAULT '',
        items_json TEXT DEFAULT '[]',
        shipping_address TEXT DEFAULT '',
        shipping_method TEXT DEFAULT '',
        tracking_number TEXT DEFAULT '',
        carrier TEXT DEFAULT '',
        estimated_delivery TEXT DEFAULT '',
        payment_method TEXT DEFAULT '',
        payment_status TEXT DEFAULT 'pending',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # Add estimated_delivery column if missing (migration)
    try:
        conn.execute("ALTER TABLE ecom_orders ADD COLUMN IF NOT EXISTS estimated_delivery TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass

    conn.execute("""CREATE TABLE IF NOT EXISTS abandoned_carts (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        session_id TEXT DEFAULT '',
        customer_name TEXT DEFAULT '',
        customer_email TEXT DEFAULT '',
        customer_phone TEXT DEFAULT '',
        cart_items TEXT DEFAULT '[]',
        cart_total DECIMAL(10,2) DEFAULT 0,
        recovery_status TEXT DEFAULT 'abandoned',
        recovery_messages_sent INTEGER DEFAULT 0,
        discount_code_sent TEXT DEFAULT '',
        recovered_at TIMESTAMP DEFAULT NULL,
        recovered_order_id INTEGER DEFAULT 0,
        abandoned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_followup_at TIMESTAMP DEFAULT NULL
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS ecom_customers (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        customer_email TEXT NOT NULL,
        customer_name TEXT DEFAULT '',
        customer_phone TEXT DEFAULT '',
        total_orders INTEGER DEFAULT 0,
        total_spent DECIMAL(10,2) DEFAULT 0,
        avg_order_value DECIMAL(10,2) DEFAULT 0,
        loyalty_points INTEGER DEFAULT 0,
        loyalty_tier TEXT DEFAULT 'bronze',
        tags TEXT DEFAULT '',
        first_purchase_at TIMESTAMP DEFAULT NULL,
        last_purchase_at TIMESTAMP DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS ecom_integrations (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        ecommerce_platform TEXT DEFAULT '',
        platform_store_url TEXT DEFAULT '',
        platform_api_key TEXT DEFAULT '',
        platform_api_secret TEXT DEFAULT '',
        webhook_url TEXT DEFAULT '',
        product_sync_frequency TEXT DEFAULT 'hourly',
        inventory_sync_frequency TEXT DEFAULT 'hourly',
        order_sync_frequency TEXT DEFAULT 'hourly',
        payment_gateway TEXT DEFAULT '',
        payment_api_key TEXT DEFAULT '',
        email_service TEXT DEFAULT '',
        email_api_key TEXT DEFAULT '',
        sms_service TEXT DEFAULT '',
        sms_api_key TEXT DEFAULT '',
        crm_integration TEXT DEFAULT '',
        crm_api_key TEXT DEFAULT '',
        analytics_integration TEXT DEFAULT '',
        analytics_tracking_id TEXT DEFAULT '',
        support_desk_integration TEXT DEFAULT '',
        support_api_key TEXT DEFAULT '',
        storefront_url TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    try:
        conn.execute("ALTER TABLE ecom_integrations ADD COLUMN IF NOT EXISTS storefront_url TEXT DEFAULT ''")
        conn.execute("ALTER TABLE ecom_integrations ADD COLUMN IF NOT EXISTS payment_publishable_key TEXT DEFAULT ''")
        conn.execute("ALTER TABLE ecom_integrations ADD COLUMN IF NOT EXISTS payment_webhook_secret TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        conn.rollback()

    conn.execute("""CREATE TABLE IF NOT EXISTS ecom_analytics_settings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        revenue_attribution_enabled INTEGER DEFAULT 1,
        conversion_tracking INTEGER DEFAULT 1,
        aov_tracking INTEGER DEFAULT 1,
        cart_recovery_tracking INTEGER DEFAULT 1,
        product_recommendation_tracking INTEGER DEFAULT 0,
        support_deflection_tracking INTEGER DEFAULT 0,
        popular_questions_report INTEGER DEFAULT 0,
        sentiment_analysis INTEGER DEFAULT 0,
        peak_hours_report INTEGER DEFAULT 0,
        export_format TEXT DEFAULT 'csv',
        report_frequency TEXT DEFAULT 'weekly',
        report_recipients TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS conversation_quality (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        session_id TEXT NOT NULL,
        quality_score INTEGER DEFAULT 0,
        engagement_score REAL DEFAULT 0,
        avg_frustration REAL DEFAULT 0,
        frustration_trend TEXT DEFAULT 'stable',
        resolution_score INTEGER DEFAULT 0,
        max_buying_intent INTEGER DEFAULT 0,
        total_messages INTEGER DEFAULT 0,
        escalated BOOLEAN DEFAULT FALSE,
        converted BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # ── Predictive Replenishment & Zero-Party Data Tables ──

    conn.execute("""CREATE TABLE IF NOT EXISTS purchase_history (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        customer_key TEXT NOT NULL,
        product_id INTEGER NOT NULL,
        product_name TEXT,
        product_category TEXT,
        quantity INTEGER DEFAULT 1,
        purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS replenishment_predictions (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        customer_key TEXT NOT NULL,
        product_id INTEGER NOT NULL,
        product_name TEXT,
        predicted_reorder_date TIMESTAMP,
        avg_days_between_orders REAL,
        confidence REAL DEFAULT 0.5,
        notified BOOLEAN DEFAULT FALSE,
        notified_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS customer_preferences (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        customer_key TEXT NOT NULL,
        preference_type TEXT NOT NULL,
        preference_key TEXT NOT NULL,
        preference_value TEXT,
        source TEXT DEFAULT 'chat',
        collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(admin_id, customer_key, preference_type, preference_key)
    )""")
    conn.commit()

    # ── Chat Analytics Events ──
    conn.execute("""CREATE TABLE IF NOT EXISTS chat_analytics_events (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        session_id TEXT NOT NULL DEFAULT '',
        event_type TEXT NOT NULL DEFAULT 'unknown',
        message_count INTEGER DEFAULT 0,
        duration_seconds INTEGER DEFAULT 0,
        scroll_depth INTEGER DEFAULT 0,
        page_time_seconds INTEGER DEFAULT 0,
        visit_count INTEGER DEFAULT 1,
        language TEXT DEFAULT 'en',
        cart_items_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    # ── AI Knowledge Base ──
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_knowledge_base (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        entry_type TEXT DEFAULT 'qa',
        question TEXT DEFAULT '',
        answer TEXT DEFAULT '',
        category TEXT DEFAULT 'general',
        keywords TEXT DEFAULT '',
        source TEXT DEFAULT 'manual',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # ── AI Guardrails ──
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_guardrails (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        rule_type TEXT DEFAULT 'block_topic',
        rule_value TEXT DEFAULT '',
        replacement_response TEXT DEFAULT '',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # ── Browse History (for abandoned browse recovery) ──
    conn.execute("""CREATE TABLE IF NOT EXISTS browse_history (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        session_id TEXT DEFAULT '',
        customer_email TEXT DEFAULT '',
        product_id INTEGER,
        product_name TEXT DEFAULT '',
        product_price DECIMAL(10,2) DEFAULT 0,
        product_image TEXT DEFAULT '',
        viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        recovery_sent BOOLEAN DEFAULT FALSE,
        recovery_sent_at TIMESTAMP
    )""")
    conn.commit()

    # ── Conversation Topics / Insights ──
    conn.execute("""CREATE TABLE IF NOT EXISTS conversation_topics (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        session_id TEXT DEFAULT '',
        topic TEXT NOT NULL,
        subtopic TEXT DEFAULT '',
        sentiment TEXT DEFAULT 'neutral',
        intent TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # ── Wishlist / Save-for-Later ──
    conn.execute("""CREATE TABLE IF NOT EXISTS wishlists (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        customer_email TEXT NOT NULL,
        session_id TEXT DEFAULT '',
        product_id INTEGER NOT NULL,
        product_name TEXT DEFAULT '',
        product_price REAL DEFAULT 0,
        product_image TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        notified_price_drop BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # ── Revenue Attribution ──
    conn.execute("""CREATE TABLE IF NOT EXISTS revenue_events (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        session_id TEXT DEFAULT '',
        customer_email TEXT DEFAULT '',
        event_type TEXT NOT NULL,
        event_value REAL DEFAULT 0,
        product_id INTEGER DEFAULT 0,
        product_name TEXT DEFAULT '',
        order_id INTEGER DEFAULT 0,
        order_number TEXT DEFAULT '',
        attribution_source TEXT DEFAULT 'chatbot',
        touchpoints_json TEXT DEFAULT '[]',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # ── Customer Interest Scores (behavioral personalization) ──
    conn.execute("""CREATE TABLE IF NOT EXISTS customer_interests (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        customer_key TEXT NOT NULL,
        category TEXT DEFAULT '',
        interest_score REAL DEFAULT 0,
        view_count INTEGER DEFAULT 0,
        cart_count INTEGER DEFAULT 0,
        purchase_count INTEGER DEFAULT 0,
        last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # ── Real Estate Tables ──

    conn.execute("""CREATE TABLE IF NOT EXISTS agency_settings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        agency_name TEXT DEFAULT '',
        agency_logo TEXT DEFAULT '',
        brand_primary_color TEXT DEFAULT '#000000',
        brand_secondary_color TEXT DEFAULT '',
        brand_font_family TEXT DEFAULT 'Roboto',
        agency_timezone TEXT DEFAULT 'UTC',
        default_language TEXT DEFAULT 'en',
        supported_languages TEXT DEFAULT '',
        agency_phone TEXT DEFAULT '',
        agency_email TEXT DEFAULT '',
        agency_address TEXT DEFAULT '',
        business_hours TEXT DEFAULT '',
        after_hours_auto_reply TEXT DEFAULT '',
        chatbot_name TEXT DEFAULT '',
        chatbot_avatar TEXT DEFAULT '',
        ai_disclosure_message TEXT DEFAULT '',
        welcome_message TEXT DEFAULT '',
        offline_message TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS re_agents (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        user_id INTEGER DEFAULT 0,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        email TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        photo TEXT DEFAULT '',
        license_number TEXT DEFAULT '',
        title TEXT DEFAULT 'Agent',
        bio TEXT DEFAULT '',
        specializations TEXT DEFAULT '',
        languages TEXT DEFAULT '',
        territories TEXT DEFAULT '',
        agent_status TEXT DEFAULT 'active',
        performance_goal INTEGER DEFAULT 0,
        calendar_url TEXT DEFAULT '',
        showing_availability TEXT DEFAULT '{}',
        max_leads_per_day INTEGER DEFAULT 0,
        max_showings_per_day INTEGER DEFAULT 0,
        notification_preference TEXT DEFAULT 'all',
        quiet_hours TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS lead_routing_settings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        routing_enabled INTEGER DEFAULT 1,
        primary_routing_method TEXT DEFAULT 'round_robin',
        round_robin_priority TEXT DEFAULT 'random',
        round_robin_reset_period TEXT DEFAULT 'weekly',
        round_robin_skip_offline INTEGER DEFAULT 1,
        round_robin_skip_maxed INTEGER DEFAULT 1,
        territory_rules TEXT DEFAULT '{}',
        territory_fallback TEXT DEFAULT 'round_robin',
        specialty_rules TEXT DEFAULT '{}',
        specialty_fallback TEXT DEFAULT 'round_robin',
        claim_system_enabled INTEGER DEFAULT 0,
        claim_time_limit INTEGER DEFAULT 30,
        claim_auto_assign_if_unclaimed INTEGER DEFAULT 1,
        vip_threshold_price DECIMAL(12,2) DEFAULT 1000000,
        vip_routing TEXT DEFAULT 'senior_agent',
        vip_instant_alert INTEGER DEFAULT 1,
        duplicate_check_enabled INTEGER DEFAULT 1,
        duplicate_check_fields TEXT DEFAULT 'email,phone',
        duplicate_action TEXT DEFAULT 'update_existing',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS qualification_flows (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        flow_name TEXT DEFAULT 'Default Qualification',
        is_active INTEGER DEFAULT 1,
        hot_lead_minimum INTEGER DEFAULT 80,
        warm_lead_minimum INTEGER DEFAULT 60,
        cold_lead_maximum INTEGER DEFAULT 39,
        hot_lead_action TEXT DEFAULT 'instant_alert',
        warm_lead_action TEXT DEFAULT 'send_shortlist',
        cold_lead_action TEXT DEFAULT 'add_to_nurture',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS qualification_questions (
        id SERIAL PRIMARY KEY,
        flow_id INTEGER NOT NULL,
        admin_id INTEGER NOT NULL,
        question_order INTEGER DEFAULT 0,
        question_text TEXT NOT NULL,
        question_type TEXT DEFAULT 'single_choice',
        question_options TEXT DEFAULT '[]',
        question_required INTEGER DEFAULT 1,
        question_skip_logic TEXT DEFAULT '{}',
        question_help_text TEXT DEFAULT '',
        question_placeholder TEXT DEFAULT '',
        score_enabled INTEGER DEFAULT 1,
        score_values TEXT DEFAULT '{}',
        score_weight DECIMAL(3,1) DEFAULT 1.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS property_listings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        listing_id TEXT DEFAULT '',
        listing_address TEXT NOT NULL,
        listing_city TEXT DEFAULT '',
        listing_state TEXT DEFAULT '',
        listing_zip TEXT DEFAULT '',
        listing_price DECIMAL(12,2) DEFAULT 0,
        listing_status TEXT DEFAULT 'active',
        listing_type TEXT DEFAULT 'single_family',
        property_subtype TEXT DEFAULT '',
        bedrooms INTEGER DEFAULT 0,
        bathrooms DECIMAL(3,1) DEFAULT 0,
        full_baths INTEGER DEFAULT 0,
        half_baths INTEGER DEFAULT 0,
        square_footage INTEGER DEFAULT 0,
        lot_size TEXT DEFAULT '',
        year_built INTEGER DEFAULT 0,
        stories INTEGER DEFAULT 1,
        garage_spaces INTEGER DEFAULT 0,
        parking_total INTEGER DEFAULT 0,
        has_pool INTEGER DEFAULT 0,
        has_fireplace INTEGER DEFAULT 0,
        has_garage INTEGER DEFAULT 0,
        has_basement INTEGER DEFAULT 0,
        has_yard INTEGER DEFAULT 0,
        has_balcony_deck INTEGER DEFAULT 0,
        has_waterfront INTEGER DEFAULT 0,
        has_mountain_view INTEGER DEFAULT 0,
        pet_friendly INTEGER DEFAULT 0,
        fenced_yard INTEGER DEFAULT 0,
        updated_kitchen INTEGER DEFAULT 0,
        updated_bathrooms INTEGER DEFAULT 0,
        energy_efficient INTEGER DEFAULT 0,
        smart_home_features INTEGER DEFAULT 0,
        accessibility_features INTEGER DEFAULT 0,
        hoa_fee DECIMAL(10,2) DEFAULT 0,
        hoa_includes TEXT DEFAULT '',
        property_tax_annual DECIMAL(10,2) DEFAULT 0,
        tax_rate DECIMAL(5,3) DEFAULT 0,
        school_district TEXT DEFAULT '',
        elementary_school TEXT DEFAULT '',
        middle_school TEXT DEFAULT '',
        high_school TEXT DEFAULT '',
        walk_score INTEGER DEFAULT 0,
        transit_score INTEGER DEFAULT 0,
        bike_score INTEGER DEFAULT 0,
        nearby_amenities TEXT DEFAULT '',
        listing_photos TEXT DEFAULT '[]',
        virtual_tour_url TEXT DEFAULT '',
        floor_plan_image TEXT DEFAULT '',
        video_tour_url TEXT DEFAULT '',
        drone_video_url TEXT DEFAULT '',
        property_description TEXT DEFAULT '',
        short_description TEXT DEFAULT '',
        listing_agent_id INTEGER DEFAULT 0,
        listing_date DATE DEFAULT CURRENT_DATE,
        days_on_market INTEGER DEFAULT 0,
        price_changes TEXT DEFAULT '[]',
        previous_sale_price DECIMAL(12,2) DEFAULT 0,
        previous_sale_date DATE DEFAULT NULL,
        open_house_enabled INTEGER DEFAULT 0,
        open_house_dates TEXT DEFAULT '[]',
        open_house_times TEXT DEFAULT '',
        open_house_agent INTEGER DEFAULT 0,
        open_house_notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS mls_settings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        mls_integration_enabled INTEGER DEFAULT 0,
        mls_provider TEXT DEFAULT 'reso_web_api',
        mls_market_area TEXT DEFAULT '',
        mls_agent_id TEXT DEFAULT '',
        mls_office_id TEXT DEFAULT '',
        mls_username TEXT DEFAULT '',
        mls_password TEXT DEFAULT '',
        mls_data_feed_url TEXT DEFAULT '',
        sync_frequency TEXT DEFAULT 'hourly',
        sync_direction TEXT DEFAULT 'pull_only',
        property_types_to_sync TEXT DEFAULT '[]',
        status_types_to_sync TEXT DEFAULT '[]',
        price_range_filter_min DECIMAL(12,2) DEFAULT 0,
        price_range_filter_max DECIMAL(12,2) DEFAULT 0,
        area_zip_filter TEXT DEFAULT '',
        photo_sync_enabled INTEGER DEFAULT 1,
        max_photo_count INTEGER DEFAULT 25,
        virtual_tour_sync_enabled INTEGER DEFAULT 0,
        last_sync_timestamp TIMESTAMP DEFAULT NULL,
        sync_error_log TEXT DEFAULT '',
        idx_enabled INTEGER DEFAULT 0,
        idx_provider TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS re_nurture_sequences (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        sequence_name TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        target_score_min INTEGER DEFAULT 0,
        target_score_max INTEGER DEFAULT 100,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS re_nurture_messages (
        id SERIAL PRIMARY KEY,
        sequence_id INTEGER NOT NULL,
        admin_id INTEGER NOT NULL,
        message_order INTEGER DEFAULT 0,
        message_delay_days INTEGER DEFAULT 0,
        message_channel TEXT DEFAULT 'email',
        message_subject TEXT DEFAULT '',
        message_body TEXT DEFAULT '',
        message_template TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS re_calendar_settings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        calendar_integration TEXT DEFAULT 'google',
        calendar_api_key TEXT DEFAULT '',
        calendar_sync_direction TEXT DEFAULT 'push_pull',
        default_showing_duration INTEGER DEFAULT 30,
        buffer_between_showings INTEGER DEFAULT 15,
        max_showings_per_day INTEGER DEFAULT 8,
        max_showings_per_week INTEGER DEFAULT 30,
        advance_booking_required INTEGER DEFAULT 24,
        same_day_booking_allowed INTEGER DEFAULT 0,
        weekend_showings_allowed INTEGER DEFAULT 1,
        evening_showings_allowed INTEGER DEFAULT 1,
        auto_confirm_enabled INTEGER DEFAULT 0,
        confirmation_window_hours INTEGER DEFAULT 4,
        reminder_24hr_enabled INTEGER DEFAULT 1,
        reminder_1hr_enabled INTEGER DEFAULT 0,
        reschedule_allowed INTEGER DEFAULT 1,
        cancellation_allowed INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS re_showings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        listing_id INTEGER NOT NULL,
        agent_id INTEGER NOT NULL,
        lead_name TEXT DEFAULT '',
        lead_email TEXT DEFAULT '',
        lead_phone TEXT DEFAULT '',
        showing_date DATE NOT NULL,
        showing_time TEXT NOT NULL,
        duration_minutes INTEGER DEFAULT 30,
        showing_status TEXT DEFAULT 'pending',
        notes TEXT DEFAULT '',
        confirmation_token TEXT DEFAULT '',
        cancel_token TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS re_leads (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        assigned_agent_id INTEGER DEFAULT 0,
        first_name TEXT DEFAULT '',
        last_name TEXT DEFAULT '',
        email TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        lead_type TEXT DEFAULT 'buyer',
        lead_score INTEGER DEFAULT 0,
        lead_status TEXT DEFAULT 'new',
        source TEXT DEFAULT 'chatbot',
        budget_min DECIMAL(12,2) DEFAULT 0,
        budget_max DECIMAL(12,2) DEFAULT 0,
        preferred_areas TEXT DEFAULT '',
        property_type_pref TEXT DEFAULT '',
        bedrooms_pref INTEGER DEFAULT 0,
        bathrooms_pref DECIMAL(3,1) DEFAULT 0,
        must_have_features TEXT DEFAULT '',
        timeline TEXT DEFAULT '',
        pre_approved INTEGER DEFAULT 0,
        financing_type TEXT DEFAULT '',
        current_situation TEXT DEFAULT '',
        household_size INTEGER DEFAULT 0,
        has_pets INTEGER DEFAULT 0,
        qualification_answers TEXT DEFAULT '{}',
        notes TEXT DEFAULT '',
        tags TEXT DEFAULT '',
        chat_transcript TEXT DEFAULT '',
        utm_source TEXT DEFAULT '',
        utm_medium TEXT DEFAULT '',
        utm_campaign TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS re_crm_settings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        crm_platform TEXT DEFAULT '',
        crm_api_key TEXT DEFAULT '',
        crm_api_secret TEXT DEFAULT '',
        crm_instance_url TEXT DEFAULT '',
        mapping_first_name TEXT DEFAULT '',
        mapping_last_name TEXT DEFAULT '',
        mapping_email TEXT DEFAULT '',
        mapping_phone TEXT DEFAULT '',
        mapping_lead_score TEXT DEFAULT '',
        mapping_lead_source TEXT DEFAULT '',
        mapping_chat_transcript TEXT DEFAULT '',
        mapping_property_interests TEXT DEFAULT '',
        mapping_appointment_date TEXT DEFAULT '',
        sync_frequency TEXT DEFAULT 'realtime',
        sync_direction TEXT DEFAULT 'push_pull',
        duplicate_handling TEXT DEFAULT 'update_existing',
        lead_source_tagging TEXT DEFAULT 'ChatGenius',
        utm_tracking_enabled INTEGER DEFAULT 0,
        stage_new_lead TEXT DEFAULT 'New Lead',
        stage_qualified TEXT DEFAULT 'Qualified',
        stage_appointment_set TEXT DEFAULT 'Appointment Set',
        stage_showing_completed TEXT DEFAULT 'Showing Done',
        stage_offer_made TEXT DEFAULT 'Offer Made',
        stage_under_contract TEXT DEFAULT 'Under Contract',
        stage_closed TEXT DEFAULT 'Closed',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS re_compliance_settings (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER UNIQUE NOT NULL,
        fair_housing_compliance_enabled INTEGER DEFAULT 1,
        fair_housing_warning_message TEXT DEFAULT '',
        ai_disclosure_enabled INTEGER DEFAULT 1,
        ai_disclosure_message TEXT DEFAULT '',
        licensing_disclosure TEXT DEFAULT '',
        sms_opt_in_required INTEGER DEFAULT 1,
        sms_opt_in_message TEXT DEFAULT '',
        email_opt_in_required INTEGER DEFAULT 0,
        do_not_call_compliance INTEGER DEFAULT 1,
        lead_data_retention_days INTEGER DEFAULT 365,
        chat_log_retention_days INTEGER DEFAULT 365,
        auto_delete_inactive_leads INTEGER DEFAULT 0,
        gdpr_mode INTEGER DEFAULT 0,
        ccpa_mode INTEGER DEFAULT 0,
        data_export_on_request INTEGER DEFAULT 1,
        data_deletion_on_request INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # ── Chat memory: cross-session memory for returning customers ──
    conn.execute("""CREATE TABLE IF NOT EXISTS chat_memory (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        customer_key TEXT NOT NULL,
        summary TEXT DEFAULT '',
        preferences TEXT DEFAULT '',
        last_products_viewed TEXT DEFAULT '',
        message_count INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(admin_id, customer_key)
    )""")
    conn.commit()

    # ── Stripe Checkout Sessions ──

    conn.execute("""CREATE TABLE IF NOT EXISTS stripe_checkout_sessions (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        session_id TEXT NOT NULL,
        stripe_session_id TEXT,
        stripe_payment_intent TEXT,
        customer_email TEXT,
        cart_items TEXT,
        cart_total DECIMAL(10,2),
        currency TEXT DEFAULT 'usd',
        status TEXT DEFAULT 'pending',
        checkout_url TEXT,
        failure_reason TEXT,
        failure_code TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP
    )""")
    conn.commit()

    # ── Product Reviews (ecommerce) ──
    conn.execute("""CREATE TABLE IF NOT EXISTS product_reviews (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        order_id INTEGER,
        order_number TEXT DEFAULT '',
        product_id INTEGER,
        product_name TEXT DEFAULT '',
        customer_email TEXT DEFAULT '',
        customer_name TEXT DEFAULT '',
        rating INTEGER DEFAULT 0,
        review_text TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        review_source TEXT DEFAULT 'chatbot',
        incentive_code TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # ── Review prompts tracking (to avoid re-asking) ──
    conn.execute("""CREATE TABLE IF NOT EXISTS review_prompts (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        order_id INTEGER NOT NULL,
        customer_email TEXT DEFAULT '',
        prompted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        review_submitted BOOLEAN DEFAULT FALSE
    )""")
    conn.commit()

    # ── Size & Fit Predictions ──
    conn.execute("""CREATE TABLE IF NOT EXISTS size_fit_profiles (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        customer_key TEXT NOT NULL,
        body_type TEXT DEFAULT '',
        preferred_fit TEXT DEFAULT '',
        height TEXT DEFAULT '',
        weight TEXT DEFAULT '',
        shoe_size TEXT DEFAULT '',
        typical_size TEXT DEFAULT '',
        fit_notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(admin_id, customer_key)
    )""")
    conn.commit()

    conn.execute("""CREATE TABLE IF NOT EXISTS size_fit_feedback (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        customer_key TEXT NOT NULL,
        product_id INTEGER NOT NULL,
        product_name TEXT DEFAULT '',
        brand TEXT DEFAULT '',
        category TEXT DEFAULT '',
        recommended_size TEXT DEFAULT '',
        actual_fit TEXT DEFAULT '',
        returned BOOLEAN DEFAULT FALSE,
        return_reason TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # ── Price Watch / Drop Alerts ──
    conn.execute("""CREATE TABLE IF NOT EXISTS price_watches (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        customer_email TEXT NOT NULL,
        session_id TEXT DEFAULT '',
        product_id INTEGER NOT NULL,
        product_name TEXT DEFAULT '',
        watched_price REAL DEFAULT 0,
        target_price REAL DEFAULT 0,
        notified BOOLEAN DEFAULT FALSE,
        notified_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(admin_id, customer_email, product_id)
    )""")
    conn.commit()

    # ── Competitor Prices ──
    conn.execute("""CREATE TABLE IF NOT EXISTS competitor_prices (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        competitor_name TEXT DEFAULT '',
        competitor_price REAL DEFAULT 0,
        competitor_url TEXT DEFAULT '',
        our_advantages TEXT DEFAULT '',
        last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(admin_id, product_id, competitor_name)
    )""")
    conn.commit()

    # ── Fraud Signals ──
    conn.execute("""CREATE TABLE IF NOT EXISTS fraud_signals (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        session_id TEXT DEFAULT '',
        customer_email TEXT DEFAULT '',
        signal_type TEXT NOT NULL,
        signal_detail TEXT DEFAULT '',
        risk_score REAL DEFAULT 0,
        resolved BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()

    # ── Add missing columns (safe migration for existing tables) ──
    for alter_sql in [
        "ALTER TABLE stripe_checkout_sessions ADD COLUMN IF NOT EXISTS failure_reason TEXT",
        "ALTER TABLE stripe_checkout_sessions ADD COLUMN IF NOT EXISTS failure_code TEXT",
    ]:
        try:
            conn.execute(alter_sql)
            conn.commit()
        except Exception:
            conn.rollback()

    # ── Indexes for ecommerce tables ──
    conn = get_db()
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_products_admin_id ON products(admin_id)",
        "CREATE INDEX IF NOT EXISTS idx_product_variants_product_id ON product_variants(product_id)",
        "CREATE INDEX IF NOT EXISTS idx_abandoned_carts_admin_id ON abandoned_carts(admin_id)",
        "CREATE INDEX IF NOT EXISTS idx_ecom_orders_admin_id ON ecom_orders(admin_id)",
        "CREATE INDEX IF NOT EXISTS idx_ecom_orders_order_number ON ecom_orders(admin_id, order_number)",
        "CREATE INDEX IF NOT EXISTS idx_store_discounts_admin_id ON store_discounts(admin_id)",
    ]:
        try:
            conn.execute(idx_sql)
            conn.commit()
        except Exception:
            conn.rollback()
    conn.close()

    # ── Website Visitor Tracking ──
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS page_visits (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            visitor_id TEXT NOT NULL DEFAULT '',
            page_url TEXT DEFAULT '',
            page_path TEXT DEFAULT '',
            referrer TEXT DEFAULT '',
            user_agent TEXT DEFAULT '',
            ip_hash TEXT DEFAULT '',
            country TEXT DEFAULT '',
            device_type TEXT DEFAULT 'desktop',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_page_visits_admin_id ON page_visits(admin_id);
        CREATE INDEX IF NOT EXISTS idx_page_visits_created_at ON page_visits(created_at);
    """)
    conn.close()


def get_chat_memory(admin_id, customer_key):
    """Get cross-session memory for a customer."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM chat_memory WHERE admin_id=%s AND customer_key=%s",
        (admin_id, customer_key)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_chat_memory(admin_id, customer_key, summary="", preferences="", last_products_viewed="", message_count=0):
    """Create or update cross-session memory for a customer."""
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM chat_memory WHERE admin_id=%s AND customer_key=%s",
        (admin_id, customer_key)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE chat_memory SET summary=%s, preferences=%s, last_products_viewed=%s, message_count=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
            (summary, preferences, last_products_viewed, message_count, existing["id"])
        )
    else:
        conn.execute(
            "INSERT INTO chat_memory (admin_id, customer_key, summary, preferences, last_products_viewed, message_count) VALUES (%s,%s,%s,%s,%s,%s)",
            (admin_id, customer_key, summary, preferences, last_products_viewed, message_count)
        )
    conn.commit()
    conn.close()


def save_mobile_app_interest(email):
    """Save an email address for mobile app launch notification."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO mobile_app_interest (email) VALUES (%s)",
            (email,)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True


def create_partner_application(data):
    """Insert a new partner application."""
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO partner_applications (agency_name, contact_name, email, phone, website, client_count, referral_source)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (data.get("agency_name", ""), data.get("contact_name", ""), data.get("email", ""),
             data.get("phone", ""), data.get("website", ""), data.get("client_count", 0),
             data.get("referral_source", ""))
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True


def get_partner_applications():
    """Get all partner applications, newest first."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM partner_applications ORDER BY created_at DESC").fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def save_lead(name, phone, notes="", admin_id=0):
    conn = get_db()
    conn.execute(
        "INSERT INTO leads (name, phone, notes, admin_id) VALUES (%s, %s, %s, %s)",
        (name, phone, notes, admin_id)
    )
    conn.commit()
    conn.close()


def get_lead_by_email_or_phone(email, phone, admin_id):
    """Find existing lead by email (primary) or phone (secondary) for deduplication."""
    conn = get_db()
    row = None
    if email:
        row = conn.execute("SELECT * FROM leads WHERE email=%s AND admin_id=%s LIMIT 1",
                           (email, admin_id)).fetchone()
    if not row and phone:
        row = conn.execute("SELECT * FROM leads WHERE phone=%s AND admin_id=%s LIMIT 1",
                           (phone, admin_id)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_lead_enriched(name, phone, email="", notes="", admin_id=0, source="chatbot",
                       capture_trigger="manual", treatment_interest="", is_returning=0,
                       preferred_time="", session_id="", budget=""):
    """Save or update a lead with deduplication by email/phone. Returns lead ID."""
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Deduplicate: check for existing lead by email or phone
    existing = None
    if email:
        existing = conn.execute("SELECT * FROM leads WHERE email=%s AND admin_id=%s LIMIT 1",
                                (email, admin_id)).fetchone()
    if not existing and phone:
        existing = conn.execute("SELECT * FROM leads WHERE phone=%s AND admin_id=%s LIMIT 1",
                                (phone, admin_id)).fetchone()

    if existing:
        existing = dict(existing)
        lead_id = existing["id"]
        # Merge: update fields that are richer than existing
        upd_name = name if (name and name != "Unknown" and (not existing.get("name") or existing["name"] == "Unknown")) else existing.get("name", name)
        upd_phone = phone or existing.get("phone", "")
        upd_email = email or existing.get("email", "")
        upd_treatment = treatment_interest or existing.get("treatment_interest", "")
        upd_session = session_id or existing.get("session_id", "")
        upd_budget = budget or existing.get("budget", "")
        conn.execute(
            """UPDATE leads SET name=%s, phone=%s, email=%s, treatment_interest=%s,
               session_id=%s, last_activity_at=%s, is_returning=%s, budget=%s
               WHERE id=%s""",
            (upd_name, upd_phone, upd_email, upd_treatment,
             upd_session, now, max(is_returning, existing.get("is_returning", 0)),
             upd_budget, lead_id)
        )
        conn.commit()
        conn.close()
        return lead_id

    # No existing lead — insert new
    _ins_cur = conn.execute(
        """INSERT INTO leads (name, phone, email, notes, admin_id, source, capture_trigger,
           treatment_interest, is_returning, preferred_time, session_id, stage, last_activity_at, budget)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'new',%s,%s) RETURNING id""",
        (name, phone, email, notes, admin_id, source, capture_trigger,
         treatment_interest, is_returning, preferred_time, session_id, now, budget)
    )
    lead_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return lead_id


def create_lead_for_session(name, phone, email="", admin_id=0, source="chatbot",
                            capture_trigger="auto_interest", treatment_interest="",
                            is_returning=0, preferred_time="", session_id="", budget=""):
    """Create a new lead for a chat session. No email dedup — each session = new lead."""
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _ins_cur = conn.execute(
        """INSERT INTO leads (name, phone, email, notes, admin_id, source, capture_trigger,
           treatment_interest, is_returning, preferred_time, session_id, stage, last_activity_at, budget)
           VALUES (%s,%s,%s,'',%s,%s,%s,%s,%s,%s,%s,'new',%s,%s) RETURNING id""",
        (name, phone, email, admin_id, source, capture_trigger,
         treatment_interest, is_returning, preferred_time, session_id, now, budget)
    )
    lead_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return lead_id


def update_lead_stage(lead_id, stage):
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE leads SET stage=%s, last_activity_at=%s WHERE id=%s", (stage, now, lead_id))
    conn.commit()
    conn.close()


def update_lead_score(lead_id, score, temperature=None):
    conn = get_db()
    score_val = max(0, round(float(score), 2))
    if temperature:
        conn.execute("UPDATE leads SET score=%s, temperature=%s WHERE id=%s", (score_val, temperature, lead_id))
    else:
        # Derive temperature from score
        if score_val < 0: temp = "frozen"
        elif score_val <= 2: temp = "cold"
        elif score_val <= 4: temp = "warm_emerging"
        elif score_val <= 7: temp = "warm"
        elif score_val <= 11: temp = "hot"
        else: temp = "vip"
        conn.execute("UPDATE leads SET score=%s, temperature=%s WHERE id=%s", (score_val, temp, lead_id))
    conn.commit()
    conn.close()


def get_all_leads(admin_id=0):
    conn = get_db()
    if admin_id:
        rows = conn.execute("SELECT * FROM leads WHERE admin_id = %s ORDER BY created_at DESC", (admin_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_leads_by_stage(admin_id, stage):
    conn = get_db()
    rows = conn.execute("SELECT * FROM leads WHERE admin_id=%s AND stage=%s ORDER BY score DESC, created_at DESC",
                        (admin_id, stage)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_lead_by_session(session_id):
    """Find an existing lead by chat session ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM leads WHERE session_id=%s LIMIT 1", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_lead_fields(lead_id, updates):
    """Update specific fields on a lead (e.g. name, email, phone)."""
    if not updates:
        return
    allowed = {"name", "email", "phone", "treatment_interest", "preferred_time", "budget"}
    safe = {k: v for k, v in updates.items() if k in allowed}
    if not safe:
        return
    conn = get_db()
    sets = ", ".join(f"{k}=%s" for k in safe)
    vals = list(safe.values()) + [lead_id]
    conn.execute(f"UPDATE leads SET {sets} WHERE id=%s", vals)
    conn.commit()
    conn.close()


def get_chat_history_by_session(session_id):
    """Get full chat history for a session (user + bot messages)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT message, sender, created_at FROM chat_logs WHERE session_id=%s ORDER BY created_at ASC",
        (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def convert_lead(lead_id, booking_id):
    """Delete a lead when converted to booking — remove from leads entirely."""
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Cancel pending follow-ups first
    conn.execute("UPDATE lead_followups SET status='cancelled', cancelled_at=%s WHERE lead_id=%s AND status='pending'",
                 (now, lead_id))
    # Delete the lead — they're now a booking
    conn.execute("DELETE FROM leads WHERE id=%s", (lead_id,))
    # Clean up follow-ups too
    conn.execute("DELETE FROM lead_followups WHERE lead_id=%s", (lead_id,))
    conn.commit()
    conn.close()


def create_lead_followup(lead_id, admin_id, day_number, scheduled_at):
    conn = get_db()
    # Prevent duplicate followups for same lead+day
    existing = conn.execute(
        "SELECT id FROM lead_followups WHERE lead_id=%s AND day_number=%s",
        (lead_id, day_number)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO lead_followups (lead_id, admin_id, day_number, scheduled_at) VALUES (%s,%s,%s,%s)",
            (lead_id, admin_id, day_number, scheduled_at)
        )
        conn.commit()
    conn.close()


def get_pending_lead_followups():
    """Get all pending follow-ups that are due."""
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT lf.*, l.name, l.email, l.phone, l.treatment_interest, l.stage, l.admin_id AS lead_admin_id
           FROM lead_followups lf
           JOIN leads l ON l.id = lf.lead_id
           WHERE lf.status='pending' AND lf.scheduled_at <= %s
           ORDER BY lf.scheduled_at""", (now,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_lead_followup_sent(followup_id):
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE lead_followups SET status='sent', sent_at=%s WHERE id=%s", (now, followup_id))
    conn.commit()
    conn.close()


def cancel_lead_followups(lead_id):
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE lead_followups SET status='cancelled', cancelled_at=%s WHERE lead_id=%s AND status='pending'",
                 (now, lead_id))
    conn.commit()
    conn.close()


def log_lead_action(lead_id, admin_id, action_type):
    """Log an admin action on a lead (called, emailed, contacted, converted) and auto-progress stage."""
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Store last action on the lead itself
    try:
        conn.execute("UPDATE leads SET last_action=%s, last_action_at=%s, last_activity_at=%s WHERE id=%s",
                     (action_type, now, now, lead_id))
    except Exception:
        conn.rollback()
        # Columns may not exist yet — just update last_activity_at
        conn.execute("UPDATE leads SET last_activity_at=%s WHERE id=%s", (now, lead_id))
    # Auto-progress stage based on action
    stage_map = {"called": "contacted", "emailed": "contacted", "contacted": "contacted", "converted": "converted"}
    new_stage = stage_map.get(action_type)
    if new_stage:
        conn.execute("UPDATE leads SET stage=%s WHERE id=%s AND stage IN ('new','engaged','warm','contacted')", (new_stage, lead_id))
    conn.commit()
    conn.close()


def get_lead_followup_summary(lead_id):
    """Returns dict with total, sent, pending counts."""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) AS cnt FROM lead_followups WHERE lead_id=%s", (lead_id,)).fetchone()['cnt']
    sent = conn.execute("SELECT COUNT(*) AS cnt FROM lead_followups WHERE lead_id=%s AND status='sent'", (lead_id,)).fetchone()['cnt']
    pending = conn.execute("SELECT COUNT(*) AS cnt FROM lead_followups WHERE lead_id=%s AND status='pending'", (lead_id,)).fetchone()['cnt']
    conn.close()
    return {"total": total, "sent": sent, "pending": pending}


def get_stale_leads(admin_id, hours=48):
    """Find leads in 'new' or 'engaged' stage with no activity for N hours."""
    from datetime import datetime, timedelta
    conn = get_db()
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT * FROM leads WHERE admin_id=%s AND stage IN ('new','engaged')
           AND last_activity_at IS NOT NULL AND last_activity_at < %s
           ORDER BY last_activity_at""",
        (admin_id, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_hot_lead_alert(lead_id, admin_id, lead_name, score, temperature, product_interest=""):
    """Create an in-app alert for a hot lead (score 12+)."""
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO hot_lead_alerts (lead_id, admin_id, lead_name, score, temperature, product_interest, created_at, seen)
           VALUES (%s,%s,%s,%s,%s,%s,%s,0)""",
        (lead_id, admin_id, lead_name, score, temperature, product_interest, now)
    )
    conn.commit()
    conn.close()


def get_unseen_hot_lead_alerts(admin_id):
    """Get unseen hot lead alerts for the admin."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM hot_lead_alerts WHERE admin_id=%s AND seen=0 ORDER BY created_at DESC LIMIT 10",
        (admin_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_hot_lead_alerts_seen(admin_id):
    """Mark all hot lead alerts as seen."""
    conn = get_db()
    conn.execute("UPDATE hot_lead_alerts SET seen=1 WHERE admin_id=%s AND seen=0", (admin_id,))
    conn.commit()
    conn.close()


def queue_lead_email(lead_id, admin_id, send_at):
    """Queue a lead outreach email to be sent at a specific time."""
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Don't double-queue for same lead
    existing = conn.execute("SELECT id FROM lead_email_queue WHERE lead_id=%s AND status='pending'", (lead_id,)).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO lead_email_queue (lead_id, admin_id, send_at, status, created_at) VALUES (%s,%s,%s,'pending',%s)",
            (lead_id, admin_id, send_at, now)
        )
        conn.commit()
    conn.close()


def get_pending_lead_emails():
    """Get all queued lead emails that are due to be sent."""
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT leq.*, l.name, l.email, l.phone, l.treatment_interest, l.score, l.temperature
           FROM lead_email_queue leq
           JOIN leads l ON l.id = leq.lead_id
           WHERE leq.status='pending' AND leq.send_at <= %s
           ORDER BY leq.send_at""", (now,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_lead_email_sent(queue_id):
    """Mark a queued lead email as sent."""
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE lead_email_queue SET status='sent', sent_at=%s WHERE id=%s", (now, queue_id))
    conn.commit()
    conn.close()


def mark_lead_email_failed(queue_id):
    """Mark a queued lead email as permanently failed."""
    conn = get_db()
    conn.execute("UPDATE lead_email_queue SET status='failed' WHERE id=%s", (queue_id,))
    conn.commit()
    conn.close()


def increment_lead_email_retry(queue_id):
    """Increment retry count for a queued email."""
    conn = get_db()
    try:
        conn.execute("UPDATE lead_email_queue SET retry_count = COALESCE(retry_count, 0) + 1 WHERE id=%s", (queue_id,))
        conn.commit()
    except Exception:
        conn.rollback()
    conn.close()


def save_booking(customer_name, customer_email, date, time, service="General Consultation",
                 calendar_event_id="", customer_phone="", doctor_id=0, doctor_name="", admin_id=0,
                 status="pending", promotion_code="", service_id=0, notes="", patient_type=""):
    conn = get_db()
    _ins_cur = conn.execute(
        """INSERT INTO bookings (customer_name, customer_email, customer_phone, date, time,
           service, calendar_event_id, doctor_id, doctor_name, admin_id, status, promotion_code,
           service_id, notes, patient_type)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (customer_name, customer_email, customer_phone, date, time, service,
         calendar_event_id, doctor_id, doctor_name, admin_id, status, promotion_code,
         int(service_id or 0), notes or "", patient_type or "")
    )
    booking_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return booking_id


def add_booking(customer_name, customer_email="", customer_phone="", date="", time="",
                service="General Consultation", doctor_id=0, doctor_name="", admin_id=0, status="pending"):
    """Add a booking and return its ID."""
    conn = get_db()
    _ins_cur = conn.execute(
        """INSERT INTO bookings (customer_name, customer_email, customer_phone, date, time,
           service, doctor_id, doctor_name, admin_id, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (customer_name, customer_email, customer_phone, date, time, service, doctor_id, doctor_name, admin_id, status))
    bid = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return bid


def confirm_booking_by_id(booking_id):
    """Mark a pending booking as confirmed."""
    conn = get_db()
    conn.execute("UPDATE bookings SET status='confirmed' WHERE id=%s", (booking_id,))
    conn.commit()
    conn.close()


def get_booked_times(doctor_id, date_str):
    """Get list of booked time strings for a doctor on a specific date.
    Also includes slots held by waitlist (status='notified') so they can't be double-booked."""
    conn = get_db()
    rows = conn.execute(
        "SELECT time FROM bookings WHERE doctor_id = %s AND date = %s AND status != 'cancelled'",
        (doctor_id, date_str)).fetchall()
    booked = [r["time"] for r in rows]
    # Also hold slots where a waitlist patient is deciding
    held = conn.execute(
        "SELECT time_slot FROM waitlist WHERE doctor_id = %s AND date = %s AND status = 'notified'",
        (doctor_id, date_str)).fetchall()
    for h in held:
        if h["time_slot"] not in booked:
            booked.append(h["time_slot"])
    conn.close()
    return booked


def find_bookings_by_date(admin_id, date_str):
    """Find active bookings for a specific date under an admin."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM bookings WHERE admin_id = %s AND date = %s AND status != 'cancelled' ORDER BY time",
        (admin_id, date_str)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_booking_dates(admin_id):
    """Return a list of distinct dates that have active bookings for an admin."""
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT date FROM bookings WHERE admin_id = %s AND status NOT IN ('cancelled','no_show') ORDER BY date",
        (admin_id,)).fetchall()
    conn.close()
    return [r["date"] for r in rows]


def cancel_booking(booking_id, admin_id=None):
    """Cancel a booking by setting its status to 'cancelled'.
    Bug 5 fix: optional admin_id parameter for defense-in-depth scoping."""
    conn = get_db()
    if admin_id:
        conn.execute(
            "UPDATE bookings SET status = 'cancelled', revenue_amount = 0, cancelled_at = CURRENT_TIMESTAMP WHERE id = %s AND admin_id = %s",
            (booking_id, admin_id),
        )
    else:
        conn.execute(
            "UPDATE bookings SET status = 'cancelled', revenue_amount = 0, cancelled_at = CURRENT_TIMESTAMP WHERE id = %s",
            (booking_id,),
        )
    conn.commit()
    conn.close()


def get_booking_by_id(booking_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM bookings WHERE id = %s", (booking_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def find_upcoming_bookings_for_customer(admin_id, name="", email="", phone=""):
    """Find upcoming (today or later) active bookings matching customer identity."""
    from datetime import date as _date
    today = _date.today().isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM bookings WHERE admin_id = %s AND date >= %s AND status != 'cancelled' ORDER BY date, time",
        (admin_id, today)).fetchall()
    conn.close()
    results = []
    name_l = (name or "").strip().lower()
    email_l = (email or "").strip().lower()
    phone_s = (phone or "").strip()
    for r in rows:
        r = dict(r)
        if ((name_l and r.get("customer_name", "").strip().lower() == name_l) or
            (email_l and r.get("customer_email", "").strip().lower() == email_l) or
            (phone_s and r.get("customer_phone", "").strip() == phone_s)):
            results.append(r)
    return results


def get_all_bookings(admin_id=0, doctor_id=0):
    conn = get_db()
    if doctor_id:
        rows = conn.execute("SELECT * FROM bookings WHERE doctor_id = %s ORDER BY created_at DESC", (doctor_id,)).fetchall()
    elif admin_id:
        rows = conn.execute("SELECT * FROM bookings WHERE admin_id = %s ORDER BY created_at DESC", (admin_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM bookings ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats(admin_id=0, doctor_id=0):
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    if doctor_id:
        lead_count = 0
        booking_count = conn.execute("SELECT COUNT(*) AS cnt FROM bookings WHERE doctor_id = %s AND status != 'cancelled'", (doctor_id,)).fetchone()['cnt']
        today_bookings = conn.execute("SELECT COUNT(*) AS cnt FROM bookings WHERE doctor_id = %s AND date = %s AND status != 'cancelled'", (doctor_id, today)).fetchone()['cnt']
    elif admin_id:
        lead_count = conn.execute("SELECT COUNT(*) AS cnt FROM leads WHERE admin_id = %s", (admin_id,)).fetchone()['cnt']
        booking_count = conn.execute("SELECT COUNT(*) AS cnt FROM bookings WHERE admin_id = %s AND status != 'cancelled'", (admin_id,)).fetchone()['cnt']
        today_bookings = conn.execute("SELECT COUNT(*) AS cnt FROM bookings WHERE admin_id = %s AND date = %s AND status != 'cancelled'", (admin_id, today)).fetchone()['cnt']
    else:
        lead_count = conn.execute("SELECT COUNT(*) AS cnt FROM leads").fetchone()['cnt']
        booking_count = conn.execute("SELECT COUNT(*) AS cnt FROM bookings WHERE status != 'cancelled'").fetchone()['cnt']
        today_bookings = conn.execute("SELECT COUNT(*) AS cnt FROM bookings WHERE date = %s AND status != 'cancelled'", (today,)).fetchone()['cnt']
    conn.close()
    return {
        "total_leads": lead_count,
        "total_bookings": booking_count,
        "today_bookings": today_bookings,
    }


def get_stats_extended(admin_id, date_from=None, date_to=None):
    """Extended stats for overview: conversion rate, weekly/monthly comparisons, status breakdown."""
    conn = get_db()
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")

    # This week (Mon-Sun)
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    # Last week
    last_week_start = (today - timedelta(days=today.weekday() + 7)).strftime("%Y-%m-%d")
    last_week_end = (today - timedelta(days=today.weekday() + 1)).strftime("%Y-%m-%d")
    # This month
    month_start = today.replace(day=1).strftime("%Y-%m-%d")
    # Last month
    if today.month == 1:
        last_month_start = today.replace(year=today.year - 1, month=12, day=1).strftime("%Y-%m-%d")
    else:
        last_month_start = today.replace(month=today.month - 1, day=1).strftime("%Y-%m-%d")
    last_month_end = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        # Conversion rate (all time)
        total_sessions = conn.execute(
            "SELECT COUNT(DISTINCT session_id) as c FROM chat_logs WHERE admin_id = %s", (admin_id,)
        ).fetchone()["c"]
        booked_sessions = conn.execute(
            "SELECT COUNT(DISTINCT session_id) as c FROM chat_logs WHERE admin_id = %s AND resulted_in_booking = 1", (admin_id,)
        ).fetchone()["c"]
        conversion_rate = min(100.0, round(booked_sessions / total_sessions * 100, 1)) if total_sessions > 0 else 0

        # This week bookings & leads
        week_bookings = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id = %s AND status != 'cancelled' AND date >= %s AND date <= %s",
            (admin_id, week_start, today_str)
        ).fetchone()["c"]
        week_leads = conn.execute(
            "SELECT COUNT(*) as c FROM leads WHERE admin_id = %s AND created_at::date >= %s AND created_at::date <= %s",
            (admin_id, week_start, today_str)
        ).fetchone()["c"]

        # Last week bookings & leads (for comparison)
        last_week_bookings = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id = %s AND status != 'cancelled' AND date >= %s AND date <= %s",
            (admin_id, last_week_start, last_week_end)
        ).fetchone()["c"]
        last_week_leads = conn.execute(
            "SELECT COUNT(*) as c FROM leads WHERE admin_id = %s AND created_at::date >= %s AND created_at::date <= %s",
            (admin_id, last_week_start, last_week_end)
        ).fetchone()["c"]

        # This month bookings & leads
        month_bookings = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id = %s AND status != 'cancelled' AND date >= %s AND date <= %s",
            (admin_id, month_start, today_str)
        ).fetchone()["c"]
        month_leads = conn.execute(
            "SELECT COUNT(*) as c FROM leads WHERE admin_id = %s AND created_at::date >= %s AND created_at::date <= %s",
            (admin_id, month_start, today_str)
        ).fetchone()["c"]

        # Last month bookings & leads
        last_month_bookings = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id = %s AND status != 'cancelled' AND date >= %s AND date <= %s",
            (admin_id, last_month_start, last_month_end)
        ).fetchone()["c"]
        last_month_leads = conn.execute(
            "SELECT COUNT(*) as c FROM leads WHERE admin_id = %s AND created_at::date >= %s AND created_at::date <= %s",
            (admin_id, last_month_start, last_month_end)
        ).fetchone()["c"]

        # Date filter clause for optional range
        _df_clause = ""
        _df_params = (admin_id,)
        if date_from and date_to:
            _df_clause = " AND date::date BETWEEN %s AND %s"
            _df_params = (admin_id, date_from, date_to)

        # Status breakdown
        status_rows = conn.execute(
            "SELECT status, COUNT(*) as c FROM bookings WHERE admin_id = %s" + _df_clause + " GROUP BY status",
            _df_params
        ).fetchall()
        status_breakdown = {r["status"]: r["c"] for r in status_rows}

        # Day-of-week distribution (by appointment date)
        dow_rows = conn.execute(
            "SELECT EXTRACT(DOW FROM date::date) as dow, COUNT(*) as c FROM bookings WHERE admin_id = %s AND status != 'cancelled'" + _df_clause + " GROUP BY dow ORDER BY dow",
            _df_params
        ).fetchall()
        dow_names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        dow_distribution = [{"day": dow_names[int(r["dow"])], "count": r["c"]} for r in dow_rows]

        # Avg bookings per doctor
        _bpd_join = " AND b.status != 'cancelled'"
        _bpd_params = [admin_id]
        if date_from and date_to:
            _bpd_join += " AND b.date::date BETWEEN %s AND %s"
            _bpd_params = [date_from, date_to, admin_id]
        doc_rows = conn.execute(
            "SELECT d.name, COUNT(b.id) as c FROM doctors d LEFT JOIN bookings b ON b.doctor_id = d.id" + _bpd_join + " WHERE d.admin_id = %s GROUP BY d.id, d.name ORDER BY c DESC",
            tuple(_bpd_params)
        ).fetchall()
        bookings_per_doctor = [{"name": r["name"], "count": r["c"]} for r in doc_rows]

        # Monthly trend (by appointment date)
        if date_from and date_to:
            monthly_rows = conn.execute(
                "SELECT TO_CHAR(date::date, 'YYYY-MM') as month, COUNT(*) as bookings, "
                "SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled, "
                "SUM(CASE WHEN status = 'no_show' THEN 1 ELSE 0 END) as no_shows, "
                "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed "
                "FROM bookings WHERE admin_id = %s AND date::date BETWEEN %s AND %s "
                "GROUP BY month ORDER BY month",
                (admin_id, date_from, date_to)
            ).fetchall()
        else:
            monthly_rows = conn.execute(
                "SELECT TO_CHAR(date::date, 'YYYY-MM') as month, COUNT(*) as bookings, "
                "SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled, "
                "SUM(CASE WHEN status = 'no_show' THEN 1 ELSE 0 END) as no_shows, "
                "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed "
                "FROM bookings WHERE admin_id = %s AND date::date >= (NOW()::date - INTERVAL '6 months') "
                "GROUP BY month ORDER BY month",
                (admin_id,)
            ).fetchall()
        monthly_trend = [{"month": r["month"], "bookings": r["bookings"], "cancelled": r["cancelled"], "no_shows": r["no_shows"], "completed": r["completed"]} for r in monthly_rows]

    finally:
        conn.close()

    def _pct_change(current, previous):
        if previous == 0:
            return 100.0 if current > 0 else 0.0
        return round((current - previous) / previous * 100, 1)

    return {
        "conversion_rate": conversion_rate,
        "total_sessions": total_sessions,
        "booked_sessions": booked_sessions,
        "week_bookings": week_bookings,
        "week_leads": week_leads,
        "week_bookings_change": _pct_change(week_bookings, last_week_bookings),
        "week_leads_change": _pct_change(week_leads, last_week_leads),
        "month_bookings": month_bookings,
        "month_leads": month_leads,
        "month_bookings_change": _pct_change(month_bookings, last_month_bookings),
        "month_leads_change": _pct_change(month_leads, last_month_leads),
        "status_breakdown": status_breakdown,
        "dow_distribution": dow_distribution,
        "bookings_per_doctor": bookings_per_doctor,
        "monthly_trend": monthly_trend,
    }


# ══════════════════════════════════════════════
#  ROI Tracking
# ══════════════════════════════════════════════

def add_booking_revenue(booking_id, amount):
    """Set revenue_amount on a booking for ROI tracking."""
    conn = get_db()
    conn.execute("UPDATE bookings SET revenue_amount=%s WHERE id=%s", (float(amount), booking_id))
    conn.commit()
    conn.close()


def get_roi_data(admin_id):
    """Get ROI metrics for a company."""
    conn = get_db()
    company_type = get_company_type(admin_id)

    if company_type == "ecommerce":
        # E-commerce: revenue from orders (exclude cancelled/refunded)
        row = conn.execute(
            "SELECT COALESCE(SUM(order_total), 0) as total_revenue, COUNT(*) as total_bookings "
            "FROM ecom_orders WHERE admin_id=%s AND order_status NOT IN ('cancelled', 'refunded')",
            (admin_id,)
        ).fetchone()
    else:
        # Dental/other: revenue from confirmed/completed bookings
        row = conn.execute(
            "SELECT COALESCE(SUM(revenue_amount), 0) as total_revenue, COUNT(*) as total_bookings "
            "FROM bookings WHERE admin_id=%s AND status IN ('confirmed', 'completed')",
            (admin_id,)
        ).fetchone()
    total_revenue = float(row["total_revenue"] or 0)
    total_bookings = row["total_bookings"]

    # Chat sessions
    sessions_row = conn.execute(
        "SELECT COUNT(DISTINCT session_id) as c FROM chat_logs WHERE admin_id=%s",
        (admin_id,)
    ).fetchone()
    total_sessions = sessions_row["c"] if sessions_row else 0

    # Get current plan
    plan_row = conn.execute(
        "SELECT plan FROM users WHERE id=%s", (admin_id,)
    ).fetchone()
    plan = plan_row["plan"] if plan_row else "free_trial"
    current_plan_cost = PLAN_COSTS.get(plan, 0)

    # Calculate total historical cost from plan_history
    # Each row = one month at that plan's cost
    history_rows = conn.execute(
        "SELECT plan, monthly_cost, started_at FROM plan_history WHERE user_id=%s ORDER BY started_at",
        (admin_id,)
    ).fetchall()

    total_cost = 0
    if history_rows:
        from datetime import datetime as _dt
        from math import ceil
        for i, h in enumerate(history_rows):
            start = _parse_dt(h["started_at"]) if h["started_at"] else _dt.now()
            if i + 1 < len(history_rows):
                end = _parse_dt(history_rows[i + 1]["started_at"])
            else:
                end = _dt.now()
            days_on_plan = max(0, (end - start).days)
            # Each billing cycle = 1 payment. They pay on day 1, then every 30 days.
            billing_months = max(1, ceil(days_on_plan / 30))
            total_cost += float(h["monthly_cost"] or 0) * billing_months
    elif current_plan_cost > 0:
        total_cost = current_plan_cost

    conn.close()

    # Get company currency and convert USD plan costs
    company_currency = get_company_currency(admin_id)

    # Always use currency code (SAR, USD, EUR etc.) — no Arabic/special symbols
    currency_symbol = company_currency + " "

    # Approximate USD exchange rates (USD → target currency)
    USD_RATES = {
        "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "SAR": 3.75, "AED": 3.67,
        "EGP": 50.0, "JOD": 0.71, "KWD": 0.31, "BHD": 0.38, "QAR": 3.64,
        "OMR": 0.38, "TRY": 32.0, "INR": 83.5, "PKR": 278.0, "JPY": 154.0,
        "CNY": 7.25, "KRW": 1340.0, "BRL": 5.0, "MXN": 17.2, "CAD": 1.37,
        "AUD": 1.55, "NZD": 1.67, "ZAR": 18.5, "NGN": 1550.0, "KES": 153.0,
        "MAD": 10.0, "IQD": 1310.0, "LBP": 89500.0, "THB": 35.5, "MYR": 4.7,
        "SGD": 1.35, "PHP": 56.5, "IDR": 15700.0, "VND": 25000.0, "CHF": 0.88,
        "SEK": 10.8, "NOK": 10.9, "DKK": 6.9, "PLN": 4.0, "CZK": 23.0,
        "HUF": 360.0, "RON": 4.6, "BGN": 1.8, "HRK": 7.0, "RUB": 92.0,
        "UAH": 41.0, "ILS": 3.7, "CLP": 950.0, "COP": 3950.0, "PEN": 3.7,
        "ARS": 870.0, "TWD": 31.5, "HKD": 7.82,
    }
    rate = USD_RATES.get(company_currency, 1.0)

    # Convert revenue from company currency to USD for ROI/profit calculation
    revenue_in_usd = round(total_revenue / rate, 2) if rate else total_revenue

    # ROI = ((revenue - cost) / cost) * 100, rounded to 3 s.f.
    if total_cost > 0:
        roi_raw = ((revenue_in_usd - total_cost) / total_cost) * 100
        if roi_raw != 0:
            from math import log10, floor
            magnitude = floor(log10(abs(roi_raw)))
            roi = round(roi_raw, -int(magnitude) + 2)
        else:
            roi = 0
    else:
        roi = 0

    # Profit in company currency: revenue (already in company currency) - cost converted to company currency
    profit = round(total_revenue - (total_cost * rate), 2)

    return {
        "money_generated": round(total_revenue, 2),
        "plan_cost": current_plan_cost,          # always USD
        "total_cost": round(total_cost, 2),       # always USD
        "plan": plan,
        "roi": roi,
        "profit": profit,                         # in company currency
        "total_sessions": total_sessions,
        "total_bookings": total_bookings,
        "currency": company_currency,
        "currency_symbol": currency_symbol,
    }


def get_roi_stats(admin_id, date_range="month"):
    """Get comprehensive ROI stats with daily revenue, funnel, loss metrics, AI insights."""
    from datetime import datetime as _dt, timedelta
    from math import log10, floor

    company_type = get_company_type(admin_id)
    is_ecom = company_type == "ecommerce"

    conn = get_db()
    now = _dt.now()

    # --- Date boundaries (include future bookings within the period) ---
    import calendar
    if date_range == "all":
        date_from = "2000-01-01"
        date_to = "2099-12-31"
        prev_from = "1999-01-01"
        prev_to = "1999-12-31"
    elif date_range == "today":
        date_from = now.strftime("%Y-%m-%d")
        date_to = date_from
        prev_from = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        prev_to = prev_from
    elif date_range == "week":
        date_from = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        date_to = (now - timedelta(days=now.weekday()) + timedelta(days=6)).strftime("%Y-%m-%d")
        prev_from = (now - timedelta(days=now.weekday() + 7)).strftime("%Y-%m-%d")
        prev_to = (now - timedelta(days=now.weekday() + 1)).strftime("%Y-%m-%d")
    elif date_range == "year":
        date_from = f"{now.year}-01-01"
        date_to = f"{now.year}-12-31"
        prev_from = f"{now.year - 1}-01-01"
        prev_to = f"{now.year - 1}-12-31"
    else:  # month (default)
        date_from = now.strftime("%Y-%m-01")
        last_day = calendar.monthrange(now.year, now.month)[1]
        date_to = now.strftime(f"%Y-%m-{last_day:02d}")
        first_of_prev = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
        prev_from = first_of_prev.strftime("%Y-%m-%d")
        prev_to = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m-%d")

    # --- Currency setup ---
    company_currency = get_company_currency(admin_id)
    # Always use currency code (SAR, USD, EUR etc.) — no Arabic/special symbols
    USD_RATES = {
        "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "SAR": 3.75, "AED": 3.67,
        "EGP": 50.0, "JOD": 0.71, "KWD": 0.31, "BHD": 0.38, "QAR": 3.64,
        "OMR": 0.38, "TRY": 32.0, "INR": 83.5, "PKR": 278.0, "JPY": 154.0,
        "CNY": 7.25, "KRW": 1340.0, "BRL": 5.0, "MXN": 17.2, "CAD": 1.37,
        "AUD": 1.55, "NZD": 1.67, "ZAR": 18.5, "NGN": 1550.0, "KES": 153.0,
        "MAD": 10.0, "IQD": 1310.0, "LBP": 89500.0, "THB": 35.5, "MYR": 4.7,
        "SGD": 1.35, "PHP": 56.5, "IDR": 15700.0, "VND": 25000.0, "CHF": 0.88,
        "SEK": 10.8, "NOK": 10.9, "DKK": 6.9, "PLN": 4.0, "CZK": 23.0,
        "HUF": 360.0, "RON": 4.6, "BGN": 1.8, "HRK": 7.0, "RUB": 92.0,
        "UAH": 41.0, "ILS": 3.7, "CLP": 950.0, "COP": 3950.0, "PEN": 3.7,
        "ARS": 870.0, "TWD": 31.5, "HKD": 7.82,
    }
    rate = USD_RATES.get(company_currency, 1.0)
    currency_symbol = company_currency + " "

    # Build a service price lookup from company_services for this admin
    svc_prices = {}
    if not is_ecom:
        svc_rows = conn.execute(
            "SELECT LOWER(name) as name, price FROM company_services WHERE admin_id=%s", (admin_id,)
        ).fetchall()
        for sr in svc_rows:
            svc_prices[sr["name"]] = sr["price"]

    def calc_booking_revenue(rev_amount, service_name):
        """Return revenue: use revenue_amount if set, else lookup service price."""
        if rev_amount and rev_amount > 0:
            return rev_amount
        return svc_prices.get((service_name or "").lower(), 0)

    # ── 1. Daily revenue chart data ──
    if is_ecom:
        daily_rows = conn.execute(
            "SELECT created_at::date as date, order_total "
            "FROM ecom_orders WHERE admin_id=%s AND order_status NOT IN ('cancelled','refunded') "
            "AND created_at::date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchall()
        daily_map = {}
        for r in daily_rows:
            d = str(r["date"])
            rev = float(r["order_total"] or 0)
            if d not in daily_map:
                daily_map[d] = {"revenue": 0, "bookings": 0}
            daily_map[d]["revenue"] += rev
            daily_map[d]["bookings"] += 1
    else:
        daily_rows = conn.execute(
            "SELECT date, service, revenue_amount "
            "FROM bookings WHERE admin_id=%s AND status IN ('confirmed','completed') "
            "AND date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchall()
        daily_map = {}
        for r in daily_rows:
            d = r["date"]
            rev = calc_booking_revenue(r["revenue_amount"], r["service"])
            if d not in daily_map:
                daily_map[d] = {"revenue": 0, "bookings": 0}
            daily_map[d]["revenue"] += rev
            daily_map[d]["bookings"] += 1
    daily_revenue = [{"date": d, "revenue": round(v["revenue"], 2), "bookings": v["bookings"]}
                     for d, v in sorted(daily_map.items())]

    # ── 2. Current period totals ──
    total_revenue = sum(d["revenue"] for d in daily_revenue)
    total_bookings = sum(d["bookings"] for d in daily_revenue)

    # Previous period for comparison
    if is_ecom:
        prev_rows = conn.execute(
            "SELECT order_total FROM ecom_orders "
            "WHERE admin_id=%s AND order_status NOT IN ('cancelled','refunded') "
            "AND created_at::date BETWEEN %s AND %s",
            (admin_id, prev_from, prev_to)
        ).fetchall()
        prev_revenue = sum(float(r["order_total"] or 0) for r in prev_rows)
        prev_bookings = len(prev_rows)
    else:
        prev_rows = conn.execute(
            "SELECT service, revenue_amount "
            "FROM bookings WHERE admin_id=%s AND status IN ('confirmed','completed') "
            "AND date BETWEEN %s AND %s",
            (admin_id, prev_from, prev_to)
        ).fetchall()
        prev_revenue = sum(calc_booking_revenue(r["revenue_amount"], r["service"]) for r in prev_rows)
        prev_bookings = len(prev_rows)
    rev_change = ((total_revenue - prev_revenue) / prev_revenue * 100) if prev_revenue > 0 else 0
    bk_change = ((total_bookings - prev_bookings) / prev_bookings * 100) if prev_bookings > 0 else 0

    avg_booking_value = round(total_revenue / total_bookings, 2) if total_bookings > 0 else 0

    # ── 3. Plan cost & ROI ──
    plan_row = conn.execute("SELECT plan FROM users WHERE id=%s", (admin_id,)).fetchone()
    plan = plan_row["plan"] if plan_row else "free_trial"
    current_plan_cost = PLAN_COSTS.get(plan, 0)

    # Calculate all-time total cost from plan history
    history_rows = conn.execute(
        "SELECT plan, monthly_cost, started_at FROM plan_history WHERE user_id=%s ORDER BY started_at",
        (admin_id,)
    ).fetchall()
    alltime_cost = 0
    if history_rows:
        from math import ceil as _ceil
        for i, h in enumerate(history_rows):
            start = _parse_dt(h["started_at"]) if h["started_at"] else _dt.now()
            if i + 1 < len(history_rows):
                end = _parse_dt(history_rows[i + 1]["started_at"])
            else:
                end = _dt.now()
            days_on_plan = max(0, (end - start).days)
            billing_months = max(1, _ceil(days_on_plan / 30))
            alltime_cost += float(h["monthly_cost"] or 0) * billing_months
    elif current_plan_cost > 0:
        alltime_cost = current_plan_cost

    # Calculate proportional cost for the selected range
    first_started = None
    if history_rows and history_rows[0]["started_at"]:
        first_started = _parse_dt(history_rows[0]["started_at"])
    if not first_started:
        user_row = conn.execute("SELECT created_at FROM users WHERE id=%s", (admin_id,)).fetchone()
        if user_row and user_row["created_at"]:
            try:
                first_started = _parse_dt(user_row["created_at"])
            except Exception:
                first_started = now
        else:
            first_started = now
    total_days_on_platform = max(1, (now - first_started).days)

    if date_range == "all":
        total_cost = alltime_cost
    else:
        dt_from = _dt.strptime(date_from, "%Y-%m-%d")
        dt_to = _dt.strptime(date_to, "%Y-%m-%d")
        range_days = max(1, (dt_to - dt_from).days + 1)
        # Proportional share: alltime_cost × (range_days / total_days)
        total_cost = round(alltime_cost * (range_days / total_days_on_platform), 2)
        # Never exceed alltime_cost
        total_cost = min(total_cost, alltime_cost)

    revenue_in_usd = round(total_revenue / rate, 2) if rate else total_revenue
    if total_cost > 0:
        roi_raw = ((revenue_in_usd - total_cost) / total_cost) * 100
        if roi_raw != 0:
            magnitude = floor(log10(abs(roi_raw)))
            roi = round(roi_raw, -int(magnitude) + 2)
        else:
            roi = 0
        roi_multiple = round(revenue_in_usd / total_cost, 2)
    else:
        roi = 0
        roi_multiple = 0

    profit = round(total_revenue - (total_cost * rate), 2)

    # ── 4. Conversion Funnel ──
    # Visitors = distinct sessions that sent at least one message to chatbot
    visitors_row = conn.execute(
        "SELECT COUNT(DISTINCT session_id) as c FROM chat_logs "
        "WHERE admin_id=%s AND created_at::date BETWEEN %s AND %s",
        (admin_id, date_from, date_to)
    ).fetchone()
    visitors = visitors_row["c"] if visitors_row else 0

    # Chats started = same as visitors (each session = one visitor who chatted)
    chats_started = visitors

    # Leads captured = distinct sessions where user shared contact info (resulted in a lead or booking)
    leads_row = conn.execute(
        "SELECT COUNT(*) as c FROM leads "
        "WHERE admin_id=%s AND created_at::date BETWEEN %s AND %s",
        (admin_id, date_from, date_to)
    ).fetchone()
    leads_captured = leads_row["c"] if leads_row else 0

    if is_ecom:
        # E-commerce funnel: visitors → leads → orders (delivered) → all orders placed
        orders_placed_row = conn.execute(
            "SELECT COUNT(*) as c FROM ecom_orders "
            "WHERE admin_id=%s AND order_status NOT IN ('cancelled','refunded') "
            "AND created_at::date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchone()
        bookings_made = orders_placed_row["c"] if orders_placed_row else 0

        delivered_row = conn.execute(
            "SELECT COUNT(*) as c FROM ecom_orders "
            "WHERE admin_id=%s AND order_status='delivered' "
            "AND created_at::date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchone()
        bookings_completed = delivered_row["c"] if delivered_row else 0
    else:
        # Bookings completed (status = completed)
        completed_row = conn.execute(
            "SELECT COUNT(*) as c FROM bookings "
            "WHERE admin_id=%s AND status='completed' AND date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchone()
        bookings_completed = completed_row["c"] if completed_row else 0

        # Bookings made (confirmed + completed, not cancelled/no_show)
        bookings_made_row = conn.execute(
            "SELECT COUNT(*) as c FROM bookings "
            "WHERE admin_id=%s AND status IN ('confirmed','completed') AND date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchone()
        bookings_made = bookings_made_row["c"] if bookings_made_row else 0

    # AI success rate — chatbot-attributed bookings
    if is_ecom:
        ai_bookings = bookings_made
        ai_success_rate = round((ai_bookings / visitors * 100), 1) if visitors > 0 else 0
    else:
        ai_booking_row = conn.execute(
            "SELECT COUNT(DISTINCT session_id) as c FROM chat_logs "
            "WHERE admin_id=%s AND resulted_in_booking=1 AND created_at::date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchone()
        ai_bookings = ai_booking_row["c"] if ai_booking_row else 0
        ai_success_rate = round((ai_bookings / visitors * 100), 1) if visitors > 0 else 0

    # Conversion rates — use chatbot-attributed bookings for funnel rates
    # If no chatbot attribution data, fall back to total bookings but cap at 100%
    funnel_bookings = ai_bookings if ai_bookings > 0 else bookings_made
    visitor_to_chat = 100.0  # every visitor IS a chat (they opened chatbot)
    chat_to_lead = min(round((leads_captured / chats_started * 100), 1), 100.0) if chats_started > 0 else 0
    lead_to_booking = min(round((funnel_bookings / leads_captured * 100), 1), 100.0) if leads_captured > 0 else 0
    bookings_per_100 = min(round((funnel_bookings / chats_started * 100), 1), 100.0) if chats_started > 0 else 0

    # ── 5. Loss Metrics ──
    if is_ecom:
        # E-commerce: cancelled + refunded orders
        lost_rows = conn.execute(
            "SELECT created_at::date as date, order_status, order_total "
            "FROM ecom_orders WHERE admin_id=%s AND order_status IN ('cancelled','refunded') "
            "AND created_at::date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchall()
        cancel_count = sum(1 for r in lost_rows if r["order_status"] == "cancelled")
        noshow_count = sum(1 for r in lost_rows if r["order_status"] == "refunded")  # refunded mapped to noshow slot
        total_lost_count = len(lost_rows)

        all_orders_row = conn.execute(
            "SELECT COUNT(*) as c FROM ecom_orders WHERE admin_id=%s AND created_at::date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchone()
        all_bookings_count = all_orders_row["c"] if all_orders_row else 0

        total_revenue_lost = 0
        daily_loss_map = {}
        for r in lost_rows:
            rev = float(r["order_total"] or 0)
            total_revenue_lost += rev
            d = str(r["date"])
            if d not in daily_loss_map:
                daily_loss_map[d] = {"noshows": 0, "cancellations": 0, "revenue_lost": 0}
            if r["order_status"] == "refunded":
                daily_loss_map[d]["noshows"] += 1
            else:
                daily_loss_map[d]["cancellations"] += 1
            daily_loss_map[d]["revenue_lost"] += rev
        total_revenue_lost = round(total_revenue_lost, 2)
    else:
        # Dental: no-shows + cancellations
        lost_rows = conn.execute(
            "SELECT date, status, service, revenue_amount, cancelled_at "
            "FROM bookings WHERE admin_id=%s AND status IN ('no_show','cancelled') "
            "AND (CASE "
            "  WHEN status='cancelled' AND cancelled_at IS NOT NULL THEN cancelled_at::date::text "
            "  ELSE date "
            "END) BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchall()
        cancel_count = sum(1 for r in lost_rows if r["status"] == "cancelled")
        noshow_count = sum(1 for r in lost_rows if r["status"] == "no_show")
        total_lost_count = len(lost_rows)

        all_bookings_row = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchone()
        all_bookings_count = all_bookings_row["c"] if all_bookings_row else 0

        total_revenue_lost = 0
        daily_loss_map = {}
        for r in lost_rows:
            rev = calc_booking_revenue(r["revenue_amount"], r["service"]) or avg_booking_value
            total_revenue_lost += rev
            if r["status"] == "cancelled" and r["cancelled_at"]:
                d = r["cancelled_at"][:10]
            else:
                d = r["date"]
            if d not in daily_loss_map:
                daily_loss_map[d] = {"noshows": 0, "cancellations": 0, "revenue_lost": 0}
            if r["status"] == "no_show":
                daily_loss_map[d]["noshows"] += 1
            else:
                daily_loss_map[d]["cancellations"] += 1
            daily_loss_map[d]["revenue_lost"] += rev
        total_revenue_lost = round(total_revenue_lost, 2)

    noshow_rate = round((noshow_count / all_bookings_count * 100), 1) if all_bookings_count > 0 else 0
    cancel_rate = round((cancel_count / all_bookings_count * 100), 1) if all_bookings_count > 0 else 0
    total_lost_rate = round((total_lost_count / all_bookings_count * 100), 1) if all_bookings_count > 0 else 0

    daily_losses = [{"date": d, "noshows": v["noshows"], "cancellations": v["cancellations"],
                     "revenue_lost": round(v["revenue_lost"], 2)}
                    for d, v in sorted(daily_loss_map.items())]

    # ── 6. AI Insights (real data) ──
    if is_ecom:
        # E-commerce: previous period losses
        prev_lost = conn.execute(
            "SELECT COUNT(*) as c FROM ecom_orders WHERE admin_id=%s AND order_status IN ('cancelled','refunded') AND created_at::date BETWEEN %s AND %s",
            (admin_id, prev_from, prev_to)
        ).fetchone()
        prev_lost_count = prev_lost["c"] if prev_lost else 0
        prev_noshow_count = 0  # no no-shows in ecom
        noshow_change = 0

        # Top revenue product — parse items_json
        import json as _json
        prod_rows = conn.execute(
            "SELECT items_json, order_total FROM ecom_orders "
            "WHERE admin_id=%s AND order_status NOT IN ('cancelled','refunded') "
            "AND created_at::date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchall()
        prod_agg = {}
        for r in prod_rows:
            try:
                items = _json.loads(r["items_json"] or "[]") if isinstance(r["items_json"], str) else (r["items_json"] or [])
            except Exception:
                items = []
            for it in items:
                name = it.get("name") or it.get("title") or "Unknown"
                qty = int(it.get("qty") or it.get("quantity") or 1)
                price = float(it.get("price") or 0)
                if name not in prod_agg:
                    prod_agg[name] = {"rev": 0, "cnt": 0}
                prod_agg[name]["rev"] += price * qty
                prod_agg[name]["cnt"] += qty
        if prod_agg:
            top_prod = max(prod_agg.items(), key=lambda x: x[1]["rev"])
            top_service_name = top_prod[0]
            top_service_revenue = round(top_prod[1]["rev"], 2)
            top_service_count = top_prod[1]["cnt"]
        else:
            top_service_name = "N/A"
            top_service_revenue = 0
            top_service_count = 0

        # Peak order hour
        peak_hours_rows = conn.execute(
            "SELECT EXTRACT(HOUR FROM created_at)::int as hour, COUNT(*) as cnt "
            "FROM ecom_orders WHERE admin_id=%s AND order_status NOT IN ('cancelled','refunded') "
            "AND created_at::date BETWEEN %s AND %s GROUP BY hour ORDER BY cnt DESC LIMIT 3",
            (admin_id, date_from, date_to)
        ).fetchall()
        peak_hours = []
        for ph in peak_hours_rows:
            try:
                h = int(ph["hour"])
                if h < 12:
                    label = f"{h} AM–{h+1} AM"
                elif h == 12:
                    label = "12–1 PM"
                else:
                    label = f"{h-12} PM–{h-11} PM"
                peak_hours.append({"hour": label, "count": ph["cnt"]})
            except (ValueError, TypeError):
                peak_hours.append({"hour": str(ph["hour"]), "count": ph["cnt"]})

        # Build ecommerce insight sentences
        insights_sentences = []
        if top_service_name != "N/A":
            insights_sentences.append(f"Top selling product: {top_service_name} ({currency_symbol}{top_service_revenue:,.0f}, {top_service_count} sold)")
        if peak_hours:
            insights_sentences.append(f"Peak order time: {peak_hours[0]['hour']} ({peak_hours[0]['count']} orders)")
        if total_bookings > 0 and prev_bookings > 0:
            if bk_change > 0:
                insights_sentences.append(f"Orders grew {bk_change:.1f}% compared to last period")
            elif bk_change < 0:
                insights_sentences.append(f"Orders declined {abs(bk_change):.1f}% compared to last period")
        if visitors > 0:
            insights_sentences.append(f"Chatbot engaged {visitors} visitors, {ai_success_rate}% converted to orders")
        if cancel_count > 0:
            insights_sentences.append(f"{cancel_count} cancelled order{'s' if cancel_count != 1 else ''} — {currency_symbol}{total_revenue_lost:,.0f} in lost revenue")
        if noshow_count > 0:
            insights_sentences.append(f"{noshow_count} refunded order{'s' if noshow_count != 1 else ''}")
        if avg_booking_value > 0:
            insights_sentences.append(f"Average order value: {currency_symbol}{avg_booking_value:,.0f}")
        if total_lost_rate > 15:
            insights_sentences.append(f"Loss rate is {total_lost_rate}% — consider improving product descriptions or policies")
    else:
        # Dental insights
        prev_lost = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND status IN ('no_show','cancelled') AND date BETWEEN %s AND %s",
            (admin_id, prev_from, prev_to)
        ).fetchone()
        prev_lost_count = prev_lost["c"] if prev_lost else 0
        prev_noshow = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND status='no_show' AND date BETWEEN %s AND %s",
            (admin_id, prev_from, prev_to)
        ).fetchone()
        prev_noshow_count = prev_noshow["c"] if prev_noshow else 0
        noshow_change = round(((noshow_count - prev_noshow_count) / prev_noshow_count * 100), 1) if prev_noshow_count > 0 else 0

        # Top revenue service
        svc_agg_rows = conn.execute(
            "SELECT service, revenue_amount FROM bookings "
            "WHERE admin_id=%s AND status IN ('confirmed','completed') AND date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchall()
        svc_agg = {}
        for r in svc_agg_rows:
            s = r["service"]
            rev = calc_booking_revenue(r["revenue_amount"], s)
            if s not in svc_agg:
                svc_agg[s] = {"rev": 0, "cnt": 0}
            svc_agg[s]["rev"] += rev
            svc_agg[s]["cnt"] += 1
        if svc_agg:
            top_svc = max(svc_agg.items(), key=lambda x: x[1]["rev"])
            top_service_name = top_svc[0]
            top_service_revenue = round(top_svc[1]["rev"], 2)
            top_service_count = top_svc[1]["cnt"]
        else:
            top_service_name = "N/A"
            top_service_revenue = 0
            top_service_count = 0

        # Peak booking hour
        peak_hours_rows = conn.execute(
            "SELECT substr(time, 1, 2) as hour, COUNT(*) as cnt "
            "FROM bookings WHERE admin_id=%s AND status IN ('confirmed','completed') "
            "AND date BETWEEN %s AND %s GROUP BY hour ORDER BY cnt DESC LIMIT 3",
            (admin_id, date_from, date_to)
        ).fetchall()
        peak_hours = []
        for ph in peak_hours_rows:
            try:
                h = int(ph["hour"])
                if h < 12:
                    label = f"{h} AM–{h+1} AM"
                elif h == 12:
                    label = "12–1 PM"
                else:
                    label = f"{h-12} PM–{h-11} PM"
                peak_hours.append({"hour": label, "count": ph["cnt"]})
            except (ValueError, TypeError):
                peak_hours.append({"hour": ph["hour"], "count": ph["cnt"]})

        # Build dental insight sentences
        insights_sentences = []
        if prev_noshow_count > 0 and noshow_change != 0:
            direction = "decreased" if noshow_change < 0 else "increased"
            insights_sentences.append(f"No-shows {direction} by {abs(noshow_change)}% compared to last period")
        if top_service_name != "N/A":
            insights_sentences.append(f"Most revenue came from {top_service_name} ({currency_symbol}{top_service_revenue:,.0f})")
        if peak_hours:
            insights_sentences.append(f"Peak booking time: {peak_hours[0]['hour']} ({peak_hours[0]['count']} bookings)")
        if total_bookings > 0 and prev_bookings > 0:
            if bk_change > 0:
                insights_sentences.append(f"Bookings grew {bk_change:.1f}% compared to last period")
            elif bk_change < 0:
                insights_sentences.append(f"Bookings declined {abs(bk_change):.1f}% compared to last period")
        if visitors > 0:
            insights_sentences.append(f"AI successfully booked {ai_success_rate}% of chatbot visitors")
        if noshow_count == 0 and all_bookings_count > 0:
            insights_sentences.append("Zero no-shows this period — great patient commitment!")
        if cancel_count > 0:
            insights_sentences.append(f"{cancel_count} cancelled appointment{'s' if cancel_count != 1 else ''} — {currency_symbol}{total_revenue_lost:,.0f} in potential revenue lost")
        if total_lost_rate > 20:
            insights_sentences.append(f"Loss rate is {total_lost_rate}% — consider sending more reminders to reduce cancellations")

    # ── 7. Customer/Patient Metrics ──
    if is_ecom:
        # E-commerce: unique customers from orders
        new_cust_row = conn.execute(
            "SELECT COUNT(DISTINCT customer_email) as c FROM ecom_orders "
            "WHERE admin_id=%s AND customer_email != '' AND created_at::date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchone()
        new_patients = new_cust_row["c"] if new_cust_row else 0

        # Returning customers
        returning_row = conn.execute(
            "SELECT COUNT(DISTINCT customer_email) as c FROM ecom_orders "
            "WHERE admin_id=%s AND customer_email != '' AND created_at::date BETWEEN %s AND %s "
            "AND customer_email IN (SELECT customer_email FROM ecom_orders WHERE admin_id=%s "
            "AND customer_email != '' AND created_at::date < %s)",
            (admin_id, date_from, date_to, admin_id, date_from)
        ).fetchone()
        returning_patients = returning_row["c"] if returning_row else 0

        # Avg orders per customer
        avg_visits_row = conn.execute(
            "SELECT AVG(order_count) as avg_v FROM ("
            "SELECT customer_email, COUNT(*) as order_count FROM ecom_orders "
            "WHERE admin_id=%s AND customer_email != '' AND order_status NOT IN ('cancelled','refunded') "
            "AND created_at::date BETWEEN %s AND %s GROUP BY customer_email) sub",
            (admin_id, date_from, date_to)
        ).fetchone()
        avg_visits = round(float(avg_visits_row["avg_v"]), 1) if avg_visits_row and avg_visits_row["avg_v"] else 0
    else:
        new_patients_row = conn.execute(
            "SELECT COUNT(*) as c FROM patients WHERE admin_id=%s AND created_at::date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchone()
        new_patients = new_patients_row["c"] if new_patients_row else 0

        returning_row = conn.execute(
            "SELECT COUNT(DISTINCT customer_email) as c FROM bookings "
            "WHERE admin_id=%s AND status='completed' AND date BETWEEN %s AND %s "
            "AND customer_email IN (SELECT customer_email FROM bookings WHERE admin_id=%s AND status='completed' "
            "AND date < %s AND customer_email != '')",
            (admin_id, date_from, date_to, admin_id, date_from)
        ).fetchone()
        returning_patients = returning_row["c"] if returning_row else 0

        avg_visits_row = conn.execute(
            "SELECT AVG(visit_count) as avg_v FROM ("
            "SELECT customer_email, COUNT(*) as visit_count FROM bookings "
            "WHERE admin_id=%s AND status IN ('confirmed','completed') AND customer_email != '' "
            "AND date BETWEEN %s AND %s GROUP BY customer_email) sub",
            (admin_id, date_from, date_to)
        ).fetchone()
        avg_visits = round(float(avg_visits_row["avg_v"]), 1) if avg_visits_row and avg_visits_row["avg_v"] else 0

    # ── 8. Automation stats ──
    if is_ecom:
        # For ecommerce, all orders are "automated" (placed via integration)
        automated_bookings = total_bookings
        automation_rate = 100.0 if total_bookings > 0 else 0
    else:
        auto_bookings_row = conn.execute(
            "SELECT COUNT(DISTINCT session_id) as c FROM chat_logs "
            "WHERE admin_id=%s AND resulted_in_booking=1 AND created_at::date BETWEEN %s AND %s",
            (admin_id, date_from, date_to)
        ).fetchone()
        automated_bookings = auto_bookings_row["c"] if auto_bookings_row else 0
        automation_rate = round((automated_bookings / total_bookings * 100), 1) if total_bookings > 0 else 0

    # Staff time saved: estimate 5 min per automated interaction
    staff_time_saved = round(visitors * 5 / 60, 1)

    conn.close()

    return {
        "is_ecom": is_ecom,
        "currency": company_currency,
        "currency_symbol": currency_symbol,
        "date_from": date_from,
        "date_to": date_to,
        "roi": {
            "multiple": roi_multiple,
            "percentage": roi,
            "monthly_cost": current_plan_cost,
            "total_cost": round(total_cost, 2),
            "profit": profit,
            "savings_total": round(staff_time_saved * 25, 2),  # $25/hr staff cost estimate
        },
        "revenue": {
            "total_generated": round(total_revenue, 2),
            "chatbot_revenue": round(total_revenue, 2),  # all revenue via chatbot platform
            "avg_booking_value": avg_booking_value,
            "total_bookings": total_bookings,
            "daily": daily_revenue,
        },
        "period_comparison": {
            "revenue_change_pct": round(rev_change, 1),
            "bookings_change_pct": round(bk_change, 1),
        },
        "funnel": {
            "visitors": visitors,
            "chats_started": chats_started,
            "leads_captured": leads_captured,
            "bookings_made": funnel_bookings,
            "total_bookings_all": bookings_made,
            "bookings_completed": bookings_completed,
            "visitor_to_chat_pct": visitor_to_chat,
            "chat_to_lead_pct": chat_to_lead,
            "lead_to_booking_pct": lead_to_booking,
            "bookings_per_100_conversations": bookings_per_100,
            "ai_success_rate": ai_success_rate,
            "revenue": round(total_revenue, 2),
        },
        "loss_metrics": {
            "noshow_count": noshow_count,
            "noshow_rate": noshow_rate,
            "cancel_count": cancel_count,
            "cancel_rate": cancel_rate,
            "total_lost_count": total_lost_count,
            "total_lost_rate": total_lost_rate,
            "revenue_lost": total_revenue_lost,
            "daily_losses": daily_losses,
        },
        "insights": {
            "sentences": insights_sentences,
            "top_service": {"name": top_service_name, "revenue": top_service_revenue, "count": top_service_count},
            "peak_booking_hours": peak_hours,
            "noshow_change_pct": noshow_change,
        },
        "patients": {
            "new_patients": new_patients,
            "returning_patients": returning_patients,
            "avg_visits_per_patient": avg_visits,
        },
        "automation": {
            "automated_bookings": automated_bookings,
            "automation_rate": automation_rate,
            "total_bookings": total_bookings,
            "lead_conversions": leads_captured,
            "staff_time_saved_hours": staff_time_saved,
        },
    }


# ══════════════════════════════════════════════
#  User Authentication
# ══════════════════════════════════════════════

def _parse_dt(val):
    """Parse a datetime value that may be a string or datetime object (PostgreSQL)."""
    if isinstance(val, datetime):
        return val
    return datetime.strptime(val, "%Y-%m-%d %H:%M:%S")


def _hash_password(password):
    """Hash password with bcrypt (12 rounds)."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def _verify_password(password, password_hash):
    """Verify password against bcrypt hash. Also handles legacy SHA256 migration."""
    if not password or not password_hash:
        return False
    # Legacy SHA256 check (for existing accounts before bcrypt migration)
    if len(password_hash) == 64 and not password_hash.startswith('$2b$'):
        legacy_salt = "chatgenius_salt_2026"
        legacy_hash = hashlib.sha256((password + legacy_salt).encode()).hexdigest()
        if hmac.compare_digest(legacy_hash, password_hash):
            return True  # caller should re-hash with bcrypt
        return False
    # bcrypt check
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except (ValueError, TypeError):
        return False


def _generate_token():
    return secrets.token_hex(32)


def _token_expiry():
    return (datetime.now() + TOKEN_LIFETIME).strftime("%Y-%m-%d %H:%M:%S")


def create_user(name, email, password="", company="", provider="email", provider_id="", role="admin", specialty=""):
    import uuid as _uuid
    import secrets
    conn = get_db()
    token = _generate_token()
    expires = _token_expiry()
    password_hash = _hash_password(password) if password else ""
    public_id = str(_uuid.uuid4())
    # Email signups require verification; social auth is auto-verified
    is_verified = 0 if provider == "email" else 1
    verification_code = ""
    verification_code_expires = ""
    if not is_verified:
        verification_code = str(secrets.randbelow(900000) + 100000)
        verification_code_expires = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    # Check if email is already taken and give a specific error message
    existing = conn.execute("SELECT provider FROM users WHERE email = %s", (email,)).fetchone()
    if existing:
        existing_provider = existing["provider"]
        conn.close()
        if existing_provider in ("google", "facebook", "apple"):
            provider_name = existing_provider.capitalize()
            return None, f"This email is already linked to a {provider_name} account. Please sign in with {provider_name} instead."
        return None, "An account with this email already exists."

    # 14-day free trial expiry
    trial_expires = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    trial_started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn.execute(
            """INSERT INTO users (name, email, password_hash, company, role, plan, plan_started_at, plan_expires_at, provider, provider_id, token, token_expires_at, specialty, public_id, is_verified, verification_code, verification_code_expires)
               VALUES (%s, %s, %s, %s, %s, 'free_trial', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (name, email, password_hash, company, role, trial_started, trial_expires, provider, provider_id, token, expires, specialty, public_id, is_verified, verification_code, verification_code_expires)
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
        conn.close()
        return dict(user), None
    except psycopg2.IntegrityError:
        conn.close()
        return None, "An account with this email already exists."


def verify_user_code(email, code):
    """Verify the 6-digit signup code. Returns (user, error)."""
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
    if not user:
        conn.close()
        return None, "Account not found."
    user = dict(user)
    if user.get("is_verified", 1) == 1:
        conn.close()
        return user, None  # Already verified
    if user.get("verification_code") != code:
        conn.close()
        return None, "Invalid verification code."
    if user.get("verification_code_expires"):
        exp = _parse_dt(user["verification_code_expires"])
        if datetime.now() > exp:
            conn.close()
            return None, "Verification code has expired. Please request a new one."
    conn.execute("UPDATE users SET is_verified = 1, verification_code = '', verification_code_expires = NULL WHERE id = %s", (user["id"],))
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE id = %s", (user["id"],)).fetchone()
    conn.close()
    return dict(user), None


def resend_verification_code(email):
    """Generate a new verification code for an unverified user. Returns (user, code, error)."""
    import secrets
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
    if not user:
        conn.close()
        return None, None, "Account not found."
    user = dict(user)
    if user.get("is_verified", 1) == 1:
        conn.close()
        return user, None, "Account is already verified."
    new_code = str(secrets.randbelow(900000) + 100000)
    new_expires = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE users SET verification_code = %s, verification_code_expires = %s WHERE id = %s", (new_code, new_expires, user["id"]))
    conn.commit()
    conn.close()
    return user, new_code, None


def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_by_public_id(public_id):
    """Resolve a public GUID to the user record."""
    if not public_id:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE public_id = %s", (public_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def login_user(email, password):
    # ── Account lockout check ──
    email_lower = email.strip().lower()
    lockout = _failed_logins.get(email_lower)
    if lockout and lockout.get("locked_until"):
        if datetime.now() < lockout["locked_until"]:
            remaining = int((lockout["locked_until"] - datetime.now()).total_seconds() // 60) + 1
            return None, f"Account temporarily locked due to too many failed attempts. Try again in {remaining} minutes."
        else:
            _failed_logins.pop(email_lower, None)

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = %s", (email_lower,)).fetchone()
    conn.close()
    if not user:
        return None, "Invalid email or password."
    if user["provider"] != "email":
        return None, f"This account uses {user['provider']} login. Please use the {user['provider'].title()} button."

    # ── Verify password (bcrypt with legacy SHA256 migration) ──
    if not _verify_password(password, user["password_hash"]):
        # Track failed attempt
        if email_lower not in _failed_logins:
            _failed_logins[email_lower] = {"count": 0, "locked_until": None}
        _failed_logins[email_lower]["count"] += 1
        if _failed_logins[email_lower]["count"] >= MAX_LOGIN_ATTEMPTS:
            _failed_logins[email_lower]["locked_until"] = datetime.now() + LOCKOUT_DURATION
            return None, f"Too many failed attempts. Account locked for {LOCKOUT_DURATION.seconds // 60} minutes."
        remaining = MAX_LOGIN_ATTEMPTS - _failed_logins[email_lower]["count"]
        return None, f"Invalid email or password. {remaining} attempt(s) remaining."

    # ── Successful login — clear failed attempts ──
    _failed_logins.pop(email_lower, None)

    # Auto-migrate legacy SHA256 hash to bcrypt
    if user["password_hash"] and len(user["password_hash"]) == 64 and not user["password_hash"].startswith('$2b$'):
        new_hash = _hash_password(password)
        conn = get_db()
        conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user["id"]))
        conn.commit()
        conn.close()

    # Refresh token with expiry
    token = _generate_token()
    expires = _token_expiry()
    conn = get_db()
    conn.execute("UPDATE users SET token = %s, token_expires_at = %s WHERE id = %s", (token, expires, user["id"]))
    conn.commit()
    conn.close()
    user_dict = dict(user)
    user_dict["token"] = token
    user_dict["token_expires_at"] = expires
    return user_dict, None


def login_or_create_social(name, email, provider, provider_id, avatar_url="", role="admin", specialty=""):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
    token = _generate_token()
    expires = _token_expiry()

    if user:
        conn.execute("UPDATE users SET token = %s, token_expires_at = %s, avatar_url = %s WHERE id = %s",
                      (token, expires, avatar_url, user["id"]))
        conn.commit()
        user_dict = dict(user)
        user_dict["token"] = token
        user_dict["token_expires_at"] = expires
        conn.close()
        return user_dict, None
    else:
        import uuid as _uuid
        public_id = str(_uuid.uuid4())
        trial_started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        trial_expires = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO users (name, email, company, role, plan, plan_started_at, plan_expires_at, provider, provider_id, avatar_url, token, token_expires_at, specialty, public_id)
               VALUES (%s, %s, '', %s, 'free_trial', %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (name, email, role, trial_started, trial_expires, provider, provider_id, avatar_url, token, expires, specialty, public_id)
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
        conn.close()
        return dict(user), None


def get_user_by_token(token):
    if not token:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE token = %s", (token,)).fetchone()
    if not user:
        conn.close()
        return None
    # Check if token has expired
    expires = user["token_expires_at"]
    if expires:
        try:
            expires_dt = _parse_dt(expires)
            if datetime.now() > expires_dt:
                conn.execute("UPDATE users SET token = '', token_expires_at = NULL WHERE id = %s", (user["id"],))
                conn.commit()
                conn.close()
                return None
        except (ValueError, TypeError):
            pass
    conn.close()
    return dict(user)


def get_user_by_email(email):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
    conn.close()
    return dict(user) if user else None


def update_user_profile(user_id, name, email, new_password="", avatar_url=None):
    conn = get_db()
    try:
        conn.execute("UPDATE users SET name = %s, email = %s WHERE id = %s", (name, email, user_id))
        if new_password:
            conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", (_hash_password(new_password), user_id))
        if avatar_url is not None:
            conn.execute("UPDATE users SET avatar_url = %s WHERE id = %s", (avatar_url, user_id))
        conn.commit()
        conn.close()
        return True
    except Exception:
        conn.close()
        return False


def set_user_admin_id(user_id, admin_id):
    """Set a user's admin_id (link/unlink from company)."""
    conn = get_db()
    conn.execute("UPDATE users SET admin_id = %s WHERE id = %s", (admin_id, user_id))
    conn.commit()
    conn.close()


PLAN_COSTS = {"free": 0, "free_trial": 0, "basic": 23, "growth": 79, "pro": 299, "enterprise": 699}
PLAN_MONTHLY_CONVERSATIONS = {"free": 50, "free_trial": 999999999, "basic": 999999999, "growth": 999999999, "pro": 999999999, "enterprise": 999999999}
PLAN_MAX_CHATBOTS = {"free": 1, "free_trial": 1, "basic": 1, "growth": 2, "pro": 3, "enterprise": 999999999}
PLAN_MAX_DOCTORS = {"free": 1, "free_trial": 3, "basic": 1, "growth": 3, "pro": 10, "enterprise": 999999999}
PLAN_MAX_LOCATIONS = {"free": 1, "free_trial": 1, "basic": 1, "growth": 1, "pro": 3, "enterprise": 999999999}
PLAN_MAX_STAFF = {"free": 1, "free_trial": 5, "basic": 2, "growth": 5, "pro": 15, "enterprise": 999999999}
PLAN_MAX_PATIENTS = {"free": 20, "free_trial": 999999999, "basic": 999999999, "growth": 999999999, "pro": 999999999, "enterprise": 999999999}
PLAN_MAX_PROMO_CODES = {"free": 0, "free_trial": 10, "basic": 0, "growth": 10, "pro": 999999999, "enterprise": 999999999}
PLAN_MAX_CUSTOM_FIELDS = {"free": 0, "free_trial": 10, "basic": 0, "growth": 10, "pro": 999999999, "enterprise": 999999999}
PLAN_MAX_EMAIL_TEMPLATES = {"free": 0, "free_trial": 10, "basic": 3, "growth": 10, "pro": 999999999, "enterprise": 999999999}
PLAN_MAX_LANGUAGES = {"free": 1, "free_trial": 10, "basic": 3, "growth": 10, "pro": 10, "enterprise": 10}


# ── Plan feature access map ──
# Which features are available on which plans (minimum plan required)
PLAN_FEATURE_ACCESS = {
    # feature_key: minimum plan level (0=free, 1=basic, 2=growth, 3=pro, 4=enterprise)
    "smart_booking": 1,          # Basic+ (Free = date+time only, no doctor choice)
    "doctor_choice": 1,          # Basic+ can choose doctor
    "lead_capture": 1,           # Basic+
    "lead_scoring_advanced": 2,  # Growth+ (Basic = hot/cold only)
    "lead_followups": 2,         # Growth+
    "lead_routing": 2,           # Growth+
    "pre_visit_forms": 1,        # Basic+ (standard fields)
    "custom_form_fields": 2,     # Growth+ (10), Pro+ (unlimited)
    "digital_signatures": 2,     # Growth+
    "sms_reminders": 2,          # Growth+
    "reminder_48h": 2,           # Growth+ (Basic = 24h+2h only)
    "noshow_detection": 2,       # Growth+
    "noshow_prediction": 3,      # Pro+
    "noshow_deposit": 3,         # Pro+
    "waitlist": 2,               # Growth+
    "loyalty_program": 2,        # Growth+
    "referral_program": 2,       # Growth+
    "promotions": 2,             # Growth+
    "invoicing": 2,              # Growth+
    "surveys": 2,                # Growth+
    "google_reviews": 2,         # Growth+
    "roi_dashboard": 2,          # Growth+
    "full_analytics": 2,         # Growth+ (Free = chat count only, Basic = basic)
    "monthly_reports": 2,        # Growth+
    "treatment_followups": 2,    # Growth+
    "treatment_packages": 3,     # Pro+
    "upsell_engine": 3,          # Pro+
    "recall_campaigns": 2,       # Growth+
    "birthday_greetings": 2,     # Growth+
    "doctor_breaks": 2,          # Growth+ (Basic = weekly schedule only)
    "doctor_off_days": 2,        # Growth+
    "schedule_blocks": 2,        # Growth+
    "flexible_lengths": 2,       # Growth+ (Basic = 1 appointment length)
    "daily_overrides": 2,        # Growth+
    "checkin_system": 2,         # Growth+
    "revenue_tracking": 2,       # Growth+
    "patient_medical_history": 2, # Growth+ (Basic = name/phone/email only)
    "patient_insurance": 2,      # Growth+
    "patient_notes": 2,          # Growth+
    "multi_language_10": 2,      # Growth+ (Basic = 3 languages)
    "sentiment_analysis": 2,     # Growth+
    "upsell_detection": 2,       # Growth+
    "patient_recognition": 2,    # Growth+
    "ai_confidence_scoring": 2,  # Growth+
    "gallery": 2,                # Growth+
    "celebration_animation": 2,  # Growth+
    "chatbot_customization": 2,  # Growth+ (Basic = 3 color presets, Free = none)
    "widget_styles": 2,          # Growth+ (all styles)
    "custom_avatar": 2,          # Growth+
    "live_chat_queue": 2,        # Growth+ (Basic = basic handoff only)
    "unified_inbox": 2,          # Growth+ (Web + WhatsApp)
    "whatsapp": 2,               # Growth+
    "google_calendar": 2,        # Growth+
    "calendly": 2,               # Growth+
    "twilio_sms": 2,             # Growth+
    "stripe": 2,                 # Growth+
    "zapier": 2,                 # Growth+
    "rest_api": 2,               # Growth+
    "custom_ai_training": 3,     # Pro+
    "voice_input": 3,            # Pro+
    "white_label": 3,            # Pro+
    "custom_domain": 3,          # Pro+
    "ab_testing": 3,             # Pro+
    "missed_call_handling": 3,   # Pro+
    "own_email_sender": 3,       # Pro+
    "facebook_instagram": 3,     # Pro+ inbox
    "copilot_suggestions": 3,    # Pro+
    "handoff_timeout": 3,        # Pro+
    "conversation_tagging": 3,   # Pro+
    "email_templates": 1,        # Basic+ (3 on Basic, 10 on Growth, unlimited on Pro+)
    "email_template_builder": 3, # Pro+ (drag-and-drop builder)
    "pms_integration": 4,        # Enterprise only
    "emr_integration": 4,        # Enterprise only
    "soc2_hipaa": 4,             # Enterprise only
    "dedicated_manager": 4,      # Enterprise only
    "sla_guarantee": 4,          # Enterprise only
    "custom_development": 4,     # Enterprise only
}

_PLAN_LEVEL_MAP = {"free": 0, "free_trial": 2, "basic": 1, "growth": 2, "pro": 3, "enterprise": 4}


def get_admin_plan(admin_id):
    """Get the plan string for an admin."""
    conn = get_db()
    user = conn.execute("SELECT plan FROM users WHERE id=%s", (admin_id,)).fetchone()
    conn.close()
    return (user["plan"] or "free") if user else "free"


def get_plan_level(plan):
    """Convert plan string to numeric level."""
    p = plan or "free"
    if p == "agency":
        p = "enterprise"
    return _PLAN_LEVEL_MAP.get(p, 0)


def can_use_feature(admin_id, feature_key):
    """Check if admin's plan allows a specific feature. Returns (allowed, plan_required)."""
    plan = get_admin_plan(admin_id)
    level = get_plan_level(plan)
    required_level = PLAN_FEATURE_ACCESS.get(feature_key, 0)
    if level >= required_level:
        return True, None
    # Find the plan name for the required level
    level_to_plan = {0: "free", 1: "basic", 2: "growth", 3: "pro", 4: "enterprise"}
    return False, level_to_plan.get(required_level, "enterprise")


def check_plan_limit(admin_id, limit_type):
    """Check if admin has reached a plan limit. Returns (within_limit, current_count, max_allowed)."""
    plan = get_admin_plan(admin_id)
    conn = get_db()

    if limit_type == "doctors":
        count = conn.execute("SELECT COUNT(*) as c FROM doctors WHERE admin_id=%s AND status='active'", (admin_id,)).fetchone()["c"]
        limit = PLAN_MAX_DOCTORS.get(plan, 1)
    elif limit_type == "staff":
        count = conn.execute("SELECT COUNT(*) as c FROM users WHERE admin_id=%s AND id != %s", (admin_id, admin_id)).fetchone()["c"]
        limit = PLAN_MAX_STAFF.get(plan, 1)
    elif limit_type == "patients":
        count = conn.execute("SELECT COUNT(*) as c FROM patients WHERE admin_id=%s", (admin_id,)).fetchone()["c"]
        limit = PLAN_MAX_PATIENTS.get(plan, 20)
    elif limit_type == "promo_codes":
        count = conn.execute("SELECT COUNT(*) as c FROM promotions WHERE admin_id=%s AND is_active=TRUE", (admin_id,)).fetchone()["c"]
        limit = PLAN_MAX_PROMO_CODES.get(plan, 0)
    elif limit_type == "custom_fields":
        count = conn.execute("SELECT COUNT(*) as c FROM form_custom_fields WHERE admin_id=%s", (admin_id,)).fetchone()["c"]
        limit = PLAN_MAX_CUSTOM_FIELDS.get(plan, 0)
    elif limit_type == "email_templates":
        count = conn.execute("SELECT COUNT(*) as c FROM email_templates WHERE admin_id=%s", (admin_id,)).fetchone()["c"]
        limit = PLAN_MAX_EMAIL_TEMPLATES.get(plan, 0)
    elif limit_type == "chatbots":
        count = len(get_active_chatbot_domains(admin_id))
        limit = PLAN_MAX_CHATBOTS.get(plan, 1)
    else:
        conn.close()
        return True, 0, 999999999

    conn.close()
    return count < limit, count, limit


def get_monthly_conversation_count(admin_id):
    """Count distinct chat sessions for this admin in the current month."""
    conn = get_db()
    now = datetime.now()
    month_start = now.strftime("%Y-%m-01 00:00:00")
    row = conn.execute(
        "SELECT COUNT(DISTINCT session_id) as c FROM chat_logs WHERE admin_id=%s AND created_at >= %s",
        (admin_id, month_start)).fetchone()
    conn.close()
    return row["c"] if row else 0


def get_monthly_message_count(admin_id):
    """Count total chat messages sent TO this admin's chatbot in the current month."""
    conn = get_db()
    now = datetime.now()
    month_start = now.strftime("%Y-%m-01 00:00:00")
    row = conn.execute(
        "SELECT COUNT(*) as c FROM chat_logs WHERE admin_id=%s AND created_at >= %s",
        (admin_id, month_start)).fetchone()
    conn.close()
    return row["c"] if row else 0


def is_conversation_limit_reached(admin_id):
    """Check if admin has exceeded their plan's monthly conversation limit."""
    conn = get_db()
    user = conn.execute("SELECT plan FROM users WHERE id=%s", (admin_id,)).fetchone()
    conn.close()
    if not user:
        return True
    plan = user["plan"] or "free_trial"
    limit = PLAN_MONTHLY_CONVERSATIONS.get(plan, 200)
    count = get_monthly_conversation_count(admin_id)
    return count >= limit


# ── Chatbot domain limit enforcement ──

def get_active_chatbot_domains(admin_id):
    """Get list of active domains where this admin's chatbot is embedded."""
    conn = get_db()
    rows = conn.execute(
        "SELECT domain, first_seen_at, last_seen_at FROM chatbot_active_domains WHERE admin_id=%s AND is_active=1 ORDER BY first_seen_at",
        (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_active_chatbot_domain_count(admin_id):
    """Count active domains for this admin."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM chatbot_active_domains WHERE admin_id=%s AND is_active=1",
        (admin_id,)).fetchone()
    conn.close()
    return row["c"] if row else 0


def register_chatbot_domain(admin_id, domain):
    """Register or update a domain for chatbot usage. Returns (ok, error_msg)."""
    conn = get_db()
    # Check if domain already registered for this admin
    existing = conn.execute(
        "SELECT id, is_active FROM chatbot_active_domains WHERE admin_id=%s AND domain=%s",
        (admin_id, domain)).fetchone()

    if existing:
        # Already registered — update last_seen and ensure active
        conn.execute(
            "UPDATE chatbot_active_domains SET last_seen_at=CURRENT_TIMESTAMP, is_active=1 WHERE id=%s",
            (existing["id"],))
        conn.commit()
        conn.close()
        return True, None

    # New domain — check plan limit
    user = conn.execute("SELECT plan FROM users WHERE id=%s", (admin_id,)).fetchone()
    plan = user["plan"] if user else "free_trial"
    max_chatbots = PLAN_MAX_CHATBOTS.get(plan, 1)

    current_count = conn.execute(
        "SELECT COUNT(*) as c FROM chatbot_active_domains WHERE admin_id=%s AND is_active=1",
        (admin_id,)).fetchone()["c"]

    if current_count >= max_chatbots:
        conn.close()
        plan_name = plan.replace("_", " ").title()
        return False, f"Your {plan_name} plan allows {max_chatbots} chatbot{'s' if max_chatbots > 1 else ''} only. Please upgrade your plan to add more."

    # Register new domain
    conn.execute(
        "INSERT INTO chatbot_active_domains (admin_id, domain) VALUES (%s, %s)",
        (admin_id, domain))
    conn.commit()
    conn.close()
    return True, None


def deactivate_chatbot_domain(admin_id, domain):
    """Deactivate a domain so the admin can use their slot for another domain."""
    conn = get_db()
    conn.execute(
        "UPDATE chatbot_active_domains SET is_active=0 WHERE admin_id=%s AND domain=%s",
        (admin_id, domain))
    conn.commit()
    conn.close()


def update_user_plan(user_id, plan, billing_cycle="monthly"):
    """Activate a plan immediately (used for first-time subscription from free_trial)."""
    from dateutil.relativedelta import relativedelta
    conn = get_db()
    now = datetime.now()
    if plan == "free_trial":
        expires = ""
    elif billing_cycle == "yearly":
        expires = (now + relativedelta(years=1)).strftime("%Y-%m-%d %H:%M:%S")
    else:
        expires = (now + relativedelta(months=1)).strftime("%Y-%m-%d %H:%M:%S")
    started = now.strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE users SET plan=%s, plan_started_at=%s, plan_expires_at=%s, billing_cycle=%s, auto_renew=1, pending_plan='' WHERE id=%s",
        (plan, started, expires, billing_cycle, user_id))
    cost = PLAN_COSTS.get(plan, 0)
    conn.execute("INSERT INTO plan_history (user_id, plan, monthly_cost) VALUES (%s,%s,%s)",
                 (user_id, plan, cost))
    conn.commit()
    conn.close()


def schedule_plan_change(user_id, new_plan):
    """Schedule a plan change for the next billing cycle. Current plan stays active until expiry."""
    conn = get_db()
    conn.execute("UPDATE users SET pending_plan=%s, auto_renew=1 WHERE id=%s", (new_plan, user_id))
    conn.commit()
    conn.close()


def cancel_user_plan(user_id):
    """Cancel subscription. Plan stays active until expiry, then downgrades to free_trial."""
    conn = get_db()
    conn.execute("UPDATE users SET auto_renew=0, pending_plan='free_trial' WHERE id=%s", (user_id,))
    conn.commit()
    conn.close()


def cancel_pending_plan_change(user_id):
    """Remove a scheduled plan change, keeping the current plan as-is."""
    conn = get_db()
    conn.execute("UPDATE users SET pending_plan='' WHERE id=%s", (user_id,))
    conn.commit()
    conn.close()


def toggle_auto_renew(user_id, enabled):
    conn = get_db()
    if enabled:
        # Re-enabling: clear the pending free_trial downgrade
        conn.execute("UPDATE users SET auto_renew=1, pending_plan='' WHERE id=%s", (user_id,))
    else:
        conn.execute("UPDATE users SET auto_renew=0, pending_plan='free_trial' WHERE id=%s", (user_id,))
    conn.commit()
    conn.close()


def process_plan_expiry(user_id):
    """Check if user's plan has expired and apply pending changes.
    Called on login / API access. Returns True if plan was changed."""
    from dateutil.relativedelta import relativedelta
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=%s", (user_id,)).fetchone()
    if not user:
        conn.close()
        return False
    plan = user["plan"] or "free_trial"
    expires = user["plan_expires_at"] or ""
    pending = user["pending_plan"] or ""
    auto_renew = user["auto_renew"]
    billing_cycle = user["billing_cycle"] or "monthly"

    if not expires:
        conn.close()
        return False

    # Free trial expired → downgrade to 'expired_trial'
    if plan == "free_trial":
        now = datetime.now()
        try:
            exp_dt = _parse_dt(expires)
        except (ValueError, TypeError):
            conn.close()
            return False
        if now < exp_dt:
            conn.close()
            return False
        conn.execute(
            "UPDATE users SET plan='expired_trial', plan_started_at='', plan_expires_at='', pending_plan='', auto_renew=0 WHERE id=%s",
            (user_id,))
        conn.commit()
        conn.close()
        return True

    now = datetime.now()
    try:
        exp_dt = _parse_dt(expires)
    except (ValueError, TypeError):
        conn.close()
        return False

    if now < exp_dt:
        conn.close()
        return False  # not expired yet

    # Plan has expired — apply changes
    if pending and pending != plan:
        # Switch to pending plan
        new_plan = pending
    elif not auto_renew:
        # Cancelled — downgrade to free_trial
        new_plan = "free_trial"
    else:
        # Auto-renew: same plan, new period
        new_plan = plan

    if new_plan == "free_trial":
        conn.execute(
            "UPDATE users SET plan='free_trial', plan_started_at='', plan_expires_at='', pending_plan='', auto_renew=1, billing_cycle='monthly' WHERE id=%s",
            (user_id,))
        cost = 0
    else:
        new_started = now.strftime("%Y-%m-%d %H:%M:%S")
        if billing_cycle == "yearly":
            new_expires = (now + relativedelta(years=1)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            new_expires = (now + relativedelta(months=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE users SET plan=%s, plan_started_at=%s, plan_expires_at=%s, pending_plan='', auto_renew=1 WHERE id=%s",
            (new_plan, new_started, new_expires, user_id))
        cost = PLAN_COSTS.get(new_plan, 0)

    conn.execute("INSERT INTO plan_history (user_id, plan, monthly_cost) VALUES (%s,%s,%s)",
                 (user_id, new_plan, cost))
    conn.commit()
    conn.close()
    return True


def get_payment_method(user_id):
    """Get the default payment method for a user."""
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS payment_methods (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        card_last4 TEXT DEFAULT '',
        card_brand TEXT DEFAULT '',
        cardholder_name TEXT DEFAULT '',
        expiry TEXT DEFAULT '',
        is_default INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    row = conn.execute("SELECT * FROM payment_methods WHERE user_id=%s AND is_default=1 ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    conn.close()
    if row:
        return {"card_last4": row["card_last4"], "card_brand": row["card_brand"],
                "cardholder_name": row["cardholder_name"], "expiry": row["expiry"]}
    return None


def save_payment_method(user_id, card_last4="", card_brand="", cardholder_name="", expiry=""):
    """Save or update a user's payment method (card last 4, brand, etc.)."""
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS payment_methods (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        card_last4 TEXT DEFAULT '',
        card_brand TEXT DEFAULT '',
        cardholder_name TEXT DEFAULT '',
        expiry TEXT DEFAULT '',
        is_default INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    # Deactivate old default payment methods
    conn.execute("UPDATE payment_methods SET is_default = 0 WHERE user_id = %s", (user_id,))
    conn.execute(
        "INSERT INTO payment_methods (user_id, card_last4, card_brand, cardholder_name, expiry) VALUES (%s,%s,%s,%s,%s)",
        (user_id, card_last4, card_brand, cardholder_name, expiry))
    conn.commit()
    conn.close()


def user_to_public(user):
    """Return safe user dict (no password hash)."""
    # Admins and doctors inherit the plan from their head_admin
    plan = user["plan"]
    admin_id = user.get("admin_id", 0)
    if user.get("role") in ("admin", "doctor") and admin_id:
        conn = get_db()
        head = conn.execute("SELECT plan FROM users WHERE id = %s", (admin_id,)).fetchone()
        conn.close()
        if head:
            plan = head["plan"]
    result = {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "company": user.get("company", ""),
        "role": user.get("role", "admin"),
        "plan": plan,
        "provider": user["provider"],
        "avatar_url": user.get("avatar_url", ""),
        "admin_id": user.get("admin_id", 0),
        "specialty": user.get("specialty", ""),
        "token_expires_at": user.get("token_expires_at", ""),
        "created_at": user["created_at"],
        "public_id": user.get("public_id", ""),
        "plan_started_at": user.get("plan_started_at", ""),
        "plan_expires_at": user.get("plan_expires_at", ""),
        "billing_cycle": user.get("billing_cycle", "monthly"),
        "auto_renew": user.get("auto_renew", 1),
        "pending_plan": user.get("pending_plan", ""),
    }
    # Include permissions for ecommerce staff
    if user.get("role") == "admin" and admin_id:
        conn2 = get_db()
        head = conn2.execute("SELECT company_type FROM users WHERE id=%s", (admin_id,)).fetchone()
        conn2.close()
        if head and head.get("company_type") == "ecommerce":
            result["permissions"] = get_staff_permissions(admin_id, user["id"])
    return result


# ══════════════════════════════════════════════
#  Company Info
# ══════════════════════════════════════════════

def get_company_info(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM company_info WHERE user_id = %s", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_company_info(user_id, data):
    conn = get_db()
    existing = conn.execute("SELECT id FROM company_info WHERE user_id = %s", (user_id,)).fetchone()
    if existing:
        conn.execute("""UPDATE company_info SET business_name=%s, address=%s, phone=%s, business_hours=%s,
            services=%s, pricing_insurance=%s, emergency_info=%s, about=%s, currency=%s,
            logo_url=%s, store_image=%s, domain=%s, updated_at=CURRENT_TIMESTAMP
            WHERE user_id=%s""",
            (data.get("business_name", ""), data.get("address", ""), data.get("phone", ""),
             data.get("business_hours", ""), data.get("services", ""), data.get("pricing_insurance", ""),
             data.get("emergency_info", ""), data.get("about", ""), data.get("currency", "USD"),
             data.get("logo_url", ""), data.get("store_image", ""), data.get("domain", ""), user_id))
    else:
        conn.execute("""INSERT INTO company_info (user_id, business_name, address, phone, business_hours,
            services, pricing_insurance, emergency_info, about, currency, logo_url, store_image, domain, external_api_key)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (user_id, data.get("business_name", ""), data.get("address", ""), data.get("phone", ""),
             data.get("business_hours", ""), data.get("services", ""), data.get("pricing_insurance", ""),
             data.get("emergency_info", ""), data.get("about", ""), data.get("currency", "USD"),
             data.get("logo_url", ""), data.get("store_image", ""), data.get("domain", ""),
             secrets.token_hex(32)))
    conn.commit()
    conn.close()


def get_admin_smtp_config(admin_id):
    """Get per-admin SMTP config. Returns dict with smtp_host/port/user/password/from_email or None."""
    if not admin_id:
        return None
    conn = get_db()
    row = conn.execute(
        "SELECT smtp_host, smtp_port, smtp_user, smtp_password, smtp_from_email, smtp_verified FROM company_info WHERE user_id = %s",
        (admin_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    cfg = dict(row)
    # Only return if at minimum smtp_user and smtp_password are set
    if cfg.get("smtp_user") and cfg.get("smtp_password"):
        return cfg
    return None


def save_admin_smtp_config(admin_id, data):
    """Save per-admin SMTP config to company_info."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM company_info WHERE user_id = %s", (admin_id,)).fetchone()
    if existing:
        conn.execute(
            """UPDATE company_info SET smtp_host=%s, smtp_port=%s, smtp_user=%s, smtp_password=%s,
               smtp_from_email=%s, smtp_verified=%s WHERE user_id=%s""",
            (data.get("smtp_host", ""), int(data.get("smtp_port", 587)),
             data.get("smtp_user", ""), data.get("smtp_password", ""),
             data.get("smtp_from_email", ""), int(data.get("smtp_verified", 0)),
             admin_id)
        )
    else:
        conn.execute(
            """INSERT INTO company_info (user_id, smtp_host, smtp_port, smtp_user, smtp_password, smtp_from_email, smtp_verified, external_api_key)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (admin_id, data.get("smtp_host", ""), int(data.get("smtp_port", 587)),
             data.get("smtp_user", ""), data.get("smtp_password", ""),
             data.get("smtp_from_email", ""), int(data.get("smtp_verified", 0)),
             secrets.token_hex(32))
        )
    conn.commit()
    conn.close()


def save_customers_api_config(user_id, api_url, api_key):
    """Save the external customers API endpoint and key for a given admin."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM company_info WHERE user_id = %s", (user_id,)).fetchone()
    if existing:
        conn.execute("UPDATE company_info SET customers_api_url=%s, customers_api_key=%s WHERE user_id=%s",
                     (api_url, api_key, user_id))
    else:
        conn.execute("INSERT INTO company_info (user_id, customers_api_url, customers_api_key) VALUES (%s,%s,%s)",
                     (user_id, api_url, api_key))
    conn.commit()
    conn.close()


def get_admin_by_external_api_key(api_key):
    """Look up the admin user_id from an external_api_key."""
    conn = get_db()
    row = conn.execute("SELECT user_id FROM company_info WHERE external_api_key = %s", (api_key,)).fetchone()
    conn.close()
    if row:
        return row["user_id"]
    return None


def get_external_api_key(user_id):
    """Get the external API key for a given admin."""
    conn = get_db()
    row = conn.execute("SELECT external_api_key FROM company_info WHERE user_id = %s", (user_id,)).fetchone()
    conn.close()
    if row:
        return row["external_api_key"] or ""
    return ""


def get_customers_api_config(user_id):
    """Get the external customers API config for a given admin."""
    conn = get_db()
    row = conn.execute("SELECT customers_api_url, customers_api_key FROM company_info WHERE user_id = %s", (user_id,)).fetchone()
    conn.close()
    if row:
        return {"customers_api_url": row["customers_api_url"] or "", "customers_api_key": row["customers_api_key"] or ""}
    return {"customers_api_url": "", "customers_api_key": ""}


# ══════════════════════════════════════════════
#  Company Services (name + price)
# ══════════════════════════════════════════════

def _ensure_company_services_table():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS company_services (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        price REAL NOT NULL DEFAULT 0,
        currency TEXT DEFAULT 'USD',
        source TEXT DEFAULT 'manual',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

_ensure_company_services_table()


def get_company_currency(admin_id):
    """Resolve currency from the head admin's company_info."""
    conn = get_db()
    # Walk up to the head admin if this user is linked
    user = conn.execute("SELECT id, role, admin_id FROM users WHERE id=%s", (admin_id,)).fetchone()
    head_id = admin_id
    if user and user["role"] != "head_admin" and user["admin_id"]:
        head_id = user["admin_id"]
    row = conn.execute("SELECT currency FROM company_info WHERE user_id=%s", (head_id,)).fetchone()
    conn.close()
    return (row["currency"] if row and row["currency"] else "USD")


def get_company_services(admin_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM company_services WHERE admin_id=%s ORDER BY name", (admin_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_company_service_by_id(service_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM company_services WHERE id=%s", (service_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_company_service(admin_id, name, price, currency="USD", source="manual",
                        category="", duration_minutes=60, description="",
                        preparation_instructions="", is_active=1):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO company_services (admin_id, name, price, currency, source,
           category, duration_minutes, description, preparation_instructions, is_active)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (admin_id, name, float(price or 0), currency, source,
         category, int(duration_minutes or 60), description, preparation_instructions, int(is_active))
    )
    sid = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return sid


def update_company_service(service_id, admin_id, name, price, category=None,
                           duration_minutes=None, description=None,
                           preparation_instructions=None, is_active=None):
    conn = get_db()
    conn.execute(
        "UPDATE company_services SET name=%s, price=%s WHERE id=%s AND admin_id=%s",
        (name, float(price or 0), service_id, admin_id)
    )
    if category is not None:
        conn.execute("UPDATE company_services SET category=%s WHERE id=%s AND admin_id=%s",
                     (category, service_id, admin_id))
    if duration_minutes is not None:
        conn.execute("UPDATE company_services SET duration_minutes=%s WHERE id=%s AND admin_id=%s",
                     (int(duration_minutes), service_id, admin_id))
    if description is not None:
        conn.execute("UPDATE company_services SET description=%s WHERE id=%s AND admin_id=%s",
                     (description, service_id, admin_id))
    if preparation_instructions is not None:
        conn.execute("UPDATE company_services SET preparation_instructions=%s WHERE id=%s AND admin_id=%s",
                     (preparation_instructions, service_id, admin_id))
    if is_active is not None:
        conn.execute("UPDATE company_services SET is_active=%s WHERE id=%s AND admin_id=%s",
                     (1 if is_active else 0, service_id, admin_id))
    conn.commit()
    conn.close()


def delete_company_service(service_id, admin_id):
    conn = get_db()
    conn.execute("DELETE FROM company_services WHERE id=%s AND admin_id=%s", (service_id, admin_id))
    conn.commit()
    conn.close()


def delete_all_company_services(admin_id, source=None):
    conn = get_db()
    if source:
        conn.execute("DELETE FROM company_services WHERE admin_id=%s AND source=%s", (admin_id, source))
    else:
        conn.execute("DELETE FROM company_services WHERE admin_id=%s", (admin_id,))
    conn.commit()
    conn.close()


def set_all_services_currency(admin_id, currency):
    conn = get_db()
    conn.execute("UPDATE company_services SET currency=%s WHERE admin_id=%s", (currency, admin_id))
    conn.commit()
    conn.close()


# ── Service-Doctor Mapping ──

def assign_doctor_to_service(service_id, doctor_id, admin_id):
    conn = get_db()
    try:
        conn.execute("INSERT INTO service_doctors (service_id, doctor_id, admin_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                     (service_id, doctor_id, admin_id))
        conn.commit()
    except Exception:
        pass
    conn.close()


def remove_doctor_from_service(service_id, doctor_id):
    conn = get_db()
    conn.execute("DELETE FROM service_doctors WHERE service_id=%s AND doctor_id=%s", (service_id, doctor_id))
    conn.commit()
    conn.close()


def get_doctors_for_service(service_id):
    """Get all doctors assigned to a service."""
    conn = get_db()
    rows = conn.execute(
        """SELECT d.* FROM doctors d
           JOIN service_doctors sd ON sd.doctor_id = d.id
           WHERE sd.service_id=%s AND d.is_active=1
           ORDER BY d.name""",
        (service_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_services_with_doctors(admin_id):
    """Get all services with their assigned doctor IDs (deduplicated by name)."""
    services = get_company_services(admin_id)
    # Deduplicate by name (keep first occurrence)
    seen = set()
    unique = []
    for svc in services:
        name_lower = svc.get("name", "").strip().lower()
        if name_lower not in seen:
            seen.add(name_lower)
            unique.append(svc)
    services = unique
    conn = get_db()
    for svc in services:
        rows = conn.execute("SELECT doctor_id FROM service_doctors WHERE service_id=%s", (svc["id"],)).fetchall()
        svc["doctor_ids"] = [r["doctor_id"] for r in rows]
    conn.close()
    return services


def set_service_doctors(service_id, doctor_ids, admin_id):
    """Replace all doctor assignments for a service."""
    conn = get_db()
    conn.execute("DELETE FROM service_doctors WHERE service_id=%s", (service_id,))
    for did in doctor_ids:
        conn.execute("INSERT INTO service_doctors (service_id, doctor_id, admin_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                     (service_id, did, admin_id))
    conn.commit()
    conn.close()


def add_service_interest(service_id, service_name, patient_name, patient_email, patient_phone, admin_id):
    """Record that a patient wants to be notified when a doctor is assigned to a service."""
    conn = get_db()
    conn.execute(
        """INSERT INTO service_interests (service_id, service_name, patient_name, patient_email, patient_phone, admin_id)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (service_id, service_name, patient_name, patient_email, patient_phone, admin_id)
    )
    conn.commit()
    conn.close()


def get_waiting_service_interests(service_id):
    """Get all patients waiting for notification about a service."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM service_interests WHERE service_id=%s AND status='waiting'",
        (service_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_service_interest_notified(interest_id):
    """Mark a service interest as notified."""
    conn = get_db()
    conn.execute(
        "UPDATE service_interests SET status='notified', notified_at=CURRENT_TIMESTAMP WHERE id=%s",
        (interest_id,)
    )
    conn.commit()
    conn.close()


def bulk_add_company_services(admin_id, services, currency, source="pdf"):
    conn = get_db()
    added = 0
    for s in services:
        name = (s.get("name") or "").strip()
        if not name:
            continue
        try:
            price = float(s.get("price") or 0)
        except (TypeError, ValueError):
            price = 0
        svc_cur = s.get("currency") or currency
        conn.execute(
            "INSERT INTO company_services (admin_id, name, price, currency, source) VALUES (%s,%s,%s,%s,%s)",
            (admin_id, name, price, svc_cur, source)
        )
        added += 1
    conn.commit()
    conn.close()
    return added


def replace_company_services_from_pdf(admin_id, services, currency):
    """Bulk-insert services parsed from a PDF (does not delete existing manual ones)."""
    conn = get_db()
    for s in services:
        conn.execute(
            "INSERT INTO company_services (admin_id, name, price, currency, source) VALUES (%s,%s,%s,%s,%s)",
            (admin_id, s["name"], float(s.get("price") or 0), currency, "pdf")
        )
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════
#  Doctors
# ══════════════════════════════════════════════

def get_doctors(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM doctors WHERE admin_id = %s ORDER BY name", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_doctor_by_id(doctor_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM doctors WHERE id = %s", (doctor_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_doctor_by_user_id(user_id):
    """Get the doctor record linked to a user account."""
    conn = get_db()
    row = conn.execute("SELECT * FROM doctors WHERE user_id = %s", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _strip_dr_prefix(name):
    """Remove leading 'Dr.' or 'Dr ' from a name to avoid 'Dr. Dr. X'."""
    import re
    return re.sub(r'^(?:Dr\.?\s+)+', '', name, flags=re.IGNORECASE).strip()


def add_doctor(admin_id, name, email="", specialty="", bio="", availability="Mon-Fri"):
    name = _strip_dr_prefix(name)
    conn = get_db()
    _ins_cur = conn.execute(
        "INSERT INTO doctors (admin_id, user_id, name, email, specialty, bio, availability, status) VALUES (%s,0,%s,%s,%s,%s,%s,%s) RETURNING id",
        (admin_id, name, email, specialty, bio, availability, "pending"))
    doctor_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return doctor_id


def add_doctor_from_pdf(admin_id, name, email="", specialty="", bio="", availability="Mon-Fri",
                        start_time=None, end_time=None, phone="", qualifications="",
                        languages="", years_of_experience=0, pdf_filename="",
                        schedule_type="fixed", daily_hours=""):
    """Create a doctor record directly from PDF extraction (no invitation flow)."""
    name = _strip_dr_prefix(name)
    conn = get_db()
    _ins_cur = conn.execute(
        """INSERT INTO doctors (admin_id, user_id, name, email, specialty, bio, availability,
           status, start_time, end_time, phone, qualifications, languages, years_of_experience,
           pdf_filename, schedule_type, daily_hours)
           VALUES (%s,0,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (admin_id, name, email, specialty, bio, availability, "active",
         start_time or "09:00 AM", end_time or "05:00 PM",
         phone, qualifications, languages, int(years_of_experience or 0), pdf_filename,
         schedule_type, daily_hours))
    doctor_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return doctor_id


def update_doctor(doctor_id, admin_id, name, specialty="", bio="", availability="Mon-Fri",
                   start_time=None, end_time=None, is_active=None, appointment_length=None,
                   years_of_experience=None, schedule_type=None, daily_hours=None,
                   gender=None, photo_url=None, **kwargs):
    name = _strip_dr_prefix(name)
    conn = get_db()
    conn.execute("UPDATE doctors SET name=%s, specialty=%s, bio=%s, availability=%s WHERE id=%s AND admin_id=%s",
                 (name, specialty, bio, availability, doctor_id, admin_id))
    if start_time is not None:
        conn.execute("UPDATE doctors SET start_time=%s WHERE id=%s AND admin_id=%s",
                     (start_time, doctor_id, admin_id))
    if end_time is not None:
        conn.execute("UPDATE doctors SET end_time=%s WHERE id=%s AND admin_id=%s",
                     (end_time, doctor_id, admin_id))
    if is_active is not None:
        conn.execute("UPDATE doctors SET is_active=%s WHERE id=%s AND admin_id=%s",
                     (1 if is_active else 0, doctor_id, admin_id))
    if appointment_length is not None:
        conn.execute("UPDATE doctors SET appointment_length=%s WHERE id=%s AND admin_id=%s",
                     (int(appointment_length), doctor_id, admin_id))
    if years_of_experience is not None:
        conn.execute("UPDATE doctors SET years_of_experience=%s WHERE id=%s AND admin_id=%s",
                     (int(years_of_experience), doctor_id, admin_id))
    if schedule_type is not None:
        conn.execute("UPDATE doctors SET schedule_type=%s WHERE id=%s AND admin_id=%s",
                     (schedule_type, doctor_id, admin_id))
    if daily_hours is not None:
        conn.execute("UPDATE doctors SET daily_hours=%s WHERE id=%s AND admin_id=%s",
                     (daily_hours if isinstance(daily_hours, str) else json.dumps(daily_hours),
                      doctor_id, admin_id))
    if gender is not None:
        conn.execute("UPDATE doctors SET gender=%s WHERE id=%s AND admin_id=%s",
                     (gender, doctor_id, admin_id))
    if photo_url is not None:
        conn.execute("UPDATE doctors SET photo_url=%s WHERE id=%s AND admin_id=%s",
                     (photo_url, doctor_id, admin_id))
    if kwargs.get("avg_appointment_price") is not None:
        conn.execute("UPDATE doctors SET avg_appointment_price=%s WHERE id=%s AND admin_id=%s",
                     (float(kwargs["avg_appointment_price"]), doctor_id, admin_id))
    if kwargs.get("avg_appointment_currency") is not None:
        conn.execute("UPDATE doctors SET avg_appointment_currency=%s WHERE id=%s AND admin_id=%s",
                     (kwargs["avg_appointment_currency"], doctor_id, admin_id))
    conn.commit()
    conn.close()


def delete_doctor(doctor_id, admin_id):
    conn = get_db()
    conn.execute("DELETE FROM doctors WHERE id=%s AND admin_id=%s", (doctor_id, admin_id))
    conn.commit()
    conn.close()


def link_doctor_to_user(doctor_id, user_id):
    """Link a doctor record to a user account after they accept."""
    conn = get_db()
    conn.execute("UPDATE doctors SET user_id = %s, status = 'active' WHERE id = %s", (user_id, doctor_id))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════
#  Doctor Breaks
# ══════════════════════════════════════════════

def get_doctor_breaks(doctor_id, day_of_week=None):
    conn = get_db()
    if day_of_week:
        rows = conn.execute(
            "SELECT * FROM doctor_breaks WHERE doctor_id = %s AND (day_of_week = %s OR day_of_week = '' OR day_of_week IS NULL) ORDER BY start_time",
            (doctor_id, day_of_week)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM doctor_breaks WHERE doctor_id = %s ORDER BY day_of_week, start_time", (doctor_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_doctor_break(doctor_id, break_name, start_time, end_time, day_of_week=""):
    conn = get_db()
    _ins_cur = conn.execute(
        "INSERT INTO doctor_breaks (doctor_id, break_name, start_time, end_time, day_of_week) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (doctor_id, break_name, start_time, end_time, day_of_week))
    break_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return break_id


def delete_doctor_break(break_id, doctor_id):
    conn = get_db()
    conn.execute("DELETE FROM doctor_breaks WHERE id = %s AND doctor_id = %s", (break_id, doctor_id))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════
#  Doctor Off Days
# ══════════════════════════════════════════════

def get_doctor_off_days(doctor_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM doctor_off_days WHERE doctor_id = %s ORDER BY off_date", (doctor_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_doctor_off_dates(doctor_id):
    """Return just the date strings as a set for quick lookup."""
    conn = get_db()
    rows = conn.execute("SELECT off_date FROM doctor_off_days WHERE doctor_id = %s", (doctor_id,)).fetchall()
    conn.close()
    return set(r["off_date"] for r in rows)


def add_doctor_off_day(doctor_id, off_date, reason=""):
    conn = get_db()
    # Prevent duplicates
    existing = conn.execute("SELECT id FROM doctor_off_days WHERE doctor_id = %s AND off_date = %s",
                            (doctor_id, off_date)).fetchone()
    if existing:
        conn.close()
        return None, "This date is already marked as off."
    _ins_cur = conn.execute(
        "INSERT INTO doctor_off_days (doctor_id, off_date, reason) VALUES (%s,%s,%s) RETURNING id",
        (doctor_id, off_date, reason))
    off_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return off_id, None


def delete_doctor_off_day(off_day_id, doctor_id):
    conn = get_db()
    conn.execute("DELETE FROM doctor_off_days WHERE id = %s AND doctor_id = %s", (off_day_id, doctor_id))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════
#  Doctor Requests
# ══════════════════════════════════════════════

def create_doctor_request(admin_id, admin_name, business_name, doctor_email, doctor_record_id):
    """Create a request for a doctor to join a practice."""
    conn = get_db()
    # Check if there's already a pending request
    existing = conn.execute(
        "SELECT id FROM doctor_requests WHERE admin_id = %s AND doctor_email = %s AND status = 'pending'",
        (admin_id, doctor_email)).fetchone()
    if existing:
        conn.close()
        return None, "A request has already been sent to this email."

    # Check if doctor has an account
    doctor_user = conn.execute("SELECT id FROM users WHERE email = %s", (doctor_email,)).fetchone()
    doctor_user_id = doctor_user["id"] if doctor_user else 0

    _ins_cur = conn.execute(
        """INSERT INTO doctor_requests (admin_id, admin_name, business_name, doctor_email,
           doctor_user_id, doctor_record_id, status) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (admin_id, admin_name, business_name, doctor_email, doctor_user_id, doctor_record_id, "pending"))
    req_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return req_id, None


def get_doctor_requests_for_doctor(doctor_email):
    """Get all pending requests for a doctor by email."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM doctor_requests WHERE doctor_email = %s AND status = 'pending' ORDER BY created_at DESC",
        (doctor_email,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_doctor_requests_by_admin(admin_id):
    """Get all requests sent by an admin."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM doctor_requests WHERE admin_id = %s ORDER BY created_at DESC",
        (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_doctor_request(request_id, admin_id):
    """Delete a pending doctor request sent by an admin."""
    conn = get_db()
    conn.execute("DELETE FROM doctor_requests WHERE id = %s AND admin_id = %s AND status = 'pending'",
                 (request_id, admin_id))
    conn.commit()
    conn.close()


def respond_to_doctor_request(request_id, doctor_user_id, accept=True):
    """Accept or reject a doctor request."""
    conn = get_db()
    req = conn.execute("SELECT * FROM doctor_requests WHERE id = %s AND status = 'pending'", (request_id,)).fetchone()
    if not req:
        conn.close()
        return None, "Request not found or already handled."

    new_status = "accepted" if accept else "rejected"
    conn.execute("UPDATE doctor_requests SET status = %s, doctor_user_id = %s WHERE id = %s",
                 (new_status, doctor_user_id, request_id))

    if accept:
        # Link doctor record to user account
        doctor_record_id = req["doctor_record_id"]
        admin_id = req["admin_id"]
        doctor_email = req["doctor_email"]
        # Get the doctor user's specialty and copy it to the doctor record
        doctor_user = conn.execute("SELECT specialty FROM users WHERE id = %s", (doctor_user_id,)).fetchone()
        user_specialty = doctor_user["specialty"] if doctor_user and doctor_user["specialty"] else None
        if user_specialty:
            conn.execute("UPDATE doctors SET user_id = %s, status = 'active', specialty = %s WHERE id = %s",
                         (doctor_user_id, user_specialty, doctor_record_id))
        else:
            conn.execute("UPDATE doctors SET user_id = %s, status = 'active' WHERE id = %s",
                         (doctor_user_id, doctor_record_id))
        # Set the doctor user's admin_id and role
        conn.execute("UPDATE users SET admin_id = %s, role = 'doctor' WHERE id = %s",
                     (admin_id, doctor_user_id))

        # Clean up: delete all OTHER pending requests for this doctor + their orphan doctor records
        other_pending = conn.execute(
            "SELECT id, doctor_record_id, admin_id FROM doctor_requests WHERE doctor_email = %s AND status = 'pending' AND id != %s",
            (doctor_email, request_id)).fetchall()
        for other in other_pending:
            # Delete the orphaned pending doctor record
            conn.execute("DELETE FROM doctors WHERE id = %s AND admin_id = %s AND status = 'pending'",
                         (other["doctor_record_id"], other["admin_id"]))
            # Mark the request as cancelled
            conn.execute("UPDATE doctor_requests SET status = 'cancelled' WHERE id = %s", (other["id"],))

    conn.commit()
    conn.close()
    return dict(req), None


# ══════════════════════════════════════════════
#  Admin Requests (head_admin invites admins)
# ══════════════════════════════════════════════

def create_admin_request(head_admin_id, head_admin_name, business_name, admin_email):
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM admin_requests WHERE head_admin_id = %s AND admin_email = %s AND status = 'pending'",
        (head_admin_id, admin_email)).fetchone()
    if existing:
        conn.close()
        return None, "A request has already been sent to this email."
    admin_user = conn.execute("SELECT id FROM users WHERE email = %s", (admin_email,)).fetchone()
    admin_user_id = admin_user["id"] if admin_user else 0
    _ins_cur = conn.execute(
        """INSERT INTO admin_requests (head_admin_id, head_admin_name, business_name,
           admin_email, admin_user_id, status) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
        (head_admin_id, head_admin_name, business_name, admin_email, admin_user_id, "pending"))
    req_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return req_id, None


def get_admin_requests_for_user(email):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM admin_requests WHERE admin_email = %s AND status = 'pending' ORDER BY created_at DESC",
        (email,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_admin_requests_by_head(head_admin_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM admin_requests WHERE head_admin_id = %s ORDER BY created_at DESC",
        (head_admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def respond_to_admin_request(request_id, user_id, accept=True):
    conn = get_db()
    req = conn.execute("SELECT * FROM admin_requests WHERE id = %s AND status = 'pending'", (request_id,)).fetchone()
    if not req:
        conn.close()
        return None, "Request not found or already handled."
    new_status = "accepted" if accept else "rejected"
    conn.execute("UPDATE admin_requests SET status = %s, admin_user_id = %s WHERE id = %s",
                 (new_status, user_id, request_id))
    if accept:
        head_admin_id = req["head_admin_id"]
        # Migrate any doctors this admin already owns to the head admin's company
        # Update doctor records: admin_id from admin's own id → head_admin_id
        conn.execute("UPDATE doctors SET admin_id = %s WHERE admin_id = %s",
                     (head_admin_id, user_id))
        # Update doctor user accounts: admin_id → head_admin_id
        conn.execute("UPDATE users SET admin_id = %s WHERE admin_id = %s AND role = 'doctor'",
                     (head_admin_id, user_id))
        # Update doctor_requests: admin_id → head_admin_id
        conn.execute("UPDATE doctor_requests SET admin_id = %s WHERE admin_id = %s",
                     (head_admin_id, user_id))
        # Link the admin to the head admin's company
        conn.execute("UPDATE users SET admin_id = %s, role = 'admin' WHERE id = %s",
                     (head_admin_id, user_id))
    conn.commit()
    conn.close()
    return dict(req), None


def delete_admin_request(request_id, head_admin_id):
    conn = get_db()
    conn.execute("DELETE FROM admin_requests WHERE id = %s AND head_admin_id = %s", (request_id, head_admin_id))
    conn.commit()
    conn.close()


def get_company_admins(head_admin_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, email, role, created_at FROM users WHERE admin_id = %s AND role = 'admin'",
        (head_admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def remove_admin_from_company(admin_user_id, head_admin_id):
    conn = get_db()
    conn.execute("UPDATE users SET admin_id = 0, role = 'head_admin' WHERE id = %s AND admin_id = %s",
                 (admin_user_id, head_admin_id))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════
#  Categories
# ══════════════════════════════════════════════

def get_categories(admin_id):
    """Get categories: admin's custom ones + global defaults (admin_id=0)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM categories WHERE admin_id IN (0, %s) ORDER BY name",
        (admin_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_category(admin_id, name):
    """Add a custom category for an admin."""
    conn = get_db()
    # Check for duplicate (global or admin-specific)
    existing = conn.execute(
        "SELECT id FROM categories WHERE name = %s AND admin_id IN (0, %s)",
        (name, admin_id)
    ).fetchone()
    if existing:
        conn.close()
        return None, "This category already exists."
    _ins_cur = conn.execute("INSERT INTO categories (admin_id, name) VALUES (%s, %s) RETURNING id", (admin_id, name))
    cat_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return cat_id, None


def delete_category(category_id, admin_id):
    """Delete a custom category (only admin's own, not global defaults)."""
    conn = get_db()
    conn.execute("DELETE FROM categories WHERE id = %s AND admin_id = %s", (category_id, admin_id))
    conn.commit()
    conn.close()


def get_doctors_by_category(admin_id, category_name):
    """Get active doctors filtered by specialty/category (supports comma-separated multi-specialty)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM doctors WHERE admin_id = %s AND status = 'active' AND (specialty = %s OR specialty ILIKE %s OR specialty ILIKE %s OR specialty ILIKE %s) ORDER BY name",
        (admin_id, category_name,
         f"{category_name}, %", f"%, {category_name}, %", f"%, {category_name}")
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════
#  Admin Audit Log
# ══════════════════════════════════════════════

def log_admin_action(admin_id, user, action, details=""):
    """Log an admin action for the audit trail."""
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db()
        conn.execute(
            "INSERT INTO audit_log (admin_id, user_id, user_name, user_email, action, details, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (admin_id, user.get("id", 0), user.get("name", ""), user.get("email", ""), action, details, now)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[audit] Failed to log: {e}", flush=True)


def get_audit_log(admin_id, limit=200, offset=0, search=""):
    """Get audit log entries for an admin."""
    conn = get_db()
    if search:
        like = f"%{search}%"
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE admin_id=%s AND (action ILIKE %s OR details ILIKE %s OR user_name ILIKE %s OR user_email ILIKE %s) ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (admin_id, like, like, like, like, limit, offset)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE admin_id=%s ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (admin_id, limit, offset)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════
#  Chat Logging & Analytics
# ══════════════════════════════════════════════

def log_chat(session_id, admin_id, message, intent="", intent_confidence=0.0, resulted_in_booking=0, sender="user"):
    """Log a chat message for analytics."""
    conn = get_db()
    conn.execute(
        "INSERT INTO chat_logs (session_id, admin_id, message, intent, intent_confidence, resulted_in_booking, sender) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (session_id, admin_id, message, intent, intent_confidence, resulted_in_booking, sender))
    conn.commit()
    conn.close()


def mark_session_booked(session_id):
    """Mark all messages in a session as having resulted in a booking."""
    conn = get_db()
    conn.execute("UPDATE chat_logs SET resulted_in_booking = 1 WHERE session_id = %s", (session_id,))
    conn.commit()
    conn.close()


_analytics_cache = {}
_CACHE_TTL = 30  # 30 seconds

def invalidate_analytics_cache(admin_id=None):
    """Clear analytics cache. Called when bookings change."""
    if admin_id:
        keys_to_remove = [k for k in _analytics_cache if k.startswith(f"{admin_id}:")]
        for k in keys_to_remove:
            del _analytics_cache[k]
    else:
        _analytics_cache.clear()


def get_analytics(admin_id, date_from, date_to):
    """Get all 5 analytics metrics in a single query. Cached for 5 minutes."""
    cache_key = f"{admin_id}:{date_from}:{date_to}"
    now = datetime.now().timestamp()
    if cache_key in _analytics_cache:
        cached_at, data = _analytics_cache[cache_key]
        if now - cached_at < _CACHE_TTL:
            return data

    conn = get_db()
    try:
        return _get_analytics_inner(conn, admin_id, date_from, date_to, cache_key, now)
    except Exception:
        raise
    finally:
        conn.close()

def _get_analytics_inner(conn, admin_id, date_from, date_to, cache_key, now):
    # 1. Leads per day (unique sessions per day)
    leads_rows = conn.execute("""
        SELECT created_at::date as day, COUNT(DISTINCT session_id) as count
        FROM chat_logs WHERE admin_id = %s AND created_at::date BETWEEN %s AND %s
        GROUP BY created_at::date ORDER BY day
    """, (admin_id, date_from, date_to)).fetchall()
    leads_per_day = [{"date": str(r["day"]), "count": r["count"]} for r in leads_rows]

    total_sessions = conn.execute("""
        SELECT COUNT(DISTINCT session_id) as c FROM chat_logs
        WHERE admin_id = %s AND created_at::date BETWEEN %s AND %s
    """, (admin_id, date_from, date_to)).fetchone()["c"]

    # 2. Conversion rate per week — merge chat sessions with actual bookings
    conversion_rows = conn.execute("""
        SELECT
            TO_CHAR(created_at, 'IYYY-"W"IW') as week,
            COUNT(DISTINCT session_id) as total_chats,
            COUNT(DISTINCT CASE WHEN resulted_in_booking = 1 THEN session_id END) as booked
        FROM chat_logs WHERE admin_id = %s AND created_at::date BETWEEN %s AND %s
        GROUP BY week ORDER BY week
    """, (admin_id, date_from, date_to)).fetchall()

    # Also get actual bookings per week from bookings table
    bookings_per_week_rows = conn.execute("""
        SELECT TO_CHAR(date::date, 'IYYY-"W"IW') as week, COUNT(*) as count
        FROM bookings WHERE admin_id = %s AND status != 'cancelled'
        AND date::date BETWEEN %s AND %s
        GROUP BY week ORDER BY week
    """, (admin_id, date_from, date_to)).fetchall()
    bookings_per_week_map = {r["week"]: r["count"] for r in bookings_per_week_rows}

    # Merge: use actual bookings as source of truth
    conversion_data = []
    for r in conversion_rows:
        actual_booked = bookings_per_week_map.get(r["week"], 0)
        conversion_data.append({
            "week": r["week"], "total_chats": r["total_chats"],
            "total_bookings": actual_booked,
            "chat_attributed": r["booked"],
            "rate": min(100.0, round(actual_booked / r["total_chats"] * 100, 1)) if r["total_chats"] > 0 else 0
        })
    # Add weeks that have bookings but no chat sessions
    for week, count in bookings_per_week_map.items():
        if not any(c["week"] == week for c in conversion_data):
            conversion_data.append({"week": week, "total_chats": 0, "total_bookings": count, "chat_attributed": 0, "rate": 0})
    conversion_data.sort(key=lambda x: x["week"])

    total_booked_sessions = conn.execute("""
        SELECT COUNT(DISTINCT session_id) as c FROM chat_logs
        WHERE admin_id = %s AND resulted_in_booking = 1 AND created_at::date BETWEEN %s AND %s
    """, (admin_id, date_from, date_to)).fetchone()["c"]

    # 3. Peak booking hours
    peak_rows = conn.execute("""
        SELECT hour24, COUNT(*) as count FROM (
            SELECT CASE
                WHEN time ~ '^\d{1,2}:\d{2}\s*(PM|pm)' AND CAST(SPLIT_PART(time, ':', 1) AS INTEGER) != 12
                    THEN CAST(SPLIT_PART(time, ':', 1) AS INTEGER) + 12
                WHEN time ~ '^\d{1,2}:\d{2}\s*(AM|am)' AND CAST(SPLIT_PART(time, ':', 1) AS INTEGER) = 12
                    THEN 0
                ELSE CAST(SPLIT_PART(time, ':', 1) AS INTEGER)
            END as hour24
            FROM bookings WHERE admin_id = %s AND status != 'cancelled'
            AND date::date BETWEEN %s AND %s
            AND time IS NOT NULL AND time != ''
        ) sub
        WHERE hour24 BETWEEN 0 AND 23
        GROUP BY hour24 ORDER BY hour24
    """, (admin_id, date_from, date_to)).fetchall()

    total_bookings_period = sum(r["count"] for r in peak_rows) if peak_rows else 0
    peak_hours = [{
        "hour": r["hour24"], "count": r["count"],
        "pct": round(r["count"] / total_bookings_period * 100, 1) if total_bookings_period > 0 else 0
    } for r in peak_rows]

    # 4. Most asked questions (top intents)
    intent_rows = conn.execute("""
        SELECT intent, COUNT(*) as count FROM chat_logs
        WHERE admin_id = %s AND intent != '' AND created_at::date BETWEEN %s AND %s
        GROUP BY intent ORDER BY count DESC LIMIT 10
    """, (admin_id, date_from, date_to)).fetchall()

    total_intents = sum(r["count"] for r in intent_rows) if intent_rows else 0
    top_intents = [{
        "intent": r["intent"], "count": r["count"],
        "pct": round(r["count"] / total_intents * 100, 1) if total_intents > 0 else 0
    } for r in intent_rows]

    # 5. No-show rate per week (by appointment date)
    noshow_rows = conn.execute("""
        SELECT
            TO_CHAR(date::date, 'IYYY-"W"IW') as week,
            COUNT(*) as total,
            SUM(CASE WHEN status = 'no_show' THEN 1 ELSE 0 END) as no_shows
        FROM bookings WHERE admin_id = %s AND status IN ('confirmed', 'no_show', 'completed')
        AND date::date BETWEEN %s AND %s
        GROUP BY week ORDER BY week
    """, (admin_id, date_from, date_to)).fetchall()
    noshow_data = [{
        "week": r["week"], "total": r["total"], "no_shows": r["no_shows"],
        "rate": round(r["no_shows"] / r["total"] * 100, 1) if r["total"] > 0 else 0
    } for r in noshow_rows]

    # 6. Bookings per day (by appointment date, not creation date)
    bookings_per_day_rows = conn.execute("""
        SELECT date::date as day, COUNT(*) as count
        FROM bookings WHERE admin_id = %s AND status != 'cancelled'
        AND date::date BETWEEN %s AND %s
        GROUP BY date::date ORDER BY day
    """, (admin_id, date_from, date_to)).fetchall()
    bookings_per_day = [{"date": str(r["day"]), "count": r["count"]} for r in bookings_per_day_rows]

    # Total bookings in period (from bookings table, not chat_logs)
    actual_bookings_count = sum(r["count"] for r in bookings_per_day) if bookings_per_day else 0

    # Conversion rate: chat sessions that resulted in a booking / total sessions
    # Only use chat-attributed bookings (resulted_in_booking flag)
    if total_booked_sessions > 0 and total_sessions > 0:
        conv_rate = min(100.0, round(total_booked_sessions / total_sessions * 100, 1))
    else:
        conv_rate = 0

    result = {
        "leads_per_day": leads_per_day,
        "total_sessions": total_sessions,
        "conversion": conversion_data,
        "conversion_rate": conv_rate,
        "peak_hours": peak_hours,
        "top_intents": top_intents,
        "noshow": noshow_data,
        "total_bookings": actual_bookings_count,
        "total_booked_sessions": total_booked_sessions,
        "bookings_per_day": bookings_per_day,
    }

    _analytics_cache[cache_key] = (now, result)
    return result


# ═══════════════ Feature 1: Waitlist ═══════════════

def add_to_waitlist(admin_id, doctor_id, date, time_slot, patient_name, patient_email="", patient_phone="", session_id=""):
    """Add patient to waitlist. Position = max existing position + 1."""
    conn = get_db()
    row = conn.execute(
        "SELECT MAX(position) as mx FROM waitlist WHERE admin_id=%s AND doctor_id=%s AND date=%s AND time_slot=%s AND status IN ('waiting','notified')",
        (admin_id, doctor_id, date, time_slot)).fetchone()
    pos = (row["mx"] or 0) + 1
    _ins_cur = conn.execute(
        "INSERT INTO waitlist (admin_id,doctor_id,date,time_slot,patient_name,patient_email,patient_phone,position,session_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (admin_id, doctor_id, date, time_slot, patient_name, patient_email, patient_phone, pos, session_id))
    wid = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return wid


def get_waitlist_for_slot(admin_id, doctor_id, date, time_slot):
    """Get all waitlist entries for a specific slot, ordered by position."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM waitlist WHERE admin_id=%s AND doctor_id=%s AND date=%s AND time_slot=%s ORDER BY position",
        (admin_id, doctor_id, date, time_slot)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_waitlist(admin_id, doctor_id=None, date=None, time_slot=None):
    """General waitlist query with optional filters."""
    conn = get_db()
    q = "SELECT * FROM waitlist WHERE admin_id=%s"
    params = [admin_id]
    if doctor_id:
        q += " AND doctor_id=%s"; params.append(doctor_id)
    if date:
        q += " AND date=%s"; params.append(date)
    if time_slot:
        q += " AND time_slot=%s"; params.append(time_slot)
    q += " ORDER BY position"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_next_waiting_patient(admin_id, doctor_id, date, time_slot):
    """Get the first patient with status='waiting' for this slot."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM waitlist WHERE admin_id=%s AND doctor_id=%s AND date=%s AND time_slot=%s AND status='waiting' ORDER BY position LIMIT 1",
        (admin_id, doctor_id, date, time_slot)).fetchone()
    conn.close()
    return dict(row) if row else None


def notify_waitlist_patient(waitlist_id, confirm_deadline):
    """Set status='notified', notified_at=now, confirm_deadline=deadline."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE waitlist SET status='notified', notified_at=%s, confirm_deadline=%s WHERE id=%s",
        (now, confirm_deadline, waitlist_id))
    conn.commit()
    conn.close()


def confirm_waitlist_patient(waitlist_id):
    """Set status='confirmed', confirmed_at=now."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE waitlist SET status='confirmed', confirmed_at=%s WHERE id=%s", (now, waitlist_id))
    conn.commit()
    conn.close()


def expire_waitlist_patient(waitlist_id):
    """Set status='expired', expired_at=now."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE waitlist SET status='expired', expired_at=%s WHERE id=%s", (now, waitlist_id))
    conn.commit()
    conn.close()


def get_active_waitlist_notifications():
    """Get all entries with status='notified' where confirm_deadline has passed."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT * FROM waitlist WHERE status='notified' AND confirm_deadline IS NOT NULL AND confirm_deadline < %s",
        (now,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_waitlist_for_admin(admin_id):
    """Get all waitlist entries for dashboard display with patient name, position, status, countdown."""
    conn = get_db()
    rows = conn.execute(
        """SELECT w.*, d.name as doctor_name
           FROM waitlist w
           LEFT JOIN doctors d ON w.doctor_id = d.id
           WHERE w.admin_id=%s
           ORDER BY w.date, w.time_slot, w.position""",
        (admin_id,)).fetchall()
    conn.close()
    results = []
    now = datetime.now()
    for r in rows:
        entry = dict(r)
        if entry["status"] == "notified" and entry.get("confirm_deadline"):
            try:
                deadline = _parse_dt(entry["confirm_deadline"])
                remaining = (deadline - now).total_seconds()
                entry["countdown_seconds"] = max(0, int(remaining))
            except (ValueError, TypeError):
                entry["countdown_seconds"] = 0
        else:
            entry["countdown_seconds"] = None
        results.append(entry)
    return results


def is_slot_held(admin_id, doctor_id, date, time_slot):
    """Check if a slot is currently held (has a notified but not yet expired/confirmed entry)."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM waitlist WHERE admin_id=%s AND doctor_id=%s AND date=%s AND time_slot=%s AND status='notified'",
        (admin_id, doctor_id, date, time_slot)).fetchone()
    conn.close()
    return row["cnt"] > 0


def release_held_slot(admin_id, doctor_id, date, time_slot):
    """When entire waitlist expires, release the slot back to public.
    The slot is implicitly free when no 'notified' entries exist."""
    pass


def get_waitlist_count(admin_id, doctor_id, date, time_slot):
    """Return count of waiting patients for a slot."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM waitlist WHERE admin_id=%s AND doctor_id=%s AND date=%s AND time_slot=%s AND status='waiting'",
        (admin_id, doctor_id, date, time_slot)).fetchone()
    conn.close()
    return row["cnt"]


def get_waitlist_entry(waitlist_id):
    """Get a single waitlist entry by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM waitlist WHERE id=%s", (waitlist_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_waitlist_entry(waitlist_id):
    """Remove a waitlist entry entirely."""
    conn = get_db()
    conn.execute("DELETE FROM waitlist WHERE id=%s", (waitlist_id,))
    conn.commit()
    conn.close()


def get_waitlist_by_token(token_value, token_type="confirm_token"):
    """Look up a waitlist entry by confirm_token or remove_token."""
    if token_type not in ('confirm_token', 'cancel_token'):
        return None
    conn = get_db()
    row = conn.execute(f"SELECT * FROM waitlist WHERE {token_type} = %s AND {token_type} != ''", (token_value,)).fetchone()
    conn.close()
    return dict(row) if row else None


# Legacy aliases for backward compatibility
def confirm_waitlist(waitlist_id):
    return confirm_waitlist_patient(waitlist_id)

def expire_waitlist(waitlist_id):
    return expire_waitlist_patient(waitlist_id)

def get_next_waiting(admin_id, doctor_id, date, time_slot):
    return get_next_waiting_patient(admin_id, doctor_id, date, time_slot)


# ═══════════════ Feature Configuration ═══════════════

# All known feature keys with their default state (1=enabled, 0=disabled)
FEATURE_DEFAULTS = {
    # Email notifications
    "email_booking_confirmation": 1,
    "email_booking_cancellation": 1,
    "email_previsit_form": 1,
    "email_noshow_patient": 1,
    "email_noshow_reason_doctor": 1,
    "email_otp": 1,
    # Feature toggles
    "auto_lead_capture": 1,
    "missed_call_autoreply": 1,
    "auto_surveys": 1,
    "auto_invoices": 1,
    "auto_reports": 1,
    "auto_noshow_recovery": 1,
    "auto_noshow_detection": 0,
    "loyalty_program": 1,
    "auto_recall": 1,
    "auto_followups": 1,
    "auto_reminders": 1,
    # SMS toggles (off by default — requires Twilio config)
    "sms_booking_confirmation": 0,
    "sms_appointment_reminder": 0,
    "sms_noshow_recovery": 0,
    # Chatbot access control
    "require_login_to_book": 0,
    # Proactive engagement
    "proactive_engagement": 1,
    # Live chat timeout (minutes) — chat shown as active if last msg within this window
    "live_chat_timeout": 8,
}


def get_feature_config(admin_id):
    """Return dict of all feature toggles for an admin, with defaults applied."""
    conn = get_db()
    rows = conn.execute("SELECT feature_key, enabled FROM feature_config WHERE admin_id=%s", (admin_id,)).fetchall()
    conn.close()
    result = dict(FEATURE_DEFAULTS)  # start with defaults
    for r in rows:
        result[r["feature_key"]] = r["enabled"]
    return result


def is_feature_enabled(admin_id, feature_key):
    """Check if a specific feature is enabled for an admin."""
    conn = get_db()
    row = conn.execute("SELECT enabled FROM feature_config WHERE admin_id=%s AND feature_key=%s",
                       (admin_id, feature_key)).fetchone()
    conn.close()
    if row:
        return bool(row["enabled"])
    return bool(FEATURE_DEFAULTS.get(feature_key, 1))


NUMERIC_FEATURE_KEYS = {"live_chat_timeout"}

def save_feature_config(admin_id, config_dict):
    """Save multiple feature toggles at once. config_dict = {feature_key: 0|1} or numeric for special keys."""
    conn = get_db()
    for key, val in config_dict.items():
        if key not in FEATURE_DEFAULTS:
            continue
        if key in NUMERIC_FEATURE_KEYS:
            save_val = max(1, min(60, int(val)))
        else:
            save_val = int(bool(val))
        conn.execute(
            "INSERT INTO feature_config (admin_id, feature_key, enabled, updated_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP) "
            "ON CONFLICT(admin_id, feature_key) DO UPDATE SET enabled=excluded.enabled, updated_at=CURRENT_TIMESTAMP",
            (admin_id, key, save_val)
        )
    conn.commit()
    conn.close()


# ── Form Configuration ──

FORM_FIELD_DEFAULTS = {
    # Personal Info - enabled by default
    "full_name": {"enabled": 1, "required": 1, "group": "Personal Information", "label": "Full Name"},
    "date_of_birth": {"enabled": 1, "required": 1, "group": "Personal Information", "label": "Date of Birth"},
    "gender": {"enabled": 1, "required": 1, "group": "Personal Information", "label": "Gender"},
    "national_id": {"enabled": 0, "required": 0, "group": "Personal Information", "label": "National ID / Passport Number"},
    "profile_photo": {"enabled": 0, "required": 0, "group": "Personal Information", "label": "Profile Photo"},
    # Contact Info - enabled by default
    "home_address": {"enabled": 0, "required": 0, "group": "Contact Information", "label": "Home Address"},
    "city": {"enabled": 0, "required": 0, "group": "Contact Information", "label": "City"},
    # Emergency Contact
    "emergency_contact_name": {"enabled": 0, "required": 0, "group": "Emergency Contact", "label": "Emergency Contact Name"},
    "emergency_contact_relationship": {"enabled": 0, "required": 0, "group": "Emergency Contact", "label": "Relationship to Patient"},
    "emergency_contact_phone": {"enabled": 0, "required": 0, "group": "Emergency Contact", "label": "Emergency Contact Phone"},
    # Medical History
    "current_medications": {"enabled": 0, "required": 0, "group": "Medical History", "label": "Current Medications"},
    "drug_allergies": {"enabled": 0, "required": 0, "group": "Medical History", "label": "Known Drug Allergies"},
    "material_allergies": {"enabled": 0, "required": 0, "group": "Medical History", "label": "Known Material Allergies (latex, metals)"},
    "blood_type": {"enabled": 0, "required": 0, "group": "Medical History", "label": "Blood Type"},
    "medical_conditions": {"enabled": 1, "required": 0, "group": "Medical History", "label": "Medical Conditions"},
    "bleeding_disorders": {"enabled": 0, "required": 0, "group": "Medical History", "label": "History of Bleeding Disorders"},
    "fainting_anxiety": {"enabled": 0, "required": 0, "group": "Medical History", "label": "History of Fainting/Anxiety During Dental Treatment"},
    "last_dental_visit": {"enabled": 0, "required": 0, "group": "Medical History", "label": "Last Dental Visit Date"},
    "last_xray_date": {"enabled": 0, "required": 0, "group": "Medical History", "label": "Last Dental X-Ray Date"},
    "dental_concerns": {"enabled": 0, "required": 0, "group": "Medical History", "label": "Current Dental Concerns or Symptoms"},
    # Insurance
    "insurance_provider": {"enabled": 1, "required": 0, "group": "Insurance", "label": "Insurance Provider Name"},
    "insurance_policy": {"enabled": 1, "required": 0, "group": "Insurance", "label": "Insurance Policy Number"},
    "insurance_member_id": {"enabled": 0, "required": 0, "group": "Insurance", "label": "Insurance Member ID"},
    "policy_holder_name": {"enabled": 0, "required": 0, "group": "Insurance", "label": "Policy Holder Name"},
    "policy_holder_dob": {"enabled": 0, "required": 0, "group": "Insurance", "label": "Policy Holder Date of Birth"},
    "billing_address": {"enabled": 0, "required": 0, "group": "Insurance", "label": "Billing Address"},
    # Other
    "how_heard_about_us": {"enabled": 0, "required": 0, "group": "Other", "label": "How Did You Hear About Us"},
    "consent_treatment": {"enabled": 0, "required": 0, "group": "Consent", "label": "Consent to Treatment"},
    "consent_data_storage": {"enabled": 0, "required": 0, "group": "Consent", "label": "Consent to Data Storage"},
    "consent_reminders": {"enabled": 0, "required": 0, "group": "Consent", "label": "Consent to Receive Reminders"},
}


def get_form_config(admin_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM form_config WHERE admin_id=%s", (admin_id,)).fetchone()
    config = {
        "send_form_after_booking": 1,
        "one_time_form": 0,
    }
    if row:
        config["send_form_after_booking"] = row["send_form_after_booking"]
        config["one_time_form"] = row["one_time_form"]

    # Get field configs
    field_rows = conn.execute("SELECT field_key, enabled, required FROM form_fields_config WHERE admin_id=%s", (admin_id,)).fetchall()
    field_map = {r["field_key"]: {"enabled": r["enabled"], "required": r["required"]} for r in field_rows}

    fields = {}
    for key, defaults in FORM_FIELD_DEFAULTS.items():
        if key in field_map:
            fields[key] = {**defaults, **field_map[key]}
        else:
            fields[key] = dict(defaults)

    config["fields"] = fields

    # Get custom fields (agency only)
    custom_rows = conn.execute("SELECT id, field_name, field_type, required, sort_order FROM form_custom_fields WHERE admin_id=%s ORDER BY sort_order", (admin_id,)).fetchall()
    config["custom_fields"] = [dict(r) for r in custom_rows]

    conn.close()
    return config


def save_form_config(admin_id, data):
    conn = get_db()
    send_form = int(bool(data.get("send_form_after_booking", 1)))
    one_time = int(bool(data.get("one_time_form", 0)))
    conn.execute(
        "INSERT INTO form_config (admin_id, send_form_after_booking, one_time_form, updated_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP) "
        "ON CONFLICT(admin_id) DO UPDATE SET send_form_after_booking=excluded.send_form_after_booking, one_time_form=excluded.one_time_form, updated_at=CURRENT_TIMESTAMP",
        (admin_id, send_form, one_time)
    )

    # Save field configs
    fields = data.get("fields", {})
    for key, val in fields.items():
        if key not in FORM_FIELD_DEFAULTS:
            continue
        enabled = int(bool(val.get("enabled", 0)))
        required = int(bool(val.get("required", 0)))
        conn.execute(
            "INSERT INTO form_fields_config (admin_id, field_key, enabled, required, updated_at) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP) "
            "ON CONFLICT(admin_id, field_key) DO UPDATE SET enabled=excluded.enabled, required=excluded.required, updated_at=CURRENT_TIMESTAMP",
            (admin_id, key, enabled, required)
        )

    conn.commit()
    conn.close()


def add_custom_form_field(admin_id, field_name, field_type="text", required=0):
    conn = get_db()
    max_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS cnt FROM form_custom_fields WHERE admin_id=%s", (admin_id,)).fetchone()['cnt']
    _ins_cur = conn.execute(
        "INSERT INTO form_custom_fields (admin_id, field_name, field_type, required, sort_order) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (admin_id, field_name, field_type, int(bool(required)), max_order + 1)
    )
    field_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return field_id


def delete_custom_form_field(admin_id, field_id):
    conn = get_db()
    conn.execute("DELETE FROM form_custom_fields WHERE id=%s AND admin_id=%s", (field_id, admin_id))
    conn.commit()
    conn.close()


# ═══════════════ Feature 2: Patient Forms ═══════════════

def create_previsit_form(booking_id, admin_id, patient_name=None):
    """Generate a UUID token, create form record, return token."""
    token = secrets.token_urlsafe(32)
    conn = get_db()
    conn.execute(
        "INSERT INTO patient_forms (booking_id, admin_id, token, full_name) VALUES (%s,%s,%s,%s)",
        (booking_id, admin_id, token, patient_name or ""))
    conn.execute("UPDATE bookings SET form_token=%s WHERE id=%s", (token, booking_id))
    conn.commit()
    conn.close()
    return token


# Keep old name as alias for backward compatibility
create_patient_form = create_previsit_form


def get_form_by_token(token):
    """Get form data by token. Return None if token invalid."""
    conn = get_db()
    row = conn.execute("SELECT * FROM patient_forms WHERE token=%s", (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


def submit_previsit_form(token, form_data):
    """Save all form fields, set submitted_at=now. Return False if already submitted."""
    conn = get_db()
    # Check if form exists and is not already submitted
    existing = conn.execute("SELECT id, submitted_at FROM patient_forms WHERE token=%s", (token,)).fetchone()
    if not existing:
        conn.close()
        return False
    if existing["submitted_at"]:
        conn.close()
        return False

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Build medical_history as JSON string if it is a dict/list, otherwise keep as string
    medical_history = form_data.get("medical_history", "")
    if isinstance(medical_history, (dict, list)):
        medical_history = json.dumps(medical_history)

    conn.execute("""UPDATE patient_forms SET
                    full_name=%s, date_of_birth=%s, gender=%s,
                    medical_history=%s, medications=%s, allergies=%s,
                    insurance_provider=%s, insurance_policy=%s,
                    signature_data=%s, submitted_at=%s
                    WHERE token=%s""",
                 (form_data.get("full_name", ""),
                  form_data.get("date_of_birth", ""),
                  form_data.get("gender", ""),
                  medical_history,
                  form_data.get("medications", ""),
                  form_data.get("allergies", ""),
                  form_data.get("insurance_provider", ""),
                  form_data.get("insurance_policy", ""),
                  form_data.get("signature_data", ""),
                  now, token))
    # Mark booking as form submitted
    conn.execute("UPDATE bookings SET form_submitted=1 WHERE id=(SELECT booking_id FROM patient_forms WHERE token=%s)", (token,))
    conn.commit()
    conn.close()
    return True


# Keep old name as alias for backward compatibility
submit_patient_form = submit_previsit_form


def is_form_submitted(token):
    """Check if form was already submitted."""
    conn = get_db()
    row = conn.execute("SELECT submitted_at FROM patient_forms WHERE token=%s", (token,)).fetchone()
    conn.close()
    if not row:
        return False
    return bool(row["submitted_at"])


def get_form_for_booking(booking_id):
    """Get form data for a specific booking (for dashboard display)."""
    conn = get_db()
    row = conn.execute("SELECT * FROM patient_forms WHERE booking_id=%s", (booking_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_patient_submitted_form(admin_id, email="", phone=""):
    """Find a previously submitted form for a returning patient by email or phone."""
    conn = get_db()
    row = None
    # Find patient first
    patient = None
    if phone:
        patient = conn.execute("SELECT id FROM patients WHERE admin_id=%s AND phone=%s", (admin_id, phone)).fetchone()
    if not patient and email:
        patient = conn.execute("SELECT id FROM patients WHERE admin_id=%s AND email=%s", (admin_id, email)).fetchone()
    if patient:
        # Find a submitted form linked to any of this patient's bookings
        row = conn.execute("""
            SELECT pf.* FROM patient_forms pf
            JOIN bookings b ON pf.booking_id = b.id
            WHERE b.patient_id = %s AND pf.submitted_at IS NOT NULL
            ORDER BY pf.submitted_at DESC LIMIT 1
        """, (patient["id"],)).fetchone()
    conn.close()
    return dict(row) if row else None


def clone_form_for_booking(source_form, booking_id, admin_id, patient_name=""):
    """Create a new form record for a booking, pre-filled from a previously submitted form."""
    token = secrets.token_urlsafe(32)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    conn.execute("""INSERT INTO patient_forms
        (booking_id, admin_id, token, full_name, date_of_birth, gender,
         medical_history, medications, allergies, insurance_provider, insurance_policy,
         signature_data, submitted_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (booking_id, admin_id, token,
         source_form.get("full_name") or patient_name,
         source_form.get("date_of_birth", ""),
         source_form.get("gender", ""),
         source_form.get("medical_history", ""),
         source_form.get("medications", ""),
         source_form.get("allergies", ""),
         source_form.get("insurance_provider", ""),
         source_form.get("insurance_policy", ""),
         source_form.get("signature_data", ""),
         now))
    conn.execute("UPDATE bookings SET form_token=%s, form_submitted=1 WHERE id=%s", (token, booking_id))
    conn.commit()
    conn.close()
    return token


# Keep old name as alias for backward compatibility
get_form_by_booking = get_form_for_booking


def sync_form_to_patient(form_data, patient_id):
    """Copy form data (medical_history, allergies, medications, insurance) to patient profile."""
    conn = get_db()
    medical_history = form_data.get("medical_history", "")
    if isinstance(medical_history, (dict, list)):
        medical_history = json.dumps(medical_history)

    conn.execute("""UPDATE patients SET
        date_of_birth=COALESCE(NULLIF(%s,''),(CASE WHEN date_of_birth='' THEN '' ELSE date_of_birth END)),
        gender=COALESCE(NULLIF(%s,''),(CASE WHEN gender='' THEN '' ELSE gender END)),
        medical_history=%s, medications=%s, allergies=%s,
        insurance_provider=%s, insurance_policy=%s,
        conditions=%s
        WHERE id=%s""",
        (form_data.get("date_of_birth", ""),
         form_data.get("gender", ""),
         medical_history,
         form_data.get("medications", ""),
         form_data.get("allergies", ""),
         form_data.get("insurance_provider", ""),
         form_data.get("insurance_policy", ""),
         medical_history,  # conditions = same as medical_history checkboxes
         patient_id))
    conn.commit()
    conn.close()


# ═══════════════ Feature 3: Recall ═══════════════

def add_recall_rule(admin_id, treatment_type, recall_days, message_template=""):
    conn = get_db()
    conn.execute("INSERT INTO recall_rules (admin_id, treatment_type, recall_days, message_template) VALUES (%s,%s,%s,%s)",
                 (admin_id, treatment_type, recall_days, message_template))
    conn.commit()
    conn.close()

def get_recall_rules(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM recall_rules WHERE admin_id=%s ORDER BY treatment_type", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_recall_rule(rule_id, admin_id, **kwargs):
    conn = get_db()
    for k, v in kwargs.items():
        if k in ("treatment_type", "recall_days", "message_template", "is_active"):
            conn.execute(f"UPDATE recall_rules SET {_safe_column(k)}=%s WHERE id=%s AND admin_id=%s", (v, rule_id, admin_id))
    conn.commit()
    conn.close()

def delete_recall_rule(rule_id, admin_id):
    conn = get_db()
    conn.execute("DELETE FROM recall_rules WHERE id=%s AND admin_id=%s", (rule_id, admin_id))
    conn.commit()
    conn.close()

def add_recall_campaign(admin_id, rule_id, patient_name, patient_email="", patient_phone="", recall_type="appointment", service_name="", doctor_name=""):
    conn = get_db()
    token = secrets.token_urlsafe(32)
    _ins_cur = conn.execute(
        "INSERT INTO recall_campaigns (admin_id,rule_id,patient_name,patient_email,patient_phone,recall_type,recall_token,service_name,doctor_name) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (admin_id, rule_id, patient_name, patient_email, patient_phone, recall_type, token, service_name, doctor_name))
    cid = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return {"id": cid, "recall_token": token}


def get_recall_campaign_by_token(token):
    conn = get_db()
    row = conn.execute("SELECT * FROM recall_campaigns WHERE recall_token=%s", (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_recall_booked(campaign_id, booking_id=0):
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE recall_campaigns SET status='booked', booked_at=%s, booking_id=%s WHERE id=%s",
                 (now, booking_id, campaign_id))
    conn.commit()
    conn.close()

def get_recall_campaigns(admin_id, status=None):
    conn = get_db()
    q = "SELECT * FROM recall_campaigns WHERE admin_id=%s"
    params = [admin_id]
    if status:
        q += " AND status=%s"; params.append(status)
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_recall_stats(admin_id):
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM recall_campaigns WHERE admin_id=%s", (admin_id,)).fetchone()["c"]
    sent = conn.execute("SELECT COUNT(*) as c FROM recall_campaigns WHERE admin_id=%s AND status='sent'", (admin_id,)).fetchone()["c"]
    opened = conn.execute("SELECT COUNT(*) as c FROM recall_campaigns WHERE admin_id=%s AND opened_at IS NOT NULL", (admin_id,)).fetchone()["c"]
    booked = conn.execute("SELECT COUNT(*) as c FROM recall_campaigns WHERE admin_id=%s AND booked_at IS NOT NULL", (admin_id,)).fetchone()["c"]
    conn.close()
    return {"total": total, "sent": sent, "opened": opened, "booked": booked}


# ═══════════════ Feature 4: Missed Calls ═══════════════

def log_missed_call(admin_id, caller_number):
    conn = get_db()
    _ins_cur = conn.execute("INSERT INTO missed_calls (admin_id, caller_number) VALUES (%s,%s) RETURNING id", (admin_id, caller_number))
    wid = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return wid

def get_missed_calls(admin_id, limit=50):
    conn = get_db()
    rows = conn.execute("SELECT * FROM missed_calls WHERE admin_id=%s ORDER BY call_time DESC LIMIT %s", (admin_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_missed_call(call_id, **kwargs):
    conn = get_db()
    for k, v in kwargs.items():
        if k in ("reply_sent", "reply_method", "subsequently_booked", "booking_id"):
            conn.execute(f"UPDATE missed_calls SET {_safe_column(k)}=%s WHERE id=%s", (v, call_id))
    conn.commit()
    conn.close()


# ═══════════════ Feature 5: Treatment Follow-Up ═══════════════

def create_treatment_followup(admin_id, doctor_id, patient_name, treatment_name, patient_email="", patient_phone=""):
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d")
    for day in [2, 5, 10]:
        conn.execute("INSERT INTO treatment_followups (admin_id,doctor_id,patient_name,patient_email,patient_phone,treatment_name,recommended_date,followup_day) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                     (admin_id, doctor_id, patient_name, patient_email, patient_phone, treatment_name, now, day))
    conn.commit()
    conn.close()

def get_treatment_followups(admin_id, status=None):
    conn = get_db()
    q = "SELECT * FROM treatment_followups WHERE admin_id=%s"
    params = [admin_id]
    if status:
        q += " AND status=%s"; params.append(status)
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def cancel_treatment_followups(admin_id, patient_name, treatment_name):
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE treatment_followups SET status='cancelled', cancelled_at=%s WHERE admin_id=%s AND patient_name=%s AND treatment_name=%s AND status='pending'",
                 (now, admin_id, patient_name, treatment_name))
    conn.commit()
    conn.close()

def get_due_followups():
    """Get all followups that are due to be sent today."""
    conn = get_db()
    rows = conn.execute("""SELECT * FROM treatment_followups WHERE status='pending'
                           AND recommended_date + (followup_day || ' days')::INTERVAL <= CURRENT_DATE""").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_single_followup(admin_id, doctor_id, patient_name, treatment_name,
                           patient_email="", patient_phone="", booking_id=0):
    """Create a single follow-up entry (from 'Add to Follow-up' button) with a booking token."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d")
    token = secrets.token_urlsafe(32)
    _ins_cur = conn.execute(
        """INSERT INTO treatment_followups
           (admin_id, doctor_id, patient_name, patient_email, patient_phone,
            treatment_name, recommended_date, followup_day, followup_token, booking_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (admin_id, doctor_id, patient_name, patient_email, patient_phone,
         treatment_name, now, 0, token, booking_id))
    fid = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return {"id": fid, "followup_token": token}


def get_followup_by_token(token):
    conn = get_db()
    row = conn.execute("SELECT * FROM treatment_followups WHERE followup_token=%s", (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_followup_booked(followup_id, booking_id=0):
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE treatment_followups SET status='booked', booked_at=%s, booking_id=%s WHERE id=%s",
                 (now, booking_id, followup_id))
    conn.commit()
    conn.close()


# ═══════════════ Feature 7: Gallery ═══════════════

def add_gallery_image(admin_id, treatment_type, image_url, image_type="after", pair_id="", caption=""):
    conn = get_db()
    order = conn.execute("SELECT MAX(sort_order) as mx FROM gallery WHERE admin_id=%s AND treatment_type=%s", (admin_id, treatment_type)).fetchone()["mx"] or 0
    conn.execute("INSERT INTO gallery (admin_id,treatment_type,image_url,image_type,pair_id,caption,sort_order) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                 (admin_id, treatment_type, image_url, image_type, pair_id, caption, order + 1))
    conn.commit()
    conn.close()

def get_gallery(admin_id, treatment_type=None):
    conn = get_db()
    if treatment_type:
        rows = conn.execute("SELECT * FROM gallery WHERE admin_id=%s AND treatment_type=%s ORDER BY sort_order", (admin_id, treatment_type)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM gallery WHERE admin_id=%s ORDER BY treatment_type, sort_order", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_gallery_image(image_id, admin_id):
    conn = get_db()
    conn.execute("DELETE FROM gallery WHERE id=%s AND admin_id=%s", (image_id, admin_id))
    conn.commit()
    conn.close()


# ═══════════════ Feature 10: Live Chat Handoff ═══════════════

def create_handoff(admin_id, session_id, patient_name="", reason="", ai_confidence=0):
    conn = get_db()
    try:
        _ins_cur = conn.execute("INSERT INTO live_chat_handoffs (admin_id,session_id,patient_name,reason,ai_confidence) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                     (admin_id, session_id, patient_name, reason, ai_confidence))
        hid = _ins_cur.fetchone()['id']
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return hid

def get_handoff_queue(admin_id):
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM live_chat_handoffs WHERE admin_id=%s AND status IN ('queued','assigned') ORDER BY created_at", (admin_id,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]

def assign_handoff(handoff_id, staff_user_id, staff_name, admin_id):
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE live_chat_handoffs SET status='assigned', staff_user_id=%s, staff_name=%s, assigned_at=%s WHERE id=%s AND admin_id=%s",
                     (staff_user_id, staff_name, now, handoff_id, admin_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True

def resolve_handoff(handoff_id, notes="", admin_id=None):
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE live_chat_handoffs SET status='resolved', resolved_at=%s, resolution_notes=%s WHERE id=%s AND admin_id=%s",
                     (now, notes, handoff_id, admin_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True

def get_handoff_by_session(session_id, admin_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM live_chat_handoffs WHERE session_id=%s AND admin_id=%s AND status IN ('queued','assigned') ORDER BY created_at DESC LIMIT 1", (session_id, admin_id)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


# ── Enhanced Handoff: Canned Responses ──

def get_canned_responses(admin_id):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM canned_responses WHERE admin_id=%s ORDER BY usage_count DESC, created_at DESC",
            (admin_id,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def create_canned_response(admin_id, title, message, category="Custom", shortcut=""):
    conn = get_db()
    try:
        _ins_cur = conn.execute(
            """INSERT INTO canned_responses (admin_id, title, message, category, shortcut)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (admin_id, title, message, category, shortcut)
        )
        rid = _ins_cur.fetchone()['id']
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return rid


def delete_canned_response(admin_id, response_id):
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM canned_responses WHERE id=%s AND admin_id=%s", (response_id, admin_id))
        conn.commit()
        affected = cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return affected > 0


def increment_canned_usage(response_id, admin_id):
    conn = get_db()
    try:
        conn.execute("UPDATE canned_responses SET usage_count = usage_count + 1 WHERE id=%s AND admin_id=%s", (response_id, admin_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_agent_typing(handoff_id, is_typing, admin_id):
    is_typing = bool(is_typing)
    conn = get_db()
    try:
        if is_typing:
            conn.execute("UPDATE live_chat_handoffs SET typing_at=%s WHERE id=%s AND admin_id=%s",
                         (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), handoff_id, admin_id))
        else:
            conn.execute("UPDATE live_chat_handoffs SET typing_at=NULL WHERE id=%s AND admin_id=%s", (handoff_id, admin_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_handoff_context(handoff_id, admin_id):
    conn = get_db()
    try:
        handoff = conn.execute("SELECT * FROM live_chat_handoffs WHERE id=%s AND admin_id=%s", (handoff_id, admin_id)).fetchone()
        if not handoff:
            return None
        session_id = handoff["session_id"]
        rows = conn.execute(
            "SELECT message, intent, created_at, is_human_handled, handler_user_id FROM chat_logs WHERE session_id=%s ORDER BY created_at ASC",
            (session_id,)
        ).fetchall()
        return {
            "handoff": dict(handoff),
            "messages": [dict(r) for r in rows],
        }
    finally:
        conn.close()


# ═══════════════ Live Chat System ═══════════════

def get_live_chats(admin_id):
    """Get all chat sessions with activity within the configured timeout."""
    timeout_min = get_feature_config(admin_id).get("live_chat_timeout", 8)
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT
                cl.session_id,
                MAX(cl.created_at) as last_activity,
                COUNT(*) as total_messages,
                COUNT(CASE WHEN cl.sender = 'user' THEN 1 END) as user_messages
            FROM chat_logs cl
            WHERE cl.admin_id = %s
            GROUP BY cl.session_id
            HAVING MAX(cl.created_at) > NOW() - (%s || ' minutes')::interval
            ORDER BY MAX(cl.created_at) DESC
        """, (admin_id, str(timeout_min))).fetchall()

        result = []
        for r in rows:
            sid = r["session_id"]
            last_user = conn.execute(
                "SELECT message FROM chat_logs WHERE session_id = %s AND sender = 'user' ORDER BY created_at DESC LIMIT 1",
                (sid,)
            ).fetchone()
            lead = conn.execute(
                "SELECT name, email, phone FROM leads WHERE session_id = %s LIMIT 1",
                (sid,)
            ).fetchone()
            handoff = conn.execute(
                "SELECT staff_user_id, staff_name, status, reason FROM live_chat_handoffs "
                "WHERE session_id = %s AND admin_id = %s AND status IN ('queued','assigned') "
                "ORDER BY created_at DESC LIMIT 1",
                (sid, admin_id)
            ).fetchone()

            result.append({
                "session_id": sid,
                "last_activity": str(r["last_activity"]),
                "total_messages": r["total_messages"],
                "user_messages": r["user_messages"],
                "last_user_message": (last_user["message"] if last_user else "")[:120],
                "customer_name": (lead["name"] if lead else "Visitor"),
                "customer_email": (lead["email"] if lead else ""),
                "assigned_staff_id": handoff["staff_user_id"] if handoff else 0,
                "assigned_staff_name": handoff["staff_name"] if handoff else "",
                "handoff_status": handoff["status"] if handoff else "",
                "needs_human": handoff is not None and handoff["status"] == "queued",
            })
        return result
    finally:
        conn.close()


def take_live_chat(admin_id, session_id, staff_user_id, staff_name):
    """Admin takes a live chat. Only one admin can take at a time."""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT staff_user_id, staff_name FROM live_chat_handoffs "
            "WHERE session_id = %s AND admin_id = %s AND status = 'assigned'",
            (session_id, admin_id)
        ).fetchone()
        if existing and existing["staff_user_id"] != staff_user_id:
            return {"error": "Already taken by " + (existing["staff_name"] or "another admin")}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        queued = conn.execute(
            "SELECT id FROM live_chat_handoffs WHERE session_id = %s AND admin_id = %s "
            "AND status IN ('queued','assigned') ORDER BY created_at DESC LIMIT 1",
            (session_id, admin_id)
        ).fetchone()

        if queued:
            conn.execute(
                "UPDATE live_chat_handoffs SET status='assigned', staff_user_id=%s, "
                "staff_name=%s, assigned_at=%s WHERE id=%s",
                (staff_user_id, staff_name, now, queued["id"])
            )
        else:
            conn.execute(
                "INSERT INTO live_chat_handoffs (admin_id, session_id, patient_name, "
                "reason, status, staff_user_id, staff_name, assigned_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (admin_id, session_id, '', 'admin_takeover', 'assigned',
                 staff_user_id, staff_name, now)
            )
        conn.commit()
        return {"success": True, "staff_name": staff_name}
    finally:
        conn.close()


def release_live_chat(admin_id, session_id, staff_user_id):
    """Admin releases a live chat back to bot."""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE live_chat_handoffs SET status='resolved', resolved_at=%s, "
            "resolution_notes='released' WHERE session_id=%s AND admin_id=%s "
            "AND staff_user_id=%s AND status='assigned'",
            (now, session_id, admin_id, staff_user_id)
        )
        conn.commit()
    finally:
        conn.close()


def send_live_chat_msg(admin_id, session_id, message, staff_name):
    """Log a staff message in a live chat."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO chat_logs (session_id, admin_id, message, intent, "
            "is_human_handled, sender) VALUES (%s,%s,%s,%s,%s,%s)",
            (session_id, admin_id, message, 'live_chat', 1, 'staff')
        )
        conn.commit()
    finally:
        conn.close()


def get_live_chat_messages(admin_id, session_id):
    """Get all messages for a live chat session."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, message, sender, created_at FROM chat_logs "
            "WHERE session_id = %s AND admin_id = %s ORDER BY created_at ASC",
            (session_id, admin_id)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_staff_messages_since(session_id, after_id=0):
    """Get staff messages for widget polling."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, message, created_at FROM chat_logs "
            "WHERE session_id = %s AND sender = 'staff' AND id > %s "
            "ORDER BY created_at ASC",
            (session_id, after_id)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_live_chat_assignment(admin_id, session_id):
    """Check who is assigned to a live chat."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT staff_user_id, staff_name, status FROM live_chat_handoffs "
            "WHERE session_id = %s AND admin_id = %s AND status = 'assigned' "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id, admin_id)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ── Enhanced Inbox: SMS + Analytics ──

def save_sms_to_inbox(admin_id, phone, message, direction, session_id=None):
    """Save an SMS message to channel_messages with channel='sms'."""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        external_id = session_id or phone

        # Find or create conversation
        row = conn.execute(
            "SELECT * FROM channel_conversations WHERE admin_id=%s AND channel_type='sms' AND external_id=%s",
            (admin_id, external_id)
        ).fetchone()

        if row:
            if direction == 'inbound':
                conn.execute(
                    "UPDATE channel_conversations SET last_message_at=%s, unread_count=unread_count+1 WHERE id=%s",
                    (now, row["id"])
                )
            else:
                conn.execute(
                    "UPDATE channel_conversations SET last_message_at=%s WHERE id=%s",
                    (now, row["id"])
                )
            conv_id = row["id"]
        else:
            _ins_cur = conn.execute(
                """INSERT INTO channel_conversations
                   (admin_id, channel_type, external_id, sender_name, phone, last_message_at, unread_count)
                   VALUES (%s, 'sms', %s, %s, %s, %s, %s) RETURNING id""",
                (admin_id, external_id, phone, phone, now, 1 if direction == 'inbound' else 0)
            )
            conv_id = _ins_cur.fetchone()['id']

        # Save message
        sender_name = phone if direction == 'inbound' else 'Staff'
        _ins_cur = conn.execute(
            """INSERT INTO channel_messages
               (admin_id, conversation_id, direction, sender_name, message_text, message_type, created_at)
               VALUES (%s,%s,%s,%s,%s,'text',%s) RETURNING id""",
            (admin_id, conv_id, direction, sender_name, message, now)
        )
        msg_id = _ins_cur.fetchone()['id']
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"conversation_id": conv_id, "message_id": msg_id}


def get_inbox_stats_enhanced(admin_id):
    """Return per-channel conversation counts including SMS."""
    conn = get_db()
    try:
        total = conn.execute(
            "SELECT COUNT(*) as c FROM channel_conversations WHERE admin_id=%s", (admin_id,)
        ).fetchone()["c"]

        unread = conn.execute(
            "SELECT COUNT(*) as c FROM channel_conversations WHERE admin_id=%s AND unread_count > 0", (admin_id,)
        ).fetchone()["c"]

        by_channel = conn.execute(
            "SELECT channel_type, COUNT(*) as c FROM channel_conversations WHERE admin_id=%s GROUP BY channel_type",
            (admin_id,)
        ).fetchall()

        # Per-channel message counts
        msg_by_channel = conn.execute(
            """SELECT cc.channel_type, COUNT(cm.id) as msg_count
               FROM channel_conversations cc
               LEFT JOIN channel_messages cm ON cm.conversation_id = cc.id
               WHERE cc.admin_id=%s
               GROUP BY cc.channel_type""",
            (admin_id,)
        ).fetchall()
    finally:
        conn.close()

    channels = {}
    for ch in ['web', 'whatsapp', 'facebook', 'instagram', 'sms']:
        channels[ch] = {"conversations": 0, "messages": 0}
    for r in by_channel:
        if r["channel_type"] in channels:
            channels[r["channel_type"]]["conversations"] = r["c"]
    for r in msg_by_channel:
        if r["channel_type"] in channels:
            channels[r["channel_type"]]["messages"] = r["msg_count"]

    return {
        "total_conversations": total,
        "unread": unread,
        "channels": channels,
    }


def get_channel_analytics(admin_id, date_from, date_to):
    """Return per-channel analytics: messages/day, response time, resolution rate."""
    conn = get_db()
    try:
        # Note: created_at is TEXT in channel_messages/channel_conversations tables.
        # Use SUBSTR for date comparison and TO_TIMESTAMP for safe casting,
        # with a regex guard to skip rows with non-date strings.
        _date_guard = r"^\d{4}-\d{2}-\d{2}"

        # Messages per channel per day
        messages_per_day = conn.execute(
            """SELECT cc.channel_type, SUBSTR(cm.created_at, 1, 10) as day, COUNT(*) as count
               FROM channel_messages cm
               JOIN channel_conversations cc ON cc.id = cm.conversation_id
               WHERE cc.admin_id=%s
                 AND cm.created_at ~ %s
                 AND SUBSTR(cm.created_at, 1, 10) BETWEEN %s AND %s
               GROUP BY cc.channel_type, SUBSTR(cm.created_at, 1, 10)
               ORDER BY day""",
            (admin_id, _date_guard, date_from, date_to)
        ).fetchall()

        # Average response time per channel (time between inbound and next outbound in same conversation)
        response_times = conn.execute(
            """SELECT cc.channel_type,
                      AVG(EXTRACT(EPOCH FROM (TO_TIMESTAMP(reply.created_at, 'YYYY-MM-DD HH24:MI:SS')
                          - TO_TIMESTAMP(inb.created_at, 'YYYY-MM-DD HH24:MI:SS'))) / 60) as avg_response_min
               FROM channel_messages inb
               JOIN channel_conversations cc ON cc.id = inb.conversation_id
               JOIN LATERAL (
                   SELECT created_at FROM channel_messages
                   WHERE conversation_id = inb.conversation_id
                     AND direction = 'outbound'
                     AND created_at ~ %s
                     AND created_at > inb.created_at
                   ORDER BY created_at ASC LIMIT 1
               ) reply ON TRUE
               WHERE cc.admin_id=%s AND inb.direction='inbound'
                 AND inb.created_at ~ %s
                 AND SUBSTR(inb.created_at, 1, 10) BETWEEN %s AND %s
               GROUP BY cc.channel_type""",
            (_date_guard, admin_id, _date_guard, date_from, date_to)
        ).fetchall()

        # Resolution rate per channel
        resolution_rates = conn.execute(
            """SELECT channel_type,
                      COUNT(*) as total,
                      COUNT(CASE WHEN status='resolved' THEN 1 END) as resolved
               FROM channel_conversations
               WHERE admin_id=%s
                 AND created_at ~ %s
                 AND SUBSTR(created_at, 1, 10) BETWEEN %s AND %s
               GROUP BY channel_type""",
            (admin_id, _date_guard, date_from, date_to)
        ).fetchall()
    finally:
        conn.close()

    return {
        "messages_per_day": [dict(r) for r in messages_per_day],
        "response_times": {r["channel_type"]: round(r["avg_response_min"] or 0, 1) for r in response_times},
        "resolution_rates": {
            r["channel_type"]: {
                "total": r["total"],
                "resolved": r["resolved"],
                "rate": round(r["resolved"] / r["total"] * 100, 1) if r["total"] > 0 else 0
            }
            for r in resolution_rates
        },
    }


# ═══════════════ Feature 11: Schedule Blocks (rebuilt) ═══════════════

def _parse_time_to_minutes(time_str):
    """Parse '09:00 AM' or '01:30 PM' to total minutes since midnight."""
    import re as _re
    if not time_str:
        return None
    time_str = time_str.strip()
    m = _re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str, _re.IGNORECASE)
    if not m:
        return None
    h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ampm == 'PM' and h < 12:
        h += 12
    if ampm == 'AM' and h == 12:
        h = 0
    return h * 60 + mi


def create_schedule_block(admin_id, doctor_id, block_type, start_date, end_date=None,
                          start_time=None, end_time=None, recurring_pattern=None,
                          recurring_day=None, label=None):
    """Create a new schedule block. Returns the new block ID."""
    conn = get_db()
    _ins_cur = conn.execute(
        """INSERT INTO schedule_blocks
           (admin_id, doctor_id, block_type, start_date, end_date,
            start_time, end_time, recurring_pattern, recurring_day, label, is_active)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1) RETURNING id""",
        (admin_id, doctor_id, block_type, start_date,
         end_date or start_date, start_time or "", end_time or "",
         recurring_pattern or "", recurring_day, label or ""))
    bid = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return bid


def get_schedule_blocks(admin_id, doctor_id=None):
    """Get all active blocks for an admin (optionally filtered by doctor)."""
    conn = get_db()
    if doctor_id is not None:
        rows = conn.execute(
            """SELECT * FROM schedule_blocks
               WHERE admin_id=%s AND is_active=1
               AND (doctor_id=%s OR doctor_id IS NULL)
               ORDER BY start_date""",
            (admin_id, doctor_id)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM schedule_blocks WHERE admin_id=%s AND is_active=1 ORDER BY start_date",
            (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_schedule_block(block_id, admin_id=None):
    """Delete a single block (or single occurrence of a recurring block)."""
    conn = get_db()
    if admin_id is not None:
        conn.execute("DELETE FROM schedule_blocks WHERE id=%s AND admin_id=%s", (block_id, admin_id))
    else:
        conn.execute("DELETE FROM schedule_blocks WHERE id=%s", (block_id,))
    conn.commit()
    conn.close()


def delete_recurring_series(block_id):
    """Delete all occurrences of a recurring block series.
    Uses the block's attributes to find siblings with the same pattern."""
    conn = get_db()
    row = conn.execute("SELECT * FROM schedule_blocks WHERE id=%s", (block_id,)).fetchone()
    if row:
        conn.execute(
            """DELETE FROM schedule_blocks
               WHERE admin_id=%s AND doctor_id IS NOT DISTINCT FROM %s AND block_type='recurring'
               AND recurring_pattern=%s AND recurring_day IS NOT DISTINCT FROM %s
               AND label=%s""",
            (row["admin_id"], row["doctor_id"], row["recurring_pattern"],
             row["recurring_day"], row["label"]))
        conn.commit()
    conn.close()


def _date_matches_recurring(date_obj, block):
    """Check whether a date matches a recurring block pattern."""
    pattern = block.get("recurring_pattern", "")
    if not pattern:
        return False

    # Check date is within the block's date range
    start_d = block.get("start_date", "")
    end_d = block.get("end_date", "")
    date_iso = date_obj.strftime("%Y-%m-%d") if hasattr(date_obj, 'strftime') else str(date_obj)
    if start_d and date_iso < start_d:
        return False
    if end_d and date_iso > end_d:
        return False

    rec_day = block.get("recurring_day")

    if pattern == "daily":
        return True
    elif pattern == "weekly":
        # recurring_day: 0=Monday .. 6=Sunday
        if rec_day is not None:
            return date_obj.weekday() == int(rec_day)
        return False
    elif pattern == "monthly":
        # recurring_day: 1-31 day of month
        if rec_day is not None:
            return date_obj.day == int(rec_day)
        return False
    return False


def is_slot_blocked(admin_id, doctor_id, date_str, time_str=None):
    """Check if a specific date+time is blocked.
    Checks clinic-wide blocks (doctor_id IS NULL), doctor-specific blocks,
    single date blocks, date range blocks, and recurring blocks.
    Returns True if blocked, False if available."""
    from datetime import datetime as dt
    conn = get_db()
    try:
        date_obj = dt.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        conn.close()
        return False

    # Fetch all active blocks that could apply (clinic-wide + doctor-specific)
    rows = conn.execute(
        """SELECT * FROM schedule_blocks
           WHERE admin_id=%s AND is_active=1
           AND (doctor_id IS NULL OR doctor_id=%s)""",
        (admin_id, doctor_id)).fetchall()
    conn.close()

    slot_mins = None
    if time_str:
        # Extract just the start time from formats like "09:00 AM - 10:00 AM"
        start_part = time_str.split(" - ")[0].strip() if " - " in time_str else time_str.strip()
        slot_mins = _parse_time_to_minutes(start_part)

    for block in rows:
        matches_date = False
        btype = block["block_type"] or "single_date"

        if btype == "single_date":
            matches_date = (block["start_date"] == date_str)
        elif btype == "date_range":
            sd = block["start_date"] or ""
            ed = block["end_date"] or sd
            matches_date = (sd <= date_str <= ed)
        elif btype == "recurring":
            matches_date = _date_matches_recurring(date_obj, block)

        if not matches_date:
            continue

        # Date matches — now check time
        blk_start = block["start_time"] or ""
        blk_end = block["end_time"] or ""

        if not blk_start and not blk_end:
            # Full-day block
            return True

        if blk_start and blk_end:
            # Time-range block — only blocked if slot falls within range
            if slot_mins is not None:
                bs = _parse_time_to_minutes(blk_start)
                be = _parse_time_to_minutes(blk_end)
                if bs is not None and be is not None and bs <= slot_mins < be:
                    return True
            elif time_str is None:
                # No time given but there IS a time-range block — partial day block.
                # We don't consider the date fully blocked.
                continue

    return False


def get_blocked_dates_for_calendar(admin_id, doctor_id, year, month):
    """Return list of date strings (YYYY-MM-DD) that are fully blocked in a given month.
    A date is 'fully blocked' if there is a full-day block (no start_time/end_time)
    covering it. Used for greying out calendar dates."""
    from datetime import datetime as dt
    import calendar as cal_mod
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM schedule_blocks
           WHERE admin_id=%s AND is_active=1
           AND (doctor_id IS NULL OR doctor_id=%s)
           AND (start_time='' OR start_time IS NULL)
           AND (end_time='' OR end_time IS NULL)""",
        (admin_id, doctor_id)).fetchall()
    conn.close()

    _, days_in_month = cal_mod.monthrange(year, month)
    blocked_dates = set()

    for day in range(1, days_in_month + 1):
        date_obj = dt(year, month, day)
        date_str = date_obj.strftime("%Y-%m-%d")

        for block in rows:
            btype = block["block_type"] or "single_date"
            matched = False

            if btype == "single_date":
                matched = (block["start_date"] == date_str)
            elif btype == "date_range":
                sd = block["start_date"] or ""
                ed = block["end_date"] or sd
                matched = (sd <= date_str <= ed)
            elif btype == "recurring":
                matched = _date_matches_recurring(date_obj, block)

            if matched:
                blocked_dates.add(date_str)
                break

    return list(blocked_dates)


def get_bookings_on_date(admin_id, date_str, doctor_id=None):
    """Return count of confirmed bookings on a date (for warning when blocking)."""
    conn = get_db()
    if doctor_id:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND date=%s AND doctor_id=%s AND status='confirmed'",
            (admin_id, date_str, doctor_id)).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id=%s AND date=%s AND status='confirmed'",
            (admin_id, date_str)).fetchone()
    conn.close()
    return row["c"] if row else 0


# ═══════════════ Feature 12: Promotions ═══════════════

def create_promotion(admin_id, code, discount_type, discount_value, applicable_treatments="all", expiry_date="", max_uses=0, min_booking_value=0):
    conn = get_db()
    _ins_cur = conn.execute("INSERT INTO promotions (admin_id,code,discount_type,discount_value,applicable_treatments,expiry_date,max_uses,min_booking_value) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                 (admin_id, code, discount_type, discount_value, applicable_treatments, expiry_date, max_uses, min_booking_value))
    pid = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return pid

def validate_promotion(code, admin_id, treatment="", booking_value=0):
    conn = get_db()
    row = conn.execute("SELECT * FROM promotions WHERE code=%s AND admin_id=%s AND is_active=1", (code, admin_id)).fetchone()
    if not row:
        conn.close()
        return None, "Invalid discount code."
    promo = dict(row)
    if promo["expiry_date"] and promo["expiry_date"] < datetime.now().strftime("%Y-%m-%d"):
        conn.close()
        return None, "This discount code has expired."
    if promo["max_uses"] > 0 and promo["current_uses"] >= promo["max_uses"]:
        conn.close()
        return None, "This discount code has reached its usage limit."
    if promo["min_booking_value"] > 0 and booking_value < promo["min_booking_value"]:
        conn.close()
        return None, f"Minimum booking value of ${promo['min_booking_value']:.0f} required."
    if promo["applicable_treatments"] != "all" and treatment:
        treatments = [t.strip().lower() for t in promo["applicable_treatments"].split(",")]
        if treatment.lower() not in treatments:
            conn.close()
            return None, "This code is not valid for the selected treatment."
    conn.close()
    return promo, None

def use_promotion(promotion_id, booking_id=0, patient_name="", patient_email="", discount_amount=0, original_amount=0):
    conn = get_db()
    conn.execute("INSERT INTO promotion_usage (promotion_id,booking_id,patient_name,patient_email,discount_amount,original_amount) VALUES (%s,%s,%s,%s,%s,%s)",
                 (promotion_id, booking_id, patient_name, patient_email, discount_amount, original_amount))
    conn.execute("UPDATE promotions SET current_uses = current_uses + 1 WHERE id=%s", (promotion_id,))
    conn.commit()
    conn.close()

def get_promotions(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM promotions WHERE admin_id=%s ORDER BY created_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_promotion_stats(admin_id):
    conn = get_db()
    rows = conn.execute("""SELECT p.*, COUNT(pu.id) as total_uses, SUM(pu.discount_amount) as total_discount, SUM(pu.original_amount) as total_revenue
                           FROM promotions p LEFT JOIN promotion_usage pu ON p.id = pu.promotion_id
                           WHERE p.admin_id=%s GROUP BY p.id ORDER BY p.created_at DESC""", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_promotion(promo_id, admin_id):
    conn = get_db()
    conn.execute("UPDATE promotions SET is_active=0 WHERE id=%s AND admin_id=%s", (promo_id, admin_id))
    conn.commit()
    conn.close()


# ═══════════════ Feature 14: Referrals ═══════════════

def create_referral_code(admin_id):
    code = "REF-" + secrets.token_hex(4).upper()
    conn = get_db()
    conn.execute("UPDATE users SET referral_code=%s WHERE id=%s", (code, admin_id))
    conn.commit()
    conn.close()
    return code

def get_referral_by_code(code):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE referral_code=%s", (code,)).fetchone()
    conn.close()
    return dict(row) if row else None

def track_referral(referrer_admin_id, referred_email, referral_code):
    conn = get_db()
    conn.execute("INSERT INTO referrals (referrer_admin_id, referred_email, referral_code) VALUES (%s,%s,%s)",
                 (referrer_admin_id, referred_email, referral_code))
    conn.commit()
    conn.close()

def get_referrals(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM referrals WHERE referrer_admin_id=%s ORDER BY created_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def convert_referral(referred_admin_id, referral_code):
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE referrals SET referred_admin_id=%s, status='converted', converted_at=%s WHERE referral_code=%s AND status='pending'",
                 (referred_admin_id, now, referral_code))
    conn.commit()
    conn.close()


# ═══════════════ Feature 15: Patient Profiles ═══════════════

def get_or_create_patient(admin_id, name="", email="", phone="", increment_booking=True):
    conn = get_db()
    # Try to find by phone or email
    row = None
    if phone:
        row = conn.execute("SELECT * FROM patients WHERE admin_id=%s AND phone=%s", (admin_id, phone)).fetchone()
    if not row and email:
        row = conn.execute("SELECT * FROM patients WHERE admin_id=%s AND email=%s", (admin_id, email)).fetchone()
    if row:
        # Update name if provided
        if name and not row["name"]:
            conn.execute("UPDATE patients SET name=%s WHERE id=%s", (name, row["id"]))
        # Increment booking count
        if increment_booking:
            conn.execute("UPDATE patients SET total_bookings=total_bookings+1 WHERE id=%s", (row["id"],))
        conn.commit()
        row = conn.execute("SELECT * FROM patients WHERE id=%s", (row["id"],)).fetchone()
        conn.close()
        return dict(row)
    # Plan limit check: patients (Free plan = 20 max)
    plan = get_admin_plan(admin_id)
    max_patients = PLAN_MAX_PATIENTS.get(plan, 999999999)
    if max_patients < 999999999:
        patient_count = conn.execute("SELECT COUNT(*) as c FROM patients WHERE admin_id=%s", (admin_id,)).fetchone()["c"]
        if patient_count >= max_patients:
            conn.close()
            return None  # Caller should handle upgrade prompt
    # Create new patient
    _ins_cur = conn.execute("INSERT INTO patients (admin_id,name,email,phone,total_bookings) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                 (admin_id, name, email, phone, 1 if increment_booking else 0))
    pid = _ins_cur.fetchone()['id']
    conn.commit()
    row = conn.execute("SELECT * FROM patients WHERE id=%s", (pid,)).fetchone()
    conn.close()
    patient_dict = dict(row) if row else None
    # ── Zapier webhook: new patient ──
    if patient_dict:
        try:
            import zapier_engine
            zapier_engine.trigger_new_patient(admin_id, patient_dict)
        except Exception:
            pass  # webhook is fire-and-forget; conn is already closed
    return patient_dict

def get_patient(patient_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM patients WHERE id=%s", (patient_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_patients(admin_id, search=""):
    conn = get_db()
    if search:
        rows = conn.execute("SELECT * FROM patients WHERE admin_id=%s AND (name ILIKE %s OR email ILIKE %s OR phone ILIKE %s) ORDER BY name",
                            (admin_id, f"%{search}%", f"%{search}%", f"%{search}%")).fetchall()
    else:
        rows = conn.execute("SELECT * FROM patients WHERE admin_id=%s ORDER BY name", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_patient_history(patient_id):
    conn = get_db()
    bookings = conn.execute("SELECT * FROM bookings WHERE patient_id=%s ORDER BY date DESC", (patient_id,)).fetchall()
    forms = conn.execute("SELECT pf.* FROM patient_forms pf JOIN bookings b ON pf.booking_id=b.id WHERE b.patient_id=%s", (patient_id,)).fetchall()
    notes = conn.execute("SELECT * FROM patient_notes WHERE patient_id=%s ORDER BY created_at DESC", (patient_id,)).fetchall()
    conn.close()
    return {
        "bookings": [dict(r) for r in bookings],
        "forms": [dict(r) for r in forms],
        "notes": [dict(r) for r in notes]
    }

def update_patient(patient_id, **kwargs):
    conn = get_db()
    allowed = ("name", "email", "phone", "date_of_birth", "gender", "language", "notes",
               "last_visit_date", "loyalty_points", "medical_history", "medications",
               "allergies", "insurance_provider", "insurance_policy", "conditions",
               "last_treatment", "total_bookings", "total_completed", "total_cancelled", "total_no_shows")
    for k, v in kwargs.items():
        if k in allowed:
            conn.execute(f"UPDATE patients SET {_safe_column(k)}=%s WHERE id=%s", (v, patient_id))
    conn.commit()
    conn.close()

def delete_patient(patient_id, admin_id):
    """Delete a patient record. Does NOT delete their bookings — only the patient entry,
    their submitted forms, and notes. Next time they book, they'll be treated as new."""
    conn = get_db()
    # Verify patient belongs to this admin
    patient = conn.execute("SELECT id FROM patients WHERE id=%s AND admin_id=%s", (patient_id, admin_id)).fetchone()
    if not patient:
        conn.close()
        return False
    # Remove patient_id from their bookings (keep bookings intact)
    conn.execute("UPDATE bookings SET patient_id=NULL WHERE patient_id=%s AND admin_id=%s", (patient_id, admin_id))
    # Delete submitted forms linked to this patient's bookings
    conn.execute("DELETE FROM patient_forms WHERE admin_id=%s AND booking_id IN (SELECT id FROM bookings WHERE admin_id=%s AND customer_email IN (SELECT email FROM patients WHERE id=%s))", (admin_id, admin_id, patient_id))
    # Delete patient notes
    conn.execute("DELETE FROM patient_notes WHERE patient_id=%s", (patient_id,))
    # Delete the patient record
    conn.execute("DELETE FROM patients WHERE id=%s AND admin_id=%s", (patient_id, admin_id))
    conn.commit()
    conn.close()
    return True


def add_patient_note(patient_id, doctor_id, note, booking_id=0):
    conn = get_db()
    conn.execute("INSERT INTO patient_notes (patient_id,doctor_id,booking_id,note) VALUES (%s,%s,%s,%s)",
                 (patient_id, doctor_id, booking_id, note))
    conn.commit()
    conn.close()


# ═══════════════ Feature 17: A/B Testing ═══════════════

def create_ab_test(admin_id, test_name, test_type, variant_a, variant_b):
    conn = get_db()
    _ins_cur = conn.execute("INSERT INTO ab_tests (admin_id,test_name,test_type,variant_a,variant_b) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                 (admin_id, test_name, test_type, variant_a, variant_b))
    tid = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return tid

def get_ab_tests(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM ab_tests WHERE admin_id=%s ORDER BY created_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_active_ab_test(admin_id, test_type):
    conn = get_db()
    row = conn.execute("SELECT * FROM ab_tests WHERE admin_id=%s AND test_type=%s AND status='running' ORDER BY created_at DESC LIMIT 1",
                       (admin_id, test_type)).fetchone()
    conn.close()
    return dict(row) if row else None

def increment_ab_test(test_id, variant, booked=False):
    conn = get_db()
    if variant == "a":
        conn.execute("UPDATE ab_tests SET variant_a_conversations = variant_a_conversations + 1 WHERE id=%s", (test_id,))
        if booked:
            conn.execute("UPDATE ab_tests SET variant_a_bookings = variant_a_bookings + 1 WHERE id=%s", (test_id,))
    else:
        conn.execute("UPDATE ab_tests SET variant_b_conversations = variant_b_conversations + 1 WHERE id=%s", (test_id,))
        if booked:
            conn.execute("UPDATE ab_tests SET variant_b_bookings = variant_b_bookings + 1 WHERE id=%s", (test_id,))
    conn.commit()
    conn.close()

def end_ab_test(test_id, winner):
    conn = get_db()
    conn.execute("UPDATE ab_tests SET status='completed', winner=%s WHERE id=%s", (winner, test_id))
    conn.commit()
    conn.close()


# ═══════════════ Feature 18: Loyalty Program ═══════════════

def get_loyalty_config(admin_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM loyalty_config WHERE admin_id=%s", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def save_loyalty_config(admin_id, **kwargs):
    conn = get_db()
    existing = conn.execute("SELECT id FROM loyalty_config WHERE admin_id=%s", (admin_id,)).fetchone()
    if existing:
        for k, v in kwargs.items():
            if k in ("points_per_appointment","points_per_referral","points_per_review","points_per_form","redemption_value","is_active"):
                conn.execute(f"UPDATE loyalty_config SET {_safe_column(k)}=%s WHERE admin_id=%s", (v, admin_id))
    else:
        conn.execute("INSERT INTO loyalty_config (admin_id) VALUES (%s)", (admin_id,))
        for k, v in kwargs.items():
            if k in ("points_per_appointment","points_per_referral","points_per_review","points_per_form","redemption_value","is_active"):
                conn.execute(f"UPDATE loyalty_config SET {_safe_column(k)}=%s WHERE admin_id=%s", (v, admin_id))
    conn.commit()
    conn.close()

def add_loyalty_points(patient_id, admin_id, points, action, description="", booking_id=0):
    conn = get_db()
    conn.execute("INSERT INTO loyalty_transactions (patient_id,admin_id,points,action,description,booking_id) VALUES (%s,%s,%s,%s,%s,%s)",
                 (patient_id, admin_id, points, action, description, booking_id))
    conn.execute("UPDATE patients SET loyalty_points = loyalty_points + %s WHERE id=%s", (points, patient_id))
    conn.commit()
    conn.close()

def redeem_loyalty_points(patient_id, admin_id, points, description="", booking_id=0):
    conn = get_db()
    patient = conn.execute("SELECT loyalty_points FROM patients WHERE id=%s", (patient_id,)).fetchone()
    if not patient or patient["loyalty_points"] < points:
        conn.close()
        return False, "Insufficient loyalty points."
    conn.execute("INSERT INTO loyalty_transactions (patient_id,admin_id,points,action,description,booking_id) VALUES (%s,%s,%s,%s,%s,%s)",
                 (patient_id, admin_id, -points, "redeem", description, booking_id))
    conn.execute("UPDATE patients SET loyalty_points = loyalty_points - %s WHERE id=%s", (points, patient_id))
    conn.commit()
    conn.close()
    return True, "Points redeemed successfully."

def get_loyalty_stats(admin_id):
    conn = get_db()
    now = datetime.now()
    month_start = now.strftime("%Y-%m-01")
    total_members = conn.execute("SELECT COUNT(*) as c FROM patients WHERE admin_id=%s AND loyalty_points > 0", (admin_id,)).fetchone()["c"]
    issued = conn.execute("SELECT COALESCE(SUM(points),0) as s FROM loyalty_transactions WHERE admin_id=%s AND points>0 AND created_at>=%s", (admin_id, month_start)).fetchone()["s"]
    redeemed = conn.execute("SELECT COALESCE(SUM(ABS(points)),0) as s FROM loyalty_transactions WHERE admin_id=%s AND points<0 AND created_at>=%s", (admin_id, month_start)).fetchone()["s"]
    top = conn.execute("SELECT p.name, p.loyalty_points FROM patients p WHERE p.admin_id=%s AND p.loyalty_points>0 ORDER BY p.loyalty_points DESC LIMIT 10", (admin_id,)).fetchall()
    conn.close()
    return {"total_members": total_members, "issued_this_month": issued, "redeemed_this_month": redeemed, "top_patients": [dict(r) for r in top]}


# ═══════════════ Feature 19: GMB ═══════════════

def save_gmb_connection(admin_id, **kwargs):
    conn = get_db()
    existing = conn.execute("SELECT id FROM gmb_connections WHERE admin_id=%s", (admin_id,)).fetchone()
    if existing:
        for k, v in kwargs.items():
            if k in ("google_account_id","location_id","access_token","refresh_token","rating","review_count","last_synced_at"):
                conn.execute(f"UPDATE gmb_connections SET {_safe_column(k)}=%s WHERE admin_id=%s", (v, admin_id))
    else:
        conn.execute("INSERT INTO gmb_connections (admin_id) VALUES (%s)", (admin_id,))
        for k, v in kwargs.items():
            if k in ("google_account_id","location_id","access_token","refresh_token","rating","review_count","last_synced_at"):
                conn.execute(f"UPDATE gmb_connections SET {_safe_column(k)}=%s WHERE admin_id=%s", (v, admin_id))
    conn.commit()
    conn.close()

def get_gmb_connection(admin_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM gmb_connections WHERE admin_id=%s", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ═══════════════ Feature 20: Benchmarking ═══════════════

def update_clinic_metrics(admin_id, **kwargs):
    conn = get_db()
    existing = conn.execute("SELECT id FROM clinic_metrics_cache WHERE admin_id=%s", (admin_id,)).fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if existing:
        for k, v in kwargs.items():
            if k in ("conversion_rate","noshow_rate","avg_response_time","monthly_bookings","review_score","city"):
                conn.execute(f"UPDATE clinic_metrics_cache SET {_safe_column(k)}=%s, updated_at=%s WHERE admin_id=%s", (v, now, admin_id))
    else:
        conn.execute("INSERT INTO clinic_metrics_cache (admin_id, updated_at) VALUES (%s,%s)", (admin_id, now))
        for k, v in kwargs.items():
            if k in ("conversion_rate","noshow_rate","avg_response_time","monthly_bookings","review_score","city"):
                conn.execute(f"UPDATE clinic_metrics_cache SET {_safe_column(k)}=%s, updated_at=%s WHERE admin_id=%s", (v, now, admin_id))
    conn.commit()
    conn.close()

def get_benchmark_data(admin_id):
    conn = get_db()
    my = conn.execute("SELECT * FROM clinic_metrics_cache WHERE admin_id=%s", (admin_id,)).fetchone()
    total_clinics = conn.execute("SELECT COUNT(*) as c FROM clinic_metrics_cache").fetchone()["c"]
    if total_clinics < 5:
        conn.close()
        return {"available": False, "reason": "Need at least 5 clinics for benchmarking", "total_clinics": total_clinics}
    avg = conn.execute("""SELECT AVG(conversion_rate) as avg_conv, AVG(noshow_rate) as avg_noshow,
                          AVG(avg_response_time) as avg_resp, AVG(monthly_bookings) as avg_bookings,
                          AVG(review_score) as avg_review FROM clinic_metrics_cache""").fetchone()
    top10 = conn.execute("""SELECT AVG(conversion_rate) as top_conv, AVG(noshow_rate) as top_noshow,
                            AVG(avg_response_time) as top_resp, AVG(monthly_bookings) as top_bookings,
                            AVG(review_score) as top_review FROM (
                                SELECT * FROM clinic_metrics_cache ORDER BY monthly_bookings DESC LIMIT GREATEST(1, (SELECT COUNT(*)/10 FROM clinic_metrics_cache))
                            )""").fetchone()
    conn.close()
    return {
        "available": True,
        "total_clinics": total_clinics,
        "my_metrics": dict(my) if my else {},
        "platform_avg": dict(avg) if avg else {},
        "top_10_pct": dict(top10) if top10 else {}
    }


# ── Customer (SaaS) Management ──────────────────────────────────────────────

def create_customer(business_name, owner_name, email, **kwargs):
    conn = get_db()
    api_key = secrets.token_urlsafe(32)
    api_secret = secrets.token_urlsafe(48)
    verification_token = secrets.token_urlsafe(24)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _ins_cur = conn.execute("""INSERT INTO customers
        (business_name, owner_name, email, phone, website, country, city, address, industry,
         plan, api_key, api_secret, verification_token, status, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (business_name, owner_name, email,
         kwargs.get("phone",""), kwargs.get("website",""),
         kwargs.get("country",""), kwargs.get("city",""),
         kwargs.get("address",""), kwargs.get("industry","dental"),
         kwargs.get("plan","free_trial"), api_key, api_secret,
         verification_token, "pending", now))
    cid = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return cid


def get_customer(customer_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM customers WHERE id=%s", (customer_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_customer_by_email(email):
    conn = get_db()
    row = conn.execute("SELECT * FROM customers WHERE email=%s", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_customer_by_api_key(api_key):
    conn = get_db()
    row = conn.execute("SELECT * FROM customers WHERE api_key=%s AND status='active'", (api_key,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_customers(status=None):
    conn = get_db()
    if status:
        rows = conn.execute("SELECT * FROM customers WHERE status=%s ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM customers ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_customer(customer_id, **kwargs):
    conn = get_db()
    allowed = ("business_name","owner_name","email","phone","website","country","city",
               "address","industry","logo_url","plan","plan_expires_at","billing_cycle",
               "paypal_customer_id","paypal_subscription_id","is_verified","status",
               "webhook_url","allowed_domains","chatbot_name","chatbot_color",
               "chatbot_position","chatbot_language","chatbot_welcome_msg",
               "max_admins","max_doctors","max_monthly_chats","max_bookings",
               "head_admin_user_id","last_active_at")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for k, v in kwargs.items():
        if k in allowed:
            conn.execute(f"UPDATE customers SET {_safe_column(k)}=%s, updated_at=%s WHERE id=%s", (v, now, customer_id))
    conn.commit()
    conn.close()


def verify_customer(customer_id):
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE customers SET is_verified=1, verified_at=%s, status='active', updated_at=%s WHERE id=%s",
                 (now, now, customer_id))
    conn.commit()
    conn.close()


def verify_customer_by_token(token):
    conn = get_db()
    row = conn.execute("SELECT id FROM customers WHERE verification_token=%s", (token,)).fetchone()
    if not row:
        conn.close()
        return None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE customers SET is_verified=1, verified_at=%s, status='active', verification_token='', updated_at=%s WHERE id=%s",
                 (now, now, row["id"]))
    conn.commit()
    conn.close()
    return row["id"]


def delete_customer(customer_id):
    conn = get_db()
    conn.execute("DELETE FROM customers WHERE id=%s", (customer_id,))
    conn.commit()
    conn.close()


def regenerate_customer_api_key(customer_id):
    conn = get_db()
    new_key = secrets.token_urlsafe(32)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE customers SET api_key=%s, updated_at=%s WHERE id=%s", (new_key, now, customer_id))
    conn.commit()
    conn.close()
    return new_key


def track_customer_usage(customer_id, chats=0, bookings=0, leads=0, api_calls=0):
    conn = get_db()
    month = datetime.now().strftime("%Y-%m")
    existing = conn.execute("SELECT id FROM customer_usage WHERE customer_id=%s AND month=%s", (customer_id, month)).fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if existing:
        conn.execute("""UPDATE customer_usage SET
            total_chats=total_chats+%s, total_bookings=total_bookings+%s,
            total_leads=total_leads+%s, total_api_calls=total_api_calls+%s, updated_at=%s
            WHERE customer_id=%s AND month=%s""",
            (chats, bookings, leads, api_calls, now, customer_id, month))
    else:
        conn.execute("""INSERT INTO customer_usage (customer_id, month, total_chats, total_bookings, total_leads, total_api_calls, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""", (customer_id, month, chats, bookings, leads, api_calls, now))
    conn.commit()
    conn.close()


def get_customer_usage(customer_id, month=None):
    conn = get_db()
    if not month:
        month = datetime.now().strftime("%Y-%m")
    row = conn.execute("SELECT * FROM customer_usage WHERE customer_id=%s AND month=%s", (customer_id, month)).fetchone()
    conn.close()
    return dict(row) if row else {"total_chats": 0, "total_bookings": 0, "total_leads": 0, "total_api_calls": 0}


def create_customer_invoice(customer_id, amount, currency="USD", period_start="", period_end=""):
    conn = get_db()
    inv_num = f"INV-{customer_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    conn.execute("""INSERT INTO customer_invoices
        (customer_id, invoice_number, amount, currency, period_start, period_end)
        VALUES (%s,%s,%s,%s,%s,%s)""", (customer_id, inv_num, amount, currency, period_start, period_end))
    conn.commit()
    conn.close()
    return inv_num


def get_customer_invoices(customer_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM customer_invoices WHERE customer_id=%s ORDER BY created_at DESC", (customer_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Smart Appointment Reminders ──────────────────────────────────────────────

def create_appointment_reminder(booking_id, admin_id, reminder_type, scheduled_for, job_id=""):
    """Insert a reminder row and return its id."""
    conn = get_db()
    _ins_cur = conn.execute(
        """INSERT INTO appointment_reminders
           (booking_id, admin_id, reminder_type, scheduled_for, job_id)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (booking_id, admin_id, reminder_type, scheduled_for, job_id)
    )
    rid = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return rid


def get_reminders_for_booking(booking_id):
    """Return all reminders for a booking."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM appointment_reminders WHERE booking_id = %s ORDER BY scheduled_for",
        (booking_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_reminder_status(reminder_id, status, sent_at=None):
    """Update the status of a reminder."""
    conn = get_db()
    if sent_at:
        conn.execute(
            "UPDATE appointment_reminders SET status = %s, sent_at = %s WHERE id = %s",
            (status, sent_at, reminder_id)
        )
    else:
        conn.execute(
            "UPDATE appointment_reminders SET status = %s WHERE id = %s",
            (status, reminder_id)
        )
    conn.commit()
    conn.close()


def update_reminder_tokens(reminder_id, confirm_token, cancel_token):
    """Store confirm/cancel tokens on a reminder."""
    conn = get_db()
    conn.execute(
        "UPDATE appointment_reminders SET confirm_token = %s, cancel_token = %s WHERE id = %s",
        (confirm_token, cancel_token, reminder_id)
    )
    conn.commit()
    conn.close()


def get_reminder_by_token(token):
    """Look up a reminder by its confirm or cancel token."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM appointment_reminders WHERE confirm_token = %s OR cancel_token = %s",
        (token, token)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def record_reminder_response(reminder_id, response):
    """Record confirmed/cancelled response with timestamp."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE appointment_reminders SET patient_response = %s, responded_at = %s WHERE id = %s",
        (response, now, reminder_id)
    )
    conn.commit()
    conn.close()


def get_pending_reminders():
    """Return reminders where status='pending' and scheduled_for <= now."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT * FROM appointment_reminders WHERE status = 'pending' AND scheduled_for <= %s",
        (now,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cancel_reminders_for_booking(booking_id):
    """Set status='skipped' for all pending reminders of a booking."""
    conn = get_db()
    conn.execute(
        "UPDATE appointment_reminders SET status = 'skipped' WHERE booking_id = %s AND status = 'pending'",
        (booking_id,)
    )
    conn.commit()
    conn.close()


def get_reminder_config(admin_id):
    """Return config for an admin, or sensible defaults."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM reminder_config WHERE admin_id = %s", (admin_id,)
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    return {
        "admin_id": admin_id,
        "reminder_48h_enabled": 1,
        "reminder_24h_enabled": 1,
        "reminder_2h_enabled": 1,
        "hours_before_first": 48,
        "hours_before_second": 24,
        "hours_before_third": 2,
        "quiet_hours_start": 23,
        "quiet_hours_end": 8,
        "high_risk_enabled": 1,
        "high_risk_threshold": 4,
        "recall_interval_days": 180,
        "recall_message": "",
        "recall_enabled": 1,
        "followup_day1": 1,
        "followup_day3": 1,
        "followup_day7": 1,
        "followup_day14": 0,
        "followup_day30": 0,
        "survey_delay_hours": 24,
        "survey_enabled": 1,
        "noshow_recovery_delay_hours": 2,
        "noshow_recovery_message": "",
        "noshow_recovery_enabled": 1,
        "birthday_enabled": 0,
        "birthday_days_before": 1,
        "reactivation_enabled": 0,
        "reactivation_days": 90,
        "welcome_enabled": 1,
        "welcome_delay_minutes": 0,
        "previsit_enabled": 1,
        "previsit_hours_before": 24,
    }


def save_reminder_config(admin_id, **kwargs):
    """Upsert reminder config for an admin."""
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM reminder_config WHERE admin_id = %s", (admin_id,)
    ).fetchone()
    if existing:
        sets = []
        vals = []
        for k, v in kwargs.items():
            sets.append(f"{_safe_column(k)} = %s")
            vals.append(v)
        if sets:
            vals.append(admin_id)
            conn.execute(
                f"UPDATE reminder_config SET {', '.join(sets)} WHERE admin_id = %s",
                tuple(vals)
            )
    else:
        cols = ["admin_id"] + [_safe_column(c) for c in kwargs.keys()]
        placeholders = ", ".join(["%s"] * len(cols))
        vals = [admin_id] + list(kwargs.values())
        conn.execute(
            f"INSERT INTO reminder_config ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(vals)
        )
    conn.commit()
    conn.close()


def get_todays_confirmation_stats(admin_id):
    """Return {total, confirmed, at_risk, pending} for today's bookings."""
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    # Get all active bookings for today
    bookings = conn.execute(
        "SELECT id FROM bookings WHERE admin_id = %s AND date = %s AND status != 'cancelled'",
        (admin_id, today)
    ).fetchall()
    booking_ids = [b["id"] for b in bookings]
    total = len(booking_ids)
    confirmed = 0
    at_risk = 0
    pending = 0
    for bid in booking_ids:
        reminder = conn.execute(
            "SELECT patient_response FROM appointment_reminders WHERE booking_id = %s AND patient_response = 'confirmed' LIMIT 1",
            (bid,)
        ).fetchone()
        if reminder:
            confirmed += 1
        else:
            # Check if any reminder was sent but no response
            sent = conn.execute(
                "SELECT id FROM appointment_reminders WHERE booking_id = %s AND status = 'sent' AND patient_response = 'none' LIMIT 1",
                (bid,)
            ).fetchone()
            if sent:
                at_risk += 1
            else:
                pending += 1
    conn.close()
    return {"total": total, "confirmed": confirmed, "at_risk": at_risk, "pending": pending}


def get_reminder_analytics(admin_id, date_from, date_to):
    """Return weekly reminder stats between date_from and date_to."""
    conn = get_db()
    rows = conn.execute(
        """SELECT
            TO_CHAR(scheduled_for, 'IYYY-"W"IW') as week,
            COUNT(*) as total_sent,
            SUM(CASE WHEN patient_response = 'confirmed' THEN 1 ELSE 0 END) as confirmed,
            SUM(CASE WHEN patient_response = 'cancelled' THEN 1 ELSE 0 END) as cancelled,
            SUM(CASE WHEN patient_response = 'none' AND status = 'sent' THEN 1 ELSE 0 END) as no_response
        FROM appointment_reminders
        WHERE admin_id = %s AND scheduled_for >= %s AND scheduled_for <= %s
        GROUP BY week ORDER BY week""",
        (admin_id, date_from, date_to)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_reminder_by_id(reminder_id):
    """Return a single reminder by id."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM appointment_reminders WHERE id = %s", (reminder_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ─── Survey DB Helpers ───────────────────────────────────────────────

def create_survey(admin_id, booking_id, patient_id, doctor_id, token, treatment_type=""):
    """Create a new survey record."""
    conn = get_db()
    _ins_cur = conn.execute(
        """INSERT INTO surveys (admin_id, booking_id, patient_id, doctor_id, token, treatment_type)
           VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
        (admin_id, booking_id, patient_id, doctor_id, token, treatment_type)
    )
    survey_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return survey_id


def get_survey_by_token(token):
    """Get a survey by its unique token."""
    conn = get_db()
    row = conn.execute("SELECT * FROM surveys WHERE token = %s", (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


def submit_survey_response(token, star_rating, feedback_text="", google_review_clicked=0):
    """Record a survey response."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """UPDATE surveys SET star_rating=%s, feedback_text=%s, completed_at=%s,
           google_review_clicked=%s WHERE token=%s""",
        (star_rating, feedback_text, now, google_review_clicked, token)
    )
    conn.commit()
    conn.close()


def get_survey_analytics_db(admin_id, date_from=None, date_to=None):
    """Get survey analytics data for an admin."""
    conn = get_db()
    params = [admin_id]
    date_filter = ""
    if date_from:
        date_filter += " AND completed_at >= %s"
        params.append(date_from)
    if date_to:
        date_filter += " AND completed_at <= %s"
        params.append(date_to)

    # Overall stats
    stats = conn.execute(
        f"""SELECT COUNT(*) as total_surveys,
            SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END) as completed,
            AVG(CASE WHEN star_rating IS NOT NULL THEN star_rating END) as avg_rating,
            SUM(CASE WHEN google_review_clicked = 1 THEN 1 ELSE 0 END) as google_clicks
        FROM surveys WHERE admin_id = %s {date_filter}""",
        params
    ).fetchone()
    stats = dict(stats) if stats else {}

    # Per-doctor averages
    doctor_stats = conn.execute(
        f"""SELECT doctor_id, AVG(star_rating) as avg_rating, COUNT(*) as total
        FROM surveys WHERE admin_id = %s AND star_rating IS NOT NULL {date_filter}
        GROUP BY doctor_id""",
        params
    ).fetchall()

    # Per-treatment averages
    treatment_stats = conn.execute(
        f"""SELECT treatment_type, AVG(star_rating) as avg_rating, COUNT(*) as total
        FROM surveys WHERE admin_id = %s AND star_rating IS NOT NULL AND treatment_type != '' {date_filter}
        GROUP BY treatment_type""",
        params
    ).fetchall()

    # Trend data (weekly)
    trend = conn.execute(
        f"""SELECT TO_CHAR(completed_at, 'IYYY-"W"IW') as week, AVG(star_rating) as avg_rating, COUNT(*) as total
        FROM surveys WHERE admin_id = %s AND completed_at IS NOT NULL {date_filter}
        GROUP BY week ORDER BY week""",
        params
    ).fetchall()

    conn.close()
    return {
        "stats": stats,
        "doctor_stats": [dict(r) for r in doctor_stats],
        "treatment_stats": [dict(r) for r in treatment_stats],
        "trend": [dict(r) for r in trend],
    }


def get_feedback_inbox_db(admin_id):
    """Get surveys with rating <= 3 (negative feedback)."""
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM surveys WHERE admin_id = %s AND star_rating IS NOT NULL AND star_rating <= 3
           ORDER BY completed_at DESC""",
        (admin_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_survey_config(admin_id):
    """Get survey configuration for an admin."""
    conn = get_db()
    row = conn.execute("SELECT * FROM survey_config WHERE admin_id = %s", (admin_id,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return {
        "admin_id": admin_id,
        "auto_send_enabled": 1,
        "send_delay_hours": 2,
        "google_review_url": "",
        "min_rating_for_review": 4,
    }


def save_survey_config(admin_id, auto_send_enabled=1, send_delay_hours=2, google_review_url="", min_rating_for_review=4):
    """Save or update survey configuration."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM survey_config WHERE admin_id = %s", (admin_id,)).fetchone()
    if existing:
        conn.execute(
            """UPDATE survey_config SET auto_send_enabled=%s, send_delay_hours=%s,
               google_review_url=%s, min_rating_for_review=%s WHERE admin_id=%s""",
            (auto_send_enabled, send_delay_hours, google_review_url, min_rating_for_review, admin_id)
        )
    else:
        conn.execute(
            """INSERT INTO survey_config (admin_id, auto_send_enabled, send_delay_hours, google_review_url, min_rating_for_review)
               VALUES (%s,%s,%s,%s,%s)""",
            (admin_id, auto_send_enabled, send_delay_hours, google_review_url, min_rating_for_review)
        )
    conn.commit()
    conn.close()


# ─── Package DB Helpers ──────────────────────────────────────────────

def create_package_db(admin_id, name, description, treatments_json, package_price, individual_total, savings, validity_days=90, max_redemptions=0):
    """Create a new treatment package."""
    conn = get_db()
    _ins_cur = conn.execute(
        """INSERT INTO treatment_packages
           (admin_id, name, description, treatments_json, package_price, individual_total, savings, validity_days, max_redemptions)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (admin_id, name, description, treatments_json, package_price, individual_total, savings, validity_days, max_redemptions)
    )
    pkg_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return pkg_id


def get_packages_db(admin_id, active_only=True):
    """Get all treatment packages for an admin."""
    conn = get_db()
    if active_only:
        rows = conn.execute(
            "SELECT * FROM treatment_packages WHERE admin_id = %s AND is_active = 1 ORDER BY created_at DESC",
            (admin_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM treatment_packages WHERE admin_id = %s ORDER BY created_at DESC",
            (admin_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_package_db(package_id, **kwargs):
    """Update a treatment package with given fields."""
    conn = get_db()
    allowed = ["name", "description", "treatments_json", "package_price", "individual_total",
               "savings", "validity_days", "max_redemptions", "is_active"]
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{_safe_column(k)} = %s")
            vals.append(v)
    if sets:
        vals.append(package_id)
        conn.execute(f"UPDATE treatment_packages SET {', '.join(sets)} WHERE id = %s", vals)
        conn.commit()
    conn.close()


def get_package_by_id(package_id):
    """Get a single package by id."""
    conn = get_db()
    row = conn.execute("SELECT * FROM treatment_packages WHERE id = %s", (package_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def redeem_package_db(package_id, patient_id, booking_id, treatment_name):
    """Record a package redemption."""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _ins_cur = conn.execute(
            "INSERT INTO package_redemptions (package_id, patient_id, booking_id, treatment_name, redeemed_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (package_id, patient_id, booking_id, treatment_name, now)
        )
        redemption_id = _ins_cur.fetchone()['id']
        conn.execute("UPDATE treatment_packages SET current_redemptions = current_redemptions + 1 WHERE id = %s", (package_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redemption_id


def get_package_analytics_db(admin_id):
    """Get analytics for all packages for an admin."""
    conn = get_db()
    packages = conn.execute(
        "SELECT * FROM treatment_packages WHERE admin_id = %s ORDER BY created_at DESC", (admin_id,)
    ).fetchall()
    result = []
    for p in packages:
        p = dict(p)
        redemptions = conn.execute(
            "SELECT COUNT(*) as total_redemptions FROM package_redemptions WHERE package_id = %s",
            (p["id"],)
        ).fetchone()
        redemptions = dict(redemptions) if redemptions else {"total_redemptions": 0}
        p["total_redemptions"] = redemptions["total_redemptions"]
        p["revenue"] = p["total_redemptions"] * (p.get("package_price") or 0)
        result.append(p)
    conn.close()
    return result


# ─── Upsell DB Helpers ───────────────────────────────────────────────

def create_upsell_rule(admin_id, trigger_treatment, suggested_treatment, message_template="",
                       suggested_package_id=None, discount_percent=0, priority=0):
    """Create a new upsell rule."""
    conn = get_db()
    _ins_cur = conn.execute(
        """INSERT INTO upsell_rules
           (admin_id, trigger_treatment, suggested_treatment, suggested_package_id, message_template, discount_percent, priority)
           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (admin_id, trigger_treatment, suggested_treatment, suggested_package_id, message_template, discount_percent, priority)
    )
    rule_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return rule_id


def get_upsell_rules(admin_id, trigger_treatment=None):
    """Get upsell rules, optionally filtered by trigger treatment."""
    conn = get_db()
    if trigger_treatment:
        rows = conn.execute(
            """SELECT * FROM upsell_rules WHERE admin_id = %s AND is_active = 1
               AND LOWER(trigger_treatment) = LOWER(%s) ORDER BY priority DESC""",
            (admin_id, trigger_treatment)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM upsell_rules WHERE admin_id = %s AND is_active = 1 ORDER BY priority DESC",
            (admin_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_upsell_impression(upsell_rule_id, session_id):
    """Record that an upsell was shown."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _ins_cur = conn.execute(
        "INSERT INTO upsell_impressions (upsell_rule_id, session_id, shown_at) VALUES (%s,%s,%s) RETURNING id",
        (upsell_rule_id, session_id, now)
    )
    impression_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return impression_id


def record_upsell_acceptance(impression_id, booking_id):
    """Record that an upsell was accepted."""
    conn = get_db()
    conn.execute(
        "UPDATE upsell_impressions SET accepted = 1, booking_id = %s WHERE id = %s",
        (booking_id, impression_id)
    )
    conn.commit()
    conn.close()


def get_upsell_impressions_for_session(session_id):
    """Get all upsell impressions for a session."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM upsell_impressions WHERE session_id = %s", (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_upsell_analytics_db(admin_id):
    """Get upsell analytics per rule."""
    conn = get_db()
    rules = conn.execute(
        "SELECT * FROM upsell_rules WHERE admin_id = %s", (admin_id,)
    ).fetchall()
    result = []
    for r in rules:
        r = dict(r)
        stats = conn.execute(
            """SELECT COUNT(*) as total_impressions,
                SUM(CASE WHEN accepted = 1 THEN 1 ELSE 0 END) as total_accepted
            FROM upsell_impressions WHERE upsell_rule_id = %s""",
            (r["id"],)
        ).fetchone()
        stats = dict(stats) if stats else {"total_impressions": 0, "total_accepted": 0}
        r["total_impressions"] = stats["total_impressions"]
        r["total_accepted"] = stats["total_accepted"]
        r["conversion_rate"] = round(stats["total_accepted"] / stats["total_impressions"] * 100, 1) if stats["total_impressions"] > 0 else 0
        result.append(r)
    conn.close()
    return result


# ─── No-Show Recovery DB Helpers ─────────────────────────────────────

def create_noshow_recovery(booking_id, patient_id, admin_id, reschedule_token, cancel_token, noshow_count=1):
    """Create a no-show recovery record and return its id."""
    conn = get_db()
    _ins_cur = conn.execute(
        """INSERT INTO noshow_recovery
           (booking_id, patient_id, admin_id, reschedule_token, cancel_token, noshow_count)
           VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
        (booking_id, patient_id, admin_id, reschedule_token, cancel_token, noshow_count)
    )
    recovery_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return recovery_id


def get_recovery_by_token(token, token_type="reschedule"):
    """Look up a recovery record by reschedule or cancel token."""
    if token_type not in ('reschedule', 'cancel'):
        return None
    conn = get_db()
    col = "reschedule_token" if token_type == "reschedule" else "cancel_token"
    row = conn.execute(f"SELECT * FROM noshow_recovery WHERE {col}=%s", (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_recovery_status(recovery_id, status, responded_at=None, new_booking_id=None):
    """Update recovery status and optional fields."""
    conn = get_db()
    if responded_at and new_booking_id:
        conn.execute(
            "UPDATE noshow_recovery SET recovery_status=%s, responded_at=%s, new_booking_id=%s WHERE id=%s",
            (status, responded_at, new_booking_id, recovery_id)
        )
    elif responded_at:
        conn.execute(
            "UPDATE noshow_recovery SET recovery_status=%s, responded_at=%s WHERE id=%s",
            (status, responded_at, recovery_id)
        )
    else:
        conn.execute(
            "UPDATE noshow_recovery SET recovery_status=%s WHERE id=%s",
            (status, recovery_id)
        )
    conn.commit()
    conn.close()


def get_noshow_policy(admin_id):
    """Get no-show policy for an admin. Returns dict or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM noshow_policy WHERE admin_id=%s", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_noshow_policy(admin_id, **kwargs):
    """Insert or update no-show policy for an admin."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM noshow_policy WHERE admin_id=%s", (admin_id,)).fetchone()
    allowed = ["max_noshows_before_deposit", "deposit_amount", "recovery_delay_minutes", "auto_recovery_enabled"]
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if existing:
        if fields:
            set_clause = ", ".join(f"{_safe_column(k)}=%s" for k in fields)
            values = list(fields.values()) + [admin_id]
            conn.execute(f"UPDATE noshow_policy SET {set_clause} WHERE admin_id=%s", values)
    else:
        cols = ["admin_id"] + [_safe_column(c) for c in fields.keys()]
        placeholders = ",".join(["%s"] * len(cols))
        values = [admin_id] + list(fields.values())
        conn.execute(f"INSERT INTO noshow_policy ({','.join(cols)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()


def get_recovery_stats(admin_id):
    """Return recovery rate, revenue recovered, and flagged patients for an admin."""
    conn = get_db()
    total = conn.execute(
        "SELECT COUNT(*) as c FROM noshow_recovery WHERE admin_id=%s", (admin_id,)
    ).fetchone()["c"]
    rescheduled = conn.execute(
        "SELECT COUNT(*) as c FROM noshow_recovery WHERE admin_id=%s AND recovery_status='rescheduled'",
        (admin_id,)
    ).fetchone()["c"]
    sent = conn.execute(
        "SELECT COUNT(*) as c FROM noshow_recovery WHERE admin_id=%s AND recovery_status IN ('sent','rescheduled','rescheduling','expired')",
        (admin_id,)
    ).fetchone()["c"]

    # Revenue recovered: sum of invoices linked to rescheduled bookings
    revenue = 0.0
    try:
        rev_row = conn.execute(
            """SELECT SUM(i.total) as rev FROM invoices i
               JOIN noshow_recovery nr ON i.booking_id = nr.new_booking_id
               WHERE nr.admin_id=%s AND nr.recovery_status='rescheduled' AND i.payment_status='paid'""",
            (admin_id,)
        ).fetchone()
        if rev_row and rev_row["rev"]:
            revenue = rev_row["rev"]
    except Exception:
        pass

    # Flagged patients: those at or above deposit threshold
    policy = get_noshow_policy(admin_id)
    threshold = policy.get("max_noshows_before_deposit", 2) if policy else 2
    flagged = conn.execute(
        "SELECT COUNT(*) as c FROM patients WHERE admin_id=%s AND total_no_shows >= %s",
        (admin_id, threshold)
    ).fetchone()["c"]

    conn.close()
    return {
        "total_recoveries": total,
        "rescheduled": rescheduled,
        "recovery_rate": round(rescheduled / sent * 100, 1) if sent > 0 else 0,
        "revenue_recovered": revenue,
        "flagged_patients": flagged,
    }


# ─── Invoice DB Helpers ─────────────────────────────────────────────

def create_invoice(admin_id, booking_id, patient_id, invoice_number, items_json,
                   subtotal, tax_rate, tax_amount, total, currency="SAR"):
    """Create an invoice record and return its id."""
    conn = get_db()
    _ins_cur = conn.execute(
        """INSERT INTO invoices
           (admin_id, booking_id, patient_id, invoice_number, items_json,
            subtotal, tax_rate, tax_amount, total, currency)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (admin_id, booking_id, patient_id, invoice_number, items_json,
         subtotal, tax_rate, tax_amount, total, currency)
    )
    invoice_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return invoice_id


def get_invoice_by_id(invoice_id):
    """Return a single invoice by id."""
    conn = get_db()
    row = conn.execute("SELECT * FROM invoices WHERE id=%s", (invoice_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_invoices_list(admin_id, date_from=None, date_to=None):
    """List invoices for an admin, optionally filtered by date range."""
    conn = get_db()
    try:
        if date_from and date_to:
            # created_at is TEXT in invoices table; use SUBSTR for safe date comparison
            rows = conn.execute(
                "SELECT * FROM invoices WHERE admin_id=%s AND created_at ~ %s AND SUBSTR(created_at, 1, 10) BETWEEN %s AND %s ORDER BY created_at DESC",
                (admin_id, r'^\d{4}-\d{2}-\d{2}', date_from, date_to)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM invoices WHERE admin_id=%s ORDER BY created_at DESC", (admin_id,)
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_invoice_config(admin_id):
    """Get invoice config for an admin. Returns dict or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM invoice_config WHERE admin_id=%s", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_invoice_config(admin_id, **kwargs):
    """Insert or update invoice config for an admin."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM invoice_config WHERE admin_id=%s", (admin_id,)).fetchone()
    allowed = ["business_name", "business_name_ar", "vat_number", "address", "address_ar",
               "logo_url", "next_invoice_number", "auto_generate"]
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if existing:
        if fields:
            set_clause = ", ".join(f"{_safe_column(k)}=%s" for k in fields)
            values = list(fields.values()) + [admin_id]
            conn.execute(f"UPDATE invoice_config SET {set_clause} WHERE admin_id=%s", values)
    else:
        cols = ["admin_id"] + [_safe_column(c) for c in fields.keys()]
        placeholders = ",".join(["%s"] * len(cols))
        values = [admin_id] + list(fields.values())
        conn.execute(f"INSERT INTO invoice_config ({','.join(cols)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()


# ─── Performance Report DB Helpers ──────────────────────────────────

def create_performance_report(admin_id, month, year, report_data_json, generated_at):
    """Create or replace a performance report and return its id."""
    conn = get_db()
    # Use INSERT OR REPLACE due to UNIQUE(admin_id, month, year)
    _ins_cur = conn.execute(
        """INSERT INTO performance_reports
           (admin_id, month, year, report_data_json, generated_at)
           VALUES (%s,%s,%s,%s,%s) RETURNING id""",
        (admin_id, month, year, report_data_json, generated_at)
    )
    report_id = _ins_cur.fetchone()['id']
    conn.commit()
    conn.close()
    return report_id


def get_performance_report(report_id):
    """Return a single performance report by id, with parsed JSON data."""
    conn = get_db()
    row = conn.execute("SELECT * FROM performance_reports WHERE id=%s", (report_id,)).fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    try:
        import json as _json
        result["report_data"] = _json.loads(result.get("report_data_json", "{}"))
    except (ValueError, TypeError):
        result["report_data"] = {}
    return result


def get_performance_reports(admin_id):
    """List all performance reports for an admin."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, admin_id, month, year, generated_at, emailed_at, created_at "
        "FROM performance_reports WHERE admin_id=%s ORDER BY year DESC, month DESC",
        (admin_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_report_config(admin_id):
    """Get report config for an admin. Returns dict or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM report_config WHERE admin_id=%s", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_report_config(admin_id, **kwargs):
    """Insert or update report config for an admin."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM report_config WHERE admin_id=%s", (admin_id,)).fetchone()
    allowed = ["auto_generate", "send_day_of_month", "recipients_json"]
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if existing:
        if fields:
            set_clause = ", ".join(f"{_safe_column(k)}=%s" for k in fields)
            values = list(fields.values()) + [admin_id]
            conn.execute(f"UPDATE report_config SET {set_clause} WHERE admin_id=%s", values)
    else:
        cols = ["admin_id"] + [_safe_column(c) for c in fields.keys()]
        placeholders = ",".join(["%s"] * len(cols))
        values = [admin_id] + list(fields.values())
        conn.execute(f"INSERT INTO report_config ({','.join(cols)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()


# ── Email Templates ──────────────────────────────────────────────────────────

def _ensure_email_templates_table():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS email_templates (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            name TEXT NOT NULL DEFAULT 'Custom Template',
            header_html TEXT DEFAULT '',
            body_html TEXT DEFAULT '',
            footer_html TEXT DEFAULT '',
            primary_color TEXT DEFAULT '#8b5cf6',
            secondary_color TEXT DEFAULT '#1a1a2e',
            bg_color TEXT DEFAULT '#f0f0f0',
            button_color TEXT DEFAULT '#8b5cf6',
            button_text_color TEXT DEFAULT '#ffffff',
            button_radius TEXT DEFAULT '8',
            button_size TEXT DEFAULT 'medium',
            header_image_url TEXT DEFAULT '',
            footer_image_url TEXT DEFAULT '',
            body_image_url TEXT DEFAULT '',
            logo_url TEXT DEFAULT '',
            font_family TEXT DEFAULT 'Helvetica Neue, Helvetica, Arial, sans-serif',
            content_width TEXT DEFAULT '600',
            card_radius TEXT DEFAULT '8',
            card_shadow TEXT DEFAULT '0 20px 60px rgba(0,0,0,0.1)',
            top_bar_height TEXT DEFAULT '4',
            line_height TEXT DEFAULT '1.6',
            letter_spacing TEXT DEFAULT '0',
            preheader TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            source_type TEXT DEFAULT 'manual',
            blocks_json TEXT DEFAULT '[]',
            compiled_html TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

_ensure_email_templates_table()

# Migration: add blocks_json and compiled_html columns if missing
try:
    _conn = get_db()
    _cols = [c[1] for c in _conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'email_templates'").fetchall()]
    if "blocks_json" not in _cols:
        _conn.execute("ALTER TABLE email_templates ADD COLUMN blocks_json TEXT DEFAULT '[]'")
    if "compiled_html" not in _cols:
        _conn.execute("ALTER TABLE email_templates ADD COLUMN compiled_html TEXT DEFAULT ''")
    for _col, _def in [("content_width","'600'"),("card_radius","'8'"),("card_shadow","'0 20px 60px rgba(0,0,0,0.1)'"),("top_bar_height","'4'"),("line_height","'1.6'"),("letter_spacing","'0'"),("preheader","''")]:
        if _col not in _cols:
            _conn.execute(f"ALTER TABLE email_templates ADD COLUMN {_col} TEXT DEFAULT {_def}")
    _conn.commit()
    _conn.close()
except Exception:
    pass

VALID_EMAIL_VARIABLES = {
    'patient_name', 'doctor_name', 'date', 'time', 'clinic_name',
    'confirm_link', 'cancel_link', 'service_name', 'booking_id',
    'waitlist_position', 'reschedule_link', 'survey_link',
    'invoice_link', 'recall_treatment', 'followup_date',
}

REQUIRED_VARIABLES_BY_TYPE = {
    'booking_confirmation': {'patient_name', 'date', 'time'},
    'waitlist_placed': {'patient_name', 'date', 'time'},
    'appointment_reminder': {'patient_name', 'date', 'time'},
    'noshow_recovery': {'patient_name'},
}


def validate_email_template_variables(html_text):
    """Extract and validate all {{variable}} placeholders. Returns (valid_vars, invalid_vars)."""
    import re
    found = set(re.findall(r'\{\{(\w+)\}\}', html_text))
    valid = found & VALID_EMAIL_VARIABLES
    invalid = found - VALID_EMAIL_VARIABLES
    return valid, invalid


def save_email_template(admin_id, **kwargs):
    """Save or update email template for an admin."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM email_templates WHERE admin_id=%s AND is_active=1", (admin_id,)).fetchone()
    allowed = [
        "name", "header_html", "body_html", "footer_html",
        "primary_color", "secondary_color", "bg_color",
        "button_color", "button_text_color", "button_radius", "button_size",
        "header_image_url", "footer_image_url", "body_image_url", "logo_url",
        "font_family", "content_width", "card_radius", "card_shadow",
        "top_bar_height", "line_height", "letter_spacing", "preheader",
        "is_active", "source_type", "blocks_json", "compiled_html"
    ]
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    fields["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if existing:
        set_clause = ", ".join(f"{_safe_column(k)}=%s" for k in fields)
        values = list(fields.values()) + [existing["id"]]
        conn.execute(f"UPDATE email_templates SET {set_clause} WHERE id=%s", values)
    else:
        # Clean up any inactive templates for this admin before inserting
        conn.execute("DELETE FROM email_templates WHERE admin_id=%s AND is_active=0", (admin_id,))
        fields["is_active"] = 1
        cols = ["admin_id"] + [_safe_column(c) for c in fields.keys()]
        placeholders = ",".join(["%s"] * len(cols))
        values = [admin_id] + list(fields.values())
        conn.execute(f"INSERT INTO email_templates ({','.join(cols)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()


def get_email_template(admin_id):
    """Get the email template for an admin, or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM email_templates WHERE admin_id=%s AND is_active=1", (admin_id,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def delete_email_template(admin_id):
    conn = get_db()
    conn.execute("DELETE FROM email_templates WHERE admin_id=%s", (admin_id,))
    conn.commit()
    conn.close()


def get_chatbot_customization(admin_id):
    """Get chatbot customization settings for an admin."""
    # Map DB columns to frontend field names
    db_to_frontend = {
        "dropdown_style": "dropdown_style",
        "msg_font_size": "font_size",
        "msg_bot_bg": "bot_msg_bg",
        "msg_bot_color": "bot_msg_text",
        "msg_user_bg": "user_msg_bg",
        "msg_user_color": "user_msg_text",
        "chatbot_bg_color": "chat_bg",
        "header_bg": "header_bg",
        "header_text_color": "header_text",
        "input_bg": "input_bg",
        "input_text_color": "input_text",
        "send_btn_color": "send_btn",
        "chatbot_title": "title",
        "msg_animation": "message_animation",
        "celebration_enabled": "confetti_enabled",
        "doctor_show_experience": "show_experience",
        "doctor_show_languages": "show_languages",
        "doctor_show_gender": "show_gender",
        "doctor_show_qualifications": "show_qualifications",
        "doctor_show_category": "show_specialty",
        "calendar_style": "calendar_style",
        "calendar_marker_color": "appt_marker",
        "launcher_bg": "launcher_bg",
        "launcher_icon": "launcher_icon",
    }
    defaults = {
        "dropdown_style": "default", "font_size": 13,
        "bot_msg_bg": "", "bot_msg_text": "", "user_msg_bg": "", "user_msg_text": "",
        "chat_bg": "", "header_bg": "", "header_text": "",
        "input_bg": "", "input_text": "", "send_btn": "",
        "title": "", "message_animation": "slide_up",
        "confetti_enabled": 0, "show_experience": 0, "show_languages": 0,
        "show_gender": 0, "show_qualifications": 0, "show_specialty": 1,
        "calendar_style": "default", "appt_marker": "#f87171",
        "launcher_bg": "", "launcher_icon": "chat",
    }
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM chatbot_customization WHERE admin_id=%s", (admin_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return defaults
    row = dict(row)
    result = {}
    for db_col, fe_key in db_to_frontend.items():
        result[fe_key] = row.get(db_col, defaults.get(fe_key, ""))
    return result


def save_chatbot_customization(admin_id, data):
    """Save chatbot customization settings (upsert)."""
    # Map frontend field names to database column names
    field_map = {
        "dropdown_style": "dropdown_style",
        "font_size": "msg_font_size", "msg_font_size": "msg_font_size",
        "bot_msg_bg": "msg_bot_bg", "msg_bot_bg": "msg_bot_bg",
        "bot_msg_text": "msg_bot_color", "msg_bot_color": "msg_bot_color",
        "user_msg_bg": "msg_user_bg", "msg_user_bg": "msg_user_bg",
        "user_msg_text": "msg_user_color", "msg_user_color": "msg_user_color",
        "chat_bg": "chatbot_bg_color", "chatbot_bg_color": "chatbot_bg_color",
        "header_bg": "header_bg",
        "header_text": "header_text_color", "header_text_color": "header_text_color",
        "input_bg": "input_bg",
        "input_text": "input_text_color", "input_text_color": "input_text_color",
        "send_btn": "send_btn_color", "send_btn_color": "send_btn_color",
        "title": "chatbot_title", "chatbot_title": "chatbot_title",
        "message_animation": "msg_animation", "msg_animation": "msg_animation",
        "confetti_enabled": "celebration_enabled", "celebration_enabled": "celebration_enabled",
        "show_experience": "doctor_show_experience", "doctor_show_experience": "doctor_show_experience",
        "show_specialty": "doctor_show_category", "doctor_show_category": "doctor_show_category",
        "show_gender": "doctor_show_gender", "doctor_show_gender": "doctor_show_gender",
        "show_languages": "doctor_show_languages", "doctor_show_languages": "doctor_show_languages",
        "show_qualifications": "doctor_show_qualifications", "doctor_show_qualifications": "doctor_show_qualifications",
        "calendar_style": "calendar_style",
        "appt_marker": "calendar_marker_color", "calendar_marker_color": "calendar_marker_color",
        "launcher_bg": "launcher_bg",
        "launcher_icon": "launcher_icon",
    }
    filtered = {}
    for k, v in data.items():
        col = field_map.get(k)
        if col:
            filtered[col] = v
    if not filtered:
        return
    conn = get_db()
    try:
        existing = conn.execute("SELECT id FROM chatbot_customization WHERE admin_id=%s", (admin_id,)).fetchone()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if existing:
            set_clause = ", ".join(f"{_safe_column(k)}=%s" for k in filtered)
            values = list(filtered.values()) + [now, admin_id]
            conn.execute(f"UPDATE chatbot_customization SET {set_clause}, updated_at=%s WHERE admin_id=%s", values)
        else:
            filtered["admin_id"] = admin_id
            filtered["updated_at"] = now
            cols = ", ".join(_safe_column(c) for c in filtered.keys())
            placeholders = ", ".join(["%s"] * len(filtered))
            conn.execute(f"INSERT INTO chatbot_customization ({cols}) VALUES ({placeholders})", list(filtered.values()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ═══════════════ Google Calendar Integration ═══════════════

def save_gcal_settings(admin_id, client_id, client_secret):
    """Save Google Calendar OAuth client settings for an admin."""
    conn = get_db()
    try:
        existing = conn.execute("SELECT id FROM gcal_settings WHERE admin_id=%s", (admin_id,)).fetchone()
        if existing:
            conn.execute("UPDATE gcal_settings SET gcal_client_id=%s, gcal_client_secret=%s WHERE admin_id=%s",
                          (client_id, client_secret, admin_id))
        else:
            conn.execute("INSERT INTO gcal_settings (admin_id, gcal_client_id, gcal_client_secret) VALUES (%s,%s,%s)",
                          (admin_id, client_id, client_secret))
        conn.commit()
    finally:
        conn.close()


def get_gcal_settings(admin_id, include_secret=False):
    """Get Google Calendar OAuth settings for an admin.
    By default excludes client_secret to prevent accidental exposure."""
    conn = get_db()
    row = conn.execute("SELECT * FROM gcal_settings WHERE admin_id=%s", (admin_id,)).fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    if not include_secret:
        result.pop("gcal_client_secret", None)
    return result


def get_doctor_gcal_status(doctor_id):
    """Check if a doctor has Google Calendar connected."""
    conn = get_db()
    row = conn.execute("SELECT gcal_refresh_token, gcal_calendar_id FROM doctors WHERE id=%s", (doctor_id,)).fetchone()
    conn.close()
    if not row:
        return {"connected": False}
    return {
        "connected": bool(row["gcal_refresh_token"]),
        "calendar_id": row["gcal_calendar_id"] or "primary",
    }


def get_doctors_with_gcal(admin_id):
    """Get all doctors for an admin with their Google Calendar status."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, email, gcal_refresh_token, gcal_calendar_id FROM doctors WHERE admin_id=%s",
        (admin_id,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["gcal_connected"] = bool(d.get("gcal_refresh_token"))
        d.pop("gcal_refresh_token", None)  # Don't expose token
        d.pop("gcal_calendar_id", None)  # Don't expose calendar ID (may reveal Google email)
        result.append(d)
    return result


# ── EMR/EHR Integration Functions ──────────────────────────────

def create_integration_request(admin_id, data):
    """Create a new integration request (for EMR/EHR systems)."""
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO integration_requests
               (admin_id, integration_name, contact_email, practice_size, current_system, notes)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (admin_id or 0,
             data.get("integration_name", ""),
             data.get("contact_email", ""),
             data.get("practice_size", ""),
             data.get("current_system", ""),
             data.get("notes", ""))
        )
        row = cur.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True, "id": row["id"]}


def get_integration_requests(admin_id):
    """Get all integration requests for an admin."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM integration_requests WHERE admin_id = %s ORDER BY created_at DESC",
        (admin_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_emr_integration(admin_id, integration_type):
    """Get EMR integration config for a given type."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM emr_integrations WHERE admin_id = %s AND integration_type = %s",
            (admin_id, integration_type)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    result = dict(row)
    result.pop("api_key_encrypted", None)  # Never expose encrypted key
    return result


def save_emr_integration(admin_id, data):
    """Save or update an EMR integration configuration.

    WARNING: The api_key is stored as plaintext in the `api_key_encrypted` column.
    This needs proper encryption (e.g., Fernet/AES with a managed key) before
    production use.  Requires key management infrastructure to implement safely.
    """
    conn = get_db()
    try:
        integration_type = data.get("integration_type", "")
        # TODO: Encrypt api_key_plaintext before storing in api_key_encrypted column.
        # Currently stored as plaintext — see docstring above.
        api_key_plaintext = data.get("api_key", "")
        existing = conn.execute(
            "SELECT id FROM emr_integrations WHERE admin_id = %s AND integration_type = %s",
            (admin_id, integration_type)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE emr_integrations
                   SET api_endpoint = %s, api_key_encrypted = %s, status = %s, sync_enabled = %s
                   WHERE admin_id = %s AND integration_type = %s""",
                (data.get("api_endpoint", ""),
                 api_key_plaintext,
                 data.get("status", "pending"),
                 data.get("sync_enabled", False),
                 admin_id, integration_type)
            )
        else:
            conn.execute(
                """INSERT INTO emr_integrations
                   (admin_id, integration_type, api_endpoint, api_key_encrypted, status, sync_enabled)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (admin_id, integration_type,
                 data.get("api_endpoint", ""),
                 api_key_plaintext,
                 data.get("status", "pending"),
                 data.get("sync_enabled", False))
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True}


def update_emr_sync_timestamp(admin_id, integration_type):
    """Update the last_sync timestamp for an EMR integration."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE emr_integrations SET last_sync = CURRENT_TIMESTAMP WHERE admin_id = %s AND integration_type = %s",
            (admin_id, integration_type)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True


# ── PMS Sync Logging ──

def log_pms_sync(admin_id, pms_type, booking_id, status, error_message=""):
    """Log a PMS sync attempt."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO pms_sync_log (admin_id, pms_type, booking_id, status, error_message) VALUES (%s, %s, %s, %s, %s)",
            (admin_id, pms_type, booking_id, status, error_message))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_pms_sync_logs(admin_id, limit=50):
    """Get recent PMS sync log entries for an admin."""
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM pms_sync_log WHERE admin_id = %s ORDER BY created_at DESC LIMIT %s",
            (admin_id, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_pms_sync_for_booking(admin_id, booking_id):
    """Get the most recent PMS sync entry for a specific booking."""
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM pms_sync_log WHERE admin_id = %s AND booking_id = %s ORDER BY created_at DESC LIMIT 1",
            (admin_id, booking_id)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


# ── AI Resolution Rate ──

def get_ai_resolution_rate(admin_id, date_from=None, date_to=None):
    """Calculate AI resolution rate metrics for a given admin and date range."""
    conn = get_db()
    try:
        date_filter = ""
        params = [admin_id]
        if date_from and date_to:
            date_filter = " AND created_at::date BETWEEN %s AND %s"
            params.extend([date_from, date_to])

        # Total conversations (distinct session_ids)
        total_row = conn.execute(
            "SELECT COUNT(DISTINCT session_id) as total FROM chat_logs WHERE admin_id=%s" + date_filter,
            tuple(params)
        ).fetchone()
        total = total_row["total"] if total_row else 0

        # AI-resolved = sessions where is_human_handled=0 AND session has 3+ messages
        ai_resolved_row = conn.execute(
            "SELECT COUNT(*) as c FROM ("
            "  SELECT session_id FROM chat_logs WHERE admin_id=%s AND is_human_handled=0" + date_filter +
            "  GROUP BY session_id HAVING COUNT(*) >= 3"
            ") sub",
            tuple(params)
        ).fetchone()
        ai_resolved = ai_resolved_row["c"] if ai_resolved_row else 0

        # Human-handled sessions
        human_row = conn.execute(
            "SELECT COUNT(DISTINCT session_id) as c FROM chat_logs WHERE admin_id=%s AND is_human_handled=1" + date_filter,
            tuple(params)
        ).fetchone()
        human_handled = human_row["c"] if human_row else 0

        # Resolution rate
        resolution_rate = round((ai_resolved / total * 100), 1) if total > 0 else 0

        # Avg messages per session
        avg_msg_row = conn.execute(
            "SELECT AVG(msg_count) as avg_msgs FROM ("
            "  SELECT session_id, COUNT(*) as msg_count FROM chat_logs WHERE admin_id=%s" + date_filter +
            "  GROUP BY session_id"
            ") sub",
            tuple(params)
        ).fetchone()
        avg_messages = round(float(avg_msg_row["avg_msgs"]), 1) if avg_msg_row and avg_msg_row["avg_msgs"] else 0

        # Avg response confidence
        conf_row = conn.execute(
            "SELECT AVG(intent_confidence) as avg_conf FROM chat_logs WHERE admin_id=%s AND intent_confidence > 0" + date_filter,
            tuple(params)
        ).fetchone()
        avg_confidence = round(float(conf_row["avg_conf"]) * 100, 1) if conf_row and conf_row["avg_conf"] else 0
    finally:
        conn.close()

    return {
        "total_conversations": total,
        "ai_resolved": ai_resolved,
        "human_handled": human_handled,
        "resolution_rate": resolution_rate,
        "avg_messages_per_session": avg_messages,
        "avg_confidence": avg_confidence,
    }


# ── Proactive Engagement Config ──

def get_proactive_config(admin_id):
    """Get proactive engagement config for an admin."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM proactive_config WHERE admin_id=%s", (admin_id,)).fetchone()
    finally:
        conn.close()
    if row:
        return dict(row)
    # Return defaults
    return {
        "admin_id": admin_id,
        "enabled": 1,
        "dwell_time_seconds": 30,
        "scroll_depth_percent": 60,
        "exit_intent_enabled": 1,
        "trigger_message": "",
        "trigger_pages": "",
    }


def save_proactive_config(admin_id, config):
    """Save proactive engagement config for an admin."""
    conn = get_db()
    try:
        enabled = int(config.get("enabled", 1))
        dwell = int(config.get("dwell_time_seconds", 30))
        scroll = int(config.get("scroll_depth_percent", 60))
        exit_intent = int(config.get("exit_intent_enabled", 1))
        trigger_msg = str(config.get("trigger_message", ""))
        trigger_pages = str(config.get("trigger_pages", ""))

        conn.execute(
            """INSERT INTO proactive_config (admin_id, enabled, dwell_time_seconds, scroll_depth_percent,
               exit_intent_enabled, trigger_message, trigger_pages)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (admin_id) DO UPDATE SET
               enabled=EXCLUDED.enabled, dwell_time_seconds=EXCLUDED.dwell_time_seconds,
               scroll_depth_percent=EXCLUDED.scroll_depth_percent,
               exit_intent_enabled=EXCLUDED.exit_intent_enabled,
               trigger_message=EXCLUDED.trigger_message, trigger_pages=EXCLUDED.trigger_pages,
               updated_at=CURRENT_TIMESTAMP""",
            (admin_id, enabled, dwell, scroll, exit_intent, trigger_msg, trigger_pages)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True


# ═══════════════ Chatbot Flow Builder ═══════════════

def save_chatbot_flow(admin_id, name, description, flow_data):
    """Save a new chatbot flow."""
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO chatbot_flows (admin_id, name, description, flow_data)
               VALUES (%s, %s, %s, %s) RETURNING id, name, description, is_active, created_at, updated_at""",
            (admin_id, name, description, json.dumps(flow_data))
        )
        row = cur.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return dict(row)


def get_chatbot_flows(admin_id):
    """List all flows for an admin."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, name, description, is_active, created_at, updated_at FROM chatbot_flows WHERE admin_id=%s ORDER BY updated_at DESC",
            (admin_id,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_chatbot_flow(admin_id, flow_id):
    """Get a single flow with full flow_data."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM chatbot_flows WHERE id=%s AND admin_id=%s",
            (flow_id, admin_id)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    result = dict(row)
    if isinstance(result.get("flow_data"), str):
        result["flow_data"] = json.loads(result["flow_data"])
    return result


def update_chatbot_flow(flow_id, admin_id, name, description, flow_data):
    """Update an existing flow."""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            """UPDATE chatbot_flows SET name=%s, description=%s, flow_data=%s, updated_at=%s
               WHERE id=%s AND admin_id=%s""",
            (name, description, json.dumps(flow_data), now, flow_id, admin_id)
        )
        conn.commit()
        affected = cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return affected > 0


def delete_chatbot_flow(flow_id, admin_id):
    """Delete a flow."""
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM chatbot_flows WHERE id=%s AND admin_id=%s", (flow_id, admin_id))
        conn.commit()
        affected = cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return affected > 0


def activate_chatbot_flow(flow_id, admin_id):
    """Set a flow as active and deactivate all others for this admin."""
    conn = get_db()
    try:
        conn.execute("UPDATE chatbot_flows SET is_active=FALSE WHERE admin_id=%s", (admin_id,))
        conn.execute("UPDATE chatbot_flows SET is_active=TRUE, updated_at=%s WHERE id=%s AND admin_id=%s",
                     (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), flow_id, admin_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True


def get_active_flow(admin_id):
    """Get the currently active flow for an admin."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM chatbot_flows WHERE admin_id=%s AND is_active=TRUE",
            (admin_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    result = dict(row)
    if isinstance(result.get("flow_data"), str):
        result["flow_data"] = json.loads(result["flow_data"])
    return result


# ── Multi-Industry Helpers ──

def get_company_type(admin_id):
    conn = get_db()
    row = conn.execute("SELECT company_type FROM users WHERE id=%s", (admin_id,)).fetchone()
    conn.close()
    return row["company_type"] if row else ""

def set_company_type(admin_id, company_type):
    if company_type not in ('dental', 'ecommerce', 'real_estate'):
        return False
    conn = get_db()
    conn.execute("UPDATE users SET company_type=%s WHERE id=%s", (company_type, admin_id))
    conn.commit()
    conn.close()
    return True


# ── Staff Permissions (ecommerce) ──

ECOM_PERMISSION_KEYS = [
    "products", "orders_view", "analytics", "store_settings",
    "integrations", "chatbot_customize", "leads", "customers",
    "promotions", "cart_recovery",
]

ECOM_DEFAULT_PERMISSIONS = {
    "products": True,
    "orders_view": True,
    "analytics": False,
    "store_settings": False,
    "integrations": False,
    "chatbot_customize": False,
    "leads": False,
    "customers": False,
    "promotions": False,
    "cart_recovery": False,
}


def seed_default_staff_permissions(admin_id, staff_user_id):
    conn = get_db()
    try:
        for key, default in ECOM_DEFAULT_PERMISSIONS.items():
            conn.execute(
                "INSERT INTO staff_permissions (admin_id, staff_user_id, permission_key, enabled) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (admin_id, staff_user_id, permission_key) DO NOTHING",
                (admin_id, staff_user_id, key, 1 if default else 0),
            )
        conn.commit()
    finally:
        conn.close()


def get_staff_permissions(admin_id, staff_user_id):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT permission_key, enabled FROM staff_permissions WHERE admin_id=%s AND staff_user_id=%s",
            (admin_id, staff_user_id),
        ).fetchall()
    finally:
        conn.close()
    perms = dict(ECOM_DEFAULT_PERMISSIONS)
    for r in rows:
        perms[r["permission_key"]] = bool(r["enabled"])
    return perms


def set_staff_permissions(admin_id, staff_user_id, permissions):
    conn = get_db()
    try:
        for key, enabled in permissions.items():
            if key not in ECOM_PERMISSION_KEYS:
                continue
            conn.execute(
                "INSERT INTO staff_permissions (admin_id, staff_user_id, permission_key, enabled) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (admin_id, staff_user_id, permission_key) "
                "DO UPDATE SET enabled=%s, updated_at=CURRENT_TIMESTAMP",
                (admin_id, staff_user_id, key, 1 if enabled else 0, 1 if enabled else 0),
            )
        conn.commit()
    finally:
        conn.close()


def get_all_staff_with_permissions(admin_id):
    conn = get_db()
    try:
        staff = conn.execute(
            "SELECT id, name, email, role, created_at FROM users WHERE admin_id=%s AND role='admin'",
            (admin_id,),
        ).fetchall()
        result = []
        for s in staff:
            rows = conn.execute(
                "SELECT permission_key, enabled FROM staff_permissions WHERE admin_id=%s AND staff_user_id=%s",
                (admin_id, s["id"]),
            ).fetchall()
            perms = dict(ECOM_DEFAULT_PERMISSIONS)
            for r in rows:
                perms[r["permission_key"]] = bool(r["enabled"])
            result.append({**dict(s), "permissions": perms})
    finally:
        conn.close()
    return result


# ── Store Settings CRUD ──

def get_store_settings(admin_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM store_settings WHERE admin_id=%s", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def save_store_settings(admin_id, **kwargs):
    conn = get_db()
    existing = conn.execute("SELECT id FROM store_settings WHERE admin_id=%s", (admin_id,)).fetchone()
    _allowed_cols = {
        "store_name", "store_logo", "brand_primary_color", "brand_secondary_color",
        "store_timezone", "store_currency", "currency_format", "default_language",
        "supported_languages", "store_contact_email", "store_contact_phone",
        "store_address", "business_hours", "chatbot_name", "chatbot_avatar",
        "chatbot_tone", "welcome_message", "offline_message",
        "store_url", "default_shipping_rate", "return_policy", "shipping_zones",
        "payment_methods", "tax_rate", "free_shipping_threshold",
        "ecommerce_type", "brand_voice", "bot_name", "target_audience",
        "cart_add_url",
        "bundle_enabled", "bundle_min_items", "bundle_discount_pct",
        "cart_integration_mode",
        "cart_integration_done",
    }
    fields = {k: v for k, v in kwargs.items() if k in _allowed_cols}
    if existing:
        if fields:
            set_clause = ", ".join(f"{k}=%s" for k in fields)
            values = list(fields.values()) + [admin_id]
            conn.execute(f"UPDATE store_settings SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE admin_id=%s", values)
    else:
        cols = ["admin_id"] + list(fields.keys())
        placeholders = ",".join(["%s"] * len(cols))
        values = [admin_id] + list(fields.values())
        conn.execute(f"INSERT INTO store_settings ({','.join(cols)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()


# ── Shipping Zones CRUD ──

def get_shipping_zones(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM shipping_zones WHERE admin_id=%s ORDER BY zone_name", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_shipping_zone(admin_id, zone_id=None, **kwargs):
    conn = get_db()
    _allowed = {"zone_name", "countries", "shipping_fee", "free_shipping_threshold", "estimated_days", "is_active"}
    fields = {k: v for k, v in kwargs.items() if k in _allowed}
    if zone_id:
        if fields:
            set_clause = ", ".join(f"{k}=%s" for k in fields)
            values = list(fields.values()) + [zone_id, admin_id]
            conn.execute(f"UPDATE shipping_zones SET {set_clause} WHERE id=%s AND admin_id=%s", values)
    else:
        cols = ["admin_id"] + list(fields.keys())
        placeholders = ",".join(["%s"] * len(cols))
        values = [admin_id] + list(fields.values())
        conn.execute(f"INSERT INTO shipping_zones ({','.join(cols)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()

def delete_shipping_zone(admin_id, zone_id):
    conn = get_db()
    conn.execute("DELETE FROM shipping_zones WHERE id=%s AND admin_id=%s", (zone_id, admin_id))
    conn.commit()
    conn.close()


# ── Store Discounts CRUD ──

def get_store_discounts(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM store_discounts WHERE admin_id=%s ORDER BY created_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_store_discount(admin_id, discount_id=None, **kwargs):
    conn = get_db()
    _allowed = {"discount_name", "discount_code", "discount_type", "discount_value",
                "applies_to", "product_ids", "category_names", "min_order_amount",
                "min_quantity", "start_date", "end_date", "max_uses", "is_active"}
    fields = {k: v for k, v in kwargs.items() if k in _allowed}
    if discount_id:
        if fields:
            set_clause = ", ".join(f"{k}=%s" for k in fields)
            values = list(fields.values()) + [discount_id, admin_id]
            conn.execute(f"UPDATE store_discounts SET {set_clause} WHERE id=%s AND admin_id=%s", values)
    else:
        cols = ["admin_id"] + list(fields.keys())
        placeholders = ",".join(["%s"] * len(cols))
        values = [admin_id] + list(fields.values())
        conn.execute(f"INSERT INTO store_discounts ({','.join(cols)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()

def delete_store_discount(admin_id, discount_id):
    conn = get_db()
    conn.execute("DELETE FROM store_discounts WHERE id=%s AND admin_id=%s", (discount_id, admin_id))
    conn.commit()
    conn.close()

def increment_discount_usage(discount_id):
    conn = get_db()
    conn.execute("UPDATE store_discounts SET current_uses = current_uses + 1 WHERE id=%s", (discount_id,))
    conn.commit()
    conn.close()


# ── Agency Settings CRUD ──

def get_agency_settings(admin_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM agency_settings WHERE admin_id=%s", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def save_agency_settings(admin_id, **kwargs):
    conn = get_db()
    existing = conn.execute("SELECT id FROM agency_settings WHERE admin_id=%s", (admin_id,)).fetchone()
    fields = {k: v for k, v in kwargs.items()}
    if existing:
        if fields:
            set_clause = ", ".join(f"{k}=%s" for k in fields)
            values = list(fields.values()) + [admin_id]
            conn.execute(f"UPDATE agency_settings SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE admin_id=%s", values)
    else:
        cols = ["admin_id"] + list(fields.keys())
        placeholders = ",".join(["%s"] * len(cols))
        values = [admin_id] + list(fields.values())
        conn.execute(f"INSERT INTO agency_settings ({','.join(cols)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()


# ── Products CRUD ──

def get_products(admin_id, status=None):
    conn = get_db()
    if status:
        rows = conn.execute("SELECT * FROM products WHERE admin_id=%s AND product_status=%s ORDER BY created_at DESC", (admin_id, status)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM products WHERE admin_id=%s ORDER BY created_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_product_by_id(product_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM products WHERE id=%s", (product_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

_PRODUCT_COLUMNS = {
    "product_id", "product_name", "product_description", "product_short_description",
    "product_images", "product_price", "compare_at_price", "cost_price",
    "product_status", "inventory_quantity", "inventory_policy", "low_stock_threshold",
    "backorder_status", "product_category", "product_subcategory", "product_tags",
    "product_weight", "product_dimensions", "product_material", "product_brand",
    "product_rating", "product_review_count", "product_barcode", "product_url",
    "product_highlights", "product_benefits", "target_customer",
    "product_specs", "use_cases", "sale_start_date", "sale_end_date",
    "related_complementary", "related_similar", "search_keywords",
    "ships_free", "shipping_class", "return_eligibility",
}

def create_product(admin_id, **kwargs):
    conn = get_db()
    try:
        fields = {k: v for k, v in kwargs.items() if k in _PRODUCT_COLUMNS}
        cols = ["admin_id"] + list(fields.keys())
        placeholders = ",".join(["%s"] * len(cols))
        values = [admin_id] + list(fields.values())
        cur = conn.execute(f"INSERT INTO products ({','.join(cols)}) VALUES ({placeholders}) RETURNING id", values)
        pid = cur.fetchone()["id"]
        # Auto-generate product_id if not provided
        if not fields.get("product_id"):
            auto_id = f"PROD-{pid}"
            conn.execute("UPDATE products SET product_id=%s WHERE id=%s", (auto_id, pid))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return pid

def update_product(product_id, **kwargs):
    conn = get_db()
    fields = {k: v for k, v in kwargs.items() if k in _PRODUCT_COLUMNS}
    if fields:
        set_clause = ", ".join(f"{k}=%s" for k in fields)
        values = list(fields.values()) + [product_id]
        conn.execute(f"UPDATE products SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=%s", values)
    conn.commit()
    conn.close()

def delete_product(product_id):
    conn = get_db()
    conn.execute("DELETE FROM product_variants WHERE product_id=%s", (product_id,))
    conn.execute("DELETE FROM products WHERE id=%s", (product_id,))
    conn.commit()
    conn.close()


# ── Product Variants CRUD ──

def get_product_variants(product_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM product_variants WHERE product_id=%s ORDER BY id", (product_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

_VARIANT_COLUMNS = {
    "variant_name", "option_1_name", "option_1_value", "option_2_name",
    "option_2_value", "option_3_name", "option_3_value", "variant_price",
    "variant_sku", "variant_inventory_qty", "variant_barcode", "variant_image",
    "inventory_quantity",
}

def create_variant(admin_id, product_id, **kwargs):
    conn = get_db()
    try:
        fields = {k: v for k, v in kwargs.items() if k in _VARIANT_COLUMNS}
        cols = ["admin_id", "product_id"] + list(fields.keys())
        placeholders = ",".join(["%s"] * len(cols))
        values = [admin_id, product_id] + list(fields.values())
        cur = conn.execute(f"INSERT INTO product_variants ({','.join(cols)}) VALUES ({placeholders}) RETURNING id", values)
        vid = cur.fetchone()["id"]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return vid

def delete_variant(variant_id):
    conn = get_db()
    conn.execute("DELETE FROM product_variants WHERE id=%s", (variant_id,))
    conn.commit()
    conn.close()


# ── Property Listings CRUD ──

def get_property_listings(admin_id, status=None):
    conn = get_db()
    if status:
        rows = conn.execute("SELECT * FROM property_listings WHERE admin_id=%s AND listing_status=%s ORDER BY created_at DESC", (admin_id, status)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM property_listings WHERE admin_id=%s ORDER BY created_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_listing_by_id(listing_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM property_listings WHERE id=%s", (listing_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

_LISTING_COLUMNS = {
    "listing_id", "listing_address", "listing_city", "listing_state", "listing_zip",
    "listing_price", "listing_status", "listing_type", "property_subtype",
    "bedrooms", "bathrooms", "full_baths", "half_baths", "square_footage",
    "lot_size", "year_built", "stories", "garage_spaces", "parking_total",
    "has_pool", "has_fireplace", "has_garage", "has_basement", "has_yard",
    "has_balcony_deck", "has_waterfront", "has_mountain_view", "pet_friendly",
    "fenced_yard", "updated_kitchen", "updated_bathrooms", "energy_efficient",
    "smart_home_features", "accessibility_features", "hoa_fee", "hoa_includes",
    "property_tax_annual", "tax_rate", "school_district", "elementary_school",
    "middle_school", "high_school", "walk_score", "transit_score", "bike_score",
    "nearby_amenities", "listing_photos", "virtual_tour_url", "floor_plan_image",
    "video_tour_url", "drone_video_url", "property_description", "short_description",
    "listing_agent_id", "listing_date", "days_on_market", "price_changes",
    "previous_sale_price",
}

def create_listing(admin_id, **kwargs):
    conn = get_db()
    try:
        fields = {k: v for k, v in kwargs.items() if k in _LISTING_COLUMNS}
        cols = ["admin_id"] + list(fields.keys())
        placeholders = ",".join(["%s"] * len(cols))
        values = [admin_id] + list(fields.values())
        cur = conn.execute(f"INSERT INTO property_listings ({','.join(cols)}) VALUES ({placeholders}) RETURNING id", values)
        lid = cur.fetchone()["id"]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return lid

def update_listing(listing_id, **kwargs):
    conn = get_db()
    try:
        fields = {k: v for k, v in kwargs.items() if k in _LISTING_COLUMNS}
        if fields:
            set_clause = ", ".join(f"{k}=%s" for k in fields)
            values = list(fields.values()) + [listing_id]
            conn.execute(f"UPDATE property_listings SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=%s", values)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def delete_listing(listing_id):
    conn = get_db()
    conn.execute("DELETE FROM property_listings WHERE id=%s", (listing_id,))
    conn.commit()
    conn.close()


# ── RE Agents CRUD ──

def get_re_agents(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM re_agents WHERE admin_id=%s ORDER BY first_name", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_re_agent_by_id(agent_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM re_agents WHERE id=%s", (agent_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def create_re_agent(admin_id, **kwargs):
    conn = get_db()
    fields = {k: v for k, v in kwargs.items()}
    cols = ["admin_id"] + list(fields.keys())
    placeholders = ",".join(["%s"] * len(cols))
    values = [admin_id] + list(fields.values())
    cur = conn.execute(f"INSERT INTO re_agents ({','.join(cols)}) VALUES ({placeholders}) RETURNING id", values)
    aid = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return aid

def update_re_agent(agent_id, **kwargs):
    conn = get_db()
    fields = {k: v for k, v in kwargs.items()}
    if fields:
        set_clause = ", ".join(f"{k}=%s" for k in fields)
        values = list(fields.values()) + [agent_id]
        conn.execute(f"UPDATE re_agents SET {set_clause} WHERE id=%s", values)
    conn.commit()
    conn.close()

def delete_re_agent(agent_id):
    conn = get_db()
    conn.execute("DELETE FROM re_agents WHERE id=%s", (agent_id,))
    conn.commit()
    conn.close()


# ── RE Leads CRUD ──

def get_re_leads(admin_id, status=None):
    conn = get_db()
    if status:
        rows = conn.execute("SELECT * FROM re_leads WHERE admin_id=%s AND lead_status=%s ORDER BY created_at DESC", (admin_id, status)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM re_leads WHERE admin_id=%s ORDER BY created_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_re_lead(admin_id, **kwargs):
    conn = get_db()
    fields = {k: v for k, v in kwargs.items()}
    cols = ["admin_id"] + list(fields.keys())
    placeholders = ",".join(["%s"] * len(cols))
    values = [admin_id] + list(fields.values())
    cur = conn.execute(f"INSERT INTO re_leads ({','.join(cols)}) VALUES ({placeholders}) RETURNING id", values)
    lid = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return lid

def update_re_lead(lead_id, **kwargs):
    conn = get_db()
    fields = {k: v for k, v in kwargs.items()}
    if fields:
        set_clause = ", ".join(f"{k}=%s" for k in fields)
        values = list(fields.values()) + [lead_id]
        conn.execute(f"UPDATE re_leads SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=%s", values)
    conn.commit()
    conn.close()


# ── Abandoned Carts CRUD ──

def get_abandoned_carts(admin_id, status=None):
    conn = get_db()
    if status:
        rows = conn.execute("SELECT * FROM abandoned_carts WHERE admin_id=%s AND recovery_status=%s ORDER BY abandoned_at DESC", (admin_id, status)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM abandoned_carts WHERE admin_id=%s ORDER BY abandoned_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

_ABANDONED_CART_COLUMNS = {
    "session_id", "customer_name", "customer_email", "customer_phone",
    "cart_items", "cart_total", "recovery_status", "recovery_messages_sent",
    "discount_code_sent", "recovered_at", "recovered_order_id", "last_followup_at"
}

def create_abandoned_cart(admin_id, **kwargs):
    conn = get_db()
    try:
        fields = {k: v for k, v in kwargs.items() if k in _ABANDONED_CART_COLUMNS}
        cols = ["admin_id"] + list(fields.keys())
        placeholders = ",".join(["%s"] * len(cols))
        values = [admin_id] + list(fields.values())
        cur = conn.execute(f"INSERT INTO abandoned_carts ({','.join(cols)}) VALUES ({placeholders}) RETURNING id", values)
        cid = cur.fetchone()["id"]
        conn.commit()
    finally:
        conn.close()
    return cid


# ── Predictive Replenishment & Zero-Party Data CRUD ──

def record_purchase(admin_id, customer_key, product_id, product_name, product_category="", quantity=1):
    conn = get_db()
    conn.execute(
        """INSERT INTO purchase_history (admin_id, customer_key, product_id, product_name, product_category, quantity)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (admin_id, customer_key, product_id, product_name, product_category, quantity)
    )
    conn.commit()
    conn.close()

def get_purchase_history(admin_id, customer_key):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM purchase_history WHERE admin_id=%s AND customer_key=%s ORDER BY purchased_at DESC",
        (admin_id, customer_key)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_replenishment_candidates(admin_id, customer_key):
    """Find products the customer bought before where the avg reorder interval has passed."""
    conn = get_db()
    rows = conn.execute(
        """SELECT product_id, product_name, product_category,
                  array_agg(purchased_at ORDER BY purchased_at) as purchase_dates,
                  COUNT(*) as purchase_count
           FROM purchase_history
           WHERE admin_id=%s AND customer_key=%s
           GROUP BY product_id, product_name, product_category
           HAVING COUNT(*) >= 2""",
        (admin_id, customer_key)
    ).fetchall()
    conn.close()

    from datetime import datetime, timedelta
    now = datetime.now()
    candidates = []
    for r in rows:
        row = dict(r)
        dates = row["purchase_dates"]
        if not dates or len(dates) < 2:
            continue
        # Calculate avg days between orders
        sorted_dates = sorted(dates)
        gaps = []
        for i in range(1, len(sorted_dates)):
            gap = (sorted_dates[i] - sorted_dates[i - 1]).total_seconds() / 86400
            if gap > 0:
                gaps.append(gap)
        if not gaps:
            continue
        avg_days = sum(gaps) / len(gaps)
        last_purchase = sorted_dates[-1]
        days_since = (now - last_purchase).total_seconds() / 86400
        # If current date > last purchase + avg_days * 0.9 then it's a candidate
        if days_since >= avg_days * 0.9:
            candidates.append({
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "product_category": row["product_category"],
                "avg_days": avg_days,
                "days_since": round(days_since, 1),
                "purchase_count": row["purchase_count"],
                "last_purchase": str(last_purchase),
            })
    return candidates

def save_replenishment_prediction(admin_id, customer_key, product_id, product_name, predicted_date, avg_days, confidence=0.5):
    conn = get_db()
    conn.execute(
        """INSERT INTO replenishment_predictions
           (admin_id, customer_key, product_id, product_name, predicted_reorder_date, avg_days_between_orders, confidence)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (admin_id, customer_key, product_id, product_name, predicted_date, avg_days, confidence)
    )
    conn.commit()
    conn.close()

def mark_replenishment_notified(prediction_id):
    conn = get_db()
    conn.execute(
        "UPDATE replenishment_predictions SET notified=TRUE, notified_at=CURRENT_TIMESTAMP WHERE id=%s",
        (prediction_id,)
    )
    conn.commit()
    conn.close()

def save_customer_preference(admin_id, customer_key, preference_type, preference_key, preference_value, source="chat"):
    conn = get_db()
    conn.execute(
        """INSERT INTO customer_preferences (admin_id, customer_key, preference_type, preference_key, preference_value, source)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (admin_id, customer_key, preference_type, preference_key)
           DO UPDATE SET preference_value=%s, source=%s, collected_at=CURRENT_TIMESTAMP""",
        (admin_id, customer_key, preference_type, preference_key, preference_value, source,
         preference_value, source)
    )
    conn.commit()
    conn.close()

def get_customer_preferences(admin_id, customer_key):
    """Returns dict grouped by preference_type."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM customer_preferences WHERE admin_id=%s AND customer_key=%s ORDER BY preference_type, collected_at DESC",
        (admin_id, customer_key)
    ).fetchall()
    conn.close()
    grouped = {}
    for r in rows:
        row = dict(r)
        ptype = row["preference_type"]
        if ptype not in grouped:
            grouped[ptype] = []
        grouped[ptype].append({
            "key": row["preference_key"],
            "value": row["preference_value"],
            "source": row["source"],
            "collected_at": str(row["collected_at"]),
        })
    return grouped

def get_all_preference_insights(admin_id):
    """Aggregated preference data for merchandising decisions."""
    conn = get_db()
    rows = conn.execute(
        """SELECT preference_type, preference_key, preference_value, COUNT(*) as cnt
           FROM customer_preferences
           WHERE admin_id=%s
           GROUP BY preference_type, preference_key, preference_value
           ORDER BY preference_type, cnt DESC""",
        (admin_id,)
    ).fetchall()
    total_customers_row = conn.execute(
        "SELECT COUNT(DISTINCT customer_key) as total FROM customer_preferences WHERE admin_id=%s",
        (admin_id,)
    ).fetchone()
    conn.close()

    total_customers = total_customers_row["total"] if total_customers_row else 0
    insights = {}
    for r in rows:
        row = dict(r)
        ptype = row["preference_type"]
        if ptype not in insights:
            insights[ptype] = []
        pct = round(row["cnt"] / total_customers * 100, 1) if total_customers > 0 else 0
        insights[ptype].append({
            "key": row["preference_key"],
            "value": row["preference_value"],
            "count": row["cnt"],
            "percentage": pct,
        })
    return {"total_customers": total_customers, "insights": insights}


# ── Qualification Flows CRUD ──

def get_qualification_flows(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM qualification_flows WHERE admin_id=%s ORDER BY created_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_qualification_questions(flow_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM qualification_questions WHERE flow_id=%s ORDER BY question_order", (flow_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Cart Recovery Settings CRUD ──

def get_cart_recovery_settings(admin_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM cart_recovery_settings WHERE admin_id=%s", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

_CART_RECOVERY_SETTINGS_COLUMNS = {
    "cart_recovery_enabled", "exit_intent_trigger", "exit_intent_delay",
    "scroll_up_trigger", "time_on_page_trigger", "cart_value_minimum", "cart_value_maximum",
    "mobile_swipe_up_trigger", "tab_switch_trigger",
    "recovery_message_1", "recovery_message_1_delay",
    "recovery_message_2", "recovery_message_2_delay",
    "recovery_message_3", "recovery_message_3_delay",
    "discount_enabled", "discount_type", "discount_value",
    "discount_minimum_cart_value", "discount_maximum_cap",
    "discount_code_prefix", "single_use_codes",
    "urgency_timer_enabled", "urgency_timer_duration",
    "email_followup_enabled", "email_1_timing", "email_1_template",
    "email_2_timing", "email_2_template", "email_3_timing", "email_3_template",
    "sms_followup_enabled", "sms_timing", "sms_template",
    "whatsapp_enabled", "whatsapp_timing", "whatsapp_template"
}

def save_cart_recovery_settings(admin_id, **kwargs):
    conn = get_db()
    try:
        existing = conn.execute("SELECT id FROM cart_recovery_settings WHERE admin_id=%s", (admin_id,)).fetchone()
        fields = {k: v for k, v in kwargs.items() if k in _CART_RECOVERY_SETTINGS_COLUMNS}
        if existing:
            if fields:
                set_clause = ", ".join(f"{k}=%s" for k in fields)
                values = list(fields.values()) + [admin_id]
                conn.execute(f"UPDATE cart_recovery_settings SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE admin_id=%s", values)
        else:
            cols = ["admin_id"] + list(fields.keys())
            placeholders = ",".join(["%s"] * len(cols))
            values = [admin_id] + list(fields.values())
            conn.execute(f"INSERT INTO cart_recovery_settings ({','.join(cols)}) VALUES ({placeholders})", values)
        conn.commit()
    finally:
        conn.close()


# ── RE Showings CRUD ──

def get_re_showings(admin_id, status=None):
    conn = get_db()
    if status:
        rows = conn.execute("SELECT s.*, l.listing_address, l.listing_price FROM re_showings s LEFT JOIN property_listings l ON s.listing_id=l.id WHERE s.admin_id=%s AND s.showing_status=%s ORDER BY s.showing_date, s.showing_time", (admin_id, status)).fetchall()
    else:
        rows = conn.execute("SELECT s.*, l.listing_address, l.listing_price FROM re_showings s LEFT JOIN property_listings l ON s.listing_id=l.id WHERE s.admin_id=%s ORDER BY s.showing_date DESC, s.showing_time", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_re_showing(admin_id, **kwargs):
    conn = get_db()
    fields = {k: v for k, v in kwargs.items()}
    cols = ["admin_id"] + list(fields.keys())
    placeholders = ",".join(["%s"] * len(cols))
    values = [admin_id] + list(fields.values())
    cur = conn.execute(f"INSERT INTO re_showings ({','.join(cols)}) VALUES ({placeholders}) RETURNING id", values)
    sid = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return sid


# ── E-commerce Orders CRUD ──

def get_ecom_order(admin_id, order_number):
    conn = get_db()
    row = conn.execute("SELECT * FROM ecom_orders WHERE admin_id=%s AND UPPER(order_number)=UPPER(%s)", (admin_id, order_number)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_ecom_orders(admin_id, status=None):
    conn = get_db()
    if status:
        rows = conn.execute("SELECT * FROM ecom_orders WHERE admin_id=%s AND order_status=%s ORDER BY created_at DESC", (admin_id, status)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM ecom_orders WHERE admin_id=%s ORDER BY created_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

_ECOM_ORDER_COLUMNS = {
    "order_number", "customer_name", "customer_email", "customer_phone",
    "order_status", "order_total", "subtotal", "tax_amount", "shipping_cost",
    "discount_amount", "discount_code", "items_json", "shipping_address",
    "shipping_method", "tracking_number", "carrier", "estimated_delivery",
    "payment_method", "payment_status", "notes",
}

def create_ecom_order(admin_id, **kwargs):
    conn = get_db()
    try:
        fields = {k: v for k, v in kwargs.items() if k in _ECOM_ORDER_COLUMNS}
        cols = ["admin_id"] + list(fields.keys())
        placeholders = ",".join(["%s"] * len(cols))
        values = [admin_id] + list(fields.values())
        cur = conn.execute(f"INSERT INTO ecom_orders ({','.join(cols)}) VALUES ({placeholders}) RETURNING id", values)
        oid = cur.fetchone()["id"]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return oid

def update_ecom_order(order_id, admin_id=None, **kwargs):
    conn = get_db()
    try:
        fields = {k: v for k, v in kwargs.items() if k in _ECOM_ORDER_COLUMNS}
        if fields:
            set_clause = ", ".join(f"{k}=%s" for k in fields)
            if admin_id:
                values = list(fields.values()) + [order_id, admin_id]
                conn.execute(f"UPDATE ecom_orders SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=%s AND admin_id=%s", values)
            else:
                values = list(fields.values()) + [order_id]
                conn.execute(f"UPDATE ecom_orders SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=%s", values)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── E-commerce Customer CRUD ──

def upsert_ecom_customer(admin_id, email, name="", phone="", order_total=0):
    """Create or update a customer record. Increments order count and totals on each call."""
    if not email:
        return None
    email = email.strip().lower()
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id, total_orders, total_spent FROM ecom_customers WHERE admin_id=%s AND LOWER(customer_email)=%s",
            (admin_id, email)
        ).fetchone()
        if existing:
            new_orders = (existing["total_orders"] or 0) + 1
            new_spent = float(existing["total_spent"] or 0) + float(order_total or 0)
            new_aov = new_spent / new_orders if new_orders > 0 else 0
            updates = {
                "total_orders": new_orders,
                "total_spent": round(new_spent, 2),
                "avg_order_value": round(new_aov, 2),
                "last_purchase_at": "CURRENT_TIMESTAMP",
            }
            if name:
                updates["customer_name"] = name
            if phone:
                updates["customer_phone"] = phone
            # Build SET clause — handle CURRENT_TIMESTAMP specially
            parts = []
            vals = []
            for k, v in updates.items():
                if v == "CURRENT_TIMESTAMP":
                    parts.append(f"{k}=CURRENT_TIMESTAMP")
                else:
                    parts.append(f"{k}=%s")
                    vals.append(v)
            vals.append(existing["id"])
            conn.execute(f"UPDATE ecom_customers SET {', '.join(parts)} WHERE id=%s", vals)
            conn.commit()
            return existing["id"]
        else:
            aov = round(float(order_total or 0), 2)
            cur = conn.execute(
                """INSERT INTO ecom_customers
                   (admin_id, customer_email, customer_name, customer_phone,
                    total_orders, total_spent, avg_order_value, first_purchase_at, last_purchase_at)
                   VALUES (%s, %s, %s, %s, 1, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                   RETURNING id""",
                (admin_id, email, name or "", phone or "", aov, aov)
            )
            cid = cur.fetchone()["id"]
            conn.commit()
            return cid
    finally:
        conn.close()


def get_ecom_customer_by_email(admin_id, email):
    if not email:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM ecom_customers WHERE admin_id=%s AND LOWER(customer_email)=LOWER(%s)",
            (admin_id, email.strip().lower())
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_ecom_orders_by_customer(admin_id, email):
    """Get all orders for a customer by email, newest first."""
    if not email:
        return []
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM ecom_orders WHERE admin_id=%s AND LOWER(customer_email)=LOWER(%s) ORDER BY created_at DESC",
            (admin_id, email.strip().lower())
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_ecom_order_by_id(order_id, admin_id=None):
    conn = get_db()
    try:
        if admin_id:
            row = conn.execute("SELECT * FROM ecom_orders WHERE id=%s AND admin_id=%s", (order_id, admin_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM ecom_orders WHERE id=%s", (order_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_delivered_orders_for_review(admin_id, customer_email):
    """Get orders delivered 5+ days ago that haven't been reviewed yet."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT o.* FROM ecom_orders o
               WHERE o.admin_id=%s AND LOWER(o.customer_email)=LOWER(%s)
               AND o.order_status='delivered'
               AND o.updated_at <= CURRENT_TIMESTAMP - INTERVAL '5 days'
               AND NOT EXISTS (
                   SELECT 1 FROM review_prompts rp
                   WHERE rp.order_id=o.id AND rp.review_submitted=TRUE
               )
               ORDER BY o.updated_at DESC LIMIT 3""",
            (admin_id, customer_email.strip().lower())
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def has_review_prompt_been_sent(admin_id, order_id):
    """Check if a review prompt was already sent for this order."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM review_prompts WHERE admin_id=%s AND order_id=%s",
            (admin_id, order_id)
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def record_review_prompt(admin_id, order_id, customer_email):
    """Record that a review prompt was sent for an order."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO review_prompts (admin_id, order_id, customer_email) VALUES (%s, %s, %s)",
            (admin_id, order_id, customer_email)
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def submit_product_review(admin_id, order_id, order_number, product_name, customer_email,
                          customer_name, rating, review_text="", incentive_code="", product_id=0):
    """Submit a product review from the chatbot."""
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO product_reviews
               (admin_id, order_id, order_number, product_id, product_name, customer_email,
                customer_name, rating, review_text, status, review_source, incentive_code)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'published', 'chatbot', %s)""",
            (admin_id, order_id, order_number, product_id, product_name,
             customer_email, customer_name, rating, review_text, incentive_code)
        )
        # Mark review as submitted in prompts table
        conn.execute(
            "UPDATE review_prompts SET review_submitted=TRUE WHERE admin_id=%s AND order_id=%s",
            (admin_id, order_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True}


def get_product_reviews(admin_id, product_id=None, limit=20):
    """Get product reviews, optionally filtered by product."""
    conn = get_db()
    try:
        if product_id:
            rows = conn.execute(
                "SELECT * FROM product_reviews WHERE admin_id=%s AND product_id=%s AND status='published' ORDER BY created_at DESC LIMIT %s",
                (admin_id, product_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM product_reviews WHERE admin_id=%s AND status='published' ORDER BY created_at DESC LIMIT %s",
                (admin_id, limit)
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_product_review_stats(admin_id, product_id=None):
    """Get review statistics for a product or all products."""
    conn = get_db()
    try:
        where = "WHERE admin_id=%s AND status='published'"
        params = [admin_id]
        if product_id:
            where += " AND product_id=%s"
            params.append(product_id)
        row = conn.execute(
            f"SELECT COUNT(*) as total, COALESCE(AVG(rating),0) as avg_rating FROM product_reviews {where}",
            params
        ).fetchone()
    finally:
        conn.close()
    return {"total": row["total"], "avg_rating": round(float(row["avg_rating"]), 1)}


# ── Stripe Integration Helpers ──

def save_stripe_keys(admin_id, publishable_key, secret_key, webhook_secret=""):
    """Store or update Stripe API keys in ecom_integrations table.
    Uses dedicated payment_ columns to avoid overwriting Shopify/WooCommerce credentials."""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM ecom_integrations WHERE admin_id=%s", (admin_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE ecom_integrations
                   SET payment_gateway='stripe', payment_api_key=%s,
                       payment_publishable_key=%s, payment_webhook_secret=%s
                   WHERE admin_id=%s""",
                (secret_key, publishable_key, webhook_secret, admin_id)
            )
        else:
            conn.execute(
                """INSERT INTO ecom_integrations
                   (admin_id, payment_gateway, payment_api_key, payment_publishable_key, payment_webhook_secret)
                   VALUES (%s, 'stripe', %s, %s, %s)""",
                (admin_id, secret_key, publishable_key, webhook_secret)
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True}


def get_stripe_keys(admin_id):
    """Retrieve Stripe API keys for an admin. Returns dict or None."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT payment_api_key, payment_publishable_key, payment_webhook_secret FROM ecom_integrations WHERE admin_id=%s AND payment_gateway='stripe'",
            (admin_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "publishable_key": row.get("payment_publishable_key", "") or "",
        "secret_key": row["payment_api_key"] or "",
        "webhook_secret": row.get("payment_webhook_secret", "") or "",
    }


# ── Ecom Integration CRUD (Shopify / WooCommerce / Generic) ──

def save_ecom_integration(admin_id, platform, **kwargs):
    """Upsert ecom integration config for a given platform.
    Only updates columns relevant to the specified platform to avoid overwriting
    other platforms' credentials."""
    conn = get_db()
    try:
        field_map = {
            "store_url": "platform_store_url",
            "api_key": "platform_api_key",
            "api_secret": "platform_api_secret",
            "api_token": "platform_api_key",
            "consumer_key": "platform_api_key",
            "consumer_secret": "platform_api_secret",
            "webhook_url": "webhook_url",
            "storefront_url": "storefront_url",
        }

        mapped = {"ecommerce_platform": platform}
        for k, v in kwargs.items():
            col = field_map.get(k)
            if col:
                mapped[col] = v

        cols = list(mapped.keys())
        vals = list(mapped.values())
        set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols)
        placeholders = ", ".join(["%s"] * (len(vals) + 1))
        all_cols = ["admin_id"] + cols

        conn.execute(
            f"""INSERT INTO ecom_integrations ({', '.join(all_cols)}) VALUES ({placeholders})
                ON CONFLICT (admin_id) DO UPDATE SET {set_clause}""",
            [admin_id] + vals
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True}


def get_ecom_integration(admin_id):
    """Get ecom integration config for an admin."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM ecom_integrations WHERE admin_id=%s", (admin_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def create_stripe_checkout(admin_id, session_id, stripe_session_id="", customer_email="",
                           cart_items="", cart_total=0, currency="usd", checkout_url=""):
    """Create a Stripe checkout session record."""
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO stripe_checkout_sessions
               (admin_id, session_id, stripe_session_id, customer_email, cart_items, cart_total, currency, checkout_url)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (admin_id, session_id, stripe_session_id, customer_email, cart_items, cart_total, currency, checkout_url)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True}


def get_stripe_checkout(stripe_session_id):
    """Retrieve a Stripe checkout session record by its Stripe session ID."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM stripe_checkout_sessions WHERE stripe_session_id=%s",
            (stripe_session_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def update_stripe_checkout_status(stripe_session_id, status, payment_intent=""):
    """Update the status of a Stripe checkout session."""
    conn = get_db()
    try:
        if status == "completed":
            conn.execute(
                "UPDATE stripe_checkout_sessions SET status=%s, stripe_payment_intent=%s, completed_at=CURRENT_TIMESTAMP WHERE stripe_session_id=%s",
                (status, payment_intent, stripe_session_id)
            )
        else:
            conn.execute(
                "UPDATE stripe_checkout_sessions SET status=%s WHERE stripe_session_id=%s",
                (status, stripe_session_id)
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True}


def update_stripe_checkout_failure(stripe_session_id, failure_reason="", failure_code=""):
    """Record a payment failure on a stripe checkout session."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE stripe_checkout_sessions SET status='failed', failure_reason=%s, failure_code=%s WHERE stripe_session_id=%s",
            (failure_reason, failure_code, stripe_session_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True}


def get_stripe_checkout_by_session(session_id):
    """Get the most recent stripe checkout for a chatbot session_id."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM stripe_checkout_sessions WHERE session_id=%s ORDER BY created_at DESC LIMIT 1",
            (session_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


# ── Conversation Quality CRUD ──

def save_conversation_quality(admin_id, session_id, quality_score, metrics, escalated=False, converted=False):
    """Save conversation quality score and metrics."""
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO conversation_quality
               (admin_id, session_id, quality_score, engagement_score, avg_frustration,
                frustration_trend, resolution_score, max_buying_intent, total_messages,
                escalated, converted)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (admin_id, session_id, quality_score,
             metrics.get("engagement_score", 0),
             metrics.get("avg_frustration", 0),
             metrics.get("frustration_trend", "stable"),
             metrics.get("resolution_score", 0),
             metrics.get("max_buying_intent", 0),
             metrics.get("total_messages", 0),
             escalated, converted)
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def get_conversation_quality_stats(admin_id, days=30):
    """Returns avg quality score, total conversations, escalation rate, conversion rate, avg frustration."""
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT
                COUNT(*) as total_conversations,
                COALESCE(AVG(quality_score), 0) as avg_quality_score,
                COALESCE(AVG(avg_frustration), 0) as avg_frustration,
                COALESCE(SUM(CASE WHEN escalated THEN 1 ELSE 0 END), 0) as escalated_count,
                COALESCE(SUM(CASE WHEN converted THEN 1 ELSE 0 END), 0) as converted_count,
                COALESCE(AVG(engagement_score), 0) as avg_engagement,
                COALESCE(AVG(resolution_score), 0) as avg_resolution,
                COALESCE(AVG(max_buying_intent), 0) as avg_buying_intent,
                COALESCE(AVG(total_messages), 0) as avg_messages
            FROM conversation_quality
            WHERE admin_id=%s AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'""",
            (admin_id, days)
        ).fetchone()
    finally:
        conn.close()
    if not row or row["total_conversations"] == 0:
        return {
            "total_conversations": 0,
            "avg_quality_score": 0,
            "avg_frustration": 0,
            "escalation_rate": 0,
            "conversion_rate": 0,
            "avg_engagement": 0,
            "avg_resolution": 0,
            "avg_buying_intent": 0,
            "avg_messages": 0,
        }
    total = row["total_conversations"]
    return {
        "total_conversations": total,
        "avg_quality_score": round(float(row["avg_quality_score"]), 1),
        "avg_frustration": round(float(row["avg_frustration"]), 1),
        "escalation_rate": round(float(row["escalated_count"]) / total * 100, 1),
        "conversion_rate": round(float(row["converted_count"]) / total * 100, 1),
        "avg_engagement": round(float(row["avg_engagement"]), 1),
        "avg_resolution": round(float(row["avg_resolution"]), 1),
        "avg_buying_intent": round(float(row["avg_buying_intent"]), 1),
        "avg_messages": round(float(row["avg_messages"]), 1),
    }


def get_conversation_quality_list(admin_id, days=30, limit=50):
    """Returns recent conversation quality records for analytics."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT * FROM conversation_quality
            WHERE admin_id=%s AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
            ORDER BY created_at DESC LIMIT %s""",
            (admin_id, days, limit)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_knowledge_base(admin_id, category=None):
    """Get all knowledge base entries for an admin."""
    conn = get_db()
    try:
        if category:
            rows = conn.execute(
                "SELECT * FROM ai_knowledge_base WHERE admin_id=%s AND is_active=TRUE AND category=%s ORDER BY created_at DESC",
                (admin_id, category)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ai_knowledge_base WHERE admin_id=%s AND is_active=TRUE ORDER BY created_at DESC",
                (admin_id,)
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def add_knowledge_entry(admin_id, question, answer, category="general", keywords="", entry_type="qa", source="manual"):
    """Add a Q&A pair or document to the knowledge base."""
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO ai_knowledge_base (admin_id, entry_type, question, answer, category, keywords, source)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (admin_id, entry_type, question, answer, category, keywords, source)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True}


def update_knowledge_entry(entry_id, admin_id, **kwargs):
    """Update a knowledge base entry."""
    allowed = {"question", "answer", "category", "keywords", "is_active", "entry_type"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    conn = get_db()
    try:
        set_clause = ", ".join(f"{k}=%s" for k in updates)
        values = list(updates.values()) + [entry_id, admin_id]
        conn.execute(
            f"UPDATE ai_knowledge_base SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=%s AND admin_id=%s",
            values
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_knowledge_entry(entry_id, admin_id):
    """Delete a knowledge base entry."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM ai_knowledge_base WHERE id=%s AND admin_id=%s", (entry_id, admin_id))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def search_knowledge_base(admin_id, query):
    """Search knowledge base by keyword matching."""
    conn = get_db()
    try:
        query_lower = query.lower().strip()
        rows = conn.execute(
            "SELECT * FROM ai_knowledge_base WHERE admin_id=%s AND is_active=TRUE",
            (admin_id,)
        ).fetchall()
    finally:
        conn.close()

    results = []
    for r in rows:
        score = 0
        q = (r["question"] or "").lower()
        a = (r["answer"] or "").lower()
        kw = (r["keywords"] or "").lower()
        for word in query_lower.split():
            if len(word) < 2:
                continue
            if word in q: score += 3
            if word in kw: score += 2
            if word in a: score += 1
        if score > 0:
            results.append((score, dict(r)))
    results.sort(key=lambda x: -x[0])
    return [r for _, r in results[:5]]


def get_guardrails(admin_id):
    """Get all active guardrails for an admin."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM ai_guardrails WHERE admin_id=%s AND is_active=TRUE ORDER BY created_at DESC",
            (admin_id,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def add_guardrail(admin_id, rule_type, rule_value, replacement_response=""):
    """Add a guardrail rule."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO ai_guardrails (admin_id, rule_type, rule_value, replacement_response) VALUES (%s, %s, %s, %s)",
            (admin_id, rule_type, rule_value, replacement_response)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True}


def delete_guardrail(guardrail_id, admin_id):
    """Delete a guardrail rule."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM ai_guardrails WHERE id=%s AND admin_id=%s", (guardrail_id, admin_id))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def record_product_view(admin_id, session_id, product_id, product_name, product_price=0,
                        product_image="", customer_email=""):
    """Record a product view for browse recovery."""
    conn = get_db()
    try:
        # Don't duplicate if same product viewed in same session recently
        existing = conn.execute(
            """SELECT id FROM browse_history
               WHERE admin_id=%s AND session_id=%s AND product_id=%s
               AND viewed_at > CURRENT_TIMESTAMP - INTERVAL '1 hour'""",
            (admin_id, session_id, product_id)
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO browse_history (admin_id, session_id, customer_email, product_id,
                   product_name, product_price, product_image)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (admin_id, session_id, customer_email, product_id, product_name, product_price, product_image)
            )
            conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def get_abandoned_browses(admin_id, hours_ago=24, limit=50):
    """Get browse sessions with views but no purchase, older than hours_ago."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT bh.customer_email, bh.session_id,
                      array_agg(DISTINCT bh.product_name) as products,
                      MAX(bh.viewed_at) as last_viewed
               FROM browse_history bh
               WHERE bh.admin_id=%s
               AND bh.customer_email != ''
               AND bh.recovery_sent = FALSE
               AND bh.viewed_at < CURRENT_TIMESTAMP - INTERVAL '%s hours'
               AND bh.viewed_at > CURRENT_TIMESTAMP - INTERVAL '7 days'
               AND NOT EXISTS (
                   SELECT 1 FROM ecom_orders o
                   WHERE o.admin_id=bh.admin_id AND LOWER(o.customer_email)=LOWER(bh.customer_email)
                   AND o.created_at > bh.viewed_at
               )
               GROUP BY bh.customer_email, bh.session_id
               LIMIT %s""",
            (admin_id, hours_ago, limit)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def mark_browse_recovery_sent(admin_id, session_id):
    """Mark browse recovery emails as sent for a session."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE browse_history SET recovery_sent=TRUE, recovery_sent_at=CURRENT_TIMESTAMP WHERE admin_id=%s AND session_id=%s",
            (admin_id, session_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def save_conversation_topic(admin_id, session_id, topic, subtopic="", sentiment="neutral", intent=""):
    """Record a conversation topic for insights tracking."""
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO conversation_topics (admin_id, session_id, topic, subtopic, sentiment, intent)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (admin_id, session_id, topic, subtopic, sentiment, intent)
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def get_trending_topics(admin_id, days=30, limit=10):
    """Get most common conversation topics in the last N days."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT topic, COUNT(*) as count,
                      COUNT(DISTINCT session_id) as unique_sessions,
                      MODE() WITHIN GROUP (ORDER BY sentiment) as top_sentiment
               FROM conversation_topics
               WHERE admin_id=%s AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
               GROUP BY topic
               ORDER BY count DESC LIMIT %s""",
            (admin_id, days, limit)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_conversation_insights(admin_id, days=30):
    """Get comprehensive conversation insights for the dashboard."""
    conn = get_db()
    try:
        # Total conversations
        total = conn.execute(
            "SELECT COUNT(DISTINCT session_id) as c FROM conversation_topics WHERE admin_id=%s AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'",
            (admin_id, days)
        ).fetchone()["c"]

        # Sentiment distribution
        sentiments = conn.execute(
            """SELECT sentiment, COUNT(*) as count FROM conversation_topics
               WHERE admin_id=%s AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
               GROUP BY sentiment ORDER BY count DESC""",
            (admin_id, days)
        ).fetchall()

        # Intent distribution
        intents = conn.execute(
            """SELECT intent, COUNT(*) as count FROM conversation_topics
               WHERE admin_id=%s AND intent != '' AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
               GROUP BY intent ORDER BY count DESC LIMIT 10""",
            (admin_id, days)
        ).fetchall()

        # Trending topics
        topics = conn.execute(
            """SELECT topic, COUNT(*) as count FROM conversation_topics
               WHERE admin_id=%s AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
               GROUP BY topic ORDER BY count DESC LIMIT 10""",
            (admin_id, days)
        ).fetchall()
    finally:
        conn.close()

    return {
        "total_conversations": total,
        "sentiments": {r["sentiment"]: r["count"] for r in sentiments},
        "top_intents": [dict(r) for r in intents],
        "trending_topics": [dict(r) for r in topics],
    }


# ── Wishlist / Save-for-Later ──

def add_to_wishlist(admin_id, customer_email, product_id, product_name, product_price=0,
                    product_image="", session_id="", notes=""):
    """Add a product to the customer's wishlist."""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM wishlists WHERE admin_id=%s AND customer_email=%s AND product_id=%s",
            (admin_id, customer_email.lower(), product_id)
        ).fetchone()
        if existing:
            return {"ok": False, "message": "Already in wishlist"}
        conn.execute(
            """INSERT INTO wishlists (admin_id, customer_email, session_id, product_id,
               product_name, product_price, product_image, notes)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (admin_id, customer_email.lower(), session_id, product_id, product_name,
             product_price, product_image, notes)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        return {"ok": False, "message": "Error saving"}
    finally:
        conn.close()
    return {"ok": True}


def get_wishlist(admin_id, customer_email, limit=20):
    """Get a customer's wishlist."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT w.*, p.product_price as current_price, p.stock_quantity
               FROM wishlists w
               LEFT JOIN products p ON p.id = w.product_id AND p.admin_id = w.admin_id
               WHERE w.admin_id=%s AND w.customer_email=%s
               ORDER BY w.created_at DESC LIMIT %s""",
            (admin_id, customer_email.lower(), limit)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def remove_from_wishlist(admin_id, customer_email, product_id):
    """Remove a product from wishlist."""
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM wishlists WHERE admin_id=%s AND customer_email=%s AND product_id=%s",
            (admin_id, customer_email.lower(), product_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def move_wishlist_to_cart(admin_id, customer_email, product_id):
    """Get wishlist item details for adding to cart, then remove from wishlist."""
    conn = get_db()
    try:
        item = conn.execute(
            "SELECT * FROM wishlists WHERE admin_id=%s AND customer_email=%s AND product_id=%s",
            (admin_id, customer_email.lower(), product_id)
        ).fetchone()
        if item:
            conn.execute(
                "DELETE FROM wishlists WHERE id=%s", (item["id"],)
            )
            conn.commit()
            return dict(item)
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return None


def get_wishlist_price_drops(admin_id, customer_email):
    """Find wishlist items where current price < saved price."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT w.*, p.product_price as current_price
               FROM wishlists w
               JOIN products p ON p.id = w.product_id AND p.admin_id = w.admin_id
               WHERE w.admin_id=%s AND w.customer_email=%s
               AND p.product_price < w.product_price
               AND w.notified_price_drop = FALSE""",
            (admin_id, customer_email.lower())
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# ── Revenue Attribution ──

def record_revenue_event(admin_id, session_id, event_type, event_value=0,
                         product_id=0, product_name="", order_id=0, order_number="",
                         customer_email="", touchpoints=None):
    """Record a revenue attribution event."""
    conn = get_db()
    try:
        import json
        tp_json = json.dumps(touchpoints or [])
        conn.execute(
            """INSERT INTO revenue_events (admin_id, session_id, customer_email, event_type,
               event_value, product_id, product_name, order_id, order_number, touchpoints_json)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (admin_id, session_id, customer_email, event_type, event_value,
             product_id, product_name, order_id, order_number, tp_json)
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def get_revenue_attribution(admin_id, days=30):
    """Get revenue attribution summary for the dashboard."""
    conn = get_db()
    try:
        # Total chatbot-influenced revenue
        total = conn.execute(
            """SELECT COALESCE(SUM(event_value), 0) as total_revenue,
                      COUNT(DISTINCT order_number) as total_orders,
                      COUNT(DISTINCT customer_email) as unique_customers
               FROM revenue_events
               WHERE admin_id=%s AND event_type='purchase'
               AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'""",
            (admin_id, days)
        ).fetchone()

        # Revenue by attribution source
        by_source = conn.execute(
            """SELECT attribution_source, SUM(event_value) as revenue, COUNT(*) as events
               FROM revenue_events
               WHERE admin_id=%s AND event_type='purchase'
               AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
               GROUP BY attribution_source ORDER BY revenue DESC""",
            (admin_id, days)
        ).fetchall()

        # Conversion funnel
        funnel = conn.execute(
            """SELECT event_type, COUNT(*) as count, COALESCE(SUM(event_value), 0) as value
               FROM revenue_events
               WHERE admin_id=%s AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
               GROUP BY event_type ORDER BY count DESC""",
            (admin_id, days)
        ).fetchall()

        # Daily revenue trend
        daily = conn.execute(
            """SELECT DATE(created_at) as day, SUM(event_value) as revenue, COUNT(*) as orders
               FROM revenue_events
               WHERE admin_id=%s AND event_type='purchase'
               AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
               GROUP BY DATE(created_at) ORDER BY day""",
            (admin_id, days)
        ).fetchall()
    finally:
        conn.close()

    return {
        "total_revenue": float(total["total_revenue"]),
        "total_orders": total["total_orders"],
        "unique_customers": total["unique_customers"],
        "by_source": [dict(r) for r in by_source],
        "funnel": [dict(r) for r in funnel],
        "daily_trend": [{"day": str(r["day"]), "revenue": float(r["revenue"]), "orders": r["orders"]} for r in daily],
    }


# ── Customer Interest Scoring (Behavioral Personalization) ──

def update_customer_interest(admin_id, customer_key, category, event_type="view"):
    """Update interest score for a customer in a product category."""
    if not category or not customer_key:
        return
    score_map = {"view": 1, "cart": 3, "purchase": 5, "wishlist": 2}
    score_delta = score_map.get(event_type, 1)
    count_col = {"view": "view_count", "cart": "cart_count", "purchase": "purchase_count"}.get(event_type, "view_count")

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM customer_interests WHERE admin_id=%s AND customer_key=%s AND category=%s",
            (admin_id, customer_key, category)
        ).fetchone()
        if existing:
            conn.execute(
                f"""UPDATE customer_interests
                    SET interest_score = interest_score + %s,
                        {count_col} = {count_col} + 1,
                        last_interaction = CURRENT_TIMESTAMP
                    WHERE id=%s""",
                (score_delta, existing["id"])
            )
        else:
            conn.execute(
                f"""INSERT INTO customer_interests (admin_id, customer_key, category, interest_score, {count_col})
                    VALUES (%s, %s, %s, %s, 1)""",
                (admin_id, customer_key, category, score_delta)
            )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def get_customer_interests(admin_id, customer_key, limit=5):
    """Get top interest categories for a customer."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT category, interest_score, view_count, cart_count, purchase_count
               FROM customer_interests
               WHERE admin_id=%s AND customer_key=%s
               ORDER BY interest_score DESC LIMIT %s""",
            (admin_id, customer_key, limit)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_personalized_products(admin_id, customer_key, limit=6):
    """Get product recommendations based on customer interests."""
    interests = get_customer_interests(admin_id, customer_key, limit=3)
    if not interests:
        return []
    top_cats = [i["category"] for i in interests if i["category"]]
    if not top_cats:
        return []
    conn = get_db()
    try:
        placeholders = ",".join(["%s"] * len(top_cats))
        rows = conn.execute(
            f"""SELECT * FROM products
                WHERE admin_id=%s AND product_status='active'
                AND LOWER(product_category) IN ({placeholders})
                ORDER BY RANDOM() LIMIT %s""",
            [admin_id] + [c.lower() for c in top_cats] + [limit]
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════
#  SIZE & FIT PREDICTOR
# ══════════════════════════════════════════════════════════════

def upsert_size_fit_profile(admin_id, customer_key, **kwargs):
    allowed = {"body_type", "preferred_fit", "height", "weight", "shoe_size", "typical_size", "fit_notes"}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v}
    if not fields:
        return
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM size_fit_profiles WHERE admin_id=%s AND customer_key=%s",
            (admin_id, customer_key)
        ).fetchone()
        if existing:
            set_clause = ", ".join(f"{k}=%s" for k in fields)
            conn.execute(
                f"UPDATE size_fit_profiles SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                list(fields.values()) + [existing["id"]]
            )
        else:
            cols = ["admin_id", "customer_key"] + list(fields.keys())
            placeholders = ",".join(["%s"] * len(cols))
            conn.execute(
                f"INSERT INTO size_fit_profiles ({','.join(cols)}) VALUES ({placeholders})",
                [admin_id, customer_key] + list(fields.values())
            )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def get_size_fit_profile(admin_id, customer_key):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM size_fit_profiles WHERE admin_id=%s AND customer_key=%s",
        (admin_id, customer_key)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_size_fit_feedback(admin_id, customer_key, product_id, product_name="",
                           brand="", category="", recommended_size="", actual_fit="",
                           returned=False, return_reason=""):
    conn = get_db()
    conn.execute(
        """INSERT INTO size_fit_feedback
           (admin_id, customer_key, product_id, product_name, brand, category,
            recommended_size, actual_fit, returned, return_reason)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (admin_id, customer_key, product_id, product_name, brand, category,
         recommended_size, actual_fit, returned, return_reason)
    )
    conn.commit()
    conn.close()


def get_size_fit_stats(admin_id, product_id=None, brand=None, category=None):
    """Get aggregate size/fit data from feedback to power recommendations."""
    conn = get_db()
    conditions = ["admin_id=%s"]
    params = [admin_id]
    if product_id:
        conditions.append("product_id=%s")
        params.append(product_id)
    if brand:
        conditions.append("LOWER(brand)=LOWER(%s)")
        params.append(brand)
    if category:
        conditions.append("LOWER(category)=LOWER(%s)")
        params.append(category)
    where = " AND ".join(conditions)
    rows = conn.execute(
        f"""SELECT recommended_size, actual_fit, returned, return_reason, COUNT(*) as cnt
            FROM size_fit_feedback WHERE {where}
            GROUP BY recommended_size, actual_fit, returned, return_reason
            ORDER BY cnt DESC""",
        params
    ).fetchall()
    conn.close()

    stats = {"total": 0, "sizes": {}, "fit_issues": [], "return_rate": 0}
    total = 0
    returned_count = 0
    for r in rows:
        row = dict(r)
        total += row["cnt"]
        if row["returned"]:
            returned_count += row["cnt"]
            stats["fit_issues"].append({
                "size": row["recommended_size"], "issue": row["return_reason"],
                "count": row["cnt"]
            })
        size = row["recommended_size"]
        if size not in stats["sizes"]:
            stats["sizes"][size] = {"total": 0, "fits_well": 0}
        stats["sizes"][size]["total"] += row["cnt"]
        if row["actual_fit"] in ("perfect", "good", "true_to_size"):
            stats["sizes"][size]["fits_well"] += row["cnt"]
    stats["total"] = total
    stats["return_rate"] = round(returned_count / total * 100, 1) if total > 0 else 0
    return stats


# ══════════════════════════════════════════════════════════════
#  PRICE WATCH / DROP ALERTS
# ══════════════════════════════════════════════════════════════

def add_price_watch(admin_id, customer_email, product_id, product_name, current_price, target_price=0, session_id=""):
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO price_watches (admin_id, customer_email, session_id, product_id,
               product_name, watched_price, target_price)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (admin_id, customer_email, product_id) DO UPDATE
               SET watched_price=%s, target_price=%s, notified=FALSE""",
            (admin_id, customer_email, session_id, product_id, product_name,
             current_price, target_price, current_price, target_price)
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return {"ok": True}


def get_price_watches(admin_id, customer_email):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM price_watches WHERE admin_id=%s AND customer_email=%s AND notified=FALSE ORDER BY created_at DESC",
        (admin_id, customer_email)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_price_drops_for_watches(admin_id):
    """Check all active price watches against current product prices. Returns alerts."""
    conn = get_db()
    rows = conn.execute(
        """SELECT pw.*, p.product_price as current_price
           FROM price_watches pw
           JOIN products p ON pw.admin_id = p.admin_id AND pw.product_id = p.id
           WHERE pw.admin_id=%s AND pw.notified=FALSE
           AND (CAST(p.product_price AS REAL) < pw.watched_price
                OR (pw.target_price > 0 AND CAST(p.product_price AS REAL) <= pw.target_price))""",
        (admin_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_price_watch_notified(watch_id):
    conn = get_db()
    conn.execute(
        "UPDATE price_watches SET notified=TRUE, notified_at=CURRENT_TIMESTAMP WHERE id=%s",
        (watch_id,)
    )
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════
#  COMPETITOR PRICES
# ══════════════════════════════════════════════════════════════

def upsert_competitor_price(admin_id, product_id, competitor_name, competitor_price,
                            competitor_url="", our_advantages=""):
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO competitor_prices (admin_id, product_id, competitor_name,
               competitor_price, competitor_url, our_advantages)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (admin_id, product_id, competitor_name) DO UPDATE
               SET competitor_price=%s, competitor_url=%s, our_advantages=%s, last_checked=CURRENT_TIMESTAMP""",
            (admin_id, product_id, competitor_name, competitor_price, competitor_url, our_advantages,
             competitor_price, competitor_url, our_advantages)
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def get_competitor_prices(admin_id, product_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM competitor_prices WHERE admin_id=%s AND product_id=%s ORDER BY competitor_price ASC",
        (admin_id, product_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════
#  FRAUD DETECTION
# ══════════════════════════════════════════════════════════════

def record_fraud_signal(admin_id, session_id, signal_type, signal_detail="",
                        risk_score=0, customer_email=""):
    conn = get_db()
    conn.execute(
        """INSERT INTO fraud_signals (admin_id, session_id, customer_email,
           signal_type, signal_detail, risk_score)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (admin_id, session_id, customer_email, signal_type, signal_detail, risk_score)
    )
    conn.commit()
    conn.close()


def get_session_fraud_score(admin_id, session_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(risk_score), 0) as total_risk FROM fraud_signals WHERE admin_id=%s AND session_id=%s AND resolved=FALSE",
        (admin_id, session_id)
    ).fetchone()
    conn.close()
    return float(row["total_risk"]) if row else 0


def get_fraud_signals(admin_id, session_id=None, limit=50):
    conn = get_db()
    if session_id:
        rows = conn.execute(
            "SELECT * FROM fraud_signals WHERE admin_id=%s AND session_id=%s ORDER BY created_at DESC LIMIT %s",
            (admin_id, session_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM fraud_signals WHERE admin_id=%s AND resolved=FALSE ORDER BY risk_score DESC, created_at DESC LIMIT %s",
            (admin_id, limit)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════
#  CLV / VIP SCORING
# ══════════════════════════════════════════════════════════════

def get_customer_ltv_score(admin_id, customer_email):
    """Calculate LTV score from ecom_customers data."""
    if not customer_email:
        return None
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM ecom_customers WHERE admin_id=%s AND LOWER(customer_email)=LOWER(%s)",
        (admin_id, customer_email)
    ).fetchone()
    conn.close()
    if not row:
        return None
    cust = dict(row)
    total_orders = int(cust.get("total_orders", 0) or 0)
    total_spent = float(cust.get("total_spent", 0) or 0)
    aov = float(cust.get("avg_order_value", 0) or 0)
    loyalty_points = int(cust.get("loyalty_points", 0) or 0)

    # Score: weighted combination
    score = 0
    if total_orders >= 10: score += 40
    elif total_orders >= 5: score += 25
    elif total_orders >= 3: score += 15
    elif total_orders >= 1: score += 5

    if total_spent >= 1000: score += 30
    elif total_spent >= 500: score += 20
    elif total_spent >= 200: score += 10
    elif total_spent >= 50: score += 5

    if aov >= 200: score += 15
    elif aov >= 100: score += 10
    elif aov >= 50: score += 5

    if loyalty_points >= 500: score += 15
    elif loyalty_points >= 100: score += 10
    elif loyalty_points >= 20: score += 5

    tier = "standard"
    if score >= 70: tier = "vip"
    elif score >= 45: tier = "gold"
    elif score >= 25: tier = "silver"

    return {
        "score": score,
        "tier": tier,
        "total_orders": total_orders,
        "total_spent": total_spent,
        "avg_order_value": aov,
        "loyalty_points": loyalty_points,
    }


# ══════════════════════════════════════════════════════════════
#  INVENTORY SCARCITY / VIEW VELOCITY
# ══════════════════════════════════════════════════════════════

def get_product_view_velocity(admin_id, product_id, hours=1):
    """Count unique sessions that viewed this product in the last N hours."""
    conn = get_db()
    row = conn.execute(
        f"""SELECT COUNT(DISTINCT session_id) as viewer_count
            FROM browse_history
            WHERE admin_id=%s AND product_id=%s
            AND viewed_at > CURRENT_TIMESTAMP - INTERVAL '{int(hours)} hours'""",
        (admin_id, product_id)
    ).fetchone()
    conn.close()
    return int(row["viewer_count"]) if row else 0


def get_product_purchase_velocity(admin_id, product_id, hours=24):
    """Count purchases of this product in the last N hours."""
    conn = get_db()
    row = conn.execute(
        f"""SELECT COUNT(*) as purchase_count
            FROM revenue_events
            WHERE admin_id=%s AND product_id=%s AND event_type='purchase'
            AND created_at > CURRENT_TIMESTAMP - INTERVAL '{int(hours)} hours'""",
        (admin_id, product_id)
    ).fetchone()
    conn.close()
    return int(row["purchase_count"]) if row else 0


# ══════════════════════════════════════════════════════════════
#  MERCHANT AI CO-PILOT
# ══════════════════════════════════════════════════════════════

def get_merchant_analytics_summary(admin_id, days=30):
    """Aggregate analytics for merchant co-pilot queries."""
    conn = get_db()
    summary = {}

    # Revenue summary
    rev = conn.execute(
        """SELECT COALESCE(SUM(event_value), 0) as total_revenue,
                  COUNT(DISTINCT order_number) as order_count,
                  COUNT(DISTINCT customer_email) as unique_customers
           FROM revenue_events
           WHERE admin_id=%s AND event_type='purchase'
           AND created_at > CURRENT_TIMESTAMP - INTERVAL '%s days'""",
        (admin_id, days)
    ).fetchone()
    summary["revenue"] = {
        "total": float(rev["total_revenue"]) if rev else 0,
        "orders": int(rev["order_count"]) if rev else 0,
        "unique_customers": int(rev["unique_customers"]) if rev else 0,
    }

    # Top products by revenue
    top_prods = conn.execute(
        """SELECT product_name, SUM(event_value) as revenue, COUNT(*) as sales
           FROM revenue_events
           WHERE admin_id=%s AND event_type='purchase'
           AND created_at > CURRENT_TIMESTAMP - INTERVAL '%s days'
           AND product_name != ''
           GROUP BY product_name ORDER BY revenue DESC LIMIT 10""",
        (admin_id, days)
    ).fetchall()
    summary["top_products"] = [{"name": r["product_name"], "revenue": float(r["revenue"]), "sales": r["sales"]} for r in top_prods]

    # Conversation topics
    topics = conn.execute(
        """SELECT topic, COUNT(*) as cnt
           FROM conversation_topics
           WHERE admin_id=%s AND created_at > CURRENT_TIMESTAMP - INTERVAL '%s days'
           GROUP BY topic ORDER BY cnt DESC LIMIT 10""",
        (admin_id, days)
    ).fetchall()
    summary["top_topics"] = [{"topic": r["topic"], "count": r["cnt"]} for r in topics]

    # Return rate (from size_fit_feedback)
    returns = conn.execute(
        """SELECT COUNT(*) as total, SUM(CASE WHEN returned THEN 1 ELSE 0 END) as returned
           FROM size_fit_feedback WHERE admin_id=%s
           AND created_at > CURRENT_TIMESTAMP - INTERVAL '%s days'""",
        (admin_id, days)
    ).fetchone()
    total_fb = int(returns["total"]) if returns and returns["total"] else 0
    returned_fb = int(returns["returned"]) if returns and returns["returned"] else 0
    summary["returns"] = {
        "total_feedback": total_fb,
        "returned": returned_fb,
        "return_rate": round(returned_fb / total_fb * 100, 1) if total_fb > 0 else 0,
    }

    # Low stock products
    low_stock = conn.execute(
        """SELECT product_name, inventory_quantity, product_category
           FROM products
           WHERE admin_id=%s AND product_status='active'
           AND inventory_quantity > 0 AND inventory_quantity <= low_stock_threshold
           ORDER BY inventory_quantity ASC LIMIT 10""",
        (admin_id,)
    ).fetchall()
    summary["low_stock"] = [{"name": r["product_name"], "qty": r["inventory_quantity"], "category": r["product_category"]} for r in low_stock]

    # Fraud alerts
    fraud = conn.execute(
        "SELECT COUNT(*) as cnt FROM fraud_signals WHERE admin_id=%s AND resolved=FALSE",
        (admin_id,)
    ).fetchone()
    summary["unresolved_fraud_alerts"] = int(fraud["cnt"]) if fraud else 0

    # Conversion funnel
    funnel = conn.execute(
        """SELECT event_type, COUNT(*) as cnt
           FROM revenue_events
           WHERE admin_id=%s AND created_at > CURRENT_TIMESTAMP - INTERVAL '%s days'
           GROUP BY event_type ORDER BY cnt DESC""",
        (admin_id, days)
    ).fetchall()
    summary["funnel"] = {r["event_type"]: r["cnt"] for r in funnel}

    conn.close()
    return summary


# ── Fast Setup results persistence ──

def _ensure_fast_setup_table():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS fast_setup_results (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL UNIQUE,
        source_url TEXT NOT NULL DEFAULT '',
        data_json TEXT NOT NULL DEFAULT '{}',
        applied BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

_ensure_fast_setup_table()


def save_fast_setup_result(admin_id, source_url, data):
    """Save fast setup scan results to DB."""
    conn = get_db()
    data_json = json.dumps(data)
    existing = conn.execute("SELECT id FROM fast_setup_results WHERE admin_id=%s", (admin_id,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE fast_setup_results SET source_url=%s, data_json=%s, applied=FALSE, updated_at=CURRENT_TIMESTAMP WHERE admin_id=%s",
            (source_url, data_json, admin_id))
    else:
        conn.execute(
            "INSERT INTO fast_setup_results (admin_id, source_url, data_json) VALUES (%s,%s,%s)",
            (admin_id, source_url, data_json))
    conn.commit()
    conn.close()


def get_fast_setup_result(admin_id):
    """Get saved fast setup results for an admin."""
    conn = get_db()
    row = conn.execute("SELECT source_url, data_json, applied FROM fast_setup_results WHERE admin_id=%s", (admin_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {"source_url": row["source_url"], "data": json.loads(row["data_json"]), "applied": row["applied"]}


def mark_fast_setup_applied(admin_id):
    """Mark fast setup as applied."""
    conn = get_db()
    conn.execute("UPDATE fast_setup_results SET applied=TRUE, updated_at=CURRENT_TIMESTAMP WHERE admin_id=%s", (admin_id,))
    conn.commit()
    conn.close()


# ── Website Visitor Tracking ──

def record_page_visit(admin_id, visitor_id="", page_url="", page_path="", referrer="", user_agent="", ip_hash="", device_type="desktop"):
    """Record a single page visit."""
    conn = get_db()
    conn.execute(
        """INSERT INTO page_visits (admin_id, visitor_id, page_url, page_path, referrer, user_agent, ip_hash, device_type)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (admin_id, visitor_id, page_url, page_path, referrer, user_agent, ip_hash, device_type)
    )
    conn.commit()
    conn.close()


def get_visitor_stats(admin_id):
    """Get visitor statistics for an admin's website."""
    from datetime import datetime, timedelta
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        # Today
        today_total = conn.execute(
            "SELECT COUNT(*) as c FROM page_visits WHERE admin_id=%s AND created_at::date = %s", (admin_id, today)
        ).fetchone()["c"]
        today_unique = conn.execute(
            "SELECT COUNT(DISTINCT visitor_id) as c FROM page_visits WHERE admin_id=%s AND created_at::date = %s", (admin_id, today)
        ).fetchone()["c"]

        # This week
        week_total = conn.execute(
            "SELECT COUNT(*) as c FROM page_visits WHERE admin_id=%s AND created_at::date >= %s", (admin_id, week_ago)
        ).fetchone()["c"]
        week_unique = conn.execute(
            "SELECT COUNT(DISTINCT visitor_id) as c FROM page_visits WHERE admin_id=%s AND created_at::date >= %s", (admin_id, week_ago)
        ).fetchone()["c"]

        # This month
        month_total = conn.execute(
            "SELECT COUNT(*) as c FROM page_visits WHERE admin_id=%s AND created_at::date >= %s", (admin_id, month_ago)
        ).fetchone()["c"]
        month_unique = conn.execute(
            "SELECT COUNT(DISTINCT visitor_id) as c FROM page_visits WHERE admin_id=%s AND created_at::date >= %s", (admin_id, month_ago)
        ).fetchone()["c"]

        # All time
        all_total = conn.execute(
            "SELECT COUNT(*) as c FROM page_visits WHERE admin_id=%s", (admin_id,)
        ).fetchone()["c"]
        all_unique = conn.execute(
            "SELECT COUNT(DISTINCT visitor_id) as c FROM page_visits WHERE admin_id=%s", (admin_id,)
        ).fetchone()["c"]

        # Top pages (last 30 days)
        top_pages = conn.execute(
            """SELECT page_path, COUNT(*) as views, COUNT(DISTINCT visitor_id) as unique_visitors
               FROM page_visits WHERE admin_id=%s AND created_at::date >= %s
               GROUP BY page_path ORDER BY views DESC LIMIT 5""",
            (admin_id, month_ago)
        ).fetchall()

        # Top referrers (last 30 days)
        top_referrers = conn.execute(
            """SELECT referrer, COUNT(*) as visits
               FROM page_visits WHERE admin_id=%s AND created_at::date >= %s AND referrer != '' AND referrer NOT LIKE '%%' || page_url || '%%'
               GROUP BY referrer ORDER BY visits DESC LIMIT 5""",
            (admin_id, month_ago)
        ).fetchall()

        # Device breakdown (last 30 days)
        devices = conn.execute(
            """SELECT device_type, COUNT(*) as visits
               FROM page_visits WHERE admin_id=%s AND created_at::date >= %s
               GROUP BY device_type ORDER BY visits DESC""",
            (admin_id, month_ago)
        ).fetchall()

        conn.close()
        return {
            "today_total": today_total,
            "today_unique": today_unique,
            "week_total": week_total,
            "week_unique": week_unique,
            "month_total": month_total,
            "month_unique": month_unique,
            "all_total": all_total,
            "all_unique": all_unique,
            "top_pages": [dict(r) for r in top_pages],
            "top_referrers": [dict(r) for r in top_referrers],
            "devices": [dict(r) for r in devices],
        }
    except Exception as e:
        conn.close()
        return None


# Initialize on import
init_db()
