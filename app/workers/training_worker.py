import logging

from app.config import get_settings
from app.workers.base import BaseWorker

logger = logging.getLogger("xa.training_worker")
_s = get_settings()


class TrainingWorker(BaseWorker):
    job_types = ("training_run",)

    async def handle(self, job):
        if not _s.training_enabled:
            return ("", "TRAINING_DISABLED")
        return (job.input_reference or "", "")


if __name__ == "__main__":
    import asyncio
    from app.core.logging import setup_logging
    setup_logging("INFO")
    asyncio.run(TrainingWorker().run())
