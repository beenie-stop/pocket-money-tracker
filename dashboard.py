
import streamlit as st
import pandas as pd
import altair as alt
from datetime import date
from fpdf import FPDF
import io
import database


CATEGORIES = ["Food", "Cab/Transport", "Groceries", "Rent", "Subscriptions",
              "Entertainment", "Shopping", "Health", "Education", "Miscellaneous", "Other"]

DEFAULT_SOURCES = ["Father", "Mother", "Relatives"]

PAYMENT_METHODS = ["UPI", "Cash"]


st.set_page_config(
    page_title="Pocket Money Tracker",
    page_icon="💸",
    layout="centered"
)

database.init_db()


# ---------------- Login / Signup ----------------

if "user_id" not in st.session_state:
    st.session_state.user_id = None
    st.session_state.username = None

if "editing_id" not in st.session_state:
    st.session_state.editing_id = None


if st.session_state.user_id is None:

    st.title("💸 Pocket Money Tracker")

    tab_login, tab_signup = st.tabs(["Log in", "Sign up"])

    with tab_login:

        with st.form("login_form"):

            username = st.text_input("Username")

            password = st.text_input(
                "Password",
                type="password"
            )

            submitted = st.form_submit_button("Log in")

            if submitted:

                user_id = database.verify_user(
                    username,
                    password
                )

                if user_id:

                    st.session_state.user_id = user_id
                    st.session_state.username = username.strip().lower()

                    st.rerun()

                else:

                    st.error(
                        "Incorrect username or password."
                    )


    with tab_signup:

        with st.form("signup_form"):

            new_username = st.text_input(
                "Choose a username"
            )

            new_password = st.text_input(
                "Choose a password",
                type="password"
            )

            confirm_password = st.text_input(
                "Confirm password",
                type="password"
            )

            submitted = st.form_submit_button(
                "Create account"
            )

            if submitted:

                if not new_username.strip() or not new_password:

                    st.error(
                        "Please fill in both fields."
                    )

                elif new_password != confirm_password:

                    st.error(
                        "Passwords don't match."
                    )

                else:

                    success, msg = database.create_user(
                        new_username,
                        new_password
                    )

                    if success:

                        st.success(
                            msg + " You can log in now."
                        )

                    else:

                        st.error(msg)

    st.stop()


# ---------------- Main app ----------------

user_id = st.session_state.user_id


top_col1, top_col2 = st.columns([4, 1])


with top_col1:

    st.title("💸 Pocket Money Tracker")

    st.caption(
        f"Logged in as **{st.session_state.username}**"
    )


with top_col2:

    if st.button("Log out"):

        st.session_state.user_id = None
        st.session_state.username = None

        st.rerun()


# ---- Month selector ----

months_available = database.get_available_months(
    user_id
)

current_month = date.today().strftime("%Y-%m")


if current_month not in months_available:

    months_available = [
        current_month
    ] + months_available


selected_month = st.selectbox(
    "Month",
    months_available,
    index=(
        months_available.index(current_month)
        if current_month in months_available
        else 0
    )
)


# ---- Money sources ----

st.subheader(
    "💰 Money received this month"
)


sources = database.get_sources_by_month(
    user_id,
    selected_month
)


source_amounts = {
    s["source"]: s["amount"]
    for s in sources
}


with st.expander(
    "Add / update money received",
    expanded=(len(sources) == 0)
):

    for name in DEFAULT_SOURCES:

        amt = st.number_input(
            f"{name}",
            min_value=0.0,
            step=100.0,
            value=float(
                source_amounts.get(name, 0.0)
            ),
            key=f"src_{name}"
        )

        if st.button(
            f"Save {name}",
            key=f"save_{name}"
        ):

            database.set_source_amount(
                user_id,
                selected_month,
                name,
                amt
            )

            st.success(
                f"Saved {name}'s contribution!"
            )

            st.rerun()


    st.markdown("**Someone else?**")


    custom_name = st.text_input(
        "Name (e.g. Uncle, Grandma)",
        key="custom_source_name"
    )


    custom_amt = st.number_input(
        "Amount",
        min_value=0.0,
        step=100.0,
        key="custom_source_amt"
    )


    if st.button("Add this source"):

        if custom_name.strip() and custom_amt > 0:

            database.set_source_amount(
                user_id,
                selected_month,
                custom_name.strip(),
                custom_amt
            )

            st.success(
                f"Added {custom_name}!"
            )

            st.rerun()

        else:

            st.error(
                "Enter a name and amount."
            )


