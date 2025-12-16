# frontend/chatui.py
import streamlit as st
import requests
import streamlit.components.v1 as components
from datetime import datetime
import os
# -----------------------------
# PAGE CONFIG
# -----------------------------
st.set_page_config(page_title="Loan Chatbot", layout="wide")
st.title("💬 Loan Chatbot — Smart Loan Assistant")

# >>> CHANGED / ADDED: Marketing entry screen with demo email capture + "Check Offers"
if 'show_chat' not in st.session_state:
    st.session_state.show_chat = False

# store demo email if user types one
if 'demo_lead_email' not in st.session_state:
    st.session_state.demo_lead_email = ""

if not st.session_state.show_chat:
    left, right = st.columns([2, 1])
    with left:
        st.markdown("## 🚀 LoanBot — Quick demo entry")
        st.write("Looks like you came from an email or ad — enter your email to get a personalized offer preview.")
        # Email capture (demo only, not stored externally)
        email_input = st.text_input("📧 Enter your email (demo)", value=st.session_state.demo_lead_email, placeholder="you@domain.com")
        if email_input:
            st.session_state.demo_lead_email = email_input
        col_a, col_b = st.columns([1,1])
        with col_a:
            if st.button("✅ Save Email & Start Chat"):
                # show quick confirmation and open chat
                st.session_state.show_chat = True
                st.success(f"Thanks — we’ll use {st.session_state.demo_lead_email} for demo personalization.")
        with col_b:
            if st.button("Start Chat (skip email)"):
                st.session_state.show_chat = True
    with right:
        # Optional taste: "Check Offers" quick preview — shows modal-like info
        st.markdown("### Offers preview")
        if st.button("Check Offers"):
            # Simple offer mock to show in slides
            offer1 = {
                "title": "Pre-approved Personal Loan",
                "amount": "₹4,00,000",
                "rate": "11.5% p.a.",
                "tenure": "36 months"
            }
            offer2 = {
                "title": "Top-up Loan",
                "amount": "₹2,00,000",
                "rate": "13.0% p.a.",
                "tenure": "24 months"
            }
            st.info("Here are personalized offers we found (demo):")
            st.markdown(f"**{offer1['title']}** — {offer1['amount']} — {offer1['rate']} — {offer1['tenure']}")
            st.markdown(f"**{offer2['title']}** — {offer2['amount']} — {offer2['rate']} — {offer2['tenure']}")
            st.write("Click **Save Email & Start Chat** to continue with a pre-filled demo experience.")
        # image for visual
        try:
            st.image("https://cdn-icons-png.flaticon.com/512/9441/9441692.png", width=160)
        except Exception:
            pass

    # stop rendering rest of the page until the user starts the chat
    st.stop()
# <<< END CHANGED



# Sidebar: backend URL
BACKEND = st.sidebar.text_input("Backend base URL", "http://127.0.0.1:8001")

# -----------------------------
# SESSION STATE
# -----------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []  # list of dicts: {"role":"user"/"bot","text":..., "ts": "...", "meta": {...}}
if "last_decision" not in st.session_state:
    st.session_state.last_decision = None
if "typing" not in st.session_state:
    st.session_state.typing = False
if "crm" not in st.session_state:
    st.session_state.crm = None   # will hold dict from /crm/{id} if loaded
if "loaded_customer_id" not in st.session_state:
    st.session_state.loaded_customer_id = None

# ---- Auto-prefill from marketing CTA (paste after session-state init in chatui.py) ----
from urllib.parse import unquote

# use st.query_params (new API)
_q = st.query_params  # streamlit >= 1.19
_prefill = None
if "prefill" in _q:
    # st.query_params returns lists like {"prefill": ["..."]}
    raw = _q.get("prefill")
    if raw:
        _prefill = unquote(raw[0])
    # optional utm params
    utm_source = _q.get("utm_source", [""])[0] if _q.get("utm_source") else ""
    utm_medium = _q.get("utm_medium", [""])[0] if _q.get("utm_medium") else ""
    utm_campaign = _q.get("utm_campaign", [""])[0] if _q.get("utm_campaign") else ""
else:
    utm_source = utm_medium = utm_campaign = ""


