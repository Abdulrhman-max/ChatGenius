"""
SQLite database for leads, bookings, users (admin/doctor roles), doctor requests.
"""

import sqlite3
import os
import json
import hashlib
import secrets
from datetime import datetime, timedelta

TOKEN_LIFETIME = timedelta(days=1, hours=3)  # 27 hours

DB_PATH = os.path.join(os.path.dirname(__file__), "chatgenius.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            source TEXT DEFAULT 'chatbot',
            notes TEXT DEFAULT '',
            admin_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            token_expires_at TIMESTAMP DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS company_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            business_name TEXT DEFAULT '',
            address TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            business_hours TEXT DEFAULT '',
            services TEXT DEFAULT '',
            pricing_insurance TEXT DEFAULT '',
            emergency_info TEXT DEFAULT '',
            about TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            user_id INTEGER DEFAULT 0,
            name TEXT NOT NULL,
            email TEXT DEFAULT '',
            specialty TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            availability TEXT DEFAULT 'Mon-Fri',
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS doctor_breaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            break_name TEXT DEFAULT 'Break',
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            day_of_week TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS doctor_off_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            off_date TEXT NOT NULL,
            reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS doctor_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            admin_name TEXT DEFAULT '',
            business_name TEXT DEFAULT '',
            doctor_email TEXT NOT NULL,
            doctor_user_id INTEGER DEFAULT 0,
            doctor_record_id INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS admin_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            head_admin_id INTEGER NOT NULL,
            head_admin_name TEXT DEFAULT '',
            business_name TEXT DEFAULT '',
            admin_email TEXT NOT NULL,
            admin_user_id INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (head_admin_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            admin_id INTEGER DEFAULT 0,
            message TEXT NOT NULL,
            intent TEXT DEFAULT '',
            intent_confidence REAL DEFAULT 0,
            resulted_in_booking INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 1: Smart Waitlist
        CREATE TABLE IF NOT EXISTS waitlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            doctor_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            time_slot TEXT NOT NULL,
            patient_name TEXT NOT NULL,
            patient_email TEXT DEFAULT '',
            patient_phone TEXT DEFAULT '',
            position INTEGER DEFAULT 0,
            status TEXT DEFAULT 'waiting',
            notified_at TIMESTAMP DEFAULT '',
            confirm_deadline TIMESTAMP DEFAULT '',
            confirmed_at TIMESTAMP DEFAULT '',
            expired_at TIMESTAMP DEFAULT '',
            session_id TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (doctor_id) REFERENCES doctors(id)
        );

        -- Feature 2: Digital Patient Forms
        CREATE TABLE IF NOT EXISTS patient_forms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings(id)
        );

        -- Feature 3: Recall & Retention
        CREATE TABLE IF NOT EXISTS recall_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            treatment_type TEXT NOT NULL,
            recall_days INTEGER NOT NULL DEFAULT 180,
            message_template TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS recall_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            rule_id INTEGER DEFAULT 0,
            patient_name TEXT NOT NULL,
            patient_email TEXT DEFAULT '',
            patient_phone TEXT DEFAULT '',
            recall_type TEXT DEFAULT 'appointment',
            status TEXT DEFAULT 'pending',
            sent_at TIMESTAMP DEFAULT '',
            opened_at TIMESTAMP DEFAULT '',
            booked_at TIMESTAMP DEFAULT '',
            booking_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 4: Missed Call Auto-Reply
        CREATE TABLE IF NOT EXISTS missed_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            doctor_id INTEGER DEFAULT 0,
            patient_name TEXT NOT NULL,
            patient_email TEXT DEFAULT '',
            patient_phone TEXT DEFAULT '',
            treatment_name TEXT NOT NULL,
            recommended_date TEXT DEFAULT '',
            followup_day INTEGER NOT NULL DEFAULT 2,
            status TEXT DEFAULT 'pending',
            sent_at TIMESTAMP DEFAULT '',
            booked_at TIMESTAMP DEFAULT '',
            cancelled_at TIMESTAMP DEFAULT '',
            booking_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 7: Before & After Gallery
        CREATE TABLE IF NOT EXISTS gallery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            patient_name TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            status TEXT DEFAULT 'queued',
            staff_user_id INTEGER DEFAULT 0,
            staff_name TEXT DEFAULT '',
            assigned_at TIMESTAMP DEFAULT '',
            resolved_at TIMESTAMP DEFAULT '',
            resolution_notes TEXT DEFAULT '',
            ai_confidence REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 11: Block & Holiday Scheduling (rebuilt)
        CREATE TABLE IF NOT EXISTS schedule_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            promotion_id INTEGER NOT NULL,
            booking_id INTEGER DEFAULT 0,
            patient_name TEXT DEFAULT '',
            patient_email TEXT DEFAULT '',
            discount_amount REAL DEFAULT 0,
            original_amount REAL DEFAULT 0,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (promotion_id) REFERENCES promotions(id)
        );

        -- Feature 14: Referral System
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_admin_id INTEGER NOT NULL,
            referred_email TEXT NOT NULL,
            referred_admin_id INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'pending',
            reward_type TEXT DEFAULT 'percentage',
            reward_value REAL DEFAULT 10,
            reward_applied INTEGER DEFAULT 0,
            converted_at TIMESTAMP DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 15: Patient Profile
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            doctor_id INTEGER DEFAULT 0,
            booking_id INTEGER DEFAULT 0,
            note TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        );

        -- Feature 17: A/B Testing
        CREATE TABLE IF NOT EXISTS ab_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,
            points INTEGER NOT NULL,
            action TEXT NOT NULL,
            description TEXT DEFAULT '',
            booking_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        );

        -- Feature 19: GMB Integration
        CREATE TABLE IF NOT EXISTS gmb_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER UNIQUE NOT NULL,
            google_account_id TEXT DEFAULT '',
            location_id TEXT DEFAULT '',
            access_token TEXT DEFAULT '',
            refresh_token TEXT DEFAULT '',
            rating REAL DEFAULT 0,
            review_count INTEGER DEFAULT 0,
            last_synced_at TIMESTAMP DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature 20: Competitor Benchmarking
        CREATE TABLE IF NOT EXISTS clinic_metrics_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            plan_expires_at TIMESTAMP DEFAULT '',
            billing_cycle TEXT DEFAULT 'monthly',
            stripe_customer_id TEXT DEFAULT '',
            stripe_subscription_id TEXT DEFAULT '',
            -- Verification & status
            is_verified INTEGER DEFAULT 0,
            verified_at TIMESTAMP DEFAULT '',
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
            chatbot_welcome_msg TEXT DEFAULT 'Hello! How can I help you today?',
            -- Limits
            max_admins INTEGER DEFAULT 3,
            max_doctors INTEGER DEFAULT 10,
            max_monthly_chats INTEGER DEFAULT 1000,
            max_bookings INTEGER DEFAULT 500,
            -- Linking to existing users system
            head_admin_user_id INTEGER DEFAULT 0,
            -- Timestamps
            last_active_at TIMESTAMP DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Customer usage tracking
        CREATE TABLE IF NOT EXISTS customer_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            total_chats INTEGER DEFAULT 0,
            total_bookings INTEGER DEFAULT 0,
            total_leads INTEGER DEFAULT 0,
            total_api_calls INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        -- Customer invoices
        CREATE TABLE IF NOT EXISTS customer_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            invoice_number TEXT UNIQUE NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            currency TEXT DEFAULT 'USD',
            status TEXT DEFAULT 'pending',
            stripe_invoice_id TEXT DEFAULT '',
            period_start TEXT DEFAULT '',
            period_end TEXT DEFAULT '',
            paid_at TIMESTAMP DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        -- Smart Appointment Reminders
        CREATE TABLE IF NOT EXISTS appointment_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER UNIQUE,
            reminder_48h_enabled INTEGER DEFAULT 1,
            reminder_24h_enabled INTEGER DEFAULT 1,
            reminder_2h_enabled INTEGER DEFAULT 1,
            hours_before_first INTEGER DEFAULT 48,
            hours_before_second INTEGER DEFAULT 24,
            hours_before_third INTEGER DEFAULT 2,
            quiet_hours_start INTEGER DEFAULT 23,
            quiet_hours_end INTEGER DEFAULT 8,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature: Patient Satisfaction Surveys
        CREATE TABLE IF NOT EXISTS surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER UNIQUE,
            auto_send_enabled INTEGER DEFAULT 1,
            send_delay_hours INTEGER DEFAULT 2,
            google_review_url TEXT DEFAULT '',
            min_rating_for_review INTEGER DEFAULT 4,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature: Treatment Packages
        CREATE TABLE IF NOT EXISTS treatment_packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_id INTEGER,
            patient_id INTEGER,
            booking_id INTEGER,
            treatment_name TEXT,
            redeemed_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Feature: Smart Upsell
        CREATE TABLE IF NOT EXISTS upsell_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upsell_rule_id INTEGER,
            session_id TEXT,
            shown_at TEXT DEFAULT CURRENT_TIMESTAMP,
            accepted INTEGER DEFAULT 0,
            booking_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- No-Show Recovery Engine
        CREATE TABLE IF NOT EXISTS noshow_recovery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER UNIQUE,
            max_noshows_before_deposit INTEGER DEFAULT 2,
            deposit_amount REAL DEFAULT 50,
            recovery_delay_minutes INTEGER DEFAULT 15,
            auto_recovery_enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Invoice Engine
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER UNIQUE,
            auto_generate INTEGER DEFAULT 1,
            send_day_of_month INTEGER DEFAULT 1,
            recipients_json TEXT DEFAULT '[]',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Multi-Channel Unified Inbox
        CREATE TABLE IF NOT EXISTS channel_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER DEFAULT 0,
            conversation_id INTEGER,
            direction TEXT DEFAULT 'inbound',
            sender_name TEXT DEFAULT '',
            message_text TEXT DEFAULT '',
            message_type TEXT DEFAULT 'text',
            media_url TEXT DEFAULT '',
            external_message_id TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES channel_conversations(id)
        );

        -- White-Label Configuration
        CREATE TABLE IF NOT EXISTS whitelabel_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    """)

    # Migration: add new columns to existing tables
    migrations = [
        ("users", "role", "TEXT DEFAULT 'admin'"),
        ("users", "admin_id", "INTEGER DEFAULT 0"),
        ("users", "token_expires_at", "TIMESTAMP DEFAULT ''"),
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
        # Feature 13: 2FA
        ("users", "totp_secret", "TEXT DEFAULT ''"),
        ("users", "two_fa_enabled", "INTEGER DEFAULT 0"),
        ("users", "two_fa_method", "TEXT DEFAULT 'email'"),
        ("users", "last_activity_at", "TIMESTAMP DEFAULT ''"),
        # Feature 14: Referral
        ("users", "referral_code", "TEXT DEFAULT ''"),
        ("users", "referred_by", "TEXT DEFAULT ''"),
        # Feature 15: Patient Profile
        ("bookings", "patient_id", "INTEGER DEFAULT 0"),
        ("bookings", "outcome", "TEXT DEFAULT ''"),
        ("bookings", "treatment_type", "TEXT DEFAULT ''"),
        # Feature 16: Real-time dashboard
        ("bookings", "checked_in", "INTEGER DEFAULT 0"),
        ("bookings", "checked_in_at", "TIMESTAMP DEFAULT ''"),
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
        ("waitlist", "expired_at", "TIMESTAMP DEFAULT ''"),
        # Feature 2: Patient Forms — signature_data column (replaces consent_signature)
        ("patient_forms", "signature_data", "TEXT DEFAULT ''"),
        # Feature 17: A/B Testing — completed_at column
        ("ab_tests", "completed_at", "TIMESTAMP DEFAULT ''"),
        # Doctor Portal — emergency availability & status message
        ("doctors", "emergency_available", "INTEGER DEFAULT 0"),
        ("doctors", "status_message", "TEXT DEFAULT ''"),
        # Waitlist-to-booking linkage
        ("bookings", "waitlist_id", "INTEGER DEFAULT 0"),
        # Customer API integration — fetch customers from external database
        ("company_info", "customers_api_url", "TEXT DEFAULT ''"),
        ("company_info", "customers_api_key", "TEXT DEFAULT ''"),
        ("company_info", "currency", "TEXT DEFAULT 'USD'"),
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
        ("leads", "last_activity_at", "TIMESTAMP DEFAULT ''"),
        ("leads", "converted_at", "TIMESTAMP DEFAULT ''"),
        ("leads", "converted_booking_id", "INTEGER DEFAULT 0"),
        ("doctor_breaks", "day_of_week", "TEXT DEFAULT ''"),
    ]
    for table, col, col_type in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    # Backfill public_id for existing users that don't have one
    import uuid as _uuid
    users_without_pid = conn.execute("SELECT id FROM users WHERE public_id IS NULL OR public_id = ''").fetchall()
    for u in users_without_pid:
        conn.execute("UPDATE users SET public_id = ? WHERE id = ?", (str(_uuid.uuid4()), u["id"]))
    if users_without_pid:
        conn.commit()

    # Feature 17: A/B Testing — session assignment tracking
    conn.execute("""CREATE TABLE IF NOT EXISTS ab_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        test_id INTEGER,
        session_id TEXT,
        variant TEXT,
        converted INTEGER DEFAULT 0,
        created_at TEXT
    )""")
    conn.commit()

    # Service-doctor mapping (which doctors perform which services)
    conn.execute("""CREATE TABLE IF NOT EXISTS service_doctors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_id INTEGER NOT NULL,
        doctor_id INTEGER NOT NULL,
        admin_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(service_id, doctor_id)
    )""")
    conn.commit()

    # Service interest notifications — when user wants a service with no doctors yet
    conn.execute("""CREATE TABLE IF NOT EXISTS service_interests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER NOT NULL,
        admin_id INTEGER NOT NULL,
        day_number INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        scheduled_at TIMESTAMP NOT NULL,
        sent_at TIMESTAMP DEFAULT '',
        cancelled_at TIMESTAMP DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
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
    existing_defaults = conn.execute("SELECT COUNT(*) FROM categories WHERE admin_id = 0").fetchone()[0]
    if existing_defaults == 0:
        for cat in DEFAULT_CATEGORIES:
            conn.execute("INSERT INTO categories (admin_id, name) VALUES (0, ?)", (cat,))
        conn.commit()

    conn.close()


