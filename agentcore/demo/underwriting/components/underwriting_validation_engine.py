"""Field-level validation engine.

Deterministic checks: mandatory fields, invalid formats, cross-document
mismatches (application vs census, claims summary vs detailed report), census
date-of-birth consistency and missing documents. Every finding carries the
source evidence and is classified as extraction error, data discrepancy,
missing field or missing document so the agent can decide what to do next.
"""

from __future__ import annotations

import json
import re

from agentcore.custom.custom_node.node import Node
from agentcore.io import DataInput, IntInput, Output
from agentcore.schema.data import Data

MANDATORY = [
    ("company_name", "Company name"),
    ("application_total_employees", "Total employees (application)"),
    ("requested_sum_insured", "Requested sum insured"),
    ("coverage_start_date", "Coverage start date"),
    ("policy_expiry_date", "Current policy expiry"),
    ("claims_total_summary", "Claims amount (summary)"),
    ("current_annual_premium", "Current annual premium"),
]
REQUIRED_DOCS = {"application": "Company application", "census": "Employee census", "claims": "Claims experience", "policy": "Current policy"}


def _inr(value) -> str:
    if value is None:
        return "—"
    try:
        n = int(value)
    except (TypeError, ValueError):
        return str(value)
    s = str(n)
    if len(s) <= 3:
        return f"₹{s}"
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "₹" + ",".join(parts) + "," + tail


