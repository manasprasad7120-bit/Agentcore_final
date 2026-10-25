"""LTM Background Processor Service.

Manages the Long Term Memory pipeline using in-memory tracking + Redis cache:
1. Tracks message counts per session_id (in-memory dict + Redis for persistence)
2. Marks sessions as "ready for processing" after N messages OR time interval
3. Actual processing happens inline when the Memory component runs with a connected LLM

Data isolation: LTM is scoped by session_id so each session's summaries are
completely isolated. No cross-session or cross-user data sharing.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID

from loguru import logger

from agentcore.services.base import Service

# Redis key prefixes for LTM state
LTM_COUNT_PREFIX = "ltm:msg_count:"


class LTMService(Service):
    """Service that tracks conversation activity and processes LTM inline.

    The LLM for summarization/fact extraction always comes from the agent's flow
    (connected via HandleInput on the Memory component). This service only:
    - Tracks message counts per session_id (in-memory + Redis)
    - Checks if threshold is reached
    - Runs the pipeline when called with an LLM by the Memory component
    """

    name = "ltm_service"

    def __init__(self) -> None:
        self._scheduler = None
        self._started = False
        self._sessions_in_progress: set[str] = set()
        # In-memory fallback when Redis is unavailable
        self._message_counts: dict[str, int] = defaultdict(int)

    def _get_redis(self):
        """Get Redis client if available."""
        try:
            from agentcore.services.deps import get_settings_service
            from agentcore.services.cache.redis_client import get_redis_client

            settings_service = get_settings_service()
            if settings_service.settings.cache_type == "redis":
                return get_redis_client(settings_service)
        except Exception:
            pass
        return None

    def _ensure_scheduler(self):
        if self._scheduler is None:
            try:
                from apscheduler.schedulers.asyncio import AsyncIOScheduler
                self._scheduler = AsyncIOScheduler()
            except ImportError:
                logger.warning("[LTM] APScheduler not installed. Time-based LTM triggers disabled.")

    def start(self) -> None:
        """Start the LTM service."""
        from agentcore.services.deps import get_settings_service

        settings = get_settings_service().settings
        if not settings.ltm_enabled:
            logger.info("[LTM] Service disabled (LTM_ENABLED=False)")
            self.set_ready()
            return

        self._ensure_scheduler()
        if self._scheduler and not self._started:
            interval_minutes = settings.ltm_time_interval_minutes
            self._scheduler.add_job(
                self._time_based_sweep,
                "interval",
                minutes=interval_minutes,
                id="ltm_time_sweep",
                replace_existing=True,
            )
            self._scheduler.start()
            self._started = True
            logger.info(
                f"[LTM] Service started | threshold={settings.ltm_message_threshold} msgs | "
                f"interval={interval_minutes} min"
            )
        self.set_ready()

    async def teardown(self) -> None:
        if self._scheduler and self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            logger.info("[LTM] Service shut down")

    async def on_message_stored(self, agent_id: str | UUID, session_id: str | None = None) -> None:
        """Called by ChatOutput after storing a message. Increments the message counter.

        Counter is keyed by session_id for data isolation — each session's LTM
        is completely separate. When the count reaches the threshold, the LTM
        pipeline is scheduled as a background task.
        """
        from agentcore.services.deps import get_settings_service

        settings = get_settings_service().settings
        if not settings.ltm_enabled:
            return

        session_id_str = str(session_id) if session_id else None
        if not session_id_str:
            return  # No session = no LTM tracking

        count = 0  # track final count for threshold check

        try:
            # Try Redis first, fall back to in-memory
            redis = self._get_redis()
            if redis:
                key = f"{LTM_COUNT_PREFIX}{session_id_str}"
                count = await redis.incr(key)
                # Set TTL of 24h so keys don't accumulate forever
                await redis.expire(key, 86400)
            else:
                self._message_counts[session_id_str] += 1
                count = self._message_counts[session_id_str]

            logger.info(f"[LTM] Message count for session={session_id_str}: {count}/{settings.ltm_message_threshold}")
        except Exception as e:
            # Fallback to in-memory
            self._message_counts[session_id_str] += 1
            count = self._message_counts[session_id_str]
            logger.debug(f"[LTM] on_message_stored (in-memory fallback): {e}")

        # Fire the pipeline when threshold is reached or exceeded, but only if not already running
        if count >= settings.ltm_message_threshold and session_id_str not in self._sessions_in_progress:
            logger.info(
                f"[LTM] Threshold reached ({count}/{settings.ltm_message_threshold}), "
                f"scheduling pipeline for session={session_id_str}"
            )
            asyncio.create_task(self.process_with_llm(session_id_str, agent_id=str(agent_id)))

    async def _time_based_sweep(self) -> None:
        """Periodic sweep: process sessions with pending messages that have reached the threshold."""
        from agentcore.services.deps import get_settings_service

        settings = get_settings_service().settings
        threshold = settings.ltm_message_threshold

        try:
            sessions_to_process = []
            redis = self._get_redis()
            if redis:
                async for key in redis.scan_iter(match=f"{LTM_COUNT_PREFIX}*", count=100):
                    val = await redis.get(key)
                    if val and int(val) >= threshold:
                        # Extract session_id from key: "ltm:msg_count:{session_id}"
                        session_id = key.decode() if isinstance(key, bytes) else key
                        session_id = session_id.replace(LTM_COUNT_PREFIX, "")
                        sessions_to_process.append(session_id)
            elif self._message_counts:
                for session_id, count in self._message_counts.items():
                    if count >= threshold:
                        sessions_to_process.append(session_id)

            if sessions_to_process:
                logger.info(f"[LTM] Time sweep: {len(sessions_to_process)} sessions ready for processing")
                for session_id in sessions_to_process:
                    logger.info(f"[LTM] Time sweep: scheduling pipeline for session={session_id}")
                    asyncio.create_task(self.process_with_llm(session_id))
        except Exception as e:
            logger.debug(f"[LTM] Time-based sweep failed: {e}")

    async def should_process(self, agent_id: str) -> bool:
        """Check if an agent has enough pending messages to trigger LTM processing."""
        from agentcore.services.deps import get_settings_service

        settings = get_settings_service().settings
        if not settings.ltm_enabled:
            return False

        try:
            redis = self._get_redis()
            if redis:
                key = f"{LTM_COUNT_PREFIX}{agent_id}"
                val = await redis.get(key)
                count = int(val) if val else 0
            else:
                count = self._message_counts.get(agent_id, 0)

            return count >= settings.ltm_message_threshold
        except Exception:
            return self._message_counts.get(agent_id, 0) >= settings.ltm_message_threshold

    async def process_with_llm(self, session_id: str, llm=None, agent_id: str | None = None) -> None:
        """Run the LTM pipeline for a specific session.

        Data isolation: each session's summaries are stored in a session-scoped
        Pinecone namespace and Neo4j graph_kb_id. No cross-session data sharing.

        Pipeline:
        1. Fetch unsummarized messages for this session
        2. Summarize via LLM
        3. Extract facts/entities via LLM
        4. Store entities to Neo4j (session-scoped)
        5. Store summary embedding to Pinecone (session-scoped)
        6. Mark messages as summarized, reset counter
        """
        logger.info(f"[LTM] process_with_llm called for session={session_id}")

        if session_id in self._sessions_in_progress:
            logger.info(f"[LTM] Skipping — session {session_id} already in progress")
            return

        self._sessions_in_progress.add(session_id)
        try:
            messages, env, message_ids, source_table = await self._get_recent_messages(session_id)
            if not messages:
                logger.info(f"[LTM] No recent messages found for session={session_id}, resetting counter")
                await self._reset_counter(session_id)
                return

            logger.info(f"[LTM] Processing {len(messages)} messages for session={session_id} (env={env}, source={source_table})")

            # 2. Summarize via LLM
            from agentcore.services.deps import get_settings_service
            max_summary_tokens = get_settings_service().settings.ltm_max_summary_tokens
            from agentcore.services.ltm.summarizer import summarize_conversation
            summary = await summarize_conversation(messages, llm, max_tokens=max_summary_tokens, agent_id=agent_id)
            if not summary:
                return

            # 3. Extract facts via LLM
            from agentcore.services.ltm.fact_extractor import extract_facts
            facts = await extract_facts(summary, llm, agent_id=agent_id)

            # 4. Store to Neo4j (session-scoped namespace, env for suffix)
            await self._store_to_neo4j(session_id, facts, env=env)

            # 5. Store summary to Pinecone (session-scoped namespace, env for suffix)
            await self._store_to_pinecone(session_id, summary, env=env)

            # 6. Mark messages as summarized in DB (source_table determines which table)
            await self._mark_messages_summarized(message_ids, source_table)

            # 7. Reset counter
            await self._reset_counter(session_id)

            logger.info(f"[LTM] ========== PIPELINE COMPLETED for session={session_id} ==========")
        except Exception as e:
            logger.error(f"[LTM] Pipeline failed for session={session_id}: {e}")
        finally:
            self._sessions_in_progress.discard(session_id)

    async def _get_recent_messages(self, session_id: str) -> tuple[list, str, list, str]:
        """Fetch messages not yet LTM-summarized for this session.

        DB query filters WHERE session_id = X AND ltm_summarized_at IS NULL.
        Returns (messages, env, row_ids, source_table).
        """
        all_messages, env, row_ids, source_table = await self._query_messages_by_priority(session_id)
        logger.info(f"[LTM] Found {len(all_messages)} unsummarized messages for session={session_id}")
        return all_messages, env, row_ids, source_table

    async def _query_messages_by_priority(self, session_id: str) -> tuple[list, str, list, str]:
        """Query unsummarized messages for this session from all tables (priority order).

        Priority:
          1. orch_conversation (deployed agents — both UAT & PROD)
          2. conversation_prod
          3. conversation_uat
          4. conversation (dev/playground — fallback)

        Returns (messages, environment_name, row_ids, source_table).
        - environment_name: "UAT"/"PROD"/"Dev" — for Pinecone/Neo4j namespace suffix
        - source_table: "Orchestrator"/"PROD"/"UAT"/"Dev" — for _mark_messages_summarized
        """
        from sqlmodel import col, select
        from agentcore.services.deps import session_scope
        from agentcore.schema.message import Message

        # 1. Check orch_conversation first (all deployed agents)
        try:
            from agentcore.services.database.models.orch_conversation.model import OrchConversationTable

            async with session_scope() as session:
                stmt = (
                    select(OrchConversationTable)
                    .where(OrchConversationTable.session_id == session_id)
                    .where(OrchConversationTable.error == False)  # noqa: E712
                    .where(OrchConversationTable.ltm_summarized_at.is_(None))
                    .order_by(col(OrchConversationTable.timestamp).asc())
                    .limit(1000)
                )
                results = await session.exec(stmt)
                rows = list(results.all())

                if rows:
                    env = await self._resolve_orch_environment(rows, session)
                    logger.info(
                        f"[LTM] Fetched {len(rows)} messages from orch_conversation "
                        f"(env={env}) for session={session_id}"
                    )
                    row_ids = [r.id for r in rows]
                    messages = [await Message.create(**r.model_dump()) for r in rows]
                    return messages, env, row_ids, "Orchestrator"
        except Exception as e:
            logger.debug(f"[LTM] Skipping orch_conversation: {e}")

        # 2. Check conversation_prod table
        try:
            from agentcore.services.database.models.conversation_prod.model import ConversationProdTable

            async with session_scope() as session:
                stmt = (
                    select(ConversationProdTable)
                    .where(ConversationProdTable.session_id == session_id)
                    .where(ConversationProdTable.error == False)  # noqa: E712
                    .where(ConversationProdTable.ltm_summarized_at.is_(None))
                    .order_by(col(ConversationProdTable.timestamp).asc())
                    .limit(1000)
                )
                results = await session.exec(stmt)
                rows = list(results.all())

                if rows:
                    logger.info(
                        f"[LTM] Fetched {len(rows)} messages from conversation_prod (PROD) "
                        f"for session={session_id}"
                    )
                    row_ids = [r.id for r in rows]
                    messages = [await Message.create(**r.model_dump()) for r in rows]
                    return messages, "PROD", row_ids, "PROD"
        except Exception as e:
            logger.debug(f"[LTM] Skipping conversation_prod: {e}")

        # 3. Check conversation_uat table
        try:
            from agentcore.services.database.models.conversation_uat.model import ConversationUATTable

            async with session_scope() as session:
                stmt = (
                    select(ConversationUATTable)
                    .where(ConversationUATTable.session_id == session_id)
                    .where(ConversationUATTable.error == False)  # noqa: E712
                    .where(ConversationUATTable.ltm_summarized_at.is_(None))
                    .order_by(col(ConversationUATTable.timestamp).asc())
                    .limit(1000)
                )
                results = await session.exec(stmt)
                rows = list(results.all())

                if rows:
                    logger.info(
                        f"[LTM] Fetched {len(rows)} messages from conversation_uat (UAT) "
                        f"for session={session_id}"
                    )
                    row_ids = [r.id for r in rows]
                    messages = [await Message.create(**r.model_dump()) for r in rows]
                    return messages, "UAT", row_ids, "UAT"
        except Exception as e:
            logger.debug(f"[LTM] Skipping conversation_uat: {e}")

        # 4. Fallback to dev conversation table
        try:
            from agentcore.services.database.models.conversation.model import ConversationTable

            async with session_scope() as session:
                stmt = (
                    select(ConversationTable)
                    .where(ConversationTable.session_id == session_id)
                    .where(ConversationTable.error == False)  # noqa: E712
                    .where(ConversationTable.ltm_summarized_at.is_(None))
                    .order_by(col(ConversationTable.timestamp).asc())
                    .limit(1000)
                )
                results = await session.exec(stmt)
                rows = list(results.all())

                if rows:
                    logger.info(
                        f"[LTM] Fetched {len(rows)} messages from conversation (Dev) "
                        f"for session={session_id}"
                    )
                    row_ids = [r.id for r in rows]
                    messages = [await Message.create(**r.model_dump()) for r in rows]
                    return messages, "Dev", row_ids, "Dev"
        except Exception as e:
            logger.debug(f"[LTM] Skipping conversation: {e}")

        return [], "Dev", [], "Dev"

    async def _resolve_orch_environment(self, rows: list, session) -> str:
        """Resolve PROD vs UAT from orch_conversation deployment_id.

        Checks the first row's deployment_id against AgentDeploymentProd first,
        then AgentDeploymentUAT. Falls back to 'Orchestrator'.
        """
        # Find the first row with a deployment_id
        deployment_id = None
        for row in rows:
            did = getattr(row, "deployment_id", None)
            if did:
                deployment_id = did
                break

        if not deployment_id:
            return "Orchestrator"

        # Check PROD first
        try:
            from agentcore.services.database.models.agent_deployment_prod.model import AgentDeploymentProd
            prod = await session.get(AgentDeploymentProd, deployment_id)
            if prod:
                return "PROD"
        except Exception:
            pass

        # Check UAT
        try:
            from agentcore.services.database.models.agent_deployment_uat.model import AgentDeploymentUAT
            uat = await session.get(AgentDeploymentUAT, deployment_id)
            if uat:
                return "UAT"
        except Exception:
            pass

        return "Orchestrator"

    async def _mark_messages_summarized(self, ids: list, env: str) -> None:
        """Mark messages as LTM-summarized in DB. Permanent — survives Redis flushes/TTL/restarts.

        Updates only the specific table the messages came from (determined by env).
        """
        if not ids:
            return

        uuid_ids = [UUID(str(i)) if not isinstance(i, UUID) else i for i in ids]
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            from sqlalchemy import update
            from agentcore.services.deps import session_scope
            from agentcore.services.database.models.conversation.model import ConversationTable
            from agentcore.services.database.models.orch_conversation.model import OrchConversationTable
            from agentcore.services.database.models.conversation_prod.model import ConversationProdTable
            from agentcore.services.database.models.conversation_uat.model import ConversationUATTable

            env_table_map = {
                "PROD": ConversationProdTable,
                "UAT": ConversationUATTable,
                "Orchestrator": OrchConversationTable,
                "Dev": ConversationTable,
            }
            model = env_table_map.get(env, ConversationTable)

            async with session_scope() as session:
                await session.execute(
                    update(model).where(model.id.in_(uuid_ids)).values(ltm_summarized_at=now)
                )
            logger.info(f"[LTM] Marked {len(uuid_ids)} messages as summarized in DB (table={model.__tablename__})")
        except Exception as e:
            logger.error(f"[LTM] Failed to mark messages summarized: {e}")

    async def _reset_counter(self, session_id: str) -> None:
        """Reset message counter after pipeline run."""
        try:
            redis = self._get_redis()
            if redis:
                await redis.set(f"{LTM_COUNT_PREFIX}{session_id}", 0)
            else:
                self._message_counts[session_id] = 0
        except Exception:
            self._message_counts[session_id] = 0

    async def _store_to_neo4j(self, session_id: str, facts: dict, env: str = "Dev") -> None:
        """Store extracted entities and relationships to Neo4j (direct connection).

        Namespaces by session_id + environment for complete data isolation.
        """
        from agentcore.services.deps import get_settings_service

        settings = get_settings_service().settings
        if not settings.ltm_neo4j_uri:
            logger.debug("[LTM] LTM_NEO4J_URI not configured, skipping Neo4j storage")
            return

        entities = facts.get("entities", [])
        relationships = facts.get("relationships", [])
        if not entities:
            return

        # Namespace by session_id — data isolation is per session
        graph_kb_id = f"{settings.ltm_neo4j_graph_kb_id}_{session_id}"

        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                settings.ltm_neo4j_uri,
                auth=(settings.ltm_neo4j_username, settings.ltm_neo4j_password),
            )

            with driver.session(database=settings.ltm_neo4j_database) as session:
                for entity in entities:
                    # Normalize name to lowercase to prevent case-sensitive duplicates
                    # (e.g., "Agentic AI" vs "agentic AI")
                    name = (entity.get("name", "") or "").strip()
                    if not name:
                        continue
                    session.run(
                        "MERGE (e:__Entity__ {name: toLower($name), graph_kb_id: $graph_kb_id}) "
                        "SET e.type = $type, e.description = $description, "
                        "e.display_name = $display_name, e.updated_at = datetime()",
                        name=name,
                        display_name=name,  # Keep original casing for display
                        type=entity.get("type", "CONCEPT"),
                        description=entity.get("description", ""),
                        graph_kb_id=graph_kb_id,
                    )

                for rel in relationships:
                    source = (rel.get("source", "") or "").strip()
                    target = (rel.get("target", "") or "").strip()
                    if not source or not target:
                        continue
                    session.run(
                        "MATCH (a:__Entity__ {name: toLower($source), graph_kb_id: $graph_kb_id}) "
                        "MATCH (b:__Entity__ {name: toLower($target), graph_kb_id: $graph_kb_id}) "
                        "MERGE (a)-[r:RELATED_TO]->(b) "
                        "SET r.type = $rel_type, r.description = $description, "
                        "r.weight = $weight, r.updated_at = datetime()",
                        source=source,
                        target=target,
                        rel_type=rel.get("type", "RELATED_TO"),
                        description=rel.get("description", ""),
                        weight=rel.get("weight", 0.5),
                        graph_kb_id=graph_kb_id,
                    )

            driver.close()
            logger.info(f"[LTM] === NEO4J STORAGE ===")
            logger.info(f"[LTM] Stored {len(entities)} entities + {len(relationships)} rels to Neo4j (graph_kb_id={graph_kb_id})")
            for e in entities:
                logger.info(f"[LTM]   Neo4j Entity: {e.get('name')} ({e.get('type')})")
            for r in relationships:
                logger.info(f"[LTM]   Neo4j Rel: {r.get('source')} --[{r.get('type')}]--> {r.get('target')}")
            logger.info(f"[LTM] === END NEO4J ===")
        except Exception as e:
            logger.error(f"[LTM] Neo4j ingestion failed for session={session_id}: {e}")

    async def _store_to_pinecone(self, session_id: str, summary: str, env: str = "Dev") -> None:
        """Store conversation summary embedding to Pinecone (direct connection).

        Namespaces by session_id + environment for complete data isolation.
        """
        from agentcore.services.deps import get_settings_service

        settings = get_settings_service().settings
        if not settings.ltm_pinecone_api_key:
            logger.debug("[LTM] LTM_PINECONE_API_KEY not configured, skipping Pinecone storage")
            return

        try:
            from pinecone import Pinecone, ServerlessSpec
            import hashlib

            pc = Pinecone(api_key=settings.ltm_pinecone_api_key)
            index_name = settings.ltm_pinecone_index

            existing = [idx.name for idx in pc.list_indexes()]
            if index_name not in existing:
                sample = await self._embed_text("test")
                dimension = len(sample)
                pc.create_index(
                    name=index_name,
                    dimension=dimension,
                    metric="cosine",
                    spec=ServerlessSpec(
                        cloud=settings.ltm_pinecone_cloud,
                        region=settings.ltm_pinecone_region,
                    ),
                )
                logger.info(f"[LTM] Created Pinecone index={index_name} dim={dimension}")

            index = pc.Index(index_name)

            embedding = await self._embed_text(summary)

            # Namespace by session_id — data isolation is per session
            namespace = f"{session_id}"

            # Dedup check: query existing summaries with this embedding
            # If a very similar summary already exists (cosine > 0.95), skip storage
            try:
                existing = index.query(
                    namespace=namespace,
                    vector=embedding,
                    top_k=1,
                    include_metadata=True,
                )
                matches = existing.get("matches", [])
                if matches and matches[0].get("score", 0) > 0.95:
                    existing_preview = matches[0].get("metadata", {}).get("summary", "")[:100]
                    logger.info(f"[LTM] Pinecone dedup: similar summary exists (score={matches[0]['score']:.3f}), skipping. Existing: {existing_preview}...")
                    return
            except Exception:
                pass  # If dedup check fails, proceed with storage

            vec_id = hashlib.sha256(summary.encode()).hexdigest()[:16]
            timestamp = datetime.now(timezone.utc).isoformat()

            index.upsert(
                vectors=[{
                    "id": vec_id,
                    "values": embedding,
                    "metadata": {
                        "summary": summary[:40000],
                        "session_id": session_id,
                        "environment": env,
                        "timestamp": timestamp,
                    },
                }],
                namespace=namespace,
            )
            logger.info(f"[LTM] === PINECONE STORAGE ===")
            logger.info(f"[LTM] Stored summary to Pinecone index={index_name}, namespace={namespace}, vec_id={vec_id}")
            logger.info(f"[LTM] Summary preview: {summary[:200]}...")
            logger.info(f"[LTM] Embedding dimension: {len(embedding)}")
            logger.info(f"[LTM] === END PINECONE ===")
        except Exception as e:
            logger.error(f"[LTM] Pinecone ingestion failed for session={session_id}: {e}")

    async def _embed_text(self, text: str) -> list[float]:
        """Generate embedding using the configured provider (OpenAI or Azure OpenAI)."""
        from agentcore.services.ltm.embeddings import embed_single
        return await embed_single(text)

    async def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts using the configured provider."""
        from agentcore.services.ltm.embeddings import embed_batch
        return await embed_batch(texts)
