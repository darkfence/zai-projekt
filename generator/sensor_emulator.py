#!/usr/bin/env python3
"""Emulator czujnika IoT (F13) – wysyła wyniki do API przez POST /api/measurements.

Tryby:
  backfill – seria wyników ze znacznikami czasu z przeszłości (dane przykładowe),
  live     – bieżące wyniki w stałych odstępach czasu.

Przykłady:
  export ZAI_SENSOR_KEY=...            # klucz otrzymany przy rejestracji czujnika
  python sensor_emulator.py --api https://zai.example.com --mode backfill --count 96 --step 30m \\
         --shape sine --min 15 --max 25 --period 24h
  python sensor_emulator.py --api https://zai.example.com --mode live --interval 10s --shape walk --min 40 --max 70
  python sensor_emulator.py --api ... --shape const --value 999 --count 1   # demonstracja odrzucenia (422)

Klucz API podaje się parametrem --key albo zmienną środowiskową ZAI_SENSOR_KEY;
nigdy nie jest zapisany w kodzie. Wymaga wyłącznie biblioteki standardowej Pythona 3.9+.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import re
import sys
import time
import urllib.error
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zai_client import ApiClient  # noqa: E402

_DUR_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h|d)?\s*$")
_UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, None: 1}


def duration(text: str) -> float:
    """'30m' -> 1800.0 s; bez jednostki = sekundy."""
    m = _DUR_RE.match(text)
    if not m:
        raise argparse.ArgumentTypeError(f"niepoprawny czas trwania: {text!r} (np. 10s, 30m, 1h)")
    value = float(m.group(1)) * _UNITS[m.group(2)]
    if value <= 0:
        raise argparse.ArgumentTypeError("czas trwania musi być dodatni")
    return value


class ValueGenerator:
    """Generuje wartości wg kształtu przebiegu; t – czas w sekundach od epoki."""

    def __init__(self, shape: str, lo: float, hi: float, period: float, noise: float, value: float | None,
                 decimals: int, rng: random.Random):
        self.shape, self.lo, self.hi = shape, lo, hi
        self.period, self.noise, self.const = period, noise, value
        self.decimals, self.rng = decimals, rng
        self.walk = (lo + hi) / 2

    def __call__(self, t: float) -> float:
        lo, hi = self.lo, self.hi
        if self.shape == "const":
            v = self.const if self.const is not None else (lo + hi) / 2
            return round(v, self.decimals)  # celowo bez przycinania – pozwala pokazać odrzucenie
        if self.shape == "random":
            v = self.rng.uniform(lo, hi)
        elif self.shape == "sine":
            mid, amp = (lo + hi) / 2, (hi - lo) / 2
            v = mid + amp * math.sin(2 * math.pi * t / self.period) + self.rng.gauss(0, self.noise)
        else:  # walk – błądzenie losowe odbijane od granic
            step = self.noise or (hi - lo) / 50
            self.walk += self.rng.gauss(0, step)
            if self.walk < lo:
                self.walk = 2 * lo - self.walk
            if self.walk > hi:
                self.walk = 2 * hi - self.walk
            v = self.walk
        return round(min(max(v, lo), hi), self.decimals)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def send(client: ApiClient, key: str, value: float, ts: datetime | None, retries: int) -> bool:
    body = {"value": value}
    if ts is not None:
        body["timestamp"] = iso(ts)
    for attempt in range(retries + 1):
        try:
            res = client.request("POST", "/api/measurements", body, {"X-API-Key": key})
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == retries:
                print(f"✘ BŁĄD POŁĄCZENIA  wartość={value}  ({e})", file=sys.stderr)
                return False
            time.sleep(2 * (attempt + 1))
    when = body.get("timestamp", "teraz")
    if res.status == 201:
        m = res.body or {}
        print(f"✔ zapisano   id={m.get('id')}  wartość={m.get('value')}  czas={m.get('timestamp', when)}")
        return True
    label = {401: "ODRZUCONO (klucz)", 422: "ODRZUCONO (walidacja)"}.get(res.status, "ODRZUCONO")
    print(f"✘ {label} HTTP {res.status}  wartość={value}  czas={when}\n    → {res.problem_text()}", file=sys.stderr)
    return False


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Emulator czujnika – wysyła wyniki pomiarów do API ZAI (POST /api/measurements).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--api", default=os.environ.get("ZAI_API_URL"), help="adres aplikacji, np. https://zai.example.com (lub ZAI_API_URL)")
    p.add_argument("--key", default=os.environ.get("ZAI_SENSOR_KEY"), help="klucz API czujnika (lub zmienna ZAI_SENSOR_KEY)")
    p.add_argument("--mode", choices=["backfill", "live"], default="live", help="backfill – wyniki z przeszłości, live – bieżące")
    p.add_argument("--count", type=int, help="liczba wyników (backfill: wymagana; live: domyślnie bez końca)")
    p.add_argument("--step", type=duration, default="30m", help="backfill: odstęp między znacznikami czasu")
    p.add_argument("--end", help="backfill: znacznik ostatniego wyniku (ISO 8601), domyślnie teraz")
    p.add_argument("--interval", type=duration, default="10s", help="live: odstęp między wysyłkami")
    p.add_argument("--shape", choices=["sine", "random", "walk", "const"], default="sine", help="kształt przebiegu wartości")
    p.add_argument("--min", type=float, default=0.0, help="minimalna generowana wartość")
    p.add_argument("--max", type=float, default=100.0, help="maksymalna generowana wartość")
    p.add_argument("--period", type=duration, default="24h", help="sine: okres przebiegu")
    p.add_argument("--noise", type=float, default=0.0, help="odchylenie standardowe szumu (sine) lub kroku (walk)")
    p.add_argument("--value", type=float, help="const: stała wartość (może być spoza przedziału serii)")
    p.add_argument("--decimals", type=int, default=2, help="liczba miejsc po przecinku")
    p.add_argument("--seed", type=int, help="ziarno generatora losowego (powtarzalne dane)")
    p.add_argument("--retries", type=int, default=3, help="ponowienia przy błędzie połączenia")
    p.add_argument("--insecure", action="store_true", help="nie weryfikuj certyfikatu TLS (lokalny self-signed)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except AttributeError:
            pass
    if not args.api:
        print("Podaj adres API: --api URL lub zmienna ZAI_API_URL.", file=sys.stderr)
        return 2
    if not args.key:
        print("Podaj klucz czujnika: --key KLUCZ lub zmienna ZAI_SENSOR_KEY.", file=sys.stderr)
        return 2
    if args.min >= args.max:
        print("--min musi być mniejsze od --max.", file=sys.stderr)
        return 2
    if args.mode == "backfill" and not args.count:
        print("Tryb backfill wymaga --count.", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    gen = ValueGenerator(args.shape, args.min, args.max, args.period, args.noise, args.value, args.decimals, rng)
    client = ApiClient(args.api, insecure=args.insecure)
    ok = failed = 0

    try:
        if args.mode == "backfill":
            end = datetime.now(timezone.utc)
            if args.end:
                end = datetime.fromisoformat(args.end.replace("Z", "+00:00"))
                end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
            print(f"Backfill: {args.count} wyników co {args.step:g} s, ostatni {iso(end)} → {client.base}")
            for i in range(args.count):
                ts = end - timedelta(seconds=args.step * (args.count - 1 - i))
                if send(client, args.key, gen(ts.timestamp()), ts, args.retries):
                    ok += 1
                else:
                    failed += 1
        else:
            print(f"Live: wynik co {args.interval:g} s → {client.base} (Ctrl+C kończy)")
            sent = 0
            while args.count is None or sent < args.count:
                started = time.monotonic()
                if send(client, args.key, gen(time.time()), None, args.retries):
                    ok += 1
                else:
                    failed += 1
                sent += 1
                if args.count is None or sent < args.count:
                    time.sleep(max(0.0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print("\nPrzerwano.")

    print(f"Podsumowanie: zapisano {ok}, odrzucono {failed}.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
