# Path: src/backend/base/agentcore/services/teams/bot_handler.py
"""Bot Framework activity handler for routing Teams messages to agentcore flows.

Follows the same pattern as api/a2a.py handle_message_send() for executing flows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from botbuilder.core import ActivityHandler, CardFactory, TurnContext
from botbuilder.schema import Activity, ActivityTypes, Attachment
from loguru import logger

from agentcore.services.teams.adaptive_cards import (
    error_card,
    text_response_card,
    welcome_card,
)

if TYPE_CHECKING:
    from agentcore.services.teams.conversation_store import ConversationStore


# Exception types whose ``str()`` representation is known to be safe to show
# to an external Teams user — the message is descriptive and doesn't leak
# internal detail. Anything else gets a generic message; the full traceback
# still goes to the server log via ``logger.exception``.
_SAFE_USER_FACING_TYPES = (
    "ConnectorPermissionError",
    "ValueError",
    "PermissionError",
)


# Adaptive Card body text rendering is capped by Teams; the documented
# safe limit for a single TextBlock display is ~4000 characters, and the
# whole card JSON payload is capped at ~28KB. Truncate long agent output
# before it reaches the card so:
#   1. The card always renders (never silently fails to display)
#   2. The user sees a clear marker that more content exists upstream
#   3. The server log retains the full content for support diagnostics
_TEAMS_MAX_TEXT = 3500  # leaves headroom for the agent-name + truncation suffix
_TEAMS_TRUNCATION_NOTICE = (
    "\n\n_(Response truncated. The full response is too long for Teams. "
    "See the agent playground for the complete output.)_"
)


def _truncate_for_teams(text: str) -> str:
    """Truncate agent output to fit a single Adaptive Card TextBlock.

    Preserves the head of the message (where the answer / opening
    summary usually lives), drops the tail, and appends a clear
    notice so the user knows content was cut. Full text remains in
    the server logs via the caller's flow execution log.
    """
    if not text:
        return text
    if len(text) <= _TEAMS_MAX_TEXT:
        return text
    return text[:_TEAMS_MAX_TEXT].rstrip() + _TEAMS_TRUNCATION_NOTICE


# ── Output sanitization (Teams-only defensive guard) ──────────────────────
#
# ``api/a2a.py:_extract_output_text`` has an exception-branch fallback that
# returns ``str(run_outputs)`` — the Python repr of the raw output list.
# For Teams the worst case looks like::
#
#     [VertexBuildResult(result_dict={'foo': 'bar'}, valid=True,
#      vertex=<LangGraphVertex object at 0x7f9c12345678>)]
#
# Showing that as an Adaptive Card body looks exactly like the "raw code"
# leak we want to avoid. We add a *Teams-only* defensive check here so
# the A2A protocol path (and any other consumer of ``_extract_output_text``)
# is unaffected — only the Adaptive Card that goes to a Teams user gets
# sanitized.
#
# Detection is conservative: two unmistakable Python-repr signals. Both
# never appear in natural-language LLM output:
#
#   1. ``object at 0x<hex>``      — Python default ``__repr__`` for objects
#                                    without a custom ``__str__``.
#   2. ``[<ClassName>(`` at start — list-of-namedtuples / dataclass repr,
#                                    which is what ``str(run_outputs)``
#                                    produces for VertexBuildResult lists.

import re as _re

_PYTHON_REPR_SIGNAL = _re.compile(
    r"object at 0x[0-9a-fA-F]+"            # memory-address pattern
    r"|^\s*\[\s*[A-Z][\w.]*\("              # list of class-call reprs
    r"|^\s*<[A-Z][\w.]+\s",                  # leading <ClassName ...> repr
)
_OUTPUT_REPR_FALLBACK = (
    "I processed your request but couldn't format the response. "
    "Please try rephrasing your question."
)


def _looks_like_python_repr(text: str) -> bool:
    """Return True iff ``text`` matches a Python ``repr()`` signature.

    Used by Teams to decide whether the upstream output extractor fell
    back to ``str(run_outputs)`` and is about to expose internal object
    structure to the end user. Conservative: misses are far worse than
    rare false positives on contrived inputs (a user asking "what does
    `<Class object at 0x...>` mean?" would get the safe message, which
    is acceptable since that question is exceedingly unlikely in a
    customer-facing chat).
    """
    if not text:
        return False
    return bool(_PYTHON_REPR_SIGNAL.search(text))


def _sanitize_agent_output_for_teams(text: str) -> str:
    """Make agent output safe to display as a Teams Adaptive Card body.

    Two-layer defence:

      1. If the upstream extractor fell back to a Python ``repr()`` of
         internal objects (memory addresses, class-call lists, leading
         ``<Class ...>``), replace with a generic user-facing fallback
         message. Full text stays in the server log via the call-site
         ``logger.info``.
      2. Otherwise, truncate long output to fit a single Adaptive Card
         TextBlock (Teams' display cap is ~4000 chars).
    """
    if _looks_like_python_repr(text):
        logger.warning(
            f"Teams output sanitizer caught a Python repr leak "
            f"(first 200 chars: {text[:200]!r}). Replacing with "
            f"safe fallback."
        )
        return _OUTPUT_REPR_FALLBACK
    return _truncate_for_teams(text)


def _sanitize_error_for_teams(exc: Exception) -> str:
    """Map an internal exception to a user-safe Teams-visible message.

    Three rules:

      * Known-safe exceptions (ConnectorPermissionError, ValueError,
        PermissionError) → their str() is descriptive by design (the
        connector helpers already produce *"Mail.Send permission not
        granted on this connector's app registration"* style text).
        Return it verbatim.
      * httpx.HTTPStatusError → return a generic "external service"
        message. The raw URL can carry query-string secrets and the
        body is upstream-defined; don't pass either through to the
        end user. Operators see the full detail in the server log.
      * Anything else → return a generic message and let the
        ``logger.exception`` call at the call site capture the full
        traceback for ops.

    Class name and Python typename are deliberately NOT included so a
    Teams user never sees ``KeyError`` / ``AttributeError`` /
    ``psycopg2.OperationalError`` (the last of which can include the
    database DSN with credentials).
    """
    exc_type_name = type(exc).__name__
    if exc_type_name in _SAFE_USER_FACING_TYPES:
        text = str(exc).strip()
        if text:
            return text
        # Fall through to generic on empty str (rare)
    # httpx errors carry the URL — never echo
    if exc_type_name in ("HTTPStatusError", "RequestError", "ConnectError",
                          "ReadTimeout", "ConnectTimeout"):
        return (
            "The agent could not reach an external service. Please try "
            "again in a moment. If this keeps happening, contact your "
            "administrator."
        )
    # Database / driver errors can include DSNs with credentials
    if any(
        token in exc_type_name
        for token in ("OperationalError", "ProgrammingError",
                       "InterfaceError", "InternalError", "DataError",
                       "IntegrityError", "DatabaseError")
    ):
        return (
            "The agent service is temporarily unavailable. Please try "
            "again in a moment."
        )
    # Catch-all for anything else (KeyError, AttributeError, RuntimeError…)
    return (
        "Something went wrong while processing your request. Please "
        "try again. If this keeps happening, contact your "
        "administrator."
    )


class AgentCoreTeamsBot(ActivityHandler):
    """Handles incoming Bot Framework activities and routes them to agentcore flows.

    Translates Bot Framework activities into agentcore flow executions,
    following the same pattern as the A2A protocol handler.
    """

    def __init__(self, conversation_store: ConversationStore):
        super().__init__()
        self.conversation_store = conversation_store

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        """Handle incoming message from Teams user."""
        logger.info("=== on_message_activity called ===")
        conversation_id = turn_context.activity.conversation.id
        user_text = turn_context.activity.text or ""
        user_name = turn_context.activity.from_property.name if turn_context.activity.from_property else None

        logger.info(f"Teams message received: conversation={conversation_id}, user={user_name}, text={user_text[:100]}")

        # Look up which agent/flow this conversation is mapped to
        state = await self.conversation_store.get_mapping(conversation_id)

        if not state:
            logger.info(f"No existing mapping for conversation {conversation_id}, resolving agent...")
            agent_id = await self._resolve_agent_from_channel_data(turn_context)
            if agent_id == self.AMBIGUOUS_ROUTING:
                # Multiple agents share the same bot — tell the user
                # clearly rather than silently routing to the wrong one.
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text=(
                            "I can't tell which agent this message is for — "
                            "more than one agent is published under the same "
                            "Teams bot. Please ask your administrator to "
                            "publish each agent with a dedicated bot, or "
                            "remove all but one published agent."
                        ),
                    )
                )
                return
            if agent_id:
                state = await self.conversation_store.set_mapping(
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    user_display_name=user_name,
                    user_aad_object_id=self._get_aad_object_id(turn_context),
                )
            else:
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text="Sorry, I couldn't determine which agent to route your message to. "
                        "Please reinstall the app or contact your administrator.",
                    )
                )
                return

        logger.info(f"Agent resolved: agent_id={state.agent_id}, session_id={state.session_id}")

        # Execute the flow
        try:
            output_text = await self._execute_flow(
                agent_id=state.agent_id,
                session_id=state.session_id,
                input_text=user_text,
            )

            # Send response as Adaptive Card. Run output through the
            # Teams-only sanitizer so:
            #   1. Python repr() leaks from the a2a extraction fallback
            #      (``str(run_outputs)`` returning VertexBuildResult dumps,
            #      ``<Object at 0x...>`` memory addresses, etc.) get
            #      replaced with a safe generic message.
            #   2. Long responses get truncated to fit Teams' ~4000-char
            #      TextBlock cap.
            agent_name = await self._get_agent_name(state.agent_id)
            safe_text = _sanitize_agent_output_for_teams(output_text)
            card = text_response_card(agent_name or "AgentCore", safe_text)
            attachment = CardFactory.adaptive_card(card)

            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    attachments=[attachment],
                )
            )

        except Exception as e:
            # Full traceback for ops only — sanitized message for the user.
            # We deliberately do NOT pass {e!s} into the card body because for
            # some exception types (httpx errors carrying request URLs with
            # query-string secrets, database driver errors carrying the DSN
            # with credentials, deep stack traces) the str() representation
            # leaks internal detail to an external Teams user.
            logger.exception(f"Error executing flow for conversation {conversation_id}: {e}")
            agent_name = await self._get_agent_name(state.agent_id)
            user_facing = _sanitize_error_for_teams(e)
            card = error_card(agent_name or "AgentCore", user_facing)
            attachment = CardFactory.adaptive_card(card)
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    attachments=[attachment],
                )
            )

    async def on_conversation_update_activity(self, turn_context: TurnContext) -> None:
        """Handle conversation update events (e.g., bot added to conversation)."""
        await self._handle_members_added(turn_context)

    async def on_members_added_activity(self, members_added, turn_context: TurnContext) -> None:
        """Send welcome message when the bot is added to a conversation."""
        bot_id = turn_context.activity.recipient.id if turn_context.activity.recipient else None

        for member in members_added:
            if member.id == bot_id:
                # Bot was added - set up conversation mapping and send welcome
                conversation_id = turn_context.activity.conversation.id
                agent_id = await self._resolve_agent_from_channel_data(turn_context)

                if agent_id:
                    user_name = (
                        turn_context.activity.from_property.name if turn_context.activity.from_property else None
                    )
                    await self.conversation_store.set_mapping(
                        conversation_id=conversation_id,
                        agent_id=agent_id,
                        user_display_name=user_name,
                        user_aad_object_id=self._get_aad_object_id(turn_context),
                    )

                    agent_name = await self._get_agent_name(agent_id)
                    agent_desc = await self._get_agent_description(agent_id)
                    card = welcome_card(agent_name or "AgentCore", agent_desc)
                    attachment = CardFactory.adaptive_card(card)

                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            attachments=[attachment],
                        )
                    )
                else:
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text="Welcome! This bot is connected to AgentCore. Send a message to get started.",
                        )
                    )

    async def _execute_flow(self, agent_id: str, session_id: str, input_text: str) -> str:
        """Execute an agentcore flow and return the output text.

        Follows the same pattern as a2a.py handle_message_send().
        """
        logger.info(f"=== _execute_flow: agent={agent_id}, session={session_id}, input={input_text[:50]} ===")
        from agentcore.api.a2a import _extract_output_text, _prebuild_dependencies
        from agentcore.helpers.agent import load_agent, run_agent

        # Look up the agent's owner user_id from the database
        user_id = await self._get_agent_user_id(agent_id)
        if not user_id:
            return "Agent not found."

        graph = await load_agent(user_id, agent_id=agent_id)
        await graph.initialize_run()
        await _prebuild_dependencies(graph, user_id, input_text)

        logger.info(f"Running agent flow for agent_id={agent_id}...")
        run_outputs = await run_agent(
            inputs={"input_value": input_text},
            graph=graph,
            user_id=user_id,
            session_id=session_id,
        )

        output_text = _extract_output_text(run_outputs)
        logger.info(f"Flow completed. Output length: {len(output_text) if output_text else 0}")
        return output_text or "No output generated."

    # Sentinel returned by _resolve_agent_from_channel_data when multiple
    # agents share the same bot and we cannot disambiguate. The caller
    # surfaces a user-facing message asking them to ask their admin to
    # assign each agent a dedicated bot.
    AMBIGUOUS_ROUTING = "__ambiguous_routing__"

    async def _resolve_agent_from_channel_data(self, turn_context: TurnContext) -> str | None:
        """Resolve agent_id for this conversation.

        Priority:
        1. ``_agentcore_agent_id`` from channel_data (set by
           ``/messages`` endpoint via JWT ``appId`` lookup — this is
           the deterministic, correct path for dedicated-bot setups).
        2. Database query for published agents (only used when the
           JWT-routing step couldn't pin a specific agent, e.g. the
           bot is the global shared one).

        For the fallback path, if multiple agents are published
        against the same global bot we return ``AMBIGUOUS_ROUTING``
        rather than silently guessing the most-recent one. Returning
        the wrong agent's response is worse than asking the user to
        reach out to their admin.
        """
        # Check for agent_id hint from JWT-based routing
        if turn_context and turn_context.activity and turn_context.activity.channel_data:
            hint = turn_context.activity.channel_data.get("_agentcore_agent_id")
            if hint:
                logger.info(f"Agent resolved from JWT appId routing: {hint}")
                return hint

        # Fallback: query database for published agents
        try:
            from sqlmodel import select

            from agentcore.services.database.models.teams_app.model import TeamsApp, TeamsPublishStatusEnum
            from agentcore.services.deps import session_scope

            async with session_scope() as session:
                stmt = (
                    select(TeamsApp)
                    .where(TeamsApp.status == TeamsPublishStatusEnum.PUBLISHED)
                    .order_by(TeamsApp.created_at.desc())
                )
                results = (await session.exec(stmt)).all()

                if len(results) == 1:
                    logger.info(f"Resolved single published agent: {results[0].agent_id}")
                    return str(results[0].agent_id)
                elif len(results) > 1:
                    # Cannot guess between N published agents on the
                    # same bot. Returning the most-recent silently
                    # routes the user's question to the wrong agent
                    # — much worse than the friction of a clear error.
                    agent_ids = [str(r.agent_id) for r in results]
                    logger.error(
                        f"AMBIGUOUS Teams routing: {len(results)} published "
                        f"agents share this bot ({agent_ids}). Refusing to "
                        f"guess; the user is being asked to contact admin "
                        f"for a dedicated bot."
                    )
                    return self.AMBIGUOUS_ROUTING
                else:
                    logger.warning("No published Teams agents found in database")
                    return None
        except Exception:
            logger.exception("Error resolving agent from database")
            return None

    async def _get_agent_name(self, agent_id: str) -> str | None:
        """Get agent name from database."""
        try:
            from uuid import UUID

            from agentcore.services.database.models.agent.model import Agent
            from agentcore.services.deps import session_scope

            async with session_scope() as session:
                agent = await session.get(Agent, UUID(agent_id))
                return agent.name if agent else None
        except Exception:
            logger.exception(f"Error getting agent name for {agent_id}")
            return None

    async def _get_agent_user_id(self, agent_id: str) -> str | None:
        """Get agent owner's user_id from database."""
        try:
            from uuid import UUID

            from agentcore.services.database.models.agent.model import Agent
            from agentcore.services.deps import session_scope

            async with session_scope() as session:
                agent = await session.get(Agent, UUID(agent_id))
                return str(agent.user_id) if agent else None
        except Exception:
            logger.exception(f"Error getting agent user_id for {agent_id}")
            return None

    async def _get_agent_description(self, agent_id: str) -> str | None:
        """Get agent description from database."""
        try:
            from uuid import UUID

            from agentcore.services.database.models.agent.model import Agent
            from agentcore.services.deps import session_scope

            async with session_scope() as session:
                agent = await session.get(Agent, UUID(agent_id))
                return agent.description if agent else None
        except Exception:
            logger.exception(f"Error getting agent description for {agent_id}")
            return None

    def _get_aad_object_id(self, turn_context: TurnContext) -> str | None:
        """Extract Azure AD object ID from the activity."""
        if turn_context.activity.from_property:
            return turn_context.activity.from_property.aad_object_id
        return None

    async def _handle_members_added(self, turn_context: TurnContext) -> None:
        """Process members added in conversation update."""
        if turn_context.activity.members_added:
            await self.on_members_added_activity(
                turn_context.activity.members_added,
                turn_context,
            )
