async def test_read_root(client):
    response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "osa-backend is running."}
