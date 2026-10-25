"""Email & attachment intake for the Email-to-Quote Underwriting Agent.

Accepts the broker email (text + attached PDFs) from the Playground, from files
uploaded on the node, or from a mock inbox folder, and produces one
"underwriting case" Data object with the email and the extracted text of every
attachment (page by page) for the downstream extraction / validation steps.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from agentcore.custom.custom_node.node import Node
from agentcore.io import DropdownInput, FileInput, MessageInput, Output, StrInput
from agentcore.schema.data import Data
from agentcore.schema.message import Message

SAMPLE_CASES = {
    "Clean application (quote expected)": "case_clean",
    "Conflicting application (clarification expected)": "case_conflicting",
}


class UnderwritingEmailIntake(Node):
    display_name = "1. Email & Attachment Intake"
    description = (
        "Reads the broker email and its PDF attachments (Playground attachments, uploaded files or a mock inbox "
        "folder) and builds the underwriting case object."
    )
    icon = "mail"
    name = "UnderwritingEmailIntake"

    inputs = [
        MessageInput(
            name="email_message",
            display_name="Inbound Email (Chat Input)",
            info="The broker email: text is the email body, attached files are the PDF attachments.",
            required=False,
        ),
        FileInput(
            name="attachments",
            display_name="PDF Attachments",
            file_types=["pdf", "txt"],
            info="Optional: attach the broker's PDFs here instead of in the chat.",
            is_list=True,
            required=False,
            advanced=False,
        ),
        StrInput(
            name="inbox_folder",
            display_name="Mock Inbox Folder",
            info="Optional folder containing email.txt and the PDF attachments (mock email connector).",
            value="",
            advanced=True,
        ),
        DropdownInput(
            name="sample_case",
            display_name="Bundled Sample Case",
            info=(
                "Use one of the bundled synthetic cases (demo/underwriting/samples) when no files are provided. "
                "Leave empty to require real attachments."
            ),
            options=["", *SAMPLE_CASES.keys()],
            value="Conflicting application (clarification expected)",
        ),
    ]

    outputs = [
        Output(display_name="Underwriting Case", name="case", method="build_case"),
    ]

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _read_pdf_pages(path: str) -> list[dict]:
        pages: list[dict] = []
        try:
            from pypdf import PdfReader

            reader = PdfReader(path)
            for idx, page in enumerate(reader.pages, start=1):
                pages.append({"page": idx, "text": page.extract_text() or ""})
            if any(p["text"].strip() for p in pages):
                return pages
        except Exception:  # noqa: BLE001
            pages = []
        try:  # fallback: PyMuPDF (handles more layouts)
            import fitz  # type: ignore

            with fitz.open(path) as doc:
                pages = [{"page": i + 1, "text": p.get_text()} for i, p in enumerate(doc)]
        except Exception:  # noqa: BLE001
            pass
        return pages

    @staticmethod
    def _classify(name: str, text: str) -> str:
        n, t = name.lower(), text.lower()
        if "census" in n or "employee census" in t:
            return "census"
        if "claim" in n or "claims experience" in t:
            return "claims"
        if "policy" in n or "policy number" in t:
            return "policy"
        if "application" in n or "company application" in t or "requested sum insured" in t:
            return "application"
        return "other"

    def _resolve_file(self, raw) -> str | None:
        if raw is None:
            return None
        path = str(getattr(raw, "path", raw)).strip()
        if not path:
            return None
        if os.path.isabs(path) and os.path.exists(path):
            return path
        if os.path.exists(path):
            return os.path.abspath(path)
        if "/" in path or "\\" in path:
            try:
                full = self.get_full_path(path.replace("\\", "/"))
                if os.path.exists(full):
                    return full
            except Exception:  # noqa: BLE001
                pass
        try:
            from agentcore.services.deps import get_storage_service

            root = Path(str(get_storage_service().data_dir))
            for candidate in (root / path, *root.rglob(Path(path).name)):
                if candidate.exists():
                    return str(candidate)
        except Exception:  # noqa: BLE001
            pass
        return None

    @staticmethod
    def _repo_sample_dir(case_folder: str) -> Path | None:
        # Walk up from the storage dir / this file to find demo/underwriting/samples/<case>
        candidates: list[Path] = []
        try:
            from agentcore.services.deps import get_storage_service

            root = Path(str(get_storage_service().data_dir))
            candidates.extend([root, *root.parents])
        except Exception:  # noqa: BLE001
            pass
        candidates.extend([Path.cwd(), *Path.cwd().parents])
        for base in candidates:
            p = base / "demo" / "underwriting" / "samples" / case_folder
            if p.exists():
                return p
        env = os.getenv("UNDERWRITING_SAMPLES_DIR")
        if env and (Path(env) / case_folder).exists():
            return Path(env) / case_folder
        return None

    @staticmethod
    def _parse_email(text: str) -> dict:
        email = {"from": "", "to": "", "subject": "", "body": text or ""}
        header_match = re.match(r"(?s)^(.*?)\n\s*\n(.*)$", text or "")
        header_block, body = (header_match.groups() if header_match else ("", text or ""))
        found_header = False
        for line in header_block.splitlines():
            m = re.match(r"^(From|To|Subject)\s*:\s*(.*)$", line.strip(), re.I)
            if m:
                email[m.group(1).lower()] = m.group(2).strip()
                found_header = True
        if found_header:
            email["body"] = body.strip()
        else:
            m = re.search(r"^Subject\s*:\s*(.*)$", text or "", re.I | re.M)
            if m:
                email["subject"] = m.group(1).strip()
        return email

    # ------------------------------------------------------------------ main
    def build_case(self) -> Data:
        email_text = ""
        file_paths: list[str] = []

        msg = self.email_message
        if isinstance(msg, Message):
            email_text = str(msg.text or "")
            for f in msg.files or []:
                resolved = self._resolve_file(f)
                if resolved:
                    file_paths.append(resolved)
        elif isinstance(msg, str):
            email_text = msg

        for f in self.attachments or []:
            resolved = self._resolve_file(f)
            if resolved and resolved not in file_paths:
                file_paths.append(resolved)

        source = "playground"
        folder = (self.inbox_folder or "").strip()
        if not file_paths and folder and Path(folder).exists():
            source = f"inbox folder {folder}"
            file_paths = sorted(str(p) for p in Path(folder).glob("*.pdf"))
            email_file = Path(folder) / "email.txt"
            if not email_text.strip() and email_file.exists():
                email_text = email_file.read_text(encoding="utf-8", errors="replace")

        if not file_paths and self.sample_case:
            case_dir = self._repo_sample_dir(SAMPLE_CASES.get(self.sample_case, ""))
            if case_dir:
                source = f"bundled sample '{self.sample_case}'"
                file_paths = sorted(str(p) for p in case_dir.glob("*.pdf"))
                email_file = case_dir / "email.txt"
                if not email_text.strip() and email_file.exists():
                    email_text = email_file.read_text(encoding="utf-8", errors="replace")

        if not file_paths:
            msg_text = (
                "No PDF attachments found. Attach the broker's PDFs in the chat, upload them on this node, "
                "set a mock inbox folder, or select a bundled sample case."
            )
            raise ValueError(msg_text)

        attachments = []
        for path in file_paths:
            pages = self._read_pdf_pages(path) if path.lower().endswith(".pdf") else [
                {"page": 1, "text": Path(path).read_text(encoding="utf-8", errors="replace")}
            ]
            text = "\n".join(p["text"] for p in pages)
            attachments.append(
                {
                    "name": Path(path).name,
                    "path": path,
                    "doc_type": self._classify(Path(path).name, text),
                    "page_count": len(pages),
                    "pages": pages,
                    "text": text,
                    "chars": len(text),
                }
            )

        case = {
            "case_id": f"UW-{abs(hash(email_text + ''.join(file_paths))) % 10**6:06d}",
            "intake_source": source,
            "email": self._parse_email(email_text),
            "attachments": attachments,
            "audit_trail": [
                {
                    "step": "intake",
                    "detail": f"{len(attachments)} attachment(s) ingested from {source}",
                    "documents": [a["name"] for a in attachments],
                }
            ],
        }
        summary = "\n".join(
            f"- {a['name']} ({a['doc_type']}, {a['page_count']} page(s), {a['chars']} chars)" for a in attachments
        )
        self.status = f"Case {case['case_id']} from {source}\n{summary}"
        return Data(data=case, text_key="intake_source")
