import streamlit as st
import pandas as pd
import altair as alt
from datetime import date
from fpdf import FPDF
from streamlit_cookies_controller import CookieController
import database

CATEGORIES = ["Food", "Cab/Transport", "Groceries", "Rent", "Subscriptions",
              "Entertainment", "Shopping", "Health", "Education", "Miscellaneous", "Other"]
DEFAULT_SOURCES = ["Father", "Mother", "Relatives"]
PAYMENT_METHODS = ["UPI", "Cash"]

st.set_page_config(page_title="Pocket Money Tracker", page_icon="💸", layout="centered")
database.init_db()
cookies = CookieController()

# ---------------- Session state + auto-login from cookie ----------------
if "user_id" not in st.session_state:
    st.session_state.user_id = None
    st.session_state.username = None
if "editing_id" not in st.session_state:
    st.session_state.editing_id = None

if st.session_state.user_id is None:
    token = cookies.get("session_token")
    if token:
        remembered_id = database.get_user_id_from_token(token)
        if remembered_id:
            st.session_state.user_id = remembered_id
            st.session_state.username = database.get_username_by_id(remembered_id)

# ---------------- Login / Signup ----------------
if st.session_state.user_id is None:
    st.title("💸 Pocket Money Tracker")
    tab_login, tab_signup = st.tabs(["Log in", "Sign up"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            remember = st.checkbox("Keep me logged in", value=True)
            if st.form_submit_button("Log in"):
                user_id = database.verify_user(username, password)
                if user_id:
                    st.session_state.user_id = user_id
                    st.session_state.username = username.strip().lower()
                    if remember:
                        cookies.set("session_token", database.create_session(user_id))
                    st.rerun()
                else:
                    st.error("Incorrect username or password.")

    with tab_signup:
        with st.form("signup_form"):
            new_username = st.text_input("Choose a username")
            new_password = st.text_input("Choose a password", type="password")
            confirm_password = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Create account"):
                if not new_username.strip() or not new_password:
                    st.error("Please fill in both fields.")
                elif new_password != confirm_password:
                    st.error("Passwords don't match.")
                else:
                    success, msg = database.create_user(new_username, new_password)
                    st.success(msg + " You can log in now.") if success else st.error(msg)
    st.stop()

# ---------------- Main app ----------------
user_id = st.session_state.user_id

top_col1, top_col2 = st.columns([4, 1])
with top_col1:
    st.title("💸 Pocket Money Tracker")
    st.caption(f"Logged in as **{st.session_state.username}**")
with top_col2:
    if st.button("Log out"):
        token = cookies.get("session_token")
        if token:
            database.delete_session(token)
            cookies.remove("session_token")
        st.session_state.user_id = None
        st.session_state.username = None
        st.rerun()

# ---- Month selector ----
months_available = database.get_available_months(user_id)
current_month = date.today().strftime("%Y-%m")
if current_month not in months_available:
    months_available = [current_month] + months_available
selected_month = st.selectbox(
    "Month", months_available,
    index=months_available.index(current_month) if current_month in months_available else 0
)

# ---- Money sources ----
st.subheader("💰 Money received this month")
sources = database.get_sources_by_month(user_id, selected_month)
source_amounts = {s["source"]: s["amount"] for s in sources}

with st.expander("Add / update money received", expanded=(len(sources) == 0)):
    for name in DEFAULT_SOURCES:
        amt = st.number_input(name, min_value=0.0, step=100.0,
                               value=float(source_amounts.get(name, 0.0)), key=f"src_{name}")
        if st.button(f"Save {name}", key=f"save_{name}"):
            database.set_source_amount(user_id, selected_month, name, amt)
            st.success(f"Saved {name}'s contribution!")
            st.rerun()

    st.markdown("**Someone else?**")
    custom_name = st.text_input("Name (e.g. Uncle, Grandma)", key="custom_source_name")
    custom_amt = st.number_input("Amount", min_value=0.0, step=100.0, key="custom_source_amt")
    if st.button("Add this source"):
        if custom_name.strip() and custom_amt > 0:
            database.set_source_amount(user_id, selected_month, custom_name.strip(), custom_amt)
            st.success(f"Added {custom_name}!")
            st.rerun()
        else:
            st.error("Enter a name and amount.")

sources = database.get_sources_by_month(user_id, selected_month)
total_budget = sum(s["amount"] for s in sources)

# ---- Load transactions ----
data = database.get_transactions_by_month(user_id, selected_month)
df_all = pd.DataFrame(data) if data else pd.DataFrame(
    columns=["id", "type", "category", "amount", "note", "date", "source", "payment_method"])

if "payment_method" not in df_all.columns:
    df_all["payment_method"] = "Cash"
else:
    df_all["payment_method"] = df_all["payment_method"].fillna("Cash").replace("", "Cash")

# ---- Balance by source ----
spent_by_source = {}
if not df_all.empty:
    expense_df_all = df_all[df_all["type"] == "expense"]
    if not expense_df_all.empty:
        spent_by_source = expense_df_all.groupby("source")["amount"].sum().to_dict()

if sources:
    st.write("**Balance by source:**")
    cols = st.columns(len(sources))
    for i, s in enumerate(sources):
        remaining = s["amount"] - spent_by_source.get(s["source"], 0)
        cols[i].metric(s["source"], f"₹{remaining:,.0f}", help=f"of ₹{s['amount']:,.0f} received")
else:
    st.info("Add money received above so you can start tracking expenses against it.")

st.divider()

# ---- Add transaction ----
st.subheader("➕ Add an expense")
source_names = [s["source"] for s in sources] if sources else DEFAULT_SOURCES

with st.form("add_form", clear_on_submit=True):
    t_type = st.selectbox("Type", ["expense", "income"])
    spend_source = st.selectbox("Spend from", source_names) if t_type == "expense" else None
    category = st.selectbox("Category", CATEGORIES)
    custom_category = st.text_input("Specify category") if category == "Other" else ""
    payment_method = None
    if t_type == "expense":
        payment_method = st.selectbox("Payment Method", PAYMENT_METHODS,
                                       format_func=lambda x: "📱 UPI" if x == "UPI" else "💵 Cash")
    amount = st.number_input("Amount (₹)", min_value=0.0, step=10.0)
    note = st.text_input("Note (optional)")
    txn_date = st.date_input("Date", value=date.today())

    if st.form_submit_button("Add", use_container_width=True):
        final_category = custom_category.strip() if category == "Other" else category
        if not final_category or amount <= 0:
            st.error("Please choose a category and enter a valid amount.")
        else:
            database.add_transaction(user_id, t_type, final_category, amount, note,
                                      str(txn_date), spend_source, payment_method)
            st.success("Added!")
            st.rerun()

st.divider()

# ---- Overview ----
if df_all.empty:
    st.info("No transactions for this month yet.")
else:
    df = df_all.copy()
    df["date"] = pd.to_datetime(df["date"])
    spent = df[df["type"] == "expense"]["amount"].sum()
    extra_income = df[df["type"] == "income"]["amount"].sum()
    remaining = total_budget + extra_income - spent

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Received", f"₹{total_budget:,.0f}")
    c2.metric("Spent", f"₹{spent:,.0f}")
    c3.metric("Remaining", f"₹{remaining:,.0f}")
    if total_budget > 0:
        st.progress(min(spent / total_budget, 1.0),
                    text=f"{spent / total_budget * 100:.0f}% of total money spent")

    expense_df = df[df["type"] == "expense"].copy()
    expense_df["payment_method"] = expense_df["payment_method"].fillna("Cash").replace("", "Cash")

    # ---- Payment method overview ----
    st.divider()
    st.subheader("💳 Spending by payment method")

    if not expense_df.empty:
        upi_spent = expense_df[expense_df["payment_method"] == "UPI"]["amount"].sum()
        cash_spent = expense_df[expense_df["payment_method"] == "Cash"]["amount"].sum()
        payment_total = upi_spent + cash_spent

        pm1, pm2, pm3 = st.columns(3)
        pm1.metric("📱 UPI Spent", f"₹{upi_spent:,.0f}")
        pm2.metric("💵 Cash Spent", f"₹{cash_spent:,.0f}")
        pm3.metric("Total Expense", f"₹{payment_total:,.0f}")

        upi_pct = round(upi_spent / payment_total * 100, 1) if payment_total > 0 else 0
        cash_pct = round(cash_spent / payment_total * 100, 1) if payment_total > 0 else 0
        payment_summary = pd.DataFrame({
            "Payment Method": ["UPI", "Cash"], "Amount": [upi_spent, cash_spent],
            "Percentage": [upi_pct, cash_pct]
        })

        payment_chart = alt.Chart(payment_summary).mark_arc(innerRadius=60).encode(
            theta="Amount:Q", color=alt.Color("Payment Method:N", legend=alt.Legend(title="Payment Method")),
            tooltip=["Payment Method", "Amount", "Percentage"]
        )
        st.altair_chart(payment_chart, use_container_width=True)
        st.dataframe(payment_summary.rename(columns={"Amount": "Amount (₹)", "Percentage": "% of spending"}),
                     hide_index=True, use_container_width=True)

        st.subheader("📋 Detailed spending by payment method")
        detail_col1, detail_col2 = st.columns(2)
        for col, method, emoji in [(detail_col1, "UPI", "📱"), (detail_col2, "Cash", "💵")]:
            with col:
                st.markdown(f"### {emoji} {method} Spending")
                pm_df = expense_df[expense_df["payment_method"] == method]
                if not pm_df.empty:
                    pm_cat = pm_df.groupby("category")["amount"].sum().reset_index().sort_values("amount", ascending=False)
                    pm_cat["percent"] = (pm_cat["amount"] / pm_cat["amount"].sum() * 100).round(1)
                    st.dataframe(pm_cat.rename(columns={"category": "Category", "amount": "Amount (₹)", "percent": f"% of {method}"}),
                                 hide_index=True, use_container_width=True)
                    st.caption(f"Total spent through {method}: ₹{pm_df['amount'].sum():,.0f}")
                else:
                    st.info(f"No {method} expenses recorded.")

        # ---- Spending by category ----
        st.divider()
        st.subheader("📊 Spending by category")
        cat_summary = expense_df.groupby("category")["amount"].sum().reset_index()
        cat_summary["percent"] = (cat_summary["amount"] / cat_summary["amount"].sum() * 100).round(1)
        pie = alt.Chart(cat_summary).mark_arc(innerRadius=60).encode(
            theta="amount", color=alt.Color("category", legend=alt.Legend(title="Category")),
            tooltip=["category", "amount", "percent"]
        )
        st.altair_chart(pie, use_container_width=True)
        st.dataframe(cat_summary.sort_values("amount", ascending=False).rename(
            columns={"category": "Category", "amount": "Amount (₹)", "percent": "% of spending"}),
            hide_index=True, use_container_width=True)

        # ---- Spending by source (expanded) ----
        st.divider()
        st.subheader("👪 Spending by source")

        src_spent = expense_df.groupby("source")["amount"].sum().to_dict()
        source_budget_map = {s["source"]: s["amount"] for s in sources}
        all_source_names = sorted(set(list(source_budget_map.keys()) + list(src_spent.keys())))

        src_rows = []
        for s in all_source_names:
            received = source_budget_map.get(s, 0)
            spent_amt = src_spent.get(s, 0)
            left = received - spent_amt
            pct_used = round((spent_amt / received * 100), 1) if received > 0 else 0
            src_rows.append({
                "Source": s, "Received (₹)": received, "Spent (₹)": spent_amt,
                "Remaining (₹)": left, "% Used": pct_used
            })
        src_summary = pd.DataFrame(src_rows).sort_values("Spent (₹)", ascending=False)

        if not src_summary.empty:
            src_cols = st.columns(len(src_summary))
            for i, r in src_summary.iterrows():
                src_cols[list(src_summary.index).index(i)].metric(
                    r["Source"], f"₹{r['Remaining (₹)']:,.0f} left",
                    delta=f"-₹{r['Spent (₹)']:,.0f} spent", delta_color="inverse"
                )

            src_pie = alt.Chart(src_summary).mark_arc(innerRadius=60).encode(
                theta="Spent (₹):Q", color=alt.Color("Source:N", legend=alt.Legend(title="Source")),
                tooltip=["Source", "Spent (₹)", "Remaining (₹)", "% Used"]
            )
            st.altair_chart(src_pie, use_container_width=True)
            st.dataframe(src_summary, hide_index=True, use_container_width=True)

            with st.expander("See category breakdown per source"):
                for s in src_summary["Source"]:
                    s_df = expense_df[expense_df["source"] == s]
                    if s_df.empty:
                        continue
                    st.markdown(f"**{s}**")
                    s_cat = s_df.groupby("category")["amount"].sum().reset_index().sort_values("amount", ascending=False)
                    s_cat["percent"] = (s_cat["amount"] / s_cat["amount"].sum() * 100).round(1)
                    st.dataframe(s_cat.rename(columns={"category": "Category", "amount": "Amount (₹)", "percent": "% of source"}),
                                 hide_index=True, use_container_width=True)
    # ---- Search & Filter ----
    st.subheader("🔍 Search & filter")
    f1, f2 = st.columns(2)
    with f1:
        filter_categories = st.multiselect("Category", options=sorted(df["category"].unique()))
        filter_type = st.multiselect("Type", options=["income", "expense"])
    with f2:
        filter_source = st.multiselect("Source", options=sorted(df["source"].dropna().unique()))
        filter_payment = st.multiselect("Payment Method", options=PAYMENT_METHODS,
                                         format_func=lambda x: "📱 UPI" if x == "UPI" else "💵 Cash")
    keyword = st.text_input("Search notes/category")

    filtered_df = df.copy()
    if filter_categories:
        filtered_df = filtered_df[filtered_df["category"].isin(filter_categories)]
    if filter_type:
        filtered_df = filtered_df[filtered_df["type"].isin(filter_type)]
    if filter_source:
        filtered_df = filtered_df[filtered_df["source"].isin(filter_source)]
    if filter_payment:
        filtered_df = filtered_df[filtered_df["payment_method"].isin(filter_payment)]
    if keyword:
        kw = keyword.lower()
        filtered_df = filtered_df[
            filtered_df["note"].fillna("").str.lower().str.contains(kw, na=False) |
            filtered_df["category"].fillna("").str.lower().str.contains(kw, na=False)
        ]

    # ---- Export ----
    st.subheader("⬇️ Export")
    exp_col1, exp_col2 = st.columns(2)
    with exp_col1:
        csv_data = filtered_df.drop(columns=["id"], errors="ignore").to_csv(index=False).encode("utf-8")
        st.download_button("Download CSV", csv_data, file_name=f"transactions_{selected_month}.csv",
                            mime="text/csv", use_container_width=True)
    with exp_col2:
        def generate_pdf(export_df, month, username):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(0, 10, f"Pocket Money Report - {month}", ln=True)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 8, f"User: {username}", ln=True)
            pdf.ln(4)
            col_widths = [24, 32, 24, 28, 58, 28]
            headers = ["Date", "Category", "Amount", "Payment", "Note", "Source"]
            pdf.set_font("Helvetica", "B", 9)
            for w, h in zip(col_widths, headers):
                pdf.cell(w, 8, h, border=1)
            pdf.ln()
            pdf.set_font("Helvetica", "", 8)
            for _, row in export_df.iterrows():
                pdf.cell(col_widths[0], 8, str(row["date"].date()), border=1)
                pdf.cell(col_widths[1], 8, str(row["category"])[:18], border=1)
                sign = "+" if row["type"] == "income" else "-"
                pdf.cell(col_widths[2], 8, f"{sign}Rs {row['amount']:.0f}", border=1)
                payment = str(row.get("payment_method", "Cash")) if row["type"] == "expense" else "N/A"
                pdf.cell(col_widths[3], 8, payment, border=1)
                pdf.cell(col_widths[4], 8, str(row["note"] or "")[:32], border=1)
                pdf.cell(col_widths[5], 8, str(row["source"] or "-")[:18], border=1)
                pdf.ln()
            return bytes(pdf.output())

        pdf_bytes = generate_pdf(filtered_df, selected_month, st.session_state.username)
        st.download_button("Download PDF", pdf_bytes, file_name=f"report_{selected_month}.pdf",
                            mime="application/pdf", use_container_width=True)

    st.divider()

    # ---- Transactions ----
    st.subheader("📋 Transactions")
    if filtered_df.empty:
        st.write("No transactions match your filters.")

    for _, row in filtered_df.iterrows():
        is_editing = st.session_state.editing_id == row["id"]

        if is_editing:
            with st.form(f"edit_form_{row['id']}"):
                st.markdown(f"**Editing transaction #{row['id']}**")
                e_type = st.selectbox("Type", ["expense", "income"],
                                       index=0 if row["type"] == "expense" else 1, key=f"etype_{row['id']}")
                e_category = st.selectbox("Category", CATEGORIES,
                                           index=CATEGORIES.index(row["category"]) if row["category"] in CATEGORIES else len(CATEGORIES) - 1,
                                           key=f"ecat_{row['id']}")
                e_payment_method = None
                if e_type == "expense":
                    current_payment = row.get("payment_method", "Cash") or "Cash"
                    if current_payment not in PAYMENT_METHODS:
                        current_payment = "Cash"
                    e_payment_method = st.selectbox("Payment Method", PAYMENT_METHODS,
                                                     index=PAYMENT_METHODS.index(current_payment),
                                                     format_func=lambda x: "📱 UPI" if x == "UPI" else "💵 Cash",
                                                     key=f"epayment_{row['id']}")
                e_amount = st.number_input("Amount (₹)", min_value=0.0, step=10.0,
                                            value=float(row["amount"]), key=f"eamt_{row['id']}")
                e_note = st.text_input("Note", value=row["note"] or "", key=f"enote_{row['id']}")
                e_date = st.date_input("Date", value=row["date"].date(), key=f"edate_{row['id']}")
                e_source = st.selectbox("Source", source_names,
                                         index=source_names.index(row["source"]) if row["source"] in source_names else 0,
                                         key=f"esrc_{row['id']}") if e_type == "expense" else None

                col_save, col_cancel = st.columns(2)
                if col_save.form_submit_button("💾 Save", use_container_width=True):
                    database.update_transaction(user_id, row["id"], e_type, e_category, e_amount,
                                                 e_note, str(e_date), e_source, e_payment_method)
                    st.session_state.editing_id = None
                    st.rerun()
                if col_cancel.form_submit_button("Cancel", use_container_width=True):
                    st.session_state.editing_id = None
                    st.rerun()
        else:
            with st.container(border=True):
                col1, col2, col3 = st.columns([4, 1, 1])
                with col1:
                    sign = "+" if row["type"] == "income" else "-"
                    color = "green" if row["type"] == "income" else "red"
                    source_label = f" · from {row['source']}" if row.get("source") else ""
                    if row["type"] == "expense":
                        pm = row.get("payment_method", "Cash") or "Cash"
                        payment_label = "📱 UPI" if pm == "UPI" else "💵 Cash"
                    else:
                        payment_label = ""
                    st.markdown(f"**{row['category']}**{source_label} · {payment_label} · {row['date'].strftime('%d %b')}")
                    st.markdown(f":{color}[{sign}₹{row['amount']:,.0f}]  \n{row['note'] or ''}")
                with col2:
                    if st.button("✏️", key=f"edit_{row['id']}"):
                        st.session_state.editing_id = row["id"]
                        st.rerun()
                with col3:
                    if st.button("🗑️", key=f"del_{row['id']}"):
                        database.delete_transaction(user_id, row["id"])
                        st.rerun()