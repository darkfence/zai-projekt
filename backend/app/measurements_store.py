"""Magazyn wyników pomiarów.

`InfluxStore` zapisuje wyniki w InfluxDB 1.8 (measurement `pomiar`):
  * tag    `series_id` – identyfikator serii (filtrowanie i usuwanie serii),
  * pole   `value`     – wartość (zawsze float),
  * pole   `sensor_id` – czujnik, który przesłał wynik (pole, nie tag – brak wzrostu kardynalności),
  * czas   – znacznik z precyzją ns.

Punkt w InfluxDB jest jednoznacznie wyznaczony przez (measurement, tagi, czas),
dlatego identyfikator wyniku to nieprzezroczysty napis `"{seriesId}-{czas_ns}"`.
Dwa wyniki tej samej serii z identycznym znacznikiem czasu nadpisałyby się, więc
przy kolizji czas nowego punktu jest przesuwany o 1 ns.

`MemoryStore` ma ten sam interfejs i służy do testów jednostkowych.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from .timeutil import iso_ns

MEASUREMENT = "pomiar"
_ID_RE = re.compile(r"^(\d{1,10})-(\d{1,20})$")
_MAX_COLLISION_SHIFT = 1000


@dataclass(frozen=True)
class Point:
    series_id: int
    ts_ns: int
    value: float
    sensor_id: int | None = None

    @property
    def id(self) -> str:
        return f"{self.series_id}-{self.ts_ns}"

    def to_dict(self) -> dict:
        d = {"id": self.id, "seriesId": self.series_id, "value": self.value, "timestamp": iso_ns(self.ts_ns)}
        if self.sensor_id is not None:
            d["sensorId"] = self.sensor_id
        return d


def parse_measurement_id(raw: str) -> tuple[int, int] | None:
    m = _ID_RE.match(raw or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


class MeasurementStore:
    def init(self) -> None: ...
    def ping(self) -> bool: ...
    def write(self, series_id: int, sensor_id: int | None, value: float, ts_ns: int) -> Point: ...
    def get(self, series_id: int, ts_ns: int) -> Point | None: ...
    def query(self, series_ids: list[int] | None, from_ns: int | None, to_ns: int | None,
              descending: bool, limit: int) -> list[Point]: ...
    def value_range(self, series_id: int) -> tuple[float, float] | None: ...
    def delete_series(self, series_id: int) -> None: ...


class MemoryStore(MeasurementStore):
    def __init__(self):
        self._points: dict[tuple[int, int], Point] = {}
        self._lock = threading.Lock()

    def init(self) -> None:
        pass

    def ping(self) -> bool:
        return True

    def write(self, series_id, sensor_id, value, ts_ns):
        with self._lock:
            ts = ts_ns
            while (series_id, ts) in self._points:
                ts += 1
            p = Point(series_id, ts, float(value), sensor_id)
            self._points[(series_id, ts)] = p
            return p

    def get(self, series_id, ts_ns):
        return self._points.get((series_id, ts_ns))

    def query(self, series_ids, from_ns, to_ns, descending, limit):
        pts = [
            p for p in self._points.values()
            if (series_ids is None or p.series_id in series_ids)
            and (from_ns is None or p.ts_ns >= from_ns)
            and (to_ns is None or p.ts_ns <= to_ns)
        ]
        pts.sort(key=lambda p: (p.ts_ns, p.series_id), reverse=descending)
        return pts[:limit]

    def value_range(self, series_id):
        vals = [p.value for p in self._points.values() if p.series_id == series_id]
        return (min(vals), max(vals)) if vals else None

    def delete_series(self, series_id):
        with self._lock:
            for key in [k for k in self._points if k[0] == series_id]:
                del self._points[key]


class InfluxStore(MeasurementStore):
    def __init__(self, host: str, port: int, database: str, username: str = "", password: str = ""):
        from influxdb import InfluxDBClient

        self.database = database
        self.client = InfluxDBClient(host=host, port=port, username=username or None,
                                     password=password or None, database=database, timeout=10, retries=2)
        self._lock = threading.Lock()

    # --- pomocnicze -------------------------------------------------------
    def _select(self, where: str, params: dict, tail: str = "") -> list[Point]:
        # Wszystkie wartości pochodzące od użytkownika trafiają do bind_params.
        q = f'SELECT "value", "sensor_id", "series_id" FROM "{MEASUREMENT}" WHERE {where} {tail}'
        rs = self.client.query(q, bind_params=params, epoch="ns")
        out = []
        for row in rs.get_points():
            sensor = row.get("sensor_id")
            out.append(Point(int(row["series_id"]), int(row["time"]), float(row["value"]),
                             int(sensor) if sensor is not None else None))
        return out

    # --- interfejs --------------------------------------------------------
    def init(self) -> None:
        try:
            self.client.create_database(self.database)  # idempotentne
        except Exception:  # brak uprawnień admina – baza tworzona przez obraz Dockera
            pass

    def ping(self) -> bool:
        try:
            self.client.ping()
            return True
        except Exception:
            return False

    def get(self, series_id, ts_ns):
        pts = self._select('"series_id" = $sid AND time = $t', {"sid": str(series_id), "t": int(ts_ns)})
        return pts[0] if pts else None

    def write(self, series_id, sensor_id, value, ts_ns):
        with self._lock:
            ts = int(ts_ns)
            for _ in range(_MAX_COLLISION_SHIFT):
                if self.get(series_id, ts) is None:
                    break
                ts += 1
            fields = {"value": float(value)}
            if sensor_id is not None:
                fields["sensor_id"] = int(sensor_id)
            self.client.write_points(
                [{"measurement": MEASUREMENT, "tags": {"series_id": str(series_id)}, "time": ts, "fields": fields}],
                time_precision="n",
            )
            return Point(int(series_id), ts, float(value), sensor_id)

    def query(self, series_ids, from_ns, to_ns, descending, limit):
        conds, params = [], {}
        if series_ids is not None:
            if not series_ids:
                return []
            ors = []
            for i, sid in enumerate(series_ids):
                params[f"s{i}"] = str(sid)
                ors.append(f'"series_id" = $s{i}')
            conds.append("(" + " OR ".join(ors) + ")")
        if from_ns is not None:
            params["from"] = int(from_ns)
            conds.append("time >= $from")
        if to_ns is not None:
            params["to"] = int(to_ns)
            conds.append("time <= $to")
        where = " AND ".join(conds) if conds else "time >= 0"
        order = "DESC" if descending else "ASC"
        return self._select(where, params, f"ORDER BY time {order} LIMIT {int(limit)}")

    def value_range(self, series_id):
        q = f'SELECT MIN("value") AS mn, MAX("value") AS mx FROM "{MEASUREMENT}" WHERE "series_id" = $sid'
        rows = list(self.client.query(q, bind_params={"sid": str(series_id)}).get_points())
        if not rows or rows[0].get("mn") is None:
            return None
        return float(rows[0]["mn"]), float(rows[0]["mx"])

    def delete_series(self, series_id):
        self.client.delete_series(database=self.database, measurement=MEASUREMENT,
                                  tags={"series_id": str(series_id)})


def create_store(config) -> MeasurementStore:
    if config["MEASUREMENT_STORE"] == "memory":
        return MemoryStore()
    return InfluxStore(config["INFLUX_HOST"], config["INFLUX_PORT"], config["INFLUX_DB"],
                       config["INFLUX_USER"], config["INFLUX_PASSWORD"])
