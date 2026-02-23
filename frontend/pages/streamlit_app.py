"""
Blue Horizon - AI-Powered Hospitality Concierge
Streamlit Frontend: Concierge Agent (single-page mode)
"""

import uuid
import requests
import streamlit as st
# import pandas as pd  # (unused in single-page mode)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
API_BASE = "http://localhost:8000/api"
# API_BASE = "http://127.0.0.1:8000/api"
# NL2SQL_URL          = f"{API_BASE}/nl2sql/query"   # commented — not used in single-page mode
# SEARCH_URL          = f"{API_BASE}/faq/search"     # commented — not used in single-page mode
CONCIERGE_URL       = f"{API_BASE}/concierge/ask"
CONCIERGE_CLEAR_URL = f"{API_BASE}/concierge/clear"
CONCIERGE_CONNECT_TIMEOUT_SECONDS = 20
CONCIERGE_READ_TIMEOUT_SECONDS = 300

HOTEL_NAME  = "Blue Horizon"
HOTEL_TAGLINE = "AI-Powered Luxury Hospitality Concierge"

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title=f"{HOTEL_NAME} Concierge",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# SESSION STATE INIT  (must run before any widget renders)
# ─────────────────────────────────────────────
if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())
if "concierge_history" not in st.session_state:
    st.session_state.concierge_history = []
# if "nl2sql_history" not in st.session_state:  # commented — NL2SQL page removed
#     st.session_state.nl2sql_history = []
# if "active_page" not in st.session_state:     # commented — single page, no nav needed
#     st.session_state.active_page = "Concierge Agent"

