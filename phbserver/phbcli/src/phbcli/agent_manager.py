"""AgentManager — LLM agent worker for phbcli.

Responsibilities:
  - Reads inbound text messages from CommunicationManager.inbound_queue.
  - Passes each message to a LangChain v1 create_agent instance.
  - Maintains per-conversation memory keyed by channel + sender_id using
    LangGraph's InMemorySaver checkpointer.
  - Constructs a reply UnifiedMessage and places it on the outbound queue.
  - On LLM errors, enqueues a human-readable fallback reply instead.

Non-text messages (image, audio, video, etc.) are silently ignored by this
worker; they remain unconsumed on the inbound queue only if no other consumer
reads them first.  Currently inbound_queue has only one consumer (this worker),
so non-text messages are drained and dropped.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from phb_channel_sdk.models import UnifiedMessage
from phb_commons.log import Logger

from .agent_config import load_agent_config, load_system_prompt

if TYPE_CHECKING:
    from .communication_manager import CommunicationManager

log = Logger.get("AGENT")

_FALLBACK_ERROR_BODY = (
    "Sorry, I encountered an error processing your message. Please try again."
)


def _build_thread_id(msg: UnifiedMessage) -> str:
    return f"{msg.channel}:{msg.sender_id}"


def _make_reply(inbound: UnifiedMessage, body: str) -> UnifiedMessage:
    return UnifiedMessage(
        id=str(uuid.uuid4()),
        channel=inbound.channel,
        direction="outbound",
        sender_id="server",
        recipient_id=inbound.sender_id,
        content_type="text",
        body=body,
        metadata={},
        timestamp=datetime.now(UTC),
    )


class AgentManager:
    """Consumes inbound text messages and produces agent replies.

    Usage::

        agent_mgr = AgentManager(comm_manager)
        await asyncio.gather(..., agent_mgr.run())
    """

    def __init__(self, comm_manager: CommunicationManager, workspace_path: Path) -> None:
        self._comm = comm_manager
        self._workspace_path = workspace_path
        self._agent = self._build_agent()

    def _build_agent(self):
        from langchain.agents import create_agent
        from langchain.chat_models import init_chat_model
        from langgraph.checkpoint.memory import InMemorySaver

        from .tools import DeviceAddTool, DeviceListTool, DeviceRevokeTool
        from .tools.langchain_adapter import to_langchain_list

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

        tools = to_langchain_list([
            DeviceAddTool(),
            DeviceListTool(),
            DeviceRevokeTool(),
        ])

        return create_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            checkpointer=InMemorySaver(),
        )

    async def _process(self, msg: UnifiedMessage) -> None:
        thread_id = _build_thread_id(msg)
        config = {"configurable": {"thread_id": thread_id}}
        log.info(
            "Processing message",
            msg_id=msg.id,
            thread=thread_id,
            sender=msg.sender_id,
            body_length=len(msg.body),
        )
        try:
            result = await self._agent.ainvoke(
                {"messages": [{"role": "user", "content": msg.body}]},
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
            in_reply_to=msg.id,
            reply_msg_id=reply.id,
            thread=thread_id,
            content_length=len(reply_body),
        )

    async def run(self) -> None:
        """Drain inbound_queue and process text messages.  Runs forever."""
        log.info("AgentManager started")
        while True:
            msg: UnifiedMessage = await self._comm.inbound_queue.get()
            try:
                if msg.content_type != "text":
                    log.info(
                        "Ignoring non-text message",
                        msg_id=msg.id,
                        content_type=msg.content_type,
                        sender=msg.sender_id,
                    )
                    continue
                await self._process(msg)
            finally:
                self._comm.inbound_queue.task_done()
