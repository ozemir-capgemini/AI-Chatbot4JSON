"""DMACO – Streamlit chat-based SPA (Section 9 of spec).

Single-page chat interface with:
- Chat history (scrollable)
- Stepper progress in the sidebar
- Read-only JSON preview panel
- FSM enforcement — no skipping, no backtracking
- All inputs sanitised before processing
"""

import json
from dotenv import load_dotenv
import streamlit as st
from bot.state import BotMemory, FSMState
from bot.engine import process_user_input

load_dotenv()

# ------------------------------------------------------------------
# Step labels for the sidebar stepper
# ------------------------------------------------------------------
STEP_LABELS: list[tuple[FSMState, str]] = [
    (FSMState.DOMAIN_SELECTION,     "1. Domain"),
    (FSMState.GENERAL_PROMPT_ENTRY, "2. General Prompt"),
    (FSMState.TABLE_OP,             "3. Tables"),
    (FSMState.SUBDOMAIN_SELECTION,  "4. Sub-Domain"),
    (FSMState.SUBDOMAIN_PROMPT_ENTRY, "5. Sub-Domain Prompt"),
    (FSMState.FEWSHOT_ENTRY,        "6. Few-Shot Examples"),
    (FSMState.FINAL_ASSEMBLY,       "7. Assemble & Export"),
]


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


def _current_step_idx(fsm: FSMState) -> int:
    """Map the current FSM state to a 0-based step index for the stepper."""
    for i, (threshold, _) in enumerate(STEP_LABELS):
        if fsm.value < threshold.value:
            return max(i - 1, 0)
    return len(STEP_LABELS) - 1


def main() -> None:
    st.set_page_config(page_title="DMACO", layout="wide")
    _init()

    # ----- Sidebar: stepper + JSON preview ----------------------------
    with st.sidebar:
        st.header("Progress")
        current_idx = _current_step_idx(st.session_state.fsm)

        for i, (_, label) in enumerate(STEP_LABELS):
            if i < current_idx:
                st.markdown(f"✅  ~~{label}~~")
            elif i == current_idx:
                st.markdown(f"👉  **{label}**")
            else:
                st.markdown(f"⬜  {label}")

        st.divider()

        # Read-only JSON preview (Section 9)
        st.subheader("JSON Preview")
        mem: BotMemory = st.session_state.memory
        st.json(mem.to_dict())

        st.divider()
        if st.button("🔄 Reset", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # ----- Main: chat area --------------------------------------------
    st.title("DMACO")
    st.caption("Deterministic Multi-Agent Configuration Orchestrator")

    # Auto-start: send the INIT greeting on first load
    if not st.session_state.started:
        reply, new_state = process_user_input(
            FSMState.INIT, st.session_state.memory, ""
        )
        st.session_state.fsm = new_state
        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.session_state.started = True

    # Render chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if st.session_state.fsm == FSMState.COMPLETE:
        st.chat_input("Configuration complete.", disabled=True)
    elif user_input := st.chat_input("Type your response…"):
        # Show user message
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # Process through FSM
        reply, new_state = process_user_input(
            st.session_state.fsm,
            st.session_state.memory,
            user_input,
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

        st.rerun()


if __name__ == "__main__":
    main()
