import io
import struct
import wave


def pcm16_to_float32(pcm: bytes) -> list[float]:
    n = len(pcm) // 2
    samples = struct.unpack(f"<{n}h", pcm)
    return [s / 32768.0 for s in samples]


def float32_to_pcm16(samples: list[float]) -> bytes:
    clipped = [max(-1.0, min(1.0, s)) for s in samples]
    ints = [int(s * 32767) for s in clipped]
    return struct.pack(f"<{len(ints)}h", *ints)


def chunk_pcm(pcm: bytes, chunk_ms: int, sample_rate: int) -> list[bytes]:
    bytes_per_ms = (sample_rate * 2) // 1000
    chunk_bytes = max(2, bytes_per_ms * chunk_ms)
    return [pcm[i:i + chunk_bytes] for i in range(0, len(pcm), chunk_bytes)]


def mix_audio(a: bytes, b: bytes) -> bytes:
    na, nb = len(a) // 2, len(b) // 2
    n = min(na, nb)
    sa = struct.unpack(f"<{n}h", a[:n * 2])
    sb = struct.unpack(f"<{n}h", b[:n * 2])
    mixed = [max(-32768, min(32767, x + y)) for x, y in zip(sa, sb)]
    return struct.pack(f"<{n}h", *mixed)


def pcm_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV container (ASR servers need a header)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()
