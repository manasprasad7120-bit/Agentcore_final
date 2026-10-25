"""Agentic decision step.

Looks at the validation outcome and the risk profile and decides the next
action: proceed to the approved rating engine, put the case on hold and ask the
broker for clarification, or refer it to an authorised underwriter.
"""

from __future__ import annotations

import json

from agentcore.custom.custom_node.node import Node
from agentcore.io import DataInput, FloatInput, IntInput, Output
from agentcore.schema.data import Data

PROCEED, CLARIFY, REFER = "PROCEED_TO_QUOTE", "REQUEST_CLARIFICATION", "REFER_TO_UNDERWRITER"


class UnderwritingDecisionRouter(Node):
    display_name = "4. Underwriting Decision"
    description = (
        "Decides the next action from the validation report and risk indicators: proceed to rating, request "
        "clarification from the broker (case on hold) or refer to an authorised underwriter."
    )
    icon = "git-branch"
    name = "UnderwritingDecisionRouter"

    inputs = [
        DataInput(name="validated", display_name="Validated Case", required=True),
        FloatInput(
            name="max_auto_loss_ratio",
            display_name="Max loss ratio for auto-quote",
            value=1.0,
            info="Incurred claims ÷ current annual premium above this value is referred to an underwriter.",
        ),
        IntInput(name="max_auto_employees", display_name="Max employees for auto-quote", value=1000),
        IntInput(name="max_auto_sum_insured", display_name="Max sum insured per employee for auto-quote", value=1000000),
        IntInput(
            name="min_validation_score",
            display_name="Minimum validation score (%)",
            value=70,
            info="Below this score the case is referred even when no single issue is material.",
            advanced=True,
        ),
    ]

    outputs = [Output(display_name="Decision", name="decision", method="decide")]

    def decide(self) -> Data:
        case = dict(self.validated.data) if isinstance(self.validated, Data) else dict(self.validated or {})
        validation = case.get("validation", {})
        model = case.get("extraction", {}).get("data_model", {})
        reasons: list[str] = []

        claims = model.get("claims_total_detailed") or model.get("claims_rows_total") or model.get("claims_total_summary")
        premium = model.get("current_annual_premium")
        loss_ratio = round(int(claims) / int(premium), 2) if claims and premium else None
        employees = model.get("employees_census_rows") or model.get("employees_application") or 0
        sum_insured = model.get("requested_sum_insured") or 0

        if validation.get("material_issues"):
            action = CLARIFY
            reasons = [f"{m['label']}: {m['detail']}" for m in validation["material_issues"]]
        else:
            if loss_ratio is not None and loss_ratio > float(self.max_auto_loss_ratio or 1.0):
                reasons.append(f"Loss ratio {loss_ratio} exceeds the auto-quote limit of {self.max_auto_loss_ratio}.")
            if int(employees) > int(self.max_auto_employees or 1000):
                reasons.append(f"Group size {employees} exceeds the auto-quote limit of {self.max_auto_employees}.")
            if int(sum_insured) > int(self.max_auto_sum_insured or 1000000):
                reasons.append(f"Requested sum insured {sum_insured} exceeds the auto-quote limit of {self.max_auto_sum_insured}.")
            if int(validation.get("validation_score", 0)) < int(self.min_validation_score or 0):
                reasons.append(f"Validation score {validation.get('validation_score')}% is below {self.min_validation_score}%.")
            action = REFER if reasons else PROCEED
            if action == PROCEED:
                reasons = ["All critical fields validated; risk indicators within the auto-quote authority."]

        if loss_ratio is None:
            risk_tier = "UNKNOWN"
        elif loss_ratio < 0.6:
            risk_tier = "LOW"
        elif loss_ratio <= 0.85:
            risk_tier = "MEDIUM"
        else:
            risk_tier = "HIGH"

        case["decision"] = {
            "next_action": action,
            "reasons": reasons,
            "loss_ratio": loss_ratio,
            "risk_tier": risk_tier,
            "employees_considered": employees,
            "warnings": [w["label"] for w in validation.get("warnings", [])],
        }
        case.setdefault("audit_trail", []).append({"step": "decision", "detail": f"{action} ({risk_tier} risk, loss ratio {loss_ratio})"})
        self.status = json.dumps(case["decision"], indent=2)
        return Data(data=case, text_key="intake_source")
