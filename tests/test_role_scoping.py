def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_consumer_sees_only_own_meter(client, seed_users_and_meters):
    token = seed_users_and_meters["token_a"]
    resp = client.get("/api/meters", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["meter_code"] == "MTR-A"


def test_consumer_gets_403_on_other_consumers_meter(client, seed_users_and_meters):
    token = seed_users_and_meters["token_a"]
    other_meter_id = seed_users_and_meters["meter_b"].id
    resp = client.get(f"/api/meters/{other_meter_id}", headers=auth_headers(token))
    assert resp.status_code == 403


def test_consumer_gets_403_on_create_meter(client, seed_users_and_meters):
    token = seed_users_and_meters["token_a"]
    consumer_b_id = seed_users_and_meters["consumer_b"].id
    resp = client.post(
        "/api/meters",
        json={
            "meter_code": "MTR-NEW",
            "user_id": str(consumer_b_id),
            "device_key": "KEY-NEW",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def test_admin_sees_all_meters(client, seed_users_and_meters):
    token = seed_users_and_meters["token_admin"]
    resp = client.get("/api/meters", headers=auth_headers(token))
    assert resp.status_code == 200
    codes = {m["meter_code"] for m in resp.json()}
    assert codes == {"MTR-A", "MTR-B"}


def test_admin_can_create_meter_with_explicit_user_id(client, seed_users_and_meters):
    token = seed_users_and_meters["token_admin"]
    consumer_a_id = seed_users_and_meters["consumer_a"].id
    resp = client.post(
        "/api/meters",
        json={
            "meter_code": "MTR-NEW",
            "user_id": str(consumer_a_id),
            "device_key": "KEY-NEW",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user_id"] == str(consumer_a_id)
    assert body["meter_code"] == "MTR-NEW"