# send the prefill once per session (so it doesn't resend on every rerun)
if _prefill and not st.session_state.get("prefill_sent"):
    st.session_state.prefill_sent = True
    # show user message in chat
    append_message("user", _prefill)
    # call backend NLP route to get immediate bot reply
    st.session_state.typing = True
    with st.spinner("Starting chat..."):
        resp = call_nlp_apply(_prefill, st.session_state.get("loaded_customer_id"))
    st.session_state.typing = False

    if resp.get("error"):
        append_message("bot", f"⚠️ Error: {resp['error']}")
    else:
        # friendly reply and decision summary (your nlp_apply returns 'reply' and 'decision')
        append_message("bot", resp.get("reply", "Hi — tell me more."))
        # store decision for later UI (offer card etc.)
        st.session_state.last_decision = resp.get("decision") or {}
    # log the marketing click (best-effort; don't fail UI on error)
    try:
        requests.post(f"{BACKEND}/log_event", json={
            "event": "marketing_prefill_click",
            "prefill": _prefill,
            "utm_source": utm_source,
            "utm_medium": utm_medium,
            "utm_campaign": utm_campaign,
            "ts": datetime.utcnow().isoformat()
        }, timeout=2)
    except Exception:
        pass
# ---- end prefill block ----

# -----------------------------
# BACKEND CALLS
# -----------------------------
import requests
from requests.exceptions import RequestException

# BACKEND should already be defined in your file, e.g.
# BACKEND = "http://127.0.0.1:8001"
# If not, set it at top of file.

def call_nlp_apply(msg: str, cust_id: str = None, timeout: int = 10):
    """
    Sends JSON {"msg": msg, "cust_id": cust_id} to /nlp_apply and returns dict.
    Returns {"error": "..."} on failure so frontend can show a friendly message.
    """
    if not msg:
        return {"error": "empty message"}

    payload = {"message": msg}
    if cust_id:
        payload["cust_id"] = cust_id

    url = f"{BACKEND.rstrip('/')}/nlp_apply"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        # If status code is not 2xx, try to return backend message
        try:
            data = resp.json()
        except Exception:
            data = None

        if resp.status_code >= 400:
            # Prefer body message if present
            if data:
                # FastAPI validation errors come as JSON details
                return {"error": f"{resp.status_code} {resp.reason}: {data}"}
            else:
                return {"error": f"{resp.status_code} {resp.reason}: {resp.text}"}

        return data or {}
    except RequestException as e:
        return {"error": f"Request failed: {str(e)}"}



def call_orchestrate(customer_id, loan_amount, tenure_months, existing_monthly_debt=0):
    payload = {
        "customer_id": customer_id,
        "loan_amount": loan_amount,
        "tenure_months": tenure_months,
        "existing_monthly_debt": existing_monthly_debt,
    }
    try:
        r = requests.post(f"{BACKEND}/orchestrate_apply", json=payload, timeout=25)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def fetch_crm(customer_id: str):
    try:
        r = requests.get(f"{BACKEND}/crm/{customer_id}", timeout=6)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None

# -----------------------------
# Additional small helpers
# -----------------------------
def call_update_crm(customer_id: str, pan: str = "", income_monthly: float = 0.0, timeout: int = 6):
    """
    POST to /crm/update to store pan and income_monthly for the customer.
    """
    payload = {"customer_id": customer_id}
    if pan is not None:
        payload["pan"] = pan
    if income_monthly is not None:
        payload["income_monthly"] = income_monthly
    try:
        r = requests.post(f"{BACKEND.rstrip('/')}/crm/update", json=payload, timeout=timeout)
        if r.status_code >= 400:
            return {"error": f"{r.status_code} {r.reason}: {r.text}"}
        return r.json() if r.text else {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}

def call_get_kyc(customer_id: str, timeout: int = 6):
    """
    GET /kyc/{customer_id} returning kyc result or error.
    """
    try:
        r = requests.get(f"{BACKEND.rstrip('/')}/kyc/{customer_id}", timeout=timeout)
        if r.status_code >= 400:
            return {"error": f"{r.status_code} {r.reason}: {r.text}"}
        return r.json() if r.text else {}
    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Improved single placeholder stepper (horizontal badges + progress bar)
# -----------------------------
import textwrap  # add at top of file near other imports

# Improved single placeholder stepper (fixed so HTML renders, not printed)
stepper_placeholder = st.empty()

