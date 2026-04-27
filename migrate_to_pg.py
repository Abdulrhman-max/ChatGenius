"""
Migration script: Convert database.py from SQLite to PostgreSQL.
Run once, then delete this file.
"""
import re

INPUT = "database.py"
OUTPUT = "database_pg.py"

with open(INPUT, "r") as f:
    content = f.read()

# ─── 1. Imports ───
content = content.replace(
    'import sqlite3',
    'import psycopg2\nimport psycopg2.extras\nimport psycopg2.errors'
)

# ─── 2. DB_PATH → DB_CONFIG ───
content = content.replace(
    'DB_PATH = os.path.join(os.path.dirname(__file__), "chatgenius.db")',
    """DB_CONFIG = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'port': os.environ.get('DB_PORT', '5433'),
    'database': os.environ.get('DB_NAME', 'chatgenius'),
    'user': os.environ.get('DB_USER', 'chatgenius_admin'),
    'password': os.environ.get('DB_PASSWORD', 'AB.eg.32'),
}"""
)

# ─── 3. Replace get_db() with PgConnection wrapper ───
old_get_db = '''def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn'''

new_get_db = '''class PgConnection:
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
    return PgConnection(conn)'''

content = content.replace(old_get_db, new_get_db)

# ─── 4. AUTOINCREMENT → SERIAL ───
content = content.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')

# ─── 5. TIMESTAMP DEFAULT '' → TIMESTAMP DEFAULT NULL ───
content = content.replace("TIMESTAMP DEFAULT ''", "TIMESTAMP DEFAULT NULL")

# ─── 6. Replace ? placeholders with %s in SQL strings ───
# This is the trickiest part. We need to only replace ? inside SQL strings.
# Strategy: Find all string literals containing SQL keywords and replace ? with %s

def replace_sql_placeholders(text):
    """Replace ? with %s inside SQL query strings only."""
    result = []
    i = 0
    while i < len(text):
        # Check for triple-quoted strings
        if text[i:i+3] in ('"""', "'''"):
            quote = text[i:i+3]
            end = text.find(quote, i+3)
            if end == -1:
                result.append(text[i:])
                break
            string_content = text[i+3:end]
            # Check if this looks like SQL
            sql_keywords = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP',
                          'WHERE', 'FROM', 'INTO', 'VALUES', 'SET ']
            is_sql = any(kw in string_content.upper() for kw in sql_keywords)
            if is_sql:
                string_content = string_content.replace('?', '%s')
            result.append(quote + string_content + quote)
            i = end + 3
        # Check for single/double quoted strings
        elif text[i] in ('"', "'"):
            quote = text[i]
            j = i + 1
            while j < len(text):
                if text[j] == '\\':
                    j += 2
                    continue
                if text[j] == quote:
                    break
                j += 1
            string_content = text[i+1:j]
            # Check if this looks like SQL
            sql_keywords = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP',
                          'WHERE', 'FROM', 'INTO', 'VALUES', 'SET ', 'AND ', 'admin_id',
                          'LIMIT', 'ORDER', 'GROUP', 'HAVING', 'JOIN', 'LEFT ', 'INNER ',
                          'ON CONFLICT', 'RETURNING']
            is_sql = any(kw in string_content.upper() for kw in sql_keywords)
            if is_sql and '?' in string_content:
                string_content = string_content.replace('?', '%s')
            result.append(quote + string_content + quote)
            i = j + 1
        else:
            result.append(text[i])
            i += 1
    return ''.join(result)

content = replace_sql_placeholders(content)

# ─── 7. Fix last_insert_rowid() patterns ───
# Pattern: conn.execute("SELECT last_insert_rowid()").fetchone()[0]
# Need to add RETURNING id to the preceding INSERT and fetch from that cursor

# First, let's replace the simple pattern where we can
content = content.replace(
    'conn.execute("SELECT last_insert_rowid()").fetchone()[0]',
    '_last_id'
)

# Also handle the variant with single quotes
content = content.replace(
    "conn.execute(\"SELECT last_insert_rowid()\").fetchone()[0]",
    "_last_id"
)

# Now we need to add RETURNING id to INSERT statements that precede _last_id
# And capture the cursor result. This is complex - let's handle it with regex.

# Pattern:
#   conn.execute("INSERT INTO ... VALUES (...)", (...))
#   conn.commit()
#   var = _last_id
# OR:
#   conn.execute("INSERT INTO ... VALUES (...)", (...))
#   var = _last_id
#   conn.commit()

# For INSERT ... RETURNING id, we need to:
# 1. Add RETURNING id to the INSERT SQL
# 2. Capture the cursor: cur = conn.execute(...)
# 3. Get id: var = cur.fetchone()['id']

