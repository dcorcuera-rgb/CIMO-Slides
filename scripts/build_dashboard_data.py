#!/usr/bin/env python3
"""Build static dashboard data by joining issue records with hierarchy records."""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
ISSUES_PATH = ROOT / "data" / "raw_issues.csv"
HIERARCHY_PATH = ROOT / "data" / "hierarchy.csv"
LEGACY_AP_PATH = ROOT / "data" / "legacy_action_plans.csv"
NEW_AP_PATH = ROOT / "data" / "new_action_plans.csv"
PROGRAM_CONFIG_PATH = ROOT / "data" / "program_config.json"
OUTPUT_PATH = ROOT / "public" / "data" / "dashboard-data.json"

DEFAULT_ISSUE_AP_IDS_COLUMN = "action_plan_ids"
ISSUE_AP_IDS_COLUMN_ALIASES = ("ap_ids", "action_plan_id", "action_plan_ids", "Issue Action Plans")
DEFAULT_AP_ID_COLUMN = "action_plan_id"
AP_ID_COLUMN_ALIASES = ("ap_id", "id", "action_plan_number")
AP_TITLE_COLUMN_ALIASES = ("action_plan_title", "title", "name", "Action Name", "Action Plan Name")
AP_STATUS_COLUMN_ALIASES = ("status",)
AP_DUE_DATE_COLUMN_ALIASES = ("due_date", "target_date", "Due Date", "Action Plan Target Date")

ISSUE_AP_IDS_COLUMN = os.getenv("ISSUE_AP_IDS_COLUMN", DEFAULT_ISSUE_AP_IDS_COLUMN)
AP_ID_COLUMN = os.getenv("AP_ID_COLUMN", DEFAULT_AP_ID_COLUMN)


def clean(value: str) -> str:
    return (value or "").strip()


def email_key(value: str) -> str:
    return clean(value).lower()


def normalize_person_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean(value).lower())


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean(value).lower())


def normalize_text(value: str) -> str:
    return clean(value).lower()


def excel_col_to_index(value: str) -> Optional[int]:
    text = clean(value).upper()
    if not text or not text.isalpha():
        return None
    total = 0
    for ch in text:
        total = total * 26 + (ord(ch) - ord("A") + 1)
    return total - 1


def column_by_excel(headers: Sequence[str], col: str) -> Optional[str]:
    idx = excel_col_to_index(col)
    if idx is None or idx < 0 or idx >= len(headers):
        return None
    return headers[idx]


def resolve_column(headers: Sequence[str], preferred: str, aliases: Sequence[str] = ()) -> Optional[str]:
    preferred_clean = clean(preferred)
    if not preferred_clean:
        return None

    by_normalized = {normalize_header(h): h for h in headers}

    if preferred_clean in headers:
        return preferred_clean

    excel_index = excel_col_to_index(preferred_clean)
    if excel_index is not None and 0 <= excel_index < len(headers):
        return headers[excel_index]

    resolved = by_normalized.get(normalize_header(preferred_clean))
    if resolved:
        return resolved

    for alias in aliases:
        alias_match = by_normalized.get(normalize_header(alias))
        if alias_match:
            return alias_match

    return None


