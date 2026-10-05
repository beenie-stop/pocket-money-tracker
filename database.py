import streamlit as st
import psycopg2
import psycopg2.extras
import hashlib
import hmac
import secrets as pysecrets
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timedelta


# ---------- Database ----------

def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])


def _to_money(value):
    """Convert a numeric input to Decimal with exactly two decimal places."""
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid monetary amount.")
    if amount < 0:
        raise ValueError("Amount cannot be negative.")
    return amount


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
                        amount NUMERIC(12, 2) NOT NULL,
                        note TEXT,
                        date TEXT NOT NULL,
                        source TEXT,
                        payment_method TEXT NOT NULL DEFAULT 'Cash',
                        CONSTRAINT transactions_type_check
                            CHECK (type IN ('expense', 'income')),
                        CONSTRAINT transactions_amount_check
                            CHECK (amount > 0)
                    )
                """)

                # Upgrade older installations without destroying existing data.
                cur.execute("""
                    ALTER TABLE transactions
                    ADD COLUMN IF NOT EXISTS payment_method TEXT NOT NULL DEFAULT 'Cash'
                """)

                # Existing installations may still have REAL amount columns.
                # Convert them to exact decimal money values.
                cur.execute("""
                    ALTER TABLE transactions
                    ALTER COLUMN amount TYPE NUMERIC(12, 2)
                    USING ROUND(amount::numeric, 2)
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS money_sources (
                        user_id INTEGER NOT NULL,
                        month TEXT NOT NULL,
                        source TEXT NOT NULL,
                        amount NUMERIC(12, 2) NOT NULL,
                        PRIMARY KEY (user_id, month, source),
                        CONSTRAINT money_sources_amount_check
                            CHECK (amount >= 0)
                    )
                """)

                cur.execute("""
                    ALTER TABLE money_sources
                    ALTER COLUMN amount TYPE NUMERIC(12, 2)
                    USING ROUND(amount::numeric, 2)
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        token TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        expires_at TIMESTAMP NOT NULL
                    )
                """)

                # Helpful indexes for the dashboard's most common queries.
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_transactions_user_date
                    ON transactions (user_id, date DESC, id DESC)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_expires_at
                    ON sessions (expires_at)
                """)

                # Add foreign keys only when they do not already exist.
                cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'transactions_user_id_fkey'
                        ) THEN
                            ALTER TABLE transactions
                            ADD CONSTRAINT transactions_user_id_fkey
                            FOREIGN KEY (user_id) REFERENCES users(id)
                            ON DELETE CASCADE;
                        END IF;
                    END $$;
                """)

                cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'money_sources_user_id_fkey'
                        ) THEN
                            ALTER TABLE money_sources
                            ADD CONSTRAINT money_sources_user_id_fkey
                            FOREIGN KEY (user_id) REFERENCES users(id)
                            ON DELETE CASCADE;
                        END IF;
                    END $$;
                """)

                cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'sessions_user_id_fkey'
                        ) THEN
                            ALTER TABLE sessions
                            ADD CONSTRAINT sessions_user_id_fkey
                            FOREIGN KEY (user_id) REFERENCES users(id)
                            ON DELETE CASCADE;
                        END IF;
                    END $$;
                """)

                # Remove expired sessions periodically.
                cur.execute(
                    "DELETE FROM sessions WHERE expires_at <= %s",
                    (datetime.utcnow(),)
                )
    finally:
        conn.close()


# ---------- Auth ----------

# PBKDF2 is deliberately slow and is available in Python's standard library.
# This avoids adding another package dependency while being much safer than
# a single SHA-256 password hash.
PBKDF2_ITERATIONS = 310_000


def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS
    ).hex()


def _legacy_hash_password(password, salt):
    """Hash format used by the original application."""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def _make_password_hash(password):
    salt = pysecrets.token_hex(16)
    return salt, _hash_password(password, salt)


def create_user(username, password):
    username = username.strip().lower()

    if not username:
        return False, "Username cannot be empty."
    if len(username) > 100:
        return False, "Username is too long."
    if not password:
        return False, "Password cannot be empty."

    salt, password_hash = _make_password_hash(password)

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (username, password_hash, salt)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (username) DO NOTHING
                    """,
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
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, password_hash, salt
                    FROM users
                    WHERE username = %s
                    """,
                    (username,)
                )

                row = cur.fetchone()

                if not row:
                    return None

                user_id, stored_hash, salt = row

                # New PBKDF2 hashes.
                if len(stored_hash) == 64:
                    candidate = _hash_password(password, salt)
                    if hmac.compare_digest(candidate, stored_hash):
                        return user_id

                    # Existing users from the old application have a SHA-256
                    # hash. Verify it once, then transparently upgrade it.
                    legacy_candidate = _legacy_hash_password(password, salt)
                    if hmac.compare_digest(legacy_candidate, stored_hash):
                        new_salt, new_hash = _make_password_hash(password)
                        cur.execute(
                            """
                            UPDATE users
                            SET password_hash = %s, salt = %s
                            WHERE id = %s
                            """,
                            (new_hash, new_salt, user_id)
                        )
                        return user_id

                return None
    finally:
        conn.close()


def get_username_by_id(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username FROM users WHERE id = %s",
                (user_id,)
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


# ---------- Transactions ----------

def _normalize_transaction_type(t_type):
    if t_type not in ("expense", "income"):
        raise ValueError("Invalid transaction type.")
    return t_type


def _normalize_payment_method(t_type, payment_method):
    if t_type == "expense":
        return payment_method if payment_method in ("UPI", "Cash") else "Cash"
    return "N/A"


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
    t_type = _normalize_transaction_type(t_type)
    category = (category or "").strip()
    if not category:
        raise ValueError("Category cannot be empty.")

    amount = _to_money(amount)

    txn_date = txn_date or str(date.today())
    payment_method = _normalize_payment_method(t_type, payment_method)

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
                        note or "",
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
    t_type = _normalize_transaction_type(t_type)
    category = (category or "").strip()
    if not category:
        raise ValueError("Category cannot be empty.")

    amount = _to_money(amount)
    payment_method = _normalize_payment_method(t_type, payment_method)

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
                        note or "",
                        txn_date,
                        source,
                        payment_method,
                        transaction_id,
                        user_id
                    )
                )
                if cur.rowcount == 0:
                    raise ValueError("Transaction not found.")
    finally:
        conn.close()


def get_transactions_by_month(user_id, month):
    conn = get_connection()
    try:
        with conn.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:
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
                """
                SELECT DISTINCT LEFT(date, 7)
                FROM transactions
                WHERE user_id = %s
                """,
                (user_id,)
            )
            txn_months = [r[0] for r in cur.fetchall()]

            cur.execute(
                """
                SELECT DISTINCT month
                FROM money_sources
                WHERE user_id = %s
                """,
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
                if cur.rowcount == 0:
                    raise ValueError("Transaction not found.")
    finally:
        conn.close()


# ---------- Money sources ----------

def _resolve_source_name(cur, user_id, month, source):
    """Return the stored spelling of a source if it already exists for this
    month (case-insensitive), otherwise the cleaned name."""
    cur.execute(
        """
        SELECT source
        FROM money_sources
        WHERE user_id = %s
          AND month = %s
          AND LOWER(source) = LOWER(%s)
        """,
        (user_id, month, source)
    )
    row = cur.fetchone()
    return row[0] if row else source


def set_source_amount(user_id, month, source, amount):
    """Set a source to an exact amount (replaces the old value)."""
    source = (source or "").strip()
    if not source:
        raise ValueError("Source name cannot be empty.")

    amount = _to_money(amount)

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                source = _resolve_source_name(cur, user_id, month, source)
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


def add_to_source_amount(user_id, month, source, amount):
    """Add money to a source. If the source already exists the amount is
    ADDED to the current value instead of replacing it."""
    source = (source or "").strip()
    if not source:
        raise ValueError("Source name cannot be empty.")

    amount = _to_money(amount)
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                source = _resolve_source_name(cur, user_id, month, source)
                cur.execute(
                    """
                    INSERT INTO money_sources
                    (user_id, month, source, amount)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, month, source)
                    DO UPDATE SET amount = money_sources.amount + EXCLUDED.amount
                    """,
                    (user_id, month, source, amount)
                )
    finally:
        conn.close()


def delete_source(user_id, month, source):
    """Remove a source. Refused if expenses were already made from it."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM transactions
                    WHERE user_id = %s
                      AND type = 'expense'
                      AND source = %s
                      AND date LIKE %s
                    """,
                    (user_id, source, f"{month}%")
                )
                if cur.fetchone()[0] > 0:
                    raise ValueError(
                        f"{source} has expenses this month, so it can't be "
                        "removed. Edit or delete those expenses first."
                    )

                cur.execute(
                    """
                    DELETE FROM money_sources
                    WHERE user_id = %s AND month = %s AND source = %s
                    """,
                    (user_id, month, source)
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

def create_session(user_id, days_valid=30):
    token = pysecrets.token_hex(32)
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
    if not token:
        return

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