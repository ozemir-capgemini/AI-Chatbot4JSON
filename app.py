"""DMACO – Streamlit chat-based SPA (Section 9 of spec).

Single-page chat interface with:
- Chat history (scrollable)
- Button-based selection for domains, sub-domains, confirmations
- Structured few-shot form (separate question + SQL fields)
- Downloadable JSON + email send simulation
- Stepper progress in the sidebar
- Read-only JSON preview panel
- FSM enforcement — no skipping, no backtracking
- All inputs sanitised before processing
- Contextual help text for non-technical users
"""

import json
from dotenv import load_dotenv
import streamlit as st
from bot.state import BotMemory, FSMState
from bot.engine import process_user_input, STEP_HELP
from bot.validators import get_all_domains, get_all_subdomains
from bot.backlog import record_table_change

load_dotenv()

# ------------------------------------------------------------------
# T-Mobile brand CSS
# ------------------------------------------------------------------
_TMOBILE_CSS = """
<style>
/* ── Imports ─────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* ── Root variables ──────────────────────────────────────────── */
:root {
    --tm-magenta:      #E20074;
    --tm-magenta-dark: #B8005E;
    --tm-magenta-glow: #FF2D9B;
    --tm-black:        #1A1A2E;
    --tm-dark:         #2D2D44;
    --tm-gray:         #A0A0B8;
    --tm-white:        #FFFFFF;
    --tm-surface:      #23233A;
    --tm-border:       #3D3D5C;
}

/* ── Global typography ───────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}

/* ── App background ──────────────────────────────────────────── */
.stApp {
    background: linear-gradient(160deg, var(--tm-black) 0%, #12122A 50%, #0D0D20 100%);
}

/* ── Sidebar ─────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--tm-dark) 0%, var(--tm-black) 100%);
    border-right: 2px solid var(--tm-magenta);
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: var(--tm-magenta) !important;
}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] li {
    color: var(--tm-white) !important;
}

/* ── Primary (magenta) buttons ───────────────────────────────── */
button[kind="primary"],
.stButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primary"] {
    background: linear-gradient(135deg, var(--tm-magenta) 0%, var(--tm-magenta-dark) 100%) !important;
    color: var(--tm-white) !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 700 !important;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    font-size: 0.85rem !important;
    padding: 0.55rem 1.2rem !important;
    transition: all 0.2s ease;
    box-shadow: 0 2px 8px rgba(226, 0, 116, 0.35);
}
button[kind="primary"]:hover,
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, var(--tm-magenta-glow) 0%, var(--tm-magenta) 100%) !important;
    box-shadow: 0 4px 16px rgba(226, 0, 116, 0.55);
    transform: translateY(-1px);
}

/* ── Secondary (default) buttons ─────────────────────────────── */
button[kind="secondary"],
.stButton > button[kind="secondary"],
.stButton > button:not([kind]) {
    background: var(--tm-surface) !important;
    color: var(--tm-magenta) !important;
    border: 1.5px solid var(--tm-magenta) !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    font-size: 0.85rem !important;
    padding: 0.55rem 1.2rem !important;
    transition: all 0.2s ease;
}
button[kind="secondary"]:hover,
.stButton > button[kind="secondary"]:hover,
.stButton > button:not([kind]):hover {
    background: rgba(226, 0, 116, 0.12) !important;
    border-color: var(--tm-magenta-glow) !important;
    color: var(--tm-magenta-glow) !important;
}

/* ── Download button ─────────────────────────────────────────── */
.stDownloadButton > button {
    background: linear-gradient(135deg, var(--tm-magenta) 0%, var(--tm-magenta-dark) 100%) !important;
    color: var(--tm-white) !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    box-shadow: 0 2px 8px rgba(226, 0, 116, 0.35);
}
.stDownloadButton > button:hover {
    background: linear-gradient(135deg, var(--tm-magenta-glow) 0%, var(--tm-magenta) 100%) !important;
    box-shadow: 0 4px 16px rgba(226, 0, 116, 0.55);
}

/* ── Text inputs & text areas ────────────────────────────────── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    background: var(--tm-surface) !important;
    border: 1.5px solid var(--tm-border) !important;
    border-radius: 8px !important;
    color: var(--tm-white) !important;
    font-family: 'Inter', sans-serif !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: var(--tm-magenta) !important;
    box-shadow: 0 0 0 2px rgba(226, 0, 116, 0.25) !important;
}
.stTextInput label,
.stTextArea label {
    color: var(--tm-gray) !important;
    font-weight: 500;
}

/* ── Chat input ──────────────────────────────────────────────── */
[data-testid="stChatInput"] textarea {
    background: var(--tm-surface) !important;
    border: 1.5px solid var(--tm-border) !important;
    border-radius: 12px !important;
    color: var(--tm-white) !important;
}
[data-testid="stChatInput"] textarea:focus {
    border-color: var(--tm-magenta) !important;
    box-shadow: 0 0 0 2px rgba(226, 0, 116, 0.25) !important;
}

/* ── Chat bubbles ────────────────────────────────────────────── */
[data-testid="stChatMessage"] {
    border-radius: 12px !important;
    padding: 1rem !important;
    margin-bottom: 0.6rem !important;
}
[data-testid="stChatMessage"][data-testid*="assistant"] {
    background: var(--tm-surface) !important;
    border-left: 3px solid var(--tm-magenta);
}

/* ── Expanders ───────────────────────────────────────────────── */
.streamlit-expanderHeader {
    background: var(--tm-surface) !important;
    border-radius: 8px !important;
    color: var(--tm-white) !important;
    font-weight: 600 !important;
}

/* ── JSON preview ────────────────────────────────────────────── */
[data-testid="stJson"] {
    background: var(--tm-surface) !important;
    border-radius: 8px !important;
    border: 1px solid var(--tm-border) !important;
}

/* ── Dividers ────────────────────────────────────────────────── */
hr {
    border-color: var(--tm-border) !important;
}

/* ── Success / Warning toasts ────────────────────────────────── */
.stSuccess { border-left-color: #00C853 !important; }
.stWarning { border-left-color: #FFD600 !important; }

/* ── Title & captions ────────────────────────────────────────── */
h1 {
    color: var(--tm-magenta) !important;
    font-weight: 800 !important;
    letter-spacing: -0.02em;
}
.stCaption, [data-testid="stCaption"] {
    color: var(--tm-gray) !important;
}

/* ── Stepper progress markers ────────────────────────────────── */
.stepper-done  { color: var(--tm-magenta-glow); }
.stepper-active { color: var(--tm-magenta); font-weight: 700; }
.stepper-todo  { color: var(--tm-gray); }

/* ── Forms ───────────────────────────────────────────────────── */
[data-testid="stForm"] {
    background: var(--tm-surface) !important;
    border: 1px solid var(--tm-border) !important;
    border-radius: 12px !important;
    padding: 1rem !important;
}

/* ── Scrollbar ───────────────────────────────────────────────── */
::-webkit-scrollbar { width: 8px; }
::-webkit-scrollbar-track { background: var(--tm-black); }
::-webkit-scrollbar-thumb {
    background: var(--tm-magenta-dark);
    border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover { background: var(--tm-magenta); }
</style>
"""
STEP_LABELS: list[tuple[FSMState, str]] = [
    (FSMState.DOMAIN_SELECTION,       "1. Pick a Domain"),
    (FSMState.GENERAL_PROMPT_ENTRY,   "2. Set the Prompt"),
    (FSMState.TABLE_OP,               "3. Define Tables"),
    (FSMState.SUBDOMAIN_SELECTION,    "4. Choose Focus Area"),
    (FSMState.SUBDOMAIN_PROMPT_ENTRY, "5. Focus Area Prompt"),
    (FSMState.FEWSHOT_ENTRY,          "6. Add Examples"),
    (FSMState.FINAL_ASSEMBLY,         "7. Export"),
]