def save_lead(name, phone, notes="", admin_id=0):
    conn = get_db()
    conn.execute(
        "INSERT INTO leads (name, phone, notes, admin_id) VALUES (?, ?, ?, ?)",
        (name, phone, notes, admin_id),
    )
    conn.commit()
    conn.close()


def save_lead_enriched(name, phone, email="", notes="", admin_id=0, source="chatbot",
                       capture_trigger="manual", treatment_interest="", is_returning=0,
                       preferred_time="", session_id=""):
    """Save a lead with full enrichment data. Returns the new lead ID."""
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO leads (name, phone, email, notes, admin_id, source, capture_trigger,
           treatment_interest, is_returning, preferred_time, session_id, stage, last_activity_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,'new',?)""",
        (name, phone, email, notes, admin_id, source, capture_trigger,
         treatment_interest, is_returning, preferred_time, session_id, now),
    )
    conn.commit()
    lead_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return lead_id


def update_lead_stage(lead_id, stage):
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE leads SET stage=?, last_activity_at=? WHERE id=?", (stage, now, lead_id))
    conn.commit()
    conn.close()


def update_lead_score(lead_id, score):
    conn = get_db()
    conn.execute("UPDATE leads SET score=? WHERE id=?", (min(10, max(0, score)), lead_id))
    conn.commit()
    conn.close()


def get_all_leads(admin_id=0):
    conn = get_db()
    if admin_id:
        rows = conn.execute("SELECT * FROM leads WHERE admin_id = ? ORDER BY created_at DESC", (admin_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_leads_by_stage(admin_id, stage):
    conn = get_db()
    rows = conn.execute("SELECT * FROM leads WHERE admin_id=? AND stage=? ORDER BY score DESC, created_at DESC",
                        (admin_id, stage)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_lead_by_session(session_id):
    """Find an existing lead by chat session ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM leads WHERE session_id=? LIMIT 1", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def convert_lead(lead_id, booking_id):
    """Delete a lead when converted to booking — remove from leads entirely."""
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Cancel pending follow-ups first
    conn.execute("UPDATE lead_followups SET status='cancelled', cancelled_at=? WHERE lead_id=? AND status='pending'",
                 (now, lead_id))
    # Delete the lead — they're now a booking
    conn.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    # Clean up follow-ups too
    conn.execute("DELETE FROM lead_followups WHERE lead_id=?", (lead_id,))
    conn.commit()
    conn.close()


