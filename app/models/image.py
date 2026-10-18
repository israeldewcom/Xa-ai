import logging

logger = logging.getLogger("xa.models.image")


class ImageGenerator:
    def __init__(self, cfg):
        self.available = bool(cfg.image_base_url)
        self.base_url = cfg.image_base_url

    async def generate(self, prompt: str, **kw) -> dict:
        if not self.available:
            return {"error": "image generation not configured"}
        return {"images": [], "note": "wire IMAGE_BASE_URL"}
