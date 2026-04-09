"""Backlog system — tracks table operations (add / edit / delete).

Two linked tables persisted to ``backlog.json``:

* **summary** — ``id``, ``date``, ``summary``
* **details** — ``id`` (FK → summary), plus full change details
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_BACKLOG_PATH = Path(os.getenv("BACKLOG_PATH", Path(__file__).resolve().parent.parent / "backlog.json"))


def _load() -> dict[str, list[dict[str, Any]]]:
    if _BACKLOG_PATH.exists():
        try:
            data = json.loads(_BACKLOG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "summary" in data and "details" in data:
                return data
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load backlog: %s", exc)
    return {"summary": [], "details": []}


def _save(data: dict[str, list[dict[str, Any]]]) -> None:
    tmp = _BACKLOG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(_BACKLOG_PATH)


def record_table_change(
    action: str,
    table_name: str,
    ddl: str,
    *,
    previous_name: str | None = None,
    previous_ddl: str | None = None,
) -> str:
    """Log a table add / edit / delete and return the generated change id."""
    change_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if action == "add":
        summary_text = f"Added table '{table_name}'"
    elif action == "edit":
        summary_text = f"Edited table '{table_name}'"
    elif action == "delete":
        summary_text = f"Deleted table '{table_name}'"
    else:
        summary_text = f"{action} table '{table_name}'"

    data = _load()

    data["summary"].append({
        "id": change_id,
        "date": now,
        "summary": summary_text,
    })

    detail: dict[str, Any] = {
        "id": change_id,
        "action": action,
        "table_name": table_name,
        "ddl": ddl,
        "date": now,
    }
    if previous_name is not None:
        detail["previous_name"] = previous_name
    if previous_ddl is not None:
        detail["previous_ddl"] = previous_ddl

    data["details"].append(detail)

    _save(data)
    log.info("Backlog: %s (id=%s)", summary_text, change_id)
    return change_id


def get_backlog() -> dict[str, list[dict[str, Any]]]:
    """Return the full backlog (both tables)."""
    return _load()
