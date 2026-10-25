"""Known model capabilities database.

Maps model name patterns to their capabilities. This is used for auto-detection
when admins register models without explicitly setting capabilities.

Providers don't expose capability metadata via API, so we maintain a curated
database of known models — same approach used by LangChain, LiteLLM, etc.

To add a new model: add an entry to KNOWN_MODELS with its capabilities.
Explicit capabilities set in the Model Registry always override these defaults.
"""

from __future__ import annotations


# Capability flags
REASONING = "reasoning"
SUPPORTS_THINKING = "supports_thinking"
VISION = "supports_vision"
TOOL_CALLING = "supports_tool_calling"
STREAMING = "supports_streaming"
WEB_SEARCH = "web_search"
IMAGE_GEN = "image_generation"


def _caps(**kwargs) -> dict:
    """Helper to build a capabilities dict with streaming=True default."""
    return {STREAMING: True, **kwargs}


# ---------------------------------------------------------------------------
# Known models database
# Each key is a substring match against model_name (lowercased).
# More specific patterns should come first (checked in order).
# ---------------------------------------------------------------------------

KNOWN_MODELS: list[tuple[str, dict]] = [
    # ── OpenAI Reasoning Models ──
    # These models reason internally but OpenAI does NOT expose reasoning text in the API.
    # reasoning=True means the model reasons, supports_thinking=False means thinking is NOT visible.
    ("o1-preview",      _caps(**{REASONING: True, TOOL_CALLING: True})),
    ("o1-mini",         _caps(**{REASONING: True, TOOL_CALLING: True})),
    ("o1",              _caps(**{REASONING: True, TOOL_CALLING: True})),
    ("o3-mini",         _caps(**{REASONING: True, TOOL_CALLING: True})),
    ("o3",              _caps(**{REASONING: True, TOOL_CALLING: True})),
    ("o4-mini",         _caps(**{REASONING: True, TOOL_CALLING: True, VISION: True})),

    # ── OpenAI GPT Models ──
    ("gpt-5",           _caps(**{VISION: True, TOOL_CALLING: True})),
    ("gpt-4.1",         _caps(**{VISION: True, TOOL_CALLING: True})),
    ("gpt-4o",          _caps(**{VISION: True, TOOL_CALLING: True})),
    ("gpt-4-turbo",     _caps(**{VISION: True, TOOL_CALLING: True})),
    ("gpt-4-vision",    _caps(**{VISION: True, TOOL_CALLING: True})),
    ("gpt-4",           _caps(**{TOOL_CALLING: True})),
    ("gpt-3.5",         _caps(**{TOOL_CALLING: True})),

    # ── OpenAI Image Models ──
    ("dall-e-3",        _caps(**{IMAGE_GEN: True})),
    ("dall-e-2",        _caps(**{IMAGE_GEN: True})),

    # ── Anthropic Claude Models ──
    ("claude-opus",     _caps(**{REASONING: True, SUPPORTS_THINKING: True, VISION: True, TOOL_CALLING: True})),
    ("claude-sonnet",   _caps(**{REASONING: True, SUPPORTS_THINKING: True, VISION: True, TOOL_CALLING: True})),
    ("claude-haiku",    _caps(**{VISION: True, TOOL_CALLING: True})),
    ("claude-3",        _caps(**{VISION: True, TOOL_CALLING: True})),
    ("claude",          _caps(**{TOOL_CALLING: True})),

    # ── Google Gemini Models ──
    ("gemini-2.5-flash-image", _caps(**{IMAGE_GEN: True, VISION: True})),
    ("gemini-2.5",      _caps(**{REASONING: True, SUPPORTS_THINKING: True, VISION: True, TOOL_CALLING: True, WEB_SEARCH: True})),
    ("gemini-2.0",      _caps(**{VISION: True, TOOL_CALLING: True, WEB_SEARCH: True})),
    ("gemini-1.5-pro",  _caps(**{VISION: True, TOOL_CALLING: True, WEB_SEARCH: True})),
    ("gemini-1.5",      _caps(**{VISION: True, TOOL_CALLING: True, WEB_SEARCH: True})),
    ("gemini-3",        _caps(**{REASONING: True, SUPPORTS_THINKING: True, VISION: True, TOOL_CALLING: True, WEB_SEARCH: True})),
    ("gemini",          _caps(**{VISION: True, TOOL_CALLING: True})),

    # ── DeepSeek Models ──
    ("deepseek-r1",     _caps(**{REASONING: True, SUPPORTS_THINKING: True})),
    ("deepseek-v3",     _caps(**{TOOL_CALLING: True})),
    ("deepseek-chat",   _caps(**{TOOL_CALLING: True})),
    ("deepseek-coder",  _caps(**{TOOL_CALLING: True})),
    ("deepseek",        _caps()),

    # ── Groq Models ──
    ("llama-3.3",       _caps(**{TOOL_CALLING: True})),
    ("llama-3.2",       _caps(**{VISION: True, TOOL_CALLING: True})),
    ("llama-3.1",       _caps(**{TOOL_CALLING: True})),
    ("llama",           _caps()),
    ("mixtral",         _caps(**{TOOL_CALLING: True})),
    ("gemma",           _caps()),

    # ── Mistral Models ──
    ("mistral-large",   _caps(**{VISION: True, TOOL_CALLING: True})),
    ("mistral-medium",  _caps(**{TOOL_CALLING: True})),
    ("mistral-small",   _caps(**{TOOL_CALLING: True})),
    ("mistral",         _caps()),

    # ── Grok Models ──
    ("grok-3",          _caps(**{REASONING: True, SUPPORTS_THINKING: True, VISION: True, TOOL_CALLING: True})),
    ("grok-2",          _caps(**{VISION: True, TOOL_CALLING: True})),
    ("grok",            _caps(**{TOOL_CALLING: True})),

    # ── Cohere Models ──
    ("command-r-plus",  _caps(**{TOOL_CALLING: True})),
    ("command-r",       _caps(**{TOOL_CALLING: True})),
    ("command",         _caps()),

    # ── Nano Banana ──
    ("nano-banana",     _caps(**{IMAGE_GEN: True})),
]


