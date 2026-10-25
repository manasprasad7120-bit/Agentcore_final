"""LTM Retriever.

Retrieves long-term memory context from Pinecone (semantic summaries)
and/or Neo4j (entity/relationship graph) using direct connections.

Data isolation: all retrieval is scoped by session_id so each session's
summaries are completely isolated. No cross-session data sharing.
"""

from __future__ import annotations

from loguru import logger


async def _embed_query(query: str) -> list[float]:
    """Generate embedding using the configured provider (OpenAI or Azure OpenAI)."""
    from agentcore.services.ltm.embeddings import embed_single
    return await embed_single(query)


async def retrieve_from_pinecone(query: str, session_id: str, top_k: int = 5, env: str = "Dev") -> list[str]:
    """Retrieve relevant conversation summaries from Pinecone for this session."""
    from agentcore.services.deps import get_settings_service

    settings = get_settings_service().settings
    if not settings.ltm_pinecone_api_key:
        logger.debug("[LTM] LTM_PINECONE_API_KEY not configured, skipping Pinecone retrieval")
        return []

    try:
        from pinecone import Pinecone

        pc = Pinecone(api_key=settings.ltm_pinecone_api_key)
        index_name = settings.ltm_pinecone_index

        existing = [idx.name for idx in pc.list_indexes()]
        if index_name not in existing:
            logger.debug(f"[LTM] Pinecone index={index_name} does not exist yet")
            return []

        index = pc.Index(index_name)
        query_embedding = await _embed_query(query)
        if not query_embedding:
            return []

        # Namespace by session_id — data isolation is per session
        namespace = f"{session_id}"

        logger.info(f"[LTM] Pinecone query: namespace={namespace}, top_k={top_k}")

        results = index.query(
            namespace=namespace,
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True,
        )

        summaries = []
        for match in results.get("matches", []):
            meta = match.get("metadata", {})
            text = meta.get("summary", "")
            score = match.get("score", 0)
            if text:
                summaries.append(text)
                logger.debug(f"[LTM] Pinecone match: score={score:.3f}, session={session_id}")

        logger.info(f"[LTM] === PINECONE RETRIEVAL ===")
        logger.info(f"[LTM] Pinecone namespace={namespace}, retrieved {len(summaries)} summaries for session={session_id}")
        for i, s in enumerate(summaries):
            logger.info(f"[LTM]   Pinecone[{i}]: {s[:200]}...")
        logger.info(f"[LTM] === END PINECONE RETRIEVAL ===")
        return summaries
    except Exception as e:
        logger.error(f"[LTM] Pinecone retrieval failed: {e}")
        return []


async def retrieve_from_neo4j(query: str, session_id: str, top_k: int = 5, env: str = "Dev") -> list[str]:
    """Retrieve relevant facts/entities from Neo4j graph for this session."""
    from agentcore.services.deps import get_settings_service

    settings = get_settings_service().settings
    if not settings.ltm_neo4j_uri:
        logger.debug("[LTM] LTM_NEO4J_URI not configured, skipping Neo4j retrieval")
        return []

    # Namespace by session_id — data isolation is per session
    graph_kb_id = f"{settings.ltm_neo4j_graph_kb_id}_{session_id}"

    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            settings.ltm_neo4j_uri,
            auth=(settings.ltm_neo4j_username, settings.ltm_neo4j_password),
        )

        keywords = [w.lower() for w in query.split() if len(w) > 3]
        facts = []

        logger.info(f"[LTM] Neo4j query: graph_kb_id={graph_kb_id}, keywords={keywords[:5]}")

        with driver.session(database=settings.ltm_neo4j_database) as session:
            for keyword in keywords[:5]:
                result = session.run(
                    "MATCH (e:__Entity__ {graph_kb_id: $graph_kb_id}) "
                    "WHERE toLower(e.name) CONTAINS $keyword "
                    "   OR toLower(e.description) CONTAINS $keyword "
                    "OPTIONAL MATCH (e)-[r:RELATED_TO]-(neighbor:__Entity__ {graph_kb_id: $graph_kb_id}) "
                    "RETURN e.name AS name, e.type AS type, e.description AS description, "
                    "       collect(DISTINCT {name: neighbor.name, rel: r.type}) AS neighbors "
                    "LIMIT $top_k",
                    keyword=keyword, graph_kb_id=graph_kb_id, top_k=top_k,
                )

                for record in result:
                    name = record["name"]
                    desc = record["description"] or ""
                    etype = record["type"] or ""
                    fact = f"{name} ({etype}): {desc}" if desc else f"{name} ({etype})"
                    if fact not in facts:
                        facts.append(fact)
                    for neighbor in record["neighbors"] or []:
                        n_name = neighbor.get("name", "")
                        if n_name:
                            rel_fact = f"{name} --[{neighbor.get('rel', 'RELATED_TO')}]--> {n_name}"
                            if rel_fact not in facts:
                                facts.append(rel_fact)

        driver.close()
        logger.info(f"[LTM] === NEO4J RETRIEVAL ===")
        logger.info(f"[LTM] Neo4j retrieved {len(facts)} facts for session={session_id}")
        for i, f in enumerate(facts[:top_k * 3]):
            logger.info(f"[LTM]   Neo4j[{i}]: {f}")
        logger.info(f"[LTM] === END NEO4J RETRIEVAL ===")
        return facts[:top_k * 3]
    except Exception as e:
        logger.error(f"[LTM] Neo4j retrieval failed: {e}")
        return []


