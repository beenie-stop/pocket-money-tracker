"""Code shared by dashboard.py and every page in views/."""
import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st
from fpdf import FPDF

import database
from database import CARRY_OVER_CATEGORY

CATEGORIES = [
    "Food", "Cab/Transport", "Groceries", "Rent", "Subscriptions",
    "Entertainment", "Shopping", "Health", "Education",
    "Miscellaneous", "Other"
]
INCOME_CATEGORIES = [
    "Pocket money", "Gift", "Refund", "Savings", CARRY_OVER_CATEGORY, "Other"
]
DEFAULT_SOURCES = ["Father", "Mother", "Relatives"]
PAYMENT_METHODS = ["UPI", "Cash"]
PAGE_SIZE = 30  # transactions rendered at a time


def today():
    """Today's date (one place to change, which keeps the app testable)."""
    return date.today()


# ---------------- Formatting helpers ----------------
def inr(value):
    """Format money as ₹. Shows paise only when there are some, so a
    ₹250.50 expense is never displayed as ₹250."""
    value = Decimal(str(value))
    sign = "-" if value < 0 else ""
    value = abs(value)

    if value == value.to_integral_value():
        return f"{sign}₹{value:,.0f}"
    return f"{sign}₹{value:,.2f}"


def payment_format(method):
    return "📱 UPI" if method == "UPI" else "💵 Cash"


def categories_for(t_type):
    return INCOME_CATEGORIES if t_type == "income" else CATEGORIES


def month_bounds(month):
    """(first_day, last_day) of a 'YYYY-MM' string."""
    year, mon = (int(x) for x in month.split("-"))
    return (
        date(year, mon, 1),
        date(year, mon, calendar.monthrange(year, mon)[1])
    )


def month_label(month):
    return month_bounds(month)[0].strftime("%B %Y")


# ---------------- Data for the selected month ----------------
@dataclass
class MonthData:
    user_id: int
    month: str
    sources: list          # [{"source", "amount"}]
    source_names: list     # names to offer in dropdowns
    total_budget: Decimal  # money received from sources
    rows: list             # raw transactions
    df_all: pd.DataFrame   # every row, dates as text
    df: pd.DataFrame       # rows with valid dates (dates parsed)
    spent_by_source: dict
    income_by_source: dict


def month_data():
    """Everything the pages need for the selected month.

    The database reads are cached (and cleared on every write), so calling
    this from several places in one run costs almost nothing.
    """
    user_id = st.session_state.user_id
    month = st.session_state.selected_month

    sources = database.get_sources_by_month(user_id, month)
    rows = database.get_transactions_by_month(user_id, month)

    df_all = (
        pd.DataFrame(rows)
        if rows
        else pd.DataFrame(columns=[
            "id", "type", "category", "amount", "note",
            "date", "source", "payment_method"
        ])
    )

    if "payment_method" not in df_all.columns:
        df_all["payment_method"] = "Cash"
    else:
        df_all["payment_method"] = (
            df_all["payment_method"].fillna("Cash").replace("", "Cash")
        )

    df = df_all.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    # Ignore malformed dates instead of crashing the whole app.
    df = df.dropna(subset=["date"])

    spent_by_source, income_by_source = {}, {}
    if not df_all.empty:
        spent_by_source = (
            df_all[df_all["type"] == "expense"]
            .groupby("source")["amount"].sum().to_dict()
        )
        income_by_source = (
            df_all[df_all["type"] == "income"]
            .groupby("source")["amount"].sum().to_dict()
        )

    return MonthData(
        user_id=user_id,
        month=month,
        sources=sources,
        source_names=(
            [s["source"] for s in sources] if sources else DEFAULT_SOURCES
        ),
        total_budget=sum((s["amount"] for s in sources), Decimal(0)),
        rows=rows,
        df_all=df_all,
        df=df,
        spent_by_source=spent_by_source,
        income_by_source=income_by_source,
    )


def ensure_sources(user_id, month, names, existing):
    """Make sure each name exists as a source this month (with ₹0 if new),
    so money added to it shows up in the 'Balance by source' cards."""
    for name in dict.fromkeys(n for n in names if n):
        if name not in existing:
            database.set_source_amount(user_id, month, name, 0)


