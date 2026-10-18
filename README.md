# XA AI

Multi-capability AI platform backend: chat, voice, device mesh, autonomous agents.

Status: **Beta (v1.3.1).** Read [LIMITATIONS.md](./LIMITATIONS.md) before deploying.
Nothing in this repository has been load tested yet, and the test suite has not been
run in the environment that produced this release. Treat the build as unproven until
CI is green on PostgreSQL (see [DEFINITION_OF_DONE.md](./DEFINITION_OF_DONE.md)).

## Quick start

```bash
cp .env.example .env
docker compose up -d postgres redis minio
alembic upgrade head
uvicorn app.main:app --reload
docker compose up media_worker outbox_worker agent_worker scheduler_worker purge_worker
```

## What is real and what is not

| Area | Status |
| --- | --- |
| Auth, conversations, quotas, rate limits, uploads, erasure, outbox, device mesh, approvals | Implemented; covered by tests that are **unrun until CI passes** |
| Chat with a real model | Needs `INFERENCE_BACKEND=openai_compatible` and a running inference server. The default `stub` only echoes. |
| Vision, image/video/music generation | **Not integrated.** Endpoints/abstractions only; no model behind them. |
| Voice | Pipeline exists; needs real ASR and TTS servers (`AUDIO_ASR_BASE_URL`, `AUDIO_TTS_BASE_URL`). |
| Training / LoRA / dataset prep / model download / evaluation | **Placeholders.** The scripts print what they would do. |
| Retrieval | Keyword-overlap ranking, not semantic search. |

## Production checklist

1. `alembic upgrade head` (migrations 0001–0004). The app never calls `create_all` when `ENVIRONMENT=production`.
2. `REDIS_URL` set. Startup fails in production without it.
3. `INFERENCE_BACKEND` is a real backend. Startup fails in production with `stub`.
4. `STORAGE_BACKEND=s3` (local disk is not durable on Render/containers). Startup fails in production with `local`.
5. `CORS_ORIGINS` is a real list, no `*`. `SECRET_KEY` is 64+ random bytes.
6. Run all five workers: `media_worker`, `outbox_worker`, `agent_worker`, `scheduler_worker`, `purge_worker`.
7. Voice: set `AUDIO_ASR_BASE_URL` and `AUDIO_TTS_BASE_URL`. WebSocket auth is first-message only in production.
8. Leave `shell` out of `AGENT_ALLOWED_TOOLS` unless the host is sandboxed.
9. Load balancer health check: `/health/ready` (database only). Alerting: `/health/workers`.

## Benchmarks

No load-test results are published yet. `benchmarks/locustfile.py` exists; run it
against your stack and record the results in LIMITATIONS.md.
