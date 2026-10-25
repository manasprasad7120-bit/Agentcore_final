"""Configurable rating engine (mock insurer rating table).

Premiums are computed only from the configured rating table — never by the
LLM. The table can be edited on the node or replaced by a call to the
insurer's rating API later.
"""

from __future__ import annotations

import json

from agentcore.custom.custom_node.node import Node
from agentcore.io import BoolInput, DataInput, MultilineInput, Output
from agentcore.schema.data import Data

DEFAULT_RATING_TABLE = {
    "currency": "INR",
    "base_sum_insured": 500000,
    "age_band_rates": [
        {"band": "18-29", "max_age": 29, "rate": 4000},
        {"band": "30-39", "max_age": 39, "rate": 5400},
        {"band": "40-49", "max_age": 49, "rate": 7600},
        {"band": "50+", "max_age": 120, "rate": 10500},
    ],
    "fallback_rate_per_employee": 6000,
    "dependant_loading_pct": 15,
    "claims_experience_adjustment": [
        {"max_loss_ratio": 0.6, "adjust_pct": -5, "label": "Favourable claims experience discount"},
        {"max_loss_ratio": 0.85, "adjust_pct": 0, "label": "Neutral claims experience"},
        {"max_loss_ratio": 1.0, "adjust_pct": 15, "label": "Adverse claims experience loading"},
        {"max_loss_ratio": 99, "adjust_pct": 30, "label": "Severe claims experience loading"},
    ],
    "minimum_premium_per_employee": 2500,
    "gst_pct": 18,
    "quote_validity_days": 30,
}


class UnderwritingRatingEngine(Node):
    display_name = "5. Rating Engine (configurable table)"
    description = (
        "Applies the insurer's configured rating table: age-band rates, sum-insured factor, dependant loading and "
        "claims-experience adjustment. Deterministic — the LLM never sets a price."
    )
    icon = "calculator"
    name = "UnderwritingRatingEngine"

    inputs = [
        DataInput(name="decision", display_name="Decision", required=True),
        MultilineInput(
            name="rating_table",
            display_name="Rating table (JSON)",
            value=json.dumps(DEFAULT_RATING_TABLE, indent=2),
            info="Insurer rating table. Replace with the approved tables or a rating-API call.",
        ),
        BoolInput(
            name="rate_if_on_hold",
            display_name="Compute indicative premium when on hold",
            value=False,
            info="If true, an indicative (non-binding) premium is computed even when the case is on hold or referred.",
            advanced=True,
        ),
    ]

    outputs = [Output(display_name="Rated Case", name="rated", method="rate")]

    def rate(self) -> Data:
        case = dict(self.decision.data) if isinstance(self.decision, Data) else dict(self.decision or {})
        decision = case.get("decision", {})
        model = case.get("extraction", {}).get("data_model", {})
        census_rows = case.get("extraction", {}).get("census_rows", [])

        try:
            table = json.loads(self.rating_table) if self.rating_table else DEFAULT_RATING_TABLE
        except json.JSONDecodeError as exc:
            msg = f"Rating table is not valid JSON: {exc}"
            raise ValueError(msg) from exc

        should_rate = decision.get("next_action") == "PROCEED_TO_QUOTE" or bool(self.rate_if_on_hold)
        if not should_rate:
            case["rating"] = {"status": "SKIPPED", "reason": f"Rating not performed: decision is {decision.get('next_action')}."}
            case.setdefault("audit_trail", []).append({"step": "rating", "detail": "skipped (case not cleared for quotation)"})
            self.status = case["rating"]["reason"]
            return Data(data=case, text_key="intake_source")

        sum_insured = int(model.get("requested_sum_insured") or table["base_sum_insured"])
        si_factor = round(sum_insured / int(table["base_sum_insured"]), 4)
        bands = sorted(table["age_band_rates"], key=lambda b: b["max_age"])

        def band_for(age: int) -> dict:
            return next((b for b in bands if age <= int(b["max_age"])), bands[-1])

        band_breakdown: dict[str, dict] = {}
        employee_base = 0.0
        if census_rows:
            for row in census_rows:
                band = band_for(int(row.get("stated_age") or 0))
                entry = band_breakdown.setdefault(band["band"], {"employees": 0, "rate": band["rate"], "premium": 0.0})
                entry["employees"] += 1
                entry["premium"] += band["rate"] * si_factor
                employee_base += band["rate"] * si_factor
            employees = len(census_rows)
            dependants = int(model.get("dependants_total") or 0)
        else:
            employees = int(model.get("employees_application") or 0)
            employee_base = employees * table["fallback_rate_per_employee"] * si_factor
            band_breakdown["flat"] = {"employees": employees, "rate": table["fallback_rate_per_employee"], "premium": employee_base}
            dependants = 0

        avg_rate = employee_base / employees if employees else 0
        dependant_loading = dependants * avg_rate * (float(table["dependant_loading_pct"]) / 100)
        subtotal = employee_base + dependant_loading

        loss_ratio = decision.get("loss_ratio")
        adjustment = next(
            (a for a in sorted(table["claims_experience_adjustment"], key=lambda a: a["max_loss_ratio"])
             if loss_ratio is not None and float(loss_ratio) <= float(a["max_loss_ratio"])),
            {"adjust_pct": 0, "label": "No claims experience available"},
        )
        claims_adjustment = subtotal * float(adjustment["adjust_pct"]) / 100
        premium = subtotal + claims_adjustment
        minimum = employees * float(table["minimum_premium_per_employee"])
        minimum_applied = premium < minimum
        premium = max(premium, minimum)
        gst = premium * float(table["gst_pct"]) / 100

        def r(x: float) -> int:
            return int(round(x))

        case["rating"] = {
            "status": "INDICATIVE" if decision.get("next_action") != "PROCEED_TO_QUOTE" else "RATED",
            "currency": table.get("currency", "INR"),
            "covered_employees": employees,
            "dependants": dependants,
            "sum_insured_per_employee": sum_insured,
            "sum_insured_factor": si_factor,
            "age_band_breakdown": {k: {"employees": v["employees"], "rate": v["rate"], "premium": r(v["premium"])} for k, v in band_breakdown.items()},
            "employee_base_premium": r(employee_base),
            "dependant_loading": r(dependant_loading),
            "dependant_loading_pct": table["dependant_loading_pct"],
            "loss_ratio": loss_ratio,
            "claims_adjustment_label": adjustment["label"],
            "claims_adjustment_pct": adjustment["adjust_pct"],
            "claims_adjustment": r(claims_adjustment),
            "minimum_premium_applied": minimum_applied,
            "annual_premium": r(premium),
            "gst_pct": table["gst_pct"],
            "gst": r(gst),
            "total_payable": r(premium + gst),
            "premium_per_employee": r(premium / employees) if employees else 0,
            "quote_validity_days": table.get("quote_validity_days", 30),
            "rating_basis": "Configured rating table (illustrative, not actuarially validated)",
        }
        case.setdefault("audit_trail", []).append(
            {"step": "rating", "detail": f"{case['rating']['status']}: annual premium {case['rating']['annual_premium']} for {employees} employees"}
        )
        self.status = json.dumps(case["rating"], indent=2)
        return Data(data=case, text_key="intake_source")
