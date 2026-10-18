import logging
from io import BytesIO

from pypdf import PdfReader

logger = logging.getLogger("xa.specialists.document")


def extract_text(mime: str, data: bytes) -> str:
    if mime == "application/pdf":
        try:
            reader = PdfReader(BytesIO(data))
            return "\n\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception as exc:
            logger.warning("pdf_extract_failed", extra={"error": str(exc)})
            return ""
    try:
        return data.decode("utf-8", "replace")
    except Exception:
        return ""


def chunk(text: str, *, size: int = 800, overlap: int = 100) -> list[str]:
    if not text:
        return []
    out = []
    i = 0
    while i < len(text):
        chunk = text[i:i + size]
        out.append(chunk)
        i += size - overlap
        if i <= 0:
            break
    return out
