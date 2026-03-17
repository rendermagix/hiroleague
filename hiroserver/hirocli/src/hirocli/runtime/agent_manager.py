"""AgentManager — LLM agent worker for hirocli.

Responsibilities:
  - Reads inbound messages from CommunicationManager.inbound_queue.
  - Skips messages that contain no text content items; only the first text
    item (or a concatenation of all text items) is passed to the agent.
  - Passes each text message to a LangChain v1 create_agent instance.
  - Maintains per-conversation persistent memory keyed by conversation_channels.id
    (a UUID) using LangGraph's AsyncSqliteSaver checkpointer backed by workspace.db.
  - Constructs a reply UnifiedMessage and places it on the outbound queue.
  - On LLM errors, enqueues a human-readable fallback reply instead.

Messages with no text content items (image-only, audio-only, etc.) are silently
ignored. They are consumed from the queue so they don't block it, but no reply
is produced. Future workers can be added as additional consumers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from hiro_channel_sdk.models import ContentItem, MessageRouting, UnifiedMessage
from hiro_commons.log import Logger

if TYPE_CHECKING:
    from .communication_manager import CommunicationManager

log = Logger.get("AGENT")

_FALLBACK_ERROR_BODY = (
    "Sorry, I encountered an error processing your message. Please try again."
)


def _make_reply(inbound: UnifiedMessage, body: str) -> UnifiedMessage:
    return UnifiedMessage(
        routing=MessageRouting(
            channel=inbound.routing.channel,
            direction="outbound",
            sender_id="server",
            recipient_id=inbound.routing.sender_id,
            metadata={},
        ),
        content=[ContentItem(content_type="text", body=body)],
    )


class AgentManager:
    """Consumes inbound text messages and produces agent replies.

    Usage::

        agent_mgr = AgentManager(comm_manager, workspace_path)
        await asyncio.gather(..., agent_mgr.run())
    """

    def __init__(self, comm_manager: CommunicationManager, workspace_path: Path) -> None:
        self._comm = comm_manager
        self._workspace_path = workspace_path
        self._agent = None  # built inside run() once the async checkpointer is ready

    def _build_agent(self, checkpointer):
        from langchain.agents import create_agent
        from langchain.chat_models import init_chat_model

        from ..domain.agent_config import load_agent_config, load_system_prompt
        from ..tools import all_tools
        from ..tools.langchain_adapter import to_langchain_list

        config = load_agent_config(self._workspace_path)
        system_prompt = load_system_prompt(self._workspace_path)

        log.info(
            "Building agent",
            model=config.model,
            provider=config.provider,
        )

        model = init_chat_model(
            model=config.model,
            model_provider=config.provider,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )

        tools = to_langchain_list(all_tools())

        return create_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            checkpointer=checkpointer,
        )

    def _resolve_thread_id(self, msg: UnifiedMessage) -> str:
        """Return the conversation_channels.id UUID for this channel+sender pair.

        The channel name used as the lookup key is channel:sender_id so that
        each unique sender on each plugin channel gets its own persistent thread.
        A new conversation_channels row is created on first contact.
        """
        from ..domain.conversation_channel import get_or_create_channel
        channel_name = f"{msg.routing.channel}:{msg.routing.sender_id}"
        channel = get_or_create_channel(self._workspace_path, channel_name)
        return channel.id

    async def _process(self, msg: UnifiedMessage) -> None:
        thread_id = self._resolve_thread_id(msg)
        config = {"configurable": {"thread_id": thread_id}}

        # Concatenate all text content items into a single input string.
        text_body = " ".join(
            item.body for item in msg.content if item.content_type == "text"
        )

        log.info(
            "Processing message",
            msg_id=msg.routing.id,
            thread=thread_id,
            sender=msg.routing.sender_id,
            body_length=len(text_body),
        )
        try:
            result = await self._agent.ainvoke(
                {"messages": [{"role": "user", "content": text_body}]},
                config=config,
            )
            reply_body: str = result["messages"][-1].content
        except Exception as exc:
            log.error(
                "Agent invocation error",
                thread=thread_id,
                error=str(exc),
                exc_info=True,
            )
            reply_body = _FALLBACK_ERROR_BODY

        reply = _make_reply(msg, reply_body)
        await self._comm.enqueue_outbound(reply)
        log.info(
            "Agent reply enqueued",
            in_reply_to=msg.routing.id,
            reply_msg_id=reply.routing.id,
            thread=thread_id,
            content_length=len(reply_body),
        )

    async def run(self) -> None:
        """Build the agent with a persistent SQLite checkpointer then drain inbound_queue."""
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        from ..domain.db import db_path

        db = str(db_path(self._workspace_path))

        # AsyncSqliteSaver manages its own checkpoint tables inside workspace.db.
        # They coexist with the application tables without conflict.
        async with AsyncSqliteSaver.from_conn_string(db) as checkpointer:
            self._agent = self._build_agent(checkpointer)
            log.info("AgentManager started")
            while True:
                msg: UnifiedMessage = await self._comm.inbound_queue.get()
                try:
                    # Only process messages that contain at least one text content item.
                    has_text = any(item.content_type == "text" for item in msg.content)
                    if not has_text:
                        log.info(
                            "Ignoring message with no text content",
                            msg_id=msg.routing.id,
                            sender=msg.routing.sender_id,
                        )
                        continue
                    await self._process(msg)
                finally:
                    self._comm.inbound_queue.task_done()
