# ZAI 26Z – Serie pomiarowe (pogoda w domu i ogrodzie)

Aplikacja do zbierania i prezentacji wyników pomiarów z czujników IoT.
Czujniki (emulowane generatorem) przesyłają wyniki przez REST API, a administrator zarządza seriami i czujnikami.

- Kontrakt API: [`docs/spec/zai-api-26z.yaml`](docs/spec/zai-api-26z.yaml)
- Specyfikacja projektu: [`docs/spec/zai-projekt-26z.md`](docs/spec/zai-projekt-26z.md)

## Architektura

```
klient / czujnik ──HTTPS──▶ NGINX (TLS, nagłówki bezpieczeństwa, statyczny frontend)
                              └─ /api ──▶ Flask + Gunicorn
                                           ├─ PostgreSQL 16 – admin, tokeny, serie, czujniki
                                           └─ InfluxDB 1.8 – wyniki pomiarów (szereg czasowy)
```

| Warstwa | Technologia | Uzasadnienie |
| --- | --- | --- |
| Backend | Python 3.12, Flask 3, SQLAlchemy 2, Alembic | lekki framework, ORM z zapytaniami parametryzowanymi, migracje |
| Konfiguracja | PostgreSQL 16 | klucze obce z kaskadą, ograniczenia CHECK, indeksy |
| Pomiary | InfluxDB 1.8 | baza szeregów czasowych, zapytania po czasie, kasowanie serii po tagu |
| Proxy | NGINX 1.27 + Let's Encrypt | TLS, HSTS, CSP, limit prób logowania |
| Frontend (E2) | Vue 3 + Bootstrap 5 | SPA serwowana przez NGINX z tej samej domeny (bez CORS) |
| Wdrożenie | Docker Compose na VPS | jeden plik opisuje całe środowisko |

### Przechowywanie wyników w InfluxDB
Measurement `pomiar`, tag `series_id`, pola `value` (float) i `sensor_id`, czas z dokładnością do nanosekund.
Identyfikator wyniku to `"{seriesId}-{czas_ns}"`, czyli nieprzezroczysty napis (kontrakt dopuszcza `id` typu string).
Usunięcie serii wywołuje `DROP SERIES … WHERE series_id=…`. Wyrejestrowanie czujnika nie usuwa jego wyników.

## Uruchomienie lokalne (bez Dockera)

Wymagania: Python 3.10+ i Node 20+ (tylko do testów `zai-tests.mjs`).

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export FLASK_APP=wsgi MEASUREMENT_STORE=memory SECURITY_HEADERS=1 DATABASE_URL=sqlite:///zai-dev.db
.venv/bin/flask db upgrade
.venv/bin/flask create-admin --username admin      # pyta o hasło
.venv/bin/flask run --port 5000
.venv/bin/pytest                                   # testy jednostkowe
```
`MEASUREMENT_STORE=memory` trzyma wyniki w pamięci procesu. Z prawdziwym InfluxDB ustaw `MEASUREMENT_STORE=influx` i `INFLUX_*`.

## Uruchomienie w Dockerze (lokalnie lub na VPS)

```bash
cp .env.example .env                 # uzupełnij hasła (openssl rand -hex 24) i DOMAIN
scripts/init-certs.sh self-signed    # lokalnie; na serwerze: scripts/init-certs.sh letsencrypt
docker compose up -d --build
```
Przy starcie kontener `app` wykonuje migracje (`flask db upgrade`), tworzy bazę w InfluxDB i zakłada konto
administratora z `ADMIN_USERNAME`/`ADMIN_PASSWORD`, jeśli jeszcze nie istnieje.
Wdrożenie bieżącego commita na serwer: `scripts/deploy.sh zai-projekt`.

## Generator danych (emulator czujnika, F13)

Narzędzie korzysta wyłącznie z biblioteki standardowej Pythona i wysyła wyniki tylko przez `POST /api/measurements`.

```bash
export ZAI_SENSOR_KEY=<klucz z rejestracji czujnika>
# dane z przeszłości: 96 wyników co 30 min
python3 generator/sensor_emulator.py --api https://<domena> --mode backfill --count 96 --step 30m \
        --shape sine --min 19 --max 24 --period 24h --noise 0.2
# bieżące wyniki co 10 s
python3 generator/sensor_emulator.py --api https://<domena> --mode live --interval 10s --shape walk --min 50 --max 90
# demonstracja odrzucenia wyniku spoza przedziału (HTTP 422)
python3 generator/sensor_emulator.py --api https://<domena> --shape const --value 999 --count 1
```

| Parametr | Opis |
| --- | --- |
| `--api` / `ZAI_API_URL` | adres aplikacji |
| `--key` / `ZAI_SENSOR_KEY` | klucz API czujnika (nie jest zapisany w kodzie) |
| `--mode backfill\|live` | wyniki z przeszłości albo bieżące |
| `--count` | liczba wyników (wymagana w `backfill`) |
| `--step` | odstęp znaczników w `backfill`, np. `30m` |
| `--end` | znacznik ostatniego wyniku w `backfill` (domyślnie teraz) |
| `--interval` | odstęp wysyłek w `live`, np. `10s` |
| `--shape sine\|random\|walk\|const` | sposób generowania wartości |
| `--min`, `--max` | zakres generowanych wartości |
| `--period`, `--noise`, `--value`, `--decimals`, `--seed` | okres sinusoidy, szum, stała wartość, zaokrąglenie, ziarno |
| `--insecure` | brak weryfikacji TLS (certyfikat samopodpisany) |

Odrzucony wynik jest wypisywany z kodem HTTP i treścią Problem Details, np.
`✘ ODRZUCONO (walidacja) HTTP 422 … Wartość 999 jest poza przedziałem serii „Temperatura – salon” [10, 35]`.
Ta sama informacja trafia do logu błędów aplikacji (`docker compose exec app cat /app/logs/errors.log`).

### Dane przykładowe (F11)
`generator/setup_demo.py` tworzy przez API 4 serie (temperatura w salonie i w ogrodzie, wilgotność, ciśnienie),
rejestruje dla nich czujniki i przy `--backfill N` wysyła emulatorem po N wyników:

```bash
ZAI_ADMIN_PASSWORD=... python3 generator/setup_demo.py --api https://<domena> --backfill 96 --step 30m
```

## Testy

```bash
cd backend && .venv/bin/pytest
node docs/spec/zai-tests.mjs --app https://<domena> --user admin --pass '<hasło>' --stage E1
```

## Bezpieczeństwo (T5)
1. Hasła: Argon2id (`argon2-cffi`), [`backend/app/security.py`](backend/app/security.py).
2. Zapytania: ORM SQLAlchemy oraz `bind_params` w InfluxQL ([`measurements_store.py`](backend/app/measurements_store.py)).
3. Sesja: losowy token Bearer (256 bitów) ważny 1 h. W bazie przechowywany jest tylko jego skrót SHA-256, a wylogowanie natychmiast go unieważnia.
4. Autoryzacja na serwerze: dekoratory `@admin_required` i `@sensor_required` na każdej operacji modyfikującej.
5. Klucze czujników: `secrets.token_urlsafe(32)` (43 znaki). W bazie przechowywany jest tylko skrót SHA-256, a sam klucz jest pokazywany wyłącznie w odpowiedzi na rejestrację.

Dodatkowo NGINX wymusza HTTPS (przekierowanie 301 i HSTS), wysyła CSP, `nosniff` oraz `X-Frame-Options` i ogranicza liczbę prób logowania.
Błędy są zwracane jako Problem Details, bez śladów stosu.
