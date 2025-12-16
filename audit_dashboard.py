# frontend/audit_dashboard.py
import streamlit as st
import pandas as pd
import requests
from io import StringIO
import altair as alt

# CONFIG
BACKEND_BASE = st.sidebar.text_input("Backend base URL", "http://127.0.0.1:8001")

st.set_page_config(page_title="Loan Bot — Audit Dashboard", layout="wide")
st.title("Loan Bot — Audit & Metrics Dashboard")

with st.sidebar.form("controls"):
    limit = st.number_input("Audit rows to fetch", min_value=5, max_value=500, value=50, step=5)
    action_filter = st.text_input("Action filter (optional)")
    fetch = st.form_submit_button("Fetch")
if not fetch:
    fetch = True

def fetch_audit(limit=50, action=None):
    try:
        params = {"limit": int(limit)}
        if action:
            params["action"] = action
        r = requests.get(f"{BACKEND_BASE}/audit", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Failed to fetch /audit: {e}")
        return None

def fetch_metrics(limit=100):
    try:
        r = requests.get(f"{BACKEND_BASE}/metrics", params={"limit": limit}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.warning(f"Could not fetch /metrics: {e}")
        return None

if fetch:
    audit = fetch_audit(limit=limit, action=action_filter)
    metrics = fetch_metrics(limit=100)

    st.subheader("Decision counts (metrics)")
    # prefer metrics summary, otherwise derive from audit
    if metrics and "summary" in metrics:
        s = metrics["summary"]
        df_counts = pd.DataFrame([
            {"decision": k, "count": int(v)} for k, v in s.items()
        ])
    else:
        # fallback: compute from audit rows
        rows = audit.get("rows", []) if audit else []
        counts = {}
        for r in rows:
            a = r.get("action","").lower()
            if "approve" in a:
                counts["APPROVE"] = counts.get("APPROVE",0)+1
            elif "refer" in a:
                counts["REFER"] = counts.get("REFER",0)+1
            elif "reject" in a:
                counts["REJECT"] = counts.get("REJECT",0)+1
        df_counts = pd.DataFrame([{"decision":k,"count":v} for k,v in counts.items()])

    if df_counts.empty:
        st.info("No decision counts available yet.")
    else:
        # bar chart
        chart = alt.Chart(df_counts).mark_bar().encode(
            x=alt.X("decision:N", sort="-y"),
            y=alt.Y("count:Q"),
            color=alt.Color("decision:N", legend=None)
        ).properties(width=400, height=300)
        st.altair_chart(chart)

        st.table(df_counts.set_index("decision"))

    st.markdown("---")
    st.subheader("Recent Audit Rows")
    if audit:
        df_rows = pd.DataFrame(audit.get("rows", []))
        if not df_rows.empty:
            # friendly ts
            try:
                df_rows["ts"] = pd.to_datetime(df_rows["ts"], errors="coerce")
            except:
                pass
            st.dataframe(df_rows, use_container_width=True)
            csv_buf = df_rows.to_csv(index=False)
            st.download_button("Download audit rows as CSV", data=csv_buf, file_name="audit_rows.csv", mime="text/csv")
        else:
            st.info("No audit rows returned.")
    else:
        st.info("No audit data found.")

    st.markdown("---")
    st.write("Raw files")
    st.markdown(f"- [Download raw audit_log.csv]({BACKEND_BASE}/audit/download)")
    st.markdown(f"- [Download raw metrics.csv]({BACKEND_BASE}/metrics/download)")