# ------------------------------------------------------------------
# Session-state helpers
# ------------------------------------------------------------------

def _init() -> None:
    """Bootstrap session-state on first load."""
    if "fsm" not in st.session_state:
        st.session_state.fsm = FSMState.INIT
    if "memory" not in st.session_state:
        st.session_state.memory = BotMemory()
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "started" not in st.session_state:
        st.session_state.started = False


def _extract_col_names(ddl: str) -> list[str]:
    """Extract column names from a CREATE TABLE DDL for friendly display."""
    import re
    # Match lines like "  column_name TYPE ..."
    cols = re.findall(r'^\s+(\w+)\s+\w+', ddl, re.MULTILINE)
    # Filter out noise like 'PRIMARY', 'CONSTRAINT', 'UNIQUE', 'INDEX', 'CHECK', 'FOREIGN'
    skip = {'primary', 'constraint', 'unique', 'index', 'check', 'foreign', 'key', 'references'}
    return [c for c in cols if c.lower() not in skip]


def _current_step_idx(fsm: FSMState) -> int:
    """Map the current FSM state to a 0-based step index for the stepper."""
    for i, (threshold, _) in enumerate(STEP_LABELS):
        if fsm.value < threshold.value:
            return max(i - 1, 0)
    return len(STEP_LABELS) - 1


