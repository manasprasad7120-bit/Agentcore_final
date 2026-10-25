"""Document intelligence step: extract and normalise fields from the attachments.

Deterministic, evidence-backed extraction (document, page, confidence) for the
structured synthetic documents, optionally refined by an LLM for free-form
layouts. The output is the standard underwriting data model used by the
validation, rating and quote steps.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime

from agentcore.custom.custom_node.node import Node
from agentcore.io import BoolInput, DataInput, HandleInput, Output
from agentcore.schema.data import Data

# Field label patterns -> (field name, document type where it is authoritative)
FIELD_PATTERNS: dict[str, tuple[str, str]] = {
    "company_name": (r"Company Name\s*:\s*(.+)", "application"),
    "industry": (r"Industry\s*:\s*(.+)", "application"),
    "registered_address": (r"Registered Address\s*:\s*(.+)", "application"),
    "application_total_employees": (r"Total Employees\s*:\s*([\d,]+)", "application"),
    "requested_sum_insured": (r"Requested Sum Insured per Employee\s*:\s*(?:INR|Rs\.?|₹)?\s*([\d,]+)", "application"),
    "policy_type": (r"Policy Type\s*:\s*(.+)", "application"),
    "coverage_start_date": (r"Coverage Start Date\s*:\s*([\d-]+)", "application"),
    "broker_name": (r"Broker\s*:\s*(.+)", "application"),
    "broker_email": (r"Contact Email\s*:\s*(\S+@\S+)", "application"),
    "census_date": (r"Census Date\s*:\s*([\d-]+)", "census"),
    "census_total_employees": (r"Total Employees in Census\s*:\s*([\d,]+)", "census"),
    "claims_policy_period": (r"Policy Period\s*:\s*(.+)", "claims"),
    "claims_total_summary": (r"Total Incurred Claims \(Summary\)\s*:\s*(?:INR|Rs\.?|₹)?\s*([\d,]+)", "claims"),
    "claims_total_detailed": (r"Total of Detailed Claims\s*:\s*(?:INR|Rs\.?|₹)?\s*([\d,]+)", "claims"),
    "current_insurer": (r"Insurer\s*:\s*(.+)", "policy"),
    "policy_number": (r"Policy Number\s*:\s*(\S+)", "policy"),
    "policy_start_date": (r"Policy Start Date\s*:\s*([\d-]+)", "policy"),
    "policy_expiry_date": (r"Policy Expiry Date\s*:\s*([\d-]+)", "policy"),
    "current_sum_insured": (r"Sum Insured per Employee\s*:\s*(?:INR|Rs\.?|₹)?\s*([\d,]+)", "policy"),
    "current_annual_premium": (r"Annual Premium \(Current\)\s*:\s*(?:INR|Rs\.?|₹)?\s*([\d,]+)", "policy"),
}
NUMERIC_FIELDS = {
    "application_total_employees",
    "requested_sum_insured",
    "census_total_employees",
    "claims_total_summary",
    "claims_total_detailed",
    "current_sum_insured",
    "current_annual_premium",
}
CENSUS_ROW = re.compile(
    r"(EMP\d+)\s*\|\s*(.+?)\s*\|\s*DOB\s*([\d-]+)\s*\|\s*Age\s*(\d+)\s*\|\s*(.+?)\s*\|\s*Dependants\s*(\d+)",
    re.I,
)
CLAIM_ROW = re.compile(r"(CLM-\d+)\s*\|\s*([\d-]+)\s*\|\s*(EMP\d+)\s*\|\s*(.+?)\s*\|\s*(?:INR|Rs\.?|₹)?\s*([\d,]+)", re.I)


def _to_int(value: str) -> int | None:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


class UnderwritingDocumentExtractor(Node):
    display_name = "2. Document Intelligence & Normalisation"
    description = (
        "Extracts fields from every attachment with source document, page and confidence, parses the census and "
        "claims tables and consolidates everything into the standard underwriting data model."
    )
    icon = "scan-text"
    name = "UnderwritingDocumentExtractor"

    inputs = [
        DataInput(name="case", display_name="Underwriting Case", info="Output of the intake step.", required=True),
        HandleInput(
            name="llm",
            display_name="Language Model (optional)",
            info="Optional LLM used to extract fields the rule-based extractor could not find in free-form documents.",
            input_types=["LanguageModel"],
            required=False,
        ),
        BoolInput(
            name="use_llm_for_missing",
            display_name="Use LLM for missing fields",
            value=True,
            info="When a model is connected, ask it only for fields the deterministic extractor left empty.",
            advanced=True,
        ),
    ]

    outputs = [Output(display_name="Extracted Case", name="extracted", method="extract")]

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _age_on(dob: str, as_of: date) -> int | None:
        try:
            d = datetime.strptime(dob, "%Y-%m-%d").date()
        except ValueError:
            return None
        return as_of.year - d.year - ((as_of.month, as_of.day) < (d.month, d.day))

    def _llm_fill(self, missing: list[str], documents: list[dict]) -> dict:
        if not missing or self.llm is None:
            return {}
        corpus = "\n\n".join(f"### {d['name']} (page {p['page']})\n{p['text'][:3000]}" for d in documents for p in d["pages"])
        prompt = (
            "You are an insurance underwriting assistant. Extract ONLY the following fields from the documents. "
            "Return strict JSON: {field: {\"value\": <string>, \"source_doc\": <file name>, \"page\": <int>}}. "
            "Use null when a field is genuinely absent. Do not invent values.\n\n"
            f"Fields: {', '.join(missing)}\n\nDocuments:\n{corpus[:24000]}"
        )
        try:
            result = self.llm.invoke(prompt)
            content = getattr(result, "content", result)
            if isinstance(content, list):
                content = " ".join(str(c.get("text", c)) if isinstance(c, dict) else str(c) for c in content)
            match = re.search(r"\{.*\}", str(content), re.S)
            return json.loads(match.group(0)) if match else {}
        except Exception as exc:  # noqa: BLE001
            self.log(f"LLM extraction skipped: {exc}")
            return {}

    # ------------------------------------------------------------------ main
    def extract(self) -> Data:
        case = dict(self.case.data) if isinstance(self.case, Data) else dict(self.case or {})
        documents = case.get("attachments", [])
        fields: dict[str, dict] = {}

        for field, (pattern, preferred_doc) in FIELD_PATTERNS.items():
            best = None
            for doc in documents:
                for page in doc["pages"]:
                    m = re.search(pattern, page["text"], re.I)
                    if not m:
                        continue
                    raw = m.group(1).strip()
                    value = _to_int(raw) if field in NUMERIC_FIELDS else raw
                    candidate = {
                        "value": value,
                        "raw": raw,
                        "source_doc": doc["name"],
                        "page": page["page"],
                        "confidence": 0.97 if doc["doc_type"] == preferred_doc else 0.80,
                        "method": "rule",
                    }
                    if best is None or candidate["confidence"] > best["confidence"]:
                        best = candidate
            if best:
                fields[field] = best

        # Census rows (one per employee)
        census_rows: list[dict] = []
        census_doc = next((d for d in documents if d["doc_type"] == "census"), None)
        as_of = date.today()
        if fields.get("census_date"):
            try:
                as_of = datetime.strptime(fields["census_date"]["value"], "%Y-%m-%d").date()
            except ValueError:
                pass
        if census_doc:
            for page in census_doc["pages"]:
                for m in CENSUS_ROW.finditer(page["text"]):
                    emp_id, name, dob, age, location, dependants = m.groups()
                    computed = self._age_on(dob, as_of)
                    census_rows.append(
                        {
                            "employee_id": emp_id,
                            "name": name.strip(),
                            "dob": dob,
                            "stated_age": int(age),
                            "computed_age": computed,
                            "age_consistent": computed is not None and abs(computed - int(age)) <= 1,
                            "location": location.strip(),
                            "dependants": int(dependants),
                            "source_doc": census_doc["name"],
                            "page": page["page"],
                        }
                    )

        # Detailed claims rows
        claims_rows: list[dict] = []
        claims_doc = next((d for d in documents if d["doc_type"] == "claims"), None)
        if claims_doc:
            for page in claims_doc["pages"]:
                for m in CLAIM_ROW.finditer(page["text"]):
                    claim_id, claim_date, emp_id, claim_type, amount = m.groups()
                    claims_rows.append(
                        {
                            "claim_id": claim_id,
                            "date": claim_date,
                            "employee_id": emp_id,
                            "type": claim_type.strip(),
                            "amount": _to_int(amount) or 0,
                            "source_doc": claims_doc["name"],
                            "page": page["page"],
                        }
                    )

        # LLM assist for anything still missing (free-form documents)
        missing = [f for f in FIELD_PATTERNS if f not in fields]
        if missing and self.llm is not None and self.use_llm_for_missing:
            for field, info in (self._llm_fill(missing, documents) or {}).items():
                if field in FIELD_PATTERNS and isinstance(info, dict) and info.get("value") not in (None, "", "null"):
                    raw = str(info["value"])
                    fields[field] = {
                        "value": _to_int(raw) if field in NUMERIC_FIELDS else raw,
                        "raw": raw,
                        "source_doc": info.get("source_doc") or "unknown",
                        "page": info.get("page"),
                        "confidence": 0.70,
                        "method": "llm",
                    }

        present_docs = {d["doc_type"] for d in documents}
        model = {
            "company_name": fields.get("company_name", {}).get("value"),
            "industry": fields.get("industry", {}).get("value"),
            "broker_name": fields.get("broker_name", {}).get("value") or case.get("email", {}).get("from"),
            "broker_email": fields.get("broker_email", {}).get("value") or case.get("email", {}).get("from"),
            "policy_type": fields.get("policy_type", {}).get("value") or "Group Medical Insurance",
            "coverage_start_date": fields.get("coverage_start_date", {}).get("value"),
            "employees_application": fields.get("application_total_employees", {}).get("value"),
            "employees_census_declared": fields.get("census_total_employees", {}).get("value"),
            "employees_census_rows": len(census_rows),
            "requested_sum_insured": fields.get("requested_sum_insured", {}).get("value"),
            "current_sum_insured": fields.get("current_sum_insured", {}).get("value"),
            "current_annual_premium": fields.get("current_annual_premium", {}).get("value"),
            "claims_total_summary": fields.get("claims_total_summary", {}).get("value"),
            "claims_total_detailed": fields.get("claims_total_detailed", {}).get("value"),
            "claims_rows_total": sum(c["amount"] for c in claims_rows),
            "policy_expiry_date": fields.get("policy_expiry_date", {}).get("value"),
            "dependants_total": sum(r["dependants"] for r in census_rows),
            "average_age": round(sum(r["stated_age"] for r in census_rows) / len(census_rows), 1) if census_rows else None,
            "documents_present": sorted(present_docs),
        }

        case["extraction"] = {
            "fields": fields,
            "census_rows": census_rows,
            "claims_rows": claims_rows,
            "data_model": model,
            "fields_found": len(fields),
            "fields_expected": len(FIELD_PATTERNS),
            "llm_used": any(f.get("method") == "llm" for f in fields.values()),
        }
        case.setdefault("audit_trail", []).append(
            {
                "step": "extraction",
                "detail": f"{len(fields)}/{len(FIELD_PATTERNS)} fields, {len(census_rows)} census rows, "
                f"{len(claims_rows)} claim rows",
            }
        )
        self.status = json.dumps(model, indent=2, default=str)
        return Data(data=case, text_key="intake_source")
