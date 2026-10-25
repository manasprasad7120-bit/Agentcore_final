"""Keyword-based Outlook intent router (legacy / backward-compat).

Kept so the `/api/outlook-orch/intent` frontend precheck endpoint keeps
working. The main orchestrator chat flow uses the MiBuddy-ported LLM
classifier in `agentcore.services.mibuddy.outlook_agent` instead.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from agentcore.services.outlook_orch.outlook_service import OutlookService
from agentcore.services.outlook_orch.token_manager import outlook_token_manager

logger = logging.getLogger(__name__)

_CALENDAR_PAT = re.compile(
    r"\b(calendar|meeting(?:s)?|appointment(?:s)?|schedule|events?)\b",
    re.IGNORECASE,
)
_EMAIL_SEARCH_PAT = re.compile(
    r"\b(?:search|find|look\s+for)\b.*\b(?:email|mail|message)s?\b",
    re.IGNORECASE,
)
_EMAIL_READ_PAT = re.compile(
    r"("
    r"(?:show|list|get|fetch|check|read|see|view)\b(?:\s+\w+){0,3}\s+"
    r"(?:email|mail|inbox|message)s?"
    r"|"
    r"(?:recent|latest|unread|new)\s+(?:email|mail|message)s?"
    r"|"
    r"how\s+many\s+(?:email|mail|message)s?"
    r"|"
    r"\binbox\b"
    r")",
    re.IGNORECASE,
)


class OutlookIntent:
    def __init__(self, kind: str, markdown: str) -> None:
        self.kind = kind
        self.markdown = markdown


def _format_email_list(emails: List[Dict[str, Any]], scope: str) -> str:
    if not emails:
        return "No emails found."
    lines = [
        f"Here are your **{len(emails)}** emails from {scope}:",
        "",
        "| # | Sender | Subject | Received | Status |",
        "|---|---|---|---|---|",
    ]
    months = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    for i, e in enumerate(emails[:10], 1):
        sender = (
            e.get("from", {}).get("emailAddress", {}).get("name")
            or e.get("from", {}).get("emailAddress", {}).get("address")
            or "Unknown"
        )
        subj = e.get("subject") or "No subject"
        iso = e.get("receivedDateTime", "")
        try:
            _y, m, d = iso[:10].split("-")
            received = f"{months[int(m) - 1]} {int(d)}"
        except Exception:
            received = iso[:10]
        status = "🟢 Read" if e.get("isRead", True) else "🔵 Unread"
        preview = (e.get("bodyPreview") or "").strip().replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:117] + "..."
        cell = f"**{subj}**"
        if preview:
            cell += f"<br/>{preview}"
        lines.append(f"| {i} | {sender} | {cell} | {received} | {status} |")
    return "\n".join(lines)


def handle_outlook_intent(user_id: str, message: str) -> Optional[OutlookIntent]:
    if not message or not message.strip():
        return None
    msg = message
    if _CALENDAR_PAT.search(msg):
        intent = "calendar"
    elif _EMAIL_SEARCH_PAT.search(msg):
        intent = "email_search"
    elif _EMAIL_READ_PAT.search(msg):
        intent = "email_read"
    else:
        return None

    token = outlook_token_manager.get_token(user_id)
    if not token:
        return OutlookIntent(
            "error",
            "Your Outlook account isn't connected. Click the **+** menu → "
            "**Outlook Connector** to sign in.",
        )
    try:
        if intent == "calendar":
            start = datetime.utcnow().isoformat() + "Z"
            end = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
            events = OutlookService.get_calendar_events(
                token, start_date=start, end_date=end, top=20,
            )
            if not events:
                return OutlookIntent("calendar", "No upcoming events.")
            rows = ["| Time | Title |", "|---|---|"]
            for ev in events:
                s = ev.get("start", {}).get("dateTime", "")[:16].replace("T", " ")
                e_ = ev.get("end", {}).get("dateTime", "")[11:16]
                t_ = (ev.get("subject") or "No title").replace("|", "\\|")
                rows.append(f"| {s} – {e_} | {t_} |")
            return OutlookIntent("calendar", "\n".join(rows))

        if intent == "email_search":
            q = re.sub(
                r"\b(find|search|look\s+for|emails?|mails?|messages?|"
                r"about|for|from|the|me|my)\b",
                "", msg, flags=re.IGNORECASE,
            ).strip() or msg
            emails = OutlookService.search_emails(token, q, top=10)
            if emails is None:
                return OutlookIntent("error", "_Failed to search emails._")
            return OutlookIntent(
                "email_search",
                _format_email_list(emails, f"search for '{q}'"),
            )

        emails = OutlookService.get_emails(token, top=10, folder="inbox")
        if emails is None:
            return OutlookIntent("error", "_Failed to retrieve emails._")
        return OutlookIntent("email_list", _format_email_list(emails, "your inbox"))
    except Exception as e:
        logger.error(f"[outlook_intent_router] {e}", exc_info=True)
        return OutlookIntent("error", f"_Outlook error: {e}_")
