"""Model relacyjny: administrator, tokeny sesji, serie i czujniki.

Wyniki pomiarów są przechowywane w InfluxDB (zob. measurements_store.py).
"""
from sqlalchemy import CheckConstraint, Double, Index

from .extensions import db
from .timeutil import iso, utcnow


class Admin(db.Model):
    __tablename__ = "admin"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    tokens = db.relationship("AuthToken", back_populates="admin", cascade="all, delete-orphan")


class AuthToken(db.Model):
    """Token Bearer administratora; w bazie wyłącznie skrót SHA-256."""

    __tablename__ = "auth_token"

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("admin.id", ondelete="CASCADE"), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)

    admin = db.relationship("Admin", back_populates="tokens")


class Series(db.Model):
    __tablename__ = "series"
    __table_args__ = (
        CheckConstraint("min_value < max_value", name="ck_series_range"),
        CheckConstraint("length(color) = 7", name="ck_series_color"),
        CheckConstraint("length(name) >= 1", name="ck_series_name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    min_value = db.Column(Double, nullable=False)
    max_value = db.Column(Double, nullable=False)
    color = db.Column(db.String(7), nullable=False)
    icon = db.Column(db.String(50), nullable=True)
    unit = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    sensors = db.relationship("Sensor", back_populates="series", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "minValue": self.min_value,
            "maxValue": self.max_value,
            "color": self.color,
            "icon": self.icon,
            "unit": self.unit,
        }


class Sensor(db.Model):
    """Czujnik przypisany do serii; klucz API przechowywany jako SHA-256."""

    __tablename__ = "sensor"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    series_id = db.Column(db.Integer, db.ForeignKey("series.id", ondelete="CASCADE"), nullable=False, index=True)
    api_key_hash = db.Column(db.String(64), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    last_measurement_at = db.Column(db.DateTime(timezone=True), nullable=True)

    series = db.relationship("Series", back_populates="sensors")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "seriesId": self.series_id,
            "createdAt": iso(self.created_at),
            "lastMeasurementAt": iso(self.last_measurement_at),
        }


Index("ix_auth_token_admin_expires", AuthToken.admin_id, AuthToken.expires_at)
