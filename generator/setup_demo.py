#!/usr/bin/env python3
"""Przygotowanie danych przykładowych (F11) – wyłącznie przez API.

1. Loguje się jako administrator i tworzy (lub odnajduje po nazwie) serie demonstracyjne.
2. Rejestruje dla każdej serii nowy czujnik i wypisuje jego klucz API (jednorazowo).
3. Z opcją --backfill wysyła emulatorem (sensor_emulator.py) wyniki z przeszłości
   kluczem każdego czujnika – przez POST /api/measurements, nie bezpośrednio do bazy.

Przykład:
  python setup_demo.py --api https://zai.example.com --user admin --backfill 96 --step 30m
  (hasło: --password albo zmienna ZAI_ADMIN_PASSWORD, albo pytanie interaktywne)
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sensor_emulator  # noqa: E402
from zai_client import ApiClient  # noqa: E402

# Pogoda w domu i ogrodzie: (seria, przebieg generatora)
DEMO = [
    ({"name": "Temperatura – salon", "minValue": 10, "maxValue": 35, "color": "#d62728", "icon": "circle", "unit": "°C"},
     ["--shape", "sine", "--min", "19.5", "--max", "23.5", "--period", "24h", "--noise", "0.2", "--decimals", "1"]),
    ({"name": "Temperatura – ogród", "minValue": -30, "maxValue": 45, "color": "#1f77b4", "icon": "triangle", "unit": "°C"},
     ["--shape", "sine", "--min", "2", "--max", "14", "--period", "24h", "--noise", "0.6", "--decimals", "1"]),
    ({"name": "Wilgotność – ogród", "minValue": 0, "maxValue": 100, "color": "#2ca02c", "icon": "square", "unit": "%"},
     ["--shape", "walk", "--min", "55", "--max", "95", "--noise", "2", "--decimals", "0"]),
    ({"name": "Ciśnienie atmosferyczne", "minValue": 950, "maxValue": 1060, "color": "#9467bd", "icon": "diamond", "unit": "hPa"},
     ["--shape", "walk", "--min", "1002", "--max", "1024", "--noise", "0.6", "--decimals", "1"]),
]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Tworzy serie i czujniki demonstracyjne przez API ZAI.")
    p.add_argument("--api", required=True, help="adres aplikacji, np. https://zai.example.com")
    p.add_argument("--user", default="admin")
    p.add_argument("--password", default=os.environ.get("ZAI_ADMIN_PASSWORD"))
    p.add_argument("--backfill", type=int, metavar="N", help="wyślij N wyników z przeszłości dla każdej serii")
    p.add_argument("--step", default="30m", help="odstęp znaczników czasu przy backfill")
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--insecure", action="store_true")
    args = p.parse_args(argv)

    password = args.password or getpass.getpass(f"Hasło administratora {args.user}: ")
    client = ApiClient(args.api, insecure=args.insecure)
    login = client.request("POST", "/api/auth/login", {"username": args.user, "password": password})
    if login.status != 200:
        print(f"Logowanie nieudane (HTTP {login.status}): {login.problem_text()}", file=sys.stderr)
        return 1
    auth = {"Authorization": f"Bearer {login.body['accessToken']}"}

    existing = {s["name"]: s for s in (client.request("GET", "/api/series").body or [])}
    rc = 0
    for i, (series_def, shape_args) in enumerate(DEMO):
        series = existing.get(series_def["name"])
        if series is None:
            res = client.request("POST", "/api/series", series_def, auth)
            if res.status != 201:
                print(f"✘ Nie utworzono serii {series_def['name']}: {res.problem_text()}", file=sys.stderr)
                rc = 1
                continue
            series = res.body
            print(f"✔ Utworzono serię #{series['id']} {series['name']}")
        else:
            print(f"• Seria #{series['id']} {series['name']} już istnieje")

        res = client.request("POST", "/api/sensors", {"name": f"Emulator – {series['name']}", "seriesId": series["id"]}, auth)
        if res.status != 201:
            print(f"✘ Nie zarejestrowano czujnika: {res.problem_text()}", file=sys.stderr)
            rc = 1
            continue
        key = res.body["apiKey"]
        print(f"  czujnik #{res.body['id']}  klucz API (zapisz – nie zostanie pokazany ponownie):\n  {key}")
        cmd = ["--api", args.api, "--key", key, *shape_args, "--seed", str(args.seed + i)]
        if args.insecure:
            cmd.append("--insecure")
        if args.backfill:
            print(f"  → backfill {args.backfill} wyników")
            rc |= sensor_emulator.main([*cmd, "--mode", "backfill", "--count", str(args.backfill), "--step", args.step])
        else:
            print("  polecenie: ZAI_SENSOR_KEY=<klucz> python sensor_emulator.py --api", args.api,
                  " ".join(shape_args), "--mode live")

    client.request("POST", "/api/auth/logout", None, auth)
    return rc


if __name__ == "__main__":
    sys.exit(main())
