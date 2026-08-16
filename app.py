import streamlit as st
import pandas as pd
import os
import base64
import re
import time
import requests
import uuid
from datetime import datetime, timezone
from urllib.parse import quote
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import streamlit_quill

# --- Page Configuration & Dark Mode CSS ---
st.set_page_config(page_title="Outreach Agent", page_icon="📧", layout="wide")

st.markdown("""
    <style>
        .stApp, .main { background-color: #0e1117; color: #ffffff; }
        p, span, label, div, h1, h2, h3, h4 { color: #e0e0e0 !important; }
        .stTextInput>div>div>input, .stTextArea textarea {
            background-color: #1e1e1e !important; color: #ffffff !important;
            border: 1px solid #444444 !important; border-radius: 8px !important;
        }
        .stButton>button {
            border-radius: 8px !important; height: 50px !important; font-weight: bold !important;
            background-color: #333333 !important; color: #ffffff !important; border: 1px solid #444444 !important;
        }
        .stButton>button:hover { background-color: #4d4d4d !important; border-color: #ffffff !important; }
        section[data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d !important; }
        .stFileUploader, .stSelectbox>div>div {
            background-color: #1e1e1e !important; border: 1px solid #444444 !important; border-radius: 8px !important;
        }
    </style>
""", unsafe_allow_html=True)

st.title("📧 Cold Outreach Agent")
st.markdown("Upload your template, map your CSV columns, and send tracked emails directly from your Gmail.")

TRACKER_URL = "https://outreach-tracker-ht4t.onrender.com"
SCOPES = ['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.modify']

def authenticate_gmail():
    creds = None
    secrets_error = None
    try:
        if 'gmail_token' in st.secrets:
            token_dict = dict(st.secrets["gmail_token"])
            creds = Credentials.from_authorized_user_info(token_dict, SCOPES)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
    except Exception as e:
        secrets_error = e
        creds = None
            
    if not creds or not creds.valid:
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
    if not creds or not creds.valid:
        if not os.path.exists('credentials.json'):
            if secrets_error:
                st.error(f"gmail_token secret found but failed to load: {secrets_error}")
            else:
                st.error("No Gmail credentials found. Add gmail_token to Streamlit secrets (cloud), or credentials.json locally.")
            return None
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

if 'custom_vars' not in st.session_state:
    st.session_state.custom_vars = {}

with st.sidebar:
    st.header("⚙️ Settings")
    if not st.session_state.get('service'):
        if st.button("🔗 Connect Gmail Account", use_container_width=True):
            with st.spinner("Authenticating..."):
                service = authenticate_gmail()
                if service:
                    st.session_state.service = service
                    st.success("✅ Gmail Connected!")
    else:
        st.success("✅ Gmail Connected!")
    st.markdown("---")
    st.header("✨ Custom Variables")
    with st.expander("Define / Manage Custom Variables"):
        with st.form("custom_var_form", clear_on_submit=True):
            cv_name = st.text_input("Variable Name (e.g., meeting_link)", key="cv_name")
            cv_value = st.text_input("Value (e.g., https://calendly.com/...)", key="cv_value")
            submitted = st.form_submit_button("➕ Add Custom Variable")
            if submitted and cv_name:
                st.session_state.custom_vars[cv_name] = cv_value
                st.success(f"Added {{{{{cv_name}}}}}")
        if st.session_state.custom_vars:
            st.markdown("**Active Custom Variables:**")
            for k, v in st.session_state.custom_vars.items():
                st.code(f"{{{{{k}}}}}  =  {v}")

st.markdown("---")

st.header("1. Message Details")
subject = st.text_input("📧 Email Subject", placeholder="E.g., Quick question for {{first_name}}...")
cc_emails = st.text_input("📎 CC (Optional)", placeholder="E.g., partner@example.com")

st.markdown("📝 **Email Body Template** (Use the toolbar to add links, bold, bullets, etc.)")
template = streamlit_quill.st_quill(html=True, placeholder="Hi {{first_name}}...", key="editor")

with st.expander("💡 How to use Personalization Variables"):
    st.markdown("""
    Wrap any word in double curly brackets in your Subject or Body to personalize it.
    * `{{first_name}}` = First Name * `{{name}}` = Full Name * `{{company}}` = Company Name
    """)

st.header("2. Contact List & Mapping")
uploaded_csv = st.file_uploader("Upload your CSV file", type=["csv"])
if uploaded_csv is not None:
    df = pd.read_csv(uploaded_csv)
    st.success(f"CSV loaded! Found {len(df)} contacts.")
    columns = df.columns.tolist()
    email_col = st.selectbox("📩 Which column contains the Email Addresses?", columns)
    all_vars = set(re.findall(r'\{\{(.*?)\}\}', subject + " " + template))
    custom_var_keys = set(st.session_state.custom_vars.keys())
    variables = all_vars - custom_var_keys
    st.markdown("**Map your CSV template variables to CSV columns:**")
    mappings = {}
    first_name_flags = {}
    if variables:
        for var in variables:
            col1, col2, col3 = st.columns([2, 2, 2])
            with col1: st.markdown(f"Variable: `{{{{{var}}}}}`")
            with col2: mappings[var] = st.selectbox(f"Map", columns, key=f"map_{var}", label_visibility="collapsed")
            with col3: first_name_flags[var] = st.checkbox(f"First name only?", key=f"fn_{var}")
            st.markdown("")

