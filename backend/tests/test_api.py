from datetime import datetime, timedelta, timezone

from conftest import ADMIN, make_sensor, make_series

T0, T1, T2 = "2026-01-10T10:00:00Z", "2026-01-10T11:00:00Z", "2026-01-10T12:00:00Z"


def send(client, key, body):
    return client.post("/api/measurements", json=body, headers={"X-API-Key": key} if key else {})


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200 and res.json == {"status": "ok"}


def test_login_and_errors(client):
    res = client.post("/api/auth/login", json=ADMIN)
    assert res.json["tokenType"] == "Bearer" and isinstance(res.json["expiresIn"], int)
    assert client.post("/api/auth/login", json={**ADMIN, "password": "zle"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin"}).status_code == 400
    bad = client.post("/api/series", data='{"name":', content_type="application/json",
                      headers={"Authorization": "Bearer " + res.json["accessToken"]})
    assert bad.status_code == 400
    assert bad.content_type == "application/problem+json"
    assert bad.json["status"] == 400 and bad.json["title"]


def test_logout_revokes_token(client, auth):
    assert client.post("/api/auth/logout", headers=auth).status_code == 204
    assert client.get("/api/sensors", headers=auth).status_code == 401


def test_password_change(client, auth):
    body = {"currentPassword": "zle", "newPassword": "NoweHaslo-123"}
    assert client.put("/api/auth/password", json=body, headers=auth).status_code == 403
    assert client.put("/api/auth/password", json=body).status_code == 401
    short = {"currentPassword": ADMIN["password"], "newPassword": "krotkie"}
    assert client.put("/api/auth/password", json=short, headers=auth).status_code == 422
    ok = {"currentPassword": ADMIN["password"], "newPassword": "NoweHaslo-123"}
    assert client.put("/api/auth/password", json=ok, headers=auth).status_code == 204
    assert client.post("/api/auth/login", json={"username": "admin", "password": "NoweHaslo-123"}).status_code == 200


def test_series_crud(client, auth):
    s = make_series(client, auth, unit="°C")
    assert s["unit"] == "°C"
    res = client.get(f"/api/series/{s['id']}")
    assert res.status_code == 200 and res.json["name"] == "Temperatura"
    upd = client.put(f"/api/series/{s['id']}", json={"name": "T2", "minValue": -5, "maxValue": 5, "color": "#FF7F0E"},
                     headers=auth)
    assert upd.status_code == 200 and upd.json["color"] == "#ff7f0e"
    assert client.delete(f"/api/series/{s['id']}", headers=auth).status_code == 204
    missing = client.get(f"/api/series/{s['id']}")
    assert missing.status_code == 404 and missing.content_type == "application/problem+json"
    assert client.get("/api/series/99999999999").status_code == 404


def test_series_validation(client, auth):
    base = {"name": "x", "minValue": 0, "maxValue": 1, "color": "#000000"}
    assert client.post("/api/series", json={**base, "maxValue": 0}, headers=auth).status_code == 422
    assert client.post("/api/series", json={**base, "color": "red"}, headers=auth).status_code == 422
    assert client.post("/api/series", json={k: v for k, v in base.items() if k != "name"}, headers=auth).status_code in (400, 422)
    assert client.post("/api/series", json={**base, "minValue": "0"}, headers=auth).status_code == 400
    assert client.post("/api/series", json={**base, "minValue": True}, headers=auth).status_code == 400
    assert client.post("/api/series", json=base).status_code == 401
    assert client.post("/api/series", data="x", content_type="text/plain", headers=auth).status_code == 415


def test_sensor_lifecycle(client, auth):
    s = make_series(client, auth)
    sensor = make_sensor(client, auth, s["id"])
    key = sensor["apiKey"]
    assert len(key) >= 32
    listing = client.get("/api/sensors", headers=auth)
    assert key not in listing.get_data(as_text=True) and "apiKey" not in listing.json[0]
    m = send(client, key, {"value": 21.5, "timestamp": T1})
    assert m.status_code == 201
    assert m.headers["Location"] == f"/api/measurements/{m.json['id']}"
    assert client.get(f"/api/sensors/{sensor['id']}", headers=auth).json["lastMeasurementAt"]
    assert client.delete(f"/api/sensors/{sensor['id']}", headers=auth).status_code == 204
    assert send(client, key, {"value": 1}).status_code == 401
    assert client.get(m.headers["Location"]).status_code == 200
    assert client.post("/api/sensors", json={"name": "x", "seriesId": 999999999}, headers=auth).status_code == 422


def test_measurements_query(client, auth):
    s = make_series(client, auth)
    key = make_sensor(client, auth, s["id"])["apiKey"]
    for value, ts in [(21.5, T1), (10, T2), (30, T0)]:
        assert send(client, key, {"value": value, "timestamp": ts}).status_code == 201
    now = send(client, key, {"value": 5})
    assert abs(datetime.fromisoformat(now.json["timestamp"].replace("Z", "+00:00")) - datetime.now(timezone.utc)) < timedelta(minutes=1)

    res = client.get(f"/api/measurements?series={s['id']}")
    times = [m["timestamp"] for m in res.json]
    assert len(times) == 4 and times == sorted(times)
    desc = client.get(f"/api/measurements?series={s['id']}&sort=-timestamp").json
    assert [m["timestamp"] for m in desc] == sorted(times, reverse=True)
    window = client.get(f"/api/measurements?series={s['id']}&from={T0}&to={T1}").json
    assert len(window) == 2
    assert len(client.get(f"/api/measurements?series={s['id']}&limit=2").json) == 2

    other = make_series(client, auth, name="Inna")
    okey = make_sensor(client, auth, other["id"])["apiKey"]
    send(client, okey, {"value": 1, "timestamp": T0})
    assert len(client.get(f"/api/measurements?series={s['id']},{other['id']}").json) == 5

    for q in ("from=nie-data", "series=a", "limit=0", "sort=value"):
        assert client.get(f"/api/measurements?{q}").status_code == 400


def test_same_timestamp_does_not_overwrite(client, auth):
    s = make_series(client, auth)
    key = make_sensor(client, auth, s["id"])["apiKey"]
    a = send(client, key, {"value": 1, "timestamp": T0}).json
    b = send(client, key, {"value": 2, "timestamp": T0}).json
    assert a["id"] != b["id"]
    assert len(client.get(f"/api/measurements?series={s['id']}").json) == 2


def test_measurement_validation(client, auth):
    s = make_series(client, auth, minValue=-5, maxValue=5)
    key = make_sensor(client, auth, s["id"])["apiKey"]
    assert send(client, key, {"value": -5, "timestamp": T0}).status_code == 201
    assert send(client, key, {"value": 5, "timestamp": T1}).status_code == 201
    out = send(client, key, {"value": 6, "timestamp": T2})
    assert out.status_code == 422 and out.content_type == "application/problem+json"
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert send(client, key, {"value": 1, "timestamp": future}).status_code == 422
    for body in ({"value": "abc"}, {}, {"value": 1, "timestamp": "wczoraj"}):
        assert send(client, key, body).status_code in (400, 422)
    assert send(client, None, {"value": 1}).status_code == 401
    assert send(client, "x" * 40, {"value": 1}).status_code == 401
    assert client.post("/api/measurements", json={"value": 1}, headers=auth).status_code == 401
    txt = client.post("/api/measurements", data="value=1", content_type="text/plain", headers={"X-API-Key": key})
    assert txt.status_code == 415


def test_range_change_conflict(client, auth):
    s = make_series(client, auth)
    key = make_sensor(client, auth, s["id"])["apiKey"]
    send(client, key, {"value": 21.5, "timestamp": T0})
    body = {"name": s["name"], "minValue": 50, "maxValue": 60, "color": "#1f77b4"}
    assert client.put(f"/api/series/{s['id']}", json=body, headers=auth).status_code == 409


def test_measurements_immutable(client, auth):
    s = make_series(client, auth)
    key = make_sensor(client, auth, s["id"])["apiKey"]
    m = send(client, key, {"value": 7, "timestamp": T0}).json
    for method in ("put", "patch", "delete"):
        res = getattr(client, method)(f"/api/measurements/{m['id']}", json={"value": 8}, headers=auth)
        assert res.status_code in (404, 405)
    assert client.get(f"/api/measurements/{m['id']}").json["value"] == 7
    assert client.get("/api/measurements/nie-istnieje").status_code == 404


def test_delete_series_cascades(client, auth):
    s = make_series(client, auth)
    sensor = make_sensor(client, auth, s["id"])
    m = send(client, sensor["apiKey"], {"value": 1, "timestamp": T0}).json
    assert client.delete(f"/api/series/{s['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/measurements/{m['id']}").status_code == 404
    assert client.get(f"/api/sensors/{sensor['id']}", headers=auth).status_code == 404
    assert send(client, sensor["apiKey"], {"value": 1}).status_code == 401


def test_admin_endpoints_require_token(client, auth):
    s = make_series(client, auth)
    sensor = make_sensor(client, auth, s["id"])
    checks = [
        ("post", "/api/series"), ("put", f"/api/series/{s['id']}"), ("delete", f"/api/series/{s['id']}"),
        ("get", "/api/sensors"), ("get", f"/api/sensors/{sensor['id']}"), ("post", "/api/sensors"),
        ("delete", f"/api/sensors/{sensor['id']}"),
    ]
    for method, path in checks:
        assert getattr(client, method)(path, json={}).status_code == 401, (method, path)
    forged = {"Authorization": "Bearer eyJhbGciOiJub25lIn0.eyJzdWIiOiJhZG1pbiJ9."}
    assert client.post("/api/series", json={}, headers=forged).status_code == 401


def test_content_negotiation_and_headers(client):
    assert client.get("/api/series", headers={"Accept": "application/xml"}).status_code == 406
    assert client.get("/api/series", headers={"Accept": "*/*"}).status_code == 200
    res = client.get("/api/series")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in res.headers
    assert "Access-Control-Allow-Origin" not in res.headers


def test_no_secrets_in_responses(client, auth):
    s = make_series(client, auth)
    sensor = make_sensor(client, auth, s["id"])
    send(client, sensor["apiKey"], {"value": 1, "timestamp": T0})
    for res in (client.post("/api/auth/login", json=ADMIN), client.get("/api/series"),
                client.get("/api/sensors", headers=auth), client.get(f"/api/measurements?series={s['id']}")):
        text = res.get_data(as_text=True)
        assert ADMIN["password"] not in text and sensor["apiKey"] not in text
        assert "hash" not in text.lower()
