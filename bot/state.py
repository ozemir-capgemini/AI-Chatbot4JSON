"""FSM states, data model, and serialisation — matches DMACO spec exactly."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from pathlib import Path


# ------------------------------------------------------------------
# Finite-State Machine — Section 5 of spec
# ------------------------------------------------------------------

class FSMState(IntEnum):
    INIT = 0
    DOMAIN_SELECTION = 1
    DOMAIN_CONFIRMATION = 2
    GENERAL_PROMPT_ENTRY = 3
    GENERAL_PROMPT_CONFIRMATION = 4
    TABLE_OP = 5
    TABLE_CONFIRMATION = 6
    SUBDOMAIN_SELECTION = 7
    SUBDOMAIN_CONFIRMATION = 8
    SUBDOMAIN_PROMPT_ENTRY = 9
    SUBDOMAIN_PROMPT_CONFIRMATION = 10
    FEWSHOT_ENTRY = 11
    FEWSHOT_CONFIRMATION = 12
    FINAL_ASSEMBLY = 13
    COMPLETE = 14


# Only these forward transitions are legal (Section 5)
ALLOWED_TRANSITIONS: dict[FSMState, FSMState] = {
    FSMState.INIT:                          FSMState.DOMAIN_SELECTION,
    FSMState.DOMAIN_SELECTION:              FSMState.DOMAIN_CONFIRMATION,
    FSMState.DOMAIN_CONFIRMATION:           FSMState.GENERAL_PROMPT_ENTRY,
    FSMState.GENERAL_PROMPT_ENTRY:          FSMState.GENERAL_PROMPT_CONFIRMATION,
    FSMState.GENERAL_PROMPT_CONFIRMATION:   FSMState.TABLE_OP,
    FSMState.TABLE_OP:                      FSMState.TABLE_CONFIRMATION,
    FSMState.TABLE_CONFIRMATION:            FSMState.SUBDOMAIN_SELECTION,
    FSMState.SUBDOMAIN_SELECTION:           FSMState.SUBDOMAIN_CONFIRMATION,
    FSMState.SUBDOMAIN_CONFIRMATION:        FSMState.SUBDOMAIN_PROMPT_ENTRY,
    FSMState.SUBDOMAIN_PROMPT_ENTRY:        FSMState.SUBDOMAIN_PROMPT_CONFIRMATION,
    FSMState.SUBDOMAIN_PROMPT_CONFIRMATION: FSMState.FEWSHOT_ENTRY,
    FSMState.FEWSHOT_ENTRY:                 FSMState.FEWSHOT_CONFIRMATION,
    FSMState.FEWSHOT_CONFIRMATION:          FSMState.FINAL_ASSEMBLY,
    FSMState.FINAL_ASSEMBLY:                FSMState.COMPLETE,
}


# ------------------------------------------------------------------
# Data model — Section 8 JSON schema
# ------------------------------------------------------------------

@dataclass
class TableEntry:
    name: str = ""
    description: str = ""


@dataclass
class FewShotEntry:
    question: str = ""
    sql: str = ""


@dataclass
class BotMemory:
    """Accumulates confirmed values only.  Matches the spec's JSON schema."""

    domain: str = ""
    general_prompt: str = ""
    tables: list[TableEntry] = field(default_factory=list)
    sub_domain: str = ""
    sub_domain_prompt: str = ""
    few_shots: list[FewShotEntry] = field(default_factory=list)

    # Transient working data (not serialised into final JSON)
    _pending_table: TableEntry | None = field(default=None, repr=False)
    _pending_few_shot: FewShotEntry | None = field(default=None, repr=False)
    _table_mode: str = field(default="", repr=False)         # "new" | "edit"
    _edit_table_idx: int | None = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """Return the spec-compliant JSON structure (no private fields)."""
        d = asdict(self)
        for k in list(d):
            if k.startswith("_"):
                del d[k]
        return d

    def save(self, path: str | Path = "output.json") -> Path:
        p = Path(path)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p
        return state
