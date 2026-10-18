async def test_cursor_pagination_walks(auth_client):
    # Create 60 conversations by starting chats
    for i in range(60):
        await auth_client.post("/api/v1/chat", json={"message": f"hi {i}"})

    r = await auth_client.get("/api/v1/conversations?limit=20")
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 20
    assert data["next_cursor"] is not None

    # Walk the cursor
    seen_ids = {i["id"] for i in data["items"]}
    cursor = data["next_cursor"]
    while cursor:
        r = await auth_client.get(f"/api/v1/conversations?limit=20&cursor={cursor}")
        data = r.json()
        for item in data["items"]:
            assert item["id"] not in seen_ids, "duplicate item across pages"
            seen_ids.add(item["id"])
        cursor = data["next_cursor"]

    assert len(seen_ids) == 60