sources = database.get_sources_by_month(
    user_id,
    selected_month
)


total_budget = sum(
    s["amount"]
    for s in sources
)


# ---- Load transactions ----

data = database.get_transactions_by_month(
    user_id,
    selected_month
)


df_all = (
    pd.DataFrame(data)
    if data
    else pd.DataFrame(
        columns=[
            "id",
            "type",
            "category",
            "amount",
            "note",
            "date",
            "source",
            "payment_method"
        ]
    )
)


# Existing transactions created before this feature
# are treated as Cash if payment_method is missing.

if "payment_method" not in df_all.columns:

    df_all["payment_method"] = "Cash"

else:

    df_all["payment_method"] = (
        df_all["payment_method"]
        .fillna("Cash")
        .replace("", "Cash")
    )


# ---- Balance by source ----

spent_by_source = {}


if not df_all.empty:

    expense_df_all = df_all[
        df_all["type"] == "expense"
    ]

    if not expense_df_all.empty:

        spent_by_source = (
            expense_df_all
            .groupby("source")["amount"]
            .sum()
            .to_dict()
        )


if sources:

    st.write("**Balance by source:**")

    cols = st.columns(
        len(sources)
    )

    for i, s in enumerate(sources):

        remaining = (
            s["amount"]
            - spent_by_source.get(
                s["source"],
                0
            )
        )

        cols[i].metric(
            s["source"],
            f"₹{remaining:,.0f}",
            help=(
                f"of ₹{s['amount']:,.0f} received"
            )
        )

else:

    st.info(
        "Add money received above so you can "
        "start tracking expenses against it."
    )


st.divider()


# ---- Add transaction ----

st.subheader(
    "➕ Add an expense"
)


source_names = (
    [s["source"] for s in sources]
    if sources
    else DEFAULT_SOURCES
)


with st.form(
    "add_form",
    clear_on_submit=True
):

    t_type = st.selectbox(
        "Type",
        ["expense", "income"]
    )


    spend_source = None

    if t_type == "expense":

        spend_source = st.selectbox(
            "Spend from",
            source_names
        )


    category = st.selectbox(
        "Category",
        CATEGORIES
    )


    custom_category = ""


    if category == "Other":

        custom_category = st.text_input(
            "Specify category"
        )


    # Payment method is required only for expenses.

    payment_method = None

    if t_type == "expense":

        payment_method = st.selectbox(
            "Payment Method",
            PAYMENT_METHODS,
            format_func=lambda x: (
                "📱 UPI"
                if x == "UPI"
                else "💵 Cash"
            )
        )


    amount = st.number_input(
        "Amount (₹)",
        min_value=0.0,
        step=10.0
    )


    note = st.text_input(
        "Note (optional)"
    )


    txn_date = st.date_input(
        "Date",
        value=date.today()
    )


    submitted = st.form_submit_button(
        "Add",
        use_container_width=True
    )


    if submitted:

        final_category = (
            custom_category.strip()
            if category == "Other"
            else category
        )


        if not final_category or amount <= 0:

            st.error(
                "Please choose a category and enter "
                "a valid amount."
            )

        else:

            database.add_transaction(
                user_id,
                t_type,
                final_category,
                amount,
                note,
                str(txn_date),
                spend_source,
                payment_method
            )

            st.success(
                "Added!"
            )

            st.rerun()


st.divider()


# ---- Overview ----

if df_all.empty:

    st.info(
        "No transactions for this month yet."
    )

