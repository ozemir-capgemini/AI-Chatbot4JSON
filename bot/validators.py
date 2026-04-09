"""Input validation & sanitisation — Sections 4 and 7 of the DMACO spec."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

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
        r"disregard\s+(all\s+)?(prior|previous)",
        r"forget\s+(all\s+)?(your\s+)?instructions?",
        r"pretend\s+you\s+are",
        r"you\s+are\s+now\b",
        r"new\s+instructions?\s+override",
    )
]

# ------------------------------------------------------------------
# 4.3 / 7.3  SQL keywords & validation
# ------------------------------------------------------------------

_SQL_MUTATION_KW = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|REPLACE|EXEC|EXECUTE|GRANT|REVOKE|INTO)\b",
    re.IGNORECASE,
)

_SQL_COMMENT = re.compile(r"--|#|/\*|\*/")

_SQL_SEMICOLON = re.compile(r";")

# Multi-word SQL commands checked in table descriptions (avoids false positives
# from single keywords like "create" or "update" in natural language).
_DESC_EXECUTABLE_SQL = re.compile(
    r"\b(CREATE|DROP|ALTER|TRUNCATE)\s+TABLE\b|\bINSERT\s+INTO\b|\bDELETE\s+FROM\b",
    re.IGNORECASE,
)

MAX_INPUT_LENGTH = 2000  # characters — guards against billing spikes / memory abuse

# ------------------------------------------------------------------
# Predefined domain & sub-domain lists
# ------------------------------------------------------------------

ALLOWED_DOMAINS: list[str] = [
    "sales", "finance", "healthcare", "telecom",
]

ALLOWED_SUBDOMAINS: dict[str, list[str]] = {
    "sales":      ["order_management", "lead_tracking", "revenue_analysis", "customer_segmentation"],
    "finance":    ["accounts_payable", "accounts_receivable", "budgeting", "tax_reporting"],
    "healthcare": ["patient_records", "appointment_scheduling", "billing", "clinical_analytics"],
    "telecom":    ["network_monitoring", "subscriber_management", "billing", "service_provisioning"],
}

# ------------------------------------------------------------------
# Custom domain / sub-domain persistence
# ------------------------------------------------------------------

_CUSTOM_FILE = Path("custom_domains.json")
_log = logging.getLogger(__name__)


def _load_custom() -> dict:
    """Load custom domains/subdomains/prompts from disk."""
    if not _CUSTOM_FILE.exists():
        return {"domains": [], "subdomains": {}, "domain_prompts": {}, "subdomain_prompts": {}}
    try:
        data = json.loads(_CUSTOM_FILE.read_text(encoding="utf-8"))
        if not isinstance(data.get("domains"), list):
            data["domains"] = []
        if not isinstance(data.get("subdomains"), dict):
            data["subdomains"] = {}
        if not isinstance(data.get("domain_prompts"), dict):
            data["domain_prompts"] = {}
        if not isinstance(data.get("subdomain_prompts"), dict):
            data["subdomain_prompts"] = {}
        return data
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning("Failed to read %s: %s", _CUSTOM_FILE, exc)
        return {"domains": [], "subdomains": {}, "domain_prompts": {}, "subdomain_prompts": {}}


def _save_custom(data: dict) -> None:
    """Persist custom domains/subdomains to disk."""
    _CUSTOM_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def add_custom_domain(name: str) -> str | None:
    """Register a new custom domain. Returns an error message or None on success."""
    name = name.lower().strip()
    if not _TABLE_NAME_RE.match(name):
        return "Domain name must contain only letters, digits, and underscores, starting with a letter or underscore."
    if name in _SQL_RESERVED:
        return f"'{name}' is a reserved SQL keyword and cannot be used as a domain name."
    if name in get_all_domains():
        return f"'{name}' already exists as a domain."
    data = _load_custom()
    data["domains"].append(name)
    _save_custom(data)
    return None


def add_custom_subdomain(domain: str, name: str) -> str | None:
    """Register a new custom subdomain under *domain*. Returns error or None."""
    name = name.lower().strip().replace(" ", "_")
    if not _TABLE_NAME_RE.match(name):
        return "Sub-domain name must contain only letters, digits, and underscores."
    if name in get_all_subdomains(domain):
        return f"'{name}' already exists as a sub-domain under **{domain}**."
    data = _load_custom()
    data.setdefault("subdomains", {}).setdefault(domain, []).append(name)
    _save_custom(data)
    return None


def get_all_domains() -> list[str]:
    """Return predefined + custom domains (deduplicated, order preserved)."""
    custom = _load_custom().get("domains", [])
    seen: set[str] = set()
    merged: list[str] = []
    for d in ALLOWED_DOMAINS + custom:
        if d not in seen:
            seen.add(d)
            merged.append(d)
    return merged


def get_all_subdomains(domain: str) -> list[str]:
    """Return predefined + custom subdomains for *domain* (deduplicated)."""
    predefined = ALLOWED_SUBDOMAINS.get(domain, [])
    custom = _load_custom().get("subdomains", {}).get(domain, [])
    seen: set[str] = set()
    merged: list[str] = []
    for s in predefined + custom:
        if s not in seen:
            seen.add(s)
            merged.append(s)
    return merged


def get_allowed_subdomains(domain: str) -> list[str]:
    """Return the full subdomain list for the given domain (predefined + custom)."""
    return get_all_subdomains(domain)


# ------------------------------------------------------------------
# Prompt persistence  (domain + subdomain prompts)
# ------------------------------------------------------------------

# Predefined prompts for built-in domains
_BUILTIN_DOMAIN_PROMPTS: dict[str, str] = {
    "sales": "You are an AI assistant specialising in sales analytics. Help users query order data, revenue metrics, customer segments, and sales pipeline information.",
    "finance": "You are an AI assistant for financial data. Help users query accounts payable/receivable, budgets, tax records, and financial reporting tables.",
    "healthcare": "You are an AI assistant for healthcare data. Help users query patient records, appointments, billing, and clinical analytics tables.",
    "telecom": "You are an AI assistant for telecom analytics. Help users query network monitoring, subscriber data, billing records, and service provisioning tables.",
}

# Predefined prompts for built-in subdomains
_BUILTIN_SUBDOMAIN_PROMPTS: dict[str, dict[str, str]] = {
    "sales": {
        "order_management": "Focus on order lifecycle queries: order creation, status tracking, fulfillment, cancellations, and order history analysis.",
        "lead_tracking": "Focus on sales lead queries: lead sources, conversion rates, pipeline stages, and follow-up scheduling.",
        "revenue_analysis": "Focus on revenue queries: monthly/quarterly revenue, growth trends, revenue by product/region, and forecasting.",
        "customer_segmentation": "Focus on customer segment queries: demographics, purchase behaviour, lifetime value, and cohort analysis.",
    },
    "finance": {
        "accounts_payable": "Focus on AP queries: outstanding invoices, payment schedules, vendor balances, and aging reports.",
        "accounts_receivable": "Focus on AR queries: customer invoices, payment collection, overdue accounts, and cash flow.",
        "budgeting": "Focus on budget queries: budget vs actuals, departmental allocations, variance analysis, and forecasts.",
        "tax_reporting": "Focus on tax queries: tax liabilities, filing status, deductions, and compliance records.",
    },
    "healthcare": {
        "patient_records": "Focus on patient data queries: demographics, medical history, diagnoses, and treatment plans.",
        "appointment_scheduling": "Focus on appointment queries: availability, bookings, cancellations, and provider schedules.",
        "billing": "Focus on billing queries: charges, insurance claims, payment status, and billing codes.",
        "clinical_analytics": "Focus on clinical queries: outcomes analysis, readmission rates, treatment effectiveness, and population health.",
    },
    "telecom": {
        "network_monitoring": "Focus on network queries: uptime, latency, throughput, outages, and capacity utilisation.",
        "subscriber_management": "Focus on subscriber queries: activations, churn rates, plan details, and usage patterns.",
        "billing": "Focus on billing queries: invoice generation, payment history, rate plans, and dispute resolution.",
        "service_provisioning": "Focus on provisioning queries: service activation, configuration, SLA compliance, and service requests.",
    },
}


def get_domain_prompt(domain: str) -> str:
    """Return the stored prompt for a domain (built-in or custom), or empty string."""
    # Check built-in first
    if domain in _BUILTIN_DOMAIN_PROMPTS:
        # Custom override takes precedence
        custom = _load_custom().get("domain_prompts", {}).get(domain)
        return custom if custom else _BUILTIN_DOMAIN_PROMPTS[domain]
    # Custom-only domain
    return _load_custom().get("domain_prompts", {}).get(domain, "")


def set_domain_prompt(domain: str, prompt: str) -> None:
    """Store a custom domain prompt (overrides built-in if any)."""
    data = _load_custom()
    data.setdefault("domain_prompts", {})[domain] = prompt
    _save_custom(data)


def get_subdomain_prompt(domain: str, subdomain: str) -> str:
    """Return the stored prompt for a subdomain (built-in or custom), or empty string."""
    if domain in _BUILTIN_SUBDOMAIN_PROMPTS and subdomain in _BUILTIN_SUBDOMAIN_PROMPTS[domain]:
        custom = _load_custom().get("subdomain_prompts", {}).get(domain, {}).get(subdomain)
        return custom if custom else _BUILTIN_SUBDOMAIN_PROMPTS[domain][subdomain]
    return _load_custom().get("subdomain_prompts", {}).get(domain, {}).get(subdomain, "")


def set_subdomain_prompt(domain: str, subdomain: str, prompt: str) -> None:
    """Store a custom subdomain prompt."""
    data = _load_custom()
    data.setdefault("subdomain_prompts", {}).setdefault(domain, {})[subdomain] = prompt
    _save_custom(data)

# ------------------------------------------------------------------
# Mock data persistence  (tables + few-shot examples per domain)
# ------------------------------------------------------------------

_MOCK_FILE = Path(__file__).resolve().parent.parent / "mock_data.json"


def _load_mock() -> dict:
    """Load the mock_data.json file."""
    if not _MOCK_FILE.exists():
        return {}
    try:
        data = json.loads(_MOCK_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning("Failed to read %s: %s", _MOCK_FILE, exc)
        return {}


def _save_mock(data: dict) -> None:
    """Persist mock data to disk."""
    _MOCK_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_mock_tables(domain: str) -> list[dict]:
    """Return mock table entries for a domain.

    Each entry has keys: name, ddl.
    """
    return _load_mock().get(domain, {}).get("tables", [])


def get_mock_fewshots(domain: str, subdomain: str) -> list[dict]:
    """Return mock few-shot examples for a domain+subdomain.

    Each entry has keys: question, sql.
    """
    return (
        _load_mock()
        .get(domain, {})
        .get("subdomains", {})
        .get(subdomain, {})
        .get("few_shots", [])
    )


def update_mock_tables(domain: str, tables: list[dict]) -> None:
    """Overwrite mock tables for a domain."""
    data = _load_mock()
    data.setdefault(domain, {})["tables"] = tables
    _save_mock(data)


def update_mock_fewshots(domain: str, subdomain: str, few_shots: list[dict]) -> None:
    """Overwrite mock few-shot examples for a domain+subdomain."""
    data = _load_mock()
    data.setdefault(domain, {}).setdefault("subdomains", {}).setdefault(subdomain, {})["few_shots"] = few_shots
    _save_mock(data)

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
    err = check_injection(val)
    if err:
        return None, err
    all_domains = get_all_domains()
    if val not in all_domains:
        options = ", ".join(f"`{d}`" for d in all_domains)
        return None, f"'{val}' is not a recognised domain. Please choose from: {options}, or type `add <name>` to add a new one."
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
    m = _DESC_EXECUTABLE_SQL.search(val)
    if m:
        return None, f"Table description must not contain SQL commands like '{m.group()}'. Use plain language."
    if _SQL_COMMENT.search(val):
        return None, "Table description must not contain SQL comment syntax."
    err = check_injection(val)
    if err:
        return None, err
    return val, None


# ------ CREATE TABLE / ALTER TABLE SQL validation ---------------------

_CREATE_TABLE_RE = re.compile(
    r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\[?[A-Za-z_][A-Za-z0-9_.]*\]?)\s*\(",
    re.IGNORECASE,
)
_ALTER_TABLE_RE = re.compile(
    r"^\s*ALTER\s+TABLE\s+(\[?[A-Za-z_][A-Za-z0-9_.]*\]?)\s+",
    re.IGNORECASE,
)
_DANGEROUS_SQL_KW = re.compile(
    r"\b(DROP\s+TABLE|TRUNCATE|INSERT\s+INTO|DELETE\s+FROM|EXEC|EXECUTE|GRANT|REVOKE|xp_)\b",
    re.IGNORECASE,
)


def validate_table_sql(raw: str) -> tuple[dict | None, str | None]:
    """Validate a CREATE TABLE or ALTER TABLE statement.

    Returns ``({"name": ..., "sql": ...}, None)`` on success, or
    ``(None, error_message)`` on failure.
    """
    val = raw.strip()
    if not val:
        return None, "SQL cannot be empty."
    if len(val) > MAX_INPUT_LENGTH:
        return None, f"SQL too long ({len(val)} chars). Keep it under {MAX_INPUT_LENGTH}."

    # Check for dangerous keywords
    m = _DANGEROUS_SQL_KW.search(val)
    if m:
        return None, f"SQL must not contain '{m.group()}'. Only CREATE TABLE or ALTER TABLE is allowed."

    # No SQL comments
    if _SQL_COMMENT.search(val):
        return None, "SQL must not contain comment syntax (-- , # , /* */)."

    # Try CREATE TABLE first, then ALTER TABLE
    cm = _CREATE_TABLE_RE.match(val)
    am = _ALTER_TABLE_RE.match(val) if not cm else None

    if not cm and not am:
        return None, "SQL must start with CREATE TABLE or ALTER TABLE."

    raw_name = (cm.group(1) if cm else am.group(1)).strip("[]")  # type: ignore[union-attr]

    # Validate extracted table name
    name_val, name_err = validate_table_name(raw_name.split(".")[-1])  # handle schema.table
    if name_err:
        return None, f"Table name issue: {name_err}"

    return {"name": name_val, "sql": val}, None


# ------ Column extraction from CREATE TABLE DDL ----------------------

_COL_LINE_RE = re.compile(
    r"^\s*(\[?[A-Za-z_][A-Za-z0-9_]*\]?)\s+"  # column name
    r"(?:INT|INTEGER|BIGINT|SMALLINT|TINYINT|FLOAT|REAL|DOUBLE|DECIMAL|NUMERIC|"
    r"VARCHAR|NVARCHAR|CHAR|NCHAR|TEXT|NTEXT|DATE|DATETIME|DATETIME2|TIME|"
    r"TIMESTAMP|BIT|BOOLEAN|MONEY|SMALLMONEY|UNIQUEIDENTIFIER|BINARY|VARBINARY|"
    r"IMAGE|XML|JSON|UUID|SERIAL|BIGSERIAL)\b",
    re.IGNORECASE,
)
_CONSTRAINT_KW = re.compile(
    r"^\s*(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|CONSTRAINT|INDEX)\b",
    re.IGNORECASE,
)


def extract_columns_from_ddl(ddl: str) -> list[str]:
    """Extract column names from a CREATE TABLE statement.

    Returns a list of lower-cased column names. Works on the body
    between the first ``(`` and its matching ``)``.
    """
    # Find the body between first ( and last )
    start = ddl.find("(")
    end = ddl.rfind(")")
    if start == -1 or end == -1 or end <= start:
        return []

    body = ddl[start + 1 : end]
    columns: list[str] = []

    for part in body.split(","):
        line = part.strip()
        if not line:
            continue
        # Skip constraint lines
        if _CONSTRAINT_KW.match(line):
            continue
        m = _COL_LINE_RE.match(line)
        if m:
            columns.append(m.group(1).strip("[]").lower())

    return columns


def extract_tables_and_columns(tables: list) -> dict[str, list[str]]:
    """Given a list of TableEntry objects, return {table_name: [col1, col2, ...]}."""
    result: dict[str, list[str]] = {}
    for t in tables:
        cols = extract_columns_from_ddl(t.description)
        result[t.name.lower()] = cols
    return result


def validate_fewshot_question(raw: str) -> tuple[str | None, str | None]:
    val = sanitize(raw)
    if not val:
        return None, "Question cannot be empty."
    err = check_injection(val)
    if err:
        return None, err
    return val, None


def validate_fewshot_sql(
    raw: str,
    known_tables: dict[str, list[str]] | None = None,
) -> tuple[str | None, str | None]:
    """Section 7.3 — strict SQL validation for few-shot queries.

    *known_tables* is an optional ``{table_name: [col1, col2, ...]}``
    dict (all lower-cased).  When provided the query is checked to
    ensure it only references tables and columns that actually exist.
    """
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

    # --- Cross-reference tables & columns against defined schema ------
    if known_tables:
        all_table_names = set(known_tables.keys())
        all_columns: set[str] = set()
        for cols in known_tables.values():
            all_columns.update(cols)

        # Extract table references from FROM / JOIN clauses
        _from_join_re = re.compile(
            r"\b(?:FROM|JOIN)\s+(\[?[A-Za-z_][A-Za-z0-9_]*\]?)",
            re.IGNORECASE,
        )
        referenced_tables = {
            t.strip("[]").lower()
            for t in _from_join_re.findall(val)
        }
        bad_tables = referenced_tables - all_table_names
        if bad_tables:
            available = ", ".join(f"`{t}`" for t in sorted(all_table_names))
            bad = ", ".join(f"`{t}`" for t in sorted(bad_tables))
            return None, (
                f"Unknown table(s) {bad} in SQL. "
                f"Available tables: {available}."
            )

        # Collect columns for referenced tables only
        valid_cols: set[str] = set()
        for tbl in referenced_tables:
            valid_cols.update(known_tables.get(tbl, []))

        # Extract identifiers that look like column references (word.word or
        # standalone identifiers in SELECT / WHERE / GROUP BY / ORDER BY / ON).
        # Use a simple approach: find all identifiers that aren't SQL keywords
        # or table names, and check them against valid columns when columns are
        # known.
        if valid_cols:
            # table.column references
            _tbl_col_re = re.compile(
                r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b"
            )
            for tbl_ref, col_ref in _tbl_col_re.findall(val):
                tbl_lower = tbl_ref.lower()
                col_lower = col_ref.lower()
                if tbl_lower in all_table_names:
                    tbl_cols = known_tables.get(tbl_lower, [])
                    if tbl_cols and col_lower not in tbl_cols:
                        avail = ", ".join(f"`{c}`" for c in tbl_cols)
                        return None, (
                            f"Column `{col_ref}` not found in table `{tbl_ref}`. "
                            f"Available columns: {avail}."
                        )

    return val, None


def validate_subdomain(raw: str, domain: str = "") -> tuple[str | None, str | None]:
    """Validate against the predefined subdomain list for the given domain."""
    val = sanitize(raw).lower().replace(" ", "_")
    if not val:
        return None, "Sub-domain cannot be empty."
    if not _TABLE_NAME_RE.match(val):
        return None, "Sub-domain must contain only letters, digits, and underscores."
    err = check_injection(val)
    if err:
        return None, err
    allowed = get_all_subdomains(domain) if domain else []
    if allowed and val not in allowed:
        options = ", ".join(f"`{s}`" for s in allowed)
        return None, f"'{val}' is not a recognised sub-domain for **{domain}**. Please choose from: {options}, or type `add <name>` to add a new one."
    return val, None


def validate_table_name_unique(
    name: str, existing: list[str], edit_idx: int | None = None
) -> str | None:
    """Return an error message if *name* duplicates an existing table (case-insensitive)."""
    for i, existing_name in enumerate(existing):
        if i == edit_idx:
            continue
        if existing_name.lower() == name.lower():
            return f"A table named '{name}' already exists (table #{i+1}). Please use a different name."
    return None