# Let's do a simpler approach: add RETURNING id to all INSERT statements
# and fix the _last_id references

# Add RETURNING id to INSERT INTO statements that are followed by _last_id
lines = content.split('\n')
new_lines = []
for i, line in enumerate(lines):
    if '_last_id' in line and '=' in line:
        # Find the variable name
        var_match = re.match(r'(\s+)(\w+)\s*=\s*_last_id', line)
        if var_match:
            indent = var_match.group(1)
            var_name = var_match.group(2)
            # Look backwards for the INSERT statement and add RETURNING id
            for j in range(len(new_lines)-1, max(len(new_lines)-15, -1), -1):
                prev_line = new_lines[j]
                # Check if this line ends a SQL INSERT (has VALUES and closing paren)
                if 'INSERT INTO' in prev_line.upper() or ('VALUES' in prev_line.upper() and ')' in prev_line):
                    # Find the line with the closing of VALUES
                    if ')' in prev_line and ('VALUES' in prev_line.upper() or 'INSERT' in prev_line.upper()):
                        # Check if it already has RETURNING
                        if 'RETURNING' not in prev_line.upper():
                            # Find the last ) before the quote end
                            # Add RETURNING id before the closing quote
                            prev_line_stripped = prev_line.rstrip()
                            # Find pattern: ...)" or ...)', or ...)"""
                            match = re.search(r'\)\s*(["\'])', prev_line_stripped)
                            if match:
                                insert_pos = match.start() + 1
                                new_lines[j] = prev_line_stripped[:insert_pos] + ' RETURNING id' + prev_line_stripped[insert_pos:]
                                break
                    elif ')' in prev_line and j > 0:
                        # Multi-line INSERT - the VALUES might be on previous lines
                        # Just add RETURNING id after the last )
                        prev_line_stripped = prev_line.rstrip()
                        match = re.search(r'\)\s*(["\'])', prev_line_stripped)
                        if match:
                            insert_pos = match.start() + 1
                            new_lines[j] = prev_line_stripped[:insert_pos] + ' RETURNING id' + prev_line_stripped[insert_pos:]
                            break

            # Also need to capture cursor. Look for conn.execute above
            for j in range(len(new_lines)-1, max(len(new_lines)-15, -1), -1):
                if 'conn.execute(' in new_lines[j] and 'INSERT' in new_lines[j].upper():
                    # Add cursor capture
                    if not new_lines[j].strip().startswith('cur =') and not new_lines[j].strip().startswith('_cur ='):
                        new_lines[j] = new_lines[j].replace('conn.execute(', '_ins_cur = conn.execute(', 1)
                    break

            # Replace _last_id with cursor fetchone
            line = f"{indent}{var_name} = _ins_cur.fetchone()['id']"
    new_lines.append(line)

content = '\n'.join(new_lines)

# ─── 8. Fix cur.lastrowid ───
content = content.replace('cur.lastrowid', "cur.fetchone()['id']")
# Need to add RETURNING id to the INSERT that uses lastrowid
# This is in save_checkout_session - we'll handle it manually

# ─── 9. sqlite3.OperationalError → psycopg2 error ───
content = content.replace('sqlite3.OperationalError', 'Exception')

# ─── 10. sqlite3.IntegrityError → psycopg2.IntegrityError ───
content = content.replace('sqlite3.IntegrityError', 'psycopg2.IntegrityError')

# ─── 11. INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING ───
content = re.sub(
    r'INSERT OR IGNORE INTO',
    'INSERT INTO',
    content
)
# Need to add ON CONFLICT DO NOTHING to these - but they already have VALUES
# Let's handle this more carefully
# Actually, for INSERT OR IGNORE, we need to find the full statement

# ─── 12. INSERT OR REPLACE → INSERT ... ON CONFLICT DO UPDATE ───
# Only 1 occurrence for performance_reports
content = content.replace(
    "INSERT OR REPLACE INTO performance_reports",
    "INSERT INTO performance_reports"
)

# ─── 13. date() function in SQL → ::date cast ───
# Replace date(column_name) with column_name::date in SQL contexts
content = re.sub(r"date\(created_at\)", "created_at::date", content)
content = re.sub(r"DATE\(created_at\)", "created_at::date", content)
content = re.sub(r"date\(cancelled_at\)", "cancelled_at::date", content)

# ─── 14. date('now') → CURRENT_DATE ───
content = content.replace("date('now')", "CURRENT_DATE")

# ─── 15. LIKE → ILIKE for search queries ───
# Only change search-context LIKE, not pattern-matching ones
# The search queries use patterns like: name LIKE ? OR email LIKE ?
content = re.sub(r'(name|email|phone|action|details|user_name|user_email|specialty)\s+LIKE\s+%s',
                 r'\1 ILIKE %s', content)

