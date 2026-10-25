"""Company Knowledge Base search handler using Azure AI Project Agent.

Replicates MiBuddy's Motherson search — queries a pre-configured Azure AI Agent
that has Azure Cognitive Search connected as a knowledge base tool.

All credentials come from settings (shared with MiBuddy's configuration).
"""

from __future__ import annotations

import re
import logging

from loguru import logger


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _get_settings():
    from agentcore.services.deps import get_settings_service
    return get_settings_service().settings


# ---------------------------------------------------------------------------
# Azure AI Agent client (same as MiBuddy's ms_agent)
# ---------------------------------------------------------------------------

_project_client = None
_agent = None


def _get_agent():
    """Get or create the Azure AI Project Agent client (singleton)."""
    global _project_client, _agent

    if _project_client is not None and _agent is not None:
        return _project_client, _agent

    from azure.ai.projects import AIProjectClient
    from azure.identity import ClientSecretCredential

    settings = _get_settings()

    if not settings.azure_ai_project_endpoint:
        raise ValueError("Azure AI Project not configured. Set AZURE_AI_PROJECT_ENDPOINT.")
    if not settings.azure_ai_project_agent_id:
        raise ValueError("Azure AI Agent not configured. Set AZURE_AI_PROJECT_AGENT_ID.")

    credential = ClientSecretCredential(
        tenant_id=settings.azure_ai_project_tenant_id,
        client_id=settings.azure_ai_project_client_id,
        client_secret=settings.azure_ai_project_client_secret,
    )

    _project_client = AIProjectClient(
        credential=credential,
        endpoint=settings.azure_ai_project_endpoint,
    )

    _agent = _project_client.agents.get_agent(settings.azure_ai_project_agent_id)
    logger.info(f"[KB Search] Connected to Azure AI Agent: {_agent.id}")

    return _project_client, _agent


def _strip_citations(text: str) -> str:
    """Clean up Azure AI Agent response:
      - Remove citation markers like 【4:0†source.docx】
      - Remove the 'Final tag: ...' classification line that the agent appends
      - Collapse excess blank lines
    """
    try:
        # Citation markers
        cleaned = re.sub(r'【[^】]*】', '', text)
        # "Final tag: Internal data and web sources." — strip whole line (any case)
        cleaned = re.sub(r'(?im)^\s*final\s*tag\s*:.*$', '', cleaned)
        # Collapse 3+ newlines to double newline
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        return cleaned.strip()
    except Exception:
        return text


# ---------------------------------------------------------------------------
# Query the knowledge base
# ---------------------------------------------------------------------------

async def handle_kb_search(query: str) -> dict:
    """Query the company knowledge base via Azure AI Agent.

    Creates a thread, sends the query, waits for completion,
    and returns the agent's response.

    Returns dict with keys: response_text, model_name
    """
    import asyncio
    from azure.ai.agents.models import ListSortOrder

    try:
        project, agent = _get_agent()

        # Run the agent query in a thread pool (Azure SDK is sync)
        def _run_agent():
            thread = project.agents.threads.create()
            project.agents.messages.create(
                thread_id=thread.id,
                role="user",
                content=query,
            )

            run = project.agents.runs.create_and_process(
                thread_id=thread.id,
                agent_id=agent.id,
            )

            if run.status == "failed":
                logger.error(f"[KB Search] Agent run failed: {run.last_error}")
                return f"Knowledge base search failed: {run.last_error}"

            messages = project.agents.messages.list(
                thread_id=thread.id,
                order=ListSortOrder.ASCENDING,
            )

            # Extract all assistant responses
            all_texts = []
            for message in messages:
                if message.role == "assistant" and message.text_messages:
                    for text_msg in message.text_messages:
                        all_texts.append(text_msg.text.value)

            return " ".join(all_texts) if all_texts else "No answer found in the knowledge base."

        response_text = await asyncio.to_thread(_run_agent)
        response_text = _strip_citations(response_text)

        return {
            "response_text": response_text,
            "model_name": "knowledge-base",
        }

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"[KB Search] Error: {e}")
        return {
            "response_text": f"Knowledge base search encountered an error: {str(e)}",
            "model_name": "knowledge-base",
        }


async def handle_kb_search_stream(query: str, event_manager=None) -> dict:
    """KB search with progress events (not truly streaming — agent runs sync)."""
    if event_manager:
        event_manager.on_token(data={"chunk": "Searching knowledge base... "})

    result = await handle_kb_search(query)

    if event_manager:
        event_manager.on_token(data={"chunk": result["response_text"]})

    return result
