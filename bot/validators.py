"""Input validation & sanitisation — Sections 4 and 7 of the DMACO spec."""

from __future__ import annotations

import re

# ------------------------------------------------------------------
# 4.1  Forbidden injection patterns
# ------------------------------------------------------------------

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+)?previous\s+instructions?",
        r"reveal\s+(your\s+)?prompt",
        r"show\s+(me\s+)?(the\s+)?architecture",
        r"jailbreak",
        r"\bDAN\b",
        r"unrestricted\s+mode",
        r"override\s+(the\s+)?model",
        r"act\s+as\s+a?\s*system\s+prompt",
    )
]

# ------------------------------------------------------------------
# 4.3 / 7.3  SQL keywords & validation
# ------------------------------------------------------------------

_SQL_MUTATION_KW = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|REPLACE|EXEC|EXECUTE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

_SQL_COMMENT = re.compile(r"--|#|/\*|\*/")

_SQL_SEMICOLON = re.compile(r";")

# ------------------------------------------------------------------
# 7.2  Table-name regex
# ------------------------------------------------------------------

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_SQL_RESERVED = {
    "select", "from", "where", "insert", "update", "delete", "drop",
    "alter", "create", "table", "index", "grant", "revoke", "truncate",
    "merge", "replace", "exec", "execute", "union", "join", "order",
    "group", "having", "limit", "offset", "into", "values", "set",
}


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def sanitize(text: str) -> str:
    """Section 4.5 — strip newlines, markdown code fences, leading/trailing whitespace."""
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    text = re.sub(r"```[a-zA-Z]*\s*", "", text)   # opening code fence
    text = text.replace("```", "")                  # closing code fence
    return text.strip()


def check_injection(text: str) -> str | None:
    """Return an error message if *text* matches a forbidden pattern, else None."""
    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            return "That input is not allowed. Please provide a valid response for the current step."
    return None


def validate_domain(raw: str) -> tuple[str | None, str | None]:
    """Return (cleaned_value, error).  One of them is always None."""
    val = sanitize(raw).lower()
    if not val:
        return None, "Domain cannot be empty."
    if " " in val:
        return None, "Domain must be a single word (no spaces)."
    if val in _SQL_RESERVED:
        return None, f"'{val}' is a reserved SQL keyword and cannot be used as a domain."
    err = check_injection(val)
    if err:
        return None, err
    return val, None


def validate_prompt(raw: str) -> tuple[str | None, str | None]:
    """Validate a general or sub-domain prompt."""
    val = sanitize(raw)
    if not val:
        return None, "Prompt cannot be empty."
    err = check_injection(val)
    if err:
        return None, err
    return val, None


def validate_table_name(raw: str) -> tuple[str | None, str | None]:
    """Section 7.2 — table names must match ^[A-Za-z_][A-Za-z0-9_]*$."""
    val = sanitize(raw)
    if not _TABLE_NAME_RE.match(val):
        return None, "Table name must start with a letter or underscore and contain only letters, digits, and underscores."
    if val.lower() in _SQL_RESERVED:
        return None, f"'{val}' is a reserved SQL keyword and cannot be used as a table name."
    err = check_injection(val)
    if err:
        return None, err
    return val, None


def validate_table_description(raw: str) -> tuple[str | None, str | None]:
    """Table description — safe text, no executable SQL."""
    val = sanitize(raw)
    if not val:
        return None, "Table description cannot be empty."
    err = check_injection(val)
    if err:
        return None, err
    return val, None


def validate_fewshot_question(raw: str) -> tuple[str | None, str | None]:
    val = sanitize(raw)
    if not val:
        return None, "Question cannot be empty."
    err = check_injection(val)
    if err:
        return None, err
    return val, None


def validate_fewshot_sql(raw: str) -> tuple[str | None, str | None]:
    """Section 7.3 — strict SQL validation for few-shot queries."""
    val = sanitize(raw)
    if not val:
        return None, "SQL query cannot be empty."

    # Must start with SELECT
    if not val.upper().lstrip().startswith("SELECT"):
        return None, "SQL must begin with SELECT."

    # No semicolons
    if _SQL_SEMICOLON.search(val):
        return None, "SQL must not contain semicolons."

    # No comments
    if _SQL_COMMENT.search(val):
        return None, "SQL must not contain comments (-- , # , /* */)."

    # No mutation keywords
    m = _SQL_MUTATION_KW.search(val)
    if m:
        return None, f"SQL must not contain '{m.group()}'. Only SELECT queries are allowed."

    err = check_injection(val)
    if err:
        return None, err

    return val, None


def validate_subdomain(raw: str) -> tuple[str | None, str | None]:
    """Same rules as domain (Section 6.4)."""
    val = sanitize(raw).lower().replace(" ", "_")
    if not val:
        return None, "Sub-domain cannot be empty."
    if not _TABLE_NAME_RE.match(val):
        return None, "Sub-domain must contain only letters, digits, and underscores."
    if val in _SQL_RESERVED:
        return None, f"'{val}' is a reserved SQL keyword."
    err = check_injection(val)
    if err:
        return None, err
    return val, None
