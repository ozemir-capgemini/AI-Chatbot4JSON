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
import logging
from bot.state import (
    ALLOWED_TRANSITIONS,
    ALLOWED_REJECTIONS,
    BotMemory,
    FSMState,
    FewShotEntry,
    TableEntry,
)
from bot import validators as V
from bot.validators import (
    get_all_domains, get_all_subdomains, add_custom_domain, add_custom_subdomain,
    get_domain_prompt, set_domain_prompt, get_subdomain_prompt, set_subdomain_prompt,
    validate_table_sql, extract_tables_and_columns,
    get_mock_tables, get_mock_fewshots, update_mock_tables, update_mock_fewshots,
)
from bot.llm import ask_agent
from bot.backlog import record_table_change

log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Step descriptions (shown in tooltips / help panels)
# ------------------------------------------------------------------

STEP_HELP: dict[FSMState, str] = {
    FSMState.DOMAIN_SELECTION: "Pick the business area this bot will help with (e.g. Sales, Finance).",
    FSMState.GENERAL_PROMPT_ENTRY: "This is the main instruction the AI assistant will follow. Think of it as telling the bot what its job is.",
    FSMState.TABLE_OP: "Tables describe the data the bot can query. Each table is like a spreadsheet with columns. Pre-loaded tables are ready to use — just click Done.",
    FSMState.SUBDOMAIN_SELECTION: "A sub-domain narrows the focus (e.g. 'Billing' within Telecom).",
    FSMState.SUBDOMAIN_PROMPT_ENTRY: "An extra instruction that tells the bot what to focus on within this sub-domain.",
    FSMState.FEWSHOT_ENTRY: "Examples teach the bot how to answer questions. Each example pairs a plain-English question with the SQL the bot should produce.",
}


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
    domain_list = ", ".join(f"**{d}**" for d in get_all_domains())
    return AgentResponse(
        "Welcome to DMACO. Let's configure your text-to-SQL bot.\n\n"
        "**Step 1 — Domain**\n"
        f"Please choose a business domain from the following list:\n{domain_list}\n\n"
        "Or type `add <name>` to register a new domain.",
        FSMState.DOMAIN_SELECTION,
    )


# ---- 6.1 Domain Agent ------------------------------------------------

