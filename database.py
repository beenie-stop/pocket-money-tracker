import sqlite3
import hashlib
import secrets
from datetime import date

DB_NAME = "finance.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                note TEXT,
                date TEXT NOT NULL,
                source TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS money_sources (
                user_id INTEGER NOT NULL,
                month TEXT NOT NULL,
                source TEXT NOT NULL,
                amount REAL NOT NULL,
                PRIMARY KEY (user_id, month, source)
            )
        """)

# ---------- Auth ----------

def _hash_password(password, salt):
    return hashlib.sha256((salt + password).encode()).hexdigest()

def create_user(username, password):
    username = username.strip().lower()
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    with sqlite3.connect(DB_NAME) as conn:
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
                (username, password_hash, salt)
            )
            return True, "Account created!"
        except sqlite3.IntegrityError:
            return False, "That username is already taken."

def verify_user(username, password):
    username = username.strip().lower()
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute(
            "SELECT id, password_hash, salt FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            return None
        user_id, stored_hash, salt = row
        if _hash_password(password, salt) == stored_hash:
            return user_id
        return None

# ---------- Transactions (all scoped to user_id) ----------

def add_transaction(user_id, t_type, category, amount, note="", txn_date=None, source=None):
    txn_date = txn_date or str(date.today())
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO transactions (user_id, type, category, amount, note, date, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, t_type, category, amount, note, txn_date, source)
        )

def get_transactions_by_month(user_id, month):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? AND date LIKE ? ORDER BY date DESC, id DESC",
            (user_id, f"{month}%")
        ).fetchall()
        return [dict(row) for row in rows]

def get_available_months(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        txn_months = [r[0] for r in conn.execute(
            "SELECT DISTINCT substr(date,1,7) FROM transactions WHERE user_id = ?", (user_id,)
        ).fetchall()]
        source_months = [r[0] for r in conn.execute(
            "SELECT DISTINCT month FROM money_sources WHERE user_id = ?", (user_id,)
        ).fetchall()]
        return sorted(set(txn_months + source_months), reverse=True)

def delete_transaction(user_id, transaction_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "DELETE FROM transactions WHERE id = ? AND user_id = ?", (transaction_id, user_id)
        )

# ---------- Money sources (all scoped to user_id) ----------

def set_source_amount(user_id, month, source, amount):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO money_sources (user_id, month, source, amount) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, month, source) DO UPDATE SET amount = excluded.amount",
            (user_id, month, source, amount)
        )

def get_sources_by_month(user_id, month):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT source, amount FROM money_sources WHERE user_id = ? AND month = ? ORDER BY source",
            (user_id, month)
        ).fetchall()
        return [dict(row) for row in rows]