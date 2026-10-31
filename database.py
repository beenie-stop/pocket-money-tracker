import hashlib
import hmac
import secrets as pysecrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import psycopg2
import psycopg2.extras
import psycopg2.pool
import streamlit as st


# ---------- Connection pool ----------
#
# Streamlit re-runs the whole script on every click. Opening a brand-new
# database connection each time (TLS handshake + auth) was the biggest source
# of lag, so connections are now kept open in a small pool that is created
# once per server process and reused by every query.

@st.cache_resource(show_spinner=False)
def _get_pool():
    return psycopg2.pool.ThreadedConnectionPool(
        1,
        10,
        dsn=st.secrets["DATABASE_URL"],
        connect_timeout=10,
        # Detect connections silently dropped by the server / proxy.
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
    )


def _run(work, write=False):
    """Run ``work(conn)`` on a pooled connection and return its result.

    * Reads run in autocommit mode: no BEGIN/COMMIT round trips.
    * Writes run in one transaction that is committed on success and rolled
      back on any error.
    * If the connection turns out to have been dropped while it sat idle in
      the pool, it is discarded and the work is retried once on a fresh one.
    """
    pool = _get_pool()

    for attempt in range(2):
        conn = pool.getconn()
        broken = False
        try:
            conn.autocommit = not write
            result = work(conn)
            if write:
                conn.commit()
            return result
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            broken = True
            if attempt == 1:
                raise
        finally:
            # putconn() rolls back any half-finished transaction for us.
            pool.putconn(conn, close=broken)


def _utcnow():
    """Naive UTC timestamp (the sessions table uses TIMESTAMP, not TIMESTAMPTZ)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Largest value that fits in NUMERIC(12, 2).
_MAX_MONEY = Decimal("9999999999.99")


def _to_money(value):
    """Convert a numeric input to Decimal with exactly two decimal places."""
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():  # NaN / Infinity
            raise ValueError
        amount = amount.quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid monetary amount.")
    if amount < 0:
        raise ValueError("Amount cannot be negative.")
    if amount > _MAX_MONEY:
        raise ValueError("Amount is too large.")
    return amount


def _normalize_date(value):
    """Return an ISO date string (YYYY-MM-DD); default to today."""
    if not value:
        return str(date.today())
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ValueError("Invalid date.")


# ---------- Schema ----------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL
);

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
);

-- Upgrade older installations without destroying existing data.
ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS payment_method TEXT NOT NULL DEFAULT 'Cash';

CREATE TABLE IF NOT EXISTS money_sources (
    user_id INTEGER NOT NULL,
    month TEXT NOT NULL,
    source TEXT NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    PRIMARY KEY (user_id, month, source),
    CONSTRAINT money_sources_amount_check
        CHECK (amount >= 0)
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at TIMESTAMP NOT NULL
);

-- Very old installations stored REAL amounts. Convert them to exact decimals,
-- but ONLY when needed: ALTER ... TYPE takes an exclusive table lock and can
-- rewrite the whole table, so it must not run on every page load.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'transactions' AND column_name = 'amount'
          AND NOT (data_type = 'numeric'
                   AND numeric_precision = 12 AND numeric_scale = 2)
    ) THEN
        ALTER TABLE transactions
            ALTER COLUMN amount TYPE NUMERIC(12, 2)
            USING ROUND(amount::numeric, 2);
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'money_sources' AND column_name = 'amount'
          AND NOT (data_type = 'numeric'
                   AND numeric_precision = 12 AND numeric_scale = 2)
    ) THEN
        ALTER TABLE money_sources
            ALTER COLUMN amount TYPE NUMERIC(12, 2)
            USING ROUND(amount::numeric, 2);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_transactions_user_date
    ON transactions (user_id, date DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_sessions_expires_at
    ON sessions (expires_at);

-- Add foreign keys only when they do not already exist.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'transactions_user_id_fkey') THEN
        ALTER TABLE transactions
            ADD CONSTRAINT transactions_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'money_sources_user_id_fkey') THEN
        ALTER TABLE money_sources
            ADD CONSTRAINT money_sources_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'sessions_user_id_fkey') THEN
        ALTER TABLE sessions
            ADD CONSTRAINT sessions_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;
END $$;

-- Remove expired sessions.
DELETE FROM sessions WHERE expires_at <= (NOW() AT TIME ZONE 'UTC');
"""


@st.cache_resource(show_spinner=False)
def init_db():
    """Create / upgrade the schema.

    Cached, so it runs once per server process instead of on every click.
    The whole script is sent in a single round trip.
    """
    def work(conn):
        with conn.cursor() as cur:
            cur.execute(_SCHEMA_SQL)

    _run(work, write=True)
    return True


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

    def work(conn):
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

    return _run(work, write=True)


def verify_user(username, password):
    username = username.strip().lower()

    def work(conn):
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

            if len(stored_hash) != 64:
                return None

            # New PBKDF2 hashes. A salt that is not valid hex can only belong
            # to a legacy account, so treat it as "not a PBKDF2 match" instead
            # of crashing the login.
            try:
                if hmac.compare_digest(
                    _hash_password(password, salt), stored_hash
                ):
                    return user_id
            except ValueError:
                pass

            # Existing users from the old application have a SHA-256 hash.
            # Verify it once, then transparently upgrade it.
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

    return _run(work, write=True)


