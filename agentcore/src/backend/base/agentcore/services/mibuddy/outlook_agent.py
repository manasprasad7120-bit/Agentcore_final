
"""
Outlook Agent - Handles email and calendar queries using Microsoft Graph API
Intents handled:
- read_emails    : Show recent emails
- search_emails  : Search for specific emails
- get_calendar   : Show calendar events
- reply_email    : Generate a clean email reply draft (structured output)
- compose_email  : Compose a new email draft (structured output)
Reply / compose responses embed a :::email_draft{...}::: block that the frontend
parses to render a proper Email Draft card with a pre-filled "Draft in Outlook" button.
"""
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Sequence, Tuple
# ── IMPORTS REDIRECTED FOR AGENTCORE ─────────────────────────────────
# Every line below this block is byte-for-byte identical to the MiBuddy
# original (backend/agents/outlook_agent.py). Only these 3 import paths
# differ because the same classes live under different module paths in
# agentcore. Shim for AgentState / AzureAIFoundryLLM lives in
# `_outlook_agent_deps.py` next to this file.
from agentcore.services.mibuddy._outlook_agent_deps import (  # noqa: F401
    AgentState, AzureAIFoundryLLM, get_message_content, get_message_role,
)
from agentcore.services.outlook_orch.outlook_service import (
    OutlookService, OutlookTokenExpiredError,
)
logger = logging.getLogger(__name__)
# ── Draft marker ──────────────────────────────────────────────────────────────
_DRAFT_START = ":::email_draft"
_DRAFT_END = ":::"

def build_email_draft_block(to: str, to_name: str, subject: str, body: str) -> str:
    """Embed structured email-draft data as a detectable marker in the response."""
    payload = json.dumps(
        {"to": to, "to_name": to_name, "subject": subject, "body": body},
        ensure_ascii=False,
    )
    return f"{_DRAFT_START}\n{payload}\n{_DRAFT_END}"