st.header("3. Attachments (Optional)")
uploaded_files = st.file_uploader("Upload files to attach", accept_multiple_files=True)

st.header("4. Send or Schedule")
col1, col2, col3 = st.columns(3)
with col1: send_test = st.button("🧪 Send Test (No Tracking)", use_container_width=True)
with col2: send_all = st.button("🚀 Send to All (Tracked)", use_container_width=True, type="primary")
with col3:
    schedule_date = st.date_input("Schedule Date")
    schedule_time = st.time_input("Schedule Time")
    schedule_btn = st.button("📅 Queue for Later", use_container_width=True)

LINK_PATTERN = re.compile(r'href="([^"]+)"')

def rewrite_links_for_tracking(html: str, uid: str) -> str:
    """Replace every href with a tracker redirect so clicks get logged before
    forwarding on to the real destination. Skips mailto: and anchor links,
    those aren't external destinations worth tracking."""
    counter = {'n': 0}

    def replace(match):
        original_url = match.group(1)
        if original_url.startswith('mailto:') or original_url.startswith('#'):
            return match.group(0)
        counter['n'] += 1
        link_id = f"link{counter['n']}"
        tracked_url = f"{TRACKER_URL}/click?uid={uid}&link_id={link_id}&url={quote(original_url, safe='')}"
        return f'href="{tracked_url}"'

    return LINK_PATTERN.sub(replace, html)

def prepare_html_body(quill_html: str) -> str:
    def zero_margin(match):
        attrs = match.group(1)
        if "style=" in attrs:
            attrs = re.sub(r'style="', 'style="margin:0;', attrs, count=1)
            return f"<p{attrs}>"
        return f'<p{attrs} style="margin:0;">'
    body = re.sub(r"<p([^>]*)>", zero_margin, quill_html)
    return '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;">' + body + '</div>'

def build_email(row, include_pixel=True):
    temp_subject = subject
    temp_body = template 
    
    for k, v in st.session_state.custom_vars.items():
        temp_subject = temp_subject.replace(f"{{{{{k}}}}}", v)
        temp_body = temp_body.replace(f"{{{{{k}}}}}", v)
    for var, col in mappings.items():
        val = str(row[col]) if pd.notna(row[col]) else ""
        if first_name_flags[var] and val: val = val.split()[0] 
        temp_subject = temp_subject.replace(f"{{{{{var}}}}}", val)
        temp_body = temp_body.replace(f"{{{{{var}}}}}", val)
        
    uid = str(uuid.uuid4())
    pixel_html = ""
    if include_pixel:
        temp_body = rewrite_links_for_tracking(temp_body, uid)
        pixel_url = f"{TRACKER_URL}/track?uid={uid}"
        pixel_html = f'<img src="{pixel_url}" width="1" height="1" alt="" style="display:none;">'
        
    temp_body = temp_body + pixel_html
    temp_body = prepare_html_body(temp_body)
    
    msg = MIMEMultipart()
    msg['to'] = row[email_col]
    msg['from'] = "Paarth Arora <paarth@reslink.org>"  # <-- Fixes the (unknown sender) issue
    msg['subject'] = temp_subject
    if cc_emails: msg['cc'] = cc_emails
    msg.attach(MIMEText(temp_body, 'html'))
    
    if uploaded_files:
        for f in uploaded_files:
            f.seek(0) # CRITICAL: Reset file pointer so attachments work in a loop
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{f.name}"')
            msg.attach(part)
            
    return msg, uid

