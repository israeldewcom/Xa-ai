import logging

logger = logging.getLogger("xa.specialists.health")

DISCLAIMER = (
    "\n\n---\nThis is informational only and not a substitute for "
    "professional medical advice. Consult a licensed clinician for any "
    "health concern."
)


def annotate(message: str) -> str:
    return message + DISCLAIMER
