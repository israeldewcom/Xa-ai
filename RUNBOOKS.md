# Runbooks

Short operational playbooks. Each is half a page. On-call should be able to
act from this file alone.

## Outbox stuck (webhook deliveries not going out)
**Symptom:** `xa_outbox_events_total{status="pending"}` growing, no deliveries.
1. `SELECT status, count(*) FROM outbox_events GROUP BY status;`
2. If `delivering` is large, workers crashed. Wait 60s for the reaper, or
   `UPDATE outbox_events SET status='retry', claimed_at=NULL WHERE status='delivering' AND claimed_at < now() - interval '60 seconds';`
3. Check `outbox_worker` logs: `kubectl logs deploy/xa-ai-outbox`.
4. If the user's webhook URL is unreachable, they will see retries. After
   3 failures they're marked `failed`. Advise user to fix URL.

## Worker crash loop
**Symptom:** `/health/ready` reports `worker_stale: X` repeatedly.
1. `kubectl logs deploy/xa-ai-X --tail=200`.
2. Common causes: bad config (missing DB creds), migration pending, deadlock.
3. If a job is poison: `UPDATE jobs SET dead_lettered=true, status='failed'
   WHERE id='<job_id>';`
4. Restart: `kubectl rollout restart deploy/xa-ai-X`.

## Quota race / one user gets too many requests
**Symptom:** User reports being over quota (or under).
1. `SELECT user_id, key, used FROM daily_quotas WHERE user_id='<id>' AND day=current_date;`
2. If `used` doesn't match expectations, check the row lock is working — look
   for `pg_insert` in `quotas.py` on the active branch.
3. Manual reset: `UPDATE daily_quotas SET used=0 WHERE user_id='<id>' AND key='<key>' AND day=current_date;`

## Device offline (commands queued forever)
**Symptom:** `device_commands` grows for a device; device never acks.
1. `SELECT count(*) FROM device_commands WHERE device_id='<id>' AND status='queued';`
2. Commands have TTL (`DEVICE_COMMAND_TTL_SECONDS`). Expired ones should be
   reaped by the purge worker.
3. Advise user to re-pair the device.

## High 5xx rate
**Symptom:** `xa_http_requests_total{status=~"5.."}` growing.
1. `kubectl logs deploy/xa-ai-api --tail=500 | grep ERROR`.
2. Likely: DB down, Redis unreachable (if `REDIS_URL` set), or inference
   backend down.
3. `curl https://api.xa.ai/health/ready` — the problems array tells you.
4. If inference is down: set `INFERENCE_BACKEND=stub` temporarily to shed load.
