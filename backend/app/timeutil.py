"""Konwersje czasu: ISO 8601 <-> datetime (UTC) <-> nanosekundy od epoki."""
import re
from datetime import datetime, timedelta, timezone

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,9}))?)?)?"
    r"\s*(Z|z|[+-]\d{2}(?::?\d{2})?)?$"
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """Datetime z bazy (SQLite zwraca naiwne) -> świadomy UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso(value) -> datetime | None:
    """Parsuje znacznik ISO 8601. Brak strefy = UTC. Zwraca None, gdy niepoprawny."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hh, mm, ss, frac, tz = m.groups()
    micro = int((frac or "0")[:6].ljust(6, "0"))
    try:
        if tz in (None, "Z", "z"):
            tzinfo = timezone.utc
        else:
            sign = 1 if tz[0] == "+" else -1
            digits = tz[1:].replace(":", "")
            hours = int(digits[:2])
            minutes = int(digits[2:4] or 0)
            if hours > 23 or minutes > 59:
                return None
            tzinfo = timezone(sign * timedelta(hours=hours, minutes=minutes))
        dt = datetime(int(year), int(month), int(day), int(hh or 0), int(mm or 0), int(ss or 0), micro, tzinfo=tzinfo)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def to_ns(dt: datetime) -> int:
    return ((as_utc(dt) - EPOCH) // timedelta(microseconds=1)) * 1000


def from_ns(ns: int) -> datetime:
    return EPOCH + timedelta(microseconds=ns // 1000)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return as_utc(dt).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_ns(ns: int) -> str:
    return iso(from_ns(ns))
