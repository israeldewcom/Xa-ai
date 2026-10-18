import logging

from app.core.exceptions import CapabilityUnavailable

logger = logging.getLogger("xa.registry")


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, dict] = {}

    def register(self, name: str, model, capabilities: list[str]) -> None:
        self._models[name] = {
            "name": name,
            "model": model,
            "capabilities": capabilities,
            "ready": True,
        }

    def list_models(self) -> list[dict]:
        return [
            {"name": v["name"], "capabilities": v["capabilities"], "ready": v["ready"]}
            for v in self._models.values()
        ]

    def find_ready(self, capability: str):
        for entry in self._models.values():
            if not entry["ready"]:
                continue
            if capability in entry["capabilities"]:
                return entry["model"]
        raise CapabilityUnavailable(capability)

    def has(self, capability: str) -> bool:
        return any(capability in e["capabilities"] for e in self._models.values())
