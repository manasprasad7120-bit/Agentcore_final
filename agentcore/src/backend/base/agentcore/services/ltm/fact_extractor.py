"""LTM Fact/Entity Extractor.

Uses an LLM (from settings config or passed directly) to extract entities
and relationships from conversation summaries.
"""

from __future__ import annotations

import json

from loguru import logger

EXTRACTION_PROMPT = """\
Extract entities and relationships from this conversation summary. \
Return ONLY a JSON object, no other text.

Example output:
{{"entities": [{{"name": "John", "type": "PERSON", "description": "Software developer"}}], "relationships": [{{"source": "John", "target": "Python", "type": "USES", "description": "uses for work", "weight": 0.8}}]}}

Entity types: PERSON, TOPIC, TOOL, CONCEPT, PREFERENCE, DECISION, PROJECT, TECHNOLOGY, ORGANIZATION
Relationship types: RELATED_TO, DISCUSSED, PREFERS, DECIDED, USES, WORKS_ON, ASKED_ABOUT

Summary:
{summary_text}

Return ONLY the JSON object:"""


def _get_ltm_llm(agent_id: str | None = None):
    """Build a MicroserviceChatModel — reuses the auto-discovery from summarizer."""
    from agentcore.services.ltm.summarizer import _get_ltm_llm as _get_llm
    return _get_llm(agent_id=agent_id)


def _parse_llm_json(raw: str) -> dict:
    """Robustly parse JSON from LLM response, handling markdown fences and common issues."""
    text = raw.strip()

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    if "```" in text:
        import re
        # Extract content between code fences
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try extracting JSON object from surrounding text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            result = json.loads(text[start:end])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Try fixing common issues: trailing commas, single quotes
    try:
        import re
        cleaned = text[start:end] if start >= 0 else text
        # Remove trailing commas before } or ]
        cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, Exception):
        pass

    logger.warning(f"[LTM] Failed to parse JSON from LLM response. Raw text:\n{raw[:500]}")
    return {"entities": [], "relationships": []}


async def extract_facts(summary: str, llm=None, agent_id: str | None = None) -> dict:
    """Extract entities and relationships from a conversation summary.

    Args:
        summary: A conversation summary text.
        llm: Optional LangChain BaseChatModel. If None, uses LTM settings to create one.
        agent_id: Optional agent ID to discover the LLM from the agent's flow.

    Returns:
        Dict with "entities" and "relationships" lists.
    """
    if not summary:
        return {"entities": [], "relationships": []}

    if llm is None:
        llm = _get_ltm_llm(agent_id=agent_id)

    prompt = EXTRACTION_PROMPT.format(summary_text=summary)

    try:
        response = await llm.ainvoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        logger.info(f"[LTM] === RAW FACT EXTRACTOR RESPONSE ===\n{raw}\n=== END RAW ===")
        result = _parse_llm_json(raw)

        entities = result.get("entities", [])
        relationships = result.get("relationships", [])
        logger.info(f"[LTM] Extracted {len(entities)} entities and {len(relationships)} relationships")
        for e in entities:
            logger.info(f"[LTM]   Entity: {e.get('name')} ({e.get('type')}) — {e.get('description', '')}")
        for r in relationships:
            logger.info(f"[LTM]   Rel: {r.get('source')} --[{r.get('type')}]--> {r.get('target')} — {r.get('description', '')}")
        return result
    except Exception as e:
        logger.error(f"[LTM] Fact extraction failed: {e}")
        raise
