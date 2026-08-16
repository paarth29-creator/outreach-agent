import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Outreach Dashboard", page_icon="📊", layout="wide")
st.title("📊 Outreach Dashboard")

TRACKER_URL = "https://outreach-tracker-ht4t.onrender.com"

key = st.secrets.get("STATUS_KEY") if hasattr(st, "secrets") else None
if not key:
    key = st.text_input("Tracker status key", type="password")

if not key:
    st.info("Enter the STATUS_KEY you set on Render to load the dashboard.")
    st.stop()

params = {"key": key}

try:
    with st.spinner("Waking up the tracker (can take 20-30s if it's been idle)..."):
        summary = requests.get(f"{TRACKER_URL}/summary", params=params, timeout=40).json()
        status_rows = requests.get(f"{TRACKER_URL}/status", params=params, timeout=40).json()
except requests.exceptions.Timeout:
    st.error("Tracker didn't respond in time. It may still be waking up, try again in a few seconds.")
    st.stop()
except Exception as e:
    st.error(f"Couldn't reach the tracker: {e}")
    st.stop()

if isinstance(summary, dict) and summary.get("error"):
    st.error("Unauthorized, check the status key.")
    st.stop()

# Note: this reflects only what's accumulated since the tracker last
# restarted. Render's free tier wipes local storage on every redeploy or
# idle spin-down, so numbers reset until that's moved to a persistent store.
st.caption("Data resets on tracker restart until persistent storage is added.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Sent", summary.get("total_sent", 0))
c2.metric("Failed", summary.get("total_failed", 0))
c3.metric("Open rate", f"{summary.get('open_rate_pct', 0)}%")
c4.metric("Click-through rate", f"{summary.get('click_through_rate_pct', 0)}%")

st.markdown("---")
st.subheader("Link performance")
link_data = summary.get("link_breakdown", [])
if link_data:
    st.dataframe(pd.DataFrame(link_data), use_container_width=True, hide_index=True)
else:
    st.caption("No link clicks recorded yet.")

st.markdown("---")
st.subheader("Per-email status")
if status_rows:
    df = pd.DataFrame(status_rows)
    display_cols = ["recipient", "open_count", "is_active",
                     "click_count", "opened_at", "label_error"]
    display_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(df[display_cols], use_container_width=True, hide_index=True)
else:
    st.caption("No emails tracked yet.")
