
import streamlit as st
import psycopg2
import psycopg2.extras
import hashlib
import secrets as pysecrets
from datetime import date


def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])


def init_db():
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        salt TEXT NOT NULL
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        type TEXT NOT NULL,
                        category TEXT NOT NULL,
                        amount REAL NOT NULL,
                        note TEXT,
                        date TEXT NOT NULL,
                        source TEXT,
                        payment_method TEXT NOT NULL DEFAULT 'Cash'
                    )
                """)

                # Add payment_method to an existing transactions table
                # without deleting or changing existing transactions.
                cur.execute("""
                    ALTER TABLE transactions
                    ADD COLUMN IF NOT EXISTS payment_method TEXT NOT NULL DEFAULT 'Cash'
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS money_sources (
                        user_id INTEGER NOT NULL,
                        month TEXT NOT NULL,
                        source TEXT NOT NULL,
                        amount REAL NOT NULL,
                        PRIMARY KEY (user_id, month, source)
                    )
                """)

    finally:
        conn.close()


# ---------- Auth ----------

def _hash_password(password, salt):
    return hashlib.sha256((salt + password).encode()).hexdigest()


def create_user(username, password):
    username = username.strip().lower()
    salt = pysecrets.token_hex(16)
    password_hash = _hash_password(password, salt)

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username, password_hash, salt) VALUES (%s, %s, %s) "
                    "ON CONFLICT (username) DO NOTHING",
                    (username, password_hash, salt)
                )

                if cur.rowcount == 0:
                    return False, "That username is already taken."

                return True, "Account created!"

    finally:
        conn.close()


def verify_user(username, password):
    username = username.strip().lower()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, password_hash, salt FROM users WHERE username = %s",
                (username,)
            )

            row = cur.fetchone()

            if not row:
                return None

            user_id, stored_hash, salt = row

            if _hash_password(password, salt) == stored_hash:
                return user_id

            return None

    finally:
        conn.close()


# ---------- Transactions ----------

def add_transaction(
    user_id,
    t_type,
    category,
    amount,
    note="",
    txn_date=None,
    source=None,
    payment_method=None
):
    txn_date = txn_date or str(date.today())

    # Payment method is relevant mainly for expenses.
    # Existing/other transactions safely default to Cash.
    if t_type == "expense":
        payment_method = payment_method or "Cash"
    else:
        payment_method = "N/A"

    conn = get_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO transactions
                    (user_id, type, category, amount, note, date, source, payment_method)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        t_type,
                        category,
                        amount,
                        note,
                        txn_date,
                        source,
                        payment_method
                    )
                )

    finally:
        conn.close()


def update_transaction(
    user_id,
    transaction_id,
    t_type,
    category,
    amount,
    note,
    txn_date,
    source,
    payment_method=None
):
    if t_type == "expense":
        payment_method = payment_method or "Cash"
    else:
        payment_method = "N/A"

    conn = get_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE transactions
                    SET type=%s,
                        category=%s,
                        amount=%s,
                        note=%s,
                        date=%s,
                        source=%s,
                        payment_method=%s
                    WHERE id=%s AND user_id=%s
                    """,
                    (
                        t_type,
                        category,
                        amount,
                        note,
                        txn_date,
                        source,
                        payment_method,
                        transaction_id,
                        user_id
                    )
                )

    finally:
        conn.close()


def get_transactions_by_month(user_id, month):
    conn = get_connection()

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM transactions
                WHERE user_id = %s
                AND date LIKE %s
                ORDER BY date DESC, id DESC
                """,
                (user_id, f"{month}%")
            )

            return [dict(row) for row in cur.fetchall()]

    finally:
        conn.close()


def get_available_months(user_id):
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT LEFT(date, 7) FROM transactions WHERE user_id = %s",
                (user_id,)
            )

            txn_months = [r[0] for r in cur.fetchall()]

            cur.execute(
                "SELECT DISTINCT month FROM money_sources WHERE user_id = %s",
                (user_id,)
            )

            source_months = [r[0] for r in cur.fetchall()]

            return sorted(
                set(txn_months + source_months),
                reverse=True
            )

    finally:
        conn.close()


def delete_transaction(user_id, transaction_id):
    conn = get_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM transactions
                    WHERE id = %s AND user_id = %s
                    """,
                    (transaction_id, user_id)
                )

    finally:
        conn.close()


# ---------- Money sources ----------

def set_source_amount(user_id, month, source, amount):
    conn = get_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO money_sources
                    (user_id, month, source, amount)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, month, source)
                    DO UPDATE SET amount = EXCLUDED.amount
                    """,
                    (user_id, month, source, amount)
                )

    finally:
        conn.close()


def get_sources_by_month(user_id, month):
    conn = get_connection()

    try:
        with conn.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT source, amount
                FROM money_sources
                WHERE user_id = %s
                AND month = %s
                ORDER BY source
                """,
                (user_id, month)
            )

            return [dict(row) for row in cur.fetchall()]

    finally:
        conn.close()


# ---------- Sessions ----------

def create_session_table_if_needed():
    conn = get_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        token TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        expires_at TIMESTAMP NOT NULL
                    )
                """)

    finally:
        conn.close()


def create_session(user_id, days_valid=30):
    token = pysecrets2.token_hex(32)
    expires_at = datetime.utcnow() + timedelta(days=days_valid)

    conn = get_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sessions
                    (token, user_id, expires_at)
                    VALUES (%s, %s, %s)
                    """,
                    (token, user_id, expires_at)
                )

    finally:
        conn.close()

    return token


def get_user_id_from_token(token):
    if not token:
        return None

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id
                FROM sessions
                WHERE token = %s
                AND expires_at > %s
                """,
                (token, datetime.utcnow())
            )

            row = cur.fetchone()

            return row[0] if row else None

    finally:
        conn.close()


def delete_session(token):
    conn = get_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM sessions WHERE token = %s",
                    (token,)
                )

    finally:
        conn.close()