def render_stepper(statuses: dict):
    def badge_html(label, state):
        if state == "pass":
            bg = "#16a34a"; icon = "✓"
        elif state == "fail":
            bg = "#dc2626"; icon = "✕"
        elif state == "in_progress":
            bg = "#f59e0b"; icon = "…"
        else:
            bg = "#64748b"; icon = "•"
        return f'<div class="step-badge" style="background:{bg};"><div class="step-icon">{icon}</div><div class="step-label">{label}</div></div>'

    complete = sum(1 for k in ("kyc","underwriting","pdf") if statuses.get(k) == "pass")
    percent = int(round((complete / 3.0) * 100))

    html = f"""
    <style>
      .stepper-wrap {{ display:flex; flex-direction:column; gap:8px; max-width:820px; }}
      .badges {{ display:flex; gap:12px; align-items:center; }}
      .step-badge {{ min-width:120px; padding:10px; border-radius:10px; color:white; display:flex; gap:10px; align-items:center; box-shadow: 0 4px 10px rgba(2,6,23,0.3); }}
      .step-icon {{ font-weight:bold; width:26px; height:26px; display:flex; align-items:center; justify-content:center; border-radius:6px; background:rgba(255,255,255,0.08); }}
      .step-label {{ font-size:14px; font-weight:600; }}
      .progress-bar-outer {{ background:#0f172a; height:8px; border-radius:6px; overflow:hidden; }}
      .progress-bar-inner {{ height:8px; width:{percent}%; background:linear-gradient(90deg,#06b6d4,#3b82f6); border-radius:6px; transition:width 400ms ease; }}
      .progress-meta {{ font-size:13px; color:#94a3b8; margin-top:4px; }}
    </style>
    <div class="stepper-wrap">
      <div class="badges">
        {badge_html("KYC", statuses.get("kyc","pending"))}
        {badge_html("Underwriting", statuses.get("underwriting","pending"))}
        {badge_html("PDF", statuses.get("pdf","pending"))}
      </div>
      <div class="progress-bar-outer"><div class="progress-bar-inner"></div></div>
      <div class="progress-meta">Progress: {percent}% — KYC: {statuses.get('kyc','pending')} • Underwriting: {statuses.get('underwriting','pending')} • PDF: {statuses.get('pdf','pending')}</div>
    </div>
    """

    # remove indentation so Streamlit does NOT treat it as a code block
    html = textwrap.dedent(html).strip()
    stepper_placeholder.markdown(html, unsafe_allow_html=True)

    # compute progress percent: 0, 33, 66, 100 depending on how many 'pass'
    complete = sum(1 for k in ("kyc","underwriting","pdf") if statuses.get(k) == "pass")
    percent = int(round((complete / 3.0) * 100))

    # assemble html
    html = f"""
    <style>
      .stepper-wrap {{ display:flex; flex-direction:column; gap:8px; max-width:820px; }}
      .badges {{ display:flex; gap:12px; align-items:center; }}
      .step-badge {{
        min-width:120px; padding:10px; border-radius:10px; color:white;
        display:flex; gap:10px; align-items:center; box-shadow: 0 4px 10px rgba(2,6,23,0.3);
      }}
      .step-icon {{ font-weight:bold; width:26px; height:26px; display:flex; align-items:center; justify-content:center; border-radius:6px; background:rgba(255,255,255,0.08); }}
      .step-label {{ font-size:14px; font-weight:600; }}
      .progress-bar-outer {{ background:#0f172a; height:8px; border-radius:6px; overflow:hidden; }}
      .progress-bar-inner {{ height:8px; width:{percent}%; background:linear-gradient(90deg,#06b6d4,#3b82f6); border-radius:6px; transition:width 400ms ease; }}
      .progress-meta {{ font-size:13px; color:#94a3b8; margin-top:4px; }}
    </style>
    <div class="stepper-wrap">
      <div class="badges">
        {badge_html("KYC", statuses.get("kyc","pending"))}
        {badge_html("Underwriting", statuses.get("underwriting","pending"))}
        {badge_html("PDF", statuses.get("pdf","pending"))}
      </div>
      <div class="progress-bar-outer"><div class="progress-bar-inner"></div></div>
      <div class="progress-meta">Progress: {percent}% — KYC: {statuses.get('kyc','pending')} • Underwriting: {statuses.get('underwriting','pending')} • PDF: {statuses.get('pdf','pending')}</div>
    </div>
    """

    # render in the single placeholder (clears previous content automatically)
    stepper_placeholder.markdown(html, unsafe_allow_html=True)

    