def _handle_domain_selection(mem: BotMemory, inp: str) -> AgentResponse:
    clean = V.sanitize(inp)

    # --- "add <name>" command ---
    if clean.lower().startswith("add "):
        new_name = clean[4:].strip().lower()
        inj = V.check_injection(new_name)
        if inj:
            return AgentResponse(f"⚠️ {inj}", FSMState.DOMAIN_SELECTION)
        err = add_custom_domain(new_name)
        if err: 
            return AgentResponse(f"⚠️ {err}", FSMState.DOMAIN_SELECTION)
        domain_list = ", ".join(f"**{d}**" for d in get_all_domains())
        return AgentResponse(
            f"✅ Domain **{new_name}** added!\n\n"
            f"Available domains:\n{domain_list}\n\n"
            "Please select a domain from the list, or `add <name>` again.",
            FSMState.DOMAIN_SELECTION,
        )

    # LLM interprets user's natural language → structured extraction
    result = ask_agent("domain", inp, _context_snapshot(mem))

    if "error" in result:
        return AgentResponse(f"⚠️ {result['error']}", FSMState.DOMAIN_SELECTION)

    if result.get("clarification"):
        return AgentResponse(result["clarification"], FSMState.DOMAIN_SELECTION)

    raw_domain = result.get("domain")
    if not raw_domain:
        domain_list = ", ".join(f"`{d}`" for d in get_all_domains())
        return AgentResponse(
            "I couldn't identify a valid domain from that. "
            f"Please choose one from the list: {domain_list}, or type `add <name>` to add a new one.",
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
        # Use stored prompt (built-in or previously saved) if available
        stored_prompt = get_domain_prompt(mem.domain)
        if stored_prompt:
            mem._suggested_prompt = stored_prompt
            return AgentResponse(
                f"✅ Domain **{mem.domain}** confirmed.\n\n"
                "**Step 2 — General Prompt**\n"
                f"Here's the saved prompt for the **{mem.domain}** domain:\n\n"
                f"> {stored_prompt}\n\n"
                "Would you like to **keep** this prompt, or **change** it?",
                FSMState.GENERAL_PROMPT_ENTRY,
            )
        # No stored prompt — generate one via LLM
        suggestion = ask_agent("domain_prompt_suggest", mem.domain)
        suggested = suggestion.get("suggested_prompt", "")
        if suggested:
            mem._suggested_prompt = suggested
            return AgentResponse(
                f"✅ Domain **{mem.domain}** confirmed.\n\n"
                "**Step 2 — General Prompt**\n"
                f"Here's a suggested prompt for the **{mem.domain}** domain:\n\n"
                f"> {suggested}\n\n"
                "Would you like to **keep** this prompt, or **change** it?",
                FSMState.GENERAL_PROMPT_ENTRY,
            )
        # Fallback if suggestion fails
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
    # If user wants to keep the suggested prompt
    clean_lower = V.sanitize(inp).lower()
    if clean_lower in ("keep", "keep it", "keep this", "keep this prompt") and mem._suggested_prompt:
        val, err = V.validate_prompt(mem._suggested_prompt)
        if err:
            return AgentResponse(f"⚠️ {err}", FSMState.GENERAL_PROMPT_ENTRY)
        mem.general_prompt = val  # type: ignore[assignment]
        mem._suggested_prompt = ""
        return AgentResponse(
            f"Here's the general prompt I captured:\n> {val}\n\nDo you confirm? (yes / no)",
            FSMState.GENERAL_PROMPT_CONFIRMATION,
        )

    # Also try LLM to interpret "keep" in natural language
    if mem._suggested_prompt:
        keep_check = _llm_confirm(inp)
        if keep_check is True:
            val, err = V.validate_prompt(mem._suggested_prompt)
            if err:
                return AgentResponse(f"⚠️ {err}", FSMState.GENERAL_PROMPT_ENTRY)
            mem.general_prompt = val  # type: ignore[assignment]
            mem._suggested_prompt = ""
            return AgentResponse(
                f"Here's the general prompt I captured:\n> {val}\n\nDo you confirm? (yes / no)",
                FSMState.GENERAL_PROMPT_CONFIRMATION,
            )
        # User chose to change — clear suggestion and process their input as new prompt
        mem._suggested_prompt = ""
        if keep_check is False:
            return AgentResponse(
                "No problem. Please describe what the AI assistant should do within this domain.",
                FSMState.GENERAL_PROMPT_ENTRY,
            )

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
        # Persist the confirmed domain prompt for future use
        set_domain_prompt(mem.domain, mem.general_prompt)

        # Pre-load mock tables for this domain if user has none yet
        if not mem.tables:
            mock_tables = get_mock_tables(mem.domain)
            for mt in mock_tables:
                mem.tables.append(TableEntry(name=mt["name"], description=mt["ddl"]))

        table_msg = (
            "✅ General prompt confirmed.\n\n"
            "**Step 3 — Table Definitions**\n"
        )
        if mem.tables:
            listing = "\n".join(
                f"  {i+1}. **{t.name}**"
                for i, t in enumerate(mem.tables)
            )
            table_msg += (
                f"Existing tables:\n{listing}\n\n"
                "Use the **Add Table** button to create a new table, "
                "**Edit** to modify one, or **Done** to continue."
            )
        else:
            table_msg += (
                "Use the **Add Table** button and enter a `CREATE TABLE` SQL statement "
                "to define your first table."
            )
        return AgentResponse(table_msg, FSMState.TABLE_OP)

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
            return AgentResponse("No tables yet. Use the **Add Table** button to create one.", FSMState.TABLE_OP)
        parts = clean.split()
        if len(parts) == 2 and parts[1].isdigit():
            idx = int(parts[1]) - 1
            if 0 <= idx < len(mem.tables):
                mem._table_mode = "edit"
                mem._edit_table_idx = idx
                mem._pending_table = None
                old = mem.tables[idx]
                return AgentResponse(
                    f"Editing table **{old.name}**.\n\n"
                    f"Current DDL:\n```sql\n{old.description}\n```\n\n"
                    "Enter an `ALTER TABLE` SQL statement to update this table, "
                    "or a new `CREATE TABLE` to replace it entirely:",
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
                old = mem.tables[mem._edit_table_idx]
                record_table_change(
                    "edit", mem._pending_table.name, mem._pending_table.description,
                    previous_name=old.name, previous_ddl=old.description,
                )
                mem.tables[mem._edit_table_idx] = mem._pending_table
            else:
                record_table_change("add", mem._pending_table.name, mem._pending_table.description)
                mem.tables.append(mem._pending_table)
            mem._pending_table = None
            mem._table_mode = ""
            mem._edit_table_idx = None
            return AgentResponse(
                "✅ Table saved.\n\n"
                "Use the **Add Table** button to add another, **Edit** to modify one, or **Done** to move on.",
                FSMState.TABLE_OP,
            )
        else:
            mem._pending_table = None
            mem._table_mode = ""
            mem._edit_table_idx = None
            return AgentResponse(
                "Table discarded. Use **Add Table**, **Edit**, or **Done**.",
                FSMState.TABLE_OP,
            )

    # --- Structured SQL input from UI form (bypass LLM) ---
    _TABLE_SQL_PREFIX = "__table_sql::"
    if inp.startswith(_TABLE_SQL_PREFIX):
        raw_sql = inp[len(_TABLE_SQL_PREFIX):]
        result, err = validate_table_sql(raw_sql)
        if err:
            return AgentResponse(f"⚠️ {err}", FSMState.TABLE_OP)

        name_val = result["name"]  # type: ignore[index]
        sql_val = result["sql"]    # type: ignore[index]

        # Duplicate table name check
        existing_names = [t.name for t in mem.tables]
        dup_err = V.validate_table_name_unique(name_val, existing_names, mem._edit_table_idx)  # type: ignore[arg-type]
        if dup_err:
            return AgentResponse(f"⚠️ {dup_err}", FSMState.TABLE_OP)

        mem._pending_table = TableEntry(name=name_val, description=sql_val)  # type: ignore[arg-type]
        if not mem._table_mode:
            mem._table_mode = "new"

        return AgentResponse(
            f"Table **{name_val}** extracted from SQL:\n```sql\n{sql_val}\n```\n\n"
            "Confirm this table? (yes / no)",
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
            "Please enter a `CREATE TABLE` SQL statement.",
            FSMState.TABLE_OP,
        )

    # Deterministic validation
    name_val, name_err = V.validate_table_name(raw_name)
    if name_err:
        return AgentResponse(f"⚠️ Table name issue: {name_err}", FSMState.TABLE_OP)

    desc_val, desc_err = V.validate_table_description(raw_desc)
    if desc_err:
        return AgentResponse(f"⚠️ Description issue: {desc_err}", FSMState.TABLE_OP)

    # Duplicate table name check
    existing_names = [t.name for t in mem.tables]
    dup_err = V.validate_table_name_unique(name_val, existing_names, mem._edit_table_idx)  # type: ignore[arg-type]
    if dup_err:
        return AgentResponse(f"⚠️ {dup_err}", FSMState.TABLE_OP)

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
        # Persist confirmed tables to mock data for future reuse
        update_mock_tables(mem.domain, [{"name": t.name, "ddl": t.description} for t in mem.tables])

        sub_list = get_all_subdomains(mem.domain)
        sub_display = ", ".join(f"**{s}**" for s in sub_list) if sub_list else "(no predefined sub-domains)"
        return AgentResponse(
            "✅ Tables confirmed.\n\n"
            "**Step 4 — Sub-Domain**\n"
            f"Please choose a sub-domain for **{mem.domain}** from the following list:\n{sub_display}\n\n"
            "Or type `add <name>` to register a new sub-domain.",
            FSMState.SUBDOMAIN_SELECTION,
        )
    return AgentResponse(
        "Tables not confirmed. Describe a table, `edit <number>`, or `done`.",
        FSMState.TABLE_OP,
    )


# ---- 6.4 Sub-Domain Agent --------------------------------------------

def _handle_subdomain_selection(mem: BotMemory, inp: str) -> AgentResponse:
    clean = V.sanitize(inp)

    # --- "add <name>" command ---
    if clean.lower().startswith("add "):
        new_name = clean[4:].strip().lower().replace(" ", "_")
        inj = V.check_injection(new_name)
        if inj:
            return AgentResponse(f"⚠️ {inj}", FSMState.SUBDOMAIN_SELECTION)
        err = add_custom_subdomain(mem.domain, new_name)
        if err:
            return AgentResponse(f"⚠️ {err}", FSMState.SUBDOMAIN_SELECTION)
        sub_list = get_all_subdomains(mem.domain)
        sub_display = ", ".join(f"**{s}**" for s in sub_list)
        return AgentResponse(
            f"✅ Sub-domain **{new_name}** added to **{mem.domain}**!\n\n"
            f"Available sub-domains:\n{sub_display}\n\n"
            "Please select a sub-domain from the list, or `add <name>` again.",
            FSMState.SUBDOMAIN_SELECTION,
        )

    result = ask_agent("subdomain", inp, _context_snapshot(mem))

    if "error" in result:
        return AgentResponse(f"⚠️ {result['error']}", FSMState.SUBDOMAIN_SELECTION)

    if result.get("clarification"):
        return AgentResponse(result["clarification"], FSMState.SUBDOMAIN_SELECTION)

    raw_sub = result.get("sub_domain")
    if not raw_sub:
        sub_list = get_all_subdomains(mem.domain)
        sub_display = ", ".join(f"`{s}`" for s in sub_list)
        return AgentResponse(
            "I couldn't extract a valid sub-domain from that. "
            f"Please choose one from the list: {sub_display}, or type `add <name>` to add a new one.",
            FSMState.SUBDOMAIN_SELECTION,
        )

    val, err = V.validate_subdomain(raw_sub, mem.domain)
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
        # Use stored subdomain prompt if available
        stored_sub_prompt = get_subdomain_prompt(mem.domain, mem.sub_domain)
        if stored_sub_prompt:
            return AgentResponse(
                f"✅ Sub-domain **{mem.sub_domain}** confirmed.\n\n"
                "**Step 5 — Sub-Domain Prompt**\n"
                f"Here's the saved prompt for **{mem.sub_domain}**:\n\n"
                f"> {stored_sub_prompt}\n\n"
                "Would you like to **keep** this prompt, or **change** it?",
                FSMState.SUBDOMAIN_PROMPT_ENTRY,
            )
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
    # Check for keep/change of stored prompt
    clean_lower = V.sanitize(inp).lower()
    if clean_lower in ("keep", "keep it", "keep this", "keep this prompt"):
        stored = get_subdomain_prompt(mem.domain, mem.sub_domain)
        if stored:
            val, err = V.validate_prompt(stored)
            if err:
                return AgentResponse(f"⚠️ {err}", FSMState.SUBDOMAIN_PROMPT_ENTRY)
            mem.sub_domain_prompt = val  # type: ignore[assignment]
            return AgentResponse(
                f"Sub-domain prompt captured:\n> {val}\n\nConfirm? (yes / no)",
                FSMState.SUBDOMAIN_PROMPT_CONFIRMATION,
            )

    # LLM confirm for keep intent
    stored = get_subdomain_prompt(mem.domain, mem.sub_domain)
    if stored:
        keep_check = _llm_confirm(inp)
        if keep_check is True:
            val, err = V.validate_prompt(stored)
            if err:
                return AgentResponse(f"⚠️ {err}", FSMState.SUBDOMAIN_PROMPT_ENTRY)
            mem.sub_domain_prompt = val  # type: ignore[assignment]
            return AgentResponse(
                f"Sub-domain prompt captured:\n> {val}\n\nConfirm? (yes / no)",
                FSMState.SUBDOMAIN_PROMPT_CONFIRMATION,
            )
        if keep_check is False:
            return AgentResponse(
                "No problem. Please describe what the AI should know for this sub-domain.",
                FSMState.SUBDOMAIN_PROMPT_ENTRY,
            )

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
        # Persist the confirmed subdomain prompt for future use
        set_subdomain_prompt(mem.domain, mem.sub_domain, mem.sub_domain_prompt)

        # Pre-load mock few-shot examples for this domain+subdomain if user has none yet
        if not mem.few_shots:
            mock_fs = get_mock_fewshots(mem.domain, mem.sub_domain)
            for mf in mock_fs:
                mem.few_shots.append(FewShotEntry(question=mf["question"], sql=mf["sql"]))

        fewshot_msg = (
            "✅ Sub-domain prompt confirmed.\n\n"
            "**Step 6 — Few-Shot Examples**\n"
        )
        if mem.few_shots:
            listing = "\n".join(
                f"  {i+1}. **Q:** {fs.question}"
                for i, fs in enumerate(mem.few_shots)
            )
            fewshot_msg += (
                f"Pre-loaded examples:\n{listing}\n\n"
                "You can add more, edit existing ones, or type `done` to continue."
            )
        else:
            fewshot_msg += (
                "Give me a natural-language question and its SQL query. You can use the format:\n"
                "`input{QUESTION} -> query{SQL}`\n\n"
                "Or just describe them naturally and I'll extract them. Type `done` when finished."
            )
        return AgentResponse(fewshot_msg, FSMState.FEWSHOT_ENTRY)
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

    # --- Structured input from UI form (bypass LLM) ---
    _FEWSHOT_PREFIX = "__fewshot_structured::"
    if inp.startswith(_FEWSHOT_PREFIX):
        try:
            payload = json.loads(inp[len(_FEWSHOT_PREFIX):])
            raw_q = payload.get("question", "")
            raw_sql = payload.get("sql", "")
        except (json.JSONDecodeError, AttributeError):
            return AgentResponse("⚠️ Invalid structured input.", FSMState.FEWSHOT_ENTRY)

        q_val, q_err = V.validate_fewshot_question(raw_q)
        if q_err:
            return AgentResponse(f"⚠️ Question issue: {q_err}", FSMState.FEWSHOT_ENTRY)
        known = extract_tables_and_columns(mem.tables)
        s_val, s_err = V.validate_fewshot_sql(raw_sql, known_tables=known)
        if s_err:
            return AgentResponse(f"⚠️ SQL issue: {s_err}", FSMState.FEWSHOT_ENTRY)

        mem.few_shots.append(FewShotEntry(question=q_val, sql=s_val))  # type: ignore[arg-type]
        return AgentResponse(
            f"✅ Example added: **Q:** {q_val}\n**SQL:** `{s_val}`\n\n"
            "Add another example or type `done` to continue.",
            FSMState.FEWSHOT_ENTRY,
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

    known = extract_tables_and_columns(mem.tables)
    s_val, s_err = V.validate_fewshot_sql(raw_sql, known_tables=known)
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
        # Persist confirmed few-shots to mock data for future reuse
        update_mock_fewshots(
            mem.domain, mem.sub_domain,
            [{"question": fs.question, "sql": fs.sql} for fs in mem.few_shots],
        )
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

    # Input length guard (#2)
    if len(user_input) > V.MAX_INPUT_LENGTH:
        return (
            f"⚠️ Input too long ({len(user_input)} characters). "
            f"Please keep it under {V.MAX_INPUT_LENGTH} characters.",
            state,
        )

    handler = _HANDLERS.get(state)
    if handler is None:
        return ("Internal error: unknown state.", state)

    resp: AgentResponse = handler(memory, user_input)
    new_state = resp.next_state

    # Enforce legal transitions (Section 5)
    if new_state != state:
        forward = ALLOWED_TRANSITIONS.get(state)
        backward = ALLOWED_REJECTIONS.get(state)
        if new_state not in (forward, backward):
            log.warning(
                "Illegal FSM transition %s → %s blocked", state.name, new_state.name
            )
            return (resp.message, state)

    # Retry counter — escalate help after repeated same-state failures
    if new_state == state:
        memory._consecutive_retries += 1
        if memory._consecutive_retries >= 5:
            memory._consecutive_retries = 0
            return (
                resp.message + "\n\n💡 **Tip:** You seem stuck on this step. "
                "Try to follow the format suggested above, or type exactly "
                "one of the options shown.",
                new_state,
            )
    else:
        memory._consecutive_retries = 0

    return resp.message, new_state