# ─────────────────────────────────────────────
# GLOBAL CSS STYLING
# ─────────────────────────────────────────────
st.markdown("""
<style>
    /* ── Global font & background ── */
    html, body, [class*="css"] {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    .main { background-color: #f7f9fc; }

    /* ── Header banner ── */
    .bh-header {
        background: linear-gradient(135deg, #0a2342 0%, #1a6b9a 60%, #0e9aa7 100%);
        color: white;
        padding: 2rem 2.5rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 20px rgba(10,35,66,0.25);
    }
    .bh-header h1 { margin: 0; font-size: 2.2rem; letter-spacing: 1px; }
    .bh-header p  { margin: 0.3rem 0 0; font-size: 1rem; opacity: 0.88; }

    /* ── Section cards ── */
    .bh-card {
        background: white;
        border-radius: 12px;
        padding: 1.4rem 1.6rem;
        margin-bottom: 1.2rem;
        box-shadow: 0 2px 10px rgba(0,0,0,0.07);
        border-left: 4px solid #1a6b9a;
    }

    /* ── Chat bubbles ── */
    .chat-user {
        background: #e8f4fd;
        border-radius: 18px 18px 4px 18px;
        padding: 0.7rem 1rem;
        margin: 0.4rem 0;
        margin-left: 8%;
        border: 1px solid #c6e0f5;
        color: #0a2342;
    }
    .chat-assistant {
        background: #ffffff;
        border-radius: 18px 18px 18px 4px;
        padding: 0.7rem 1rem;
        margin: 0.4rem 0;
        margin-right: 8%;
        border: 1px solid #e0e0e0;
        color: #1a1a2e;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .chat-label-user      { text-align: right; font-size: 0.72rem; color: #666; margin-right: 4px; }
    .chat-label-assistant { text-align: left;  font-size: 0.72rem; color: #666; margin-left:  4px; }

    /* ── Result table tweaks ── */
    .stDataFrame { border-radius: 10px; overflow: hidden; }

    /* ── Status badges ── */
    .badge-success { background:#d4edda; color:#155724; border-radius:6px; padding:2px 8px; font-size:0.8rem; }
    .badge-error   { background:#f8d7da; color:#721c24; border-radius:6px; padding:2px 8px; font-size:0.8rem; }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0a2342 0%, #1a3a5c 100%);
    }
    [data-testid="stSidebar"] * { color: #dce8f5 !important; }
    [data-testid="stSidebar"] .stRadio label { font-size: 1rem; }

    /* ── Primary buttons ── */
    .stButton > button {
        background: linear-gradient(135deg, #1a6b9a, #0e9aa7);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.5rem 1.4rem;
        font-weight: 600;
        transition: opacity 0.2s;
    }
    .stButton > button:hover { opacity: 0.88; }

    /* ── Metric cards ── */
    [data-testid="metric-container"] {
        background: white;
        border-radius: 10px;
        padding: 0.8rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    }

    /* ── Divider ── */
    hr { border-color: #d0dcea; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("##  Blue Horizon")
    st.markdown("*AI Hospitality Concierge*")
    st.divider()

    # Navigation removed — single-page mode
    # page = st.radio(
    #     "Navigate",
    #     ["Concierge Agent", "Home", "Booking Data Query", "FAQ Search", "About"],
    #     key="nav_radio"
    # )
    # st.session_state.active_page = page

    st.markdown("**Session Info**")
    _uid = st.session_state.get("user_id") or str(uuid.uuid4())
    st.session_state["user_id"] = _uid
    st.caption(f"Session ID: `{_uid[:8]}...`")

    st.divider()

    # Backend health indicator
    try:
        health = requests.get(f"http://localhost:8000/", timeout=2)
        if health.status_code == 200:
            st.success("Backend: Online ✓")
        else:
            st.warning("Backend: Degraded")
    except Exception:
        st.error("Backend: Offline ✗")

    if st.button("Clear History"):
        uid = st.session_state.get("user_id", "guest")
        try:
            requests.post(f"{CONCIERGE_CLEAR_URL}/{uid}", timeout=5)
        except Exception:
            pass
        st.session_state.concierge_history = []
        st.rerun()


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def call_concierge(user_id: str, message: str) -> dict:
    """Send message to PydanticAI Concierge Agent (NL2SQL + FAQ + chat)."""
    try:
        resp = requests.post(
            CONCIERGE_URL,
            json={"user_id": user_id, "message": message},
            timeout=(CONCIERGE_CONNECT_TIMEOUT_SECONDS, CONCIERGE_READ_TIMEOUT_SECONDS),
        )
        try:
            body = resp.json()
        except Exception:
            body = {}
        if resp.status_code == 200:
            return {"success": True, "response": body.get("response", resp.text or "(no response)")}
        error_detail = body.get("detail") or resp.text or f"HTTP {resp.status_code}"
        return {"success": False, "error": error_detail}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Cannot connect to backend. Is the server running?"}
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": (
                "Agent response took too long. "
                f"Please try again (timeout: {CONCIERGE_READ_TIMEOUT_SECONDS}s)."
            ),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def clear_concierge_session(user_id: str) -> None:
    """Tell the backend to wipe the server-side conversation history for this user."""
    try:
        requests.post(f"{CONCIERGE_CLEAR_URL}/{user_id}", timeout=5)
    except Exception:
        pass  # Best-effort; local state is cleared regardless


# def call_search(query: str, top_k: int = 5) -> dict:  # commented — FAQ Search page removed
#     """Send semantic search query to FAQ search service."""
#     try:
#         resp = requests.post(SEARCH_URL, json={"query": query, "top_k": top_k}, timeout=60)
#         if resp.status_code == 200:
#             return {"success": True, **resp.json()}
#         return {"success": False, "error": resp.json().get("detail", f"HTTP {resp.status_code}")}
#     except requests.exceptions.ConnectionError:
#         return {"success": False, "error": "Cannot connect to backend."}
#     except Exception as e:
#         return {"success": False, "error": str(e)}


# def call_nl2sql(question: str) -> dict:  # commented — Booking Data Query page removed
#     """Send natural language question to NL2SQL agent."""
#     try:
#         resp = requests.post(NL2SQL_URL, json={"question": question}, timeout=300)
#         if resp.status_code == 200:
#             return {"success": True, **resp.json()}
#         return {"success": False, "error": resp.json().get("detail", f"HTTP {resp.status_code}")}
#     except requests.exceptions.ConnectionError:
#         return {"success": False, "error": "Cannot connect to backend."}
#     except Exception as e:
#         return {"success": False, "error": str(e)}


def render_header(title: str, subtitle: str = ""):
    """Render the top banner."""
    st.markdown(f"""
    <div class="bh-header">
        <h1>{title}</h1>
        <p>{subtitle}</p>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# commented — HOME PAGE
# ─────────────────────────────────────────────
# if page == "Home":
#     render_header(HOTEL_NAME, HOTEL_TAGLINE)
#     col1, col2, col3 = st.columns(3)
#     with col1:
#         st.markdown("""<div class="bh-card"><h3>Concierge Agent</h3>...</div>""", unsafe_allow_html=True)
#     with col2:
#         st.markdown("""<div class="bh-card"><h3>Booking Data Query</h3>...</div>""", unsafe_allow_html=True)
#     with col3:
#         st.markdown("""<div class="bh-card"><h3>Semantic FAQ Search</h3>...</div>""", unsafe_allow_html=True)
#     st.divider()
#     st.markdown("### Quick Start")
#     qs_col1, qs_col2 = st.columns(2)
#     with qs_col1:
#         st.markdown("**Try the Concierge Agent:** ...")
#     with qs_col2:
#         st.markdown("**Try Booking Data Queries:** ...")


# ─────────────────────────────────────────────
# commented — BOOKING DATA QUERY (NL2SQL) PAGE
# ─────────────────────────────────────────────
# elif page == "Booking Data Query":
#     render_header("Booking Data Query", "Ask questions in plain English — get live data from the database.")
#     with st.expander("Example Queries", expanded=False):
#         examples = [...]
#         for i, ex in enumerate(examples):
#             if cols[i % 2].button(ex, key=f"nl2sql_ex_{i}"):
#                 st.session_state._pending_nl2sql = ex
#     with st.form("nl2sql_form", clear_on_submit=True):
#         question = st.text_input(...)
#         query_submitted = st.form_submit_button("Run Query", use_container_width=True)
#     if query_submitted and question.strip():
#         result = call_nl2sql(question.strip())
#         st.session_state.nl2sql_history.append({"question": question.strip(), "result": result})
#     if st.session_state.nl2sql_history:
#         ... (display SQL, table, download CSV, history)


# ─────────────────────────────────────────────
# commented — FAQ SEARCH PAGE
# ─────────────────────────────────────────────
# elif page == "FAQ Search":
#     render_header("FAQ Search", "Semantic search through hotel FAQs and knowledge base.")
#     with st.expander("Example Searches", expanded=False):
#         examples = [...]
#         for i, ex in enumerate(examples):
#             if cols[i % 2].button(ex, key=f"faq_ex_{i}"):
#                 st.session_state._pending_search = ex
#     with st.form("search_form", clear_on_submit=False):
#         query = st.text_input(...)
#         search_submitted = st.form_submit_button("Search", use_container_width=True)
#         top_k = st.number_input("Results", min_value=1, max_value=10, value=5)
#     if search_submitted and query.strip():
#         result = call_search(query.strip(), top_k=int(top_k))
#         ... (display cards with relevance badges)


# ─────────────────────────────────────────────
# commented — ABOUT PAGE
# ─────────────────────────────────────────────
# elif page == "About":
#     render_header("About Blue Horizon AI", "Technology stack and system architecture")
#     col1, col2 = st.columns(2)
#     with col1:
#         st.markdown("""<div class="bh-card"><h3>Architecture</h3>...</div>""", unsafe_allow_html=True)
#     with col2:
#         st.markdown("""<div class="bh-card"><h3>AI Agents</h3>...</div>""", unsafe_allow_html=True)
#     st.markdown("""<div class="bh-card"><h3>API Endpoints</h3>...</div>""", unsafe_allow_html=True)
#     st.markdown("""<div class="bh-card"><h3>Running the App</h3>...</div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# commented — HOME PAGE (active content below, now removed)
# ─────────────────────────────────────────────
# render_header(HOTEL_NAME, HOTEL_TAGLINE)
# col1, col2, col3 = st.columns(3)  # (old home page cards)
# ...

# ─────────────────────────────────────────────
# commented — BOOKING DATA QUERY PAGE
# ─────────────────────────────────────────────
# elif page == "Booking Data Query":  (full block removed)

# ─────────────────────────────────────────────
# commented — FAQ SEARCH PAGE
# ─────────────────────────────────────────────
# elif page == "FAQ Search":  (full block removed)

# ─────────────────────────────────────────────
# commented — ABOUT PAGE
# ─────────────────────────────────────────────
# elif page == "About":  (full block removed)

# ─────────────────────────────────────────────
# PAGE: CONCIERGE AGENT  (PydanticAI orchestration)
# ─────────────────────────────────────────────
render_header(
    "Concierge Agent",
    "PydanticAI-powered agent — asks the right question, picks the right tool.",
)

# (old Home page cards and Quick Start section removed — single-page mode)


# ─────────────────────────────────────────────
# commented — BOOKING DATA QUERY PAGE (NL2SQL)
# ─────────────────────────────────────────────
# elif page == "Booking Data Query":
#     render_header(...)  — full block removed; call_nl2sql, pd.DataFrame, etc. not used.

# ─────────────────────────────────────────────
# commented — FAQ SEARCH PAGE
# ─────────────────────────────────────────────
# elif page == "FAQ Search":
#     render_header(...)  — full block removed; call_search not used.


st.markdown("""
<div class="bh-card">
    <strong>How it works:</strong> Ask anything. The agent decides whether to query
    the booking database (SQL), search the FAQ knowledge base, make a room reservation,
    or answer conversationally. You don't need to know which system to use — the agent figures it out.
</div>
""", unsafe_allow_html=True)

# Display conversation history
for turn in st.session_state.concierge_history:
    role    = turn["role"]
    content = turn["content"]
    if role == "user":
        st.markdown('<div class="chat-label-user">You</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="chat-user">{content}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="chat-label-assistant">Concierge Agent</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="chat-assistant">{content}</div>', unsafe_allow_html=True)

# Example prompts
with st.expander("Example prompts", expanded=len(st.session_state.concierge_history) == 0):
    examples = [
        "How many bookings were made in January?",
        "What is the cancellation policy?",
        "Which room type had the highest revenue last month?",
        "Is breakfast included in the room rate?",
        "Show me guests who checked in this week.",
        "What time does the pool open?",
        "Book a Deluxe room for Anaya Sharma, check-in 2026-03-10, check-out 2026-03-14, 2 adults.",
        "Is a Suite available from 2026-04-01 to 2026-04-05?",
    ]
    cols = st.columns(2)
    for i, ex in enumerate(examples):
        if cols[i % 2].button(ex, key=f"ca_ex_{i}"):
            st.session_state._ca_pending = ex

# Input form
with st.form("concierge_form", clear_on_submit=True):
    pending = getattr(st.session_state, "_ca_pending", "")
    user_input = st.text_input(
        "Ask the agent",
        value=pending,
        placeholder="e.g. How many VIP guests checked in this week?",
        label_visibility="collapsed",
    )
    col_s, col_c = st.columns([5, 1])
    submitted = col_s.form_submit_button("Send", use_container_width=True)
    cleared   = col_c.form_submit_button("Clear", use_container_width=True)

if cleared:
    uid = st.session_state.get("user_id", "guest")
    clear_concierge_session(uid)
    st.session_state.concierge_history = []
    st.rerun()

if submitted and user_input.strip():
    if hasattr(st.session_state, "_ca_pending"):
        del st.session_state._ca_pending

    st.session_state.concierge_history.append({"role": "user", "content": user_input.strip()})
    uid = st.session_state.get("user_id", "guest")

    with st.spinner("Agent is thinking..."):
        result = call_concierge(uid, user_input.strip())

    if result["success"]:
        reply = result["response"]
    else:
        reply = f"Error: {result['error']}"

    st.session_state.concierge_history.append({"role": "assistant", "content": reply})
    st.rerun()


# ─────────────────────────────────────────────
# commented — ABOUT PAGE
# ─────────────────────────────────────────────
# elif page == "About":
# (About page body removed — render_header, architecture cards, API table, running-the-app block)