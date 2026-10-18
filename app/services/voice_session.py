"""Voice session orchestration with streaming, cancelable TTS."""
import asyncio
import base64
import contextlib
import logging
import time
from dataclasses import dataclass

from app.config import get_settings
from app.core.audio_codec import pcm_to_wav
from app.core.metrics import voice_utterance_seconds
from app.core.vad import build_vad
from app.models.audio import ASRAdapter, TTSAdapter
from app.orchestration.router import RequestRouter

logger = logging.getLogger("xa.voice")
_s = get_settings()


@dataclass
class VoiceConfig:
    sample_rate: int = 16000
    chunk_ms: int = 20
    vad_aggressiveness: int = 2
    silence_ms: int = 700
    min_speech_ms: int = 200
    max_utterance_seconds: int = 30
    barge_in: bool = True


class VoiceSessionState:
    def __init__(self, cfg: VoiceConfig):
        self.cfg = cfg
        self.vad = build_vad(cfg.sample_rate, cfg.vad_aggressiveness)
        self._speech_ms = 0
        self._silence_ms = 0
        self._utterance = bytearray()
        self._in_speech = False
        self._assistant_speaking = False
        self._turn_count = 0
        self._started_at = time.monotonic()

    @property
    def elapsed_seconds(self) -> int:
        return int(time.monotonic() - self._started_at)

    @property
    def turn_count(self) -> int:
        return self._turn_count

    def set_assistant_speaking(self, speaking: bool) -> None:
        self._assistant_speaking = speaking

    def push_audio(self, pcm: bytes) -> bytes | None:
        """Returns: b"" for barge-in signal, bytes for completed utterance,
        None for nothing. Caller must distinguish."""
        chunk_ms = self.cfg.chunk_ms
        is_speech = self.vad.is_speech(pcm)

        if is_speech and self._assistant_speaking and self.cfg.barge_in:
            self._assistant_speaking = False
            self._in_speech = True
            self._utterance = bytearray(pcm)
            self._speech_ms = chunk_ms
            self._silence_ms = 0
            return b""  # barge-in sentinel

        if is_speech:
            self._speech_ms += chunk_ms
            self._silence_ms = 0
            self._utterance.extend(pcm)
            self._in_speech = True
            if self._speech_ms > self.cfg.max_utterance_seconds * 1000:
                return self._flush()
            return None
        else:
            if self._in_speech:
                self._silence_ms += chunk_ms
                self._utterance.extend(pcm)
                if self._silence_ms >= self.cfg.silence_ms:
                    if self._speech_ms >= self.cfg.min_speech_ms:
                        return self._flush()
                    self._reset_utterance()
            return None

    def _flush(self) -> bytes:
        out = bytes(self._utterance)
        try:
            voice_utterance_seconds.observe(self._speech_ms / 1000.0)
        except Exception:
            pass
        self._reset_utterance()
        self._turn_count += 1
        return out

    def _reset_utterance(self) -> None:
        self._utterance = bytearray()
        self._speech_ms = 0
        self._silence_ms = 0
        self._in_speech = False


class VoicePipeline:
    def __init__(
        self,
        user_id: str,
        req_router: RequestRouter,
        asr: ASRAdapter | None,
        tts: TTSAdapter | None,
        tts_voice: str | None = None,
        cfg: VoiceConfig | None = None,
    ):
        self.user_id = user_id
        self.req_router = req_router
        self.asr = asr
        self.tts = tts
        self.tts_voice = tts_voice or _s.audio_tts_voice
        self.state = VoiceSessionState(cfg or VoiceConfig(
            sample_rate=_s.voice_sample_rate_hz,
            chunk_ms=_s.voice_chunk_ms,
            vad_aggressiveness=_s.voice_vad_aggressiveness,
            silence_ms=_s.voice_vad_silence_ms,
            min_speech_ms=_s.voice_vad_min_speech_ms,
            max_utterance_seconds=_s.voice_max_utterance_seconds,
            barge_in=_s.voice_barge_in_enabled,
        ))
        self._tts_task: asyncio.Task | None = None
        self._tts_queue: asyncio.Queue | None = None

    async def handle_pcm(self, pcm: bytes):
        completed = self.state.push_audio(pcm)
        if completed is None:
            return
        if completed == b"":
            # barge-in — cancel any in-flight TTS and emit event
            await self._interrupt_tts()
            yield {"type": "barge_in"}
            return
        async for ev in self._process_utterance(completed):
            yield ev

    async def _interrupt_tts(self) -> None:
        if self._tts_task and not self._tts_task.done():
            self._tts_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._tts_task
        self._tts_task = None
        self._tts_queue = None

    async def _tts_stream_worker(
        self, text: str, queue: asyncio.Queue, done: asyncio.Event,
    ) -> None:
        try:
            async for chunk in self.tts.synthesize_stream(
                text, voice=self.tts_voice,
            ):
                await queue.put(("chunk", chunk))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("tts_stream_failed", extra={"error": str(exc)})
            await queue.put(("error", str(exc)))
        finally:
            done.set()

    async def _process_utterance(self, pcm: bytes):
        if self.asr is None:
            yield {"type": "error", "message": "ASR backend not configured"}
            return
        try:
            asr_result = await self.asr.transcribe(
                pcm_to_wav(pcm, self.state.cfg.sample_rate),
                filename="utterance.wav",
            )
            transcript = (asr_result.get("text") or "").strip()
        except Exception as exc:
            logger.warning("asr_failed", extra={"error": str(exc)})
            yield {"type": "error", "message": f"ASR failed: {exc}"}
            return

        if not transcript:
            return
        yield {"type": "transcript_final", "text": transcript}

        capability = self.req_router.classify(transcript, "auto")
        yield {"type": "assistant_start", "capability": capability}

        parts: list[str] = []
        try:
            async for chunk in self.req_router.stream(
                transcript, capability, options={},
            ):
                parts.append(chunk)
                yield {"type": "assistant_delta", "content": chunk}
        except Exception as exc:
            logger.warning("llm_stream_failed", extra={"error": str(exc)})
            yield {"type": "error", "message": f"LLM failed: {exc}"}
            return

        full = "".join(parts)
        yield {"type": "assistant_final", "content": full}

        if self.tts is not None and full:
            self.state.set_assistant_speaking(True)
            queue: asyncio.Queue = asyncio.Queue()
            done = asyncio.Event()
            self._tts_queue = queue
            self._tts_task = asyncio.create_task(
                self._tts_stream_worker(full, queue, done),
            )
            try:
                while not (done.is_set() and queue.empty()):
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=0.5)
                    except asyncio.TimeoutError:
                        if done.is_set() and queue.empty():
                            break
                        continue
                    kind, value = item
                    if kind == "chunk":
                        yield {
                            "type": "tts_audio",
                            "format": "mp3",
                            "data": base64.b64encode(value).decode("ascii"),
                        }
                    elif kind == "error":
                        yield {"type": "error", "message": value}
                        break
            except asyncio.CancelledError:
                raise
            finally:
                await self._interrupt_tts()
                self.state.set_assistant_speaking(False)
