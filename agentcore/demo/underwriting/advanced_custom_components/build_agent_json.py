"""Assemble the importable agent JSON for the Email-to-Quote Underwriting Agent.

Uses the running backend to render exact node templates:
  * built-in nodes (Chat Input, Chat Output, Large Language Model) from GET /api/all
  * the six custom underwriting components from POST /api/custom_component

Usage (backend must be running, credentials from .env or env vars):
    python demo/underwriting/build_agent_json.py
Writes:
    Email_to_Quote_Underwriting_Agent.json          (LLM node wired in; pick a model after import)
    Email_to_Quote_Underwriting_Agent_no_llm.json   (deterministic only; runs without any model)
"""

from __future__ import annotations

import gzip
import json
import os
import random
import string
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
API = os.getenv("AGENTCORE_API", "http://127.0.0.1:7860").rstrip("/")

COMPONENT_FILES = [
    "underwriting_email_intake.py",
    "underwriting_mailbox_intake.py",
    "underwriting_document_extractor.py",
    "underwriting_validation_engine.py",
    "underwriting_decision_router.py",
    "underwriting_rating_engine.py",
    "underwriting_quote_composer.py",
]

SAMPLE_EMAIL = (
    "Subject: Group Medical Insurance — Renewal Quote Request — ABC Technologies\n\n"
    "Dear Underwriting Team,\n\n"
    "Please find attached the employee census, current policy details, claims experience report and company "
    "information for our client's group medical insurance renewal.\n\n"
    "Kindly review the information and share your proposed premium quotation and coverage terms.\n\n"
    "Regards,\nCorporate Insurance Broker"
)


def _env_from_dotenv(key: str) -> str:
    env_file = ROOT / ".env"
    if os.getenv(key):
        return os.getenv(key, "")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return ""


def _request(method: str, path: str, token: str | None = None, data: bytes | None = None, content_type: str = "application/json"):
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Content-Type", content_type)
    req.add_header("Accept-Encoding", "identity")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":  # the backend gzips large responses regardless of Accept-Encoding
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def login() -> str:
    user = _env_from_dotenv("AGENTCORE_SUPERUSER") or "admin@demo.local"
    password = _env_from_dotenv("AGENTCORE_SUPERUSER_PASSWORD") or "Demo@12345"
    body = urllib.parse.urlencode({"username": user, "password": password}).encode()
    return _request("POST", "/api/login", data=body, content_type="application/x-www-form-urlencoded")["access_token"]


def suffix() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=5))  # noqa: S311


def make_node(type_name: str, frontend_node: dict, x: float, y: float, width: int = 340) -> dict:
    node_id = f"{type_name}-{suffix()}"
    node = json.loads(json.dumps(frontend_node))
    node.setdefault("edited", False)
    node.setdefault("frozen", False)
    node.setdefault("hidden", False)
    node.setdefault("minimized", False)
    node.setdefault("pinned", False)
    return {
        "id": node_id,
        "type": "genericNode",
        "position": {"x": x, "y": y},
        "data": {"id": node_id, "type": type_name, "node": node, "showNode": True},
        "dragging": False,
        "selected": False,
        "measured": {"width": width, "height": 420},
    }


def enc(d: dict) -> str:
    return json.dumps(d, separators=(",", ":")).replace('"', "œ")


def make_edge(src: dict, out_name: str, tgt: dict, field: str) -> dict:
    out = next(o for o in src["data"]["node"]["outputs"] if o["name"] == out_name)
    tmpl = tgt["data"]["node"]["template"][field]
    sh = {"dataType": src["data"]["type"], "id": src["id"], "name": out_name, "output_types": out["types"]}
    th = {"fieldName": field, "id": tgt["id"], "inputTypes": tmpl.get("input_types") or [], "type": tmpl.get("type", "other")}
    return {
        "animated": False,
        "className": "",
        "data": {"sourceHandle": sh, "targetHandle": th},
        "id": f"reactFlow__edge-{src['id']}{enc(sh)}-{tgt['id']}{enc(th)}",
        "selected": False,
        "source": src["id"],
        "sourceHandle": enc(sh),
        "target": tgt["id"],
        "targetHandle": enc(th),
    }


_TEMPLATE_CACHE: dict[str, dict] = {}


