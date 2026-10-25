"""Quote generation, broker email drafting and controlled dispatch.

Produces the quotation PDF (when the case is cleared), drafts the outbound
email for the decided action (quote / clarification / referral), optionally
polishes the wording with the LLM (numbers are never changed), and either keeps
the email as a draft pending approval or sends it through SMTP.
"""

from __future__ import annotations

import io
import os
import re
import smtplib
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path

from agentcore.custom.custom_node.node import Node
from agentcore.io import BoolInput, DataInput, DropdownInput, HandleInput, Output, StrInput
from agentcore.schema.data import Data
from agentcore.schema.message import Message

DRAFT, SEND = "Draft only (requires approval)", "Send via SMTP when approved"


def inr(value) -> str:
    if value is None:
        return "—"
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return str(value)
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if n < 0 else "") + "₹" + s


class UnderwritingQuoteComposer(Node):
    display_name = "6. Quote, Broker Email & Dispatch"
    description = (
        "Generates the quotation PDF, drafts the broker email for the decided action, shows the full review "
        "(extraction, validation, decision, rating, audit trail) and dispatches only when approved."
    )
    icon = "file-text"
    name = "UnderwritingQuoteComposer"

    inputs = [
        DataInput(name="rated", display_name="Rated Case", required=True),
        HandleInput(
            name="llm",
            display_name="Language Model (optional)",
            info="Optional LLM used to polish the email wording. Figures are fixed by the rating engine.",
            input_types=["LanguageModel"],
            required=False,
        ),
        StrInput(name="insurer_name", display_name="Insurer name", value="Demo General Insurance Co. Ltd."),
        StrInput(name="underwriter_signature", display_name="Email signature", value="Insurance Underwriting Team"),
        DropdownInput(
            name="dispatch_mode",
            display_name="Dispatch mode",
            options=[DRAFT, SEND],
            value=DRAFT,
            info="Emails are drafts by default. Sending requires 'Approved' and SMTP_* settings in .env.",
        ),
        BoolInput(
            name="approved",
            display_name="Approved by authorised underwriter",
            value=False,
            info="Human approval gate for dispatch.",
        ),
        StrInput(
            name="output_folder",
            display_name="Output folder for quote PDF",
            value="",
            info="Optional local folder to copy the generated quote PDF into (e.g. a mock outbox).",
            advanced=True,
        ),
    ]

    outputs = [
        Output(display_name="Underwriting Response", name="response", method="compose"),
        Output(display_name="Case Record (JSON)", name="case_record", method="case_record"),
    ]

    # ------------------------------------------------------------------ PDF
    @staticmethod
    def _build_quote_pdf(case: dict, insurer: str) -> bytes:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas

        model = case["extraction"]["data_model"]
        rating = case["rating"]
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        w, h = A4
        y = h - 25 * mm

        def line(text, size=10, bold=False, dy=6 * mm, color=colors.black):
            nonlocal y
            c.setFillColor(color)
            c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
            c.drawString(20 * mm, y, text)
            y -= dy

        line(insurer, 16, True, 8 * mm, colors.HexColor("#b3202c"))
        line("Group Medical Insurance — Quotation (Illustrative)", 13, True, 10 * mm)
        line(f"Quote reference: {case.get('case_id')}    Date: {date.today().isoformat()}    "
             f"Valid until: {(date.today() + timedelta(days=int(rating.get('quote_validity_days', 30)))).isoformat()}", 9)
        y -= 3 * mm
        line("Proposer", 11, True)
        line(f"Company: {model.get('company_name') or '—'}")
        line(f"Industry: {model.get('industry') or '—'}    Broker: {model.get('broker_name') or '—'}")
        line(f"Policy: {model.get('policy_type')}    Coverage start: {model.get('coverage_start_date') or 'To be confirmed'}")
        y -= 3 * mm
        line("Coverage & Premium", 11, True)
        rows = [
            ("Covered employees", str(rating["covered_employees"])),
            ("Dependants covered", str(rating["dependants"])),
            ("Sum insured per employee", inr(rating["sum_insured_per_employee"])),
            ("Employee base premium", inr(rating["employee_base_premium"])),
            (f"Dependant loading ({rating['dependant_loading_pct']}%)", inr(rating["dependant_loading"])),
            (f"{rating['claims_adjustment_label']} ({rating['claims_adjustment_pct']:+}%)", inr(rating["claims_adjustment"])),
            ("Annual premium (excl. GST)", inr(rating["annual_premium"])),
            (f"GST @ {rating['gst_pct']}% (calculated separately)", inr(rating["gst"])),
            ("Total payable", inr(rating["total_payable"])),
        ]
        for label, value in rows:
            c.setFont("Helvetica", 10)
            c.drawString(20 * mm, y, label)
            c.setFont("Helvetica-Bold", 10)
            c.drawRightString(w - 20 * mm, y, value)
            y -= 6 * mm
        y -= 3 * mm
        line("Age-band breakdown", 11, True)
        for band, info in rating["age_band_breakdown"].items():
            line(f"{band}: {info['employees']} employees × rate {inr(info['rate'])} → {inr(info['premium'])}", 9)
        y -= 3 * mm
        line("Terms & Conditions", 11, True)
        for t in (
            "Subject to the insurer's applicable underwriting guidelines and authorised approval.",
            "Premium computed from the configured rating table; placeholder rates, not actuarially validated.",
            "Pre-existing disease waiting periods, room-rent limits and exclusions as per the policy wording.",
            f"Loss ratio considered: {rating.get('loss_ratio')} ({case['decision'].get('risk_tier')} risk tier).",
        ):
            line(f"• {t}", 9, dy=5 * mm)
        c.setFont("Helvetica-Oblique", 8)
        c.setFillColor(colors.grey)
        c.drawString(20 * mm, 15 * mm, "Generated by the Email-to-Quote Underwriting Agent — all company names and figures are fictional demo data.")
        c.showPage()
        c.save()
        return buf.getvalue()

    # ------------------------------------------------------------------ emails
    def _draft_email(self, case: dict) -> dict:
        model = case["extraction"]["data_model"]
        decision = case["decision"]
        validation = case["validation"]
        company = model.get("company_name") or "the proposer"
        broker = model.get("broker_name") or case.get("email", {}).get("from") or "Broker"
        to_addr = model.get("broker_email") or case.get("email", {}).get("from") or ""
        subject_in = case.get("email", {}).get("subject") or f"Group Medical Insurance — {company}"
        action = decision["next_action"]

        if action == "PROCEED_TO_QUOTE":
            r = case["rating"]
            subject = f"RE: {subject_in} — Proposed Quotation"
            body = (
                f"Dear {broker},\n\n"
                f"We have completed the preliminary review of the Group Medical Insurance submission for {company}. "
                "Please find the proposed quotation attached, including the coverage details, premium breakdown, terms and conditions.\n\n"
                f"Summary of the proposed terms:\n"
                f"  • Covered employees: {r['covered_employees']} (dependants: {r['dependants']})\n"
                f"  • Sum insured per employee: {inr(r['sum_insured_per_employee'])}\n"
                f"  • Annual premium (excl. GST): {inr(r['annual_premium'])}\n"
                f"  • GST @ {r['gst_pct']}%: {inr(r['gst'])}  |  Total payable: {inr(r['total_payable'])}\n"
                f"  • Quote valid for {r['quote_validity_days']} days from {date.today().isoformat()}\n\n"
                "This quotation is subject to the insurer's applicable underwriting guidelines and authorised approval.\n\n"
                f"Regards,\n{self.underwriter_signature}\n{self.insurer_name}"
            )
        elif action == "REQUEST_CLARIFICATION":
            subject = f"RE: {subject_in} — Clarification required before quotation"
            items = "\n".join(f"  {i}. {m['label']}: {m['source_value']}. {m['detail']}" for i, m in enumerate(validation["material_issues"], 1))
            body = (
                f"Dear {broker},\n\n"
                f"Thank you for the Group Medical Insurance submission for {company}. During our field-level review of the "
                "attached documents we found discrepancies that must be resolved before a quotation can be released:\n\n"
                f"{items}\n\n"
                "Kindly share the corrected documents or confirm the correct figures. The case has been placed on hold and "
                "will resume automatically once the clarified information is received.\n\n"
                f"Regards,\n{self.underwriter_signature}\n{self.insurer_name}"
            )
        else:
            subject = f"RE: {subject_in} — Submission under underwriter review"
            reasons = "\n".join(f"  • {x}" for x in decision["reasons"])
            body = (
                f"Dear {broker},\n\n"
                f"Thank you for the Group Medical Insurance submission for {company}. The documents have been validated and the "
                "case has been referred to an authorised underwriter for review because of the following risk indicators:\n\n"
                f"{reasons}\n\n"
                "We will revert with the underwriting decision and quotation shortly.\n\n"
                f"Regards,\n{self.underwriter_signature}\n{self.insurer_name}"
            )

        body = self._polish(body)
        return {"to": to_addr, "subject": subject, "body": body, "action": action}

    def _polish(self, body: str) -> str:
        if self.llm is None:
            return body
        numbers = set(re.findall(r"[₹\d][\d,.%]*", body))
        prompt = (
            "Rewrite the following insurance underwriting email so it is concise, professional and courteous. "
            "Keep every number, amount, date, name and bullet exactly as given, keep the same structure and sign-off, "
            "and return ONLY the email body.\n\n" + body
        )
        try:
            result = self.llm.invoke(prompt)
            content = getattr(result, "content", result)
            if isinstance(content, list):
                content = "\n".join(str(c.get("text", c)) if isinstance(c, dict) else str(c) for c in content)
            polished = str(content).strip()
            # Safety: every figure in the original must survive the rewrite, otherwise keep the deterministic draft.
            if polished and all(n in polished for n in numbers if any(ch.isdigit() for ch in n)):
                return polished
            self.log("LLM rewrite dropped a figure; keeping the deterministic draft.")
        except Exception as exc:  # noqa: BLE001
            self.log(f"LLM polish skipped: {exc}")
        return body

    def _dispatch(self, email: dict, attachment: tuple[str, bytes] | None) -> str:
        if self.dispatch_mode != SEND:
            return "DRAFT — awaiting approval (dispatch mode: draft only)"
        if not self.approved:
            return "HELD — 'Approved by authorised underwriter' is not set"
        host = os.getenv("SMTP_HOST") or os.getenv("SMTP_SERVER")
        if not host or not email.get("to"):
            return "NOT SENT — SMTP_HOST or recipient address not configured"
        try:
            msg = EmailMessage()
            msg["From"] = os.getenv("SMTP_FROM_EMAIL") or os.getenv("SMTP_FROM") or os.getenv("SMTP_USERNAME") or "underwriting@example.com"
            msg["To"] = email["to"]
            msg["Subject"] = email["subject"]
            msg.set_content(email["body"])
            if attachment:
                msg.add_attachment(attachment[1], maintype="application", subtype="pdf", filename=attachment[0])
            port = int(os.getenv("SMTP_PORT") or 587)
            use_ssl = (os.getenv("SMTP_USE_SSL") or "false").lower() in {"1", "true", "yes"}
            smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
            with smtp_cls(host, port, timeout=20) as s:
                if not use_ssl and (os.getenv("SMTP_USE_TLS") or "true").lower() in {"1", "true", "yes"}:
                    s.starttls()
                user = os.getenv("SMTP_USERNAME") or os.getenv("SMTP_USER")
                if user:
                    s.login(user, os.getenv("SMTP_PASSWORD") or "")
                s.send_message(msg)
            return f"SENT to {email['to']} via {host}"
        except Exception as exc:  # noqa: BLE001
            return f"FAILED — {exc}"

    # ------------------------------------------------------------------ outputs
    def _case(self) -> dict:
        return dict(self.rated.data) if isinstance(self.rated, Data) else dict(self.rated or {})

    async def compose(self) -> Message:
        case = self._case()
        model = case.get("extraction", {}).get("data_model", {})
        validation = case.get("validation", {})
        decision = case.get("decision", {})
        rating = case.get("rating", {})
        email = self._draft_email(case)

        attachment = None
        files: list[str] = []
        pdf_note = ""
        if decision.get("next_action") == "PROCEED_TO_QUOTE" and rating.get("status") == "RATED":
            pdf_bytes = self._build_quote_pdf(case, self.insurer_name)
            filename = f"Quote_{re.sub(r'[^A-Za-z0-9]+', '_', model.get('company_name') or 'proposer')}_{case.get('case_id')}.pdf"
            attachment = (filename, pdf_bytes)
            try:
                from agentcore.services.deps import get_storage_service

                agent_id = str(self.agent_id or "underwriting")
                await get_storage_service().save_file(agent_id, filename, pdf_bytes)
                files.append(f"{agent_id}/{filename}")
                pdf_note = f"Quote PDF saved as `{agent_id}/{filename}` in the agent's file storage."
            except Exception as exc:  # noqa: BLE001
                pdf_note = f"Quote PDF generated in memory (storage save failed: {exc})."
            if (self.output_folder or "").strip():
                out = Path(self.output_folder.strip())
                out.mkdir(parents=True, exist_ok=True)
                (out / filename).write_bytes(pdf_bytes)
                pdf_note += f" Copy written to `{out / filename}`."

        dispatch_status = self._dispatch(email, attachment)
        case["outbound_email"] = {**email, "dispatch_status": dispatch_status, "attachment": attachment[0] if attachment else None}
        case.setdefault("audit_trail", []).append({"step": "dispatch", "detail": dispatch_status})

        # ---------------- markdown review
        action_label = {
            "PROCEED_TO_QUOTE": "✅ Proceed to quotation",
            "REQUEST_CLARIFICATION": "⚠️ Clarification requested — case on hold",
            "REFER_TO_UNDERWRITER": "🔍 Referred to authorised underwriter",
        }.get(decision.get("next_action"), decision.get("next_action"))

        lines = [
            f"## Underwriting review — {model.get('company_name') or 'Unknown proposer'}",
            f"**Case** `{case.get('case_id')}` · intake: {case.get('intake_source')} · "
            f"documents: {', '.join(a['name'] for a in case.get('attachments', []))}",
            "",
            f"### Decision: {action_label}",
            *[f"- {r}" for r in decision.get("reasons", [])],
            f"- Risk tier: **{decision.get('risk_tier')}** · loss ratio: **{decision.get('loss_ratio')}** · "
            f"completeness: **{validation.get('completeness_score')}%** · validation score: **{validation.get('validation_score')}%**",
            "",
            "### Field-level validation",
            "| Field | Source value | Result | Type | Evidence |",
            "|---|---|---|---|---|",
        ]
        for r in validation.get("report", []):
            icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(r["result"], "")
            evidence = "; ".join(f"{e.get('doc')} p.{e.get('page')}" + (f" ({e.get('confidence')})" if e.get("confidence") else "") for e in r.get("evidence", [])[:2])
            lines.append(f"| {r['label']} | {r['source_value']} | {icon} {r['result']} | {r.get('issue_type') or ''} | {evidence} |")

        lines += ["", "### Extracted data model", "| Field | Value |", "|---|---|"]
        for k, v in model.items():
            if k == "documents_present":
                v = ", ".join(v)
            elif k in {"requested_sum_insured", "current_sum_insured", "current_annual_premium", "claims_total_summary", "claims_total_detailed", "claims_rows_total"}:
                v = inr(v)
            lines.append(f"| {k.replace('_', ' ')} | {v if v is not None else '—'} |")

        if rating.get("status") in {"RATED", "INDICATIVE"}:
            lines += [
                "",
                f"### Rating & quotation ({rating['status'].lower()})",
                "| Item | Amount |",
                "|---|---|",
                f"| Covered employees | {rating['covered_employees']} (dependants {rating['dependants']}) |",
                f"| Sum insured per employee | {inr(rating['sum_insured_per_employee'])} |",
                f"| Employee base premium | {inr(rating['employee_base_premium'])} |",
                f"| Dependant loading ({rating['dependant_loading_pct']}%) | {inr(rating['dependant_loading'])} |",
                f"| {rating['claims_adjustment_label']} ({rating['claims_adjustment_pct']:+}%) | {inr(rating['claims_adjustment'])} |",
                f"| **Annual premium (excl. GST)** | **{inr(rating['annual_premium'])}** |",
                f"| GST @ {rating['gst_pct']}% | {inr(rating['gst'])} |",
                f"| Total payable | {inr(rating['total_payable'])} |",
                "",
                f"_{rating['rating_basis']}._ {pdf_note}",
            ]
        elif rating:
            lines += ["", f"### Rating: {rating.get('reason')}"]

        lines += [
            "",
            f"### Outbound email — {dispatch_status}",
            f"**To:** {email['to'] or '—'}  ",
            f"**Subject:** {email['subject']}",
            "",
            "```",
            email["body"],
            "```",
            "",
            "### Audit trail",
            *[f"{i}. **{a['step']}** — {a['detail']}" for i, a in enumerate(case.get("audit_trail", []), 1)],
        ]

        self._case_record = case
        self.status = action_label
        return Message(text="\n".join(lines), files=files, sender="Machine", sender_name="Underwriting Agent")

    def case_record(self) -> Data:
        case = getattr(self, "_case_record", None) or self._case()
        return Data(data=case, text_key="intake_source")