# -----------------------------
# CHAT HELPERS
# -----------------------------
def append_message(role, text, meta=None):
    ts = datetime.now().strftime("%H:%M")
    st.session_state.messages.append({"role": role, "text": text, "ts": ts, "meta": meta or {}})


def render_chat_html(messages, typing=False):
    user_avatar = "🧑"
    bot_avatar = "🤖"
    items_html = ""

    for m in messages:
        role = m.get("role", "bot")
        text = str(m.get("text", "")).replace("\n", "<br>")
        ts = m.get("ts", "")
        meta = m.get("meta", {})

        extra_html = ""
        pdf_url = meta.get("pdf_url")
        if pdf_url:
            extra_html = f'<div class="pdf-link"><a href="{pdf_url}" target="_blank">📄 Download sanction letter</a></div>'

        if role == "user":
            items_html += f"""
            <div class='msg-row user'>
                <div class='bubble'>{text}{extra_html}<div class='ts'>{ts}</div></div>
                <div class='avatar'>{user_avatar}</div>
            </div>
            """
        else:
            items_html += f"""
            <div class='msg-row bot'>
                <div class='avatar'>{bot_avatar}</div>
                <div class='bubble'>{text}{extra_html}<div class='ts'>{ts}</div></div>
            </div>
            """

    typing_html = ""
    if typing:
        typing_html = """
        <div class='msg-row bot typing-row'>
            <div class='avatar'>🤖</div>
            <div class='bubble typing'>
                <span class='dot'></span><span class='dot'></span><span class='dot'></span>
            </div>
        </div>
        """

    html = f"""
    <style>
      .chat-wrap {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial;
        max-width: 720px;
        margin: 0 auto;
        padding: 8px;
      }}
      .chat-box {{
        height: 420px;
        overflow-y: auto;
        padding: 16px;
        border-radius: 12px;
        background: #f1f4f7;
        box-shadow: inset 0 1px 3px rgba(0,0,0,0.08);
      }}
      .msg-row {{ display: flex; align-items: flex-end; margin-bottom: 12px; }}
      .msg-row.user {{ justify-content: flex-end; }}
      .msg-row.bot {{ justify-content: flex-start; }}
      .avatar {{ width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; font-size: 22px; margin: 0 6px; }}
      .bubble {{
        max-width: 70%;
        padding: 10px 12px;
        border-radius: 14px;
        line-height: 1.4;
        box-shadow: 0 1px 2px rgba(0,0,0,0.1);
        font-size: 14px;
        word-wrap: break-word;
      }}
      .msg-row.user .bubble {{
        background: linear-gradient(135deg, #0084ff, #0066d6);
        color: white;
        border-bottom-right-radius: 4px;
      }}
      .msg-row.bot .bubble {{
        background: white;
        color: #111;
        border-bottom-left-radius: 4px;
      }}
      .ts {{ font-size: 11px; opacity: 0.6; margin-top: 4px; text-align: right; }}
      .pdf-link {{ margin-top: 8px; font-size: 13px; }}
      .typing {{ display: flex; gap: 5px; align-items: center; }}
      .dot {{
        width: 8px; height: 8px; background: #bbb; border-radius: 50%;
        animation: blink 1.4s infinite;
      }}
      .dot:nth-child(2) {{ animation-delay: 0.2s; }}
      .dot:nth-child(3) {{ animation-delay: 0.4s; }}
      @keyframes blink {{
        0% {{ opacity: 0.2; }}
        50% {{ opacity: 1; }}
        100% {{ opacity: 0.2; }}
      }}
    </style>

    <div class='chat-wrap'>
      <div id='chat' class='chat-box'>
        {items_html}
        {typing_html}
      </div>
    </div>

    <script>
      const chat = document.getElementById('chat');
      if (chat) {{
        chat.scrollTop = chat.scrollHeight;
      }}
    </script>
    """
    return html

# -----------------------------
# CRM Loader UI
# # -----------------------------
# st.markdown("#### Load existing customer")
# col_a, col_b, col_c = st.columns([3,1,2])
# with col_a:
#     cust_input_box = st.text_input("Customer ID (e.g. CUST_001)", value="")
# with col_b:
#     load_btn = st.button("Load customer")
# with col_c:
#     clear_btn = st.button("Clear loaded customer")

