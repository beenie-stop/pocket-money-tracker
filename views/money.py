import altair as alt
import pandas as pd
import streamlit as st

import database
from ui_common import (
    DEFAULT_SOURCES, build_copy_candidates, ensure_sources, inr, month_data,
    month_label, new_month_card, payment_format
)

ctx = month_data()
user_id = ctx.user_id

st.subheader(f"💰 Money & Months · {month_label(ctx.month)}")

new_month_card(ctx, "money")

tab_received, tab_repeat, tab_history = st.tabs(
    ["💰 Money received", "🔁 Repeat last month", "📈 History"]
)

# =====================================================================
# Money received
# =====================================================================
with tab_received:
    source_amounts = {s["source"]: s["amount"] for s in ctx.sources}

    if "src_form_n" not in st.session_state:
        st.session_state.src_form_n = 0
    form_n = st.session_state.src_form_n

    # Default sources + any custom source already saved this month
    editable_sources = DEFAULT_SOURCES + [
        name for name in source_amounts if name not in DEFAULT_SOURCES
    ]

    st.markdown("**Edit a source** (sets the exact total received)")

    for name in editable_sources:
        current = float(source_amounts.get(name, 0))

        # Key includes the saved amount so the box refreshes after changes.
        amt = st.number_input(
            name, min_value=0.0, step=100.0, value=current,
            key=f"src_{name}_{current}"
        )

        save_col, del_col = st.columns(2)

        if save_col.button(f"Save {name}", key=f"src_save_{name}"):
            try:
                database.set_source_amount(
                    user_id, ctx.month, name, amt
                )
                st.toast(f"Saved {name}: {inr(amt)}")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        if name in source_amounts:
            if del_col.button(f"Remove {name}", key=f"src_del_{name}"):
                try:
                    database.delete_source(user_id, ctx.month, name)
                    st.toast(f"Removed {name}.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    st.divider()
    st.markdown("**Add more money**")
    st.caption(
        "If the name already exists (e.g. Savings), this amount is "
        "ADDED to what it already has. Nothing is overwritten."
    )

    custom_name = st.text_input(
        "Name (e.g. Savings, Uncle, Grandma)",
        key=f"custom_source_name_{form_n}"
    )
    custom_amt = st.number_input(
        "Amount to add", min_value=0.0, step=100.0,
        key=f"custom_source_amt_{form_n}"
    )

    if st.button("Add this amount"):
        if custom_name.strip() and custom_amt > 0:
            try:
                database.add_to_source_amount(
                    user_id, ctx.month, custom_name.strip(), custom_amt
                )
                st.session_state.src_form_n += 1
                st.toast(
                    f"Added {inr(custom_amt)} to {custom_name.strip()}!"
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        else:
            st.error("Enter a name and an amount above 0.")

# =====================================================================
# Repeat last month
# =====================================================================
with tab_repeat:
    st.caption(
        "Things don't carry over between months on their own. Pick what "
        f"you want again in {month_label(ctx.month)} and add it in one tap."
    )

    others = [
        m for m in database.get_available_months(user_id) if m != ctx.month
    ]

    if not others:
        st.info("There is no other month to copy from yet.")
    else:
        older = [m for m in others if m < ctx.month]
        src_month = st.selectbox(
            "Copy from",
            others,
            index=others.index(max(older)) if older else 0,
            format_func=month_label,
            key="copy_from"
        )

        mode = st.radio(
            "Copy as",
            ["Grouped totals", "Each transaction"],
            horizontal=True,
            key="copy_mode",
            help="Grouped totals adds ONE entry per category + source + "
                 "payment method, e.g. Miscellaneous ₹4,555. Each "
                 "transaction copies every entry separately."
        )

        candidates = build_copy_candidates(
            database.get_transactions_by_month(user_id, src_month),
            ctx.rows, ctx.month, src_month,
            grouped=(mode == "Grouped totals")
        )

        if not candidates:
            st.info(f"{month_label(src_month)} has nothing to copy.")
        else:
            table = pd.DataFrame({
                "Add": [not c["duplicate"] for c in candidates],
                "Type": [c["type"] for c in candidates],
                "Category": [c["category"] for c in candidates],
                "Source": [c["source"] or "—" for c in candidates],
                "Payment": [
                    payment_format(c["payment_method"])
                    if c["type"] == "expense" else "—"
                    for c in candidates
                ],
                "Amount (₹)": [float(c["amount"]) for c in candidates],
                "Entries": [c["count"] for c in candidates],
                "Date": [c["date"] for c in candidates],
                "Already added": [
                    "✓ already there" if c["duplicate"] else ""
                    for c in candidates
                ],
            })

            # A form, so ticking boxes doesn't re-run the app each time.
            # The key changes when the month's data changes, which resets
            # the ticks after you add something.
            with st.form("copy_form"):
                edited = st.data_editor(
                    table,
                    hide_index=True,
                    width="stretch",
                    disabled=[c for c in table.columns if c != "Add"],
                    column_config={
                        "Add": st.column_config.CheckboxColumn("Add?"),
                        "Amount (₹)": st.column_config.NumberColumn(
                            format="%.2f"
                        ),
                    },
                    key=(
                        f"copy_editor_{src_month}_{mode}_{ctx.month}_"
                        f"{len(ctx.rows)}"
                    )
                )

                submitted = st.form_submit_button(
                    f"➕ Add ticked rows to {month_label(ctx.month)}",
                    type="primary",
                    width="stretch"
                )

            if submitted:
                chosen = [
                    candidates[i] for i in edited.index[edited["Add"]]
                ]

                if not chosen:
                    st.warning("Tick at least one row first.")
                else:
                    try:
                        # Money added to a source that doesn't exist this
                        # month would be invisible in the balance cards.
                        ensure_sources(
                            user_id, ctx.month,
                            [c["source"] for c in chosen],
                            {s["source"] for s in ctx.sources}
                        )
                        database.add_transactions(user_id, chosen)
                        st.toast(
                            f"Added {len(chosen)} to "
                            f"{month_label(ctx.month)}."
                        )
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

            st.caption(
                "Dates are the same day of the month (Grouped totals use "
                "the 1st). You can edit any of them afterwards in "
                "Transactions. If a source has no money this month yet, "
                "add the money in the first tab."
            )

# =====================================================================
# History
# =====================================================================
with tab_history:
    summary = database.get_monthly_summary(user_id)

    if not summary:
        st.info("Nothing to show yet.")
    else:
        hist = pd.DataFrame(summary)
        for col in ("received", "income", "carried", "spent"):
            hist[col] = hist[col].astype(float)

        # Leftover carried in from last month is NOT new money, so it is
        # shown separately and left out of "Received" and "Saved".
        hist["Received"] = hist["received"] + hist["income"]
        hist["Saved"] = hist["Received"] - hist["spent"]
        hist["Saving rate"] = (
            (hist["Saved"] / hist["Received"] * 100)
            .where(hist["Received"] > 0)
        )

        if len(hist) > 1:
            avg_spent = hist["spent"].mean()
            avg_saved = hist["Saved"].mean()
            h1, h2 = st.columns(2)
            h1.metric("Average spent / month", inr(round(avg_spent, 2)))
            h2.metric("Average saved / month", inr(round(avg_saved, 2)))

        this_idx = hist.index[hist["month"] == ctx.month]
        if len(this_idx) and this_idx[0] + 1 < len(hist):
            now_row, prev_row = hist.loc[this_idx[0]], hist.loc[this_idx[0] + 1]
            if prev_row["spent"] > 0:
                change = (now_row["spent"] - prev_row["spent"]) / prev_row["spent"] * 100
                word = "more" if change >= 0 else "less"
                st.caption(
                    f"{month_label(ctx.month)}: spent {inr(now_row['spent'])}, "
                    f"{abs(change):.0f}% {word} than "
                    f"{month_label(prev_row['month'])} "
                    f"({inr(prev_row['spent'])})."
                )

        chart_data = (
            hist.assign(Month=hist["month"].map(month_label))
            .melt(
                id_vars=["Month", "month"],
                value_vars=["Received", "spent"],
                var_name="Type", value_name="Amount"
            )
            .replace({"spent": "Spent"})
            .sort_values("month")
        )

        st.altair_chart(
            alt.Chart(chart_data).mark_bar().encode(
                x=alt.X("Month:N", sort=alt.SortField("month")),
                xOffset="Type:N",
                y=alt.Y("Amount:Q", title="₹"),
                color=alt.Color("Type:N", legend=alt.Legend(title=None)),
                tooltip=["Month", "Type", "Amount"]
            ),
            width="stretch"
        )

        table = pd.DataFrame({
            "Month": hist["month"].map(month_label),
            "Received (₹)": hist["Received"],
            "Carried in (₹)": hist["carried"],
            "Spent (₹)": hist["spent"],
            "Saved (₹)": hist["Saved"],
            "Saving rate": hist["Saving rate"],
        })

        st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            column_config={
                "Saving rate": st.column_config.NumberColumn(format="%.0f%%"),
            }
        )
        st.caption(
            "Received = money from sources + other income. Leftover carried "
            "in from the previous month is shown separately, so it isn't "
            "counted as saved twice."
        )