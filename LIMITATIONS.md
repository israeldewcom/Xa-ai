# Known limitations — XA AI v1.3.1

This file is honest. If a claim in the README isn't backed by evidence here,
the README is wrong.

## Not implemented
- **2FA / MFA** — password-only auth. TOTP is a 1-day follow-up.
- **Email verification** — users can register with unverified emails.
- **Password reset** — no self-service reset; admins reset via DB.
- **CSAM scanning** — requires a third-party integration (PhotoDNA etc.).
- **Content moderation** — `MODERATION_BASE_URL` is wired but no adapter.
- **OpenTelemetry** — Prometheus metrics only; no distributed tracing.
- **Multi-region outbox** — single-DB assumption. For multi-region, replicate
  or use a Kafka/Pulsar outbox.
- **Distributed rate limiter without Redis** — in-memory limiter in production
  is per-worker; N workers means N× the limit. Redis is required in prod.
- **Streaming LLM via SSE with tool-calling** — streaming currently text-only.

## Assumptions
- **Single-DB, single-tenant-ish** — one PostgreSQL instance for all users.
  Scale-to-zero friendly, but not partition-ready.
- **Workers are trusted** — they run in the same VPC as the DB.
- **No private IP outbound** — set `OUTBOUND_BLOCK_PRIVATE_IPS=true` (default).
  If you wire a local inference backend, use an internal network and adjust.
- **The stub LLM does not call tools** — agent flows return "failed" without
  a real model. This is intentional: the agent must not fabricate tool output.

## Sandbox
- **Shell tool is disabled by default.** Opt in only if the training workspace
  is truly sandboxed (container + read-only FS + no network).
- **File paths are bounded to `TRAINING_WORKSPACE`** but this is a lexical
  check, not a kernel-level sandbox. Symlinks are prevented but hardlinks
  are not. Do not enable shell in multi-tenant deployments.

## Voice
- **VAD requires `webrtcvad`** (in requirements-voice.txt). Without it we fall
  back to energy-threshold VAD which is noticeably worse in noisy environments.
- **`?token=` WS auth is always rejected when `ENVIRONMENT=production`**
  (first-message auth only). Outside production it is allowed unless
  `VOICE_WS_AUTH_STRICT=true`.
- **Voice is metered** against `QUOTA_VOICE_MINUTES_PER_DAY`; a session that ends
  over quota is allowed to finish and the next one is refused.
- **Audio is not stored.** No playback history, no re-transcription.

## Devices
- **No push transport.** Commands are pulled by polling. Adding WS push is
  straightforward (reuse the voice WS) but not implemented.
- **Pairing code is 8 digits**, bound to the device in the URL and rate limited
  per user. Still not a substitute for a QR/out-of-band flow in high-security
  deployments. Two simultaneous pairings can collide on the unique code (rare,
  surfaces as a 500 on `pair/start`; retry).
- **Device request replay window is 60 s.** Signed requests carry a timestamp but
  no nonce, so a captured poll can be replayed inside that window.

## Compliance
- **GDPR erasure** — `/api/v1/account/erase` removes all user-owned rows
  (verified by test). Audit events are scrubbed but retained for the
  regulatory window (configurable via `RETENTION_AUDIT_DAYS`).
- **No SOC 2 / HIPAA** — this is not an audit-ready build. Get a real one.

## Benchmarks
No load-test results are published yet. `benchmarks/locustfile.py` exists; run it
against your stack and record results here.

## Security caveats
- **DNS rebinding.** The SSRF check and the actual connection resolve DNS
  separately. For high-risk deployments pin the resolved IP.
- **Keyword-overlap RAG** scans all of a user's chunks in Python. Move to
  pgvector once a user has more than a few thousand chunks.
- **Declared upload type.** Binary types are detected by magic bytes; plain
  text/markdown fall back to the client-declared content type.
- **Agent runs are not reaped if a worker dies mid-run** (status stays
  `running`). Add a reaper before relying on agents unattended.
- **Not capabilities:** vision, image/video/music generation, training and
  evaluation are placeholders (see README).

See `DEFINITION_OF_DONE.md` for the acceptance criteria.
