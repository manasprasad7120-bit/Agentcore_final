"""Live mailbox intake for the Email-to-Quote Underwriting Agent.

Reads the latest broker email from a mailbox linked through the product's
Outlook connector (Connectors page -> Outlook -> Link Mailbox), downloads the
PDF attachments in full via Microsoft Graph and builds the same underwriting
case object as the chat/sample intake, so the rest of the pipeline is unchanged.

Reuses the product's own connector helpers (token refresh, connector lookup)
from ``agentcore.components.tools.outlook_mail``.
"""

from __future__ import annotations

import base64
import hashlib
import html
import re
from pathlib import Path

from agentcore.custom.custom_node.node import Node
from agentcore.io import BoolInput, DropdownInput, IntInput, MessageInput, MessageTextInput, Output
from agentcore.schema.data import Data
from agentcore.schema.message import Message

ACCEPTED_EXTENSIONS = (".pdf", ".txt")


class UnderwritingMailboxIntake(Node):
    display_name = "1. Outlook Mailbox Intake (live)"
    description = (
        "Reads the newest (unread) broker email with PDF attachments from a mailbox linked via the Outlook "
        "connector, downloads the attachments in full and builds the underwriting case."
    )
    icon = "mail"
    name = "UnderwritingMailboxIntake"

    inputs = [
        MessageInput(
            name="trigger",
            display_name="Trigger (Chat Input)",
            info=(
                "Any chat message starts a mailbox check. Optional overrides inside the text: "
                "'subject: <words>', 'from: <address>', 'include read'."
            ),
            required=False,
        ),
        DropdownInput(
            name="connector",
            display_name="Outlook Connector",
            info="Outlook connector from the Connectors page (click refresh to load).",
            options=[],
            value="",
            refresh_button=True,
            real_time_refresh=True,
            combobox=True,
        ),
        MessageTextInput(
            name="account_email",
            display_name="Mailbox (linked account email)",
            info="Leave empty to use the first mailbox linked to the connector.",
            value="",
        ),
        MessageTextInput(name="folder", display_name="Mail folder", value="inbox", advanced=True),
        MessageTextInput(
            name="filter_sender",
            display_name="Only from sender",
            info="Optional sender address filter (e.g. the broker's mailbox).",
            value="",
        ),
        MessageTextInput(
            name="filter_subject",
            display_name="Subject contains",
            info="Optional subject keyword, e.g. 'Quote Request'.",
            value="",
        ),
        BoolInput(name="unread_only", display_name="Unread emails only", value=True),
        BoolInput(name="require_attachments", display_name="Require PDF attachments", value=True),
        BoolInput(
            name="mark_as_read",
            display_name="Mark the email as read after intake",
            value=True,
            info="Needs Mail.ReadWrite on the app registration.",
        ),
        IntInput(name="max_candidates", display_name="Emails to scan", value=10, advanced=True),
    ]

    outputs = [Output(display_name="Underwriting Case", name="case", method="build_case")]

    # ------------------------------------------------------------------ dropdown
    def update_build_config(self, build_config: dict, field_value: str, field_name: str | None = None):
        if field_name == "connector":
            try:
                from agentcore.components.tools.outlook_mail import _fetch_outlook_connectors

                options = _fetch_outlook_connectors()
                build_config["connector"]["options"] = options or []
                if build_config["connector"].get("value") not in options:
                    build_config["connector"]["value"] = options[0] if options else ""
            except Exception as exc:  # noqa: BLE001
                self.log(f"Could not list Outlook connectors: {exc}")
                build_config["connector"]["options"] = []
        return build_config

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _html_to_text(content: str) -> str:
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", content or "")
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()

    @staticmethod
    def _read_pdf_pages(path: str) -> list[dict]:
        pages: list[dict] = []
        try:
            from pypdf import PdfReader

            reader = PdfReader(path)
            pages = [{"page": i, "text": p.extract_text() or ""} for i, p in enumerate(reader.pages, start=1)]
            if any(p["text"].strip() for p in pages):
                return pages
        except Exception:  # noqa: BLE001
            pages = []
        try:
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

    def _overrides_from_trigger(self) -> tuple[str, str, bool | None]:
        text = ""
        if isinstance(self.trigger, Message):
            text = str(self.trigger.text or "")
        elif isinstance(self.trigger, str):
            text = self.trigger
        subject = re.search(r"subject\s*:\s*(.+)", text, re.I)
        sender = re.search(r"from\s*:\s*(\S+@\S+)", text, re.I)
        include_read = True if re.search(r"include\s+read|all\s+emails", text, re.I) else None
        return (
            subject.group(1).strip() if subject else "",
            sender.group(1).strip().strip(",.;") if sender else "",
            include_read,
        )

    @staticmethod
    def _case_dir(message_id: str) -> Path:
        digest = hashlib.sha1(message_id.encode("utf-8")).hexdigest()[:16]  # noqa: S324 - folder name only
        try:
            from agentcore.services.deps import get_storage_service

            root = Path(str(get_storage_service().data_dir))
        except Exception:  # noqa: BLE001
            root = Path.cwd()
        folder = root / "underwriting_inbox" / digest
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    # ------------------------------------------------------------------ main
    def build_case(self) -> Data:
        import httpx
        from agentcore.components.tools.outlook_mail import (
            GRAPH_BASE,
            _get_outlook_config,
            _odata_escape,
            _refresh_token_sync,
            _validate_path_segment,
        )

        if not self.connector:
            msg = "Select the Outlook connector on the node (click the refresh icon next to the dropdown)."
            raise ValueError(msg)
        parts = [p.strip() for p in str(self.connector).split("|")]
        connector_id = parts[3] if len(parts) >= 4 else parts[-1]
        config = _get_outlook_config(connector_id)
        if not config:
            msg = "Outlook connector not found. Refresh the dropdown and select it again."
            raise ValueError(msg)
        config["_connector_id"] = connector_id

        accounts = config.get("linked_accounts", [])
        if not accounts:
            msg = "No mailbox is linked to this connector. Use 'Link Mailbox' on the Connectors page first."
            raise ValueError(msg)
        wanted = (self.account_email or "").strip().lower()
        acct = next((a for a in accounts if a.get("email", "").lower() == wanted), None) if wanted else accounts[0]
        if acct is None:
            msg = f"Mailbox '{wanted}' is not linked. Linked: {', '.join(a.get('email', '') for a in accounts)}"
            raise ValueError(msg)
        access_token = _refresh_token_sync(config, acct)
        headers = {"Authorization": f"Bearer {access_token}"}

        subject_override, sender_override, include_read = self._overrides_from_trigger()
        filter_subject = subject_override or (self.filter_subject or "").strip()
        filter_sender = sender_override or (self.filter_sender or "").strip()
        unread_only = bool(self.unread_only) and include_read is None
        limit = max(int(self.max_candidates or 10), 1)

        folder = _validate_path_segment((self.folder or "inbox").strip(), "folder")
        url = f"{GRAPH_BASE}/me/mailFolders/{folder}/messages"
        select = "id,subject,from,toRecipients,receivedDateTime,bodyPreview,body,hasAttachments,isRead,internetMessageId,conversationId"
        params: dict[str, str] = {"$top": str(limit), "$select": select, "$orderby": "receivedDateTime desc"}
        filters = ["receivedDateTime ge 1970-01-01T00:00:00Z"]  # Graph needs the orderby property in $filter
        if unread_only:
            filters.append("isRead eq false")
        if filter_sender:
            filters.append(f"from/emailAddress/address eq '{_odata_escape(filter_sender)}'")
        if filter_subject:
            filters.append(f"contains(subject, '{_odata_escape(filter_subject)}')")
        if len(filters) > 1:
            params["$filter"] = " and ".join(filters)

        resp = httpx.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 401:
            headers["Authorization"] = f"Bearer {_refresh_token_sync(config, acct, force=True)}"
            resp = httpx.get(url, headers=headers, params=params, timeout=30)
        client_side = False
        if resp.status_code in (400, 501) and "$filter" in params:  # consumer mailboxes may reject $filter
            params = {k: v for k, v in params.items() if k != "$filter"}
            params["$top"] = str(min(limit * 5, 50))
            resp = httpx.get(url, headers=headers, params=params, timeout=30)
            client_side = True
        if resp.status_code != 200:
            msg = f"Microsoft Graph error {resp.status_code} while listing mail: {resp.text[:300]}"
            raise ValueError(msg)

        candidates = resp.json().get("value", [])
        if client_side:
            def keep(m: dict) -> bool:
                addr = (m.get("from", {}).get("emailAddress", {}).get("address") or "").lower()
                return (
                    (not unread_only or not m.get("isRead"))
                    and (not filter_sender or addr == filter_sender.lower())
                    and (not filter_subject or filter_subject.lower() in (m.get("subject") or "").lower())
                )
            candidates = [m for m in candidates if keep(m)]
        if self.require_attachments:
            candidates = [m for m in candidates if m.get("hasAttachments")]
        if not candidates:
            msg = (
                f"No {'unread ' if unread_only else ''}email{' with attachments' if self.require_attachments else ''} "
                f"found in '{folder}' of {acct.get('email')}"
                + (f" matching subject '{filter_subject}'" if filter_subject else "")
                + (f" from {filter_sender}" if filter_sender else "")
                + ". Send the broker email to this mailbox and run again."
            )
            raise ValueError(msg)

        message = candidates[0]
        message_id = message["id"]
        from_info = message.get("from", {}).get("emailAddress", {})
        body = message.get("body", {}) or {}
        body_text = self._html_to_text(body.get("content", "")) if (body.get("contentType") or "").lower() == "html" else (body.get("content") or message.get("bodyPreview") or "")

        # Attachments (full content, not truncated)
        att_resp = httpx.get(f"{GRAPH_BASE}/me/messages/{message_id}/attachments", headers=headers, timeout=60)
        if att_resp.status_code != 200:
            msg = f"Microsoft Graph error {att_resp.status_code} while fetching attachments: {att_resp.text[:300]}"
            raise ValueError(msg)
        case_dir = self._case_dir(message_id)
        attachments: list[dict] = []
        skipped: list[str] = []
        for att in att_resp.json().get("value", []):
            if att.get("@odata.type") != "#microsoft.graph.fileAttachment":
                continue
            name = re.sub(r"[^A-Za-z0-9._ -]+", "_", att.get("name") or "attachment")
            if not name.lower().endswith(ACCEPTED_EXTENSIONS):
                skipped.append(name)
                continue
            content = att.get("contentBytes")
            if not content:  # large attachments: fetch raw bytes
                raw_resp = httpx.get(f"{GRAPH_BASE}/me/messages/{message_id}/attachments/{att['id']}/$value", headers=headers, timeout=120)
                raw = raw_resp.content if raw_resp.status_code == 200 else b""
            else:
                raw = base64.b64decode(content)
            if not raw:
                skipped.append(name)
                continue
            path = case_dir / name
            path.write_bytes(raw)
            pages = self._read_pdf_pages(str(path)) if name.lower().endswith(".pdf") else [{"page": 1, "text": raw.decode("utf-8", errors="replace")}]
            text = "\n".join(p["text"] for p in pages)
            attachments.append(
                {
                    "name": name,
                    "path": str(path),
                    "doc_type": self._classify(name, text),
                    "page_count": len(pages),
                    "pages": pages,
                    "text": text,
                    "chars": len(text),
                    "size_bytes": len(raw),
                }
            )
        if not attachments:
            msg = f"The email '{message.get('subject')}' has no PDF/TXT attachments (skipped: {', '.join(skipped) or 'none'})."
            raise ValueError(msg)

        read_note = "not marked"
        if self.mark_as_read:
            patch = httpx.patch(f"{GRAPH_BASE}/me/messages/{message_id}", headers={**headers, "Content-Type": "application/json"}, json={"isRead": True}, timeout=30)
            read_note = "marked as read" if patch.status_code in (200, 204) else f"mark-as-read failed ({patch.status_code})"

        sender_address = (from_info.get("address") or "").lower()
        case = {
            "case_id": f"UW-{hashlib.sha1(message_id.encode()).hexdigest()[:6].upper()}",  # noqa: S324
            "intake_source": f"outlook:{acct.get('email')}",
            "email": {
                "from": sender_address,
                "from_name": from_info.get("name") or "",
                "to": ", ".join(r.get("emailAddress", {}).get("address", "") for r in message.get("toRecipients", [])),
                "subject": message.get("subject") or "",
                "received": message.get("receivedDateTime") or "",
                "body": body_text,
            },
            "attachments": attachments,
            "source_mailbox": {
                "connector_id": connector_id,
                "account_email": acct.get("email"),
                "message_id": message_id,
                "internet_message_id": message.get("internetMessageId"),
                "conversation_id": message.get("conversationId"),
                "from_address": sender_address,
                "subject": message.get("subject") or "",
            },
            "audit_trail": [
                {
                    "step": "intake",
                    "detail": (
                        f"Read email '{message.get('subject')}' from {sender_address} received {message.get('receivedDateTime')} "
                        f"via Outlook connector ({acct.get('email')}); {len(attachments)} attachment(s) downloaded, {read_note}"
                        + (f"; skipped non-PDF: {', '.join(skipped)}" if skipped else "")
                    ),
                    "documents": [a["name"] for a in attachments],
                }
            ],
        }
        self.status = (
            f"{message.get('subject')} — from {sender_address}\n"
            + "\n".join(f"- {a['name']} ({a['doc_type']}, {a['page_count']} p, {a['chars']} chars)" for a in attachments)
        )
        return Data(data=case, text_key="intake_source")