else:

    df = df_all.copy()


    df["date"] = pd.to_datetime(
        df["date"]
    )


    spent = (
        df[df["type"] == "expense"]["amount"]
        .sum()
    )


    extra_income = (
        df[df["type"] == "income"]["amount"]
        .sum()
    )


    remaining = (
        total_budget
        + extra_income
        - spent
    )


    # ---- Main metrics ----

    c1, c2, c3 = st.columns(3)


    c1.metric(
        "Total Received",
        f"₹{total_budget:,.0f}"
    )


    c2.metric(
        "Spent",
        f"₹{spent:,.0f}"
    )


    c3.metric(
        "Remaining",
        f"₹{remaining:,.0f}"
    )


    if total_budget > 0:

        st.progress(
            min(
                spent / total_budget,
                1.0
            ),
            text=(
                f"{spent / total_budget * 100:.0f}% "
                "of total money spent"
            )
        )


    # ---- Payment method overview ----

    st.divider()

    st.subheader(
        "💳 Spending by payment method"
    )


    expense_df = df[
        df["type"] == "expense"
    ].copy()


    if not expense_df.empty:

        # Make sure older transactions
        # always have a payment method.

        expense_df["payment_method"] = (
            expense_df["payment_method"]
            .fillna("Cash")
            .replace("", "Cash")
        )


        upi_spent = (
            expense_df[
                expense_df["payment_method"] == "UPI"
            ]["amount"]
            .sum()
        )


        cash_spent = (
            expense_df[
                expense_df["payment_method"] == "Cash"
            ]["amount"]
            .sum()
        )


        payment_total = (
            upi_spent
            + cash_spent
        )


        pm1, pm2, pm3 = st.columns(3)


        pm1.metric(
            "📱 UPI Spent",
            f"₹{upi_spent:,.0f}"
        )


        pm2.metric(
            "💵 Cash Spent",
            f"₹{cash_spent:,.0f}"
        )


        pm3.metric(
            "Total Expense",
            f"₹{payment_total:,.0f}"
        )


        # ---- Payment method percentage ----

        if payment_total > 0:

            upi_percent = (
                upi_spent
                / payment_total
                * 100
            )

            cash_percent = (
                cash_spent
                / payment_total
                * 100
            )

        else:

            upi_percent = 0
            cash_percent = 0


        payment_summary = pd.DataFrame({
            "Payment Method": [
                "UPI",
                "Cash"
            ],
            "Amount": [
                upi_spent,
                cash_spent
            ],
            "Percentage": [
                round(upi_percent, 1),
                round(cash_percent, 1)
            ]
        })


        payment_chart = (
            alt.Chart(payment_summary)
            .mark_arc(innerRadius=60)
            .encode(
                theta=alt.Theta(
                    "Amount:Q"
                ),
                color=alt.Color(
                    "Payment Method:N",
                    legend=alt.Legend(
                        title="Payment Method"
                    )
                ),
                tooltip=[
                    "Payment Method",
                    "Amount",
                    "Percentage"
                ]
            )
        )


        st.altair_chart(
            payment_chart,
            use_container_width=True
        )


        st.dataframe(
            payment_summary.rename(
                columns={
                    "Payment Method":
                        "Payment Method",
                    "Amount":
                        "Amount (₹)",
                    "Percentage":
                        "% of spending"
                }
            ),
            hide_index=True,
            use_container_width=True
        )


        # ---- Detailed UPI / Cash spending ----

        st.subheader(
            "📋 Detailed spending by payment method"
        )


        detail_col1, detail_col2 = st.columns(2)


        # -------- UPI --------

        with detail_col1:

            st.markdown(
                "### 📱 UPI Spending"
            )


            upi_df = expense_df[
                expense_df["payment_method"]
                == "UPI"
            ]


            if not upi_df.empty:

                upi_category = (
                    upi_df
                    .groupby("category")["amount"]
                    .sum()
                    .reset_index()
                    .sort_values(
                        "amount",
                        ascending=False
                    )
                )


                upi_category["percent"] = (
                    upi_category["amount"]
                    / upi_category["amount"].sum()
                    * 100
                ).round(1)


                st.dataframe(
                    upi_category.rename(
                        columns={
                            "category":
                                "Category",
                            "amount":
                                "Amount (₹)",
                            "percent":
                                "% of UPI"
                        }
                    ),
                    hide_index=True,
                    use_container_width=True
                )


                st.caption(
                    f"Total spent through UPI: "
                    f"₹{upi_spent:,.0f}"
                )

            else:

                st.info(
                    "No UPI expenses recorded."
                )


        # -------- Cash --------

        with detail_col2:

            st.markdown(
                "### 💵 Cash Spending"
            )


            cash_df = expense_df[
                expense_df["payment_method"]
                == "Cash"
            ]


            if not cash_df.empty:

                cash_category = (
                    cash_df
                    .groupby("category")["amount"]
                    .sum()
                    .reset_index()
                    .sort_values(
                        "amount",
                        ascending=False
                    )
                )


                cash_category["percent"] = (
                    cash_category["amount"]
                    / cash_category["amount"].sum()
                    * 100
                ).round(1)


                st.dataframe(
                    cash_category.rename(
                        columns={
                            "category":
                                "Category",
                            "amount":
                                "Amount (₹)",
                            "percent":
                                "% of Cash"
                        }
                    ),
                    hide_index=True,
                    use_container_width=True
                )


                st.caption(
                    f"Total spent through Cash: "
                    f"₹{cash_spent:,.0f}"
                )

            else:

                st.info(
                    "No cash expenses recorded."
                )


        # ---- Spending by category ----

        st.divider()

        st.subheader(
            "📊 Spending by category"
        )


        cat_summary = (
            expense_df
            .groupby("category")["amount"]
            .sum()
            .reset_index()
        )


        cat_summary["percent"] = (
            cat_summary["amount"]
            / cat_summary["amount"].sum()
            * 100
        ).round(1)


        pie = (
            alt.Chart(cat_summary)
            .mark_arc(innerRadius=60)
            .encode(
                theta="amount",
                color=alt.Color(
                    "category",
                    legend=alt.Legend(
                        title="Category"
                    )
                ),
                tooltip=[
                    "category",
                    "amount",
                    "percent"
                ]
            )
        )


        st.altair_chart(
            pie,
            use_container_width=True
        )


        st.dataframe(
            cat_summary
            .sort_values(
                "amount",
                ascending=False
            )
            .rename(
                columns={
                    "category":
                        "Category",
                    "amount":
                        "Amount (₹)",
                    "percent":
                        "% of spending"
                }
            ),
            hide_index=True,
            use_container_width=True
        )


        # ---- Spending by source ----

        st.subheader(
            "👪 Spending by source"
        )


        src_summary = (
            expense_df
            .groupby("source")["amount"]
            .sum()
            .reset_index()
            .rename(
                columns={
                    "source":
                        "Source",
                    "amount":
                        "Amount (₹)"
                }
            )
        )


        st.dataframe(
            src_summary
            .sort_values(
                "Amount (₹)",
                ascending=False
            ),
            hide_index=True,
            use_container_width=True
        )


    else:

        st.write(
            "No expenses recorded this month."
        )


    st.divider()


    # ---- Search & Filter ----

    st.subheader(
        "🔍 Search & filter"
    )


    f1, f2 = st.columns(2)


    with f1:

        filter_categories = st.multiselect(
            "Category",
            options=sorted(
                df["category"].unique()
            )
        )


        filter_type = st.multiselect(
            "Type",
            options=[
                "income",
                "expense"
            ]
        )


    with f2:

        filter_source = st.multiselect(
            "Source",
            options=sorted(
                df["source"]
                .dropna()
                .unique()
            )
        )


        filter_payment = st.multiselect(
            "Payment Method",
            options=PAYMENT_METHODS,
            format_func=lambda x: (
                "📱 UPI"
                if x == "UPI"
                else "💵 Cash"
            )
        )


    keyword = st.text_input(
        "Search notes/category"
    )


    filtered_df = df.copy()


    if filter_categories:

        filtered_df = filtered_df[
            filtered_df["category"].isin(
                filter_categories
            )
        ]


    if filter_type:

        filtered_df = filtered_df[
            filtered_df["type"].isin(
                filter_type
            )
        ]


    if filter_source:

        filtered_df = filtered_df[
            filtered_df["source"].isin(
                filter_source
            )
        ]


    if filter_payment:

        filtered_df = filtered_df[
            filtered_df["payment_method"].isin(
                filter_payment
            )
        ]


    if keyword:

        kw = keyword.lower()


        filtered_df = filtered_df[
            filtered_df["note"]
            .fillna("")
            .str.lower()
            .str.contains(
                kw,
                na=False
            )
            |
            filtered_df["category"]
            .fillna("")
            .str.lower()
            .str.contains(
                kw,
                na=False
            )
        ]


    # ---- Export ----

    st.subheader(
        "⬇️ Export"
    )


    exp_col1, exp_col2 = st.columns(2)


    with exp_col1:

        csv_data = (
            filtered_df
            .drop(
                columns=["id"],
                errors="ignore"
            )
            .to_csv(
                index=False
            )
            .encode("utf-8")
        )


        st.download_button(
            "Download CSV",
            csv_data,
            file_name=(
                f"transactions_{selected_month}.csv"
            ),
            mime="text/csv",
            use_container_width=True
        )


    with exp_col2:

        def generate_pdf(
            export_df,
            month,
            username
        ):

            pdf = FPDF()

            pdf.add_page()

            pdf.set_font(
                "Helvetica",
                "B",
                16
            )


            pdf.cell(
                0,
                10,
                f"Pocket Money Report - {month}",
                ln=True
            )


            pdf.set_font(
                "Helvetica",
                "",
                10
            )


            pdf.cell(
                0,
                8,
                f"User: {username}",
                ln=True
            )


            pdf.ln(4)


            # Date, Category, Amount, Payment,
            # Note, Source

            col_widths = [
                24,
                32,
                24,
                28,
                58,
                28
            ]


            headers = [
                "Date",
                "Category",
                "Amount",
                "Payment",
                "Note",
                "Source"
            ]


            pdf.set_font(
                "Helvetica",
                "B",
                9
            )


            for w, h in zip(
                col_widths,
                headers
            ):

                pdf.cell(
                    w,
                    8,
                    h,
                    border=1
                )


            pdf.ln()


            pdf.set_font(
                "Helvetica",
                "",
                8
            )


            for _, row in export_df.iterrows():

                pdf.cell(
                    col_widths[0],
                    8,
                    str(
                        row["date"].date()
                    ),
                    border=1
                )


                pdf.cell(
                    col_widths[1],
                    8,
                    str(
                        row["category"]
                    )[:18],
                    border=1
                )


                sign = (
                    "+"
                    if row["type"] == "income"
                    else "-"
                )


                pdf.cell(
                    col_widths[2],
                    8,
                    f"{sign}Rs {row['amount']:.0f}",
                    border=1
                )


                payment = (
                    str(
                        row.get(
                            "payment_method",
                            "Cash"
                        )
                    )
                    if row["type"] == "expense"
                    else "N/A"
                )


                pdf.cell(
                    col_widths[3],
                    8,
                    payment,
                    border=1
                )


                pdf.cell(
                    col_widths[4],
                    8,
                    str(
                        row["note"] or ""
                    )[:32],
                    border=1
                )


                pdf.cell(
                    col_widths[5],
                    8,
                    str(
                        row["source"] or "-"
                    )[:18],
                    border=1
                )


                pdf.ln()


            return bytes(
                pdf.output()
            )


        pdf_bytes = generate_pdf(
            filtered_df,
            selected_month,
            st.session_state.username
        )


        st.download_button(
            "Download PDF",
            pdf_bytes,
            file_name=(
                f"report_{selected_month}.pdf"
            ),
            mime="application/pdf",
            use_container_width=True
        )


    st.divider()


    # ---- Transactions ----

    st.subheader(
        "📋 Transactions"
    )


    if filtered_df.empty:

        st.write(
            "No transactions match your filters."
        )


    for _, row in filtered_df.iterrows():

        is_editing = (
            st.session_state.editing_id
            == row["id"]
        )


        if is_editing:

            with st.form(
                f"edit_form_{row['id']}"
            ):

                st.markdown(
                    f"**Editing transaction #{row['id']}**"
                )


                e_type = st.selectbox(
                    "Type",
                    [
                        "expense",
                        "income"
                    ],
                    index=(
                        0
                        if row["type"] == "expense"
                        else 1
                    ),
                    key=f"etype_{row['id']}"
                )


                e_category = st.selectbox(
                    "Category",
                    CATEGORIES,
                    index=(
                        CATEGORIES.index(
                            row["category"]
                        )
                        if row["category"]
                        in CATEGORIES
                        else len(CATEGORIES) - 1
                    ),
                    key=f"ecat_{row['id']}"
                )


                e_payment_method = None

                if e_type == "expense":

                    current_payment = (
                        row.get(
                            "payment_method",
                            "Cash"
                        )
                        or "Cash"
                    )


                    if current_payment not in PAYMENT_METHODS:

                        current_payment = "Cash"


                    e_payment_method = st.selectbox(
                        "Payment Method",
                        PAYMENT_METHODS,
                        index=PAYMENT_METHODS.index(
                            current_payment
                        ),
                        format_func=lambda x: (
                            "📱 UPI"
                            if x == "UPI"
                            else "💵 Cash"
                        ),
                        key=f"epayment_{row['id']}"
                    )


                e_amount = st.number_input(
                    "Amount (₹)",
                    min_value=0.0,
                    step=10.0,
                    value=float(
                        row["amount"]
                    ),
                    key=f"eamt_{row['id']}"
                )


                e_note = st.text_input(
                    "Note",
                    value=row["note"] or "",
                    key=f"enote_{row['id']}"
                )


                e_date = st.date_input(
                    "Date",
                    value=row["date"].date(),
                    key=f"edate_{row['id']}"
                )


                e_source = (
                    st.selectbox(
                        "Source",
                        source_names,
                        index=(
                            source_names.index(
                                row["source"]
                            )
                            if row["source"]
                            in source_names
                            else 0
                        ),
                        key=f"esrc_{row['id']}"
                    )
                    if e_type == "expense"
                    else None
                )


                col_save, col_cancel = st.columns(2)


                save = col_save.form_submit_button(
                    "💾 Save",
                    use_container_width=True
                )


                cancel = col_cancel.form_submit_button(
                    "Cancel",
                    use_container_width=True
                )


                if save:

                    database.update_transaction(
                        user_id,
                        row["id"],
                        e_type,
                        e_category,
                        e_amount,
                        e_note,
                        str(e_date),
                        e_source,
                        e_payment_method
                    )


                    st.session_state.editing_id = None

                    st.rerun()


                if cancel:

                    st.session_state.editing_id = None

                    st.rerun()


        else:

            with st.container(
                border=True
            ):

                col1, col2, col3 = st.columns(
                    [4, 1, 1]
                )


                with col1:

                    sign = (
                        "+"
                        if row["type"] == "income"
                        else "-"
                    )


                    color = (
                        "green"
                        if row["type"] == "income"
                        else "red"
                    )


                    source_label = (
                        f" · from {row['source']}"
                        if row.get("source")
                        else ""
                    )


                    if row["type"] == "expense":

                        payment_method = (
                            row.get(
                                "payment_method",
                                "Cash"
                            )
                            or "Cash"
                        )


                        if payment_method == "UPI":

                            payment_label = "📱 UPI"

                        else:

                            payment_label = "💵 Cash"


                    else:

                        payment_label = ""


                    st.markdown(
                        f"**{row['category']}**"
                        f"{source_label}"
                        f" · {payment_label}"
                        f" · {row['date'].strftime('%d %b')}"
                    )


                    st.markdown(
                        f":{color}["
                        f"{sign}₹{row['amount']:,.0f}"
                        f"]  \n"
                        f"{row['note'] or ''}"
                    )


                with col2:

                    if st.button(
                        "✏️",
                        key=f"edit_{row['id']}"
                    ):

                        st.session_state.editing_id = (
                            row["id"]
                        )

                        st.rerun()


                with col3:

                    if st.button(
                        "🗑️",
                        key=f"del_{row['id']}"
                    ):

                        database.delete_transaction(
                            user_id,
                            row["id"]
                        )

                        st.rerun()