def read_csv(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        headers = [clean(h) for h in (reader.fieldnames or [])]
        return rows, headers


def read_csv_with_header_row(path: Path, header_row_index: int) -> Tuple[List[Dict[str, str]], List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        all_rows = list(csv.reader(handle))
    if header_row_index >= len(all_rows):
        raise ValueError(f"{path} does not have row {header_row_index + 1} for headers.")

    headers = [clean(h) for h in all_rows[header_row_index]]
    records: List[Dict[str, str]] = []
    for row in all_rows[header_row_index + 1 :]:
        if not any(clean(cell) for cell in row):
            continue
        padded = row + ([""] * max(0, len(headers) - len(row)))
        records.append({headers[i]: clean(padded[i]) for i in range(len(headers))})
    return records, headers


def parse_int(value: str) -> int:
    text = clean(value)
    if not text:
        return 0
    digits = re.sub(r"[^\d-]+", "", text)
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0


def load_program_config() -> Dict[str, object]:
    if not PROGRAM_CONFIG_PATH.exists():
        return {}
    try:
        payload = json.loads(PROGRAM_CONFIG_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"{PROGRAM_CONFIG_PATH} contains invalid JSON: {exc}") from exc


def matches_any_rule(record: Dict[str, str], rules: Sequence[Dict[str, object]]) -> List[str]:
    reasons: List[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        field = clean(str(rule.get("field", "")))
        contains_values = rule.get("contains", [])
        label = clean(str(rule.get("label", ""))) or field
        if not field or not isinstance(contains_values, list):
            continue
        haystack = normalize_text(record.get(field, ""))
        if not haystack:
            continue
        for raw_value in contains_values:
            needle = normalize_text(str(raw_value))
            if needle and needle in haystack:
                reasons.append(f"{label}: {raw_value}")
                break
    return reasons


def apply_program_scope(record: Dict[str, str], config: Dict[str, object]) -> Dict[str, object]:
    rules = config.get("population_rules", {}) if isinstance(config.get("population_rules", {}), dict) else {}
    include_rules = rules.get("include_any", []) if isinstance(rules.get("include_any", []), list) else []
    exclude_rules = rules.get("exclude_any", []) if isinstance(rules.get("exclude_any", []), list) else []

    include_reasons = matches_any_rule(record, include_rules)
    exclude_reasons = matches_any_rule(record, exclude_rules)

    if include_rules:
        in_scope = bool(include_reasons) and not exclude_reasons
    else:
        in_scope = not exclude_reasons

    return {
        "in_program_scope": in_scope,
        "program_scope_include_reasons": include_reasons,
        "program_scope_exclude_reasons": exclude_reasons,
    }


def build_cimo_config(program_config: Dict[str, object]) -> Dict[str, object]:
    defaults = {
        "compliance_hierarchy_roots": ["Tyler Hand"],
        "compliance_level_1_risk_domain_keywords": ["Compliance |"],
    }
    configured = program_config.get("cimo_intake_config", {})
    if not isinstance(configured, dict):
        return defaults
    merged = dict(defaults)
    merged.update({k: v for k, v in configured.items() if v is not None})
    return merged


def person_matches_hierarchy_root(
    person_value: str, hierarchy: Dict[str, Dict[str, str]], root_values: Sequence[str]
) -> bool:
    if not root_values:
        return False
    person = lookup_person(person_value, hierarchy)
    if not person:
        return False

    candidate_values = {
        normalize_text(person.get("employee_name", "")),
        normalize_text(person.get("employee_email", "")),
        normalize_text(person.get("manager_name", "")),
        normalize_text(person.get("manager_email", "")),
        normalize_text(person.get("core_plus_1", "")),
        normalize_text(person.get("core_plus_2", "")),
        normalize_text(person.get("core_plus_3", "")),
    }
    normalized_roots = {normalize_text(str(root)) for root in root_values if clean(str(root))}
    return bool(candidate_values & normalized_roots)


def classify_cimo_intake(
    record: Dict[str, str], hierarchy: Dict[str, Dict[str, str]], program_config: Dict[str, object]
) -> Dict[str, object]:
    config = build_cimo_config(program_config)
    roots = config.get("compliance_hierarchy_roots", [])
    risk_domain_keywords = config.get("compliance_level_1_risk_domain_keywords", [])
    owner_in_compliance = isinstance(roots, list) and person_matches_hierarchy_root(
        str(record.get("issue_owner_email", "")) or str(record.get("issue_owner_name", "")),
        hierarchy,
        roots,
    )
    approver_in_compliance = isinstance(roots, list) and person_matches_hierarchy_root(
        str(record.get("approver_email", "")) or str(record.get("approver_name", "")) or str(record.get("action_owner_email", "")),
        hierarchy,
        roots,
    )
    compliance_risk_domain = isinstance(risk_domain_keywords, list) and match_text_keywords(
        str(record.get("risk_domain", "")),
        risk_domain_keywords,
    )
    reasons = []
    if owner_in_compliance:
        reasons.append("Issue owned by Compliance hierarchy")
    if approver_in_compliance:
        reasons.append("Issue approved by Compliance hierarchy")
    if compliance_risk_domain:
        reasons.append("Issue tagged to Compliance level 1 risk domain")
    return {
        "cimo_owner_in_compliance_hierarchy": owner_in_compliance,
        "cimo_approver_in_compliance_hierarchy": approver_in_compliance,
        "cimo_compliance_risk_domain": compliance_risk_domain,
        "in_cimo_intake": bool(reasons),
        "cimo_intake_reasons": reasons,
    }


def canonicalize_issues(rows: List[Dict[str, str]], headers: Sequence[str]) -> List[Dict[str, str]]:
    issue_id_col = resolve_column(headers, "issue_id", ("Issue ID", "ID"))
    issue_title_col = resolve_column(headers, "issue_title", ("Issue Title",))
    status_col = resolve_column(headers, "status", ("Status",))
    severity_col = resolve_column(headers, "severity", ("Issue Severity Rating", "Severity"))
    due_date_col = resolve_column(headers, "due_date", ("Issue Due Date", "Issue Current Due Date"))
    owner_col = column_by_excel(headers, "W") or resolve_column(headers, "issue_owner_email", ("Issue Owner", "Issue Owner Email"))
    approver_col = column_by_excel(headers, "X") or resolve_column(headers, "action_owner_email", ("Issue Approver", "Action Owner", "Approver"))
    ap_link_col = resolve_column(headers, ISSUE_AP_IDS_COLUMN, ISSUE_AP_IDS_COLUMN_ALIASES)
    business_unit_col = resolve_column(headers, "business_unit", ("Business Unit",))
    risk_domain_col = resolve_column(headers, "risk_domain", ("Risk Domain",))
    issue_type_col = resolve_column(headers, "issue_type", ("Issue Type",))
    issue_source_col = resolve_column(headers, "issue_source", ("Issue Source",))
    health_check_col = resolve_column(headers, "issue_health_check", ("Issue Health Check",))
    ap_count_col = resolve_column(headers, "number_of_action_plans", ("Number of Action Plans",))
    unresolved_ap_count_col = resolve_column(
        headers,
        "number_of_unresolved_action_plans",
        ("Number of Unresolved Action Plans",),
    )
    identified_date_col = resolve_column(headers, "date_issue_identified", ("Date Issue Identified",))
    create_date_col = resolve_column(headers, "record_create_date", ("Create Date",))
    rca_completed_col = resolve_column(headers, "date_rca_completed", ("Date RCA Completed",))
    issue_open_date_col = resolve_column(headers, "issue_open_date", ("Issue Open Date",))
    date_closed_col = resolve_column(headers, "date_closed", ("Date Closed",))

    required_resolved = {
        "issue_id": issue_id_col,
        "issue_title": issue_title_col,
        "status": status_col,
        "severity": severity_col,
        "due_date": due_date_col,
        "issue_owner_email": owner_col,
        "action_owner_email": approver_col,
    }
    missing = [key for key, val in required_resolved.items() if not val]
    if missing:
        raise ValueError(
            f"{ISSUES_PATH} missing required logical columns: {', '.join(missing)}. "
            f"Found headers: {', '.join(headers)}"
        )

    normalized: List[Dict[str, str]] = []
    for row in rows:
        normalized.append(
            {
                "issue_id": clean(row.get(issue_id_col or "", "")),
                "issue_title": clean(row.get(issue_title_col or "", "")),
                "status": clean(row.get(status_col or "", "")),
                "severity": clean(row.get(severity_col or "", "")),
                "due_date": clean(row.get(due_date_col or "", "")),
                "issue_owner_email": clean(row.get(owner_col or "", "")),
                "action_owner_email": clean(row.get(approver_col or "", "")),
                "approver_email": clean(row.get(approver_col or "", "")),
                "business_unit": clean(row.get(business_unit_col or "", "")),
                "risk_domain": clean(row.get(risk_domain_col or "", "")),
                "issue_type": clean(row.get(issue_type_col or "", "")),
                "issue_source": clean(row.get(issue_source_col or "", "")),
                "issue_health_check": clean(row.get(health_check_col or "", "")),
                "action_plans_total": clean(row.get(ap_count_col or "", "")),
                "unresolved_action_plans_count": clean(row.get(unresolved_ap_count_col or "", "")),
                "date_issue_identified": clean(row.get(identified_date_col or "", "")),
                "record_create_date": clean(row.get(create_date_col or "", "")),
                "date_rca_completed": clean(row.get(rca_completed_col or "", "")),
                "issue_open_date": clean(row.get(issue_open_date_col or "", "")),
                "date_closed": clean(row.get(date_closed_col or "", "")),
                **({ap_link_col: clean(row.get(ap_link_col, ""))} if ap_link_col else {}),
            }
        )
    return normalized


def canonicalize_hierarchy(rows: List[Dict[str, str]], headers: Sequence[str]) -> List[Dict[str, str]]:
    employee_name_col = column_by_excel(headers, "B") or resolve_column(headers, "employee_name", ("Worker", "Employee Name", "Full Name"))
    manager_col = column_by_excel(headers, "L") or resolve_column(headers, "manager_name", ("Manager",))
    core1_col = column_by_excel(headers, "M") or resolve_column(headers, "core_plus_1", ("Core + 1",))
    core2_col = column_by_excel(headers, "N") or resolve_column(headers, "core_plus_2", ("Core + 2",))
    core3_col = column_by_excel(headers, "O") or resolve_column(headers, "core_plus_3", ("Core + 3",))
    employee_email_col = resolve_column(headers, "employee_email", ("Email - Primary Work", "Work Email"))
    org_level_col = resolve_column(headers, "org_level", ("Worker Type", "Org Level"))
    department_col = resolve_column(headers, "department", ("Business Unit", "Department", "Job Title"))

    if not employee_name_col:
        raise ValueError(
            f"{HIERARCHY_PATH} missing employee identity columns. Found headers: {', '.join(headers)}"
        )
    if not manager_col:
        raise ValueError(f"{HIERARCHY_PATH} missing manager columns. Found headers: {', '.join(headers)}")

    output: List[Dict[str, str]] = []
    for row in rows:
        employee_name = clean(row.get(employee_name_col, ""))
        employee_email = clean(row.get(employee_email_col or "", ""))
        manager_name = clean(row.get(manager_col, ""))
        core1 = clean(row.get(core1_col or "", ""))
        core2 = clean(row.get(core2_col or "", ""))
        core3 = clean(row.get(core3_col or "", ""))
        if not employee_name:
            continue
        output.append(
            {
                "employee_name": employee_name,
                "employee_email": employee_email,
                "manager_name": manager_name,
                "manager_email": "",
                "core_plus_1": core1,
                "core_plus_2": core2,
                "core_plus_3": core3,
                "org_level": clean(row.get(org_level_col or "", "")),
                "department": clean(row.get(department_col or "", "")),
            }
        )

    return output


def make_hierarchy_map(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    table: Dict[str, Dict[str, str]] = {}
    for row in rows:
        email = clean(row.get("employee_email", ""))
        name = clean(row.get("employee_name", ""))
        key_email = email_key(email)
        key_name = normalize_person_key(name)
        if not key_email and not key_name:
            continue
        person = {
            "employee_name": name,
            "employee_email": email,
            "manager_name": clean(row.get("manager_name", "")),
            "manager_email": clean(row.get("manager_email", "")),
            "core_plus_1": clean(row.get("core_plus_1", "")),
            "core_plus_2": clean(row.get("core_plus_2", "")),
            "core_plus_3": clean(row.get("core_plus_3", "")),
            "org_level": clean(row.get("org_level", "")),
            "department": clean(row.get("department", "")),
        }
        if key_email:
            table[f"email:{key_email}"] = person
        if key_name:
            table[f"name:{key_name}"] = person
    return table


def lookup_person(value: str, hierarchy: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    ekey = email_key(value)
    if ekey and f"email:{ekey}" in hierarchy:
        return hierarchy[f"email:{ekey}"]
    nkey = normalize_person_key(value)
    if nkey and f"name:{nkey}" in hierarchy:
        return hierarchy[f"name:{nkey}"]
    return {}


def manager_chain(start_value: str, hierarchy: Dict[str, Dict[str, str]], depth: int = 6) -> str:
    node = lookup_person(start_value, hierarchy)
    chain = [
        clean(node.get("manager_name", "")),
        clean(node.get("core_plus_1", "")),
        clean(node.get("core_plus_2", "")),
        clean(node.get("core_plus_3", "")),
    ]
    return " > ".join([x for x in chain if x])


def hierarchy_levels(start_value: str, hierarchy: Dict[str, Dict[str, str]], levels: int = 4) -> List[Dict[str, str]]:
    node = lookup_person(start_value, hierarchy)
    results: List[Dict[str, str]] = [
        {"name": clean(node.get("manager_name", "")), "email": ""},
        {"name": clean(node.get("core_plus_1", "")), "email": ""},
        {"name": clean(node.get("core_plus_2", "")), "email": ""},
        {"name": clean(node.get("core_plus_3", "")), "email": ""},
    ]
    while len(results) < levels:
        results.append({"name": "", "email": ""})
    return results[:levels]


def enrich_person(prefix: str, person_value: str, hierarchy: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    person = lookup_person(person_value, hierarchy)
    levels = hierarchy_levels(person_value, hierarchy, levels=4)
    return {
        f"{prefix}_name": clean(person.get("employee_name", "")),
        f"{prefix}_email": clean(person.get("employee_email", "")) or clean(person_value),
        f"{prefix}_manager_name": clean(person.get("manager_name", "")),
        f"{prefix}_manager_email": clean(person.get("manager_email", "")),
        f"{prefix}_org_level": clean(person.get("org_level", "")),
        f"{prefix}_department": clean(person.get("department", "")),
        f"{prefix}_manager_chain": manager_chain(person_value, hierarchy),
        f"{prefix}_manager": levels[0]["name"],
        f"{prefix}_manager_email_direct": levels[0]["email"],
        f"{prefix}_core_plus_1": levels[1]["name"],
        f"{prefix}_core_plus_1_email": levels[1]["email"],
        f"{prefix}_core_plus_2": levels[2]["name"],
        f"{prefix}_core_plus_2_email": levels[2]["email"],
        f"{prefix}_core_plus_3": levels[3]["name"],
        f"{prefix}_core_plus_3_email": levels[3]["email"],
    }


def parse_date(value: str) -> Optional[date]:
    text = clean(value)
    if not text:
        return None
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y/%m/%d",
        "%b %d %Y",
        "%B %d %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime(value: str) -> Optional[datetime]:
    text = clean(value)
    if not text:
        return None
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %H:%M",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    parsed = parse_date(text)
    if parsed:
        return datetime.combine(parsed, datetime.min.time())
    return None


def is_closed_status(status: str) -> bool:
    normalized = clean(status).lower()
    closed_terms = {"closed", "resolved", "done", "complete", "completed", "cancelled", "canceled"}
    return normalized in closed_terms


def is_overdue(due_date_text: str, status: str, today: date) -> bool:
    if is_closed_status(status):
        return False
    due = parse_date(due_date_text)
    if not due:
        return False
    return due < today


def parse_id_list(value: str) -> List[str]:
    text = clean(value)
    if not text:
        return []
    ids = re.findall(r"\b\d{5,}\b", text)
    if ids:
        return ids
    return [item for item in (clean(x) for x in re.split(r"[,\n;|]+", text)) if item]


def days_between(start: Optional[datetime], end: Optional[datetime]) -> Optional[int]:
    if not start or not end:
        return None
    return max(0, (end.date() - start.date()).days)


def mean(values: Sequence[int]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def percentile(values: Sequence[int], quantile: float) -> Optional[int]:
    ordered = sorted(values)
    if not ordered:
        return None
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * quantile))))
    return ordered[index]


def safe_ratio(numerator: int, denominator: int) -> Optional[float]:
    if not denominator:
        return None
    return numerator / denominator


def build_kri_config(program_config: Dict[str, object]) -> Dict[str, object]:
    defaults = {
        "self_identified_keywords": ["Self-Identified"],
        "draft_logging_days": 30,
        "rca_completion_days": 45,
        "action_plan_documentation_days": 10,
        "closure_days_by_severity": {
            "high": 180,
            "moderate": 270,
            "low": 365,
        },
    }
    configured = program_config.get("kri_config", {})
    if not isinstance(configured, dict):
        return defaults
    merged = dict(defaults)
    merged.update({k: v for k, v in configured.items() if v is not None})
    return merged


def match_text_keywords(value: str, keywords: Sequence[str]) -> bool:
    haystack = normalize_text(value)
    return any(normalize_text(keyword) in haystack for keyword in keywords if clean(str(keyword)))


def compute_kri(records: List[Dict[str, object]], program_config: Dict[str, object]) -> Dict[str, object]:
    scoped = [record for record in records if record.get("in_cimo_intake")]
    config = build_kri_config(program_config)
    draft_logging_days = config.get("draft_logging_days")
    rca_completion_days = config.get("rca_completion_days")
    action_plan_documentation_days = config.get("action_plan_documentation_days")
    closure_days_by_severity = config.get("closure_days_by_severity", {})
    self_id_keywords = config.get("self_identified_keywords", [])

    draft_creation_values: List[int] = []
    rca_completion_values: List[int] = []
    remediation_values: List[int] = []
    action_plan_open_values: List[int] = []
    adherence = {
        "draft_logging": {"met": 0, "eligible": 0},
        "rca_completion": {"met": 0, "eligible": 0},
        "action_plan_documentation": {"met": 0, "eligible": 0},
        "closure": {"met": 0, "eligible": 0},
    }
    adherence_by_severity: Dict[str, Dict[str, Dict[str, int]]] = {}

    overdue_open = 0
    open_total = 0
    self_identified_count = 0
    intake_count = 0
    owner_hierarchy_count = 0
    approver_hierarchy_count = 0
    compliance_risk_domain_count = 0

    for record in scoped:
        severity = normalize_text(str(record.get("severity", "")))
        closure_threshold = (
            closure_days_by_severity.get(severity) if isinstance(closure_days_by_severity, dict) else None
        )

        identified_at = parse_datetime(str(record.get("date_issue_identified", "")))
        created_at = parse_datetime(str(record.get("record_create_date", "")))
        rca_completed_at = parse_datetime(str(record.get("date_rca_completed", "")))
        closed_at = parse_datetime(str(record.get("date_closed", "")))

        draft_creation_days = days_between(identified_at, created_at)
        rca_completion_metric_days = days_between(created_at, rca_completed_at)
        issue_open_at = parse_datetime(str(record.get("issue_open_date", "")))
        remediation_days = days_between(issue_open_at, closed_at)
        action_plan_open_days = record.get("action_plan_open_days_min")
        if isinstance(action_plan_open_days, int):
            action_plan_open_values.append(action_plan_open_days)

        record["draft_creation_days"] = draft_creation_days
        record["rca_completion_days"] = rca_completion_metric_days
        record["remediation_days"] = remediation_days

        sev_bucket = adherence_by_severity.setdefault(
            severity or "unknown",
            {
                "closure": {"met": 0, "eligible": 0},
            },
        )

        if draft_creation_days is not None and draft_logging_days is not None:
            adherence["draft_logging"]["eligible"] += 1
            if draft_creation_days <= int(draft_logging_days):
                adherence["draft_logging"]["met"] += 1

        if rca_completion_metric_days is not None and rca_completion_days is not None:
            adherence["rca_completion"]["eligible"] += 1
            if rca_completion_metric_days <= int(rca_completion_days):
                adherence["rca_completion"]["met"] += 1

        if isinstance(action_plan_open_days, int) and action_plan_documentation_days is not None:
            adherence["action_plan_documentation"]["eligible"] += 1
            if action_plan_open_days <= int(action_plan_documentation_days):
                adherence["action_plan_documentation"]["met"] += 1

        if remediation_days is not None and closure_threshold is not None:
            adherence["closure"]["eligible"] += 1
            sev_bucket["closure"]["eligible"] += 1
            if remediation_days <= int(closure_threshold):
                adherence["closure"]["met"] += 1
                sev_bucket["closure"]["met"] += 1

        if draft_creation_days is not None:
            draft_creation_values.append(draft_creation_days)
        if rca_completion_metric_days is not None:
            rca_completion_values.append(rca_completion_metric_days)
        if remediation_days is not None:
            remediation_values.append(remediation_days)

        if not is_closed_status(str(record.get("status", ""))):
            open_total += 1
            if bool(record.get("is_overdue")):
                overdue_open += 1

        if isinstance(self_id_keywords, list) and match_text_keywords(str(record.get("issue_source", "")), self_id_keywords):
            self_identified_count += 1

        if bool(record.get("cimo_owner_in_compliance_hierarchy")):
            owner_hierarchy_count += 1
        if bool(record.get("cimo_approver_in_compliance_hierarchy")):
            approver_hierarchy_count += 1
        if bool(record.get("cimo_compliance_risk_domain")):
            compliance_risk_domain_count += 1
        if bool(record.get("in_cimo_intake")):
            intake_count += 1

    def adherence_payload(metric: str) -> Dict[str, object]:
        met = adherence[metric]["met"]
        eligible = adherence[metric]["eligible"]
        return {"met": met, "eligible": eligible, "rate": safe_ratio(met, eligible)}

    by_severity_payload: Dict[str, object] = {}
    for severity, metrics in adherence_by_severity.items():
        by_severity_payload[severity] = {
            metric: {
                "met": values["met"],
                "eligible": values["eligible"],
                "rate": safe_ratio(values["met"], values["eligible"]),
            }
            for metric, values in metrics.items()
        }

    return {
        "issue_inventory_tracking_and_trends": {
            "scope_size": len(scoped),
            "scope_label": "CIMO intake scoped issues",
            "time_to_draft_logging_days": {
                "average": mean(draft_creation_values),
                "median": percentile(draft_creation_values, 0.5),
                "p90": percentile(draft_creation_values, 0.9),
                "sla_days": draft_logging_days,
                "sla_adherence": adherence_payload("draft_logging"),
            },
            "time_to_rca_completion_days": {
                "average": mean(rca_completion_values),
                "median": percentile(rca_completion_values, 0.5),
                "p90": percentile(rca_completion_values, 0.9),
                "sla_days": rca_completion_days,
                "sla_adherence": adherence_payload("rca_completion"),
            },
            "time_to_action_plan_open_days": {
                "average": mean(action_plan_open_values),
                "median": percentile(action_plan_open_values, 0.5),
                "p90": percentile(action_plan_open_values, 0.9),
                "available_count": len(action_plan_open_values),
                "sla_days": action_plan_documentation_days,
                "sla_adherence": adherence_payload("action_plan_documentation"),
            },
            "time_to_issue_closure_days": {
                "average": mean(remediation_values),
                "median": percentile(remediation_values, 0.5),
                "p90": percentile(remediation_values, 0.9),
                "sla_adherence": adherence_payload("closure"),
            },
            "closure_sla_by_severity": by_severity_payload,
        },
        "compliance_issues_overdue": {
            "open_compliance_issues": open_total,
            "open_compliance_issues_overdue": overdue_open,
            "percent_overdue": safe_ratio(overdue_open, open_total),
        },
        "self_identified_vs_overall": {
            "self_identified_issues": self_identified_count,
            "overall_issues": len(scoped),
            "percent_self_identified": safe_ratio(self_identified_count, len(scoped)),
        },
        "cimo_intake_detection": {
            "configured": True,
            "detected_issues": intake_count,
            "overall_issues": len(records),
            "detection_rate": safe_ratio(intake_count, len(records)),
            "owner_in_compliance_hierarchy": owner_hierarchy_count,
            "approver_in_compliance_hierarchy": approver_hierarchy_count,
            "compliance_level_1_risk_domain": compliance_risk_domain_count,
        },
    }


def build_ap_index(ap_rows: List[Dict[str, str]], ap_headers: Sequence[str], source_name: str) -> Dict[str, Dict[str, str]]:
    ap_id_col = resolve_column(ap_headers, AP_ID_COLUMN, AP_ID_COLUMN_ALIASES)
    if not ap_id_col:
        raise ValueError(
            f"{source_name} is missing an action plan ID column. "
            f"Tried: {AP_ID_COLUMN}, {', '.join(AP_ID_COLUMN_ALIASES)}"
        )
    ap_title_col = resolve_column(ap_headers, "action_plan_title", AP_TITLE_COLUMN_ALIASES) or ""
    ap_status_col = resolve_column(ap_headers, "status", AP_STATUS_COLUMN_ALIASES) or ""
    ap_due_col = resolve_column(ap_headers, "due_date", AP_DUE_DATE_COLUMN_ALIASES) or ""
    ap_create_col = resolve_column(ap_headers, "create_date", ("Create Date", "Original Created Date")) or ""
    if source_name == "legacy":
        ap_owner_col = column_by_excel(ap_headers, "O")
        ap_approver_col = column_by_excel(ap_headers, "P")
    elif source_name == "new":
        ap_owner_col = column_by_excel(ap_headers, "M")
        ap_approver_col = column_by_excel(ap_headers, "N")
    else:
        ap_owner_col = resolve_column(ap_headers, "action_plan_owner", ("Action Plan Owner", "Owner"))
        ap_approver_col = resolve_column(ap_headers, "action_plan_approver", ("Action Plan Approver", "Approver"))

    index: Dict[str, Dict[str, str]] = {}
    for row in ap_rows:
        ap_id = clean(row.get(ap_id_col, ""))
        if not ap_id:
            continue
        index[ap_id] = {
            "source": source_name,
            "action_plan_id": ap_id,
            "title": clean(row.get(ap_title_col, "")) if ap_title_col else "",
            "status": clean(row.get(ap_status_col, "")) if ap_status_col else "",
            "due_date": clean(row.get(ap_due_col, "")) if ap_due_col else "",
            "create_date": clean(row.get(ap_create_col, "")) if ap_create_col else "",
            "action_plan_owner": clean(row.get(ap_owner_col or "", "")),
            "action_plan_approver": clean(row.get(ap_approver_col or "", "")),
        }
    return index


def build_dataset(
    issues: List[Dict[str, str]],
    issue_headers: Sequence[str],
    hierarchy: Dict[str, Dict[str, str]],
    program_config: Optional[Dict[str, object]] = None,
    legacy_aps: Optional[Dict[str, Dict[str, str]]] = None,
    new_aps: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, object]:
    records = []
    today = datetime.now(timezone.utc).date()
    overdue_issues_count = 0
    scoped_overdue_issues_count = 0
    issue_ap_ids_col = resolve_column(issue_headers, ISSUE_AP_IDS_COLUMN, ISSUE_AP_IDS_COLUMN_ALIASES)
    ap_lookup = {}
    ap_lookup.update(legacy_aps or {})
    ap_lookup.update(new_aps or {})
    program_config = program_config or {}

    for row in issues:
        issue_owner_value = clean(row.get("issue_owner_email", ""))
        action_owner_value = clean(row.get("action_owner_email", ""))
        approver_value = clean(row.get("approver_email", "")) or action_owner_value
        overdue = is_overdue(clean(row.get("due_date", "")), clean(row.get("status", "")), today)
        if overdue:
            overdue_issues_count += 1

        base = {
            "issue_id": clean(row.get("issue_id", "")),
            "issue_title": clean(row.get("issue_title", "")),
            "status": clean(row.get("status", "")),
            "severity": clean(row.get("severity", "")),
            "due_date": clean(row.get("due_date", "")),
            "issue_owner_email": issue_owner_value,
            "action_owner_email": action_owner_value,
            "approver_email": approver_value,
            "is_overdue": overdue,
        }

        linked_ids: List[str] = []
        if issue_ap_ids_col and issue_ap_ids_col in row:
            linked_ids = parse_id_list(row.get(issue_ap_ids_col, ""))
        linked_plans = [ap_lookup[ap_id] for ap_id in linked_ids if ap_id in ap_lookup]
        linked_plans_enriched = []
        for ap in linked_plans:
            plan = dict(ap)
            plan.update(enrich_person("ap_owner", clean(ap.get("action_plan_owner", "")), hierarchy))
            plan.update(enrich_person("ap_approver", clean(ap.get("action_plan_approver", "")), hierarchy))
            linked_plans_enriched.append(plan)
        linked_overdue = [
            ap for ap in linked_plans if is_overdue(ap.get("due_date", ""), ap.get("status", ""), today)
        ]
        open_linked = [ap for ap in linked_plans if not is_closed_status(ap.get("status", ""))]
        issue_open_at = parse_datetime(row.get("issue_open_date", ""))
        ap_create_days = []
        for ap in linked_plans:
            delta = days_between(issue_open_at, parse_datetime(ap.get("create_date", "")))
            if delta is not None:
                ap_create_days.append(delta)
        fallback_total_aps = parse_int(row.get("action_plans_total", ""))
        fallback_unresolved_aps = parse_int(row.get("unresolved_action_plans_count", ""))
        linked_plans_count = len(linked_plans) if linked_plans else fallback_total_aps
        linked_open_count = len(open_linked) if linked_plans else fallback_unresolved_aps
        linked_overdue_count = len(linked_overdue)
        base.update(
            {
                "linked_action_plan_ids": linked_ids,
                "linked_action_plans_count": linked_plans_count,
                "linked_action_plans_open_count": linked_open_count,
                "linked_action_plans_overdue_count": linked_overdue_count,
                "linked_action_plans": linked_plans_enriched,
                "business_unit": clean(row.get("business_unit", "")),
                "risk_domain": clean(row.get("risk_domain", "")),
                "issue_type": clean(row.get("issue_type", "")),
                "issue_source": clean(row.get("issue_source", "")),
                "issue_health_check": clean(row.get("issue_health_check", "")),
                "date_issue_identified": clean(row.get("date_issue_identified", "")),
                "record_create_date": clean(row.get("record_create_date", "")),
                "date_rca_completed": clean(row.get("date_rca_completed", "")),
                "issue_open_date": clean(row.get("issue_open_date", "")),
                "date_closed": clean(row.get("date_closed", "")),
                "action_plan_open_days_min": min(ap_create_days) if ap_create_days else None,
            }
        )

        base.update(enrich_person("issue_owner", issue_owner_value, hierarchy))
        base.update(enrich_person("action_owner", action_owner_value, hierarchy))
        base.update(enrich_person("approver", approver_value, hierarchy))
        base.update(classify_cimo_intake(base, hierarchy, program_config))
        base.update(apply_program_scope(base, program_config))

        if base["in_program_scope"] and overdue:
            scoped_overdue_issues_count += 1

        records.append(base)

    scoped_records = [record for record in records if record.get("in_program_scope")]
    due_soon_count = sum(
        1
        for record in records
        if not is_closed_status(str(record.get("status", "")))
        and (lambda due: bool(due and 0 <= (due - today).days <= 30))(parse_date(str(record.get("due_date", ""))))
    )
    scoped_due_soon_count = sum(
        1
        for record in scoped_records
        if not is_closed_status(str(record.get("status", "")))
        and (lambda due: bool(due and 0 <= (due - today).days <= 30))(parse_date(str(record.get("due_date", ""))))
    )
    open_records = [record for record in records if not is_closed_status(str(record.get("status", "")))]
    scoped_open_records = [record for record in scoped_records if not is_closed_status(str(record.get("status", "")))]
    high_critical_count = sum(
        1 for record in records if normalize_text(str(record.get("severity", ""))) in {"high", "critical"}
    )
    scoped_high_critical_count = sum(
        1 for record in scoped_records if normalize_text(str(record.get("severity", ""))) in {"high", "critical"}
    )
    risk_accepted_count = sum(
        1 for record in records if normalize_text(str(record.get("status", ""))) == "risk accepted"
    )
    scoped_risk_accepted_count = sum(
        1 for record in scoped_records if normalize_text(str(record.get("status", ""))) == "risk accepted"
    )
    unresolved_ap_count = sum(parse_int(str(record.get("linked_action_plans_open_count", 0))) for record in records)
    scoped_unresolved_ap_count = sum(
        parse_int(str(record.get("linked_action_plans_open_count", 0))) for record in scoped_records
    )
    kri = compute_kri(records, program_config)

    return {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "program": {
            "name": clean(str(program_config.get("program_name", ""))) or "Program health dashboard",
            "scope_note": clean(str(program_config.get("scope_note", ""))),
            "updates": program_config.get("updates", []) if isinstance(program_config.get("updates", []), list) else [],
        },
        "metrics": {
            "overdue_issues_count": overdue_issues_count,
            "scoped_overdue_issues_count": scoped_overdue_issues_count,
            "as_of_date": today.isoformat(),
            "summary": {
                "total_issues": len(records),
                "scoped_issues": len(scoped_records),
                "open_issues": len(open_records),
                "scoped_open_issues": len(scoped_open_records),
                "high_critical_issues": high_critical_count,
                "scoped_high_critical_issues": scoped_high_critical_count,
                "risk_accepted_issues": risk_accepted_count,
                "scoped_risk_accepted_issues": scoped_risk_accepted_count,
                "issues_due_within_30_days": due_soon_count,
                "scoped_issues_due_within_30_days": scoped_due_soon_count,
                "unresolved_action_plans": unresolved_ap_count,
                "scoped_unresolved_action_plans": scoped_unresolved_ap_count,
            },
        },
        "kri": kri,
        "records": records,
    }


def main() -> None:
    issues_rows_raw, issue_headers = read_csv(ISSUES_PATH)
    issues_rows = canonicalize_issues(issues_rows_raw, issue_headers)

    hierarchy_rows_raw, hierarchy_headers = read_csv(HIERARCHY_PATH)
    if hierarchy_headers and "All Active Workers" in hierarchy_headers[0]:
        hierarchy_rows_raw, hierarchy_headers = read_csv_with_header_row(HIERARCHY_PATH, 4)
    hierarchy_rows = canonicalize_hierarchy(hierarchy_rows_raw, hierarchy_headers)

    hierarchy = make_hierarchy_map(hierarchy_rows)
    legacy_ap_index: Dict[str, Dict[str, str]] = {}
    new_ap_index: Dict[str, Dict[str, str]] = {}
    program_config = load_program_config()

    if LEGACY_AP_PATH.exists():
        legacy_rows, legacy_headers = read_csv(LEGACY_AP_PATH)
        legacy_ap_index = build_ap_index(legacy_rows, legacy_headers, "legacy")
    if NEW_AP_PATH.exists():
        new_rows, new_headers = read_csv(NEW_AP_PATH)
        new_ap_index = build_ap_index(new_rows, new_headers, "new")
    dataset = build_dataset(
        issues_rows,
        issue_headers,
        hierarchy,
        program_config=program_config,
        legacy_aps=legacy_ap_index,
        new_aps=new_ap_index,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(dataset, indent=2), encoding="utf-8")
    print(f"Wrote {len(dataset['records'])} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
