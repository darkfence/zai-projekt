import pytest

from app import create_app
from app.extensions import db
from app.measurements_store import MemoryStore
from app.models import Admin
from app.security import hash_password

ADMIN = {"username": "admin", "password": "Haslo-testowe-123"}


@pytest.fixture()
def app():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "MEASUREMENT_STORE": "memory",
        "MEASUREMENT_STORE_INSTANCE": MemoryStore(),
        "SECURITY_HEADERS": True,
    })
    with app.app_context():
        db.create_all()
        db.session.add(Admin(username=ADMIN["username"], password_hash=hash_password(ADMIN["password"])))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def token(client):
    res = client.post("/api/auth/login", json=ADMIN)
    assert res.status_code == 200
    return res.json["accessToken"]


@pytest.fixture()
def auth(token):
    return {"Authorization": f"Bearer {token}"}


def make_series(client, auth, **over):
    body = {"name": "Temperatura", "minValue": 0, "maxValue": 100, "color": "#1f77b4", **over}
    res = client.post("/api/series", json=body, headers=auth)
    assert res.status_code == 201, res.json
    return res.json


def make_sensor(client, auth, series_id):
    res = client.post("/api/sensors", json={"name": "czujnik", "seriesId": series_id}, headers=auth)
    assert res.status_code == 201, res.json
    return res.json
