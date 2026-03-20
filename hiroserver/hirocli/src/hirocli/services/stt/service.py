"""STTService — model-centric speech-to-text orchestrator.

Aggregates multiple STTProvider instances into a single interface. Callers
think in terms of model IDs; the provider is resolved automatically.

Usage
-----
    from hirocli.services.stt import STTService, OpenAISTTProvider, GeminiSTTProvider

    stt = STTService(providers=[OpenAISTTProvider(), GeminiSTTProvider()])

    # Async (adapter pipeline, agent tools):
    transcript = await stt.transcribe(source)
    transcript = await stt.transcribe(source, model="gemini-3.1-flash-lite")

    # Sync (CLI tools):
    transcript = stt.transcribe_sync(source)

    # Introspection:
    for m in stt.list_models():
        print(m.model_id, m.display_name)

Configuration
-------------
    STT_DEFAULT_MODEL   Model ID to use when no model is specified.
                        Falls back to the first model from the first
                        available provider if unset.
    OPENAI_API_KEY      Enables OpenAISTTProvider.
    GOOGLE_API_KEY /
    GEMINI_API_KEY      Enables GeminiSTTProvider.
"""

from __future__ import annotations

import asyncio
import base64
import os
from concurrent.futures import ThreadPoolExecutor

from hiro_commons.log import Logger

from .provider import ModelInfo, STTProvider

log = Logger.get("STT.SERVICE")


class STTService:
    """Model-centric speech-to-text service.

    On construction, each provider is asked whether it is available.
    Only available providers contribute models to the registry. Unavailable
    providers (missing API key, missing SDK) are silently skipped.
    """

    def __init__(
        self,
        providers: list[STTProvider] | None = None,
        default_model: str | None = None,
    ) -> None:
        self._model_to_provider: dict[str, STTProvider] = {}
        self._models: list[ModelInfo] = []

        for provider in (providers or []):
            if not provider.is_available():
                log.debug("STT provider not available, skipping", provider=provider.name)
                continue
            for model_info in provider.supported_models():
                self._model_to_provider[model_info.model_id] = provider
                self._models.append(model_info)
            log.info(
                f"STT provider loaded: {provider.name}",                
                models=[m.model_id for m in provider.supported_models()],
            )

        env_default = default_model or os.environ.get("STT_DEFAULT_MODEL")
        if env_default and env_default in self._model_to_provider:
            self._default_model: str | None = env_default
        elif self._models:
            self._default_model = self._models[0].model_id
        else:
            self._default_model = None

        if self._default_model:
            log.info(f"STT default model: {self._default_model}")
        else:
            log.warning("No STT providers available — transcription disabled")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True when at least one provider is loaded."""
        return bool(self._model_to_provider)

    def list_models(self) -> list[ModelInfo]:
        """Return all models from all available providers."""
        return list(self._models)

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    async def transcribe(
        self,
        source: str,
        *,
        model: str | None = None,
        **kwargs: object,
    ) -> str:
        """Transcribe audio and return the transcript text.

        ``source`` may be:
          - A URL (``http://`` or ``https://``)
          - A data URI (``data:<mime>;base64,...``)
          - A raw base64-encoded string

        ``model`` selects a specific model (must be one from list_models()).
        When omitted, the default model is used.

        Extra keyword arguments are forwarded to the provider (e.g. ``language``,
        ``prompt``, ``temperature`` for OpenAI; ``mime_type`` for Gemini).
        """
        if not source:
            raise ValueError("Audio source is empty")

        effective_model = model or self._default_model
        if not effective_model:
            raise RuntimeError(
                "No STT providers are available. "
                "Set OPENAI_API_KEY or GOOGLE_API_KEY to enable transcription."
            )

        provider = self._model_to_provider.get(effective_model)
        if provider is None:
            available = [m.model_id for m in self._models]
            raise ValueError(
                f"Unknown STT model {effective_model!r}. "
                f"Available: {available}"
            )

        audio_bytes = _resolve_audio_bytes(source)
        return await provider.transcribe(audio_bytes, model=effective_model, **kwargs)

    def transcribe_sync(self, source: str, **kwargs: object) -> str:
        """Synchronous wrapper — safe to call from a tool or non-async context.

        Runs transcribe() in a dedicated thread so an existing event loop in
        the calling thread is not affected.
        """
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(asyncio.run, self.transcribe(source, **kwargs))
            return future.result()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_audio_bytes(source: str) -> bytes:
    """Convert a source value (data URI, URL, or raw base64) to raw bytes."""
    if source.startswith("data:"):
        _header, encoded = source.split(",", 1)
        return base64.b64decode(encoded)
    if source.startswith("http://") or source.startswith("https://"):
        import urllib.request
        with urllib.request.urlopen(source, timeout=30) as resp:  # noqa: S310
            return resp.read()
    return base64.b64decode(source)
