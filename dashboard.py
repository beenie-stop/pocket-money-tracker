import streamlit as st
from streamlit_cookies_controller import CookieController

import database
from ui_common import (
    PAGE_SIZE, add_transaction_dialog, month_label, today
)

st.set_page_config(
    page_title="Pocket Money Tracker",
    page_icon="💸",
    layout="centered"
)

# Cached: the schema is created/upgraded once per server process,
# not on every click.
database.init_db()
cookies = CookieController()


# ---------------- Session state + auto-login ----------------
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
            username = database.get_username_by_id(remembered_id)
            if username:
                st.session_state.user_id = remembered_id
                st.session_state.username = username


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
                        cookies.set(
                            "session_token",
                            database.create_session(user_id)
                        )

                    st.rerun()
                else:
                    st.error("Incorrect username or password.")

    with tab_signup:
        with st.form("signup_form"):
            new_username = st.text_input("Choose a username")
            new_password = st.text_input("Choose a password", type="password")
            confirm_password = st.text_input(
                "Confirm password",
                type="password"
            )

            if st.form_submit_button("Create account"):
                if not new_username.strip() or not new_password:
                    st.error("Please fill in both fields.")
                elif new_password != confirm_password:
                    st.error("Passwords don't match.")
                else:
                    success, msg = database.create_user(
                        new_username,
                        new_password
                    )
                    if success:
                        st.success(msg + " You can log in now.")
                    else:
                        st.error(msg)

    st.stop()


# ---------------- Main app: navigation ----------------
# Only the page you are on runs, which is also why this is faster than
# putting everything on one long page.
nav = st.navigation(
    [
        st.Page("views/home.py", title="Home", icon="🏠", default=True),
        st.Page("views/transactions.py", title="Transactions", icon="📋"),
        st.Page("views/insights.py", title="Insights", icon="📊"),
        st.Page("views/money.py", title="Money & Months", icon="💰"),
        st.Page("views/export.py", title="Export", icon="⬇️"),
    ],
    position="top"
)

user_id = st.session_state.user_id

top_left, top_right = st.columns([4, 1], vertical_alignment="center")

with top_left:
    st.title("💸 Pocket Money")
    st.caption(f"Logged in as **{st.session_state.username}**")

with top_right:
    if st.button("Log out", width="stretch"):
        token = cookies.get("session_token")
        if token:
            database.delete_session(token)
            cookies.remove("session_token")

        st.session_state.user_id = None
        st.session_state.username = None
        st.session_state.editing_id = None
        # Don't carry one user's month/paging state over to the next login.
        for key in (
            "selected_month", "txn_month", "txn_limit", "pdf_report"
        ):
            st.session_state.pop(key, None)
        st.rerun()


# ---------------- Month selector + Add button (on every page) ----------------
months_available = database.get_available_months(user_id)
current_month = today().strftime("%Y-%m")

if current_month not in months_available:
    months_available = [current_month] + months_available

month_col, add_col = st.columns([3, 2], vertical_alignment="bottom")

with month_col:
    # The key keeps the chosen month stable across pages and reruns.
    selected_month = st.selectbox(
        "Month",
        months_available,
        index=months_available.index(current_month),
        format_func=month_label,
        key="selected_month"
    )

with add_col:
    if st.button("➕ Add transaction", type="primary", width="stretch"):
        add_transaction_dialog()

# New month -> start paging from the top and leave edit mode.
if st.session_state.get("txn_month") != selected_month:
    st.session_state.txn_month = selected_month
    st.session_state.txn_limit = PAGE_SIZE
    st.session_state.editing_id = None

nav.run()