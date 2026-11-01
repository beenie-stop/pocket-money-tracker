import altair as alt
import pandas as pd
import streamlit as st

from ui_common import inr, month_data, month_label

ctx = month_data()
df = ctx.df

st.subheader(f"📊 Insights · {month_label(ctx.month)}")

expense_df = df[df["type"] == "expense"].copy()

if expense_df.empty:
    st.info("No expenses this month yet, so there is nothing to chart.")
    st.stop()


def donut(data, theta, color, tooltip):
    return (
        alt.Chart(data)
        .mark_arc(innerRadius=60)
        .encode(
            theta=theta,
            color=alt.Color(color, legend=alt.Legend(title=None)),
            tooltip=tooltip
        )
    )


def with_percent(summary, amount_col="amount"):
    total = summary[amount_col].sum()
    summary["percent"] = (summary[amount_col] / total * 100).round(1)
    return summary


# Only the chosen view is built (tabs would build all three every click).
view = st.radio(
    "View",
    ["By category", "By payment method", "By source"],
    horizontal=True,
    label_visibility="collapsed",
    key="insights_view"
)

# ---------------- By category ----------------
if view == "By category":
    cat_summary = (
        expense_df.groupby("category")["amount"].sum().reset_index()
    )
    cat_summary = with_percent(cat_summary)

    st.altair_chart(
        donut(
            cat_summary, "amount:Q", "category:N",
            ["category", "amount", "percent"]
        ),
        width="stretch"
    )

    st.dataframe(
        cat_summary.sort_values("amount", ascending=False).rename(
            columns={
                "category": "Category",
                "amount": "Amount (₹)",
                "percent": "% of spending"
            }
        ),
        hide_index=True,
        width="stretch"
    )

# ---------------- By payment method ----------------
elif view == "By payment method":
    upi_spent = expense_df.loc[
        expense_df["payment_method"] == "UPI", "amount"
    ].sum()
    cash_spent = expense_df.loc[
        expense_df["payment_method"] == "Cash", "amount"
    ].sum()
    payment_total = upi_spent + cash_spent

    pm1, pm2, pm3 = st.columns(3)
    pm1.metric("📱 UPI", inr(upi_spent))
    pm2.metric("💵 Cash", inr(cash_spent))
    pm3.metric("Total", inr(payment_total))

    payment_summary = pd.DataFrame({
        "Payment Method": ["UPI", "Cash"],
        "Amount": [upi_spent, cash_spent],
    })
    payment_summary["Percentage"] = [
        round(float(a / payment_total * 100), 1) if payment_total > 0 else 0
        for a in payment_summary["Amount"]
    ]

    st.altair_chart(
        donut(
            payment_summary, "Amount:Q", "Payment Method:N",
            ["Payment Method", "Amount", "Percentage"]
        ),
        width="stretch"
    )

    detail_col1, detail_col2 = st.columns(2)

    for col, method, emoji in [
        (detail_col1, "UPI", "📱"), (detail_col2, "Cash", "💵")
    ]:
        with col:
            st.markdown(f"**{emoji} {method} spending**")
            pm_df = expense_df[expense_df["payment_method"] == method]

            if pm_df.empty:
                st.info(f"No {method} expenses.")
                continue

            pm_cat = (
                pm_df.groupby("category")["amount"].sum()
                .reset_index().sort_values("amount", ascending=False)
            )
            pm_cat = with_percent(pm_cat)

            st.dataframe(
                pm_cat.rename(columns={
                    "category": "Category",
                    "amount": "Amount (₹)",
                    "percent": f"% of {method}"
                }),
                hide_index=True,
                width="stretch"
            )

# ---------------- By source ----------------
else:
    src_spent = expense_df.groupby("source")["amount"].sum().to_dict()
    source_budget_map = {s["source"]: s["amount"] for s in ctx.sources}

    all_source_names = sorted(
        set(source_budget_map) | set(src_spent) | set(ctx.income_by_source)
    )

    src_rows = []
    for name in all_source_names:
        received = (
            source_budget_map.get(name, 0) + ctx.income_by_source.get(name, 0)
        )
        spent_amt = src_spent.get(name, 0)

        src_rows.append({
            "Source": name,
            "Received (₹)": received,
            "Spent (₹)": spent_amt,
            "Remaining (₹)": received - spent_amt,
            "% Used": (
                round(float(spent_amt / received * 100), 1)
                if received > 0 else 0
            ),
        })

    src_summary = (
        pd.DataFrame(src_rows).sort_values("Spent (₹)", ascending=False)
    )

    src_cols = st.columns(min(len(src_summary), 4))
    for i, (_, row) in enumerate(src_summary.iterrows()):
        src_cols[i % len(src_cols)].metric(
            row["Source"],
            f"{inr(row['Remaining (₹)'])} left",
            delta=f"-{inr(row['Spent (₹)'])} spent",
            delta_color="inverse"
        )

    if src_summary["Spent (₹)"].sum() > 0:
        st.altair_chart(
            donut(
                src_summary, "Spent (₹):Q", "Source:N",
                ["Source", "Spent (₹)", "Remaining (₹)", "% Used"]
            ),
            width="stretch"
        )

    st.dataframe(src_summary, hide_index=True, width="stretch")

    with st.expander("Category breakdown per source"):
        for name in src_summary["Source"]:
            source_df = expense_df[expense_df["source"] == name]
            if source_df.empty:
                continue

            st.markdown(f"**{name}**")
            source_cat = (
                source_df.groupby("category")["amount"].sum()
                .reset_index().sort_values("amount", ascending=False)
            )
            source_cat = with_percent(source_cat)

            st.dataframe(
                source_cat.rename(columns={
                    "category": "Category",
                    "amount": "Amount (₹)",
                    "percent": "% of source"
                }),
                hide_index=True,
                width="stretch"
            )