def _send(user_text: str, *, show_user: bool = True) -> None:
    """Send *user_text* through the FSM, appending messages to chat history."""
    if show_user:
        st.session_state.messages.append({"role": "user", "content": user_text})

    reply, new_state = process_user_input(
        st.session_state.fsm,
        st.session_state.memory,
        user_text,
    )
    st.session_state.fsm = new_state
    st.session_state.messages.append({"role": "assistant", "content": reply})

    # Auto-trigger assembly (no user input needed)
    if new_state == FSMState.FINAL_ASSEMBLY:
        reply2, new_state2 = process_user_input(
            FSMState.FINAL_ASSEMBLY, st.session_state.memory, ""
        )
        st.session_state.fsm = new_state2
        st.session_state.messages.append({"role": "assistant", "content": reply2})


# ------------------------------------------------------------------
# Reusable: contextual help
# ------------------------------------------------------------------


def _render_help() -> None:
    """Show contextual blue info box for the current step."""
    fsm = st.session_state.fsm
    # Map confirmation states to their parent step for help text
    help_map = {
        FSMState.DOMAIN_CONFIRMATION: FSMState.DOMAIN_SELECTION,
        FSMState.GENERAL_PROMPT_CONFIRMATION: FSMState.GENERAL_PROMPT_ENTRY,
        FSMState.TABLE_CONFIRMATION: FSMState.TABLE_OP,
        FSMState.SUBDOMAIN_CONFIRMATION: FSMState.SUBDOMAIN_SELECTION,
        FSMState.SUBDOMAIN_PROMPT_CONFIRMATION: FSMState.SUBDOMAIN_PROMPT_ENTRY,
        FSMState.FEWSHOT_CONFIRMATION: FSMState.FEWSHOT_ENTRY,
    }
    lookup = help_map.get(fsm, fsm)
    tip = STEP_HELP.get(lookup)
    if tip:
        st.info(f"💡 **Tip:** {tip}", icon="ℹ️")


# ------------------------------------------------------------------
# Action-panel renderers (buttons / forms shown below chat)
# ------------------------------------------------------------------

def _render_domain_buttons() -> None:
    """Show clickable buttons for each available domain + Add New."""
    st.markdown("##### Select a domain")
    domains = get_all_domains()
    cols = st.columns(min(len(domains), 4))
    for i, d in enumerate(domains):
        if cols[i % 4].button(d.replace("_", " ").title(), key=f"dom_{d}", use_container_width=True):
            _send(d)
            st.rerun()
    st.divider()
    with st.expander("➕ Add a new domain"):
        new_dom = st.text_input("New domain name", key="new_domain_input")
        if st.button("Add Domain", key="add_domain_btn"):
            if new_dom.strip():
                _send(f"add {new_dom.strip()}")
                st.rerun()


