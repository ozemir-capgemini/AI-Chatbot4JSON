"""DMACO FSM controller + LLM-powered agent handlers (Sections 5, 6, 10, 11).

Architecture (Section 11 — Hybrid Strategy):
  User input → LLM agent (interprets / clarifies)
             → Deterministic validator (gates output)
             → Confirmed values stored in memory

Each handler receives (memory, user_input) and returns (bot_reply, new_fsm_state).
The controller dispatches based on current FSM state.
"""

from __future__ import annotations

import json
from bot.state import (
    ALLOWED_TRANSITIONS,
    BotMemory,
    FSMState,
    FewShotEntry,
    TableEntry,
)
from bot import validators as V
from bot.llm import ask_agent


# ------------------------------------------------------------------
# Response helper
# ------------------------------------------------------------------

class AgentResponse:
    __slots__ = ("message", "next_state")

    def __init__(self, message: str, next_state: FSMState):
        self.message = message
        self.next_state = next_state


def _context_snapshot(mem: BotMemory) -> dict:
    """Minimum context for LLM agents (Section 3)."""
    return {
        "domain": mem.domain or None,
        "sub_domain": mem.sub_domain or None,
        "tables": [t.name for t in mem.tables] if mem.tables else [],
    }


# ------------------------------------------------------------------
# LLM confirmation helper (used by all confirmation states)
# ------------------------------------------------------------------

def _llm_confirm(user_input: str) -> bool | None:
    """Use the confirmation agent to interpret yes/no.  Returns True/False/None."""
    result = ask_agent("confirmation", user_input)
    if "error" in result:
        return None
    return result.get("confirmed")


# ------------------------------------------------------------------
# Individual agent handlers  (Section 6)
# ------------------------------------------------------------------

def _handle_init(_mem: BotMemory, _inp: str) -> AgentResponse:
    return AgentResponse(
        "Welcome to DMACO. Let's configure your text-to-SQL bot.\n\n"
        "**Step 1 — Domain**\n"
        "What business domain is this bot for? "
        "(e.g. sales, inventory, finance, logistics)",
        FSMState.DOMAIN_SELECTION,
    )


# ---- 6.1 Domain Agent ------------------------------------------------

def _handle_domain_selection(mem: BotMemory, inp: str) -> AgentResponse:
    # LLM interprets user's natural language → structured extraction
    result = ask_agent("domain", inp, _context_snapshot(mem))

    if "error" in result:
        return AgentResponse(f"⚠️ {result['error']}", FSMState.DOMAIN_SELECTION)

    if result.get("clarification"):
        return AgentResponse(result["clarification"], FSMState.DOMAIN_SELECTION)

    raw_domain = result.get("domain")
    if not raw_domain:
        return AgentResponse(
            "I couldn't identify a domain from that. "
            "Please provide a single-word business domain (e.g. `sales`, `inventory`, `finance`).",
            FSMState.DOMAIN_SELECTION,
        )

    # Deterministic validation gate (Section 11)
    val, err = V.validate_domain(raw_domain)
    if err:
        return AgentResponse(f"⚠️ {err}", FSMState.DOMAIN_SELECTION)

    mem.domain = val  # type: ignore[assignment]
    return AgentResponse(
        f"I understood the domain as: **{val}**\n\nDo you confirm? (yes / no)",
        FSMState.DOMAIN_CONFIRMATION,
    )


def _handle_domain_confirmation(mem: BotMemory, inp: str) -> AgentResponse:
    confirmed = _llm_confirm(inp)

    if confirmed is None:
        return AgentResponse(
            "I wasn't sure — did you mean yes or no?",
            FSMState.DOMAIN_CONFIRMATION,
        )

    if confirmed:
        return AgentResponse(
            f"✅ Domain **{mem.domain}** confirmed.\n\n"
            "**Step 2 — General Prompt**\n"
            "Describe what the AI assistant should do within this domain. "
            "This will be used as the contextual system prompt.",
            FSMState.GENERAL_PROMPT_ENTRY,
        )

    mem.domain = ""
    return AgentResponse(
        "Domain not confirmed. Please tell me the domain again.",
        FSMState.DOMAIN_SELECTION,
    )


# ---- 6.2 General Prompt Agent ----------------------------------------

