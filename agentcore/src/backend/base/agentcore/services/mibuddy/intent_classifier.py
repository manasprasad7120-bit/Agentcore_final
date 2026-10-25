"""Intent classification service for orchestrator chat routing.

Classifies user queries into intents (general_chat, web_search, image_generation)
using an LLM from the model registry via the Model microservice.
"""

from __future__ import annotations

import json
import logging
import re
from enum import Enum
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage

from agentcore.services.model_service_client import MicroserviceChatModel

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    GENERAL_CHAT = "general_chat"
    WEB_SEARCH = "web_search"
    IMAGE_GENERATION = "image_generation"
    KNOWLEDGE_BASE_SEARCH = "knowledge_base_search"
    OUTLOOK_QUERY = "outlook_query"


def _build_classification_prompt() -> str:
    """Build the intent classification prompt, dynamically including company KB info."""
    from agentcore.services.deps import get_settings_service
    settings = get_settings_service().settings

    company_name = settings.company_kb_name
    company_keywords = settings.company_kb_keywords

    kb_intent = ""
    if company_name and company_keywords:
        examples = ", ".join(f'"{kw.strip()}"' for kw in company_keywords.split(",")[:5])
        kb_intent = f"""
4. "knowledge_base_search": Use this if the user asks about {company_name} (the company), its policies, internal documents, employees, corporate information, or anything specifically related to {company_name}.
   Keywords that indicate this intent: {examples}.
   Examples: "What is {company_name}'s leave policy?", "Who is the CEO of {company_name}?", "{company_name} revenue"."""

    return f"""You are an intelligent intent classifier for an AI assistant.
Your job is to analyze the user's query and categorize it into EXACTLY one of the following categories:

1. "image_generation": Use this if the user requests to create, generate, draw, render, modify, edit, or transform any image, picture, photo, logo, or diagram.
   Examples: "create an image of a dog", "generate a logo", "draw a sunset", "edit that image", "make the background blue".

2. "web_search": Use this if the user asks for *current* information, real-time data, news, weather, stock prices, sports scores, or explicitly asks to search the web/internet.
   Examples: "What is the weather in London?", "Latest news on AI", "Who won the game yesterday?", "Search for..."

3. "outlook_query": Use this if the user asks about emails, calendar, meetings, Outlook, or wants to search/read/send/compose/write/draft emails, or reply to emails.
   Examples: "Show me my recent emails", "Do I have any meetings today?", "Search for emails from John", "What's on my calendar?", "Check my inbox", "Write an email to John about the project update", "Draft an email saying the services are down", "Can you write me an email about...", "Compose an email to the team", "Reply to the email from Sarah", "Send an email about the outage".{kb_intent}

{"5" if kb_intent else "4"}. "general_chat": Use this for everything else. This includes general knowledge, coding help, writing, summarization, translation, math, casual conversation, and any question that can be answered from training knowledge.
   Examples: "Write a python script", "Summarize this text", "Translate hello to spanish", "Tell me a joke", "Explain quantum computing".

Output Format:
You must output ONLY a valid JSON object containing a single key "intent".
Example: {{"intent": "web_search"}}
Do not include any explanation or markdown formatting."""


