import streamlit as st

from database import CARRY_OVER_CATEGORY
from ui_common import (
    inr, month_data, month_label, new_month_card, payment_format
)

ctx = month_data()

new_month_card(ctx, "home")

df = ctx.df

spent = df.loc[df["type"] == "expense", "amount"].sum()
extra_income = df.loc[df["type"] == "income", "amount"].sum()
carried = df.loc[
    (df["type"] == "income") & (df["category"] == CARRY_OVER_CATEGORY),
    "amount"
].sum()

received_total = ctx.total_budget + extra_income
remaining = received_total - spent

c1, c2, c3 = st.columns(3)
c1.metric("Received", inr(received_total))
c2.metric("Spent", inr(spent))
c3.metric("Remaining", inr(remaining))

if carried > 0:
    st.caption(f"Includes {inr(carried)} carried over from last month.")

if received_total > 0:
    ratio = float(spent / received_total)
    st.progress(
        min(max(ratio, 0.0), 1.0),
        text=f"{ratio * 100:.0f}% of the money spent"
    )

st.divider()

# ---------------- Balance by source ----------------
if ctx.sources:
    st.subheader("Balance by source")

    cols = st.columns(min(len(ctx.sources), 4))
    overspent = []

    for i, source_row in enumerate(ctx.sources):
        name = source_row["source"]
        source_received = (
            source_row["amount"] + ctx.income_by_source.get(name, 0)
        )
        left = source_received - ctx.spent_by_source.get(name, 0)

        cols[i % len(cols)].metric(
            name, inr(left),
            help=f"of {inr(source_received)} received"
        )

        if left < 0:
            overspent.append(name)

    if overspent:
        st.warning(
            "Spent more than received from: " + ", ".join(overspent)
            + ". If you got more money, add it in Money & Months."
        )
else:
    st.info(
        "No money received for "
        f"{month_label(ctx.month)} yet. Add it under Money & Months so "
        "you can track expenses against it."
    )
    st.page_link("views/money.py", label="Go to Money & Months", icon="💰")

st.divider()

# ---------------- Recent activity ----------------
st.subheader("Recent activity")

if df.empty:
    st.info("No transactions this month yet. Tap **➕ Add transaction**.")
else:
    for _, row in df.head(5).iterrows():
        is_income = row["type"] == "income"
        sign, color = ("+", "green") if is_income else ("-", "red")

        direction = "to" if is_income else "from"
        source_label = f" · {direction} {row['source']}" if row["source"] else ""
        payment_label = (
            f" · {payment_format(row['payment_method'])}"
            if not is_income else ""
        )

        with st.container(border=True):
            left_col, right_col = st.columns([3, 2], vertical_alignment="center")
            left_col.markdown(
                f"**{row['category']}**{source_label}{payment_label}  \n"
                f"{row['date'].strftime('%d %b')}"
                + (f" · {row['note']}" if row["note"] else "")
            )
            right_col.markdown(
                f":{color}[**{sign}{inr(row['amount'])}**]"
            )

    st.page_link(
        "views/transactions.py", label="See all transactions", icon="📋"
    )