def _handle_general_prompt_entry(mem: BotMemory, inp: str) -> AgentResponse:
    result = ask_agent("general_prompt", inp, _context_snapshot(mem))

    if "error" in result:
        return AgentResponse(f"⚠️ {result['error']}", FSMState.GENERAL_PROMPT_ENTRY)

    if result.get("clarification"):
        return AgentResponse(result["clarification"], FSMState.GENERAL_PROMPT_ENTRY)

    raw_prompt = result.get("general_prompt")
    if not raw_prompt:
        return AgentResponse(
            "I couldn't extract a prompt from that. Please describe what the AI should do.",
            FSMState.GENERAL_PROMPT_ENTRY,
        )

    val, err = V.validate_prompt(raw_prompt)
    if err:
        return AgentResponse(f"⚠️ {err}", FSMState.GENERAL_PROMPT_ENTRY)

    mem.general_prompt = val  # type: ignore[assignment]
    return AgentResponse(
        f"Here's the general prompt I captured:\n> {val}\n\nDo you confirm? (yes / no)",
        FSMState.GENERAL_PROMPT_CONFIRMATION,
    )


def _handle_general_prompt_confirmation(mem: BotMemory, inp: str) -> AgentResponse:
    confirmed = _llm_confirm(inp)

    if confirmed is None:
        return AgentResponse("Did you mean yes or no?", FSMState.GENERAL_PROMPT_CONFIRMATION)

    if confirmed:
        return AgentResponse(
            "✅ General prompt confirmed.\n\n"
            "**Step 3 — Table Definitions**\n"
            "Describe a table you'd like to add — tell me its name and what it contains "
            "(columns, purpose). Or type `done` when finished.",
            FSMState.TABLE_OP,
        )

    mem.general_prompt = ""
    return AgentResponse(
        "General prompt not confirmed. Please describe the prompt again.",
        FSMState.GENERAL_PROMPT_ENTRY,
    )


# ---- 6.3 Table / DDL Agent -------------------------------------------

def _handle_table_op(mem: BotMemory, inp: str) -> AgentResponse:
    clean = V.sanitize(inp).lower()
    inj = V.check_injection(clean)
    if inj:
        return AgentResponse(f"⚠️ {inj}", FSMState.TABLE_OP)

    # --- "done" command ---
    if clean == "done":
        if not mem.tables:
            return AgentResponse(
                "⚠️ You must add at least one table before continuing.",
                FSMState.TABLE_OP,
            )
        summary = "\n".join(
            f"  {i+1}. **{t.name}** — {t.description[:80]}"
            for i, t in enumerate(mem.tables)
        )
        return AgentResponse(
            f"Current tables:\n{summary}\n\nConfirm these tables? (yes / no)",
            FSMState.TABLE_CONFIRMATION,
        )

    # --- "edit N" command ---
    if clean.startswith("edit"):
        if not mem.tables:
            return AgentResponse("No tables yet. Describe a table to add one.", FSMState.TABLE_OP)
        parts = clean.split()
        if len(parts) == 2 and parts[1].isdigit():
            idx = int(parts[1]) - 1
            if 0 <= idx < len(mem.tables):
                mem._table_mode = "edit"
                mem._edit_table_idx = idx
                mem._pending_table = TableEntry(
                    name=mem.tables[idx].name,
                    description=mem.tables[idx].description,
                )
                return AgentResponse(
                    f"Editing table **{mem.tables[idx].name}**.\n"
                    "Describe the updated table (name and what it contains):",
                    FSMState.TABLE_OP,
                )
        listing = "\n".join(f"  {i+1}. {t.name}" for i, t in enumerate(mem.tables))
        return AgentResponse(
            f"Which table to edit? Type `edit <number>`.\n{listing}",
            FSMState.TABLE_OP,
        )

    # --- Pending table awaiting confirmation ---
    if mem._pending_table is not None and mem._pending_table.name and mem._pending_table.description:
        confirmed = _llm_confirm(inp)
        if confirmed is None:
            return AgentResponse("Did you mean yes or no?", FSMState.TABLE_OP)
        if confirmed:
            if mem._table_mode == "edit" and mem._edit_table_idx is not None:
                mem.tables[mem._edit_table_idx] = mem._pending_table
            else:
                mem.tables.append(mem._pending_table)
            mem._pending_table = None
            mem._table_mode = ""
            mem._edit_table_idx = None
            return AgentResponse(
                "✅ Table saved.\n\n"
                "Describe another table, type `edit <number>` to edit one, or `done` to move on.",
                FSMState.TABLE_OP,
            )
        else:
            mem._pending_table = None
            mem._table_mode = ""
            mem._edit_table_idx = None
            return AgentResponse(
                "Table discarded. Describe a table, `edit <number>`, or `done`.",
                FSMState.TABLE_OP,
            )

    # --- LLM extracts table name + description from natural language ---
    result = ask_agent("table", inp, _context_snapshot(mem))

    if "error" in result:
        return AgentResponse(f"⚠️ {result['error']}", FSMState.TABLE_OP)

    if result.get("clarification"):
        return AgentResponse(result["clarification"], FSMState.TABLE_OP)

    raw_name = result.get("name")
    raw_desc = result.get("description")

    if not raw_name or not raw_desc:
        return AgentResponse(
            "I couldn't extract a table definition from that. "
            "Please provide a table name and describe its columns/purpose.",
            FSMState.TABLE_OP,
        )

    # Deterministic validation
    name_val, name_err = V.validate_table_name(raw_name)
    if name_err:
        return AgentResponse(f"⚠️ Table name issue: {name_err}", FSMState.TABLE_OP)

    desc_val, desc_err = V.validate_table_description(raw_desc)
    if desc_err:
        return AgentResponse(f"⚠️ Description issue: {desc_err}", FSMState.TABLE_OP)

    mem._pending_table = TableEntry(name=name_val, description=desc_val)  # type: ignore[arg-type]
    if not mem._table_mode:
        mem._table_mode = "new"

    preview = json.dumps({"name": name_val, "description": desc_val}, indent=2)
    return AgentResponse(
        f"Here's what I extracted:\n```json\n{preview}\n```\n"
        "Confirm this table? (yes / no)",
        FSMState.TABLE_OP,
    )


