"""Autocomplete suggestion service.

Generates query suggestions as the user types, using a lightweight model
(e.g. Meta-Llama-3.1-8B on Azure AI Foundry serverless endpoint).

Supports two endpoint formats:
1. Serverless (Llama/Mistral): SUGGESTION_ENDPOINT + /openai/v1/chat/completions
   - Model name sent in request body
2. Managed (Azure OpenAI): MIBUDDY_ENDPOINT + /openai/deployments/{name}/chat/completions
   - Model name in URL path
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def get_suggestions(query: str) -> list[str]:
    """Generate autocomplete suggestions for the user's input.

    Args:
        query: Current text in the input field (may be empty).

    Returns:
        List of up to 5 suggestion strings.
    """
    from agentcore.services.deps import get_settings_service

    settings = get_settings_service().settings

    model_name = settings.suggestion_model_name
    if not model_name:
        return []

    # Determine endpoint — dedicated serverless endpoint or shared managed endpoint
    endpoint = settings.suggestion_endpoint or settings.mibuddy_endpoint
    api_key = settings.mibuddy_api_key

    if not endpoint or not api_key:
        return []

    # Build prompt based on whether input is empty or has text
    if not query or not query.strip():
        user_prompt = (
            "Generate EXACTLY 5 trending conversational topics that users commonly ask about. "
            "Each topic should be a short question or statement. "
            "Return ONLY the 5 topics, one per line. No numbering, no bullets, no extra text."
        )
    else:
        user_prompt = (
            f"Based on this partial input, generate EXACTLY 5 short helpful completions "
            f"of what the user might be trying to ask. Each suggestion should be a complete "
            f"question or statement. Return ONLY the 5 suggestions, one per line. "
            f"No numbering, no bullets, no extra text.\n\nPartial input: {query}"
        )

    # Determine URL format based on endpoint type
    base = endpoint.rstrip("/")
    if settings.suggestion_endpoint:
        # Serverless endpoint (Llama, Mistral, etc.) — model in body
        url = f"{base}/openai/v1/chat/completions"
        body: dict = {
            "model": model_name,
            "messages": [{"role": "user", "content": user_prompt}],
            "max_tokens": 60,
            "temperature": 0.7,
        }
    else:
        # Managed deployment (Azure OpenAI) — model in URL
        url = f"{base}/openai/deployments/{model_name}/chat/completions?api-version={settings.mibuddy_api_version}"
        body = {
            "messages": [{"role": "user", "content": user_prompt}],
            "max_tokens": 200,
            "temperature": 1,
        }

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "api-key": api_key,
                },
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Parse suggestions (one per line)
        suggestions = [
            line.strip().lstrip("0123456789.-) ")
            for line in content.strip().split("\n")
            if line.strip() and len(line.strip()) > 3
        ]

        return suggestions[:5]

    except Exception as e:
        logger.debug(f"[Suggestions] Failed: {e}")
        return []
