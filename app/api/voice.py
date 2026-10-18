import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.core.exceptions import RateLimited
from app.core.quotas import check_and_increment, get_today
from app.core.security import decode_token
from app.database.models import User, VoiceSession
from app.database.session import AsyncSessionLocal
from app.models.audio import ASRAdapter, TTSAdapter
from app.services.voice_session import VoicePipeline

logger = logging.getLogger("xa.api.voice")
router = APIRouter(prefix="/voice", tags=["voice"])
_s = get_settings()


async def _auth_via_message(ws: WebSocket) -> str | None:
    """Auth via first WS message: {"type":"auth","token":"..."} within 5s.
    Fallback: ?token= query param (dev only, rejected in prod if strict)."""
    import asyncio
    try:
        msg = await asyncio.wait_for(ws.receive_text(), timeout=5.0)
    except asyncio.TimeoutError:
        return None
    try:
        data = json.loads(msg)
    except json.JSONDecodeError:
        return None
    if data.get("type") != "auth":
        return None
    token = data.get("token", "")
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        return payload["sub"]
    except Exception:
        return None


@router.websocket("/stream")
async def voice_stream(ws: WebSocket):
    await ws.accept()

    if _s.environment == "production" or _s.voice_ws_auth_strict:
        # Reject ?token= entirely
        if ws.query_params.get("token"):
            await ws.close(code=4401, reason="auth required via message")
            return
        user_id = await _auth_via_message(ws)
    else:
        # Legacy query-param auth first, then fall back to message
        query_token = ws.query_params.get("token")
        user_id = None
        if query_token:
            try:
                payload = decode_token(query_token)
                if payload.get("type") == "access":
                    user_id = payload["sub"]
            except Exception:
                user_id = None
        if user_id is None:
            user_id = await _auth_via_message(ws)

    if not user_id:
        await ws.close(code=4401, reason="auth failed")
        return

    limiter = ws.app.state.voice_limiter
    try:
        await limiter.check(f"voice:{user_id}")
    except RateLimited:
        await ws.close(code=4429, reason="rate limited")
        return

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None or user.status != "active":
            await ws.close(code=4401, reason="inactive user")
            return
        used = (await get_today(db, user_id)).get("voice_seconds", 0)
        if used >= _s.quota_voice_minutes_per_day * 60:
            await ws.close(code=4429, reason="voice quota exceeded")
            return
        session = VoiceSession(user_id=user_id)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = session.id

    req_router = ws.app.state.router
    asr = None
    tts = None
    if _s.audio_asr_base_url:
        asr = ASRAdapter(base_url=_s.audio_asr_base_url)
    if _s.audio_tts_base_url:
        tts = TTSAdapter(base_url=_s.audio_tts_base_url)

    pipeline = VoicePipeline(user_id, req_router, asr, tts)

    try:
        await ws.send_json({"type": "ready", "session_id": session_id})
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if "bytes" in msg and msg["bytes"] is not None:
                async for event in pipeline.handle_pcm(msg["bytes"]):
                    await ws.send_json(event)
            elif "text" in msg and msg["text"]:
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "interrupt":
                    pipeline.state.set_assistant_speaking(False)
                    await pipeline._interrupt_tts()
                elif data.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("voice_stream_error", extra={"error": str(exc)})
    finally:
        async with AsyncSessionLocal() as db:
            sess = await db.get(VoiceSession, session_id)
            if sess:
                from datetime import datetime, timezone
                sess.ended_at = datetime.now(timezone.utc)
                sess.status = "ended"
                sess.total_seconds = pipeline.state.elapsed_seconds
                sess.turn_count = pipeline.state.turn_count
                await db.commit()
                try:
                    await check_and_increment(
                        db, user_id, "voice_seconds", sess.total_seconds,
                        _s.quota_voice_minutes_per_day * 60,
                    )
                except RateLimited:
                    pass  # session already over; next session is refused above
