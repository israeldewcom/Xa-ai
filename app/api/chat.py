import logging
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.cost import record_usage
from app.core.pricing import cost_micros
from app.core.exceptions import NotFound, RateLimited
from app.core.idempotency import IdempotencyManager
from app.core.prompt_safety import fence_many
from app.core.quotas import enforce
from app.core.rate_limit import RateLimiter
from app.core.sse import sse_stream
from app.database.models import Conversation, FileRecord, Message, User
from app.database.session import AsyncSessionLocal, get_db
from app.dependencies import get_current_user, get_router
from app.orchestration.router import RequestRouter
from app.schemas.chat import ChatRequest, ChatResponse, Source
from app.services.retrieval import retrieve
from app.specialists.health import annotate as health_annotate

logger = logging.getLogger("xa.api.chat")
router = APIRouter(prefix="/chat", tags=["chat"])
_s = get_settings()


async def _build_attachments(
    db: AsyncSession, user_id: str, payload: ChatRequest,
) -> tuple[list[dict], list[Source], list[str]]:
    extra_msgs: list[dict] = []
    sources: list[Source] = []
    file_ids: list[str] = []
    for att in payload.attachments:
        rec = await db.get(FileRecord, att.file_id)
        if rec is None or rec.user_id != user_id:
            raise NotFound(f"Attachment {att.file_id} not found.")
        file_ids.append(rec.id)
        if att.kind in ("document", "text"):
            rag = await retrieve(db, user_id, payload.message, top_k=4)
            if rag:
                extra_msgs.append({
                    "role": "user",
                    "content": fence_many([
                        (f"document chunk #{i + 1}", r["content"])
                        for i, r in enumerate(rag)
                    ]),
                })
                for i, r in enumerate(rag):
                    sources.append(Source(
                        file_id=r["file_id"], score=r["score"], rank=i + 1,
                    ))
    return extra_msgs, sources, file_ids


async def _run_chat(
    request: Request, payload: ChatRequest, user: User, db: AsyncSession,
    req_router: RequestRouter,
):
    limiter: RateLimiter = request.app.state.chat_limiter
    await limiter.check(f"chat:{user.id}")
    await enforce(db, user.id, "chat", 1)

    conversation: Conversation | None = None
    if payload.conversation_id:
        conversation = await db.get(Conversation, payload.conversation_id)
        if conversation is None or conversation.user_id != user.id:
            raise NotFound("Conversation not found.")
    else:
        title = payload.message[:60] + ("..." if len(payload.message) > 60 else "")
        conversation = Conversation(user_id=user.id, title=title)
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)

    extra_msgs, sources, _ = await _build_attachments(
        db, user.id, payload,
    )

    capability = req_router.classify(payload.message, payload.capability)
    result = await req_router.execute(
        payload.message, payload.capability,
        {"messages": [
            {"role": "user", "content": payload.message},
            *extra_msgs,
        ]},
    )

    content = result["content"]
    if capability == "health":
        content = health_annotate(content)

    usage = result.get("usage") or {}
    await record_usage(
        db, user.id, kind="chat",
        model_id=result["model"]["id"],
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
    )
    if usage.get("output_tokens"):
        await enforce(db, user.id, "chat_tokens", int(usage["output_tokens"]))

    db.add(Message(
        conversation_id=conversation.id, role="user",
        content=payload.message, capability=capability,
    ))
    assistant_msg = Message(
        conversation_id=conversation.id, role="assistant",
        content=content, capability=capability,
        model_id=result["model"]["id"], status="completed",
    )
    db.add(assistant_msg)
    await db.commit()
    await db.refresh(assistant_msg)

    return ChatResponse(
        conversation_id=conversation.id,
        message_id=assistant_msg.id,
        content=content,
        capability=capability,
        model=result["model"],
        sources=sources,
        usage=usage,
    )


@router.post("", response_model=ChatResponse)
async def chat(
    request: Request, payload: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    req_router: RequestRouter = Depends(get_router),
):
    idem_key = request.headers.get("idempotency-key")
    if idem_key:
        mgr = IdempotencyManager(db, user.id, "chat")
        cached = await mgr.begin(idem_key)
        if cached is not None:
            return cached["body"]
        try:
            result = await _run_chat(request, payload, user, db, req_router)
            await mgr.finalize(idem_key, 200, result.model_dump())
            return result
        except Exception:
            await mgr.release(idem_key)
            raise
    return await _run_chat(request, payload, user, db, req_router)


@router.post("/stream")
async def chat_stream(
    request: Request, payload: ChatRequest,
    user: User = Depends(get_current_user),
    req_router: RequestRouter = Depends(get_router),
):
    await request.app.state.chat_limiter.check(f"chat:{user.id}")
    user_id = user.id
    # The request-scoped session from get_db is closed once the handler returns,
    # which is before the stream body runs. Use short-lived sessions of our own.
    async with AsyncSessionLocal() as db:
        await enforce(db, user_id, "chat", 1)
        if payload.conversation_id:
            conv = await db.get(Conversation, payload.conversation_id)
            if conv is None or conv.user_id != user_id:
                raise NotFound("Conversation not found.")
        else:
            conv = Conversation(user_id=user_id, title=payload.message[:60])
            db.add(conv)
            await db.commit()
            await db.refresh(conv)
        conversation_id = conv.id

    message_id = uuid.uuid4().hex
    capability = req_router.classify(payload.message, payload.capability)

    async def source() -> AsyncIterator[dict]:
        yield {"event": "start", "conversation_id": conversation_id,
               "capability": capability}
        collected: list[str] = []
        try:
            async for chunk in req_router.stream(
                payload.message, payload.capability, options={},
            ):
                collected.append(chunk)
                yield {"event": "delta", "content": chunk}
        except Exception:
            logger.exception("stream_failed")
            yield {"event": "error", "message": "stream failed"}
            return
        final = "".join(collected)
        if capability == "health":
            final = health_annotate(final)
        out_tokens = max(1, len(final) // 4)
        async with AsyncSessionLocal() as db:
            db.add(Message(
                conversation_id=conversation_id, role="user",
                content=payload.message, capability=capability,
            ))
            db.add(Message(
                id=message_id, conversation_id=conversation_id,
                role="assistant", content=final, capability=capability,
                status="completed",
            ))
            await db.commit()
            await record_usage(
                db, user_id, kind="chat_stream",
                input_tokens=len(payload.message) // 4, output_tokens=out_tokens,
                cost_micros_override=cost_micros(
                    _s.inference_model_name, len(payload.message) // 4, out_tokens,
                ),
            )
            try:
                await enforce(db, user_id, "chat_tokens", out_tokens)
            except RateLimited:
                pass  # tokens already spent; the next request is refused
        yield {"event": "done", "message_id": message_id,
               "conversation_id": conversation_id}

    return StreamingResponse(
        sse_stream(source(), heartbeat_seconds=_s.stream_heartbeat_seconds),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
