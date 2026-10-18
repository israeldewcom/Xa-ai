import logging
import httpx

logger = logging.getLogger("xa.models.audio")


class ASRAdapter:
    def __init__(self, *, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def transcribe(self, audio_bytes: bytes, *, filename: str = "a.wav") -> dict:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        files = {"file": (filename, audio_bytes, "application/octet-stream")}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{self.base_url}/v1/audio/transcriptions",
                files=files, headers=headers,
            )
            r.raise_for_status()
            return r.json()


class TTSAdapter:
    def __init__(self, *, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def synthesize(self, text: str, *, voice: str = "alloy",
                         fmt: str = "mp3") -> bytes:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{self.base_url}/v1/audio/speech",
                json={"model": "tts-1", "input": text, "voice": voice,
                      "response_format": fmt},
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.content

    async def synthesize_stream(self, text: str, *, voice: str = "alloy"):
        """Yields MP3 bytes chunks. Cancelable by the caller."""
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST", f"{self.base_url}/v1/audio/speech",
                json={"model": "tts-1", "input": text, "voice": voice,
                      "response_format": "mp3"},
                headers=self._headers(),
            ) as r:
                r.raise_for_status()
                async for chunk in r.aiter_bytes(chunk_size=8192):
                    yield chunk
