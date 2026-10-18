import logging

from app.config import get_settings
from app.models.text import OpenAICompatibleChatModel, StubChatModel
from app.orchestration.registry import ModelRegistry

logger = logging.getLogger("xa.model_manager")
_s = get_settings()


async def bootstrap_registry(registry: ModelRegistry) -> None:
    if _s.inference_backend == "openai_compatible":
        model = OpenAICompatibleChatModel(
            name=_s.inference_model_name,
            base_url=_s.inference_base_url,
            api_key=_s.inference_api_key,
            model_identifier=_s.inference_model_name,
            timeout=_s.inference_timeout_seconds,
            max_retries=_s.inference_max_retries,
        )
    else:
        model = StubChatModel()

    registry.register(
        name=_s.inference_model_name,
        model=model,
        capabilities=["text", "coding", "math", "health"],
    )
    logger.info("registry_bootstrapped", extra={
        "backend": _s.inference_backend,
        "model": _s.inference_model_name,
    })
