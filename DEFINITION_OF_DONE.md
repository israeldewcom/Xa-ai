# Definition of done — v1.3.1

**No box below is ticked.** Tick one only after the named test or check passes in CI
on PostgreSQL. This release was produced without being able to run the suite.

Every PR must cite this file. A bug fix that doesn't reference a line here is
an unfinished bug fix.

## Correctness
- [ ] Every Phase 0/1/2 bug has a behavioral test that fails before the fix
      and passes after (no source-code greps — see tests/test_fixes.py).
- [ ] `test_quota_under_concurrency` fires 20 concurrent requests at a limit
      of 5 and asserts exactly 5 successes and 15 rate-limited.
- [ ] `test_backoff_honors_next_attempt_at` proves a failed job is queued but
      not re-claimable before `next_attempt_at`.
- [ ] `test_erasure_removes_user` deletes a seeded user and asserts 0 rows in
      conversations, daily_quotas, usage_events, and users.
- [ ] `test_voice_barge_in_cancels_tts` emits the barge-in sentinel on the
      first speech chunk during TTS.
- [ ] `test_outbox_reaper_recovers_crashed_claims` simulates a crashed worker
      and proves the reaper reclaims the event after the lease expires.
- [ ] `test_approval_expiry_fails_run` proves the purge worker expires
      approvals and fails the associated run.
- [ ] `test_agent_run_returns_202_queued` proves runs are enqueued, not
      executed inline.
- [ ] `test_device_command_encrypted_decryptable_by_device_key` uses the
      device's private key + server public key ONLY to decrypt — proves the
      channel is real, not just self-consistent.
- [ ] `test_x25519_persists_across_secret_rotation` proves device channels
      survive a `SECRET_KEY` change.
- [ ] `test_shell_not_in_default_allowed_tools` proves shell is opt-in.
- [ ] `test_cost_is_recorded` proves `cost_micros` is populated from the
      pricing table.

## Tests / CI
- [ ] `pytest.ini` enforces `--cov-fail-under=75`.
- [ ] `ruff check` must pass.
- [ ] `mypy --strict app/` must pass (CI currently runs it with `|| true`; remove that once the type errors are fixed).
- [ ] Alembic roundtrip (`upgrade head`, `downgrade base`, `upgrade head`)
      passes on SQLite and PostgreSQL.
- [ ] `docker build` succeeds and `check_environment.py` returns 0.

## Documentation
- [ ] `LIMITATIONS.md` exists and is honest.
- [ ] `RUNBOOKS.md` covers the top 5 failure modes.
- [ ] README makes no production-ready or throughput claim without a recorded load test.
- [ ] No `12/10` or `10/10` claims in the README. Version number is the
      claim.

## Operational
- [ ] `/metrics` exposes Prometheus counters.
- [ ] `/health/ready` reflects the database only; `/health/workers` returns 503
      if any worker hasn't heartbeated within 3× its interval.
- [ ] Worker heartbeats are written every 15s.
- [ ] Orphaned voice sessions (>1h active) are reaped.
- [ ] `test_v131.py` passes: Redis limiter, tool-context injection, device poll
      flow, pairing bound to device, atomic quotas, router keywords, body cap.