async def _get_playground_sessions(agent_id: str) -> list[str]:
    """Get all distinct session_ids for an agent from the dev conversation table.

    Used for cross-session LTM in playground mode. Safe because only the agent
    owner can access private agents.
    """
    from uuid import UUID
    from sqlalchemy import func
    from sqlmodel import select
    from agentcore.services.deps import session_scope

    try:
        from agentcore.services.database.models.conversation.model import ConversationTable

        async with session_scope() as session:
            stmt = (
                select(ConversationTable.session_id)
                .where(ConversationTable.agent_id == UUID(agent_id))
                .group_by(ConversationTable.session_id)
                .order_by(func.max(ConversationTable.timestamp).desc())
                .limit(50)
            )
            results = await session.exec(stmt)
            sessions = [r for r in results.all()]
            logger.info(f"[LTM] Found {len(sessions)} playground sessions for agent={agent_id}")
            return sessions
    except Exception as e:
        logger.error(f"[LTM] Failed to get playground sessions: {e}")
        return []


async def _get_orch_sessions(user_id: str, agent_id: str) -> list[str]:
    """Get all distinct session_ids for a user+agent from orch_conversation.

    Used for cross-session LTM in orchestrator mode. Scoped by user_id so
    User A never sees User B's sessions.
    """
    from uuid import UUID
    from sqlalchemy import func
    from sqlmodel import select
    from agentcore.services.deps import session_scope

    try:
        from agentcore.services.database.models.orch_conversation.model import OrchConversationTable

        async with session_scope() as session:
            stmt = (
                select(OrchConversationTable.session_id)
                .where(OrchConversationTable.user_id == UUID(user_id))
                .where(OrchConversationTable.agent_id == UUID(agent_id))
                .group_by(OrchConversationTable.session_id)
                .order_by(func.max(OrchConversationTable.timestamp).desc())
                .limit(50)
            )
            results = await session.exec(stmt)
            sessions = [r for r in results.all()]
            logger.info(f"[LTM] Found {len(sessions)} orch sessions for user={user_id}, agent={agent_id}")
            return sessions
    except Exception as e:
        logger.error(f"[LTM] Failed to get orch sessions: {e}")
        return []


async def _get_uat_api_sessions(agent_id: str) -> list[str]:
    """Get all distinct session_ids for an agent from conversation_uat.

    Used for cross-session LTM when a UAT agent is called via direct API.
    """
    from uuid import UUID
    from sqlalchemy import func
    from sqlmodel import select
    from agentcore.services.deps import session_scope

    try:
        from agentcore.services.database.models.conversation_uat.model import ConversationUATTable

        async with session_scope() as session:
            stmt = (
                select(ConversationUATTable.session_id)
                .where(ConversationUATTable.agent_id == UUID(agent_id))
                .group_by(ConversationUATTable.session_id)
                .order_by(func.max(ConversationUATTable.timestamp).desc())
                .limit(50)
            )
            results = await session.exec(stmt)
            sessions = [r for r in results.all()]
            logger.info(f"[LTM] Found {len(sessions)} UAT API sessions for agent={agent_id}")
            return sessions
    except Exception as e:
        logger.error(f"[LTM] Failed to get UAT API sessions: {e}")
        return []


async def _get_prod_api_sessions(agent_id: str) -> list[str]:
    """Get all distinct session_ids for an agent from conversation_prod.

    Used for cross-session LTM when a PROD agent is called via direct API.
    """
    from uuid import UUID
    from sqlalchemy import func
    from sqlmodel import select
    from agentcore.services.deps import session_scope

    try:
        from agentcore.services.database.models.conversation_prod.model import ConversationProdTable

        async with session_scope() as session:
            stmt = (
                select(ConversationProdTable.session_id)
                .where(ConversationProdTable.agent_id == UUID(agent_id))
                .group_by(ConversationProdTable.session_id)
                .order_by(func.max(ConversationProdTable.timestamp).desc())
                .limit(50)
            )
            results = await session.exec(stmt)
            sessions = [r for r in results.all()]
            logger.info(f"[LTM] Found {len(sessions)} PROD API sessions for agent={agent_id}")
            return sessions
    except Exception as e:
        logger.error(f"[LTM] Failed to get PROD API sessions: {e}")
        return []