# ─── 16. strftime → TO_CHAR ───
content = content.replace("strftime('%Y-W%W', created_at)", "TO_CHAR(created_at, 'IYYY-\"W\"IW')")
content = content.replace("strftime('%%Y-%%W', scheduled_for)", "TO_CHAR(scheduled_for, 'IYYY-\"W\"IW')")
content = content.replace("strftime('%Y-%W', completed_at)", "TO_CHAR(completed_at, 'IYYY-\"W\"IW')")

# ─── 17. fetchone()[0] on COUNT queries → fetchone()['count'] ───
# With RealDictCursor, COUNT(*) returns key 'count'
# But a safer approach: these patterns need aliases
# Let's replace the common pattern
content = re.sub(
    r'\.execute\("SELECT COUNT\(\*\) FROM',
    '.execute("SELECT COUNT(*) AS cnt FROM',
    content
)
# And fix the fetchone access
content = re.sub(
    r"\.fetchone\(\)\[0\]",
    ".fetchone()['cnt']",
    content
)

# ─── 18. PRAGMA table_info → information_schema ───
content = content.replace(
    'PRAGMA table_info(email_templates)',
    "SELECT column_name FROM information_schema.columns WHERE table_name = 'email_templates'"
)

# ─── 19. MAX in LIMIT → GREATEST ───
content = content.replace('LIMIT MAX(1,', 'LIMIT GREATEST(1,')

# ─── 20. Fix date arithmetic: date(col, '+' || days || ' days') ───
content = content.replace(
    "date(recommended_date, '+' || followup_day || ' days')",
    "recommended_date + (followup_day || ' days')::INTERVAL"
)

# ─── 21. Fix empty string timestamp comparisons ───
# != '' for timestamp columns should be IS NOT NULL
# But we need to be careful - only for timestamp-like columns
for col in ['cancelled_at', 'last_activity_at', 'notified_at', 'sent_at', 'activated_at',
            'token_expires_at', 'verified_at', 'confirmed_at', 'expired_at', 'opened_at',
            'booked_at', 'resolved_at', 'assigned_at', 'last_synced_at', 'paid_at',
            'responded_at', 'message_sent_at', 'voided_at', 'completed_at']:
    content = content.replace(f"{col} != ''", f"{col} IS NOT NULL")
    content = content.replace(f"{col} = ''", f"{col} IS NULL")

# ─── 22. Fix IS ? for NULL-safe comparison ───
content = content.replace('doctor_id IS %s', 'doctor_id IS NOT DISTINCT FROM %s')
content = content.replace('recurring_day IS %s', 'recurring_day IS NOT DISTINCT FROM %s')

# ─── 23. Fix ON CONFLICT for INSERT OR IGNORE (service_doctors) ───
content = content.replace(
    "INSERT INTO service_doctors (service_id, doctor_id, admin_id) VALUES (%s,%s,%s)",
    "INSERT INTO service_doctors (service_id, doctor_id, admin_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING"
)

# ─── 24. Fix INSERT OR REPLACE for performance_reports ───
# Already removed OR REPLACE above, now add ON CONFLICT
content = content.replace(
    "INSERT INTO performance_reports (admin_id, month, year, report_data_json, generated_at) VALUES (%s,%s,%s,%s,%s)",
    "INSERT INTO performance_reports (admin_id, month, year, report_data_json, generated_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (admin_id, month, year) DO UPDATE SET report_data_json = EXCLUDED.report_data_json, generated_at = EXCLUDED.generated_at"
)

# ─── 25. Fix docstring ───
content = content.replace(
    'SQLite database for leads, bookings, users (admin/doctor roles), doctor requests.',
    'PostgreSQL database for leads, bookings, users (admin/doctor roles), doctor requests.'
)

# ─── 26. Fix column name check for PRAGMA replacement ───
# The PRAGMA result was accessed by column name 'name', info_schema uses 'column_name'
content = content.replace(
    "col['name']",
    "col.get('column_name', col.get('name', ''))"
)

# ─── 27. Fix rollback after failed transaction ───
# After catching DuplicateColumn errors in migrations, we need to rollback
old_except = """        except Exception:
            pass  # Column already exists"""
new_except = """        except Exception:
            conn.rollback()  # Must rollback failed transaction in PostgreSQL"""
content = content.replace(old_except, new_except)

# Also handle the simpler pattern
content = content.replace(
    "except Exception:\n            pass",
    "except Exception:\n            conn.rollback()"
)

# ─── Write output ───
with open(OUTPUT, "w") as f:
    f.write(content)

print(f"Migration complete! Written to {OUTPUT}")
print("Review the output, then: mv database_pg.py database.py")