# ---------------- Add transaction pop-up ----------------
def render_add_form():
    """The 'add a transaction' form (shown inside the pop-up)."""
    ctx = month_data()
    first_day, last_day = month_bounds(ctx.month)
    now = today()
    default_date = now if first_day <= now <= last_day else first_day

    st.caption(f"Adding to **{month_label(ctx.month)}**")

    # Type and Category are outside the form on purpose: widgets inside
    # st.form don't rerun, so "Other" / income-only fields wouldn't appear.
    t_type = st.selectbox("Type", ["expense", "income"], key="add_type")
    category = st.selectbox(
        "Category", categories_for(t_type), key=f"add_category_{t_type}"
    )

    with st.form("add_form", clear_on_submit=True):
        source = st.selectbox(
            "Spend from" if t_type == "expense" else "Add money to",
            ctx.source_names
        )

        custom_category = (
            st.text_input("Specify category") if category == "Other" else ""
        )

        payment_method = (
            st.selectbox(
                "Payment Method", PAYMENT_METHODS,
                format_func=payment_format
            )
            if t_type == "expense" else None
        )

        amount = st.number_input("Amount (₹)", min_value=0.0, step=10.0)
        note = st.text_input("Note (optional)")
        txn_date = st.date_input(
            "Date", value=default_date,
            min_value=first_day, max_value=last_day
        )

        if st.form_submit_button("Add", width="stretch"):
            final_category = (
                custom_category.strip() if category == "Other" else category
            )

            if not final_category or amount <= 0:
                st.error("Please choose a category and enter a valid amount.")
            else:
                try:
                    database.add_transaction(
                        ctx.user_id, t_type, final_category, amount, note,
                        str(txn_date), source, payment_method
                    )
                    st.toast("Added!")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


@st.dialog("➕ Add a transaction")
def add_transaction_dialog():
    render_add_form()


# ---------------- "Start new month" card ----------------
def new_month_card(ctx, key_prefix):
    """On a new month: show what was left last month and offer one-tap
    ways to (1) copy last month's received amounts and (2) carry the
    leftover forward. Renders nothing when there is nothing to offer."""
    # Only for the current calendar month, never for old months.
    if ctx.month != today().strftime("%Y-%m"):
        return

    older = [
        m for m in database.get_available_months(ctx.user_id)
        if m < ctx.month
    ]
    if not older:
        return

    prev = max(older)
    prev_sources = database.get_sources_by_month(ctx.user_id, prev)
    if not prev_sources:
        return

    spent, income = {}, {}
    for r in database.get_transactions_by_month(ctx.user_id, prev):
        bucket = spent if r["type"] == "expense" else income
        if r["source"]:
            bucket[r["source"]] = (
                bucket.get(r["source"], Decimal(0)) + r["amount"]
            )

    closing = {
        s["source"]: (
            s["amount"]
            + income.get(s["source"], 0)
            - spent.get(s["source"], 0)
        )
        for s in prev_sources
    }

    already_carried = {
        r["source"] for r in ctx.rows
        if r["type"] == "income" and r["category"] == CARRY_OVER_CATEGORY
    }
    can_copy = not ctx.sources
    carry_items = {
        name: amt for name, amt in closing.items()
        if amt > 0 and name not in already_carried
    }

    if not can_copy and not carry_items:
        return

    prev_name = month_label(prev)

    with st.container(border=True):
        st.subheader(f"🗓️ Start {month_label(ctx.month)}")
        st.caption(f"What was left at the end of {prev_name}:")

        cols = st.columns(min(len(closing), 4))
        for i, (name, amt) in enumerate(closing.items()):
            cols[i % len(cols)].metric(name, f"{inr(amt)} left")

        copy_col, carry_col = st.columns(2)

        if can_copy and copy_col.button(
            f"📋 Copy {prev_name} amounts",
            key=f"{key_prefix}_copy_sources",
            width="stretch",
            help="Sets this month's received money to the same amounts "
                 "as last month. You can still edit them."
        ):
            for s in prev_sources:
                database.set_source_amount(
                    ctx.user_id, ctx.month, s["source"], s["amount"]
                )
            st.toast(f"Copied amounts from {prev_name}.")
            st.rerun()

        if carry_items and carry_col.button(
            f"➡️ Carry {inr(sum(carry_items.values()))} forward",
            key=f"{key_prefix}_carry",
            width="stretch",
            help="Adds each source's leftover to this month as income "
                 f"(category '{CARRY_OVER_CATEGORY}')."
        ):
            ensure_sources(
                ctx.user_id, ctx.month, carry_items,
                {s["source"] for s in ctx.sources}
            )
            database.add_transactions(ctx.user_id, [
                {
                    "type": "income",
                    "category": CARRY_OVER_CATEGORY,
                    "amount": amt,
                    "note": f"Leftover from {prev_name}",
                    "date": f"{ctx.month}-01",
                    "source": name,
                }
                for name, amt in carry_items.items()
            ])
            st.toast("Leftover carried forward.")
            st.rerun()