async def retrieve_cross_session(
    query: str,
    session_ids: list[str],
    mode: str = "Both",
    pinecone_top_k: int = 5,
    neo4j_top_k: int = 10,
    env: str = "Dev",
) -> str:
    """Query Pinecone/Neo4j across multiple session namespaces, merge results.

    Used when cross-session LTM sharing is enabled. Queries each session's
    namespace separately and merges results sorted by relevance score.
    """
    from agentcore.services.deps import get_settings_service

    settings = get_settings_service().settings
    all_summaries: list[tuple[float, str]] = []
    all_facts: list[str] = []
    logger.info(f"[LTM] Cross-session retrieval: {len(session_ids)} sessions, mode={mode}")

    if mode in ("Pinecone Only", "Both") and settings.ltm_pinecone_api_key:
        try:
            from pinecone import Pinecone

            query_embedding = await _embed_query(query)
            if query_embedding:
                pc = Pinecone(api_key=settings.ltm_pinecone_api_key)
                index_name = settings.ltm_pinecone_index
                existing = [idx.name for idx in pc.list_indexes()]
                if index_name in existing:
                    index = pc.Index(index_name)
                    for sid in session_ids:
                        namespace = f"{sid}"
                        try:
                            results = index.query(
                                namespace=namespace,
                                vector=query_embedding,
                                top_k=pinecone_top_k,
                                include_metadata=True,
                            )
                            for match in results.get("matches", []):
                                text = match.get("metadata", {}).get("summary", "")
                                score = match.get("score", 0)
                                if text:
                                    all_summaries.append((score, text))
                        except Exception as e:
                            logger.debug(f"[LTM] Pinecone query failed for namespace={namespace}: {e}")

            # Sort by score descending, deduplicate, take top_k
            all_summaries.sort(key=lambda x: x[0], reverse=True)
            seen = set()
            unique_summaries = []
            for score, text in all_summaries:
                if text not in seen:
                    seen.add(text)
                    unique_summaries.append(text)
                    if len(unique_summaries) >= pinecone_top_k:
                        break

            logger.info(f"[LTM] Cross-session Pinecone: {len(unique_summaries)} summaries from {len(session_ids)} sessions")
            all_summaries_final = unique_summaries
        except Exception as e:
            logger.error(f"[LTM] Cross-session Pinecone retrieval failed: {e}")
            all_summaries_final = []
    else:
        all_summaries_final = []

    if mode in ("Neo4j Only", "Both") and settings.ltm_neo4j_uri:
        for sid in session_ids:
            try:
                facts = await retrieve_from_neo4j(query, sid, neo4j_top_k, env)
                all_facts.extend(facts)
            except Exception as e:
                logger.debug(f"[LTM] Neo4j query failed for session={sid}: {e}")
        # Deduplicate preserving order
        all_facts = list(dict.fromkeys(all_facts))[:neo4j_top_k * 3]
        logger.info(f"[LTM] Cross-session Neo4j: {len(all_facts)} facts from {len(session_ids)} sessions")

    # Format result
    parts = []
    if all_summaries_final:
        parts.append("Relevant Past Conversations:\n" + "\n".join(f"- {s}" for s in all_summaries_final))
    if all_facts:
        parts.append("Known Facts & Relationships:\n" + "\n".join(f"- {f}" for f in all_facts))

    result = "\n\n".join(parts) if parts else ""
    if result:
        logger.info(f"[LTM] === FINAL CROSS-SESSION LTM CONTEXT ({len(result)} chars) ===\n{result}\n=== END LTM CONTEXT ===")
    return result


async def retrieve(
    query: str,
    session_id: str,
    mode: str = "Both",
    pinecone_top_k: int = 5,
    neo4j_top_k: int = 10,
    top_k: int | None = None,
    env: str | None = None,
    # Legacy parameter — ignored, kept for backward compatibility
    agent_id: str | None = None,
) -> str:
    """Main retrieval entry point.

    Scoped by session_id for data isolation. Automatically detects environment
    (PROD/UAT/Orchestrator/Dev) and queries the correct namespace.

    Args:
        query: Current user query.
        session_id: The session ID (data isolation key).
        mode: "Pinecone Only", "Neo4j Only", or "Both".
        pinecone_top_k: Number of summaries to retrieve from Pinecone.
        neo4j_top_k: Number of entities/relationships from Neo4j.
        top_k: Legacy param — if set, used for both pinecone_top_k and neo4j_top_k.
        env: Optional environment override. If None, auto-detected.
        agent_id: Legacy param — ignored (kept for backward compatibility).

    Returns:
        Formatted LTM context string.
    """
    if top_k is not None:
        pinecone_top_k = top_k
        neo4j_top_k = top_k

    logger.info(f"[LTM] Retrieval environment={env} for session={session_id}")

    parts = []

    if mode in ("Pinecone Only", "Both"):
        summaries = await retrieve_from_pinecone(query, session_id, pinecone_top_k, env=env)
        if summaries:
            parts.append("Relevant Past Conversations:\n" + "\n".join(f"- {s}" for s in summaries))

    if mode in ("Neo4j Only", "Both"):
        facts = await retrieve_from_neo4j(query, session_id, neo4j_top_k, env=env)
        if facts:
            parts.append("Known Facts & Relationships:\n" + "\n".join(f"- {f}" for f in facts))

    result = "\n\n".join(parts) if parts else ""
    if result:
        logger.info(f"[LTM] === FINAL LTM CONTEXT ({len(result)} chars) ===\n{result}\n=== END LTM CONTEXT ===")
    return result
