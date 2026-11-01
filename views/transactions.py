from datetime import date

import pandas as pd
import streamlit as st

import database
from ui_common import (
    PAGE_SIZE, PAYMENT_METHODS, categories_for, inr, month_data,
    month_label, payment_format
)

ctx = month_data()
user_id = ctx.user_id
df = ctx.df

st.subheader(f"📋 Transactions · {month_label(ctx.month)}")

if df.empty:
    st.info("No transactions this month yet. Tap **➕ Add transaction**.")
    st.stop()

# ---------------- Search & filter ----------------
with st.expander("🔍 Search & filter"):
    f1, f2 = st.columns(2)

    with f1:
        filter_categories = st.multiselect(
            "Category", options=sorted(df["category"].dropna().unique())
        )
        filter_type = st.multiselect("Type", options=["income", "expense"])

    with f2:
        filter_source = st.multiselect(
            "Source", options=sorted(df["source"].dropna().unique())
        )
        filter_payment = st.multiselect(
            "Payment Method", options=PAYMENT_METHODS,
            format_func=payment_format
        )

    keyword = st.text_input("Search notes/category")

filtered_df = df.copy()

if filter_categories:
    filtered_df = filtered_df[filtered_df["category"].isin(filter_categories)]

if filter_type:
    filtered_df = filtered_df[filtered_df["type"].isin(filter_type)]

if filter_source:
    filtered_df = filtered_df[filtered_df["source"].isin(filter_source)]

if filter_payment:
    filtered_df = filtered_df[
        filtered_df["payment_method"].isin(filter_payment)
    ]

kw = keyword.strip()
if kw:
    filtered_df = filtered_df[
        filtered_df["note"].fillna("").astype(str)
        .str.contains(kw, case=False, regex=False, na=False)
        |
        filtered_df["category"].fillna("").astype(str)
        .str.contains(kw, case=False, regex=False, na=False)
    ]

st.caption(f"{len(filtered_df)} of {len(df)} transactions")

if filtered_df.empty:
    st.write("No transactions match your filters.")

limit = st.session_state.get("txn_limit", PAGE_SIZE)

# Rendering hundreds of rows (each with columns + buttons) is slow, so only
# the newest PAGE_SIZE are drawn until "Show more" is pressed.
for _, row in filtered_df.head(limit).iterrows():
    row_id = int(row["id"])
    is_editing = st.session_state.editing_id == row_id

    if is_editing:
        with st.container(border=True):
            st.markdown(f"**Editing transaction #{row_id}**")

            # Type and Category are outside the form so that choosing
            # "Other" / "income" immediately updates the fields below.
            e_type = st.selectbox(
                "Type", ["expense", "income"],
                index=0 if row["type"] == "expense" else 1,
                key=f"etype_{row_id}"
            )

            cats = categories_for(e_type)
            existing_category = str(row["category"] or "")
            category_index = (
                cats.index(existing_category)
                if existing_category in cats
                else cats.index("Other")
            )

            e_category = st.selectbox(
                "Category", cats, index=category_index,
                key=f"ecat_{row_id}_{e_type}"
            )

            with st.form(f"edit_form_{row_id}"):
                custom_edit_category = ""

                if e_category == "Other":
                    custom_edit_category = st.text_input(
                        "Specify category",
                        value=(
                            existing_category
                            if existing_category not in cats else ""
                        ),
                        key=f"ecustomcat_{row_id}"
                    )

                e_payment_method = None

                if e_type == "expense":
                    current_payment = (
                        row.get("payment_method", "Cash") or "Cash"
                    )
                    if current_payment not in PAYMENT_METHODS:
                        current_payment = "Cash"

                    e_payment_method = st.selectbox(
                        "Payment Method", PAYMENT_METHODS,
                        index=PAYMENT_METHODS.index(current_payment),
                        format_func=payment_format,
                        key=f"epayment_{row_id}"
                    )

                e_amount = st.number_input(
                    "Amount (₹)", min_value=0.0, step=10.0,
                    value=float(row["amount"]), key=f"eamt_{row_id}"
                )

                e_note = st.text_input(
                    "Note", value=row["note"] or "", key=f"enote_{row_id}"
                )

                e_date = st.date_input(
                    "Date",
                    value=(
                        row["date"].date()
                        if pd.notna(row["date"]) else date.today()
                    ),
                    key=f"edate_{row_id}"
                )

                # Expense: spent FROM a source. Income: added TO a source
                # (old income rows may have none, so allow "— none —").
                src_options = (
                    ctx.source_names
                    if e_type == "expense"
                    else [None] + ctx.source_names
                )
                if row["source"] in ctx.source_names:
                    current_src = row["source"]
                else:
                    current_src = (
                        ctx.source_names[0] if e_type == "expense" else None
                    )

                e_source = st.selectbox(
                    "Spend from" if e_type == "expense" else "Add money to",
                    src_options,
                    index=src_options.index(current_src),
                    format_func=lambda s: "— none —" if s is None else s,
                    key=f"esrc_{row_id}_{e_type}"
                )

                col_save, col_cancel = st.columns(2)

                if col_save.form_submit_button("💾 Save", width="stretch"):
                    final_category = (
                        custom_edit_category.strip()
                        if e_category == "Other" else e_category
                    )

                    if not final_category:
                        st.error("Please specify a category.")
                    elif e_amount <= 0:
                        st.error("Amount must be greater than zero.")
                    else:
                        try:
                            database.update_transaction(
                                user_id, row_id, e_type, final_category,
                                e_amount, e_note, str(e_date), e_source,
                                e_payment_method
                            )
                            st.session_state.editing_id = None
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))

                if col_cancel.form_submit_button("Cancel", width="stretch"):
                    st.session_state.editing_id = None
                    st.rerun()

    else:
        with st.container(border=True):
            col1, col2, col3 = st.columns([4, 1, 1])

            with col1:
                is_income = row["type"] == "income"
                sign = "+" if is_income else "-"
                color = "green" if is_income else "red"

                source_label = (
                    f" · {'to' if is_income else 'from'} {row['source']}"
                    if row.get("source") else ""
                )
                payment_label = (
                    ""
                    if is_income
                    else payment_format(
                        row.get("payment_method", "Cash") or "Cash"
                    )
                )

                st.markdown(
                    f"**{row['category']}**{source_label} · "
                    f"{payment_label} · {row['date'].strftime('%d %b')}"
                )
                st.markdown(
                    f":{color}[{sign}{inr(row['amount'])}]  \n"
                    f"{row['note'] or ''}"
                )

            with col2:
                if st.button("✏️", key=f"edit_{row_id}"):
                    st.session_state.editing_id = row_id
                    st.rerun()

            with col3:
                if st.button("🗑️", key=f"del_{row_id}"):
                    try:
                        database.delete_transaction(user_id, row_id)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

remaining_rows = len(filtered_df) - limit
if remaining_rows > 0:
    if st.button(f"Show more ({remaining_rows} more)", width="stretch"):
        st.session_state.txn_limit = limit + PAGE_SIZE
        st.rerun()