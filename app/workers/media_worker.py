import logging

from app.workers.base import BaseWorker

logger = logging.getLogger("xa.media_worker")


class MediaWorker(BaseWorker):
    job_types = ("document_processing", "image_processing", "audio_transcription")

    async def handle(self, job):
        logger.info("media_job", extra={"job_type": job.job_type, "job_id": job.id})
        # Placeholder — wire real handlers as needed
        return (job.input_reference or "", "")


if __name__ == "__main__":
    import asyncio
    from app.core.logging import setup_logging
    setup_logging("INFO")
    asyncio.run(MediaWorker().run())