# if load_btn:
#     cid = cust_input_box.strip()
#     if cid:
#         crm = fetch_crm(cid)
#         if crm:
#             st.session_state.crm = crm
#             st.session_state.loaded_customer_id = cid
#             append_message("bot", f"Loaded customer {cid} from CRM — income: {crm.get('income_monthly') or crm.get('income') or 'N/A'}, existing debt: {crm.get('existing_monthly_debt') or crm.get('existing_debt') or 'N/A'}")
#         else:
#             st.session_state.crm = None
#             st.session_state.loaded_customer_id = None
#             append_message("bot", f"Customer {cid} not found in CRM. I'll parse message instead.")
#     else:
#         append_message("bot", "Enter a customer id before clicking Load.")

# if clear_btn:
#     st.session_state.crm = None
#     st.session_state.loaded_customer_id = None
#     append_message("bot", "Cleared loaded customer. I'll parse messages without CRM now.")

# st.markdown("---")

# -----------------------------
# CHAT INPUT FORM
# -----------------------------
# %&%&with st.form("chat_form", clear_on_submit=True):
#     user_msg = st.text_area("Type your message (e.g. 'I want 2 lakh loan for 3 years, my salary is 45k')", height=90)
#     submitted = st.form_submit_button("Send 💬")

# -----------------------------
# OPTIONAL: Show (readonly) prefilled fields from CRM
# -----------------------------
# If CRM is loaded, show its income and existing debt as read-only so users know it's used.
if st.session_state.crm:
    crm = st.session_state.crm
    st.markdown("**Using CRM values:**")
    c1, c2 = st.columns(2)
    with c1:
        st.text_input("Income (from CRM)", value=str(crm.get("income_monthly") or crm.get("income") or ""), disabled=True)
    with c2:
        st.text_input("Existing monthly debt (from CRM)", value=str(crm.get("existing_monthly_debt") or crm.get("existing_debt") or "0"), disabled=True)
else:
    # Show nothing (or you can show optional prefill inputs if you want)
    pass


# -----------------------------
# RENDER CHAT WINDOW (new bubble-style chat UI)
# -----------------------------
st.markdown("### 💬 Chat")

# Render chat history as native chat bubbles
for msg in st.session_state.messages:
    role = msg.get("role", "bot")
    text = msg.get("text", "")
    if role == "user":
        st.chat_message("user").write(text)
    else:
        st.chat_message("assistant").write(text)

import re  # ensure this import is near your other imports at top

# ---- Bottom single input: accept Customer ID or normal messages ----
import re

# Make the placeholder only for customer-id format initially
# NOTE: You can change the text below if you want different wording.
user_input = st.chat_input("Enter Customer ID (e.g. CUST_001)")

