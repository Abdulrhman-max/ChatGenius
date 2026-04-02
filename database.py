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
    ]
    for table, col, col_type in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

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

    # Log all users out
    conn.execute("UPDATE users SET token = '', token_expires_at = ''")
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


def get_all_leads(admin_id=0):
    conn = get_db()
    if admin_id:
        rows = conn.execute("SELECT * FROM leads WHERE admin_id = ? ORDER BY created_at DESC", (admin_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_booking(customer_name, customer_email, date, time, service="General Consultation",
                 calendar_event_id="", customer_phone="", doctor_id=0, doctor_name="", admin_id=0):
    conn = get_db()
    conn.execute(
        """INSERT INTO bookings (customer_name, customer_email, customer_phone, date, time,
           service, calendar_event_id, doctor_id, doctor_name, admin_id) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (customer_name, customer_email, customer_phone, date, time, service,
         calendar_event_id, doctor_id, doctor_name, admin_id),
    )
    conn.commit()
    conn.close()


def get_booked_times(doctor_id, date_str):
    """Get list of booked time strings for a doctor on a specific date."""
    conn = get_db()
    rows = conn.execute(
        "SELECT time FROM bookings WHERE doctor_id = ? AND date = ? AND status != 'cancelled'",
        (doctor_id, date_str)).fetchall()
    conn.close()
    return [r["time"] for r in rows]


def find_bookings_by_date(admin_id, date_str):
    """Find active bookings for a specific date under an admin."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM bookings WHERE admin_id = ? AND date = ? AND status != 'cancelled' ORDER BY time",
        (admin_id, date_str)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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
        booking_count = conn.execute("SELECT COUNT(*) FROM bookings WHERE doctor_id = ?", (doctor_id,)).fetchone()[0]
        today_bookings = conn.execute("SELECT COUNT(*) FROM bookings WHERE doctor_id = ? AND date = ?", (doctor_id, today)).fetchone()[0]
    elif admin_id:
        lead_count = conn.execute("SELECT COUNT(*) FROM leads WHERE admin_id = ?", (admin_id,)).fetchone()[0]
        booking_count = conn.execute("SELECT COUNT(*) FROM bookings WHERE admin_id = ?", (admin_id,)).fetchone()[0]
        today_bookings = conn.execute("SELECT COUNT(*) FROM bookings WHERE admin_id = ? AND date = ?", (admin_id, today)).fetchone()[0]
    else:
        lead_count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        booking_count = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        today_bookings = conn.execute("SELECT COUNT(*) FROM bookings WHERE date = ?", (today,)).fetchone()[0]
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
    conn = get_db()
    token = _generate_token()
    expires = _token_expiry()
    password_hash = _hash_password(password) if password else ""
    try:
        conn.execute(
            """INSERT INTO users (name, email, password_hash, company, role, plan, provider, provider_id, token, token_expires_at, specialty)
               VALUES (?, ?, ?, ?, ?, 'free_trial', ?, ?, ?, ?, ?)""",
            (name, email, password_hash, company, role, provider, provider_id, token, expires, specialty),
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        return dict(user), None
    except sqlite3.IntegrityError:
        conn.close()
        return None, "An account with this email already exists."


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
        conn.execute(
            """INSERT INTO users (name, email, company, role, plan, provider, provider_id, avatar_url, token, token_expires_at, specialty)
               VALUES (?, ?, '', ?, 'free_trial', ?, ?, ?, ?, ?, ?)""",
            (name, email, role, provider, provider_id, avatar_url, token, expires, specialty),
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
            services=?, pricing_insurance=?, emergency_info=?, about=?, updated_at=CURRENT_TIMESTAMP
            WHERE user_id=?""",
            (data.get("business_name", ""), data.get("address", ""), data.get("phone", ""),
             data.get("business_hours", ""), data.get("services", ""), data.get("pricing_insurance", ""),
             data.get("emergency_info", ""), data.get("about", ""), user_id))
    else:
        conn.execute("""INSERT INTO company_info (user_id, business_name, address, phone, business_hours,
            services, pricing_insurance, emergency_info, about) VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, data.get("business_name", ""), data.get("address", ""), data.get("phone", ""),
             data.get("business_hours", ""), data.get("services", ""), data.get("pricing_insurance", ""),
             data.get("emergency_info", ""), data.get("about", "")))
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


def add_doctor(admin_id, name, email="", specialty="", bio="", availability="Mon-Fri"):
    conn = get_db()
    conn.execute(
        "INSERT INTO doctors (admin_id, user_id, name, email, specialty, bio, availability, status) VALUES (?,0,?,?,?,?,?,?)",
        (admin_id, name, email, specialty, bio, availability, "pending"))
    conn.commit()
    doctor_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return doctor_id


def update_doctor(doctor_id, admin_id, name, specialty="", bio="", availability="Mon-Fri",
                   start_time=None, end_time=None, is_active=None, appointment_length=None):
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

def get_doctor_breaks(doctor_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM doctor_breaks WHERE doctor_id = ? ORDER BY start_time", (doctor_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_doctor_break(doctor_id, break_name, start_time, end_time):
    conn = get_db()
    conn.execute(
        "INSERT INTO doctor_breaks (doctor_id, break_name, start_time, end_time) VALUES (?,?,?,?)",
        (doctor_id, break_name, start_time, end_time))
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
    """Get active doctors filtered by specialty/category."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM doctors WHERE admin_id = ? AND status = 'active' AND specialty = ? ORDER BY name",
        (admin_id, category_name)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# Initialize on import
init_db()