def _render_subdomain_buttons() -> None:
    """Show clickable buttons for each sub-domain under the current domain + Add New."""
    mem: BotMemory = st.session_state.memory
    subs = get_all_subdomains(mem.domain)
    if subs:
        st.markdown("##### Select a focus area")
        cols = st.columns(min(len(subs), 4))
        for i, s in enumerate(subs):
            if cols[i % 4].button(s.replace("_", " ").title(), key=f"sub_{s}", use_container_width=True):
                _send(s)
                st.rerun()
    st.divider()
    with st.expander("➕ Add a new focus area"):
        new_sub = st.text_input("New focus area name", key="new_subdomain_input")
        if st.button("Add Focus Area", key="add_subdomain_btn"):
            if new_sub.strip():
                _send(f"add {new_sub.strip()}")
                st.rerun()


def _render_yes_no(label: str = "Confirm?") -> None:
    """Show Yes / No buttons for confirmation states."""
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Yes", key="confirm_yes", type="primary", use_container_width=True):
        _send("yes")
        st.rerun()
    if c2.button("No", key="confirm_no", use_container_width=True):
        _send("no")
        st.rerun()


def _render_keep_change() -> None:
    """Show Keep / Change buttons for prompt keep-or-edit states."""
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Keep", key="prompt_keep", type="primary", use_container_width=True):
        _send("keep")
        st.rerun()
    if c2.button("Change", key="prompt_change", use_container_width=True):
        _send("change")
        st.rerun()


def _render_table_actions() -> None:
    """Show table action panel: Add / Edit buttons with SQL input form."""
    mem: BotMemory = st.session_state.memory

    # Show existing tables as friendly cards
    if mem.tables:
        st.markdown(f"##### Your tables ({len(mem.tables)})")
        for i, t in enumerate(mem.tables):
            # Extract column names for a friendly summary
            cols_list = _extract_col_names(t.description)
            col_summary = ", ".join(cols_list[:6])
            if len(cols_list) > 6:
                col_summary += f", … (+{len(cols_list) - 6} more)"
            with st.expander(f"📋 **{t.name}** — {len(cols_list)} columns", expanded=False):
                st.caption(f"Columns: {col_summary}")
                st.code(t.description, language="sql")

    # If a pending table is awaiting confirmation, show Yes/No only
    if mem._pending_table is not None and mem._pending_table.name:
        _render_yes_no("Confirm this table?")
        return

    # Determine if we are in edit mode
    editing = mem._table_mode == "edit" and mem._edit_table_idx is not None

    if editing:
        old = mem.tables[mem._edit_table_idx]  # type: ignore[index]
        st.markdown(f"##### ✏️ Editing table: {old.name}")
        default_sql = old.description
        form_label = "Enter updated SQL (CREATE TABLE to replace, or ALTER TABLE to modify)"
        btn_label = "Update Table"
    else:
        st.markdown("##### ➕ Add a table")
        default_sql = ""
        form_label = "CREATE TABLE statement"
        btn_label = "Add Table"

    with st.form("table_sql_form", clear_on_submit=True):
        sql = st.text_area(
            form_label,
            value=default_sql,
            placeholder="CREATE TABLE orders (\n  id INT PRIMARY KEY,\n  customer_id INT,\n  amount DECIMAL(10,2),\n  order_date DATE\n)",
            height=160,
            help="Paste a CREATE TABLE SQL statement. Don't worry about getting it perfect — you can edit later.",
        )
        submitted = st.form_submit_button(btn_label, type="primary")
    if submitted and sql.strip():
        _send(f"__table_sql::{sql.strip()}", show_user=False)
        action = "Updated" if editing else "Added"
        st.session_state.messages.insert(-1, {
            "role": "user",
            "content": f"**{action}:**\n```sql\n{sql.strip()}\n```",
        })
        st.rerun()

    # Cancel edit button
    if editing:
        if st.button("Cancel Edit", key="cancel_edit_btn"):
            mem._table_mode = ""
            mem._edit_table_idx = None
            st.rerun()

    # Edit + Delete + Done buttons (only when NOT already in edit mode)
    if mem.tables and not editing:
        st.divider()
        c_edit, c_del, c_done = st.columns(3)
        with c_edit:
            with st.expander("✏️ Edit a table"):
                for i, t in enumerate(mem.tables):
                    if st.button(f"Edit: {t.name}", key=f"table_edit_{i}"):
                        _send(f"edit {i+1}")
                        st.rerun()
        with c_del:
            with st.expander("🗑️ Remove a table"):
                for i, t in enumerate(mem.tables):
                    if st.button(f"Remove: {t.name}", key=f"table_del_{i}"):
                        record_table_change("delete", t.name, t.description)
                        mem.tables.pop(i)
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": f"🗑️ Table **{t.name}** removed.",
                        })
                        st.rerun()
        with c_done:
            if st.button("✅ Done — continue", key="table_done_btn", type="primary", use_container_width=True):
                _send("done")
                st.rerun()


