import streamlit as st
import pandas as pd
import altair as alt
from datetime import date
import database

CATEGORIES = ["Food", "Cab/Transport", "Groceries", "Rent", "Subscriptions",
              "Entertainment", "Shopping", "Health", "Education", "Miscellaneous", "Other"]

DEFAULT_SOURCES = ["Father", "Mother", "Relatives"]

st.set_page_config(page_title="Pocket Money Tracker", page_icon="💸", layout="centered")
database.init_db()

# ---------------- Login / Signup ----------------

if "user_id" not in st.session_state:
    st.session_state.user_id = None
    st.session_state.username = None

if st.session_state.user_id is None:
    st.title("💸 Pocket Money Tracker")
    tab_login, tab_signup = st.tabs(["Log in", "Sign up"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in")
            if submitted:
                user_id = database.verify_user(username, password)
                if user_id:
                    st.session_state.user_id = user_id
                    st.session_state.username = username.strip().lower()
                    st.rerun()
                else:
                    st.error("Incorrect username or password.")

    with tab_signup:
        with st.form("signup_form"):
            new_username = st.text_input("Choose a username")
            new_password = st.text_input("Choose a password", type="password")
            confirm_password = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Create account")
            if submitted:
                if not new_username.strip() or not new_password:
                    st.error("Please fill in both fields.")
                elif new_password != confirm_password:
                    st.error("Passwords don't match.")
                else:
                    success, msg = database.create_user(new_username, new_password)
                    if success:
                        st.success(msg + " You can log in now.")
                    else:
                        st.error(msg)

    st.stop()  # nothing below runs until logged in

# ---------------- Main app (only reached once logged in) ----------------

user_id = st.session_state.user_id

top_col1, top_col2 = st.columns([4, 1])
with top_col1:
    st.title("💸 Pocket Money Tracker")
    st.caption(f"Logged in as **{st.session_state.username}**")
with top_col2:
    if st.button("Log out"):
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
        amt = st.number_input(
            f"{name}", min_value=0.0, step=100.0,
            value=float(source_amounts.get(name, 0.0)), key=f"src_{name}"
        )
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

data = database.get_transactions_by_month(user_id, selected_month)
df_all = pd.DataFrame(data) if data else pd.DataFrame(columns=["type", "category", "amount", "note", "date", "source"])

spent_by_source = {}
if not df_all.empty:
    expense_df_all = df_all[df_all["type"] == "expense"]
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
st.subheader("Add an expense")
source_names = [s["source"] for s in sources] if sources else DEFAULT_SOURCES

with st.form("add_form", clear_on_submit=True):
    t_type = st.selectbox("Type", ["expense", "income"])

    spend_source = None
    if t_type == "expense":
        spend_source = st.selectbox("Spend from", source_names)

    category = st.selectbox("Category", CATEGORIES)
    custom_category = ""
    if category == "Other":
        custom_category = st.text_input("Specify category")

    amount = st.number_input("Amount (₹)", min_value=0.0, step=10.0)
    note = st.text_input("Note (optional)")
    txn_date = st.date_input("Date", value=date.today())
    submitted = st.form_submit_button("Add")

    if submitted:
        final_category = custom_category.strip() if category == "Other" else category
        if not final_category or amount <= 0:
            st.error("Please choose a category and enter a valid amount.")
        else:
            database.add_transaction(
                user_id, t_type, final_category, amount, note, str(txn_date), spend_source
            )
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
        st.progress(min(spent / total_budget, 1.0), text=f"{spent/total_budget*100:.0f}% of total money spent")

    st.divider()
    st.subheader("Spending by category")
    expense_df = df[df["type"] == "expense"]
    if not expense_df.empty:
        cat_summary = expense_df.groupby("category")["amount"].sum().reset_index()
        cat_summary["percent"] = (cat_summary["amount"] / cat_summary["amount"].sum() * 100).round(1)

        pie = alt.Chart(cat_summary).mark_arc(innerRadius=60).encode(
            theta="amount",
            color=alt.Color("category", legend=alt.Legend(title="Category")),
            tooltip=["category", "amount", "percent"]
        )
        st.altair_chart(pie, use_container_width=True)

        st.dataframe(
            cat_summary.sort_values("amount", ascending=False).rename(
                columns={"category": "Category", "amount": "Amount (₹)", "percent": "% of spending"}
            ),
            hide_index=True, use_container_width=True
        )

        st.subheader("Spending by source")
        src_summary = expense_df.groupby("source")["amount"].sum().reset_index().rename(
            columns={"source": "Source", "amount": "Amount (₹)"}
        )
        st.dataframe(src_summary.sort_values("Amount (₹)", ascending=False), hide_index=True, use_container_width=True)
    else:
        st.write("No expenses recorded this month.")

    st.divider()
    st.subheader("Transactions")
    for _, row in df.iterrows():
        with st.container(border=True):
            col1, col2 = st.columns([4, 1])
            with col1:
                sign = "+" if row["type"] == "income" else "-"
                color = "green" if row["type"] == "income" else "red"
                source_label = f" · from {row['source']}" if row.get("source") else ""
                st.markdown(f"**{row['category']}**{source_label} · {row['date'].strftime('%d %b')}")
                st.markdown(f":{color}[{sign}₹{row['amount']:,.0f}]  \n{row['note'] or ''}")
            with col2:
                if st.button("Delete", key=f"del_{row['id']}"):
                    database.delete_transaction(user_id, row['id'])
                    st.rerun()