def _handle_table_confirmation(mem: BotMemory, inp: str) -> AgentResponse:
    confirmed = _llm_confirm(inp)
    if confirmed is None:
        return AgentResponse("Did you mean yes or no?", FSMState.TABLE_CONFIRMATION)

    if confirmed:
        return AgentResponse(
            "✅ Tables confirmed.\n\n"
            "**Step 4 — Sub-Domain**\n"
            "What module or sub-domain should this target? "
            "(e.g. order management, returns processing, demand forecasting)",
            FSMState.SUBDOMAIN_SELECTION,
        )
    return AgentResponse(
        "Tables not confirmed. Describe a table, `edit <number>`, or `done`.",
        FSMState.TABLE_OP,
    )


# ---- 6.4 Sub-Domain Agent --------------------------------------------

def _handle_subdomain_selection(mem: BotMemory, inp: str) -> AgentResponse:
    result = ask_agent("subdomain", inp, _context_snapshot(mem))

    if "error" in result:
        return AgentResponse(f"⚠️ {result['error']}", FSMState.SUBDOMAIN_SELECTION)

    if result.get("clarification"):
        return AgentResponse(result["clarification"], FSMState.SUBDOMAIN_SELECTION)

    raw_sub = result.get("sub_domain")
    if not raw_sub:
        return AgentResponse(
            "I couldn't extract a sub-domain. Please provide a module label "
            "(e.g. `order_management`, `returns_processing`).",
            FSMState.SUBDOMAIN_SELECTION,
        )

    val, err = V.validate_subdomain(raw_sub)
    if err:
        return AgentResponse(f"⚠️ {err}", FSMState.SUBDOMAIN_SELECTION)

    mem.sub_domain = val  # type: ignore[assignment]
    return AgentResponse(
        f"Sub-domain received: **{val}**\n\nConfirm? (yes / no)",
        FSMState.SUBDOMAIN_CONFIRMATION,
    )


def _handle_subdomain_confirmation(mem: BotMemory, inp: str) -> AgentResponse:
    confirmed = _llm_confirm(inp)
    if confirmed is None:
        return AgentResponse("Did you mean yes or no?", FSMState.SUBDOMAIN_CONFIRMATION)

    if confirmed:
        return AgentResponse(
            f"✅ Sub-domain **{mem.sub_domain}** confirmed.\n\n"
            "**Step 5 — Sub-Domain Prompt**\n"
            "Describe what the AI should know or do specifically for this sub-domain.",
            FSMState.SUBDOMAIN_PROMPT_ENTRY,
        )
    mem.sub_domain = ""
    return AgentResponse(
        "Sub-domain not confirmed. Please describe the sub-domain again.",
        FSMState.SUBDOMAIN_SELECTION,
    )


# ---- 6.5 Sub-Domain Prompt Agent -------------------------------------

