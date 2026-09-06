from datetime import datetime, timezone


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _reading_body(meter_code: str) -> dict:
    return {
        "meter_id": meter_code,
        "voltage": 230.0,
        "current": 5.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def test_meter_defaults_to_relay_connected(client, seed_users_and_meters):
    resp = client.get("/api/meters", headers=auth_headers(seed_users_and_meters["token_admin"]))
    assert resp.status_code == 200
    assert all(m["relay_state"] == "connected" for m in resp.json())


def test_admin_can_disconnect_and_reconnect(client, seed_users_and_meters):
    meter_id = str(seed_users_and_meters["meter_a"].id)
    token = seed_users_and_meters["token_admin"]

    resp = client.patch(
        f"/api/meters/{meter_id}/relay", json={"state": "disconnected"}, headers=auth_headers(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["relay_state"] == "disconnected"
    assert body["relay_updated_at"] is not None

    resp = client.patch(
        f"/api/meters/{meter_id}/relay", json={"state": "connected"}, headers=auth_headers(token)
    )
    assert resp.status_code == 200
    assert resp.json()["relay_state"] == "connected"


def test_consumer_cannot_set_relay(client, seed_users_and_meters):
    meter_id = str(seed_users_and_meters["meter_a"].id)
    resp = client.patch(
        f"/api/meters/{meter_id}/relay",
        json={"state": "disconnected"},
        headers=auth_headers(seed_users_and_meters["token_a"]),
    )
    assert resp.status_code == 403


def test_reading_post_returns_current_relay_command(client, seed_users_and_meters):
    meter = seed_users_and_meters["meter_a"]
    admin = seed_users_and_meters["token_admin"]

    resp = client.post(
        "/api/readings", json=_reading_body(meter.meter_code), headers={"x-device-key": "KEY-A"}
    )
    assert resp.status_code == 201
    assert resp.json()["relay_command"] == "connected"

    client.patch(
        f"/api/meters/{meter.id}/relay", json={"state": "disconnected"}, headers=auth_headers(admin)
    )
    resp = client.post(
        "/api/readings", json=_reading_body(meter.meter_code), headers={"x-device-key": "KEY-A"}
    )
    assert resp.status_code == 201
    assert resp.json()["relay_command"] == "disconnected"


def test_device_can_poll_relay_command(client, seed_users_and_meters):
    resp = client.get("/api/readings/relay", headers={"x-device-key": "KEY-A"})
    assert resp.status_code == 200
    assert resp.json() == {"relay_command": "connected"}


def test_relay_poll_rejects_unknown_device_key(client, seed_users_and_meters):
    resp = client.get("/api/readings/relay", headers={"x-device-key": "nope"})
    assert resp.status_code == 401