def build(token: str, *, with_llm: bool, intake: str = "chat") -> dict:
    """intake: 'chat' (Playground text + attachments / bundled samples) or 'outlook' (live mailbox)."""
    if not _TEMPLATE_CACHE:
        catalogue = _request("GET", "/api/all", token)
        _TEMPLATE_CACHE["builtin"] = {name: tmpl for cat in catalogue.values() for name, tmpl in cat.items()}
        custom: dict[str, dict] = {}
        for file in COMPONENT_FILES:
            code = (HERE / "components" / file).read_text(encoding="utf-8")
            resp = _request("POST", "/api/custom_component", token, json.dumps({"code": code}).encode())
            custom[resp["type"]] = resp["data"]
            print(f"  built template for {resp['type']}")
        _TEMPLATE_CACHE["custom"] = custom
    builtin, custom = _TEMPLATE_CACHE["builtin"], _TEMPLATE_CACHE["custom"]

    y, step = 200, 430
    chat_in = make_node("ChatInput", builtin["ChatInput"], 0, y, 300)
    if intake == "outlook":
        chat_in["data"]["node"]["template"]["input_value"]["value"] = "Check the underwriting inbox for new broker submissions."
        intake_node = make_node("UnderwritingMailboxIntake", custom["UnderwritingMailboxIntake"], step, y)
        intake_field = "trigger"
    else:
        chat_in["data"]["node"]["template"]["input_value"]["value"] = SAMPLE_EMAIL
        intake_node = make_node("UnderwritingEmailIntake", custom["UnderwritingEmailIntake"], step, y)
        intake_field = "email_message"
    intake = intake_node  # noqa: PLW0127 - reuse name below for wiring
    extractor = make_node("UnderwritingDocumentExtractor", custom["UnderwritingDocumentExtractor"], 2 * step, y)
    validator = make_node("UnderwritingValidationEngine", custom["UnderwritingValidationEngine"], 3 * step, y)
    router = make_node("UnderwritingDecisionRouter", custom["UnderwritingDecisionRouter"], 4 * step, y)
    rating = make_node("UnderwritingRatingEngine", custom["UnderwritingRatingEngine"], 5 * step, y)
    composer = make_node("UnderwritingQuoteComposer", custom["UnderwritingQuoteComposer"], 6 * step, y)
    chat_out = make_node("ChatOutput", builtin["ChatOutput"], 7 * step, y, 300)
    chat_out["data"]["node"]["template"]["sender_name"]["value"] = "Underwriting Agent"

    nodes = [chat_in, intake, extractor, validator, router, rating, composer, chat_out]
    edges = [
        make_edge(chat_in, "message", intake, intake_field),
        make_edge(intake, "case", extractor, "case"),
        make_edge(extractor, "extracted", validator, "extracted"),
        make_edge(validator, "validated", router, "validated"),
        make_edge(router, "decision", rating, "decision"),
        make_edge(rating, "rated", composer, "rated"),
        make_edge(composer, "response", chat_out, "input_value"),
    ]
    if with_llm:
        llm = make_node("RegistryModelComponent", builtin["RegistryModelComponent"], 2 * step, y + 620)
        nodes.append(llm)
        edges += [make_edge(llm, "model_output", extractor, "llm"), make_edge(llm, "model_output", composer, "llm")]

    suffix_name = {"chat": "", "outlook": " (Outlook live inbox)"}[intake_field == "trigger" and "outlook" or "chat"]
    name = "Email-to-Quote Underwriting Agent" + suffix_name + ("" if with_llm else " (no LLM)")
    source_desc = (
        "Reads the newest unread broker email with PDF attachments from the mailbox linked via the Outlook connector"
        if intake_field == "trigger"
        else "broker email + PDF attachments from the Playground (or bundled sample cases)"
    )
    return {
        "id": "email-to-quote-underwriting-agent" + ("-outlook" if intake_field == "trigger" else "") + ("" if with_llm else "-no-llm"),
        "name": name,
        "description": (
            f"AI-powered insurance underwriting & quotation: {source_desc} → document intelligence → "
            "field-level validation → underwriting decision → configurable rating → quote PDF and broker email "
            "(draft until approved; can reply through the Outlook mailbox). Group Medical Insurance demo."
        ),
        "icon": "FileText",
        "gradient": "2",
        "tags": ["insurance", "underwriting", "demo"],
        "is_component": False,
        "endpoint_name": None,
        "data": {"nodes": nodes, "edges": edges, "viewport": {"x": 40, "y": 60, "zoom": 0.45}},
    }


if __name__ == "__main__":
    tok = login()
    for with_llm, intake_kind, filename in (
        (True, "chat", "Email_to_Quote_Underwriting_Agent.json"),
        (False, "chat", "Email_to_Quote_Underwriting_Agent_no_llm.json"),
        (True, "outlook", "Email_to_Quote_Underwriting_Agent_outlook.json"),
    ):
        print(f"Building {filename} ...")
        flow = build(tok, with_llm=with_llm, intake=intake_kind)
        (HERE / filename).write_text(json.dumps(flow, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {HERE / filename} ({len(flow['data']['nodes'])} nodes, {len(flow['data']['edges'])} edges)")
    sys.exit(0)
