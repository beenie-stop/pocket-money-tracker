import sqlite3
from datetime import date

DB_NAME = "finance.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                note TEXT,
                date TEXT NOT NULL,
                source TEXT
            )
        """)
        # Safe migration in case an older transactions table exists without 'source'
        cols = [row[1] for row in conn.execute("PRAGMA table_info(transactions)").fetchall()]
        if "source" not in cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN source TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS money_sources (
                month TEXT NOT NULL,
                source TEXT NOT NULL,
                amount REAL NOT NULL,
                PRIMARY KEY (month, source)
            )
        """)

# ---------- Transactions ----------

def add_transaction(t_type, category, amount, note="", txn_date=None, source=None):
    txn_date = txn_date or str(date.today())
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO transactions (type, category, amount, note, date, source) VALUES (?, ?, ?, ?, ?, ?)",
            (t_type, category, amount, note, txn_date, source)
        )

def get_all_transactions():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM transactions ORDER BY date DESC, id DESC").fetchall()
        return [dict(row) for row in rows]

def get_transactions_by_month(month):  # month format: "YYYY-MM"
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM transactions WHERE date LIKE ? ORDER BY date DESC, id DESC",
            (f"{month}%",)
        ).fetchall()
        return [dict(row) for row in rows]

def get_available_months():
    with sqlite3.connect(DB_NAME) as conn:
        txn_months = [r[0] for r in conn.execute(
            "SELECT DISTINCT substr(date,1,7) FROM transactions"
        ).fetchall()]
        source_months = [r[0] for r in conn.execute(
            "SELECT DISTINCT month FROM money_sources"
        ).fetchall()]
        return sorted(set(txn_months + source_months), reverse=True)

def delete_transaction(transaction_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))

# ---------- Money sources (Father / Mother / Relatives / etc.) ----------

def set_source_amount(month, source, amount):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO money_sources (month, source, amount) VALUES (?, ?, ?) "
            "ON CONFLICT(month, source) DO UPDATE SET amount = excluded.amount",
            (month, source, amount)
        )

def get_sources_by_month(month):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT source, amount FROM money_sources WHERE month = ? ORDER BY source",
            (month,)
        ).fetchall()
        return [dict(row) for row in rows]

def delete_source(month, source):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM money_sources WHERE month = ? AND source = ?", (month, source))

def get_total_budget(month):
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM money_sources WHERE month = ?", (month,)
        ).fetchone()
        return row[0] if row else 0.0