def create_lead_followup(lead_id, admin_id, day_number, scheduled_at):
    conn = get_db()
    conn.execute(
        "INSERT INTO lead_followups (lead_id, admin_id, day_number, scheduled_at) VALUES (?,?,?,?)",
        (lead_id, admin_id, day_number, scheduled_at),
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
           WHERE lf.status='pending' AND lf.scheduled_at <= ?
           ORDER BY lf.scheduled_at""", (now,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_lead_followup_sent(followup_id):
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE lead_followups SET status='sent', sent_at=? WHERE id=?", (now, followup_id))
    conn.commit()
    conn.close()


def cancel_lead_followups(lead_id):
    from datetime import datetime
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE lead_followups SET status='cancelled', cancelled_at=? WHERE lead_id=? AND status='pending'",
                 (now, lead_id))
    conn.commit()
    conn.close()


def get_lead_followup_summary(lead_id):
    """Returns dict with total, sent, pending counts."""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM lead_followups WHERE lead_id=?", (lead_id,)).fetchone()[0]
    sent = conn.execute("SELECT COUNT(*) FROM lead_followups WHERE lead_id=? AND status='sent'", (lead_id,)).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM lead_followups WHERE lead_id=? AND status='pending'", (lead_id,)).fetchone()[0]
    conn.close()
    return {"total": total, "sent": sent, "pending": pending}


def get_stale_leads(admin_id, hours=48):
    """Find leads in 'new' or 'engaged' stage with no activity for N hours."""
    from datetime import datetime, timedelta
    conn = get_db()
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT * FROM leads WHERE admin_id=? AND stage IN ('new','engaged')
           AND last_activity_at != '' AND last_activity_at < ?
           ORDER BY last_activity_at""",
        (admin_id, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_booking(customer_name, customer_email, date, time, service="General Consultation",
                 calendar_event_id="", customer_phone="", doctor_id=0, doctor_name="", admin_id=0,
                 status="pending", promotion_code="", service_id=0, notes="", patient_type=""):
    conn = get_db()
    conn.execute(
        """INSERT INTO bookings (customer_name, customer_email, customer_phone, date, time,
           service, calendar_event_id, doctor_id, doctor_name, admin_id, status, promotion_code,
           service_id, notes, patient_type)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (customer_name, customer_email, customer_phone, date, time, service,
         calendar_event_id, doctor_id, doctor_name, admin_id, status, promotion_code,
         int(service_id or 0), notes or "", patient_type or ""),
    )
    booking_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return booking_id


def add_booking(customer_name, customer_email="", customer_phone="", date="", time="",
                service="General Consultation", doctor_id=0, doctor_name="", admin_id=0, status="pending"):
    """Add a booking and return its ID."""
    conn = get_db()
    conn.execute(
        """INSERT INTO bookings (customer_name, customer_email, customer_phone, date, time,
           service, doctor_id, doctor_name, admin_id, status) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (customer_name, customer_email, customer_phone, date, time, service, doctor_id, doctor_name, admin_id, status))
    conn.commit()
    bid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return bid


def confirm_booking_by_id(booking_id):
    """Mark a pending booking as confirmed."""
    conn = get_db()
    conn.execute("UPDATE bookings SET status='confirmed' WHERE id=?", (booking_id,))
    conn.commit()
    conn.close()


def get_booked_times(doctor_id, date_str):
    """Get list of booked time strings for a doctor on a specific date.
    Also includes slots held by waitlist (status='notified') so they can't be double-booked."""
    conn = get_db()
    rows = conn.execute(
        "SELECT time FROM bookings WHERE doctor_id = ? AND date = ? AND status != 'cancelled'",
        (doctor_id, date_str)).fetchall()
    booked = [r["time"] for r in rows]
    # Also hold slots where a waitlist patient is deciding
    held = conn.execute(
        "SELECT time_slot FROM waitlist WHERE doctor_id = ? AND date = ? AND status = 'notified'",
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
        "SELECT * FROM bookings WHERE admin_id = ? AND date = ? AND status != 'cancelled' ORDER BY time",
        (admin_id, date_str)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_booking_dates(admin_id):
    """Return a list of distinct dates that have active bookings for an admin."""
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT date FROM bookings WHERE admin_id = ? AND status NOT IN ('cancelled','no_show') ORDER BY date",
        (admin_id,)).fetchall()
    conn.close()
    return [r["date"] for r in rows]


def cancel_booking(booking_id):
    """Cancel a booking by setting its status to 'cancelled'."""
    conn = get_db()
    conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()


def get_booking_by_id(booking_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def find_upcoming_bookings_for_customer(admin_id, name="", email="", phone=""):
    """Find upcoming (today or later) active bookings matching customer identity."""
    from datetime import date as _date
    today = _date.today().isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM bookings WHERE admin_id = ? AND date >= ? AND status != 'cancelled' ORDER BY date, time",
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
        rows = conn.execute("SELECT * FROM bookings WHERE doctor_id = ? ORDER BY created_at DESC", (doctor_id,)).fetchall()
    elif admin_id:
        rows = conn.execute("SELECT * FROM bookings WHERE admin_id = ? ORDER BY created_at DESC", (admin_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM bookings ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats(admin_id=0, doctor_id=0):
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    if doctor_id:
        lead_count = 0
        booking_count = conn.execute("SELECT COUNT(*) FROM bookings WHERE doctor_id = ? AND status != 'cancelled'", (doctor_id,)).fetchone()[0]
        today_bookings = conn.execute("SELECT COUNT(*) FROM bookings WHERE doctor_id = ? AND date = ? AND status != 'cancelled'", (doctor_id, today)).fetchone()[0]
    elif admin_id:
        lead_count = conn.execute("SELECT COUNT(*) FROM leads WHERE admin_id = ?", (admin_id,)).fetchone()[0]
        booking_count = conn.execute("SELECT COUNT(*) FROM bookings WHERE admin_id = ? AND status != 'cancelled'", (admin_id,)).fetchone()[0]
        today_bookings = conn.execute("SELECT COUNT(*) FROM bookings WHERE admin_id = ? AND date = ? AND status != 'cancelled'", (admin_id, today)).fetchone()[0]
    else:
        lead_count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        booking_count = conn.execute("SELECT COUNT(*) FROM bookings WHERE status != 'cancelled'").fetchone()[0]
        today_bookings = conn.execute("SELECT COUNT(*) FROM bookings WHERE date = ? AND status != 'cancelled'", (today,)).fetchone()[0]
    conn.close()
    return {
        "total_leads": lead_count,
        "total_bookings": booking_count,
        "today_bookings": today_bookings,
    }


# ══════════════════════════════════════════════
#  User Authentication
# ══════════════════════════════════════════════

def _hash_password(password):
    salt = "chatgenius_salt_2026"
    return hashlib.sha256((password + salt).encode()).hexdigest()


def _generate_token():
    return secrets.token_hex(32)


def _token_expiry():
    return (datetime.now() + TOKEN_LIFETIME).strftime("%Y-%m-%d %H:%M:%S")


def create_user(name, email, password="", company="", provider="email", provider_id="", role="admin", specialty=""):
    import uuid as _uuid
    conn = get_db()
    token = _generate_token()
    expires = _token_expiry()
    password_hash = _hash_password(password) if password else ""
    public_id = str(_uuid.uuid4())
    try:
        conn.execute(
            """INSERT INTO users (name, email, password_hash, company, role, plan, provider, provider_id, token, token_expires_at, specialty, public_id)
               VALUES (?, ?, ?, ?, ?, 'free_trial', ?, ?, ?, ?, ?, ?)""",
            (name, email, password_hash, company, role, provider, provider_id, token, expires, specialty, public_id),
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        return dict(user), None
    except sqlite3.IntegrityError:
        conn.close()
        return None, "An account with this email already exists."


def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_by_public_id(public_id):
    """Resolve a public GUID to the user record."""
    if not public_id:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE public_id = ?", (public_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def login_user(email, password):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    if not user:
        return None, "No account found with this email."
    if user["provider"] != "email":
        return None, f"This account uses {user['provider']} login. Please use the {user['provider'].title()} button."
    if user["password_hash"] != _hash_password(password):
        return None, "Incorrect password. Please try again."
    # Refresh token with expiry
    token = _generate_token()
    expires = _token_expiry()
    conn = get_db()
    conn.execute("UPDATE users SET token = ?, token_expires_at = ? WHERE id = ?", (token, expires, user["id"]))
    conn.commit()
    conn.close()
    user_dict = dict(user)
    user_dict["token"] = token
    user_dict["token_expires_at"] = expires
    return user_dict, None


def login_or_create_social(name, email, provider, provider_id, avatar_url="", role="admin", specialty=""):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    token = _generate_token()
    expires = _token_expiry()

    if user:
        conn.execute("UPDATE users SET token = ?, token_expires_at = ?, avatar_url = ? WHERE id = ?",
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
        conn.execute(
            """INSERT INTO users (name, email, company, role, plan, provider, provider_id, avatar_url, token, token_expires_at, specialty, public_id)
               VALUES (?, ?, '', ?, 'free_trial', ?, ?, ?, ?, ?, ?, ?)""",
            (name, email, role, provider, provider_id, avatar_url, token, expires, specialty, public_id),
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        return dict(user), None


def get_user_by_token(token):
    if not token:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
    if not user:
        conn.close()
        return None
    # Check if token has expired
    expires = user["token_expires_at"]
    if expires:
        try:
            expires_dt = datetime.strptime(expires, "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expires_dt:
                conn.execute("UPDATE users SET token = '', token_expires_at = '' WHERE id = ?", (user["id"],))
                conn.commit()
                conn.close()
                return None
        except ValueError:
            pass
    conn.close()
    return dict(user)


def get_user_by_email(email):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(user) if user else None


def update_user_profile(user_id, name, email, new_password="", avatar_url=None):
    conn = get_db()
    try:
        conn.execute("UPDATE users SET name = ?, email = ? WHERE id = ?", (name, email, user_id))
        if new_password:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (_hash_password(new_password), user_id))
        if avatar_url is not None:
            conn.execute("UPDATE users SET avatar_url = ? WHERE id = ?", (avatar_url, user_id))
        conn.commit()
        conn.close()
        return True
    except Exception:
        conn.close()
        return False


def set_user_admin_id(user_id, admin_id):
    """Set a user's admin_id (link/unlink from company)."""
    conn = get_db()
    conn.execute("UPDATE users SET admin_id = ? WHERE id = ?", (admin_id, user_id))
    conn.commit()
    conn.close()


def update_user_plan(user_id, plan):
    conn = get_db()
    conn.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, user_id))
    conn.commit()
    conn.close()


def user_to_public(user):
    """Return safe user dict (no password hash)."""
    # Admins and doctors inherit the plan from their head_admin
    plan = user["plan"]
    admin_id = user.get("admin_id", 0)
    if user.get("role") in ("admin", "doctor") and admin_id:
        conn = get_db()
        head = conn.execute("SELECT plan FROM users WHERE id = ?", (admin_id,)).fetchone()
        conn.close()
        if head:
            plan = head["plan"]
    return {
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
    }


# ══════════════════════════════════════════════
#  Company Info
# ══════════════════════════════════════════════

def get_company_info(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM company_info WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_company_info(user_id, data):
    conn = get_db()
    existing = conn.execute("SELECT id FROM company_info WHERE user_id = ?", (user_id,)).fetchone()
    if existing:
        conn.execute("""UPDATE company_info SET business_name=?, address=?, phone=?, business_hours=?,
            services=?, pricing_insurance=?, emergency_info=?, about=?, currency=?, updated_at=CURRENT_TIMESTAMP
            WHERE user_id=?""",
            (data.get("business_name", ""), data.get("address", ""), data.get("phone", ""),
             data.get("business_hours", ""), data.get("services", ""), data.get("pricing_insurance", ""),
             data.get("emergency_info", ""), data.get("about", ""), data.get("currency", "USD"), user_id))
    else:
        conn.execute("""INSERT INTO company_info (user_id, business_name, address, phone, business_hours,
            services, pricing_insurance, emergency_info, about, currency) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (user_id, data.get("business_name", ""), data.get("address", ""), data.get("phone", ""),
             data.get("business_hours", ""), data.get("services", ""), data.get("pricing_insurance", ""),
             data.get("emergency_info", ""), data.get("about", ""), data.get("currency", "USD")))
    conn.commit()
    conn.close()


def save_customers_api_config(user_id, api_url, api_key):
    """Save the external customers API endpoint and key for a given admin."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM company_info WHERE user_id = ?", (user_id,)).fetchone()
    if existing:
        conn.execute("UPDATE company_info SET customers_api_url=?, customers_api_key=? WHERE user_id=?",
                     (api_url, api_key, user_id))
    else:
        conn.execute("INSERT INTO company_info (user_id, customers_api_url, customers_api_key) VALUES (?,?,?)",
                     (user_id, api_url, api_key))
    conn.commit()
    conn.close()


def get_customers_api_config(user_id):
    """Get the external customers API config for a given admin."""
    conn = get_db()
    row = conn.execute("SELECT customers_api_url, customers_api_key FROM company_info WHERE user_id = ?", (user_id,)).fetchone()
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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    user = conn.execute("SELECT id, role, admin_id FROM users WHERE id=?", (admin_id,)).fetchone()
    head_id = admin_id
    if user and user["role"] != "head_admin" and user["admin_id"]:
        head_id = user["admin_id"]
    row = conn.execute("SELECT currency FROM company_info WHERE user_id=?", (head_id,)).fetchone()
    conn.close()
    return (row["currency"] if row and row["currency"] else "USD")


def get_company_services(admin_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM company_services WHERE admin_id=? ORDER BY name", (admin_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_company_service_by_id(service_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM company_services WHERE id=?", (service_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_company_service(admin_id, name, price, currency="USD", source="manual",
                        category="", duration_minutes=60, description="",
                        preparation_instructions="", is_active=1):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO company_services (admin_id, name, price, currency, source,
           category, duration_minutes, description, preparation_instructions, is_active)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (admin_id, name, float(price or 0), currency, source,
         category, int(duration_minutes or 60), description, preparation_instructions, int(is_active)),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def update_company_service(service_id, admin_id, name, price, category=None,
                           duration_minutes=None, description=None,
                           preparation_instructions=None, is_active=None):
    conn = get_db()
    conn.execute(
        "UPDATE company_services SET name=?, price=? WHERE id=? AND admin_id=?",
        (name, float(price or 0), service_id, admin_id),
    )
    if category is not None:
        conn.execute("UPDATE company_services SET category=? WHERE id=? AND admin_id=?",
                     (category, service_id, admin_id))
    if duration_minutes is not None:
        conn.execute("UPDATE company_services SET duration_minutes=? WHERE id=? AND admin_id=?",
                     (int(duration_minutes), service_id, admin_id))
    if description is not None:
        conn.execute("UPDATE company_services SET description=? WHERE id=? AND admin_id=?",
                     (description, service_id, admin_id))
    if preparation_instructions is not None:
        conn.execute("UPDATE company_services SET preparation_instructions=? WHERE id=? AND admin_id=?",
                     (preparation_instructions, service_id, admin_id))
    if is_active is not None:
        conn.execute("UPDATE company_services SET is_active=? WHERE id=? AND admin_id=?",
                     (1 if is_active else 0, service_id, admin_id))
    conn.commit()
    conn.close()


def delete_company_service(service_id, admin_id):
    conn = get_db()
    conn.execute("DELETE FROM company_services WHERE id=? AND admin_id=?", (service_id, admin_id))
    conn.commit()
    conn.close()


def delete_all_company_services(admin_id, source=None):
    conn = get_db()
    if source:
        conn.execute("DELETE FROM company_services WHERE admin_id=? AND source=?", (admin_id, source))
    else:
        conn.execute("DELETE FROM company_services WHERE admin_id=?", (admin_id,))
    conn.commit()
    conn.close()


def set_all_services_currency(admin_id, currency):
    conn = get_db()
    conn.execute("UPDATE company_services SET currency=? WHERE admin_id=?", (currency, admin_id))
    conn.commit()
    conn.close()


# ── Service-Doctor Mapping ──

def assign_doctor_to_service(service_id, doctor_id, admin_id):
    conn = get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO service_doctors (service_id, doctor_id, admin_id) VALUES (?,?,?)",
                     (service_id, doctor_id, admin_id))
        conn.commit()
    except Exception:
        pass
    conn.close()


def remove_doctor_from_service(service_id, doctor_id):
    conn = get_db()
    conn.execute("DELETE FROM service_doctors WHERE service_id=? AND doctor_id=?", (service_id, doctor_id))
    conn.commit()
    conn.close()


def get_doctors_for_service(service_id):
    """Get all doctors assigned to a service."""
    conn = get_db()
    rows = conn.execute(
        """SELECT d.* FROM doctors d
           JOIN service_doctors sd ON sd.doctor_id = d.id
           WHERE sd.service_id=? AND d.is_active=1
           ORDER BY d.name""",
        (service_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_services_with_doctors(admin_id):
    """Get all services with their assigned doctor IDs."""
    services = get_company_services(admin_id)
    conn = get_db()
    for svc in services:
        rows = conn.execute("SELECT doctor_id FROM service_doctors WHERE service_id=?", (svc["id"],)).fetchall()
        svc["doctor_ids"] = [r["doctor_id"] for r in rows]
    conn.close()
    return services


def set_service_doctors(service_id, doctor_ids, admin_id):
    """Replace all doctor assignments for a service."""
    conn = get_db()
    conn.execute("DELETE FROM service_doctors WHERE service_id=?", (service_id,))
    for did in doctor_ids:
        conn.execute("INSERT INTO service_doctors (service_id, doctor_id, admin_id) VALUES (?,?,?)",
                     (service_id, did, admin_id))
    conn.commit()
    conn.close()


def add_service_interest(service_id, service_name, patient_name, patient_email, patient_phone, admin_id):
    """Record that a patient wants to be notified when a doctor is assigned to a service."""
    conn = get_db()
    conn.execute(
        """INSERT INTO service_interests (service_id, service_name, patient_name, patient_email, patient_phone, admin_id)
           VALUES (?,?,?,?,?,?)""",
        (service_id, service_name, patient_name, patient_email, patient_phone, admin_id)
    )
    conn.commit()
    conn.close()


def get_waiting_service_interests(service_id):
    """Get all patients waiting for notification about a service."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM service_interests WHERE service_id=? AND status='waiting'",
        (service_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_service_interest_notified(interest_id):
    """Mark a service interest as notified."""
    conn = get_db()
    conn.execute(
        "UPDATE service_interests SET status='notified', notified_at=CURRENT_TIMESTAMP WHERE id=?",
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
            "INSERT INTO company_services (admin_id, name, price, currency, source) VALUES (?,?,?,?,?)",
            (admin_id, name, price, svc_cur, source),
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
            "INSERT INTO company_services (admin_id, name, price, currency, source) VALUES (?,?,?,?,?)",
            (admin_id, s["name"], float(s.get("price") or 0), currency, "pdf"),
        )
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════
#  Doctors
# ══════════════════════════════════════════════

def get_doctors(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM doctors WHERE admin_id = ? ORDER BY name", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_doctor_by_id(doctor_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_doctor_by_user_id(user_id):
    """Get the doctor record linked to a user account."""
    conn = get_db()
    row = conn.execute("SELECT * FROM doctors WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _strip_dr_prefix(name):
    """Remove leading 'Dr.' or 'Dr ' from a name to avoid 'Dr. Dr. X'."""
    import re
    return re.sub(r'^(?:Dr\.?\s+)+', '', name, flags=re.IGNORECASE).strip()


def add_doctor(admin_id, name, email="", specialty="", bio="", availability="Mon-Fri"):
    name = _strip_dr_prefix(name)
    conn = get_db()
    conn.execute(
        "INSERT INTO doctors (admin_id, user_id, name, email, specialty, bio, availability, status) VALUES (?,0,?,?,?,?,?,?)",
        (admin_id, name, email, specialty, bio, availability, "pending"))
    conn.commit()
    doctor_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return doctor_id


def add_doctor_from_pdf(admin_id, name, email="", specialty="", bio="", availability="Mon-Fri",
                        start_time=None, end_time=None, phone="", qualifications="",
                        languages="", years_of_experience=0, pdf_filename="",
                        schedule_type="fixed", daily_hours=""):
    """Create a doctor record directly from PDF extraction (no invitation flow)."""
    name = _strip_dr_prefix(name)
    conn = get_db()
    conn.execute(
        """INSERT INTO doctors (admin_id, user_id, name, email, specialty, bio, availability,
           status, start_time, end_time, phone, qualifications, languages, years_of_experience,
           pdf_filename, schedule_type, daily_hours)
           VALUES (?,0,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (admin_id, name, email, specialty, bio, availability, "active",
         start_time or "09:00 AM", end_time or "05:00 PM",
         phone, qualifications, languages, int(years_of_experience or 0), pdf_filename,
         schedule_type, daily_hours))
    conn.commit()
    doctor_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return doctor_id


def update_doctor(doctor_id, admin_id, name, specialty="", bio="", availability="Mon-Fri",
                   start_time=None, end_time=None, is_active=None, appointment_length=None,
                   years_of_experience=None, schedule_type=None, daily_hours=None,
                   gender=None, photo_url=None):
    name = _strip_dr_prefix(name)
    conn = get_db()
    conn.execute("UPDATE doctors SET name=?, specialty=?, bio=?, availability=? WHERE id=? AND admin_id=?",
                 (name, specialty, bio, availability, doctor_id, admin_id))
    if start_time is not None:
        conn.execute("UPDATE doctors SET start_time=? WHERE id=? AND admin_id=?",
                     (start_time, doctor_id, admin_id))
    if end_time is not None:
        conn.execute("UPDATE doctors SET end_time=? WHERE id=? AND admin_id=?",
                     (end_time, doctor_id, admin_id))
    if is_active is not None:
        conn.execute("UPDATE doctors SET is_active=? WHERE id=? AND admin_id=?",
                     (1 if is_active else 0, doctor_id, admin_id))
    if appointment_length is not None:
        conn.execute("UPDATE doctors SET appointment_length=? WHERE id=? AND admin_id=?",
                     (int(appointment_length), doctor_id, admin_id))
    if years_of_experience is not None:
        conn.execute("UPDATE doctors SET years_of_experience=? WHERE id=? AND admin_id=?",
                     (int(years_of_experience), doctor_id, admin_id))
    if schedule_type is not None:
        conn.execute("UPDATE doctors SET schedule_type=? WHERE id=? AND admin_id=?",
                     (schedule_type, doctor_id, admin_id))
    if daily_hours is not None:
        conn.execute("UPDATE doctors SET daily_hours=? WHERE id=? AND admin_id=?",
                     (daily_hours if isinstance(daily_hours, str) else json.dumps(daily_hours),
                      doctor_id, admin_id))
    if gender is not None:
        conn.execute("UPDATE doctors SET gender=? WHERE id=? AND admin_id=?",
                     (gender, doctor_id, admin_id))
    if photo_url is not None:
        conn.execute("UPDATE doctors SET photo_url=? WHERE id=? AND admin_id=?",
                     (photo_url, doctor_id, admin_id))
    conn.commit()
    conn.close()


def delete_doctor(doctor_id, admin_id):
    conn = get_db()
    conn.execute("DELETE FROM doctors WHERE id=? AND admin_id=?", (doctor_id, admin_id))
    conn.commit()
    conn.close()


def link_doctor_to_user(doctor_id, user_id):
    """Link a doctor record to a user account after they accept."""
    conn = get_db()
    conn.execute("UPDATE doctors SET user_id = ?, status = 'active' WHERE id = ?", (user_id, doctor_id))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════
#  Doctor Breaks
# ══════════════════════════════════════════════

def get_doctor_breaks(doctor_id, day_of_week=None):
    conn = get_db()
    if day_of_week:
        rows = conn.execute(
            "SELECT * FROM doctor_breaks WHERE doctor_id = ? AND (day_of_week = ? OR day_of_week = '' OR day_of_week IS NULL) ORDER BY start_time",
            (doctor_id, day_of_week)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM doctor_breaks WHERE doctor_id = ? ORDER BY day_of_week, start_time", (doctor_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_doctor_break(doctor_id, break_name, start_time, end_time, day_of_week=""):
    conn = get_db()
    conn.execute(
        "INSERT INTO doctor_breaks (doctor_id, break_name, start_time, end_time, day_of_week) VALUES (?,?,?,?,?)",
        (doctor_id, break_name, start_time, end_time, day_of_week))
    conn.commit()
    break_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return break_id


def delete_doctor_break(break_id, doctor_id):
    conn = get_db()
    conn.execute("DELETE FROM doctor_breaks WHERE id = ? AND doctor_id = ?", (break_id, doctor_id))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════
#  Doctor Off Days
# ══════════════════════════════════════════════

def get_doctor_off_days(doctor_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM doctor_off_days WHERE doctor_id = ? ORDER BY off_date", (doctor_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_doctor_off_dates(doctor_id):
    """Return just the date strings as a set for quick lookup."""
    conn = get_db()
    rows = conn.execute("SELECT off_date FROM doctor_off_days WHERE doctor_id = ?", (doctor_id,)).fetchall()
    conn.close()
    return set(r["off_date"] for r in rows)


def add_doctor_off_day(doctor_id, off_date, reason=""):
    conn = get_db()
    # Prevent duplicates
    existing = conn.execute("SELECT id FROM doctor_off_days WHERE doctor_id = ? AND off_date = ?",
                            (doctor_id, off_date)).fetchone()
    if existing:
        conn.close()
        return None, "This date is already marked as off."
    conn.execute(
        "INSERT INTO doctor_off_days (doctor_id, off_date, reason) VALUES (?,?,?)",
        (doctor_id, off_date, reason))
    conn.commit()
    off_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return off_id, None


def delete_doctor_off_day(off_day_id, doctor_id):
    conn = get_db()
    conn.execute("DELETE FROM doctor_off_days WHERE id = ? AND doctor_id = ?", (off_day_id, doctor_id))
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
        "SELECT id FROM doctor_requests WHERE admin_id = ? AND doctor_email = ? AND status = 'pending'",
        (admin_id, doctor_email)).fetchone()
    if existing:
        conn.close()
        return None, "A request has already been sent to this email."

    # Check if doctor has an account
    doctor_user = conn.execute("SELECT id FROM users WHERE email = ?", (doctor_email,)).fetchone()
    doctor_user_id = doctor_user["id"] if doctor_user else 0

    conn.execute(
        """INSERT INTO doctor_requests (admin_id, admin_name, business_name, doctor_email,
           doctor_user_id, doctor_record_id, status) VALUES (?,?,?,?,?,?,?)""",
        (admin_id, admin_name, business_name, doctor_email, doctor_user_id, doctor_record_id, "pending"))
    conn.commit()
    req_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return req_id, None


def get_doctor_requests_for_doctor(doctor_email):
    """Get all pending requests for a doctor by email."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM doctor_requests WHERE doctor_email = ? AND status = 'pending' ORDER BY created_at DESC",
        (doctor_email,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_doctor_requests_by_admin(admin_id):
    """Get all requests sent by an admin."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM doctor_requests WHERE admin_id = ? ORDER BY created_at DESC",
        (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_doctor_request(request_id, admin_id):
    """Delete a pending doctor request sent by an admin."""
    conn = get_db()
    conn.execute("DELETE FROM doctor_requests WHERE id = ? AND admin_id = ? AND status = 'pending'",
                 (request_id, admin_id))
    conn.commit()
    conn.close()


def respond_to_doctor_request(request_id, doctor_user_id, accept=True):
    """Accept or reject a doctor request."""
    conn = get_db()
    req = conn.execute("SELECT * FROM doctor_requests WHERE id = ? AND status = 'pending'", (request_id,)).fetchone()
    if not req:
        conn.close()
        return None, "Request not found or already handled."

    new_status = "accepted" if accept else "rejected"
    conn.execute("UPDATE doctor_requests SET status = ?, doctor_user_id = ? WHERE id = ?",
                 (new_status, doctor_user_id, request_id))

    if accept:
        # Link doctor record to user account
        doctor_record_id = req["doctor_record_id"]
        admin_id = req["admin_id"]
        doctor_email = req["doctor_email"]
        # Get the doctor user's specialty and copy it to the doctor record
        doctor_user = conn.execute("SELECT specialty FROM users WHERE id = ?", (doctor_user_id,)).fetchone()
        user_specialty = doctor_user["specialty"] if doctor_user and doctor_user["specialty"] else None
        if user_specialty:
            conn.execute("UPDATE doctors SET user_id = ?, status = 'active', specialty = ? WHERE id = ?",
                         (doctor_user_id, user_specialty, doctor_record_id))
        else:
            conn.execute("UPDATE doctors SET user_id = ?, status = 'active' WHERE id = ?",
                         (doctor_user_id, doctor_record_id))
        # Set the doctor user's admin_id and role
        conn.execute("UPDATE users SET admin_id = ?, role = 'doctor' WHERE id = ?",
                     (admin_id, doctor_user_id))

        # Clean up: delete all OTHER pending requests for this doctor + their orphan doctor records
        other_pending = conn.execute(
            "SELECT id, doctor_record_id, admin_id FROM doctor_requests WHERE doctor_email = ? AND status = 'pending' AND id != ?",
            (doctor_email, request_id)).fetchall()
        for other in other_pending:
            # Delete the orphaned pending doctor record
            conn.execute("DELETE FROM doctors WHERE id = ? AND admin_id = ? AND status = 'pending'",
                         (other["doctor_record_id"], other["admin_id"]))
            # Mark the request as cancelled
            conn.execute("UPDATE doctor_requests SET status = 'cancelled' WHERE id = ?", (other["id"],))

    conn.commit()
    conn.close()
    return dict(req), None


# ══════════════════════════════════════════════
#  Admin Requests (head_admin invites admins)
# ══════════════════════════════════════════════

def create_admin_request(head_admin_id, head_admin_name, business_name, admin_email):
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM admin_requests WHERE head_admin_id = ? AND admin_email = ? AND status = 'pending'",
        (head_admin_id, admin_email)).fetchone()
    if existing:
        conn.close()
        return None, "A request has already been sent to this email."
    admin_user = conn.execute("SELECT id FROM users WHERE email = ?", (admin_email,)).fetchone()
    admin_user_id = admin_user["id"] if admin_user else 0
    conn.execute(
        """INSERT INTO admin_requests (head_admin_id, head_admin_name, business_name,
           admin_email, admin_user_id, status) VALUES (?,?,?,?,?,?)""",
        (head_admin_id, head_admin_name, business_name, admin_email, admin_user_id, "pending"))
    conn.commit()
    req_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return req_id, None


def get_admin_requests_for_user(email):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM admin_requests WHERE admin_email = ? AND status = 'pending' ORDER BY created_at DESC",
        (email,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_admin_requests_by_head(head_admin_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM admin_requests WHERE head_admin_id = ? ORDER BY created_at DESC",
        (head_admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def respond_to_admin_request(request_id, user_id, accept=True):
    conn = get_db()
    req = conn.execute("SELECT * FROM admin_requests WHERE id = ? AND status = 'pending'", (request_id,)).fetchone()
    if not req:
        conn.close()
        return None, "Request not found or already handled."
    new_status = "accepted" if accept else "rejected"
    conn.execute("UPDATE admin_requests SET status = ?, admin_user_id = ? WHERE id = ?",
                 (new_status, user_id, request_id))
    if accept:
        head_admin_id = req["head_admin_id"]
        # Migrate any doctors this admin already owns to the head admin's company
        # Update doctor records: admin_id from admin's own id → head_admin_id
        conn.execute("UPDATE doctors SET admin_id = ? WHERE admin_id = ?",
                     (head_admin_id, user_id))
        # Update doctor user accounts: admin_id → head_admin_id
        conn.execute("UPDATE users SET admin_id = ? WHERE admin_id = ? AND role = 'doctor'",
                     (head_admin_id, user_id))
        # Update doctor_requests: admin_id → head_admin_id
        conn.execute("UPDATE doctor_requests SET admin_id = ? WHERE admin_id = ?",
                     (head_admin_id, user_id))
        # Link the admin to the head admin's company
        conn.execute("UPDATE users SET admin_id = ?, role = 'admin' WHERE id = ?",
                     (head_admin_id, user_id))
    conn.commit()
    conn.close()
    return dict(req), None


def delete_admin_request(request_id, head_admin_id):
    conn = get_db()
    conn.execute("DELETE FROM admin_requests WHERE id = ? AND head_admin_id = ?", (request_id, head_admin_id))
    conn.commit()
    conn.close()


def get_company_admins(head_admin_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, email, role, created_at FROM users WHERE admin_id = ? AND role = 'admin'",
        (head_admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def remove_admin_from_company(admin_user_id, head_admin_id):
    conn = get_db()
    conn.execute("UPDATE users SET admin_id = 0, role = 'head_admin' WHERE id = ? AND admin_id = ?",
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
        "SELECT * FROM categories WHERE admin_id IN (0, ?) ORDER BY name",
        (admin_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_category(admin_id, name):
    """Add a custom category for an admin."""
    conn = get_db()
    # Check for duplicate (global or admin-specific)
    existing = conn.execute(
        "SELECT id FROM categories WHERE name = ? AND admin_id IN (0, ?)",
        (name, admin_id)
    ).fetchone()
    if existing:
        conn.close()
        return None, "This category already exists."
    conn.execute("INSERT INTO categories (admin_id, name) VALUES (?, ?)", (admin_id, name))
    conn.commit()
    cat_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return cat_id, None


def delete_category(category_id, admin_id):
    """Delete a custom category (only admin's own, not global defaults)."""
    conn = get_db()
    conn.execute("DELETE FROM categories WHERE id = ? AND admin_id = ?", (category_id, admin_id))
    conn.commit()
    conn.close()


def get_doctors_by_category(admin_id, category_name):
    """Get active doctors filtered by specialty/category (supports comma-separated multi-specialty)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM doctors WHERE admin_id = ? AND status = 'active' AND (specialty = ? OR specialty LIKE ? OR specialty LIKE ? OR specialty LIKE ?) ORDER BY name",
        (admin_id, category_name,
         f"{category_name}, %", f"%, {category_name}, %", f"%, {category_name}")
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════
#  Chat Logging & Analytics
# ══════════════════════════════════════════════

def log_chat(session_id, admin_id, message, intent="", intent_confidence=0.0, resulted_in_booking=0):
    """Log a chat message for analytics."""
    conn = get_db()
    conn.execute(
        "INSERT INTO chat_logs (session_id, admin_id, message, intent, intent_confidence, resulted_in_booking) "
        "VALUES (?,?,?,?,?,?)",
        (session_id, admin_id, message, intent, intent_confidence, resulted_in_booking))
    conn.commit()
    conn.close()


def mark_session_booked(session_id):
    """Mark all messages in a session as having resulted in a booking."""
    conn = get_db()
    conn.execute("UPDATE chat_logs SET resulted_in_booking = 1 WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


_analytics_cache = {}
_CACHE_TTL = 300  # 5 minutes


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
        SELECT DATE(created_at) as day, COUNT(DISTINCT session_id) as count
        FROM chat_logs WHERE admin_id = ? AND DATE(created_at) BETWEEN ? AND ?
        GROUP BY DATE(created_at) ORDER BY day
    """, (admin_id, date_from, date_to)).fetchall()
    leads_per_day = [{"date": r["day"], "count": r["count"]} for r in leads_rows]

    total_sessions = conn.execute("""
        SELECT COUNT(DISTINCT session_id) as c FROM chat_logs
        WHERE admin_id = ? AND DATE(created_at) BETWEEN ? AND ?
    """, (admin_id, date_from, date_to)).fetchone()["c"]

    # 2. Conversion rate (sessions that booked / total sessions) per week
    conversion_rows = conn.execute("""
        SELECT
            strftime('%Y-W%W', created_at) as week,
            COUNT(DISTINCT session_id) as total_chats,
            COUNT(DISTINCT CASE WHEN resulted_in_booking = 1 THEN session_id END) as booked
        FROM chat_logs WHERE admin_id = ? AND DATE(created_at) BETWEEN ? AND ?
        GROUP BY week ORDER BY week
    """, (admin_id, date_from, date_to)).fetchall()
    conversion_data = [{
        "week": r["week"], "total_chats": r["total_chats"],
        "total_bookings": r["booked"],
        "rate": round(r["booked"] / r["total_chats"] * 100, 1) if r["total_chats"] > 0 else 0
    } for r in conversion_rows]

    total_booked_sessions = conn.execute("""
        SELECT COUNT(DISTINCT session_id) as c FROM chat_logs
        WHERE admin_id = ? AND resulted_in_booking = 1 AND DATE(created_at) BETWEEN ? AND ?
    """, (admin_id, date_from, date_to)).fetchone()["c"]

    # 3. Peak booking hours
    peak_rows = conn.execute("""
        SELECT CAST(SUBSTR(time, 1, 2) as INTEGER) as hour_num,
               CASE WHEN time LIKE '%PM%' AND SUBSTR(time, 1, 2) != '12' THEN CAST(SUBSTR(time, 1, 2) as INTEGER) + 12
                    WHEN time LIKE '%AM%' AND SUBSTR(time, 1, 2) = '12' THEN 0
                    ELSE CAST(SUBSTR(time, 1, 2) as INTEGER) END as hour24,
               COUNT(*) as count
        FROM bookings WHERE admin_id = ? AND status != 'cancelled'
        AND DATE(created_at) BETWEEN ? AND ?
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
        WHERE admin_id = ? AND intent != '' AND DATE(created_at) BETWEEN ? AND ?
        GROUP BY intent ORDER BY count DESC LIMIT 10
    """, (admin_id, date_from, date_to)).fetchall()

    total_intents = sum(r["count"] for r in intent_rows) if intent_rows else 0
    top_intents = [{
        "intent": r["intent"], "count": r["count"],
        "pct": round(r["count"] / total_intents * 100, 1) if total_intents > 0 else 0
    } for r in intent_rows]

    # 5. No-show rate per week
    noshow_rows = conn.execute("""
        SELECT
            strftime('%Y-W%W', created_at) as week,
            COUNT(*) as total,
            SUM(CASE WHEN status = 'no_show' THEN 1 ELSE 0 END) as no_shows
        FROM bookings WHERE admin_id = ? AND status IN ('confirmed', 'no_show', 'completed')
        AND DATE(created_at) BETWEEN ? AND ?
        GROUP BY week ORDER BY week
    """, (admin_id, date_from, date_to)).fetchall()
    noshow_data = [{
        "week": r["week"], "confirmed": r["total"], "no_shows": r["no_shows"],
        "rate": round(r["no_shows"] / r["total"] * 100, 1) if r["total"] > 0 else 0
    } for r in noshow_rows]

    # 6. Bookings per day
    bookings_per_day_rows = conn.execute("""
        SELECT DATE(created_at) as day, COUNT(*) as count
        FROM bookings WHERE admin_id = ? AND status != 'cancelled'
        AND DATE(created_at) BETWEEN ? AND ?
        GROUP BY DATE(created_at) ORDER BY day
    """, (admin_id, date_from, date_to)).fetchall()
    bookings_per_day = [{"date": r["day"], "count": r["count"]} for r in bookings_per_day_rows]

    result = {
        "leads_per_day": leads_per_day,
        "total_sessions": total_sessions,
        "conversion": conversion_data,
        "conversion_rate": round(total_booked_sessions / total_sessions * 100, 1) if total_sessions > 0 else 0,
        "peak_hours": peak_hours,
        "top_intents": top_intents,
        "noshow": noshow_data,
        "total_bookings": total_bookings_period,
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
        "SELECT MAX(position) as mx FROM waitlist WHERE admin_id=? AND doctor_id=? AND date=? AND time_slot=? AND status IN ('waiting','notified')",
        (admin_id, doctor_id, date, time_slot)).fetchone()
    pos = (row["mx"] or 0) + 1
    conn.execute(
        "INSERT INTO waitlist (admin_id,doctor_id,date,time_slot,patient_name,patient_email,patient_phone,position,session_id) VALUES (?,?,?,?,?,?,?,?,?)",
        (admin_id, doctor_id, date, time_slot, patient_name, patient_email, patient_phone, pos, session_id))
    conn.commit()
    wid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return wid


def get_waitlist_for_slot(admin_id, doctor_id, date, time_slot):
    """Get all waitlist entries for a specific slot, ordered by position."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM waitlist WHERE admin_id=? AND doctor_id=? AND date=? AND time_slot=? ORDER BY position",
        (admin_id, doctor_id, date, time_slot)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_waitlist(admin_id, doctor_id=None, date=None, time_slot=None):
    """General waitlist query with optional filters."""
    conn = get_db()
    q = "SELECT * FROM waitlist WHERE admin_id=?"
    params = [admin_id]
    if doctor_id:
        q += " AND doctor_id=?"; params.append(doctor_id)
    if date:
        q += " AND date=?"; params.append(date)
    if time_slot:
        q += " AND time_slot=?"; params.append(time_slot)
    q += " ORDER BY position"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_next_waiting_patient(admin_id, doctor_id, date, time_slot):
    """Get the first patient with status='waiting' for this slot."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM waitlist WHERE admin_id=? AND doctor_id=? AND date=? AND time_slot=? AND status='waiting' ORDER BY position LIMIT 1",
        (admin_id, doctor_id, date, time_slot)).fetchone()
    conn.close()
    return dict(row) if row else None


def notify_waitlist_patient(waitlist_id, confirm_deadline):
    """Set status='notified', notified_at=now, confirm_deadline=deadline."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE waitlist SET status='notified', notified_at=?, confirm_deadline=? WHERE id=?",
        (now, confirm_deadline, waitlist_id))
    conn.commit()
    conn.close()


def confirm_waitlist_patient(waitlist_id):
    """Set status='confirmed', confirmed_at=now."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE waitlist SET status='confirmed', confirmed_at=? WHERE id=?", (now, waitlist_id))
    conn.commit()
    conn.close()


def expire_waitlist_patient(waitlist_id):
    """Set status='expired', expired_at=now."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE waitlist SET status='expired', expired_at=? WHERE id=?", (now, waitlist_id))
    conn.commit()
    conn.close()


def get_active_waitlist_notifications():
    """Get all entries with status='notified' where confirm_deadline has passed."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT * FROM waitlist WHERE status='notified' AND confirm_deadline != '' AND confirm_deadline < ?",
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
           WHERE w.admin_id=?
           ORDER BY w.date, w.time_slot, w.position""",
        (admin_id,)).fetchall()
    conn.close()
    results = []
    now = datetime.now()
    for r in rows:
        entry = dict(r)
        if entry["status"] == "notified" and entry.get("confirm_deadline"):
            try:
                deadline = datetime.strptime(entry["confirm_deadline"], "%Y-%m-%d %H:%M:%S")
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
        "SELECT COUNT(*) as cnt FROM waitlist WHERE admin_id=? AND doctor_id=? AND date=? AND time_slot=? AND status='notified'",
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
        "SELECT COUNT(*) as cnt FROM waitlist WHERE admin_id=? AND doctor_id=? AND date=? AND time_slot=? AND status='waiting'",
        (admin_id, doctor_id, date, time_slot)).fetchone()
    conn.close()
    return row["cnt"]


def get_waitlist_entry(waitlist_id):
    """Get a single waitlist entry by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM waitlist WHERE id=?", (waitlist_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# Legacy aliases for backward compatibility
def confirm_waitlist(waitlist_id):
    return confirm_waitlist_patient(waitlist_id)

def expire_waitlist(waitlist_id):
    return expire_waitlist_patient(waitlist_id)

def get_next_waiting(admin_id, doctor_id, date, time_slot):
    return get_next_waiting_patient(admin_id, doctor_id, date, time_slot)


# ═══════════════ Feature 2: Patient Forms ═══════════════

def create_previsit_form(booking_id, admin_id, patient_name=None):
    """Generate a UUID token, create form record, return token."""
    token = secrets.token_urlsafe(32)
    conn = get_db()
    conn.execute(
        "INSERT INTO patient_forms (booking_id, admin_id, token, full_name) VALUES (?,?,?,?)",
        (booking_id, admin_id, token, patient_name or ""))
    conn.execute("UPDATE bookings SET form_token=? WHERE id=?", (token, booking_id))
    conn.commit()
    conn.close()
    return token


# Keep old name as alias for backward compatibility
create_patient_form = create_previsit_form


def get_form_by_token(token):
    """Get form data by token. Return None if token invalid."""
    conn = get_db()
    row = conn.execute("SELECT * FROM patient_forms WHERE token=?", (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


def submit_previsit_form(token, form_data):
    """Save all form fields, set submitted_at=now. Return False if already submitted."""
    conn = get_db()
    # Check if form exists and is not already submitted
    existing = conn.execute("SELECT id, submitted_at FROM patient_forms WHERE token=?", (token,)).fetchone()
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
                    full_name=?, date_of_birth=?, gender=?,
                    medical_history=?, medications=?, allergies=?,
                    insurance_provider=?, insurance_policy=?,
                    signature_data=?, submitted_at=?
                    WHERE token=?""",
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
    conn.execute("UPDATE bookings SET form_submitted=1 WHERE id=(SELECT booking_id FROM patient_forms WHERE token=?)", (token,))
    conn.commit()
    conn.close()
    return True


# Keep old name as alias for backward compatibility
submit_patient_form = submit_previsit_form


def is_form_submitted(token):
    """Check if form was already submitted."""
    conn = get_db()
    row = conn.execute("SELECT submitted_at FROM patient_forms WHERE token=?", (token,)).fetchone()
    conn.close()
    if not row:
        return False
    return bool(row["submitted_at"])


def get_form_for_booking(booking_id):
    """Get form data for a specific booking (for dashboard display)."""
    conn = get_db()
    row = conn.execute("SELECT * FROM patient_forms WHERE booking_id=?", (booking_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# Keep old name as alias for backward compatibility
get_form_by_booking = get_form_for_booking


def sync_form_to_patient(form_data, patient_id):
    """Copy form data (medical_history, allergies, medications, insurance) to patient profile."""
    conn = get_db()
    medical_history = form_data.get("medical_history", "")
    if isinstance(medical_history, (dict, list)):
        medical_history = json.dumps(medical_history)

    conn.execute("""UPDATE patients SET
        date_of_birth=COALESCE(NULLIF(?,''),(CASE WHEN date_of_birth='' THEN '' ELSE date_of_birth END)),
        gender=COALESCE(NULLIF(?,''),(CASE WHEN gender='' THEN '' ELSE gender END)),
        medical_history=?, medications=?, allergies=?,
        insurance_provider=?, insurance_policy=?,
        conditions=?
        WHERE id=?""",
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
    conn.execute("INSERT INTO recall_rules (admin_id, treatment_type, recall_days, message_template) VALUES (?,?,?,?)",
                 (admin_id, treatment_type, recall_days, message_template))
    conn.commit()
    conn.close()

def get_recall_rules(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM recall_rules WHERE admin_id=? ORDER BY treatment_type", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_recall_rule(rule_id, admin_id, **kwargs):
    conn = get_db()
    for k, v in kwargs.items():
        if k in ("treatment_type", "recall_days", "message_template", "is_active"):
            conn.execute(f"UPDATE recall_rules SET {k}=? WHERE id=? AND admin_id=?", (v, rule_id, admin_id))
    conn.commit()
    conn.close()

def delete_recall_rule(rule_id, admin_id):
    conn = get_db()
    conn.execute("DELETE FROM recall_rules WHERE id=? AND admin_id=?", (rule_id, admin_id))
    conn.commit()
    conn.close()

def add_recall_campaign(admin_id, rule_id, patient_name, patient_email="", patient_phone="", recall_type="appointment"):
    conn = get_db()
    conn.execute("INSERT INTO recall_campaigns (admin_id,rule_id,patient_name,patient_email,patient_phone,recall_type) VALUES (?,?,?,?,?,?)",
                 (admin_id, rule_id, patient_name, patient_email, patient_phone, recall_type))
    conn.commit()
    conn.close()

def get_recall_campaigns(admin_id, status=None):
    conn = get_db()
    q = "SELECT * FROM recall_campaigns WHERE admin_id=?"
    params = [admin_id]
    if status:
        q += " AND status=?"; params.append(status)
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_recall_stats(admin_id):
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM recall_campaigns WHERE admin_id=?", (admin_id,)).fetchone()["c"]
    sent = conn.execute("SELECT COUNT(*) as c FROM recall_campaigns WHERE admin_id=? AND status='sent'", (admin_id,)).fetchone()["c"]
    opened = conn.execute("SELECT COUNT(*) as c FROM recall_campaigns WHERE admin_id=? AND opened_at IS NOT NULL AND opened_at != ''", (admin_id,)).fetchone()["c"]
    booked = conn.execute("SELECT COUNT(*) as c FROM recall_campaigns WHERE admin_id=? AND booked_at IS NOT NULL AND booked_at != ''", (admin_id,)).fetchone()["c"]
    conn.close()
    return {"total": total, "sent": sent, "opened": opened, "booked": booked}


# ═══════════════ Feature 4: Missed Calls ═══════════════

def log_missed_call(admin_id, caller_number):
    conn = get_db()
    conn.execute("INSERT INTO missed_calls (admin_id, caller_number) VALUES (?,?)", (admin_id, caller_number))
    conn.commit()
    wid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return wid

def get_missed_calls(admin_id, limit=50):
    conn = get_db()
    rows = conn.execute("SELECT * FROM missed_calls WHERE admin_id=? ORDER BY call_time DESC LIMIT ?", (admin_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_missed_call(call_id, **kwargs):
    conn = get_db()
    for k, v in kwargs.items():
        if k in ("reply_sent", "reply_method", "subsequently_booked", "booking_id"):
            conn.execute(f"UPDATE missed_calls SET {k}=? WHERE id=?", (v, call_id))
    conn.commit()
    conn.close()


# ═══════════════ Feature 5: Treatment Follow-Up ═══════════════

def create_treatment_followup(admin_id, doctor_id, patient_name, treatment_name, patient_email="", patient_phone=""):
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d")
    for day in [2, 5, 10]:
        conn.execute("INSERT INTO treatment_followups (admin_id,doctor_id,patient_name,patient_email,patient_phone,treatment_name,recommended_date,followup_day) VALUES (?,?,?,?,?,?,?,?)",
                     (admin_id, doctor_id, patient_name, patient_email, patient_phone, treatment_name, now, day))
    conn.commit()
    conn.close()

def get_treatment_followups(admin_id, status=None):
    conn = get_db()
    q = "SELECT * FROM treatment_followups WHERE admin_id=?"
    params = [admin_id]
    if status:
        q += " AND status=?"; params.append(status)
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def cancel_treatment_followups(admin_id, patient_name, treatment_name):
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE treatment_followups SET status='cancelled', cancelled_at=? WHERE admin_id=? AND patient_name=? AND treatment_name=? AND status='pending'",
                 (now, admin_id, patient_name, treatment_name))
    conn.commit()
    conn.close()

def get_due_followups():
    """Get all followups that are due to be sent today."""
    conn = get_db()
    rows = conn.execute("""SELECT * FROM treatment_followups WHERE status='pending'
                           AND date(recommended_date, '+' || followup_day || ' days') <= date('now')""").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════ Feature 7: Gallery ═══════════════

def add_gallery_image(admin_id, treatment_type, image_url, image_type="after", pair_id="", caption=""):
    conn = get_db()
    order = conn.execute("SELECT MAX(sort_order) as mx FROM gallery WHERE admin_id=? AND treatment_type=?", (admin_id, treatment_type)).fetchone()["mx"] or 0
    conn.execute("INSERT INTO gallery (admin_id,treatment_type,image_url,image_type,pair_id,caption,sort_order) VALUES (?,?,?,?,?,?,?)",
                 (admin_id, treatment_type, image_url, image_type, pair_id, caption, order + 1))
    conn.commit()
    conn.close()

def get_gallery(admin_id, treatment_type=None):
    conn = get_db()
    if treatment_type:
        rows = conn.execute("SELECT * FROM gallery WHERE admin_id=? AND treatment_type=? ORDER BY sort_order", (admin_id, treatment_type)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM gallery WHERE admin_id=? ORDER BY treatment_type, sort_order", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_gallery_image(image_id, admin_id):
    conn = get_db()
    conn.execute("DELETE FROM gallery WHERE id=? AND admin_id=?", (image_id, admin_id))
    conn.commit()
    conn.close()


# ═══════════════ Feature 10: Live Chat Handoff ═══════════════

def create_handoff(admin_id, session_id, patient_name="", reason="", ai_confidence=0):
    conn = get_db()
    conn.execute("INSERT INTO live_chat_handoffs (admin_id,session_id,patient_name,reason,ai_confidence) VALUES (?,?,?,?,?)",
                 (admin_id, session_id, patient_name, reason, ai_confidence))
    conn.commit()
    hid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return hid

def get_handoff_queue(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM live_chat_handoffs WHERE admin_id=? AND status IN ('queued','assigned') ORDER BY created_at", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def assign_handoff(handoff_id, staff_user_id, staff_name):
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE live_chat_handoffs SET status='assigned', staff_user_id=?, staff_name=?, assigned_at=? WHERE id=?",
                 (staff_user_id, staff_name, now, handoff_id))
    conn.commit()
    conn.close()

def resolve_handoff(handoff_id, notes=""):
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE live_chat_handoffs SET status='resolved', resolved_at=?, resolution_notes=? WHERE id=?",
                 (now, notes, handoff_id))
    conn.commit()
    conn.close()

def get_handoff_by_session(session_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM live_chat_handoffs WHERE session_id=? AND status IN ('queued','assigned') ORDER BY created_at DESC LIMIT 1", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


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
    conn.execute(
        """INSERT INTO schedule_blocks
           (admin_id, doctor_id, block_type, start_date, end_date,
            start_time, end_time, recurring_pattern, recurring_day, label, is_active)
           VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
        (admin_id, doctor_id, block_type, start_date,
         end_date or start_date, start_time or "", end_time or "",
         recurring_pattern or "", recurring_day, label or ""))
    conn.commit()
    bid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return bid


def get_schedule_blocks(admin_id, doctor_id=None):
    """Get all active blocks for an admin (optionally filtered by doctor)."""
    conn = get_db()
    if doctor_id is not None:
        rows = conn.execute(
            """SELECT * FROM schedule_blocks
               WHERE admin_id=? AND is_active=1
               AND (doctor_id=? OR doctor_id IS NULL)
               ORDER BY start_date""",
            (admin_id, doctor_id)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM schedule_blocks WHERE admin_id=? AND is_active=1 ORDER BY start_date",
            (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_schedule_block(block_id, admin_id=None):
    """Delete a single block (or single occurrence of a recurring block)."""
    conn = get_db()
    if admin_id is not None:
        conn.execute("DELETE FROM schedule_blocks WHERE id=? AND admin_id=?", (block_id, admin_id))
    else:
        conn.execute("DELETE FROM schedule_blocks WHERE id=?", (block_id,))
    conn.commit()
    conn.close()


def delete_recurring_series(block_id):
    """Delete all occurrences of a recurring block series.
    Uses the block's attributes to find siblings with the same pattern."""
    conn = get_db()
    row = conn.execute("SELECT * FROM schedule_blocks WHERE id=?", (block_id,)).fetchone()
    if row:
        conn.execute(
            """DELETE FROM schedule_blocks
               WHERE admin_id=? AND doctor_id IS ? AND block_type='recurring'
               AND recurring_pattern=? AND recurring_day IS ?
               AND label=?""",
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
           WHERE admin_id=? AND is_active=1
           AND (doctor_id IS NULL OR doctor_id=?)""",
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
           WHERE admin_id=? AND is_active=1
           AND (doctor_id IS NULL OR doctor_id=?)
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
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id=? AND date=? AND doctor_id=? AND status='confirmed'",
            (admin_id, date_str, doctor_id)).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM bookings WHERE admin_id=? AND date=? AND status='confirmed'",
            (admin_id, date_str)).fetchone()
    conn.close()
    return row["c"] if row else 0


# ═══════════════ Feature 12: Promotions ═══════════════

def create_promotion(admin_id, code, discount_type, discount_value, applicable_treatments="all", expiry_date="", max_uses=0, min_booking_value=0):
    conn = get_db()
    conn.execute("INSERT INTO promotions (admin_id,code,discount_type,discount_value,applicable_treatments,expiry_date,max_uses,min_booking_value) VALUES (?,?,?,?,?,?,?,?)",
                 (admin_id, code, discount_type, discount_value, applicable_treatments, expiry_date, max_uses, min_booking_value))
    conn.commit()
    pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return pid

def validate_promotion(code, admin_id, treatment="", booking_value=0):
    conn = get_db()
    row = conn.execute("SELECT * FROM promotions WHERE code=? AND admin_id=? AND is_active=1", (code, admin_id)).fetchone()
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
    conn.execute("INSERT INTO promotion_usage (promotion_id,booking_id,patient_name,patient_email,discount_amount,original_amount) VALUES (?,?,?,?,?,?)",
                 (promotion_id, booking_id, patient_name, patient_email, discount_amount, original_amount))
    conn.execute("UPDATE promotions SET current_uses = current_uses + 1 WHERE id=?", (promotion_id,))
    conn.commit()
    conn.close()

def get_promotions(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM promotions WHERE admin_id=? ORDER BY created_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_promotion_stats(admin_id):
    conn = get_db()
    rows = conn.execute("""SELECT p.*, COUNT(pu.id) as total_uses, SUM(pu.discount_amount) as total_discount, SUM(pu.original_amount) as total_revenue
                           FROM promotions p LEFT JOIN promotion_usage pu ON p.id = pu.promotion_id
                           WHERE p.admin_id=? GROUP BY p.id ORDER BY p.created_at DESC""", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_promotion(promo_id, admin_id):
    conn = get_db()
    conn.execute("UPDATE promotions SET is_active=0 WHERE id=? AND admin_id=?", (promo_id, admin_id))
    conn.commit()
    conn.close()


# ═══════════════ Feature 14: Referrals ═══════════════

def create_referral_code(admin_id):
    code = "REF-" + secrets.token_hex(4).upper()
    conn = get_db()
    conn.execute("UPDATE users SET referral_code=? WHERE id=?", (code, admin_id))
    conn.commit()
    conn.close()
    return code

def get_referral_by_code(code):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE referral_code=?", (code,)).fetchone()
    conn.close()
    return dict(row) if row else None

def track_referral(referrer_admin_id, referred_email, referral_code):
    conn = get_db()
    conn.execute("INSERT INTO referrals (referrer_admin_id, referred_email, referral_code) VALUES (?,?,?)",
                 (referrer_admin_id, referred_email, referral_code))
    conn.commit()
    conn.close()

def get_referrals(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM referrals WHERE referrer_admin_id=? ORDER BY created_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def convert_referral(referred_admin_id, referral_code):
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE referrals SET referred_admin_id=?, status='converted', converted_at=? WHERE referral_code=? AND status='pending'",
                 (referred_admin_id, now, referral_code))
    conn.commit()
    conn.close()


# ═══════════════ Feature 15: Patient Profiles ═══════════════

def get_or_create_patient(admin_id, name="", email="", phone="", increment_booking=True):
    conn = get_db()
    # Try to find by phone or email
    row = None
    if phone:
        row = conn.execute("SELECT * FROM patients WHERE admin_id=? AND phone=?", (admin_id, phone)).fetchone()
    if not row and email:
        row = conn.execute("SELECT * FROM patients WHERE admin_id=? AND email=?", (admin_id, email)).fetchone()
    if row:
        # Update name if provided
        if name and not row["name"]:
            conn.execute("UPDATE patients SET name=? WHERE id=?", (name, row["id"]))
        # Increment booking count
        if increment_booking:
            conn.execute("UPDATE patients SET total_bookings=total_bookings+1 WHERE id=?", (row["id"],))
        conn.commit()
        row = conn.execute("SELECT * FROM patients WHERE id=?", (row["id"],)).fetchone()
        conn.close()
        return dict(row)
    # Create new patient
    conn.execute("INSERT INTO patients (admin_id,name,email,phone,total_bookings) VALUES (?,?,?,?,?)",
                 (admin_id, name, email, phone, 1 if increment_booking else 0))
    conn.commit()
    pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    row = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_patient(patient_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_patients(admin_id, search=""):
    conn = get_db()
    if search:
        rows = conn.execute("SELECT * FROM patients WHERE admin_id=? AND (name LIKE ? OR email LIKE ? OR phone LIKE ?) ORDER BY name",
                            (admin_id, f"%{search}%", f"%{search}%", f"%{search}%")).fetchall()
    else:
        rows = conn.execute("SELECT * FROM patients WHERE admin_id=? ORDER BY name", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_patient_history(patient_id):
    conn = get_db()
    bookings = conn.execute("SELECT * FROM bookings WHERE patient_id=? ORDER BY date DESC", (patient_id,)).fetchall()
    forms = conn.execute("SELECT pf.* FROM patient_forms pf JOIN bookings b ON pf.booking_id=b.id WHERE b.patient_id=?", (patient_id,)).fetchall()
    notes = conn.execute("SELECT * FROM patient_notes WHERE patient_id=? ORDER BY created_at DESC", (patient_id,)).fetchall()
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
            conn.execute(f"UPDATE patients SET {k}=? WHERE id=?", (v, patient_id))
    conn.commit()
    conn.close()

def add_patient_note(patient_id, doctor_id, note, booking_id=0):
    conn = get_db()
    conn.execute("INSERT INTO patient_notes (patient_id,doctor_id,booking_id,note) VALUES (?,?,?,?)",
                 (patient_id, doctor_id, booking_id, note))
    conn.commit()
    conn.close()


# ═══════════════ Feature 17: A/B Testing ═══════════════

def create_ab_test(admin_id, test_name, test_type, variant_a, variant_b):
    conn = get_db()
    conn.execute("INSERT INTO ab_tests (admin_id,test_name,test_type,variant_a,variant_b) VALUES (?,?,?,?,?)",
                 (admin_id, test_name, test_type, variant_a, variant_b))
    conn.commit()
    tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return tid

def get_ab_tests(admin_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM ab_tests WHERE admin_id=? ORDER BY created_at DESC", (admin_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_active_ab_test(admin_id, test_type):
    conn = get_db()
    row = conn.execute("SELECT * FROM ab_tests WHERE admin_id=? AND test_type=? AND status='running' ORDER BY created_at DESC LIMIT 1",
                       (admin_id, test_type)).fetchone()
    conn.close()
    return dict(row) if row else None

def increment_ab_test(test_id, variant, booked=False):
    conn = get_db()
    if variant == "a":
        conn.execute("UPDATE ab_tests SET variant_a_conversations = variant_a_conversations + 1 WHERE id=?", (test_id,))
        if booked:
            conn.execute("UPDATE ab_tests SET variant_a_bookings = variant_a_bookings + 1 WHERE id=?", (test_id,))
    else:
        conn.execute("UPDATE ab_tests SET variant_b_conversations = variant_b_conversations + 1 WHERE id=?", (test_id,))
        if booked:
            conn.execute("UPDATE ab_tests SET variant_b_bookings = variant_b_bookings + 1 WHERE id=?", (test_id,))
    conn.commit()
    conn.close()

def end_ab_test(test_id, winner):
    conn = get_db()
    conn.execute("UPDATE ab_tests SET status='completed', winner=? WHERE id=?", (winner, test_id))
    conn.commit()
    conn.close()


# ═══════════════ Feature 18: Loyalty Program ═══════════════

def get_loyalty_config(admin_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM loyalty_config WHERE admin_id=?", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def save_loyalty_config(admin_id, **kwargs):
    conn = get_db()
    existing = conn.execute("SELECT id FROM loyalty_config WHERE admin_id=?", (admin_id,)).fetchone()
    if existing:
        for k, v in kwargs.items():
            if k in ("points_per_appointment","points_per_referral","points_per_review","points_per_form","redemption_value","is_active"):
                conn.execute(f"UPDATE loyalty_config SET {k}=? WHERE admin_id=?", (v, admin_id))
    else:
        conn.execute("INSERT INTO loyalty_config (admin_id) VALUES (?)", (admin_id,))
        for k, v in kwargs.items():
            if k in ("points_per_appointment","points_per_referral","points_per_review","points_per_form","redemption_value","is_active"):
                conn.execute(f"UPDATE loyalty_config SET {k}=? WHERE admin_id=?", (v, admin_id))
    conn.commit()
    conn.close()

def add_loyalty_points(patient_id, admin_id, points, action, description="", booking_id=0):
    conn = get_db()
    conn.execute("INSERT INTO loyalty_transactions (patient_id,admin_id,points,action,description,booking_id) VALUES (?,?,?,?,?,?)",
                 (patient_id, admin_id, points, action, description, booking_id))
    conn.execute("UPDATE patients SET loyalty_points = loyalty_points + ? WHERE id=?", (points, patient_id))
    conn.commit()
    conn.close()

def redeem_loyalty_points(patient_id, admin_id, points, description="", booking_id=0):
    conn = get_db()
    patient = conn.execute("SELECT loyalty_points FROM patients WHERE id=?", (patient_id,)).fetchone()
    if not patient or patient["loyalty_points"] < points:
        conn.close()
        return False, "Insufficient loyalty points."
    conn.execute("INSERT INTO loyalty_transactions (patient_id,admin_id,points,action,description,booking_id) VALUES (?,?,?,?,?,?)",
                 (patient_id, admin_id, -points, "redeem", description, booking_id))
    conn.execute("UPDATE patients SET loyalty_points = loyalty_points - ? WHERE id=?", (points, patient_id))
    conn.commit()
    conn.close()
    return True, "Points redeemed successfully."

def get_loyalty_stats(admin_id):
    conn = get_db()
    now = datetime.now()
    month_start = now.strftime("%Y-%m-01")
    total_members = conn.execute("SELECT COUNT(*) as c FROM patients WHERE admin_id=? AND loyalty_points > 0", (admin_id,)).fetchone()["c"]
    issued = conn.execute("SELECT COALESCE(SUM(points),0) as s FROM loyalty_transactions WHERE admin_id=? AND points>0 AND created_at>=?", (admin_id, month_start)).fetchone()["s"]
    redeemed = conn.execute("SELECT COALESCE(SUM(ABS(points)),0) as s FROM loyalty_transactions WHERE admin_id=? AND points<0 AND created_at>=?", (admin_id, month_start)).fetchone()["s"]
    top = conn.execute("SELECT p.name, p.loyalty_points FROM patients p WHERE p.admin_id=? AND p.loyalty_points>0 ORDER BY p.loyalty_points DESC LIMIT 10", (admin_id,)).fetchall()
    conn.close()
    return {"total_members": total_members, "issued_this_month": issued, "redeemed_this_month": redeemed, "top_patients": [dict(r) for r in top]}


# ═══════════════ Feature 19: GMB ═══════════════

def save_gmb_connection(admin_id, **kwargs):
    conn = get_db()
    existing = conn.execute("SELECT id FROM gmb_connections WHERE admin_id=?", (admin_id,)).fetchone()
    if existing:
        for k, v in kwargs.items():
            if k in ("google_account_id","location_id","access_token","refresh_token","rating","review_count","last_synced_at"):
                conn.execute(f"UPDATE gmb_connections SET {k}=? WHERE admin_id=?", (v, admin_id))
    else:
        conn.execute("INSERT INTO gmb_connections (admin_id) VALUES (?)", (admin_id,))
        for k, v in kwargs.items():
            if k in ("google_account_id","location_id","access_token","refresh_token","rating","review_count","last_synced_at"):
                conn.execute(f"UPDATE gmb_connections SET {k}=? WHERE admin_id=?", (v, admin_id))
    conn.commit()
    conn.close()

def get_gmb_connection(admin_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM gmb_connections WHERE admin_id=?", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ═══════════════ Feature 20: Benchmarking ═══════════════

def update_clinic_metrics(admin_id, **kwargs):
    conn = get_db()
    existing = conn.execute("SELECT id FROM clinic_metrics_cache WHERE admin_id=?", (admin_id,)).fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if existing:
        for k, v in kwargs.items():
            if k in ("conversion_rate","noshow_rate","avg_response_time","monthly_bookings","review_score","city"):
                conn.execute(f"UPDATE clinic_metrics_cache SET {k}=?, updated_at=? WHERE admin_id=?", (v, now, admin_id))
    else:
        conn.execute("INSERT INTO clinic_metrics_cache (admin_id, updated_at) VALUES (?,?)", (admin_id, now))
        for k, v in kwargs.items():
            if k in ("conversion_rate","noshow_rate","avg_response_time","monthly_bookings","review_score","city"):
                conn.execute(f"UPDATE clinic_metrics_cache SET {k}=?, updated_at=? WHERE admin_id=?", (v, now, admin_id))
    conn.commit()
    conn.close()

def get_benchmark_data(admin_id):
    conn = get_db()
    my = conn.execute("SELECT * FROM clinic_metrics_cache WHERE admin_id=?", (admin_id,)).fetchone()
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
                                SELECT * FROM clinic_metrics_cache ORDER BY monthly_bookings DESC LIMIT MAX(1, (SELECT COUNT(*)/10 FROM clinic_metrics_cache))
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
    conn.execute("""INSERT INTO customers
        (business_name, owner_name, email, phone, website, country, city, address, industry,
         plan, api_key, api_secret, verification_token, status, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (business_name, owner_name, email,
         kwargs.get("phone",""), kwargs.get("website",""),
         kwargs.get("country",""), kwargs.get("city",""),
         kwargs.get("address",""), kwargs.get("industry","dental"),
         kwargs.get("plan","free_trial"), api_key, api_secret,
         verification_token, "pending", now))
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return cid


def get_customer(customer_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_customer_by_email(email):
    conn = get_db()
    row = conn.execute("SELECT * FROM customers WHERE email=?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_customer_by_api_key(api_key):
    conn = get_db()
    row = conn.execute("SELECT * FROM customers WHERE api_key=? AND status='active'", (api_key,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_customers(status=None):
    conn = get_db()
    if status:
        rows = conn.execute("SELECT * FROM customers WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM customers ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_customer(customer_id, **kwargs):
    conn = get_db()
    allowed = ("business_name","owner_name","email","phone","website","country","city",
               "address","industry","logo_url","plan","plan_expires_at","billing_cycle",
               "stripe_customer_id","stripe_subscription_id","is_verified","status",
               "webhook_url","allowed_domains","chatbot_name","chatbot_color",
               "chatbot_position","chatbot_language","chatbot_welcome_msg",
               "max_admins","max_doctors","max_monthly_chats","max_bookings",
               "head_admin_user_id","last_active_at")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for k, v in kwargs.items():
        if k in allowed:
            conn.execute(f"UPDATE customers SET {k}=?, updated_at=? WHERE id=?", (v, now, customer_id))
    conn.commit()
    conn.close()


def verify_customer(customer_id):
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE customers SET is_verified=1, verified_at=?, status='active', updated_at=? WHERE id=?",
                 (now, now, customer_id))
    conn.commit()
    conn.close()


def verify_customer_by_token(token):
    conn = get_db()
    row = conn.execute("SELECT id FROM customers WHERE verification_token=?", (token,)).fetchone()
    if not row:
        conn.close()
        return None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE customers SET is_verified=1, verified_at=?, status='active', verification_token='', updated_at=? WHERE id=?",
                 (now, now, row["id"]))
    conn.commit()
    conn.close()
    return row["id"]


def delete_customer(customer_id):
    conn = get_db()
    conn.execute("DELETE FROM customers WHERE id=?", (customer_id,))
    conn.commit()
    conn.close()


def regenerate_customer_api_key(customer_id):
    conn = get_db()
    new_key = secrets.token_urlsafe(32)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE customers SET api_key=?, updated_at=? WHERE id=?", (new_key, now, customer_id))
    conn.commit()
    conn.close()
    return new_key


def track_customer_usage(customer_id, chats=0, bookings=0, leads=0, api_calls=0):
    conn = get_db()
    month = datetime.now().strftime("%Y-%m")
    existing = conn.execute("SELECT id FROM customer_usage WHERE customer_id=? AND month=?", (customer_id, month)).fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if existing:
        conn.execute("""UPDATE customer_usage SET
            total_chats=total_chats+?, total_bookings=total_bookings+?,
            total_leads=total_leads+?, total_api_calls=total_api_calls+?, updated_at=?
            WHERE customer_id=? AND month=?""",
            (chats, bookings, leads, api_calls, now, customer_id, month))
    else:
        conn.execute("""INSERT INTO customer_usage (customer_id, month, total_chats, total_bookings, total_leads, total_api_calls, updated_at)
            VALUES (?,?,?,?,?,?,?)""", (customer_id, month, chats, bookings, leads, api_calls, now))
    conn.commit()
    conn.close()


def get_customer_usage(customer_id, month=None):
    conn = get_db()
    if not month:
        month = datetime.now().strftime("%Y-%m")
    row = conn.execute("SELECT * FROM customer_usage WHERE customer_id=? AND month=?", (customer_id, month)).fetchone()
    conn.close()
    return dict(row) if row else {"total_chats": 0, "total_bookings": 0, "total_leads": 0, "total_api_calls": 0}


def create_customer_invoice(customer_id, amount, currency="USD", period_start="", period_end=""):
    conn = get_db()
    inv_num = f"INV-{customer_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    conn.execute("""INSERT INTO customer_invoices
        (customer_id, invoice_number, amount, currency, period_start, period_end)
        VALUES (?,?,?,?,?,?)""", (customer_id, inv_num, amount, currency, period_start, period_end))
    conn.commit()
    conn.close()
    return inv_num


def get_customer_invoices(customer_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM customer_invoices WHERE customer_id=? ORDER BY created_at DESC", (customer_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Smart Appointment Reminders ──────────────────────────────────────────────

def create_appointment_reminder(booking_id, admin_id, reminder_type, scheduled_for, job_id=""):
    """Insert a reminder row and return its id."""
    conn = get_db()
    conn.execute(
        """INSERT INTO appointment_reminders
           (booking_id, admin_id, reminder_type, scheduled_for, job_id)
           VALUES (?, ?, ?, ?, ?)""",
        (booking_id, admin_id, reminder_type, scheduled_for, job_id),
    )
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return rid


def get_reminders_for_booking(booking_id):
    """Return all reminders for a booking."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM appointment_reminders WHERE booking_id = ? ORDER BY scheduled_for",
        (booking_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_reminder_status(reminder_id, status, sent_at=None):
    """Update the status of a reminder."""
    conn = get_db()
    if sent_at:
        conn.execute(
            "UPDATE appointment_reminders SET status = ?, sent_at = ? WHERE id = ?",
            (status, sent_at, reminder_id),
        )
    else:
        conn.execute(
            "UPDATE appointment_reminders SET status = ? WHERE id = ?",
            (status, reminder_id),
        )
    conn.commit()
    conn.close()


def update_reminder_tokens(reminder_id, confirm_token, cancel_token):
    """Store confirm/cancel tokens on a reminder."""
    conn = get_db()
    conn.execute(
        "UPDATE appointment_reminders SET confirm_token = ?, cancel_token = ? WHERE id = ?",
        (confirm_token, cancel_token, reminder_id),
    )
    conn.commit()
    conn.close()


def get_reminder_by_token(token):
    """Look up a reminder by its confirm or cancel token."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM appointment_reminders WHERE confirm_token = ? OR cancel_token = ?",
        (token, token),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def record_reminder_response(reminder_id, response):
    """Record confirmed/cancelled response with timestamp."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE appointment_reminders SET patient_response = ?, responded_at = ? WHERE id = ?",
        (response, now, reminder_id),
    )
    conn.commit()
    conn.close()


def get_pending_reminders():
    """Return reminders where status='pending' and scheduled_for <= now."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT * FROM appointment_reminders WHERE status = 'pending' AND scheduled_for <= ?",
        (now,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cancel_reminders_for_booking(booking_id):
    """Set status='skipped' for all pending reminders of a booking."""
    conn = get_db()
    conn.execute(
        "UPDATE appointment_reminders SET status = 'skipped' WHERE booking_id = ? AND status = 'pending'",
        (booking_id,),
    )
    conn.commit()
    conn.close()


def get_reminder_config(admin_id):
    """Return config for an admin, or sensible defaults."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM reminder_config WHERE admin_id = ?", (admin_id,)
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
    }


def save_reminder_config(admin_id, **kwargs):
    """Upsert reminder config for an admin."""
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM reminder_config WHERE admin_id = ?", (admin_id,)
    ).fetchone()
    if existing:
        sets = []
        vals = []
        for k, v in kwargs.items():
            sets.append(f"{k} = ?")
            vals.append(v)
        if sets:
            vals.append(admin_id)
            conn.execute(
                f"UPDATE reminder_config SET {', '.join(sets)} WHERE admin_id = ?",
                tuple(vals),
            )
    else:
        cols = ["admin_id"] + list(kwargs.keys())
        placeholders = ", ".join(["?"] * len(cols))
        vals = [admin_id] + list(kwargs.values())
        conn.execute(
            f"INSERT INTO reminder_config ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(vals),
        )
    conn.commit()
    conn.close()


def get_todays_confirmation_stats(admin_id):
    """Return {total, confirmed, at_risk, pending} for today's bookings."""
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    # Get all active bookings for today
    bookings = conn.execute(
        "SELECT id FROM bookings WHERE admin_id = ? AND date = ? AND status != 'cancelled'",
        (admin_id, today),
    ).fetchall()
    booking_ids = [b["id"] for b in bookings]
    total = len(booking_ids)
    confirmed = 0
    at_risk = 0
    pending = 0
    for bid in booking_ids:
        reminder = conn.execute(
            "SELECT patient_response FROM appointment_reminders WHERE booking_id = ? AND patient_response = 'confirmed' LIMIT 1",
            (bid,),
        ).fetchone()
        if reminder:
            confirmed += 1
        else:
            # Check if any reminder was sent but no response
            sent = conn.execute(
                "SELECT id FROM appointment_reminders WHERE booking_id = ? AND status = 'sent' AND patient_response = 'none' LIMIT 1",
                (bid,),
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
            strftime('%%Y-%%W', scheduled_for) as week,
            COUNT(*) as total_sent,
            SUM(CASE WHEN patient_response = 'confirmed' THEN 1 ELSE 0 END) as confirmed,
            SUM(CASE WHEN patient_response = 'cancelled' THEN 1 ELSE 0 END) as cancelled,
            SUM(CASE WHEN patient_response = 'none' AND status = 'sent' THEN 1 ELSE 0 END) as no_response
        FROM appointment_reminders
        WHERE admin_id = ? AND scheduled_for >= ? AND scheduled_for <= ?
        GROUP BY week ORDER BY week""",
        (admin_id, date_from, date_to),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_reminder_by_id(reminder_id):
    """Return a single reminder by id."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM appointment_reminders WHERE id = ?", (reminder_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ─── Survey DB Helpers ───────────────────────────────────────────────

def create_survey(admin_id, booking_id, patient_id, doctor_id, token, treatment_type=""):
    """Create a new survey record."""
    conn = get_db()
    conn.execute(
        """INSERT INTO surveys (admin_id, booking_id, patient_id, doctor_id, token, treatment_type)
           VALUES (?,?,?,?,?,?)""",
        (admin_id, booking_id, patient_id, doctor_id, token, treatment_type),
    )
    conn.commit()
    survey_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return survey_id


def get_survey_by_token(token):
    """Get a survey by its unique token."""
    conn = get_db()
    row = conn.execute("SELECT * FROM surveys WHERE token = ?", (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


def submit_survey_response(token, star_rating, feedback_text="", google_review_clicked=0):
    """Record a survey response."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """UPDATE surveys SET star_rating=?, feedback_text=?, completed_at=?,
           google_review_clicked=? WHERE token=?""",
        (star_rating, feedback_text, now, google_review_clicked, token),
    )
    conn.commit()
    conn.close()


def get_survey_analytics_db(admin_id, date_from=None, date_to=None):
    """Get survey analytics data for an admin."""
    conn = get_db()
    params = [admin_id]
    date_filter = ""
    if date_from:
        date_filter += " AND completed_at >= ?"
        params.append(date_from)
    if date_to:
        date_filter += " AND completed_at <= ?"
        params.append(date_to)

    # Overall stats
    stats = conn.execute(
        f"""SELECT COUNT(*) as total_surveys,
            SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END) as completed,
            AVG(CASE WHEN star_rating IS NOT NULL THEN star_rating END) as avg_rating,
            SUM(CASE WHEN google_review_clicked = 1 THEN 1 ELSE 0 END) as google_clicks
        FROM surveys WHERE admin_id = ? {date_filter}""",
        params,
    ).fetchone()
    stats = dict(stats) if stats else {}

    # Per-doctor averages
    doctor_stats = conn.execute(
        f"""SELECT doctor_id, AVG(star_rating) as avg_rating, COUNT(*) as total
        FROM surveys WHERE admin_id = ? AND star_rating IS NOT NULL {date_filter}
        GROUP BY doctor_id""",
        params,
    ).fetchall()

    # Per-treatment averages
    treatment_stats = conn.execute(
        f"""SELECT treatment_type, AVG(star_rating) as avg_rating, COUNT(*) as total
        FROM surveys WHERE admin_id = ? AND star_rating IS NOT NULL AND treatment_type != '' {date_filter}
        GROUP BY treatment_type""",
        params,
    ).fetchall()

    # Trend data (weekly)
    trend = conn.execute(
        f"""SELECT strftime('%Y-%W', completed_at) as week, AVG(star_rating) as avg_rating, COUNT(*) as total
        FROM surveys WHERE admin_id = ? AND completed_at IS NOT NULL {date_filter}
        GROUP BY week ORDER BY week""",
        params,
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
        """SELECT * FROM surveys WHERE admin_id = ? AND star_rating IS NOT NULL AND star_rating <= 3
           ORDER BY completed_at DESC""",
        (admin_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_survey_config(admin_id):
    """Get survey configuration for an admin."""
    conn = get_db()
    row = conn.execute("SELECT * FROM survey_config WHERE admin_id = ?", (admin_id,)).fetchone()
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
    existing = conn.execute("SELECT id FROM survey_config WHERE admin_id = ?", (admin_id,)).fetchone()
    if existing:
        conn.execute(
            """UPDATE survey_config SET auto_send_enabled=?, send_delay_hours=?,
               google_review_url=?, min_rating_for_review=? WHERE admin_id=?""",
            (auto_send_enabled, send_delay_hours, google_review_url, min_rating_for_review, admin_id),
        )
    else:
        conn.execute(
            """INSERT INTO survey_config (admin_id, auto_send_enabled, send_delay_hours, google_review_url, min_rating_for_review)
               VALUES (?,?,?,?,?)""",
            (admin_id, auto_send_enabled, send_delay_hours, google_review_url, min_rating_for_review),
        )
    conn.commit()
    conn.close()


# ─── Package DB Helpers ──────────────────────────────────────────────

def create_package_db(admin_id, name, description, treatments_json, package_price, individual_total, savings, validity_days=90, max_redemptions=0):
    """Create a new treatment package."""
    conn = get_db()
    conn.execute(
        """INSERT INTO treatment_packages
           (admin_id, name, description, treatments_json, package_price, individual_total, savings, validity_days, max_redemptions)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (admin_id, name, description, treatments_json, package_price, individual_total, savings, validity_days, max_redemptions),
    )
    conn.commit()
    pkg_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return pkg_id


def get_packages_db(admin_id, active_only=True):
    """Get all treatment packages for an admin."""
    conn = get_db()
    if active_only:
        rows = conn.execute(
            "SELECT * FROM treatment_packages WHERE admin_id = ? AND is_active = 1 ORDER BY created_at DESC",
            (admin_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM treatment_packages WHERE admin_id = ? ORDER BY created_at DESC",
            (admin_id,),
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
            sets.append(f"{k} = ?")
            vals.append(v)
    if sets:
        vals.append(package_id)
        conn.execute(f"UPDATE treatment_packages SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()
    conn.close()


def get_package_by_id(package_id):
    """Get a single package by id."""
    conn = get_db()
    row = conn.execute("SELECT * FROM treatment_packages WHERE id = ?", (package_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def redeem_package_db(package_id, patient_id, booking_id, treatment_name):
    """Record a package redemption."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO package_redemptions (package_id, patient_id, booking_id, treatment_name, redeemed_at) VALUES (?,?,?,?,?)",
        (package_id, patient_id, booking_id, treatment_name, now),
    )
    conn.execute("UPDATE treatment_packages SET current_redemptions = current_redemptions + 1 WHERE id = ?", (package_id,))
    conn.commit()
    redemption_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return redemption_id


def get_package_analytics_db(admin_id):
    """Get analytics for all packages for an admin."""
    conn = get_db()
    packages = conn.execute(
        "SELECT * FROM treatment_packages WHERE admin_id = ? ORDER BY created_at DESC", (admin_id,)
    ).fetchall()
    result = []
    for p in packages:
        p = dict(p)
        redemptions = conn.execute(
            "SELECT COUNT(*) as total_redemptions FROM package_redemptions WHERE package_id = ?",
            (p["id"],),
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
    conn.execute(
        """INSERT INTO upsell_rules
           (admin_id, trigger_treatment, suggested_treatment, suggested_package_id, message_template, discount_percent, priority)
           VALUES (?,?,?,?,?,?,?)""",
        (admin_id, trigger_treatment, suggested_treatment, suggested_package_id, message_template, discount_percent, priority),
    )
    conn.commit()
    rule_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return rule_id


def get_upsell_rules(admin_id, trigger_treatment=None):
    """Get upsell rules, optionally filtered by trigger treatment."""
    conn = get_db()
    if trigger_treatment:
        rows = conn.execute(
            """SELECT * FROM upsell_rules WHERE admin_id = ? AND is_active = 1
               AND LOWER(trigger_treatment) = LOWER(?) ORDER BY priority DESC""",
            (admin_id, trigger_treatment),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM upsell_rules WHERE admin_id = ? AND is_active = 1 ORDER BY priority DESC",
            (admin_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_upsell_impression(upsell_rule_id, session_id):
    """Record that an upsell was shown."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO upsell_impressions (upsell_rule_id, session_id, shown_at) VALUES (?,?,?)",
        (upsell_rule_id, session_id, now),
    )
    conn.commit()
    impression_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return impression_id


def record_upsell_acceptance(impression_id, booking_id):
    """Record that an upsell was accepted."""
    conn = get_db()
    conn.execute(
        "UPDATE upsell_impressions SET accepted = 1, booking_id = ? WHERE id = ?",
        (booking_id, impression_id),
    )
    conn.commit()
    conn.close()


def get_upsell_impressions_for_session(session_id):
    """Get all upsell impressions for a session."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM upsell_impressions WHERE session_id = ?", (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_upsell_analytics_db(admin_id):
    """Get upsell analytics per rule."""
    conn = get_db()
    rules = conn.execute(
        "SELECT * FROM upsell_rules WHERE admin_id = ?", (admin_id,)
    ).fetchall()
    result = []
    for r in rules:
        r = dict(r)
        stats = conn.execute(
            """SELECT COUNT(*) as total_impressions,
                SUM(CASE WHEN accepted = 1 THEN 1 ELSE 0 END) as total_accepted
            FROM upsell_impressions WHERE upsell_rule_id = ?""",
            (r["id"],),
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
    conn.execute(
        """INSERT INTO noshow_recovery
           (booking_id, patient_id, admin_id, reschedule_token, cancel_token, noshow_count)
           VALUES (?,?,?,?,?,?)""",
        (booking_id, patient_id, admin_id, reschedule_token, cancel_token, noshow_count),
    )
    conn.commit()
    recovery_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return recovery_id


def get_recovery_by_token(token, token_type="reschedule"):
    """Look up a recovery record by reschedule or cancel token."""
    conn = get_db()
    col = "reschedule_token" if token_type == "reschedule" else "cancel_token"
    row = conn.execute(f"SELECT * FROM noshow_recovery WHERE {col}=?", (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_recovery_status(recovery_id, status, responded_at=None, new_booking_id=None):
    """Update recovery status and optional fields."""
    conn = get_db()
    if responded_at and new_booking_id:
        conn.execute(
            "UPDATE noshow_recovery SET recovery_status=?, responded_at=?, new_booking_id=? WHERE id=?",
            (status, responded_at, new_booking_id, recovery_id),
        )
    elif responded_at:
        conn.execute(
            "UPDATE noshow_recovery SET recovery_status=?, responded_at=? WHERE id=?",
            (status, responded_at, recovery_id),
        )
    else:
        conn.execute(
            "UPDATE noshow_recovery SET recovery_status=? WHERE id=?",
            (status, recovery_id),
        )
    conn.commit()
    conn.close()


def get_noshow_policy(admin_id):
    """Get no-show policy for an admin. Returns dict or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM noshow_policy WHERE admin_id=?", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_noshow_policy(admin_id, **kwargs):
    """Insert or update no-show policy for an admin."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM noshow_policy WHERE admin_id=?", (admin_id,)).fetchone()
    allowed = ["max_noshows_before_deposit", "deposit_amount", "recovery_delay_minutes", "auto_recovery_enabled"]
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if existing:
        if fields:
            set_clause = ", ".join(f"{k}=?" for k in fields)
            values = list(fields.values()) + [admin_id]
            conn.execute(f"UPDATE noshow_policy SET {set_clause} WHERE admin_id=?", values)
    else:
        cols = ["admin_id"] + list(fields.keys())
        placeholders = ",".join(["?"] * len(cols))
        values = [admin_id] + list(fields.values())
        conn.execute(f"INSERT INTO noshow_policy ({','.join(cols)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()


def get_recovery_stats(admin_id):
    """Return recovery rate, revenue recovered, and flagged patients for an admin."""
    conn = get_db()
    total = conn.execute(
        "SELECT COUNT(*) as c FROM noshow_recovery WHERE admin_id=?", (admin_id,)
    ).fetchone()["c"]
    rescheduled = conn.execute(
        "SELECT COUNT(*) as c FROM noshow_recovery WHERE admin_id=? AND recovery_status='rescheduled'",
        (admin_id,),
    ).fetchone()["c"]
    sent = conn.execute(
        "SELECT COUNT(*) as c FROM noshow_recovery WHERE admin_id=? AND recovery_status IN ('sent','rescheduled','rescheduling','expired')",
        (admin_id,),
    ).fetchone()["c"]

    # Revenue recovered: sum of invoices linked to rescheduled bookings
    revenue = 0.0
    try:
        rev_row = conn.execute(
            """SELECT SUM(i.total) as rev FROM invoices i
               JOIN noshow_recovery nr ON i.booking_id = nr.new_booking_id
               WHERE nr.admin_id=? AND nr.recovery_status='rescheduled' AND i.payment_status='paid'""",
            (admin_id,),
        ).fetchone()
        if rev_row and rev_row["rev"]:
            revenue = rev_row["rev"]
    except Exception:
        pass

    # Flagged patients: those at or above deposit threshold
    policy = get_noshow_policy(admin_id)
    threshold = policy.get("max_noshows_before_deposit", 2) if policy else 2
    flagged = conn.execute(
        "SELECT COUNT(*) as c FROM patients WHERE admin_id=? AND total_no_shows >= ?",
        (admin_id, threshold),
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
                   subtotal, tax_rate, tax_amount, total):
    """Create an invoice record and return its id."""
    conn = get_db()
    conn.execute(
        """INSERT INTO invoices
           (admin_id, booking_id, patient_id, invoice_number, items_json,
            subtotal, tax_rate, tax_amount, total)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (admin_id, booking_id, patient_id, invoice_number, items_json,
         subtotal, tax_rate, tax_amount, total),
    )
    conn.commit()
    invoice_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return invoice_id


def get_invoice_by_id(invoice_id):
    """Return a single invoice by id."""
    conn = get_db()
    row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_invoices_list(admin_id, date_from=None, date_to=None):
    """List invoices for an admin, optionally filtered by date range."""
    conn = get_db()
    if date_from and date_to:
        rows = conn.execute(
            "SELECT * FROM invoices WHERE admin_id=? AND DATE(created_at) BETWEEN ? AND ? ORDER BY created_at DESC",
            (admin_id, date_from, date_to),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM invoices WHERE admin_id=? ORDER BY created_at DESC", (admin_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_invoice_config(admin_id):
    """Get invoice config for an admin. Returns dict or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM invoice_config WHERE admin_id=?", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_invoice_config(admin_id, **kwargs):
    """Insert or update invoice config for an admin."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM invoice_config WHERE admin_id=?", (admin_id,)).fetchone()
    allowed = ["business_name", "business_name_ar", "vat_number", "address", "address_ar",
               "logo_url", "next_invoice_number", "auto_generate"]
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if existing:
        if fields:
            set_clause = ", ".join(f"{k}=?" for k in fields)
            values = list(fields.values()) + [admin_id]
            conn.execute(f"UPDATE invoice_config SET {set_clause} WHERE admin_id=?", values)
    else:
        cols = ["admin_id"] + list(fields.keys())
        placeholders = ",".join(["?"] * len(cols))
        values = [admin_id] + list(fields.values())
        conn.execute(f"INSERT INTO invoice_config ({','.join(cols)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()


# ─── Performance Report DB Helpers ──────────────────────────────────

def create_performance_report(admin_id, month, year, report_data_json, generated_at):
    """Create or replace a performance report and return its id."""
    conn = get_db()
    # Use INSERT OR REPLACE due to UNIQUE(admin_id, month, year)
    conn.execute(
        """INSERT OR REPLACE INTO performance_reports
           (admin_id, month, year, report_data_json, generated_at)
           VALUES (?,?,?,?,?)""",
        (admin_id, month, year, report_data_json, generated_at),
    )
    conn.commit()
    report_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return report_id


def get_performance_report(report_id):
    """Return a single performance report by id, with parsed JSON data."""
    conn = get_db()
    row = conn.execute("SELECT * FROM performance_reports WHERE id=?", (report_id,)).fetchone()
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
        "FROM performance_reports WHERE admin_id=? ORDER BY year DESC, month DESC",
        (admin_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_report_config(admin_id):
    """Get report config for an admin. Returns dict or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM report_config WHERE admin_id=?", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_report_config(admin_id, **kwargs):
    """Insert or update report config for an admin."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM report_config WHERE admin_id=?", (admin_id,)).fetchone()
    allowed = ["auto_generate", "send_day_of_month", "recipients_json"]
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if existing:
        if fields:
            set_clause = ", ".join(f"{k}=?" for k in fields)
            values = list(fields.values()) + [admin_id]
            conn.execute(f"UPDATE report_config SET {set_clause} WHERE admin_id=?", values)
    else:
        cols = ["admin_id"] + list(fields.keys())
        placeholders = ",".join(["?"] * len(cols))
        values = [admin_id] + list(fields.values())
        conn.execute(f"INSERT INTO report_config ({','.join(cols)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()


# Initialize on import
init_db()
