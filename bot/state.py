"""Data model that accumulates across all steps and exports to JSON."""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
import json
from pathlib import Path


@dataclass
class TableInfo:
    name: str = ""
    ddl: str = ""
    context: str = ""
    description: str = ""


@dataclass
class FewShotExample:
    input: str = ""
    query: str = ""


@dataclass
class BotState:
    """Central state that every step reads from / writes to."""

    domain: str = ""                            # Step 1
    general_prompt: str = ""                    # Step 2
    tables: list[TableInfo] = field(default_factory=list)  # Step 3
    sub_domain: str = ""                        # Step 4
    sub_domain_prompt: str = ""                 # Step 5
    few_shot_examples: list[FewShotExample] = field(default_factory=list)  # Step 6

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path = "output.json") -> Path:
        p = Path(path)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | Path = "output.json") -> "BotState":
        p = Path(path)
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        state = cls(
            domain=data.get("domain", ""),
            general_prompt=data.get("general_prompt", ""),
            sub_domain=data.get("sub_domain", ""),
            sub_domain_prompt=data.get("sub_domain_prompt", ""),
        )
        for t in data.get("tables", []):
            state.tables.append(TableInfo(**t))
        for ex in data.get("few_shot_examples", []):
            state.few_shot_examples.append(FewShotExample(**ex))
        return state