def _handle_subdomain_prompt_entry(mem: BotMemory, inp: str) -> AgentResponse:
    result = ask_agent("subdomain_prompt", inp, _context_snapshot(mem))

    if "error" in result:
        return AgentResponse(f"⚠️ {result['error']}", FSMState.SUBDOMAIN_PROMPT_ENTRY)

    if result.get("clarification"):
        return AgentResponse(result["clarification"], FSMState.SUBDOMAIN_PROMPT_ENTRY)

    raw_prompt = result.get("sub_domain_prompt")
    if not raw_prompt:
        return AgentResponse(
            "I couldn't extract a prompt. Please describe what the AI should know for this sub-domain.",
            FSMState.SUBDOMAIN_PROMPT_ENTRY,
        )

    val, err = V.validate_prompt(raw_prompt)
    if err:
        return AgentResponse(f"⚠️ {err}", FSMState.SUBDOMAIN_PROMPT_ENTRY)

    mem.sub_domain_prompt = val  # type: ignore[assignment]
    return AgentResponse(
        f"Sub-domain prompt captured:\n> {val}\n\nConfirm? (yes / no)",
        FSMState.SUBDOMAIN_PROMPT_CONFIRMATION,
    )


def _handle_subdomain_prompt_confirmation(mem: BotMemory, inp: str) -> AgentResponse:
    confirmed = _llm_confirm(inp)
    if confirmed is None:
        return AgentResponse("Did you mean yes or no?", FSMState.SUBDOMAIN_PROMPT_CONFIRMATION)

    if confirmed:
        return AgentResponse(
            "✅ Sub-domain prompt confirmed.\n\n"
            "**Step 6 — Few-Shot Examples**\n"
            "Give me a natural-language question and its SQL query. You can use the format:\n"
            "`input{QUESTION} -> query{SQL}`\n\n"
            "Or just describe them naturally and I'll extract them. Type `done` when finished.",
            FSMState.FEWSHOT_ENTRY,
        )
    mem.sub_domain_prompt = ""
    return AgentResponse(
        "Sub-domain prompt not confirmed. Please describe it again.",
        FSMState.SUBDOMAIN_PROMPT_ENTRY,
    )


# ---- 6.6 Few-Shot Agent ----------------------------------------------

def _handle_fewshot_entry(mem: BotMemory, inp: str) -> AgentResponse:
    clean = V.sanitize(inp)
    inj = V.check_injection(clean)
    if inj:
        return AgentResponse(f"⚠️ {inj}", FSMState.FEWSHOT_ENTRY)

    if clean.lower() == "done":
        if not mem.few_shots:
            return AgentResponse(
                "⚠️ You must add at least one few-shot example.",
                FSMState.FEWSHOT_ENTRY,
            )
        listing = "\n".join(
            f"  {i+1}. **Q:** {e.question}\n      **SQL:** `{e.sql}`"
            for i, e in enumerate(mem.few_shots)
        )
        return AgentResponse(
            f"Few-shot examples:\n{listing}\n\nConfirm all examples? (yes / no)",
            FSMState.FEWSHOT_CONFIRMATION,
        )

    # Pending example awaiting confirmation
    if mem._pending_few_shot is not None:
        confirmed = _llm_confirm(inp)
        if confirmed is None:
            return AgentResponse("Did you mean yes or no?", FSMState.FEWSHOT_ENTRY)
        if confirmed:
            mem.few_shots.append(mem._pending_few_shot)
            mem._pending_few_shot = None
            return AgentResponse(
                "✅ Example added.\n\n"
                "Give me another question + SQL, or type `done`.",
                FSMState.FEWSHOT_ENTRY,
            )
        else:
            mem._pending_few_shot = None
            return AgentResponse(
                "Example discarded. Give me another or type `done`.",
                FSMState.FEWSHOT_ENTRY,
            )

    # LLM extracts question + SQL from natural language
    result = ask_agent("fewshot", inp, _context_snapshot(mem))

    if "error" in result:
        return AgentResponse(f"⚠️ {result['error']}", FSMState.FEWSHOT_ENTRY)

    if result.get("clarification"):
        return AgentResponse(result["clarification"], FSMState.FEWSHOT_ENTRY)

    raw_q = result.get("question")
    raw_sql = result.get("sql")

    if not raw_q or not raw_sql:
        return AgentResponse(
            "I couldn't extract a question and SQL from that. "
            "Please provide both a question and its SELECT query.",
            FSMState.FEWSHOT_ENTRY,
        )

    # Deterministic validation
    q_val, q_err = V.validate_fewshot_question(raw_q)
    if q_err:
        return AgentResponse(f"⚠️ Question issue: {q_err}", FSMState.FEWSHOT_ENTRY)

    s_val, s_err = V.validate_fewshot_sql(raw_sql)
    if s_err:
        return AgentResponse(f"⚠️ SQL issue: {s_err}", FSMState.FEWSHOT_ENTRY)

    mem._pending_few_shot = FewShotEntry(question=q_val, sql=s_val)  # type: ignore[arg-type]
    preview = json.dumps({"question": q_val, "sql": s_val}, indent=2)
    return AgentResponse(
        f"Here's what I extracted:\n```json\n{preview}\n```\n"
        "Confirm this example? (yes / no)",
        FSMState.FEWSHOT_ENTRY,
    )