def _render_fewshot_form() -> None:
    """Show structured form with separate question + SQL fields, plus Done button."""
    mem: BotMemory = st.session_state.memory
    if mem.few_shots:
        st.markdown(f"##### Your examples ({len(mem.few_shots)})")
        for i, e in enumerate(mem.few_shots):
            with st.expander(f"**{i+1}.** {e.question[:60]}{'…' if len(e.question) > 60 else ''}", expanded=False):
                st.markdown(f"**Question:** {e.question}")
                st.code(e.sql, language="sql")
                if st.button(f"🗑️ Remove this example", key=f"fs_del_{i}"):
                    mem.few_shots.pop(i)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": f"🗑️ Example {i+1} removed.",
                    })
                    st.rerun()

    st.markdown("##### ➕ Add an example")
    st.caption("An example teaches the bot how to turn a question into SQL. Give it a plain-English question and its answer as a SQL query.")
    with st.form("fewshot_form", clear_on_submit=True):
        q = st.text_input(
            "Question (plain English)",
            placeholder="e.g. What were total sales last month?",
            help="Write the question a user would ask in everyday language.",
        )
        sql = st.text_area(
            "SQL answer",
            placeholder="e.g. SELECT SUM(amount) FROM orders WHERE ...",
            height=100,
            help="Write the SQL query that answers the question above.",
        )
        submitted = st.form_submit_button("Add Example", type="primary")
    if submitted and q.strip() and sql.strip():
        payload = json.dumps({"question": q.strip(), "sql": sql.strip()})
        _send(f"__fewshot_structured::{payload}", show_user=False)
        # Show a friendly user-facing message instead of the raw payload
        st.session_state.messages.insert(-1, {
            "role": "user",
            "content": f"**Q:** {q.strip()}\n**SQL:** `{sql.strip()}`",
        })
        st.rerun()

    if mem.few_shots:
        if st.button("✅ Done — confirm examples", key="fewshot_done_btn", type="primary"):
            _send("done")
            st.rerun()


def _render_complete_panel() -> None:
    """Show download + email send panel when configuration is complete."""
    mem: BotMemory = st.session_state.memory
    output = json.dumps(mem.to_dict(), indent=2)

    st.divider()
    st.markdown("##### Export")

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            label="Download JSON",
            data=output,
            file_name="output.json",
            mime="application/json",
            type="primary",
            use_container_width=True,
        )
    with c2:
        email = st.text_input("Recipient email", placeholder="user@example.com", key="email_input")
        if st.button("Send", key="send_email_btn", use_container_width=True):
            if email.strip():
                st.success(f"Configuration sent to **{email.strip()}** (simulated).")
            else:
                st.warning("Please enter an email address.")


# ------------------------------------------------------------------
# Determine which action panel to show based on current FSM state
# ------------------------------------------------------------------