def get_username_by_id(user_id):
    def work(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username FROM users WHERE id = %s",
                (user_id,)
            )
            row = cur.fetchone()
            return row[0] if row else None

    return _run(work)


# ---------- Read cache ----------
#
# Every widget click re-runs the script, which used to hit the database again
# even when nothing had changed (typing in a filter, opening an expander...).
# Reads are cached and the cache is cleared whenever this module writes data.

def _invalidate_cache():
    get_available_months.clear()
    get_sources_by_month.clear()
    get_transactions_by_month.clear()


# ---------- Transactions ----------

def _normalize_transaction_type(t_type):
    if t_type not in ("expense", "income"):
        raise ValueError("Invalid transaction type.")
    return t_type


def _normalize_payment_method(t_type, payment_method):
    if t_type == "expense":
        return payment_method if payment_method in ("UPI", "Cash") else "Cash"
    return "N/A"


def _clean_transaction_fields(t_type, category, amount, txn_date):
    t_type = _normalize_transaction_type(t_type)

    category = (category or "").strip()
    if not category:
        raise ValueError("Category cannot be empty.")

    amount = _to_money(amount)
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")

    return t_type, category, amount, _normalize_date(txn_date)


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
    t_type, category, amount, txn_date = _clean_transaction_fields(
        t_type, category, amount, txn_date
    )
    payment_method = _normalize_payment_method(t_type, payment_method)

    def work(conn):
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

    _run(work, write=True)
    _invalidate_cache()


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
    t_type, category, amount, txn_date = _clean_transaction_fields(
        t_type, category, amount, txn_date
    )
    payment_method = _normalize_payment_method(t_type, payment_method)

    def work(conn):
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

    _run(work, write=True)
    _invalidate_cache()


@st.cache_data(ttl=300, show_spinner=False)
def get_transactions_by_month(user_id, month):
    def work(conn):
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

    return _run(work)


@st.cache_data(ttl=300, show_spinner=False)
def get_available_months(user_id):
    # One round trip instead of two.
    def work(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m FROM (
                    SELECT LEFT(date, 7) AS m
                    FROM transactions
                    WHERE user_id = %s
                    UNION
                    SELECT month AS m
                    FROM money_sources
                    WHERE user_id = %s
                ) AS months
                WHERE m IS NOT NULL AND m <> ''
                ORDER BY m DESC
                """,
                (user_id, user_id)
            )
            return [r[0] for r in cur.fetchall()]

    return _run(work)


def delete_transaction(user_id, transaction_id):
    def work(conn):
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

    _run(work, write=True)
    _invalidate_cache()


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

    def work(conn):
        with conn.cursor() as cur:
            name = _resolve_source_name(cur, user_id, month, source)
            cur.execute(
                """
                INSERT INTO money_sources
                (user_id, month, source, amount)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, month, source)
                DO UPDATE SET amount = EXCLUDED.amount
                """,
                (user_id, month, name, amount)
            )

    _run(work, write=True)
    _invalidate_cache()


def add_to_source_amount(user_id, month, source, amount):
    """Add money to a source. If the source already exists the amount is
    ADDED to the current value instead of replacing it."""
    source = (source or "").strip()
    if not source:
        raise ValueError("Source name cannot be empty.")

    amount = _to_money(amount)
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")

    def work(conn):
        with conn.cursor() as cur:
            name = _resolve_source_name(cur, user_id, month, source)
            cur.execute(
                """
                INSERT INTO money_sources
                (user_id, month, source, amount)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, month, source)
                DO UPDATE SET amount = money_sources.amount + EXCLUDED.amount
                """,
                (user_id, month, name, amount)
            )

    _run(work, write=True)
    _invalidate_cache()


def delete_source(user_id, month, source):
    """Remove a source. Refused if expenses were already made from it."""
    def work(conn):
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

    _run(work, write=True)
    _invalidate_cache()


@st.cache_data(ttl=300, show_spinner=False)
def get_sources_by_month(user_id, month):
    def work(conn):
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

    return _run(work)


# ---------- Sessions ----------

def create_session(user_id, days_valid=30):
    token = pysecrets.token_hex(32)
    now = _utcnow()
    expires_at = now + timedelta(days=days_valid)

    def work(conn):
        with conn.cursor() as cur:
            # Housekeeping: drop expired sessions whenever a new one is made.
            cur.execute(
                "DELETE FROM sessions WHERE expires_at <= %s",
                (now,)
            )
            cur.execute(
                """
                INSERT INTO sessions
                (token, user_id, expires_at)
                VALUES (%s, %s, %s)
                """,
                (token, user_id, expires_at)
            )

    _run(work, write=True)
    return token


def get_user_id_from_token(token):
    if not token:
        return None

    def work(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id
                FROM sessions
                WHERE token = %s
                  AND expires_at > %s
                """,
                (token, _utcnow())
            )
            row = cur.fetchone()
            return row[0] if row else None

    return _run(work)


def delete_session(token):
    if not token:
        return

    def work(conn):
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sessions WHERE token = %s",
                (token,)
            )

    _run(work, write=True)