def detect_capabilities(
    provider: str,
    model_name: str,
    explicit_capabilities: dict | None = None,
    provider_config: dict | None = None,
) -> dict:
    """Detect model capabilities using the known models database.

    Priority:
    1. Explicit capabilities from the Model Registry (admin-set)
    2. Known models database match (model_name or azure_deployment pattern)
    3. Provider-level defaults (basic fallback)

    Args:
        provider: Model provider (openai, anthropic, google, etc.)
        model_name: Model name/ID (gpt-5.1, claude-sonnet-4-6, etc.)
        explicit_capabilities: Capabilities set explicitly in the registry.
        provider_config: Provider-specific config (may contain azure_deployment).

    Returns:
        Merged capabilities dict.
    """
    # Normalize — treat "Gemini 3 Pro", "gemini-3-pro", "gemini_3_pro" as equal
    def _norm(s: str) -> str:
        return (s or "").lower().replace("_", "").replace("-", "").replace(" ", "")

    m = (model_name or "").lower()
    m_norm = _norm(model_name)
    p = (provider or "").lower()
    detected: dict = {STREAMING: True}

    # For Azure, also check azure_deployment name (may differ from model_name)
    azure_deployment = ""
    azure_deployment_norm = ""
    if provider_config and p == "azure":
        azure_deployment = (provider_config.get("azure_deployment") or "").lower()
        azure_deployment_norm = _norm(azure_deployment)

    # Step 1: Match against known models database (compare both raw and normalized)
    matched = False
    for pattern, caps in KNOWN_MODELS:
        pattern_norm = _norm(pattern)
        if (
            pattern in m
            or (azure_deployment and pattern in azure_deployment)
            or (pattern_norm and pattern_norm in m_norm)
            or (azure_deployment_norm and pattern_norm and pattern_norm in azure_deployment_norm)
        ):
            detected.update(caps)
            matched = True
            break

    # Step 2: Provider-level defaults (if no known model matched)
    if not matched:
        if p in ("openai", "azure"):
            detected[TOOL_CALLING] = True
        if p == "anthropic":
            detected[TOOL_CALLING] = True
            detected[VISION] = True
        if p == "google":
            detected[TOOL_CALLING] = True
            detected[VISION] = True

    # Step 3: Merge — explicit capabilities from registry always win
    if explicit_capabilities:
        detected.update({k: v for k, v in explicit_capabilities.items() if v is not None})

    return detected