def process_and_send(row, is_test=False):
    # 1. Build Tracked Email
    tracked_msg, uid = build_email(row, include_pixel=not is_test)
    raw_tracked = base64.urlsafe_b64encode(tracked_msg.as_bytes()).decode()
    
    # 2. Send Tracked Email
    sent_msg = st.session_state.service.users().messages().send(userId='me', body={'raw': raw_tracked}).execute()
    orig_id = sent_msg.get('id')
    thread_id = sent_msg.get('threadId')
    internal_date = sent_msg.get('internalDate')
    
    # 3. The "Strip & Replace" Logic (Only for real sends)
    if not is_test:
        try:
            # Trash the tracked version from Sent folder
            st.session_state.service.users().messages().trash(userId='me', id=orig_id).execute()
            
            # Build Clean Email Locally (No Pixel)
            clean_msg, _ = build_email(row, include_pixel=False)
            raw_clean = base64.urlsafe_b64encode(clean_msg.as_bytes()).decode()
            
            # Insert Clean Email into Sent Folder
            inserted_msg = st.session_state.service.users().messages().insert(
                userId='me', 
                body={
                    'raw': raw_clean, 
                    'labelIds': ['SENT'], 
                    'threadId': thread_id,
                    'internalDate': internal_date
                }
            ).execute()
            clean_msg_id = inserted_msg.get('id')
            
            # Register the CLEAN msg_id with the tracker
            try:
                r = requests.post(
                    f"{TRACKER_URL}/register",
                    json={'uid': uid, 'msg_id': clean_msg_id, 'recipient': row[email_col]},
                    timeout=20,
                )
                r.raise_for_status()
            except Exception as reg_err:
                st.session_state.setdefault('registration_errors', []).append(
                    f"{row[email_col]}: register failed ({reg_err})"
                )
        except Exception as e:
            print(f"Replacement failed: {e}")
            st.session_state.setdefault('registration_errors', []).append(
                f"{row[email_col]}: sent-copy replacement failed ({e}), self-open protection skipped for this one"
            )
            try:
                r = requests.post(
                    f"{TRACKER_URL}/register",
                    json={'uid': uid, 'msg_id': orig_id, 'recipient': row[email_col]},
                    timeout=20,
                )
                r.raise_for_status()
            except Exception as reg_err:
                st.session_state['registration_errors'].append(
                    f"{row[email_col]}: fallback register also failed ({reg_err}), open tracking will not work for this one"
                )
        
    return row[email_col]

if send_test or send_all or schedule_btn:
    if not st.session_state.get('service'):
        st.error("Please connect your Gmail account in the sidebar first.")
    elif uploaded_csv is None or not template or not subject:
        st.error("Please upload a CSV, and fill out both Subject and Template.")
    else:
        if send_test:
            try:
                with st.spinner("Sending untracked test email..."):
                    row = df.iloc[0]
                    recipient = process_and_send(row, is_test=True)
                    st.success(f"Test email sent to {recipient}! Safe to open.")
            except Exception as e:
                st.error(f"An error occurred: {e}")

        elif send_all:
            st.session_state['registration_errors'] = []
            send_errors = []
            st.info(f"Sending {len(df)} tracked emails. Please keep this window open.")
            progress_bar = st.progress(0)
            success_count = 0
            fail_count = 0

            for index, row in df.iterrows():
                # Each row gets its own try/except now, one bad address or a
                # transient API error no longer aborts every row after it.
                try:
                    recipient = process_and_send(row, is_test=False)
                    success_count += 1
                    try:
                        requests.post(f"{TRACKER_URL}/log_attempt",
                                      json={'recipient': recipient, 'status': 'sent'}, timeout=10)
                    except Exception:
                        pass
                except Exception as e:
                    fail_count += 1
                    send_errors.append(f"{row[email_col]}: {e}")
                    try:
                        requests.post(f"{TRACKER_URL}/log_attempt",
                                      json={'recipient': row[email_col], 'status': 'failed', 'error': str(e)},
                                      timeout=10)
                    except Exception:
                        pass
                progress_bar.progress((success_count + fail_count) / len(df))
                time.sleep(2)

            st.success(f"🎉 Sent {success_count} of {len(df)} tracked emails.")
            if fail_count:
                st.error(f"{fail_count} failed to send:\n\n" + "\n".join(send_errors))
            if st.session_state.get('registration_errors'):
                st.warning(
                    "Sent, but tracking registration failed for:\n\n"
                    + "\n".join(st.session_state['registration_errors'])
                )

        elif schedule_btn:
            key = st.secrets.get("STATUS_KEY") if hasattr(st, "secrets") else None
            if not key:
                st.error("STATUS_KEY isn't set in this app's secrets, scheduling needs it to authenticate with the tracker.")
            else:
                schedule_dt = datetime.combine(schedule_date, schedule_time).replace(tzinfo=timezone.utc)
                rows = df.to_dict(orient="records")

                attachments_payload = []
                if uploaded_files:
                    for f in uploaded_files:
                        f.seek(0)
                        attachments_payload.append({
                            "filename": f.name,
                            "content_b64": base64.b64encode(f.read()).decode(),
                        })

                try:
                    r = requests.post(
                        f"{TRACKER_URL}/campaigns",
                        params={"key": key},
                        json={
                            "subject_template": subject,
                            "body_template": template,
                            "email_column": email_col,
                            "cc_emails": cc_emails,
                            "custom_vars": st.session_state.custom_vars,
                            "mappings": mappings,
                            "first_name_flags": first_name_flags,
                            "schedule_time": schedule_dt.isoformat(),
                            "rows": rows,
                            "attachments": attachments_payload,
                        },
                        timeout=40,
                    )
                    r.raise_for_status()
                    resp = r.json()
                    st.success(
                        f"Queued {resp.get('recipient_count')} emails for "
                        f"{schedule_date} at {schedule_time} (campaign #{resp.get('campaign_id')})."
                    )
                except Exception as e:
                    st.error(f"Couldn't queue the campaign: {e}")