# ---------------- Repeat last month's transactions ----------------
def build_copy_candidates(src_rows, current_rows, target_month, src_month,
                          grouped):
    """Work out what could be copied from ``src_month`` into ``target_month``.

    grouped=True  -> ONE row per (type, category, source, payment method) with
                     the amounts added up, e.g. "Miscellaneous ₹4,555".
    grouped=False -> every transaction separately (same day of the month).

    Each candidate is flagged ``duplicate`` when an identical entry already
    exists in the target month, so clicking twice doesn't double up.
    """
    from collections import Counter

    src_rows = [r for r in src_rows if r["category"] != CARRY_OVER_CATEGORY]
    first_day, last_day = month_bounds(target_month)
    items = []

    if grouped:
        groups = {}
        for r in src_rows:
            key = (r["type"], r["category"], r["source"], r["payment_method"])
            g = groups.setdefault(key, {"amount": Decimal(0), "count": 0})
            g["amount"] += r["amount"]
            g["count"] += 1

        for (t, cat, src, pm), g in groups.items():
            items.append({
                "type": t, "category": cat, "source": src,
                "payment_method": pm, "amount": g["amount"],
                "count": g["count"],
                "note": f"Copied from {month_label(src_month)}",
                "date": first_day.isoformat(),
            })
        items.sort(key=lambda i: i["amount"], reverse=True)
    else:
        for r in src_rows:
            try:
                day = int(str(r["date"])[8:10])
            except ValueError:
                day = 1
            day = min(max(day, 1), last_day.day)  # e.g. 31st -> 30th
            items.append({
                "type": r["type"], "category": r["category"],
                "source": r["source"], "payment_method": r["payment_method"],
                "amount": r["amount"], "count": 1,
                "note": r["note"] or "",
                "date": first_day.replace(day=day).isoformat(),
            })

    existing = Counter(
        (r["type"], r["category"], r["amount"], r["source"],
         r["payment_method"])
        for r in current_rows
    )
    for item in items:
        key = (item["type"], item["category"], item["amount"],
               item["source"], item["payment_method"])
        item["duplicate"] = existing[key] > 0
        if item["duplicate"]:
            existing[key] -= 1

    return items


# ---------------- PDF ----------------
def pdf_safe(value):
    """FPDF's built-in Helvetica uses Latin-1. Replace unsupported Unicode
    characters instead of letting PDF generation crash."""
    return str(value).encode("latin-1", errors="replace").decode("latin-1")


def generate_pdf(export_df, month, username):
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(
        0, 10, pdf_safe(f"Pocket Money Report - {month}"),
        new_x="LMARGIN", new_y="NEXT"
    )

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(
        0, 8, pdf_safe(f"User: {username}"),
        new_x="LMARGIN", new_y="NEXT"
    )
    pdf.ln(4)

    headers = ["Date", "Category", "Amount", "Payment", "Note", "Source"]
    col_widths = [28, 38, 30, 30, 100, 38]

    def draw_header():
        pdf.set_font("Helvetica", "B", 9)
        for width, header in zip(col_widths, headers):
            pdf.cell(width, 8, header, border=1)
        pdf.ln()
        pdf.set_font("Helvetica", "", 8)

    draw_header()

    for _, row in export_df.iterrows():
        if pdf.get_y() > 185:
            pdf.add_page()
            draw_header()

        txn_date = row["date"]
        if pd.notna(txn_date):
            date_text = (
                txn_date.strftime("%Y-%m-%d")
                if hasattr(txn_date, "strftime")
                else str(txn_date)
            )
        else:
            date_text = "-"

        sign = "+" if row["type"] == "income" else "-"
        payment = (
            str(row.get("payment_method", "Cash"))
            if row["type"] == "expense"
            else "N/A"
        )

        values = [
            date_text,
            str(row["category"])[:25],
            f"{sign}Rs {float(row['amount']):.2f}",
            payment,
            str(row["note"] or "")[:60],
            str(row["source"] or "-")[:25]
        ]

        for width, value in zip(col_widths, values):
            pdf.cell(width, 8, pdf_safe(value), border=1)
        pdf.ln()

    return bytes(pdf.output())