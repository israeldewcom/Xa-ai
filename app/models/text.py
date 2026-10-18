import json
import logging
from typing import AsyncIterator

import httpx
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from app.config import get_settings
from app.core.circuit_breaker import CircuitBreaker
from app.core.exceptions import BackendError
from app.core.metrics import inference_requests_total, inference_seconds

logger = logging.getLogger("xa.models.text")
_s = get_settings()


class OpenAICompatibleChatModel:
    def __init__(self, *, name: str, base_url: str, api_key: str | None,
                 model_identifier: str, timeout: float = 60.0,
                 max_retries: int = 3):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_identifier = model_identifier
        self.timeout = timeout
        self.max_retries = max_retries
        self._cb = CircuitBreaker(
            _s.inference_cb_failure_threshold,
            _s.inference_cb_recovery_seconds,
        )

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.HTTPError, BackendError)),
        reraise=True,
    )
    async def generate(
        self, messages: list[dict], *, temperature: float = 0.7,
        max_tokens: int | None = None, **kw,
    ) -> dict:
        self._cb.check()
        payload = {
            "model": self.model_identifier,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or _s.inference_max_tokens,
        }
        import time
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload, headers=self._headers(),
                )
                r.raise_for_status()
                data = r.json()
            self._cb.record_success()
            inference_requests_total.labels(self.name, "success").inc()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return {
                "content": content,
                "usage": {
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                },
                "raw": data,
            }
        except Exception as exc:
            self._cb.record_failure()
            inference_requests_total.labels(self.name, "error").inc()
            logger.warning("inference_failed", extra={"error": str(exc)})
            raise BackendError(str(exc))
        finally:
            inference_seconds.labels(self.name).observe(time.monotonic() - started)

    async def stream(
        self, messages: list[dict], **kw,
    ) -> AsyncIterator[str]:
        self._cb.check()
        payload = {
            "model": self.model_identifier,
            "messages": messages,
            "temperature": kw.get("temperature", 0.7),
            "max_tokens": kw.get("max_tokens", _s.inference_max_tokens),
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/v1/chat/completions",
                    json=payload, headers=self._headers(),
                ) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                            delta = obj["choices"][0]["delta"].get("content")
                            if delta:
                                yield delta
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
            self._cb.record_success()
        except Exception as exc:
            self._cb.record_failure()
            raise BackendError(str(exc))


class StubChatModel:
    """Stub model for testing — does NOT pretend to understand tools. It
    returns deterministic text-only responses so agent flows must gracefully
    report 'no tool call proposed'."""
    name = "stub"

    async def generate(self, messages: list[dict], *, temperature=0.7,
                       max_tokens=None, **kw) -> dict:
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m.get("content", "")
                break
        content = f"[stub] Echo: {last_user[:200]}"
        return {
            "content": content,
            "usage": {"input_tokens": len(last_user) // 4, "output_tokens": len(content) // 4},
            "raw": {},
        }

    async def stream(self, messages: list[dict], **kw) -> AsyncIterator[str]:
        result = await self.generate(messages, **kw)
        for word in result["content"].split(" "):
            yield word + " "