class UnderwritingValidationEngine(Node):
    display_name = "3. Field-Level Validation"
    description = (
        "Checks mandatory fields, formats, cross-document consistency and census integrity; produces a validation "
        "report with evidence, completeness/validation scores and the list of material issues."
    )
    icon = "shield-check"
    name = "UnderwritingValidationEngine"

    inputs = [
        DataInput(name="extracted", display_name="Extracted Case", required=True),
        IntInput(
            name="employee_count_tolerance",
            display_name="Employee count tolerance",
            value=0,
            info="Allowed difference between the application head-count and the census before it is material.",
            advanced=True,
        ),
        IntInput(
            name="claims_tolerance_pct",
            display_name="Claims mismatch tolerance (%)",
            value=2,
            info="Allowed difference between the claims summary and the detailed report before it is material.",
            advanced=True,
        ),
    ]

    outputs = [Output(display_name="Validated Case", name="validated", method="validate")]

    def validate(self) -> Data:
        case = dict(self.extracted.data) if isinstance(self.extracted, Data) else dict(self.extracted or {})
        extraction = case.get("extraction", {})
        fields = extraction.get("fields", {})
        model = extraction.get("data_model", {})
        census_rows = extraction.get("census_rows", [])
        report: list[dict] = []

        def add(field, label, source_value, result, issue_type=None, detail="", evidence=None, material=False):
            report.append(
                {
                    "field": field,
                    "label": label,
                    "source_value": source_value,
                    "result": result,  # PASS | FAIL | WARN
                    "issue_type": issue_type,  # extraction_error | data_discrepancy | missing_field | missing_document | invalid_format
                    "detail": detail,
                    "evidence": evidence or [],
                    "material": material,
                }
            )

        def ev(field):
            f = fields.get(field)
            return [{"doc": f["source_doc"], "page": f.get("page"), "confidence": f.get("confidence"), "method": f.get("method")}] if f else []

        # 1. Missing documents
        present = set(model.get("documents_present", []))
        for doc_type, label in REQUIRED_DOCS.items():
            if doc_type not in present:
                add(f"document:{doc_type}", label, "not received", "FAIL", "missing_document", f"{label} was not attached.", material=True)

        # 2. Mandatory fields
        for field, label in MANDATORY:
            f = fields.get(field)
            if f is None or f.get("value") in (None, ""):
                add(field, label, "missing", "FAIL", "missing_field", f"{label} could not be found in the attachments.",
                    material=field in {"policy_expiry_date", "application_total_employees", "requested_sum_insured", "company_name"})
            else:
                add(field, label, f["raw"] if field not in {"requested_sum_insured", "claims_total_summary", "current_annual_premium"} else _inr(f["value"]),
                    "PASS", None, f"Extracted from {f['source_doc']} p.{f.get('page')} (confidence {f.get('confidence')}).", ev(field))

        # 3. Formats
        for field in ("coverage_start_date", "policy_start_date", "policy_expiry_date", "census_date"):
            f = fields.get(field)
            if f and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(f["raw"])):
                add(field, field.replace("_", " ").title(), f["raw"], "FAIL", "invalid_format", "Expected ISO date YYYY-MM-DD.", ev(field), material=False)
        if fields.get("broker_email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(fields["broker_email"]["raw"])):
            add("broker_email", "Broker email", fields["broker_email"]["raw"], "WARN", "invalid_format", "Email address format looks invalid.", ev("broker_email"))

        # 4. Cross-document: employees (application vs census)
        app_n = model.get("employees_application")
        census_n = model.get("employees_census_rows") or model.get("employees_census_declared")
        if app_n is not None and census_n:
            diff = abs(int(app_n) - int(census_n))
            if diff > int(self.employee_count_tolerance or 0):
                add("total_employees", "Total employees", f"{app_n} in application; {census_n} in census", "FAIL", "data_discrepancy",
                    f"Head-count differs by {diff}. The census is the rating basis; the broker must confirm the correct number.",
                    ev("application_total_employees") + ev("census_total_employees"), material=True)
            else:
                add("total_employees", "Total employees", f"{app_n} (application) = {census_n} (census)", "PASS", None, "Head-count consistent across documents.",
                    ev("application_total_employees") + ev("census_total_employees"))
        declared = model.get("employees_census_declared")
        rows = model.get("employees_census_rows")
        if declared and rows and int(declared) != int(rows):
            add("census_row_count", "Census row count", f"{rows} rows parsed; {declared} declared", "WARN", "extraction_error",
                "Parsed census rows differ from the declared total — possible table extraction issue; verify the census document.",
                ev("census_total_employees"))

        # 5. Census DOB / age consistency
        inconsistent = [r for r in census_rows if not r.get("age_consistent")]
        if census_rows:
            if inconsistent:
                sample = ", ".join(f"{r['employee_id']} (DOB {r['dob']}, stated {r['stated_age']}, computed {r['computed_age']}, p.{r['page']})" for r in inconsistent[:5])
                add("employee_dob", "Employee date of birth", f"Inconsistent for {len(inconsistent)} employee(s)", "FAIL", "data_discrepancy",
                    f"Stated age does not match date of birth: {sample}.", [{"doc": r["source_doc"], "page": r["page"]} for r in inconsistent[:5]],
                    material=len(inconsistent) >= 3)
            else:
                add("employee_dob", "Employee date of birth", f"Consistent for all {len(census_rows)} employees", "PASS")

        # 6. Claims summary vs detailed report
        s, d = model.get("claims_total_summary"), model.get("claims_total_detailed") or model.get("claims_rows_total")
        if s is not None and d:
            pct = abs(int(s) - int(d)) / max(int(d), 1) * 100
            if pct > float(self.claims_tolerance_pct or 0):
                add("claims_amount", "Claims amount", f"{_inr(s)} in summary; {_inr(d)} in detailed report", "FAIL", "data_discrepancy",
                    f"Summary and detailed claims differ by {pct:.1f}%. Loss ratio cannot be rated until the broker confirms the incurred claims.",
                    ev("claims_total_summary") + ev("claims_total_detailed"), material=True)
            else:
                add("claims_amount", "Claims amount", f"{_inr(s)} (summary) ≈ {_inr(d)} (detailed)", "PASS", None, "Claims figures reconcile.",
                    ev("claims_total_summary") + ev("claims_total_detailed"))

        # 7. Sum insured sanity
        si = model.get("requested_sum_insured")
        if si is not None and (int(si) < 100000 or int(si) > 5000000):
            add("requested_sum_insured_range", "Requested sum insured range", _inr(si), "WARN", "data_discrepancy",
                "Outside the usual ₹1 lakh – ₹50 lakh band for group medical cover; underwriter attention advised.", ev("requested_sum_insured"))

        # Scores
        total_fields = extraction.get("fields_expected") or 1
        completeness = round(100 * (extraction.get("fields_found") or 0) / total_fields)
        checks = [r for r in report if r["result"] in {"PASS", "FAIL"}]
        validation_score = round(100 * sum(1 for r in checks if r["result"] == "PASS") / max(len(checks), 1))
        material = [r for r in report if r["material"] and r["result"] == "FAIL"]
        status = "HOLD" if material else "PASS"

        case["validation"] = {
            "report": report,
            "completeness_score": completeness,
            "validation_score": validation_score,
            "material_issues": material,
            "warnings": [r for r in report if r["result"] == "WARN"],
            "status": status,
        }
        case.setdefault("audit_trail", []).append(
            {"step": "validation", "detail": f"{status}: {len(material)} material issue(s), completeness {completeness}%, validation {validation_score}%"}
        )
        self.status = json.dumps(
            {"status": status, "completeness": completeness, "validation_score": validation_score,
             "material_issues": [m["label"] for m in material]}, indent=2)
        return Data(data=case, text_key="intake_source")
