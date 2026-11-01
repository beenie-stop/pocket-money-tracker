import pandas as pd
import streamlit as st

from ui_common import generate_pdf, inr, month_data, month_label

ctx = month_data()
df = ctx.df

st.subheader(f"⬇️ Export · {month_label(ctx.month)}")

if df.empty:
    st.info("No transactions this month to export.")
    st.stop()

# Optional narrowing before exporting
f1, f2 = st.columns(2)
with f1:
    filter_type = st.multiselect(
        "Type", options=["income", "expense"], key="export_type"
    )
with f2:
    filter_categories = st.multiselect(
        "Category",
        options=sorted(df["category"].dropna().unique()),
        key="export_category"
    )

export_df = df
if filter_type:
    export_df = export_df[export_df["type"].isin(filter_type)]
if filter_categories:
    export_df = export_df[export_df["category"].isin(filter_categories)]

spent = export_df.loc[export_df["type"] == "expense", "amount"].sum()
st.caption(
    f"{len(export_df)} transactions · {inr(spent)} spent "
    "(leave the filters empty to export everything)"
)

if export_df.empty:
    st.warning("Nothing matches those filters.")
    st.stop()

exp_col1, exp_col2 = st.columns(2)

with exp_col1:
    csv_data = (
        export_df.drop(columns=["id"], errors="ignore")
        .to_csv(index=False)
        .encode("utf-8")
    )

    # on_click="ignore": downloading doesn't re-run the whole app.
    st.download_button(
        "Download CSV",
        csv_data,
        file_name=f"transactions_{ctx.month}.csv",
        mime="text/csv",
        width="stretch",
        on_click="ignore"
    )

with exp_col2:
    # Building a PDF is slow, so it is built only on request.
    pdf_signature = (
        ctx.month,
        int(
            pd.util.hash_pandas_object(
                export_df.astype(str), index=False
            ).sum()
        )
    )

    if st.button("Prepare PDF report", width="stretch"):
        try:
            st.session_state.pdf_report = {
                "signature": pdf_signature,
                "bytes": generate_pdf(
                    export_df, ctx.month, st.session_state.username
                )
            }
        except Exception as exc:
            st.session_state.pop("pdf_report", None)
            st.error(f"Could not generate PDF: {exc}")

    report = st.session_state.get("pdf_report")

    # Only offer the file if it still matches what is on screen.
    if report and report["signature"] == pdf_signature:
        st.download_button(
            "⬇️ Download PDF",
            report["bytes"],
            file_name=f"report_{ctx.month}.pdf",
            mime="application/pdf",
            width="stretch",
            on_click="ignore"
        )