def _render_action_panel() -> None:
    """Render contextual buttons / forms below the chat area."""
    fsm = st.session_state.fsm

    # Contextual help + Go Back (shown on most steps)
    _render_help()

    if fsm == FSMState.DOMAIN_SELECTION:
        _render_domain_buttons()

    elif fsm == FSMState.DOMAIN_CONFIRMATION:
        _render_yes_no("Confirm domain?")

    elif fsm == FSMState.GENERAL_PROMPT_ENTRY:
        # If a suggested/stored prompt was shown, offer keep/change buttons
        mem: BotMemory = st.session_state.memory
        if mem._suggested_prompt:
            _render_keep_change()

    elif fsm == FSMState.GENERAL_PROMPT_CONFIRMATION:
        _render_yes_no("Confirm prompt?")

    elif fsm == FSMState.TABLE_OP:
        _render_table_actions()

    elif fsm == FSMState.TABLE_CONFIRMATION:
        _render_yes_no("Confirm tables?")

    elif fsm == FSMState.SUBDOMAIN_SELECTION:
        _render_subdomain_buttons()

    elif fsm == FSMState.SUBDOMAIN_CONFIRMATION:
        _render_yes_no("Confirm focus area?")

    elif fsm == FSMState.SUBDOMAIN_PROMPT_ENTRY:
        # Check if stored prompt exists → show keep/change
        mem2: BotMemory = st.session_state.memory
        from bot.validators import get_subdomain_prompt
        stored = get_subdomain_prompt(mem2.domain, mem2.sub_domain)
        if stored:
            _render_keep_change()

    elif fsm == FSMState.SUBDOMAIN_PROMPT_CONFIRMATION:
        _render_yes_no("Confirm focus area prompt?")

    elif fsm == FSMState.FEWSHOT_ENTRY:
        _render_fewshot_form()

    elif fsm == FSMState.FEWSHOT_CONFIRMATION:
        st.markdown("##### Ready to finish?")
        if st.button("✅ Finish & Export", key="confirm_yes", type="primary", use_container_width=True):
            _send("yes")
            st.rerun()

    elif fsm == FSMState.COMPLETE:
        _render_complete_panel()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="DMACO | T-Mobile", layout="wide", page_icon="📱")
    _init()

    # Inject T-Mobile brand CSS
    st.markdown(_TMOBILE_CSS, unsafe_allow_html=True)

    # ----- Sidebar: stepper + JSON preview ----------------------------
    with st.sidebar:
        st.markdown(
            '<div style="text-align:center;padding:0.5rem 0 1rem;">'
            '<span style="font-size:2rem;font-weight:800;color:#E20074;letter-spacing:-0.03em;">'
            'T&#x2011;Mobile</span><br>'
            '<span style="font-size:0.75rem;color:#A0A0B8;text-transform:uppercase;letter-spacing:0.15em;">'
            'DMACO Configuration</span></div>',
            unsafe_allow_html=True,
        )
        st.divider()
        st.markdown("#### Progress")
        current_idx = _current_step_idx(st.session_state.fsm)

        # Visual progress bar
        total_steps = len(STEP_LABELS)
        progress_pct = min((current_idx + 1) / total_steps, 1.0)
        if st.session_state.fsm == FSMState.COMPLETE:
            progress_pct = 1.0
        st.progress(progress_pct, text=f"Step {current_idx + 1} of {total_steps}")

        for i, (_, label) in enumerate(STEP_LABELS):
            if i < current_idx:
                st.markdown(
                    f'<p class="stepper-done">✅&ensp;<s>{label}</s></p>',
                    unsafe_allow_html=True,
                )
            elif i == current_idx:
                st.markdown(
                    f'<p class="stepper-active">▸&ensp;<strong>{label}</strong></p>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<p class="stepper-todo">○&ensp;{label}</p>',
                    unsafe_allow_html=True,
                )

        st.divider()

        # Read-only JSON preview (Section 9)
        st.subheader("JSON Preview")
        mem: BotMemory = st.session_state.memory
        st.json(mem.to_dict())

        st.divider()
        if st.button("Reset", use_container_width=True, type="primary"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # ----- Main: chat area --------------------------------------------
    st.markdown(
        '<h1 style="margin-bottom:0;">DMACO</h1>',
        unsafe_allow_html=True,
    )
    st.caption("Configure your text-to-SQL bot step by step — no coding required.")

    # Auto-start: send the INIT greeting on first load
    if not st.session_state.started:
        _send("", show_user=False)
        st.session_state.started = True

    # Render chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Contextual action panel (buttons / forms)
    _render_action_panel()

    # Free-text chat input (always available except at COMPLETE)
    if st.session_state.fsm == FSMState.COMPLETE:
        st.chat_input("Configuration complete.", disabled=True)
    elif user_input := st.chat_input("Type your response…"):
        _send(user_input)
        st.rerun()


if __name__ == "__main__":
    main()