def strip_markdown(text: str) -> str:
    """Remove common markdown syntax for a plain-text email body."""
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^-{3,}$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-*+]\s+', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'`+([^`]+)`+', r'\1', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# Preambles the LLM sometimes adds despite strict instructions
_PREAMBLE_RE = re.compile(
    r'^(sure[!,.]?\s*|certainly[!,.]?\s*|of course[!,.]?\s*|'
    r'here(?:\'s| is) (?:a |the |your )?(?:draft(?:ed)?|reply|email)[:\s]*)',
    re.IGNORECASE,
)

def _remove_preamble(text: str) -> str:
    while True:
        cleaned = _PREAMBLE_RE.sub('', text).lstrip()
        if cleaned == text:
            break
        text = cleaned
    return text

def _safe_call(fn, *args, **kwargs):
    """Wrap an OutlookService call, return None on any exception (except token expiration)."""
    try:
        return fn(*args, **kwargs)
    except OutlookTokenExpiredError:
        raise  
    except Exception as e:
        logger.error(f"OutlookService {fn.__name__} failed: {e}")
        return None
def _format_date(dt: datetime) -> str:
    """Cross-platform date formatting without leading zeros."""
    return dt.strftime("%A, %B {day}, %Y").replace("{day}", str(dt.day))
def _format_short_date(dt: datetime) -> str:
    """Cross-platform short date formatting."""
    return dt.strftime("%b {day}").replace("{day}", str(dt.day))

def _parse_email_date_filter(date_filter: str) -> Tuple[Optional[str], Optional[str], str]:
    """
    Parse date_filter string into ISO datetime range for Graph API.

    Args:
        date_filter: "today", "yesterday", "this_week", "last_week",
                     "this_month", "last_month", "last_N_days", or "YYYY-MM-DD"

    Returns:
        (received_after_utc_iso, received_before_utc_iso, human_readable_label)
    """
    import re as regex_modules
    from datetime import timezone as _tz

    IST = _tz(timedelta(hours=5, minutes=30))

    # "Today" as seen in IST — midnight at start of current IST calendar day
    now_ist = datetime.now(IST)
    today_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

    def _to_utc_iso(dt_ist: datetime) -> str:
        """Convert an IST-aware datetime to a UTC ISO string for Graph API."""
        return dt_ist.astimezone(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if date_filter == "today":
        start = today_ist
        end   = today_ist + timedelta(days=1)
        label = "today"
    elif date_filter == "yesterday":
        start = today_ist - timedelta(days=1)
        end   = today_ist
        label = "yesterday"
    elif date_filter == "this_week":
        start = today_ist - timedelta(days=today_ist.weekday())
        end   = today_ist + timedelta(days=1)
        label = "this week"
    elif date_filter == "last_week":
        this_monday_ist = today_ist - timedelta(days=today_ist.weekday())
        start = this_monday_ist - timedelta(days=7)
        end   = this_monday_ist
        label = "last week"
    elif date_filter == "this_month":
        start = today_ist.replace(day=1)
        end   = today_ist + timedelta(days=1)
        label = "this month"
    elif date_filter == "last_month":
        first_of_this_month = today_ist.replace(day=1)
        end   = first_of_this_month
        start = (first_of_this_month - timedelta(days=1)).replace(day=1)
        label = "last month"
    elif date_filter.startswith("last_") and date_filter.endswith("_days"):
        match = regex_modules.match(r"last_(\d+)_days", date_filter)
        if match:
            n_days = int(match.group(1))
            start = today_ist - timedelta(days=n_days)
            end   = today_ist + timedelta(days=1)
            label = f"the last {n_days} days"
        else:
            start = today_ist
            end   = today_ist + timedelta(days=1)
            label = "today"
    elif regex_modules.match(r"\d{4}-\d{2}-\d{2}", date_filter):
        try:
            naive = datetime.strptime(date_filter, "%Y-%m-%d")
            start = naive.replace(tzinfo=IST)
            end   = start + timedelta(days=1)
            label = _format_date(naive)
        except ValueError:
            start = today_ist
            end   = today_ist + timedelta(days=1)
            label = "today"
    else:
        start = today_ist
        end   = today_ist + timedelta(days=1)
        label = "today"

    start_utc = _to_utc_iso(start)
    end_utc   = _to_utc_iso(end)
    logger.info(
        f"[_parse_email_date_filter] date_filter='{date_filter}' "
        f"-> IST [{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}] "
        f"-> UTC [{start_utc} to {end_utc}] label='{label}'"
    )
    return start_utc, end_utc, label

def _parse_calendar_date(query: str, llm) -> Tuple[Optional[str], Optional[str], str]:
    """
    Parse date expressions from user query using LLM.
    Returns: (start_date_iso, end_date_iso, human_readable_label)
    """
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    today_str = _format_date(today)
    today_weekday = today.strftime("%A")
    
    date_prompt = f"""Today is {today_str} (a {today_weekday}).
User query: "{query}"
Parse the date the user is asking about. Return ONLY valid JSON:
{{
  "year": 2026,
  "month": 3,
  "day": 4,
  "is_range": false
}}
If the user asks for a week/range, set "is_range": true and provide "end_month" and "end_day".
If unclear, ask the user to explicitely give the dates or range for clarity. Do NOT assume a date if it's not clear from the query."""
    
    try:
        raw = llm.complete(date_prompt).text.strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        date_data = json.loads(raw)
        
        year = int(date_data.get("year", today.year))
        month = int(date_data.get("month", today.month))
        day = int(date_data.get("day", today.day))
        
        target_date = datetime(year, month, day, 0, 0, 0)
        
        if date_data.get("is_range"):
            end_month = int(date_data.get("end_month", month))
            end_day = int(date_data.get("end_day", day))
            end_date_obj = datetime(year, end_month, end_day, 23, 59, 59)
            label = f"{_format_short_date(target_date)} - {_format_short_date(end_date_obj)}"
        else:
            end_date_obj = target_date + timedelta(days=1)
            label = _format_date(target_date)
        
        return target_date.isoformat() + "Z", end_date_obj.isoformat() + "Z", label
        
    except Exception as e:
        logger.warning(f"Date parsing failed: {e}, defaulting to next 7 days")
        start = today
        end = today + timedelta(days=7)
        return start.isoformat() + "Z", end.isoformat() + "Z", "the upcoming week"
async def outlook_agent_node(state: AgentState) -> AgentState:
    """Process Outlook-related queries: emails, calendar, reply drafts, compose."""
    logger.info("Outlook Agent: Starting")
    try:
        # ── Retrieve user query ────────────────────────────────────────────────
        # [agentcore] shim replaces MiBuddy helper: from backend.agents.utils import get_message_content
        user_query = (
            get_message_content(state["messages"][-1]) if state["messages"] else ""
        )
        # ── Access token ───────────────────────────────────────────────────────
        from agentcore.services.outlook_orch.token_manager import outlook_token_manager
        user_id = state.get("user_id")
        # Prefer the token passed through state (from the encrypted cookie)
        # so multi-pod K8s deployments work. Fall back to the pod-local
        # token manager for single-instance deployments.
        access_token = state.get("access_token") or (
            outlook_token_manager.get_token(user_id) if user_id else None
        )
        if not access_token:
            if outlook_token_manager.was_token_expired(user_id):
                state["final_response"] = (
                    "Your Outlook session has expired.\n\n"
                    "**To reconnect:**\n"
                    "1. Click the **+** button → **Outlook Connector**\n"
                    "2. If it's already toggled on, switch it **off** then back **on** to re-authenticate\n\n"
                    "Sessions last approximately 1 hour for security reasons."
                )
            else:
                state["final_response"] = (
                    "Your Outlook account isn't connected, or your previous session may have expired.\n\n"
                    "**To connect / reconnect:**\n"
                    "1. Click the **+** button → **Outlook Connector**\n"
                    "2. If it's already toggled on, switch it **off** then back **on** to re-authenticate\n"
                    "3. Sign in with your Microsoft account and grant the required permissions\n\n"
                    "Once connected I can read emails, check your calendar, and draft replies."
                )
            return state
        logger.info(f"Token retrieved for user: {user_id}")
        # ── Classify intent ────────────────────────────────────────────────────
        llm = AzureAIFoundryLLM("gpt-5.2")
        intent_prompt = f"""You are an Outlook assistant intent classifier.
User query: "{user_query}"
Classify into exactly one of:
1. "read_emails"   – user wants recent / latest emails, including date-based requests like "emails today", "emails this week", "show my inbox"
2. "search_emails" – user wants to find specific emails by a concrete keyword, sender name, or subject phrase (NOT date/time words like today, yesterday, this week)
3. "get_calendar"  – user wants upcoming meetings or calendar events
4. "reply_email"   – user wants to draft / generate a reply to a specific email
5. "compose_email" – user wants to write a new email to someone
EXAMPLES:
- "show my emails"                          → read_emails   (confidence: 0.99, date_filter: "today")
- "emails from today"                       → read_emails   (confidence: 0.99, date_filter: "today")
- "show me yesterday's emails"              → read_emails   (confidence: 0.99, date_filter: "yesterday")
- "find John's invoice email"               → search_emails (confidence: 0.95)
- "reply to Sarah's email about project"    → reply_email   (confidence: 0.95)
- "what meetings do I have tomorrow"        → get_calendar  (confidence: 0.99)
- "show my unread emails"                   → read_emails   (confidence: 0.99, unread_only: true, date_filter: "")
- "unread emails from yesterday"            → read_emails   (confidence: 0.99, unread_only: true, date_filter: "yesterday")
- "any unseen messages?"                    → read_emails   (confidence: 0.99, unread_only: true, date_filter: "")
- "unread emails of today"                  → read_emails   (confidence: 0.99, unread_only: true, date_filter: "today")
- "emails from last week"                   → read_emails   (confidence: 0.99, date_filter: "last_week")
- "last month's emails"                     → read_emails   (confidence: 0.99, date_filter: "last_month")
- "show emails this month"                  → read_emails   (confidence: 0.99, date_filter: "this_month")
- "check John's email"                      → read_emails   (confidence: 0.55) ← ambiguous
- "find the invoice and reply to it"        → reply_email   (confidence: 0.50) ← mixed intent
RULES:
- If the user mentions only a time period (today, yesterday, this week, last week, this month, last month, last 5 days) without a specific keyword/sender/subject, classify as "read_emails", NOT "search_emails".
- Any mention of replying/responding → always "reply_email"
- Writing to someone new             → always "compose_email"
- If the user says "unread", "haven't read", "new emails", "unseen" → set unread_only to true
- If confidence < 0.75, still pick best intent but explain why you are unsure in ambiguity_reason
- IMPORTANT: Only set date_filter if the user EXPLICITLY mentions a date/time (today, yesterday, this week, last week, this month, last month, last N days, specific date). If no date is mentioned, set date_filter to empty string "".
- For generic requests like "show my emails" without a date, default date_filter to "today". But for "show my unread emails" (no date mentioned), set date_filter to "" (empty).
Extract:
- search_query     : keyword / sender / subject to search
- sender           : sender name or email mentioned
- subject_hint     : subject line hint for reply/compose
- to               : recipient email or name (for compose)
- count            : number of items (default 10)
- confidence       : float 0.0 to 1.0 — how confident you are about the intent
- ambiguity_reason : if confidence < 0.75, briefly explain why; otherwise empty string
- unread_only      : true if user explicitly wants only unread/unseen/new emails, false otherwise
- date_filter      : "today", "yesterday", "this_week", "last_week", "this_month", "last_month", "last_N_days" (e.g. "last_7_days"), specific date "2026-03-10", or "" (empty string if no date mentioned for unread queries)
Respond with ONLY valid JSON, no explanation:
{{
  "intent": "...",
  "search_query": "...",
  "sender": "...",
  "subject_hint": "...",
  "to": "...",
  "count": 10,
  "confidence": 0.95,
  "ambiguity_reason": "",
  "unread_only": false,
  "date_filter": ""
}}"""
        try:
            raw = llm.complete(intent_prompt).text.strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            intent_data = json.loads(raw)
        except Exception as e:
            logger.warning(f"Intent classification failed ({e}), defaulting to read_emails")
            intent_data = {}
        intent = intent_data.get("intent", "read_emails")
        confidence = float(intent_data.get("confidence", 1.0))
        ambiguity_reason = intent_data.get("ambiguity_reason", "")
        count = min(int(intent_data.get("count") or 10), 50)
        search_query = intent_data.get("search_query") or ""
        sender_hint = intent_data.get("sender") or ""
        subject_hint = intent_data.get("subject_hint") or ""
        to_hint = intent_data.get("to") or ""
        unread_only = bool(intent_data.get("unread_only", False))
        date_filter = intent_data.get("date_filter") or ""  
        logger.info(f"Intent: {intent} | confidence: {confidence} | unread_only: {unread_only} | date_filter: '{date_filter}' | search: '{search_query}' | sender: '{sender_hint}'")
        # ── Confirm intent with user if confidence is low ──────────────────────
        if confidence < 0.75:
            intent_labels = {
                "read_emails":   "read your recent emails",
                "search_emails": "search your emails",
                "get_calendar":  "check your calendar",
                "reply_email":   "draft a reply to an email",
                "compose_email": "compose a new email",
            }
            readable = intent_labels.get(intent, intent)
            logger.info(f"Low confidence ({confidence}) for intent '{intent}': {ambiguity_reason}")
            state["final_response"] = (
                f"I want to make sure I understood you correctly.\n\n"
                f"You said: *\"{user_query}\"*\n\n"
                f"I think you want me to **{readable}** — is that right?\n\n"
                f"If yes, please confirm or rephrase more clearly. For example:\n"
                f"- *\"Show my recent emails\"*\n"
                f"- *\"Reply to John's email about the project\"*\n"
                f"- *\"What meetings do I have tomorrow?\"*"
            )
            return state
        # ── Auto-enable canvas for email composition/reply ─────────────────────
        if intent in ("compose_email", "reply_email"):
            state["is_canvas_enabled"] = True
            logger.info(f"Auto-enabling canvas mode for intent: {intent}")
        else:
            state["is_canvas_enabled"] = False
        # ── Route ──────────────────────────────────────────────────────────────
        if intent == "reply_email":
            response = await _handle_reply_email(
                access_token, user_query, search_query, sender_hint, subject_hint, llm,
                messages=state.get("messages", []),
            )
        elif intent == "compose_email":
            response = await _handle_compose_email(user_query, to_hint, subject_hint, llm)
        elif intent == "search_emails":
            # Prefer sender-specific search if a sender was extracted
            if sender_hint:
                emails = _safe_call(OutlookService.search_emails_by_sender, access_token, sender_hint, top=count)
                search_scope = f"mailbox search for emails from '{sender_hint}'"
            else:
                q = search_query or user_query
                emails = _safe_call(OutlookService.search_emails, access_token, q, top=count)
                search_scope = f"mailbox search for '{q}'"
                if not emails:
                    # Fallback only for non-sender keyword searches
                    logger.info(f"Search for '{q}' returned no results, falling back to recent inbox")
                    emails = _safe_call(OutlookService.get_emails, access_token, top=count)
                    search_scope = f"your {count} most recent inbox emails"
            rd = {"emails": emails, "type": "search_results", "search_scope": search_scope} if emails else None
            response = await _format_email_list(user_query, rd, llm)
        elif intent == "get_calendar":
            # Parse date from query using LLM
            start_date, end_date, date_label = _parse_calendar_date(user_query, llm)
            include_ooo = bool(re.search(r"\b(ooo|out\s*-?of\s*-?office)\b", user_query, re.IGNORECASE))
            # Calendar is commonly denser than email; avoid truncating at the generic default.
            calendar_top = min(max(count, 50), 200)
            events = _safe_call(
                OutlookService.get_calendar_events, access_token,
                start_date=start_date,
                end_date=end_date,
                top=calendar_top,
            )
            rd = {
                "events": events,
                "type": "calendar",
                "date_label": date_label,
                "start_date": start_date,
                "end_date": end_date,
                "include_ooo": include_ooo,
            } if events else None
            response = await _format_calendar(user_query, rd, llm)
        else:  # read_emails
            # ── Parse date filter (only if specified) ──────────────────────────
            if date_filter:
                received_after, received_before, date_label = _parse_email_date_filter(date_filter)
            else:
                received_after, received_before, date_label = None, None, ""
            
            if sender_hint:
                # User asked about a specific sender — search entire mailbox (no date filter for search)
                logger.info(f"read_emails with sender filter: '{sender_hint}'")
                emails = _safe_call(OutlookService.search_emails_by_sender, access_token, sender_hint, top=count)
                search_scope = f"emails from '{sender_hint}'"
            elif search_query:
                # Has a keyword — use search (no date filter for search)
                logger.info(f"read_emails with search: '{search_query}'")
                emails = _safe_call(OutlookService.search_emails, access_token, search_query, top=count)
                search_scope = f"emails matching '{search_query}'"
            else:
                # ── Date filter + optional unread filter ───────────────────────
                logger.info(f"Fetching emails: date_filter='{date_filter}', unread_only={unread_only}")
                emails = _safe_call(
                    OutlookService.get_emails,
                    access_token,
                    top=count,
                    unread_only=unread_only,
                    received_after=received_after,
                    received_before=received_before,
                )
                
                if unread_only:
                    if date_label:
                        search_scope = f"unread emails from {date_label}"
                    else:
                        search_scope = f"your {count} most recent unread emails"
                    # ── No unread emails found ─────────────────────────────────
                    if not emails:
                        if date_label:
                            state["final_response"] = f"You have no unread emails from {date_label}!"
                        else:
                            state["final_response"] = "You have no unread emails!"
                        return state
                else:
                    if date_label:
                        search_scope = f"emails from {date_label}"
                    else:
                        search_scope = f"your {count} most recent inbox emails"
                    if not emails:
                        if date_label:
                            state["final_response"] = f"You have no emails from {date_label}."
                        else:
                            state["final_response"] = "You have no emails in your inbox."
                        return state
            rd = {
                "emails": emails,
                "type": "email_list",
                "search_scope": search_scope,
                "unread_only": unread_only,
                "date_label": date_label,
            } if emails else None
            response = await _format_email_list(user_query, rd, llm)
        state["final_response"] = response
        logger.info("Outlook Agent: Done")
    except OutlookTokenExpiredError:
        logger.warning("Outlook token expired/revoked during API call")
        from agentcore.services.outlook_orch.token_manager import outlook_token_manager
        user_id = state.get("user_id")
        if user_id:
            outlook_token_manager.delete_token(user_id)
            outlook_token_manager._expired_users[user_id] = datetime.utcnow()
        state["final_response"] = (
            "Your Outlook session has expired.\n\n"
            "**To reconnect:**\n"
            "1. Click the **+** button → **Outlook Connector**\n"
            "2. Sign in again with your Microsoft account, if already signed in, toggle off and on again\n\n"
            "Sessions last approximately 1 hour for security reasons."
        )
    except Exception as e:
        logger.error(f"Unhandled error in Outlook agent: {e}", exc_info=True)
        state["final_response"] = f"I encountered an error accessing your Outlook: {str(e)}"
    return state
# ── Reply handler ──────────────────────────────────────────────────────────────
async def _handle_reply_email(
    access_token: str,
    user_query: str,
    search_query: str,
    sender_hint: str,
    subject_hint: str,
    llm,
    messages: Sequence = (),
) -> str:
    """
    Locate the target email, then generate a clean plain-text reply body.
    Returns the :::email_draft::: block so the frontend can render a Draft card.
    """
    # [agentcore] shim replaces MiBuddy helper: from backend.agents.utils import get_message_content, get_message_role
    # ── Build conversation context from recent messages ─────────────────────
    recent_context = ""
    for msg in reversed(messages[:-1]):
        role = get_message_role(msg)
        if role == "assistant":
            content = get_message_content(msg)
            if content:
                recent_context = content[:3000]
                break
    def _norm(s: str) -> str:
        return (s or "").strip().lower()
    def _email_line(idx: int, em: Dict[str, Any]) -> str:
        fr = em.get("from", {}).get("emailAddress", {})
        return (
            f"{idx}. From: {fr.get('name', '')} ({fr.get('address', '')}) | "
            f"Subject: {em.get('subject', '')}"
        )
    # ── Fetch candidate emails (deep search up to 50) ──────────────────────
    q = search_query or sender_hint or subject_hint
    candidate_map: Dict[str, Dict[str, Any]] = {}
    def _add_candidates(items: Sequence[Dict[str, Any]]) -> None:
        for em in items or []:
            em_id = em.get("id")
            if em_id and em_id not in candidate_map:
                candidate_map[em_id] = em
    if sender_hint:
        _add_candidates(_safe_call(OutlookService.search_emails_by_sender, access_token, sender_hint, top=50) or [])
    if subject_hint:
        _add_candidates(_safe_call(OutlookService.search_emails, access_token, subject_hint, top=50) or [])
    if search_query:
        _add_candidates(_safe_call(OutlookService.search_emails, access_token, search_query, top=50) or [])
    if not candidate_map and q:
        _add_candidates(_safe_call(OutlookService.search_emails, access_token, q, top=50) or [])
    if not candidate_map:
        _add_candidates(_safe_call(OutlookService.get_emails, access_token, top=50) or [])
    candidates = list(candidate_map.values())
    # Deterministic filtering first (prevents LLM from guessing wrong thread)
    sender_hint_n = _norm(sender_hint)
    subject_hint_n = _norm(subject_hint)
    if sender_hint_n or subject_hint_n:
        filtered = []
        for em in candidates:
            fr = em.get("from", {}).get("emailAddress", {})
            sender_line = _norm(f"{fr.get('name', '')} {fr.get('address', '')}")
            subj = _norm(em.get("subject", ""))
            sender_ok = (not sender_hint_n) or (sender_hint_n in sender_line)
            subject_ok = (not subject_hint_n) or (subject_hint_n in subj)
            if sender_ok and subject_ok:
                filtered.append(em)
        if filtered:
            candidates = filtered
        else:
            short = "\n".join(_email_line(i + 1, em) for i, em in enumerate(candidates[:5]))
            return (
                "I could not find an exact email matching that sender/subject in the recent search results.\n\n"
                "Please confirm one of these emails (reply with a number), or give a more specific subject:\n"
                f"{short}"
            )
    if not candidates:
        return (
            "I couldn't find an email to reply to. "
            "Can you try being more specific, e.g. *\"reply to John's email about the project update\"*."
        )
    # ── Fast path for explicit ordinal references (e.g., "reply to 12th email")
    ordinal_match = re.search(r"\b(\d+)(?:st|nd|rd|th)?\s+email\b", user_query, re.IGNORECASE)
    if ordinal_match:
        pick_num = int(ordinal_match.group(1))
        if 1 <= pick_num <= len(candidates):
            pick = pick_num - 1
        else:
            return (
                f"I found only {len(candidates)} candidate emails right now, so I can't pick email #{pick_num}. "
                "Please specify sender/subject, or choose a valid number."
            )
    else:
        pick = 0
    # ── Ask LLM to pick the correct email when ordinal isn't explicit ───────
    email_options = []
    for i, em in enumerate(candidates):
        fr = em.get("from", {}).get("emailAddress", {})
        email_options.append(
            f"{i+1}. From: {fr.get('name', '')} ({fr.get('address', '')}) | "
            f"Subject: {em.get('subject', '')} | "
            f"Preview: {em.get('bodyPreview', '')[:100]}"
        )
    if not ordinal_match:
        pick_prompt = f"""The user previously saw this assistant message:
---
{recent_context}
---
Now the user says: "{user_query}"
Here are the candidate emails:
{chr(10).join(email_options)}
Which email number (1-{len(candidates)}) does the user want to reply to?
Return ONLY valid JSON: {{"pick": <number>, "confidence": <0 to 1>}}
If unsure, set confidence below 0.55."""
        try:
            raw = llm.complete(pick_prompt).text.strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            pick_data = json.loads(raw)
            pick = int(pick_data.get("pick", 1)) - 1
            pick = max(0, min(pick, len(candidates) - 1))
            pick_conf = float(pick_data.get("confidence", 0.0))
            if pick_conf < 0.55:
                short = "\n".join(_email_line(i + 1, em) for i, em in enumerate(candidates[:5]))
                return (
                    "I found multiple possible emails and don't want to draft a reply to the wrong one.\n\n"
                    "Please reply with the email number from this shortlist:\n"
                    f"{short}"
                )
        except Exception as e:
            logger.warning(f"Email pick failed ({e})")
            short = "\n".join(_email_line(i + 1, em) for i, em in enumerate(candidates[:5]))
            return (
                "I couldn't reliably identify the exact email to reply to.\n\n"
                "Please reply with a number from this shortlist:\n"
                f"{short}"
            )
    email = candidates[pick]
    logger.info(f"User requested reply to email #{pick+1} of {len(candidates)}")
    # Extract metadata
    from_obj = email.get("from", {}).get("emailAddress", {})
    to_email = from_obj.get("address", "")
    to_name = from_obj.get("name", to_email)
    original_subject = email.get("subject", "")
    reply_subject = (
        original_subject if original_subject.lower().startswith("re:")
        else f"Re: {original_subject}"
    )
    body_obj = email.get("body", {})
    original_body = (
        body_obj.get("content", "")
        if body_obj.get("contentType", "").lower() == "text"
        else email.get("bodyPreview", "")
    )
    original_body = re.sub(r'<[^>]+>', ' ', original_body).strip()
    original_body = re.sub(r'\s{2,}', ' ', original_body)
    logger.info(f"Generating reply to '{to_name} <{to_email}>' re: '{original_subject}'")
    first_name = to_name.split()[0] if to_name else "there"
    prompt = f"""You are drafting a professional email reply on behalf of the user.
Original email:
  From: {to_name} ({to_email})
  Subject: {original_subject}
  Message: {original_body[:800]}
User's instruction: "{user_query}"
Return output in EXACTLY this format:
Subject: <subject line>
<Salutation>
<Email body paragraphs>
<Closing>
<Name if required>
Rules:
- No explanations.
- No markdown.
- No text before "Subject:".
- No text after closing.
- Do not ask follow-up questions.
- Leave exactly one blank line after the subject.
- Use the subject: {reply_subject}
- Begin the body with a greeting such as "Hi {first_name},"
- Use plain prose, professional tone."""
    try:
        raw_output = llm.complete(prompt).text.strip()
    except Exception as e:
        logger.error(f"LLM reply generation failed: {e}")
        return f"I found the email from **{to_name}** but couldn't generate a reply. Please try again."
    raw_output = _remove_preamble(raw_output)
    return raw_output
# ── Compose handler ────────────────────────────────────────────────────────────
async def _handle_compose_email(
    user_query: str,
    to_hint: str,
    subject_hint: str,
    llm,
) -> str:
    """Generate a new email draft and return the :::email_draft::: block."""
    prompt = f"""You are drafting a professional email on behalf of the user.
User instruction: "{user_query}"
Recipient: {to_hint or "not specified"}
Subject hint: {subject_hint or "not specified"}
Return output in EXACTLY this format:
Subject: <subject line>
<Salutation>
<Email body paragraphs>
<Closing>
<Name if required>
Rules:
- No explanations.
- No markdown.
- No text before "Subject:".
- No text after closing.
- Do not ask follow-up questions.
- Leave exactly one blank line after the subject.
- Use plain prose, professional tone.
- Begin the body with an appropriate greeting."""
    try:
        raw_output = llm.complete(prompt).text.strip()
    except Exception as e:
        logger.error(f"LLM compose failed: {e}")
        return "I couldn't draft the email. Please try again."
    raw_output = _remove_preamble(raw_output)
    return raw_output

# ── Email-list formatter ───────────────────────────────────────────────────────
# Matches MiBuddy's PRODUCTION output: clean markdown table (Gemini-style)
# with header "Here are your **N** emails from {scope}:", 20 email cap,
# truncated sender/subject/preview, and status indicators for unread +
# high-importance + attachments.
async def _format_email_list(query: str, data: Optional[Dict], llm) -> str:
    """Format emails as a clean markdown table (Gemini-style)."""
    if not data:
        return (
            "I couldn't find any emails matching your request.\n\n"
            "💡 **Tips:** Try a shorter keyword, search by sender name, or check if the email "
            "was just received (Graph API indexes with a short delay)."
        )
    emails = data.get("emails", [])
    if not emails:
        return "No emails found."

    search_scope = data.get("search_scope", "your recent emails")
    capped = emails[:20]
    email_count = len(capped)

    # ── Build header ───────────────────────────────────────────────────────
    header = f"Here are your **{email_count}** emails from {search_scope}:\n\n"

    # ── Build markdown table ───────────────────────────────────────────────
    table_rows = [
        "| # | Sender | Subject | Received | Status |",
        "|---|--------|---------|----------|--------|",
    ]

    for i, email in enumerate(capped, 1):
        try:
            fr = email.get("from", {}).get("emailAddress", {})
            sender = (fr.get("name") or fr.get("address", "Unknown"))
            subj = " ".join(email.get("subject", "No subject").split())
            preview = " ".join(email.get("bodyPreview", "").split())

            # Truncate long fields for table readability
            if len(sender) > 28:
                sender = sender[:26] + "…"
            if len(subj) > 55:
                subj = subj[:53] + "…"
            if len(preview) > 80:
                preview = preview[:78] + "…"

            # Escape pipes in content
            sender = sender.replace("|", "\\|")
            subj = subj.replace("|", "\\|")
            preview = preview.replace("|", "\\|")

            # Combine subject + preview in one cell
            if preview:
                subj_cell = f"**{subj}**<br>{preview}"
            else:
                subj_cell = f"**{subj}**"

            # Format received date as "Apr 7"
            raw_dt = email.get("receivedDateTime", "")
            try:
                dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
                received = _format_short_date(dt)
            except Exception:
                received = raw_dt[:10]

            # Status indicators
            is_read = email.get("isRead", True)
            importance = email.get("importance", "normal")
            has_attach = email.get("hasAttachments", False)

            status_parts = []
            if not is_read:
                status_parts.append("🔵 Unread")
            else:
                status_parts.append("✅ Read")
            if importance == "high":
                status_parts.append("❗ High Importance")
            if has_attach:
                status_parts.append("📎 Attachment")
            status = " · ".join(status_parts)

            table_rows.append(f"| {i} | {sender} | {subj_cell} | {received} | {status} |")
        except Exception:
            continue

    if len(table_rows) <= 2:
        return "Could not parse email data."

    return header + "\n".join(table_rows)

# ── Calendar formatter ─────────────────────────────────────────────────────────
def _fmt_time(dt_str: str) -> str:
    """Extract HH:MM from a Graph dateTime string (already in IST via Prefer header)."""
    try:
        t = dt_str[11:16]
        return t
    except Exception:
        return dt_str[:16].replace("T", " ")

def _is_ooo_event(ev: Dict[str, Any]) -> bool:
    """Detect out-of-office style placeholders that usually add noise to schedule views."""
    show_as = str(ev.get("showAs", "")).lower()
    subject = str(ev.get("subject", "")).lower()
    return (
        show_as in {"oof", "workingelsewhere"}
        or "out of office" in subject
        or "ooo" in subject
    )

async def _format_calendar(query: str, data: Optional[Dict], llm) -> str:
    if not data:
        return "I couldn't find any upcoming events in your calendar."
    events = data.get("events", [])
    if not events:
        return "No events found for the requested period."
    date_label = data.get("date_label", "the requested period")
    include_ooo = bool(data.get("include_ooo", False))
    active, cancelled = [], []
    hidden_ooo_count = 0
    for ev in events:
        try:
            if not include_ooo and _is_ooo_event(ev):
                hidden_ooo_count += 1
                continue
            is_cancelled = (
                ev.get("isCancelled", False)
                or ev.get("showAs", "").lower() == "free"
                or str(ev.get("subject", "")).lower().startswith("canceled")
                or str(ev.get("subject", "")).lower().startswith("cancelled")
            )
            entry = {
                "subject": ev.get("subject", "No title"),
                "start": _fmt_time(ev.get("start", {}).get("dateTime", "")),
                "end": _fmt_time(ev.get("end", {}).get("dateTime", "")),
                "online": ev.get("isOnlineMeeting", False),
            }
            if is_cancelled:
                cancelled.append(entry)
            else:
                active.append(entry)
        except Exception:
            continue
    if not active and not cancelled:
        if hidden_ooo_count > 0:
            return (
                f"No non-OOO events found for {date_label}. "
                f"({hidden_ooo_count} out-of-office entries were hidden.)"
            )
        return "No events found for the requested period."
    # ── Header ─────────────────────────────────────────────────────────────────
    header = f"You have the following meetings scheduled for {date_label}:\n\n"
    if hidden_ooo_count > 0:
        header += f"(Hidden {hidden_ooo_count} out-of-office entries. Ask for OOO explicitly to include them.)\n\n"
    # ── Table builder ──────────────────────────────────────────────────────────
    def _make_table(entries: list) -> str:
        if not entries:
            return ""
        rows = []
        rows.append("| **Time** | **Title** |")
        rows.append("|----------|-----------|")
        for e in entries:
            time_range = f"{e['start']} - {e['end']}"
            icon = " 📅" if e["online"] else ""
            title = e['subject'] + icon
            title = title.replace("|", "\\|")
            rows.append(f"| {time_range} | {title} |")
        return "\n".join(rows)
    sections = []
    if active:
        sections.append("**Active Meetings**\n\n" + _make_table(active))
    if cancelled:
        sections.append("**Cancelled Meetings**\n\n" + _make_table(cancelled))
    return header + "\n\n".join(sections)

__all__ = ["outlook_agent_node", "build_email_draft_block", "strip_markdown"]