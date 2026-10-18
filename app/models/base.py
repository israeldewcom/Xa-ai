from dataclasses import dataclass
from typing import AsyncIterator, Protocol


class ChatModel(Protocol):
    name: str

    async def generate(
        self, messages: list[dict], *, temperature: float = 0.7,
        max_tokens: int | None = None, **kw,
    ) -> dict: ...

    async def stream(
        self, messages: list[dict], **kw,
    ) -> AsyncIterator[str]: ...


@dataclass
class ModelCapabilities:
    text: bool = False
    vision: bool = False
    image: bool = False
    audio: bool = False
    video: bool = False
    embedding: bool = False