class IntentClassifier:
    """Classifies user queries into intents using an LLM.

    Supports two modes:
    1. Model name (e.g. 'gpt-5.1') — uses LTM embedding API key directly (simpler)
    2. Registry UUID — uses model service to resolve credentials (existing flow)
    """

    def __init__(self, model_id: str | None = None):
        self._model_id = model_id
        self._model = None

    def _get_model(self):
        if self._model is not None:
            return self._model

        from agentcore.services.deps import get_settings_service
        settings = get_settings_service().settings

        model_name = settings.intent_classifier_model_name
        endpoint = settings.mibuddy_endpoint
        api_key = settings.mibuddy_api_key
        api_version = settings.mibuddy_api_version

        logger.info(f"[IntentClassifier] model='{model_name}', endpoint='{endpoint}', key={'***' + api_key[-4:] if api_key and len(api_key) > 4 else '(empty)'}")

        if not model_name:
            raise ValueError("Set INTENT_CLASSIFIER_MODEL_NAME in .env")
        if not endpoint or not api_key:
            raise ValueError("Set MIBUDDY_ENDPOINT and MIBUDDY_API_KEY in .env")

        from langchain_openai import AzureChatOpenAI
        self._model = AzureChatOpenAI(
            azure_endpoint=endpoint,
            azure_deployment=model_name,
            api_version=api_version,
            api_key=api_key,
            temperature=1,
            max_tokens=300,
        )
        return self._model

    @staticmethod
    def _matches_kb_keywords(query: str) -> bool:
        """Check if query contains any company KB keyword as a whole word.

        Uses word-boundary regex (\\b) so 'smother' does NOT match 'mother',
        but 'motherson group' DOES match 'motherson'.
        """
        from agentcore.services.deps import get_settings_service
        settings = get_settings_service().settings
        keywords = settings.company_kb_keywords
        if not keywords:
            return False
        q_lower = query.lower()
        for kw in keywords.split(","):
            kw = kw.strip().lower()
            if not kw:
                continue
            # Word-boundary match — handles multi-word keywords like "samvardhana motherson"
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, q_lower):
                return True
        return False

    async def _llm_fuzzy_kb_check(self, query: str) -> bool:
        """Use the classifier LLM to check if query is about the company (typo-tolerant).

        Replaces the SentenceTransformer semantic check used by MiBuddy with a
        focused yes/no LLM call. Catches typos like 'mothrson' → Motherson,
        misspellings, and indirect references.

        Returns False on any failure to avoid false positives.
        """
        from agentcore.services.deps import get_settings_service
        settings = get_settings_service().settings
        company_name = settings.company_kb_name
        if not company_name:
            return False
        try:
            model = self._get_model()
            prompt = (
                f"Does the following user query refer to '{company_name}' (the company), "
                f"its people, products, or business? Consider typos, misspellings, and "
                f"abbreviations of '{company_name}'.\n\n"
                f"Query: {query}\n\n"
                f"Reply with ONLY one word: 'yes' or 'no'."
            )
            result = await model.ainvoke([
                SystemMessage(content="You answer with one word: yes or no."),
                HumanMessage(content=prompt),
            ])
            content = (result.content if hasattr(result, "content") else str(result)) or ""
            answer = content.strip().lower().rstrip(".!?,")
            is_match = answer.startswith("yes")
            if is_match:
                logger.info(f"[IntentClassifier] LLM fuzzy KB match: '{query[:60]}' -> yes")
            return is_match
        except Exception as e:
            logger.debug(f"[IntentClassifier] LLM fuzzy check failed: {e}")
            return False

    async def classify(self, query: str) -> Intent:
        """Classify a user query into an intent.

        Two-stage company KB detection (matches MiBuddy's hybrid approach):
          1. Word-boundary keyword match  → instant, deterministic
          2. LLM fuzzy yes/no check       → typo-tolerant fallback (replaces SentenceTransformer)

        If neither stage flags it as KB, runs the standard LLM intent classifier.
        Falls back to GENERAL_CHAT on any failure.
        """
        # Stage 1: Word-boundary keyword fast-path (no LLM call)
        if self._matches_kb_keywords(query):
            logger.info(f"[IntentClassifier] Keyword match -> knowledge_base_search: '{query[:60]}'")
            return Intent.KNOWLEDGE_BASE_SEARCH

        try:
            logger.info(f"[IntentClassifier] Classifying: '{query[:80]}'")
            model = self._get_model()
            prompt = _build_classification_prompt()
            messages = [
                SystemMessage(content=prompt),
                HumanMessage(content=query),
            ]
            result = await model.ainvoke(messages)
            content = result.content if hasattr(result, "content") else str(result)
            logger.info(f"[IntentClassifier] Raw response: {content!r}")

            # Empty response → fall back
            if not content or not content.strip():
                logger.warning("[IntentClassifier] Empty response, defaulting to general_chat")
                return Intent.GENERAL_CHAT

            # Robust JSON extraction — handle markdown code blocks or extra text
            json_str = content.strip()
            if "```" in json_str:
                json_str = json_str.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]
                json_str = json_str.strip()
            elif "{" in json_str:
                start = json_str.index("{")
                end = json_str.rindex("}") + 1
                json_str = json_str[start:end]

            parsed = json.loads(json_str)
            intent_str = parsed.get("intent", "general_chat")
            logger.info(f"Intent classified: '{query[:60]}' -> {intent_str}")

            try:
                intent = Intent(intent_str)
            except ValueError:
                logger.warning(f"Unknown intent '{intent_str}' from classifier, defaulting to general_chat")
                intent = Intent.GENERAL_CHAT

            # Stage 2: LLM fuzzy KB check — only if classifier said general_chat
            # (catches typos like 'mothrson' that the keyword check missed)
            if intent == Intent.GENERAL_CHAT and await self._llm_fuzzy_kb_check(query):
                return Intent.KNOWLEDGE_BASE_SEARCH

            return intent

        except Exception as e:
            logger.error(f"[IntentClassifier] Failed: {type(e).__name__}: {e}")
            # Last-resort: still try the fuzzy check if classifier crashed
            if await self._llm_fuzzy_kb_check(query):
                return Intent.KNOWLEDGE_BASE_SEARCH
            return Intent.GENERAL_CHAT
