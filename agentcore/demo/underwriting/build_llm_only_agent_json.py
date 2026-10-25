"""Assemble the Email-to-Quote Underwriting Agent from BUILT-IN components only.

No custom components, no OCR node: the LLM reads the email and the attachment text
directly. Two variants are written:

  Email_to_Quote_Underwriting_Agent.json        Chat Input -> Outlook Mail (live mailbox) -> Prompt Template
                                                -> Large Language Model -> Chat Output
  Email_to_Quote_Underwriting_Agent_files.json  Chat Input (email text) + File (uploaded PDFs) -> Prompt Template
                                                -> Large Language Model -> Chat Output

Node templates are taken from the running backend (GET /api/all) so they match the product.
Usage (backend running, credentials from .env or env vars):
    python demo/underwriting/build_llm_only_agent_json.py
"""

from __future__ import annotations

import gzip
import json
import os
import random
import re
import string
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = os.getenv("AGENTCORE_API", "http://127.0.0.1:7860").rstrip("/")

SYSTEM_MESSAGE = (
    "You are the underwriting assistant of a group health insurer. You read broker submissions (the email and the "
    "text of its PDF attachments) and produce a complete, auditable underwriting review. Never invent figures: every "
    "number you report must come from the documents or from the rating table you are given. If a value is missing, "
    "say 'not found'. Be precise, structured and concise."
)

PROMPT_TEMPLATE = (HERE / "underwriting_prompt.md").read_text(encoding="utf-8")

SAMPLE_EMAIL = (
    "Subject: Group Medical Insurance — Renewal Quote Request — ABC Technologies\n\n"
    "Dear Underwriting Team,\n\n"
    "Please find attached the employee census, current policy details, claims experience report and company "
    "information for our client's group medical insurance renewal.\n\n"
    "Kindly review the information and share your proposed premium quotation and coverage terms.\n\n"
    "Regards,\nCorporate Insurance Broker"
)


def _env_from_dotenv(key: str) -> str:
    if os.getenv(key):
        return os.getenv(key, "")
    env_file = ROOT / ".env"
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
    if raw[:2] == b"\x1f\x8b":
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
    for key, default in (("edited", False), ("frozen", False), ("hidden", False), ("minimized", False), ("pinned", False)):
        node.setdefault(key, default)
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


def prompt_variable_field(name: str) -> dict:
    """Shape of a Prompt Template variable field, as the product's UI creates it."""
    return {
        "advanced": False,
        "display_name": name,
        "dynamic": False,
        "field_type": "str",
        "fileTypes": [],
        "file_path": "",
        "info": "",
        "input_types": ["Message"],
        "list": False,
        "load_from_db": False,
        "multiline": True,
        "name": name,
        "placeholder": "",
        "required": False,
        "show": True,
        "title_case": False,
        "type": "str",
        "value": "",
    }


def make_prompt_node(frontend_node: dict, template_text: str, x: float, y: float) -> dict:
    node = make_node("Prompt Template", frontend_node, x, y, 380)
    tmpl = node["data"]["node"]["template"]
    tmpl["template"]["value"] = template_text
    variables = list(dict.fromkeys(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", template_text)))
    for var in variables:
        tmpl[var] = prompt_variable_field(var)
    node["data"]["node"]["custom_fields"] = {"template": variables}
    return node


def find_template(catalogue: dict, name: str) -> dict:
    for comps in catalogue.values():
        if name in comps:
            return comps[name]
        for comp_name, tmpl in comps.items():
            if tmpl.get("display_name") == name:
                return tmpl
    msg = f"Component '{name}' not found in /api/all"
    raise KeyError(msg)


def build(catalogue: dict, *, variant: str) -> dict:
    y, step = 220, 440
    chat_in = make_node("ChatInput", find_template(catalogue, "ChatInput"), 0, y, 300)
    prompt = make_prompt_node(find_template(catalogue, "Prompt Template"), PROMPT_TEMPLATE, 2 * step, y)
    llm = make_node("RegistryModelComponent", find_template(catalogue, "RegistryModelComponent"), 3 * step, y)
    llm["data"]["node"]["template"]["system_message"]["value"] = SYSTEM_MESSAGE
    chat_out = make_node("ChatOutput", find_template(catalogue, "ChatOutput"), 4 * step, y, 300)
    chat_out["data"]["node"]["template"]["sender_name"]["value"] = "Underwriting Agent"

    nodes = [chat_in, prompt, llm, chat_out]
    edges = [
        make_edge(prompt, "prompt", llm, "input_value"),
        make_edge(llm, "text_output", chat_out, "input_value"),
    ]

    if variant == "outlook":
        chat_in["data"]["node"]["template"]["input_value"]["value"] = (
            "Review the newest broker submission in the underwriting inbox and prepare the quotation or clarification."
        )
        outlook = make_node("OutlookMail", find_template(catalogue, "OutlookMail"), step, y + 40, 360)
        ot = outlook["data"]["node"]["template"]
        ot["max_results"]["value"] = 1
        ot["folder"]["value"] = "inbox"
        if "attachment_max_chars" in ot:
            ot["attachment_max_chars"]["value"] = 60000
        nodes.append(outlook)
        edges += [
            make_edge(chat_in, "message", prompt, "instruction"),
            make_edge(outlook, "read_mail", prompt, "email"),
        ]
        name, fid = "Email-to-Quote Underwriting Agent", "email-to-quote-underwriting-agent"
        source = "the newest broker email (with attachment text) read through the Outlook connector"
    else:
        chat_in["data"]["node"]["template"]["input_value"]["value"] = SAMPLE_EMAIL
        files = make_node("File", find_template(catalogue, "File"), step, y + 420, 360)
        nodes.append(files)
        edges += [
            make_edge(chat_in, "message", prompt, "email"),
            make_edge(files, "message", prompt, "documents"),
        ]
        name, fid = "Email-to-Quote Underwriting Agent (file upload)", "email-to-quote-underwriting-agent-files"
        source = "the broker email typed in the chat plus PDFs uploaded on the File node"

    return {
        "id": fid,
        "name": name,
        "description": (
            f"LLM-driven insurance underwriting & quotation built from standard components: {source} → Prompt "
            "Template (extraction, field-level validation, decision rules, rating table, broker email) → Large "
            "Language Model → Chat Output. Group Medical Insurance demo."
        ),
        "icon": "FileText",
        "gradient": "2",
        "tags": ["insurance", "underwriting", "demo"],
        "is_component": False,
        "endpoint_name": None,
        "data": {"nodes": nodes, "edges": edges, "viewport": {"x": 40, "y": 40, "zoom": 0.55}},
    }


if __name__ == "__main__":
    token = login()
    catalogue = _request("GET", "/api/all", token)
    for variant, filename in (("outlook", "Email_to_Quote_Underwriting_Agent.json"), ("files", "Email_to_Quote_Underwriting_Agent_files.json")):
        flow = build(catalogue, variant=variant)
        (HERE / filename).write_text(json.dumps(flow, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {HERE / filename} ({len(flow['data']['nodes'])} nodes, {len(flow['data']['edges'])} edges)")
    sys.exit(0)
