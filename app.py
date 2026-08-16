import streamlit as st
import pandas as pd
import os
import base64
import re
import time
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
        /* Dark Mode Background */
        .stApp, .main { background-color: #0e1117; color: #ffffff; }
        
        /* Text and Inputs */
        p, span, label, div, h1, h2, h3, h4 { color: #e0e0e0 !important; }
        .stTextInput>div>div>input, .stTextArea textarea {
            background-color: #1e1e1e !important;
            color: #ffffff !important;
            border: 1px solid #444444 !important;
            border-radius: 8px !important;
        }
        
        /* Buttons */
        .stButton>button {
            border-radius: 8px !important;
            height: 50px !important;
            font-weight: bold !important;
            background-color: #333333 !important;
            color: #ffffff !important;
            border: 1px solid #444444 !important;
        }
        .stButton>button:hover {
            background-color: #4d4d4d !important;
            border-color: #ffffff !important;
        }
        
        /* Sidebar */
        section[data-testid="stSidebar"] {
            background-color: #161b22 !important;
            border-right: 1px solid #30363d !important;
        }
        
        /* File Uploader & Selectbox */
        .stFileUploader, .stSelectbox>div>div {
            background-color: #1e1e1e !important;
            border: 1px solid #444444 !important;
            border-radius: 8px !important;
        }
    </style>
""", unsafe_allow_html=True)

st.title("📧 Cold Outreach Agent")
st.markdown("Upload your template, map your CSV columns, and send or schedule emails directly from your Gmail.")

# --- Gmail Authentication Function (Updated for Cloud + Local) ---
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def authenticate_gmail():
    creds = None
    
    # 1. Check if running on Streamlit Cloud (using Secrets)
    if 'gmail_token' in st.secrets:
        token_dict = dict(st.secrets["gmail_token"])
        creds = Credentials.from_authorized_user_info(token_dict, SCOPES)
        # Refresh token if expired
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            
    # 2. Check if running locally (using token.json file)
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
    # 3. If no token at all, run the local browser flow (only works on local machine)
    if not creds or not creds.valid:
        if not os.path.exists('credentials.json'):
            st.error("Please add your credentials.json to the app locally first to generate a token.")
            return None
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
    return build('gmail', 'v1', credentials=creds)

# --- Initialize Session State ---
if 'custom_vars' not in st.session_state:
    st.session_state.custom_vars = {}

# --- Sidebar for Settings & Custom Variables ---
with st.sidebar:
    st.header("⚙️ Settings")
    
    # Gmail Connection
    if 'service' not in st.session_state:
        if st.button("🔗 Connect Gmail Account", use_container_width=True):
            with st.spinner("Authenticating..."):
                try:
                    st.session_state.service = authenticate_gmail()
                    if st.session_state.service:
                        st.success("✅ Gmail Connected!")
                except Exception as e:
                    st.error(f"Error: {e}")
    else:
        st.success("✅ Gmail Connected!")
    
    st.markdown("---")
    
    # Custom Variables
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

# --- 1. Template & Subject Input ---
st.header("1. Message Details")
subject = st.text_input("📧 Email Subject", placeholder="E.g., Quick question for {{first_name}}...")
cc_emails = st.text_input("📎 CC (Optional)", placeholder="E.g., partner@example.com, assistant@example.com")

st.markdown("📝 **Email Body Template** (Use the toolbar to add links, bold, bullets, etc.)")
template = streamlit_quill.st_quill(
    html=True,
    placeholder="Hi {{first_name}},\n\nI was looking at {{company}} and thought...",
    key="editor"
)

# Variable Guide
with st.expander("💡 How to use Personalization Variables"):
    st.markdown("""
    Wrap any word in double curly brackets in your Subject or Body to personalize it.
    
    **Standard Variables:**
    * `{{first_name}}` = First Name (e.g., John)
    * `{{name}}` = Full Name (e.g., John Doe)
    * `{{company}}` = Company Name
    
    *Note: If you use any of these, you will be asked to map them to the exact column in your CSV below. You can check a box to extract only the first name from a full name column.*
    
    **Custom Variables:**
    You can also use custom variables defined in the sidebar (e.g., `{{meeting_link}}`).
    """)

# --- 2. CSV Upload & Column Mapping ---
st.header("2. Contact List & Mapping")
uploaded_csv = st.file_uploader("Upload your CSV file", type=["csv"])

if uploaded_csv is not None:
    df = pd.read_csv(uploaded_csv)
    st.success(f"CSV loaded! Found {len(df)} contacts.")
    
    columns = df.columns.tolist()
    email_col = st.selectbox("📩 Which column contains the Email Addresses?", columns)
    
    # Find all variables used, EXCEPT the custom ones (which are handled automatically)
    all_vars = set(re.findall(r'\{\{(.*?)\}\}', subject + " " + template))
    custom_var_keys = set(st.session_state.custom_vars.keys())
    variables = all_vars - custom_var_keys # Remove custom vars from CSV mapping list
    
    st.markdown("**Map your CSV template variables to CSV columns:**")
    mappings = {}
    first_name_flags = {}
    
    if variables:
        for var in variables:
            col1, col2, col3 = st.columns([2, 2, 2])
            with col1:
                st.markdown(f"Variable: `{{{{{var}}}}}`")
            with col2:
                mappings[var] = st.selectbox(f"Map to column", columns, key=f"map_{var}", label_visibility="collapsed")
            with col3:
                first_name_flags[var] = st.checkbox(f"First name only?", key=f"fn_{var}")
            st.markdown("")
    elif all_vars:
        st.info("All variables in your template are covered by your Custom Variables in the sidebar.")
    else:
        st.info("No variables like {{name}} found in your template. No mapping needed.")

# --- 3. Attachments ---
st.header("3. Attachments (Optional)")
uploaded_files = st.file_uploader("Upload files to attach", accept_multiple_files=True)

# --- 4. Action Buttons ---
st.header("4. Send or Schedule")
col1, col2, col3 = st.columns(3)

with col1:
    send_test = st.button("🧪 Send Test (First Contact)", use_container_width=True)
with col2:
    send_all = st.button("🚀 Send to All (Now)", use_container_width=True, type="primary")
with col3:
    schedule_date = st.date_input("Schedule Date")
    schedule_time = st.time_input("Schedule Time")
    schedule_btn = st.button("📅 Queue for Later", use_container_width=True)

# --- HTML cleanup ---
def prepare_html_body(quill_html: str) -> str:
    """Quill gives each Enter its own <p>, and a blank line becomes an empty
    <p><br></p> of its own. Setting margin:0 on every <p> means spacing comes
    only from however many blank lines you actually typed (each one is its
    own line-height of space), not from any extra margin stacked on top.
    No width cap: body fills whatever width the recipient's Gmail pane
    happens to be, so line length will vary by recipient/screen rather than
    holding at a fixed value.
    """
    def zero_margin(match):
        attrs = match.group(1)
        if "style=" in attrs:
            attrs = re.sub(r'style="', 'style="margin:0;', attrs, count=1)
            return f"<p{attrs}>"
        return f'<p{attrs} style="margin:0;">'

    body = re.sub(r"<p([^>]*)>", zero_margin, quill_html)
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;'
        f'font-size:14px;line-height:1.5;">{body}</div>'
    )


# --- Processing Logic ---
def process_and_send(row):
    temp_subject = subject
    temp_body = template 
    
    # 1. Replace Custom Variables
    for k, v in st.session_state.custom_vars.items():
        temp_subject = temp_subject.replace(f"{{{{{k}}}}}", v)
        temp_body = temp_body.replace(f"{{{{{k}}}}}", v)
    
    # 2. Replace CSV Mapped Variables
    for var, col in mappings.items():
        val = str(row[col]) if pd.notna(row[col]) else ""
        
        # Extract first name if checked
        if first_name_flags[var] and val:
            val = val.split()[0] 
            
        temp_subject = temp_subject.replace(f"{{{{{var}}}}}", val)
        temp_body = temp_body.replace(f"{{{{{var}}}}}", val)
        
    recipient = row[email_col]
    
    # 3. Fix HTML formatting: controlled paragraph spacing
    temp_body = prepare_html_body(temp_body)
    
    # Create Email
    msg = MIMEMultipart()
    msg['to'] = recipient
    msg['subject'] = temp_subject
    
    # Add CC if provided
    if cc_emails:
        msg['cc'] = cc_emails
        
    msg.attach(MIMEText(temp_body, 'html')) # HTML directly from the editor
    
    # Attach Files
    if uploaded_files:
        for f in uploaded_files:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{f.name}"')
            msg.attach(part)
            
    raw_string = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    st.session_state.service.users().messages().send(userId='me', body={'raw': raw_string}).execute()
    return recipient

# Button Actions
if send_test or send_all or schedule_btn:
    if 'service' not in st.session_state:
        st.error("Please connect your Gmail account in the sidebar first.")
    elif uploaded_csv is None or not template or not subject:
        st.error("Please upload a CSV, and fill out both Subject and Template.")
    else:
        try:
            if send_test:
                with st.spinner("Sending test email..."):
                    row = df.iloc[0]
                    recipient = process_and_send(row)
                    st.success(f"Test email sent to {recipient}! Check your inbox to verify the formatting.")
                    
            elif send_all:
                st.info(f"Sending {len(df)} emails. Please keep this window open.")
                progress_bar = st.progress(0)
                success_count = 0
                
                for index, row in df.iterrows():
                    recipient = process_and_send(row)
                    success_count += 1
                    progress_bar.progress(success_count / len(df))
                    time.sleep(2) 
                    
                st.success(f"🎉 Successfully sent {success_count} emails!")
                
            elif schedule_btn:
                st.info(f"Campaign queued for {schedule_date} at {schedule_time}. (Note: Background execution requires a task queue, which can be added later).")
                
        except Exception as e:
            st.error(f"An error occurred: {e}")