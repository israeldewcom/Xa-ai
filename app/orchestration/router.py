import logging
import re

from app.orchestration.registry import ModelRegistry

logger = logging.getLogger("xa.router")

_CODING = re.compile(
    r"\b(def|class|python|javascript|traceback|stack ?trace|exception)\b|```", re.I,
)
_MATH = re.compile(
    r"\b(calculate|solve|integral|derivative|equation)\b|\d\s*[-+*/×^]\s*\d", re.I,
)
_HEALTH = re.compile(r"\b(symptoms?|doctor|medication|diagnosis)\b", re.I)


class RequestRouter:
    def __init__(self, registry: ModelRegistry):
        self.registry = registry

    def classify(self, message: str, capability: str) -> str:
        if capability != "auto":
            return capability
        if _CODING.search(message):
            return "coding"
        if _MATH.search(message):
            return "math"
        if _HEALTH.search(message):
            return "health"
        return "text"

    async def execute(
        self, message: str, capability: str, options: dict,
    ) -> dict:
        resolved = self.classify(message, capability)
        model = self.registry.find_ready(resolved)
        messages = options.get("messages") or [
            {"role": "user", "content": message},
        ]
        result = await model.generate(
            messages,
            temperature=options.get("temperature", 0.7),
            max_tokens=options.get("max_tokens"),
        )
        return {
            "content": result["content"],
            "capability": resolved,
            "model": {"id": model.name, "name": model.name},
            "usage": result.get("usage", {}),
            "raw": result.get("raw", {}),
        }

    async def stream(
        self, message: str, capability: str, options: dict,
    ):
        resolved = self.classify(message, capability)
        model = self.registry.find_ready(resolved)
        messages = options.get("messages") or [
            {"role": "user", "content": message},
        ]
        async for chunk in model.stream(messages, **options):
            yield chunk
