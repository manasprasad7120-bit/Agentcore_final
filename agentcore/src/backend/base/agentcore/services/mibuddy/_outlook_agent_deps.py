"""Shim dependencies for the ported MiBuddy `outlook_agent`.

MiBuddy's `outlook_agent.py` imports:
  - AgentState (LangGraph TypedDict)
  - AzureAIFoundryLLM (MiBuddy's Azure OpenAI wrapper with `.complete(prompt).text`)
  - get_message_content / get_message_role (LangChain-style helpers)

agentcore doesn't have those directly, so we provide drop-in shims here
so the outlook_agent.py source can be copied VERBATIM with just its
imports redirected at the top of the file.
"""
from __future__ import annotations

import logging
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    """Matches the MiBuddy LangGraph state dict."""

    messages: list
    user_id: str
    final_response: str
    is_canvas_enabled: bool
    intent: str


def get_message_content(msg: Any) -> str:
    if msg is None:
        return ""
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        return str(msg.get("content") or "")
    return str(getattr(msg, "content", msg) or "")


def get_message_role(msg: Any) -> str:
    if msg is None:
        return ""
    if isinstance(msg, dict):
        return str(
            msg.get("role")
            or ("assistant" if msg.get("sender") == "agent" else msg.get("sender"))
            or "",
        )
    return str(getattr(msg, "role", None) or getattr(msg, "type", None) or "")


class _LLMResult:
    """Mimics MiBuddy's LLM response object; exposes `.text`."""

    def __init__(self, text: str) -> None:
        self.text = text


class AzureAIFoundryLLM:
    """VERBATIM port of MiBuddy-Backend/backend/utils/model.py::AzureAIFoundryLLM.

    Same client construction (`openai.AzureOpenAI`), same message format
    (`azure.ai.inference.models.SystemMessage` / `UserMessage`), same
    `.complete(prompt)` returning an object with `.text`. NO `temperature`
    is passed — some Azure OpenAI deployments (e.g., gpt-5.1-chat) reject
    any value other than the default, so MiBuddy doesn't send it.

    Agentcore-specific tweak: instead of reading credentials from
    MiBuddy's `environ.py`, we pull them from agentcore's settings so the
    same `.env` the IntentClassifier already uses works here too.
    """

    # default system message kept generic; outlook_agent.py overrides
    # behaviour via its prompts so the system message can stay minimal.
    _DEFAULT_SYSTEM = "You are a helpful assistant."

    def __init__(
        self, model_name: str = "gpt-5.2", system_message: str | None = None,
    ) -> None:
        from agentcore.services.deps import get_settings_service
        settings = get_settings_service().settings

        # MiBuddy resolves short names via model_map; agentcore just uses
        # the settings-configured deployment name directly (same value
        # IntentClassifier uses).
        self.model_name = (
            settings.intent_classifier_model_name or model_name
        )
        self.system_message = system_message or self._DEFAULT_SYSTEM

        endpoint = settings.mibuddy_endpoint
        api_key = settings.mibuddy_api_key
        api_version = settings.mibuddy_api_version

        if not endpoint or not api_key:
            raise ValueError("Set MIBUDDY_ENDPOINT and MIBUDDY_API_KEY in .env")

        from openai import AzureOpenAI
        self.client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key,
            timeout=30.0,
        )

    def complete(self, prompt: str) -> _LLMResult:
        """Matches MiBuddy's contract:
        - takes a plain prompt string
        - returns an object with `.text` attribute
        - no temperature parameter sent to the API
        """
        try:
            from azure.ai.inference.models import SystemMessage, UserMessage
            messages = [
                SystemMessage(content=self.system_message),
                UserMessage(content=prompt),
            ]
            response = self.client.chat.completions.create(
                messages=messages,
                model=self.model_name,
            )
            return _LLMResult(response.choices[0].message.content or "")
        except Exception as e:
            logger.error(f"[AzureAIFoundryLLM] complete failed: {e}", exc_info=True)
            return _LLMResult("")
