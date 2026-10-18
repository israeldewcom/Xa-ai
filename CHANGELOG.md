# Changelog

## 1.3.1
Fixes (see tests/test_v131.py):
- Rate limiter is async end-to-end (Redis client is async; sync calls returned unawaited coroutines).
- Agent tools received no context (`db` vs `_db` keys); model-supplied `_`-prefixed args are stripped.
- Path sandboxes use `is_relative_to` (prefix check allowed `/root-evil`).
- Device mesh: 8-digit pairing codes bound to the URL's device, Ed25519-signed device polling, result endpoint, redelivery/expiry in the purge worker.
- Voice: PCM wrapped as WAV before ASR; voice quota enforced; rate limit and quota checked before a session row is created; first-message WS auth forced in production.
- `create_all` disabled in production; migration 0004 adds `ix_jobs_next_attempt_at`; CI runs `alembic check`.
- Readiness depends on the database only; `/health/workers` added; HEALTHCHECK removed from the shared Dockerfile; container runs as non-root.
- Uploads: `UploadFile.read` loop (not async-iterable), storage calls off the event loop, pure-ASGI body cap that also covers chunked bodies, other users' files return 404.
- `/chat/stream` uses its own DB sessions, records usage and quotas; RAG context sent as untrusted `user` content.
- GDPR erasure deletes stored objects after commit.
- Quotas: single conditional UPDATE, atomic on Postgres and SQLite; fixed naive/aware datetime bug.
- Router keyword matching uses word boundaries.
- Approvals: atomic decision, run resumed through the worker queue instead of inline in the API; worker claim uses `SKIP LOCKED` and preserves `started_at`.
- Production config validation rejects `stub` inference and local storage.
- Pricing rounds up so non-zero usage is never free.
