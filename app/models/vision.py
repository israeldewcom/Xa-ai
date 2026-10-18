import logging
from dataclasses import dataclass

logger = logging.getLogger("xa.models.vision")


@dataclass
class VisionCapability:
    name: str = "vision"
    available: bool = False

    async def describe(self, image_bytes: bytes, prompt: str) -> dict:
        return {"description": "[vision not configured]", "raw": {}}


def build_vision(cfg) -> VisionCapability:
    if not cfg.vision_base_url:
        return VisionCapability(available=False)
    return VisionCapability(name=cfg.vision_model_name or "vision", available=True)
