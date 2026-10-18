import logging
import struct

logger = logging.getLogger("xa.vad")


class EnergyVAD:
    def __init__(self, threshold: int = 500):
        self.threshold = threshold

    def is_speech(self, pcm16_mono: bytes) -> bool:
        if len(pcm16_mono) < 2:
            return False
        samples = struct.unpack(f"<{len(pcm16_mono)//2}h", pcm16_mono)
        if not samples:
            return False
        rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
        return rms > self.threshold


class WebRTCVAD:
    def __init__(self, sample_rate: int = 16000, aggressiveness: int = 2):
        try:
            import webrtcvad  # type: ignore
        except ImportError as exc:
            raise RuntimeError("webrtcvad not installed; use EnergyVAD") from exc
        if sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError(f"webrtcvad needs 8/16/32/48kHz, got {sample_rate}")
        self._vad = webrtcvad.Vad(aggressiveness)
        self.sample_rate = sample_rate

    def is_speech(self, pcm16_mono: bytes) -> bool:
        frame_bytes = int(self.sample_rate * 0.02) * 2
        if len(pcm16_mono) < frame_bytes:
            return False
        try:
            return self._vad.is_speech(pcm16_mono[:frame_bytes], self.sample_rate)
        except Exception:
            return False


def build_vad(sample_rate: int, aggressiveness: int):
    try:
        return WebRTCVAD(sample_rate, aggressiveness)
    except RuntimeError:
        logger.info("vad_fallback_energy")
        return EnergyVAD()