if user_input:
    text = user_input.strip()

    # Pattern for customer id: accepts CUST_001, cust-1, CUST001, etc.
    cust_pattern = re.compile(r'^cust[_-]?\d+$', re.I)


    if cust_pattern.match(text):
        # Normalize format to CUST_XXX (upper + underscore)
        cid = text.upper().replace('-', '_')
        # show user message in chat
        append_message("user", cid)
        st.chat_message("user").write(cid)

        # fetch CRM and show assistant message with details
        crm = fetch_crm(cid)
        if crm:
            st.session_state.crm = crm
            st.session_state.loaded_customer_id = cid
                    # Enhanced personalized greeting for demo
            import time
            with st.spinner("Fetching your CRM details..."):
                time.sleep(1.2)

            name = crm.get("name") or "Customer"
            income = crm.get("income_monthly") or crm.get("income") or "N/A"
            existing = crm.get("existing_monthly_debt") or crm.get("existing_debt") or "N/A"
            preapproved = crm.get("pre_approved_limit") or "N/A"

            msg = (
                f"👋 Welcome back, {name}! "
                f"I’ve fetched your record: monthly income ₹{income}, "
                f"existing EMI ₹{existing}. "
            )
            if preapproved not in ("", "N/A", None):
                msg += f"You're pre-approved for up to ₹{preapproved}! 🎉"
            else:
                msg += "Let's check your best loan options today."

            append_message("bot", msg)
            st.chat_message("assistant").write(msg)

        else:
            st.session_state.crm = None
            st.session_state.loaded_customer_id = None
            msg = f"Customer {cid} not found in CRM. I will parse messages normally."
            append_message("bot", msg)
            st.chat_message("assistant").write(msg)

    else:
        # Normal chat message -> call NLP (uses loaded_customer_id if set)
        append_message("user", text)
        st.chat_message("user").write(text)

        st.session_state.typing = True
        with st.spinner("Contacting backend..."):
            resp = call_nlp_apply(text, st.session_state.get("loaded_customer_id"))
        st.session_state.typing = False

        # persist response for EMI/options UI
        st.session_state['last_resp'] = resp if isinstance(resp, dict) else {}

        if resp is None or "error" in resp:
            err_text = resp.get("error") if isinstance(resp, dict) else "Unknown error"
            append_message("bot", f"⚠️ Error: {err_text}")
            st.chat_message("assistant").write(f"⚠️ Error: {err_text}")
        else:
            friendly = resp.get("reply") or "No friendly reply."
            decision = resp.get("decision") or {}
            st.session_state.last_decision = decision
            append_message("bot", friendly)
            st.chat_message("assistant").write(friendly)

            # Show EMI options (if backend returned them)
            emi_opts = resp.get("emi_options", []) if isinstance(resp, dict) else []
            if emi_opts:
                st.markdown("**EMI options (tap to choose):**")
                cols = st.columns(len(emi_opts))
                for i, opt in enumerate(emi_opts):
                    label = f"{opt['tenure_months']}m\n₹{opt['emi']:,}/mo"
                    if cols[i].button(label):
                        st.session_state.last_decision = st.session_state.get("last_decision", {}) or {}
                        lr = st.session_state.last_decision.get("loan_request", {}) or {}
                        lr["tenure_months"] = opt["tenure_months"]
                        lr["est_emi"] = opt["emi"]
                        st.session_state.last_decision["loan_request"] = lr

                        append_message("user", f"Choose {opt['tenure_months']} months")
                        st.chat_message("user").write(f"Choose {opt['tenure_months']} months")
                        append_message("bot", f"Selected {opt['tenure_months']} months — EMI ₹{opt['emi']:,}. Click 'Proceed with Formal Apply' to continue.")
                        st.chat_message("assistant").write(f"Selected {opt['tenure_months']} months — EMI ₹{opt['emi']:,}. Click 'Proceed with Formal Apply' to continue.")
                        st.experimental_rerun()

            # Show quick replies (if backend returned any)
            resp_quick = resp.get("quick_replies", []) if isinstance(resp, dict) else []
            if resp_quick:
                st.markdown("**Quick replies:**")
                cols = st.columns(len(resp_quick))
                for i, qr in enumerate(resp_quick):
                    if cols[i].button(qr):
                        append_message("user", qr)
                        st.chat_message("user").write(qr)
                        with st.spinner("Processing quick reply..."):
                            resp2 = call_nlp_apply(qr, st.session_state.get("loaded_customer_id"))
                        st.session_state['last_resp'] = resp2 if isinstance(resp2, dict) else {}
                        if resp2 is None or "error" in resp2:
                            err2 = resp2.get("error") if isinstance(resp2, dict) else "Unknown error"
                            append_message("bot", f"⚠️ Error: {err2}")
                            st.chat_message("assistant").write(f"⚠️ Error: {err2}")
                        else:
                            friendly2 = resp2.get("reply") or ""
                            st.session_state.last_decision = resp2.get("decision") or {}
                            append_message("bot", friendly2)
                            st.chat_message("assistant").write(friendly2)

# -----------------------------
# DECISION / ORCHESTRATE SECTION
# -----------------------------
if st.session_state.last_decision:
    dec = st.session_state.last_decision
    st.subheader("🔍 Decision Details")
    st.json(dec)

    # Extract loan request defaults
    lr = dec.get("loan_request", {}) if isinstance(dec, dict) else {}
    # If CRM loaded, prefer CRM values for existing_debt and use loaded customer id
    cust = st.session_state.loaded_customer_id or ""
    default_loan_amount = lr.get("loan_amount") or 0
    default_tenure = lr.get("tenure_months") or 0

    # If CRM present, show its existing debt and make it read-only. Otherwise allow edit.
    if st.session_state.crm:
        existing_debt_value = float(st.session_state.crm.get("existing_monthly_debt") or st.session_state.crm.get("existing_debt") or 0)
        income_value = float(st.session_state.crm.get("income_monthly") or st.session_state.crm.get("income") or 0)
        st.info(f"Using CRM data for customer {cust}: income={income_value}, existing_debt={existing_debt_value}")
        loan_amount = st.number_input("Loan amount", value=float(default_loan_amount or 0))
        tenure_months = st.number_input("Tenure (months)", value=int(default_tenure or 0))
        existing_debt = existing_debt_value  # fixed from CRM
    else:
        loan_amount = st.number_input("Loan amount", value=float(default_loan_amount or 0))
        tenure_months = st.number_input("Tenure (months)", value=int(default_tenure or 0))
        existing_debt = st.number_input("Existing monthly debt", value=0.0)

    col1, col2 = st.columns(2)
    with col1:
        # --- New: controlled KYC flow using session_state ---
