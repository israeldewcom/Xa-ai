async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_metrics(client):
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert b"xa_http_requests_total" in r.content


async def test_ready_depends_on_database_only(client):
    r = await client.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


async def test_workers_endpoint_reports_stale_workers(client):
    r = await client.get("/health/workers")
    # No worker processes run under pytest, so every kind is stale.
    assert r.status_code == 503
    assert set(r.json()["stale"]) == {
        "media_worker", "outbox_worker", "agent_worker",
        "scheduler_worker", "purge_worker",
    }
