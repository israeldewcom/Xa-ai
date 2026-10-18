import logging

logger = logging.getLogger("xa.models.video")


class VideoProcessor:
    def __init__(self, cfg):
        self.available = False

    async def process(self, source: str) -> dict:
        return {"error": "video processing not configured"}