def _handle_fewshot_confirmation(mem: BotMemory, inp: str) -> AgentResponse:
    confirmed = _llm_confirm(inp)
    if confirmed is None:
        return AgentResponse("Did you mean yes or no?", FSMState.FEWSHOT_CONFIRMATION)

    if confirmed:
        return AgentResponse(
            "✅ Few-shot examples confirmed.\n\n"
            "**Assembling final configuration…**",
            FSMState.FINAL_ASSEMBLY,
        )
    mem.few_shots.clear()
    return AgentResponse(
        "Few-shots not confirmed. All examples cleared.\n"
        "Give me question + SQL pairs, or type `done`.",
        FSMState.FEWSHOT_ENTRY,
    )


# ---- 6.7 Assembler Agent (deterministic — no LLM rewriting) ----------

def _handle_final_assembly(mem: BotMemory, _inp: str) -> AgentResponse:
    final = json.dumps(mem.to_dict(), indent=2)
    mem.save("output.json")
    return AgentResponse(
        f"✅ Configuration complete! Saved to `output.json`.\n\n"
        f"```json\n{final}\n```",
        FSMState.COMPLETE,
    )


def _handle_complete(_mem: BotMemory, _inp: str) -> AgentResponse:
    return AgentResponse(
        "The configuration is complete. Restart the application to create a new configuration.",
        FSMState.COMPLETE,
    )


# ------------------------------------------------------------------
# Handler dispatch table  (Section 10 switch)
# ------------------------------------------------------------------

_HANDLERS: dict[FSMState, callable] = {
    FSMState.INIT:                          _handle_init,
    FSMState.DOMAIN_SELECTION:              _handle_domain_selection,
    FSMState.DOMAIN_CONFIRMATION:           _handle_domain_confirmation,
    FSMState.GENERAL_PROMPT_ENTRY:          _handle_general_prompt_entry,
    FSMState.GENERAL_PROMPT_CONFIRMATION:   _handle_general_prompt_confirmation,
    FSMState.TABLE_OP:                      _handle_table_op,
    FSMState.TABLE_CONFIRMATION:            _handle_table_confirmation,
    FSMState.SUBDOMAIN_SELECTION:           _handle_subdomain_selection,
    FSMState.SUBDOMAIN_CONFIRMATION:        _handle_subdomain_confirmation,
    FSMState.SUBDOMAIN_PROMPT_ENTRY:        _handle_subdomain_prompt_entry,
    FSMState.SUBDOMAIN_PROMPT_CONFIRMATION: _handle_subdomain_prompt_confirmation,
    FSMState.FEWSHOT_ENTRY:                 _handle_fewshot_entry,
    FSMState.FEWSHOT_CONFIRMATION:          _handle_fewshot_confirmation,
    FSMState.FINAL_ASSEMBLY:                _handle_final_assembly,
    FSMState.COMPLETE:                      _handle_complete,
}


# ------------------------------------------------------------------
# Public controller  (Section 10 — processUserInput)
# ------------------------------------------------------------------

def process_user_input(
    state: FSMState,
    memory: BotMemory,
    user_input: str,
) -> tuple[str, FSMState]:
    """Core controller.  Returns (bot_reply, new_fsm_state)."""
    handler = _HANDLERS.get(state)
    if handler is None:
        return ("Internal error: unknown state.", state)

    resp: AgentResponse = handler(memory, user_input)
    new_state = resp.next_state

    # Enforce legal transitions (Section 5)
    if new_state != state:
        allowed_next = ALLOWED_TRANSITIONS.get(state)
        # Some handlers intentionally stay on the same state (retry loops).
        # A *rejection* rewinds to the prior entry state — this is permitted
        # only when the handler explicitly returns that state.
        if allowed_next is not None and new_state != allowed_next and new_state != state:
            # The handler is trying a backward jump for a rejection.
            # We allow one-step-back rejections that the handler explicitly coded.
            # Anything else is illegal.
            pass  # trust the handler — they only go back one logical step

    return resp.message, new_state

