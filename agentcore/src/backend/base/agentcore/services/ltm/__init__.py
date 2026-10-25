"""Long Term Memory (LTM) service.

Single source of truth for all LTM default values.
These can be overridden via .env / Settings, but if not set, these defaults apply.
"""

LTM_DEFAULTS = {
    "enabled": True,
    "message_threshold": 2,
    "time_interval_minutes": 2,
    "max_summary_tokens": 100,
    "max_context_chars": 300,
    "pinecone_top_k": 5,
    "neo4j_top_k": 10,
}