# ensure keys exist
        if "show_kyc_form" not in st.session_state:
            st.session_state.show_kyc_form = False
        if "kyc_pan" not in st.session_state:
            st.session_state.kyc_pan = ""
        if "kyc_income" not in st.session_state:
            st.session_state.kyc_income = float(st.session_state.crm.get("income_monthly") if st.session_state.crm else 0.0)
        if "kyc_consent" not in st.session_state:
            st.session_state.kyc_consent = False

        # When user clicks Proceed, just flip a flag to show the KYC form
        if st.button("🚀 Proceed with Formal Apply"):
            if not cust:
                st.error("Customer ID required for formal apply (to run KYC, underwriting, and generate sanction PDF).")
            elif float(loan_amount) <= 0 or int(tenure_months) <= 0:
                st.error("Loan amount and tenure must be > 0.")
            else:
                st.session_state.show_kyc_form = True
                # prefill income from CRM if available
                try:
                    st.session_state.kyc_income = float(st.session_state.crm.get("income_monthly") or 0)
                except:
                    st.session_state.kyc_income = st.session_state.kyc_income or 0.0
                # keep interface responsive: show helpful message
                st.info("Please provide KYC consent details below to continue.")

        # Render KYC form when flag is true (this runs on every rerun so form submission works)
        if st.session_state.show_kyc_form:
            with st.form("kyc_consent_form"):
                st.markdown("### KYC consent (demo)\nWe need your consent to use PAN and income for KYC checks.")
                pan_val = st.text_input("PAN (optional)", value=st.session_state.kyc_pan)
                income_val = st.number_input("Monthly income (₹)", value=float(st.session_state.kyc_income))
                consent = st.checkbox("I consent to share PAN and monthly income for KYC and underwriting", value=st.session_state.kyc_consent)
                submit_kyc = st.form_submit_button("Continue")

            # If form submitted, process it (this block will run on the submit rerun)
            if submit_kyc:
                # save into session_state (so values persist if we rerun)
                st.session_state.kyc_pan = pan_val
                st.session_state.kyc_income = income_val
                st.session_state.kyc_consent = consent

                if not consent:
                    st.warning("Consent required to proceed with KYC.")
                else:
                    # hide the form while processing to avoid duplicate submits
                    st.session_state.show_kyc_form = False

                    # 1) update CRM with PAN and income (best-effort)
                    st.info("Saving KYC details to CRM (demo)...")
                    up_resp = call_update_crm(cust, pan=pan_val, income_monthly=income_val)
                    if isinstance(up_resp, dict) and up_resp.get("error"):
                        st.warning(f"CRM update warning: {up_resp.get('error')}")
                    else:
                        # refresh local CRM if possible
                        crm_refreshed = fetch_crm(cust)
                        if crm_refreshed:
                            st.session_state.crm = crm_refreshed

                    # 2) Stepper initial statuses
                    statuses = {"kyc": "in_progress", "underwriting": "pending", "pdf": "pending"}
                    render_stepper(statuses)

                    # 3) call /kyc/{id}
                    with st.spinner("Running KYC check..."):
                        kyc_res = call_get_kyc(cust)
                    if isinstance(kyc_res, dict) and kyc_res.get("error"):
                        st.error(f"KYC endpoint error: {kyc_res.get('error')}")
                        statuses["kyc"] = "fail"
                        render_stepper(statuses)
                    else:
                        kyc_status = (kyc_res.get("kyc", {}) if isinstance(kyc_res, dict) else {})
                        if kyc_status and kyc_status.get("status", "").upper() == "PASS":
                            statuses["kyc"] = "pass"
                            render_stepper(statuses)

                            # 4) call orchestration (underwriting + pdf)
                            statuses["underwriting"] = "in_progress"
                            render_stepper(statuses)
                            with st.spinner("Running underwriting and PDF generation..."):
                                orch = call_orchestrate(cust, float(loan_amount), int(tenure_months), float(existing_debt or 0))
                            if isinstance(orch, dict) and orch.get("error"):
                                st.error(f"Orchestration error: {orch.get('error')}")
                                statuses["underwriting"] = "fail"
                                render_stepper(statuses)
                            else:
                                statuses["underwriting"] = "pass"
                                if orch.get("pdf_url"):
                                    statuses["pdf"] = "pass"
                                render_stepper(statuses)

                                st.success("✅ Orchestration complete.")

                                # --- Pretty decision summary ---
                                dec = orch.get("decision", {}) if isinstance(orch, dict) else {}
                                loan_req = dec.get("loan_request", {}) or {}
                                decision_status = dec.get("decision", "N/A")
                                emi = dec.get("emi") or loan_req.get("est_emi")
                                tenure = loan_req.get("tenure_months") or "-"
                                loan_amt = loan_req.get("loan_amount") or "-"
                                pdf_url = orch.get("pdf_url")

                                # choose emoji and color based on decision
                                if str(decision_status).upper() == "APPROVE":
                                    icon = "✅"
                                    color = "#16a34a"  # green
                                elif str(decision_status).upper() == "REFER":
                                    icon = "⚠️"
                                    color = "#eab308"  # yellow
                                else:
                                    icon = "❌"
                                    color = "#dc2626"  # red

                                # Display card
                                st.markdown(f"""
                                <div style="
                                    background-color:#1e293b;
                                    border-radius:12px;
                                    padding:16px 20px;
                                    color:white;
                                    box-shadow:0 0 8px rgba(0,0,0,0.3);
                                ">
                                    <h3 style="margin-top:0;">{icon} Decision Summary</h3>
                                    <p><b>Decision:</b> <span style="color:{color};font-weight:bold;">{decision_status}</span></p>
                                    <p><b>Loan Amount:</b> ₹{int(float(loan_amt)):,}</p>
                                    <p><b>Tenure:</b> {tenure} months</p>
                                    <p><b>Estimated EMI:</b> ₹{int(float(emi)):,} / month</p>
                                </div>
                                """, unsafe_allow_html=True)

                                # --- Show download link if approved ---
                                import os  # make sure you have this import once at top of file

                                if str(decision_status).upper() == "APPROVE" and pdf_url:
                                    full_pdf = BACKEND.rstrip("/") + pdf_url
                                    st.markdown("### 📄 Sanction Letter")

                                    # Try to fetch PDF bytes from backend on demand and provide a download button
                                    try:
                                        resp = requests.get(full_pdf, timeout=10)
                                        if resp.status_code == 200:
                                            pdf_bytes = resp.content
                                            # Derive a friendly filename (basename of the url path)
                                            fname = os.path.basename(pdf_url) or "sanction_letter.pdf"
                                            # Show a download button — will only download when clicked
                                            st.download_button(
                                                label="⬇️ Download Sanction Letter",
                                                data=pdf_bytes,
                                                file_name=fname,
                                                mime="application/pdf"
                                            )
                                        else:
                                            st.warning("Sanction letter exists but could not be fetched right now. Try again later.")
                                            # fallback link (doesn't auto-download but opens in new tab if clicked)
                                            st.markdown(f"[Open sanction letter]({full_pdf})")
                                    except Exception as e:
                                        st.warning("Could not retrieve sanction letter from server.")
                                        st.markdown(f"[Open sanction letter]({full_pdf})")



                                # Embedded PDF preview (if provided)
                                pdf_url = orch.get("pdf_url")
                                if pdf_url:
                                    full_pdf = BACKEND.rstrip("/") + pdf_url
                                    st.markdown("### Sanction letter preview")
                                    try:
                                        components.iframe(full_pdf, height=600)
                                    except Exception:
                                        st.markdown(f"[Open sanction letter]({full_pdf})")
                        else:
                            statuses["kyc"] = "fail"
                            render_stepper(statuses)
                            st.error("KYC failed or missing data — workflow stopped. Please update CRM and try again.")


    with col2:
        if st.button("🧹 Clear Chat"):
            st.session_state.messages = []
            st.session_state.last_decision = None
            st.experimental_rerun()

st.caption("💡 Note: If you load a Customer ID, the UI will use stored income & existing debt from CRM and won't ask for them again.")
