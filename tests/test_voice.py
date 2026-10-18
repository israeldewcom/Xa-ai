async def test_voice_vad_segments_utterance():
    from app.services.voice_session import VoiceConfig, VoiceSessionState

    state = VoiceSessionState(VoiceConfig(
        silence_ms=60, min_speech_ms=20, chunk_ms=20,
    ))
    speech = b"\x00\x10" * 160
    silence = b"\x00\x00" * 160
    out = None
    for _ in range(3):
        out = state.push_audio(speech)
    for _ in range(3):
        out = state.push_audio(silence)
    assert out is not None and len(out) > 0
    assert state.turn_count == 1
