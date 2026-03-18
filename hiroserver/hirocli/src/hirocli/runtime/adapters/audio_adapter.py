"""AudioTranscriptionAdapter — bridges STTService into the adapter pipeline.

Delegates all transcription logic to STTService. The adapter's only job is to
read item.body and write the transcript into item.metadata.
"""

from __future__ import annotations

import time

from hiro_channel_sdk.models import ContentItem, UnifiedMessage
from hiro_commons.log import Logger

from ...services.stt import STTService
from ..message_adapter import ContentTypeAdapter

log = Logger.get("ADAPTER.AUDIO")


class AudioTranscriptionAdapter(ContentTypeAdapter):
    """Transcribes audio ContentItems using STTService."""

    def __init__(self, service: STTService | None = None) -> None:
        self._service = service or STTService()

    @property
    def target_content_type(self) -> str:
        return "audio"

    def can_handle(self, msg: UnifiedMessage) -> bool:
        if not self._service.is_available():
            return False
        return super().can_handle(msg)

    async def process_item(self, item: ContentItem) -> str:
        if not item.body:
            raise ValueError("Audio ContentItem has no body to transcribe")
        audio_bytes = len(item.body)
        provider = type(self._service).__name__
        log.info("Transcribing audio", audio_bytes=audio_bytes, provider=provider)
        _t0 = time.perf_counter()
        transcript = await self._service.transcribe(item.body)
        _elapsed_ms = int((time.perf_counter() - _t0) * 1000)
        log.info(
            "Transcription complete",
            transcript_len=len(transcript),
            elapsed_ms=_elapsed_ms,
        )
        return transcript
