# Plan – etap E1 projektu ZAI 26Z (Flask + PostgreSQL + InfluxDB 1.8, Docker, NGINX)

## Kontekst
Projekt: aplikacja do zbierania i prezentacji pomiarów z czujników IoT. Termin E1 to **7 lis 2026**, czyli za 3 dni. W E1 musi działać publicznie wdrożony backend zgodny z `zai-api-26z.yaml`, a dane przykładowe (F11) mają być wprowadzone generatorem przez API. W tym etapie zgłasza się adres API, konto admina i link do repozytorium. Ocenę A1 (10 pkt) wystawiają testy `zai-tests.mjs --stage E1` (grupa `kontrakt`). Testy grup `walidacja` i `bezpieczenstwo` (E2) spełniamy od razu, bo koszt jest niewielki.

Decyzje użytkownika:
- backend **Flask**;
- konfiguracja (admin, tokeny, serie, czujniki) w **PostgreSQL 16**;
- **pomiary w InfluxDB 1.8**, co daje bonus do +3 pkt za bazę szeregów czasowych;
- wszystko w **docker compose** na jednym VPS za **NGINX-em** (HTTPS z Let's Encrypt). VPS jeszcze nie ma, więc najpierw całość ma działać lokalnie w compose;
- frontend w E2: **Vue 3 + Bootstrap 5**, statyczny build serwowany przez NGINX z tej samej domeny, więc bez CORS;
- dziedzina: **pogoda w domu i ogrodzie**.

## Struktura repozytorium (nowe repo git w `ZAI/`)
```
docker-compose.yml        nginx, app, postgres, influxdb, certbot
.env.example              DOMAIN, POSTGRES_*, INFLUX_*, SECRET_KEY, ADMIN_USER/PASS (bez prawdziwych wartości)
nginx/templates/default.conf.template   80→301 https, 443: /api → app:8000, / → static; nagłówki bezpieczeństwa
nginx/static/index.html   E1: prosta strona Bootstrap 5 (lokalny bootstrap.min.css); w E2 zastąpi ją build Vue
scripts/init-letsencrypt.sh   tymczasowy certyfikat → start nginx → certbot webroot → reload
backend/
  Dockerfile              python:3.12-slim + gunicorn
  app/__init__.py         create_app(), blueprinty, ProxyFix, logowanie (stdout + plik błędów)
  app/config.py           konfiguracja z env
  app/extensions.py       db (Flask-SQLAlchemy), migrate (Flask-Migrate)
  app/models.py           Admin, AuthToken, Series, Sensor (SQL)
  app/measurements_store.py  interfejs MeasurementStore + InfluxStore (1.8) + MemoryStore (testy)
  app/errors.py           Problem Details (RFC 9457) dla wszystkich błędów, także 404/405/500
  app/security.py         Argon2id, tokeny, klucze API, @admin_required, @sensor_required
  app/validation.py       walidacja JSON (typy, NaN/Inf, bool≠liczba), ISO 8601
  app/api/{health,auth,series,sensors,measurements}.py
  app/cli.py              `flask create-admin`, `flask init-influx`
  migrations/             Alembic (Flask-Migrate)
  tests/                  pytest: SQLite + MemoryStore; integracja z Influx w compose
  requirements.txt        Flask 3, Flask-SQLAlchemy, Flask-Migrate, psycopg[binary], influxdb (1.x), argon2-cffi, gunicorn
generator/
  sensor_emulator.py      emulator czujnika (F13)
  setup_demo.py           tworzy przez API admina serie i czujniki demo, wypisuje klucze
docs/spec/                pliki z zadania (zai-*.md/.yaml/.mjs, README-autotest.md)
docs/schema.sql           DDL PostgreSQL (eksport z migracji, do B4)
frontend/                 (E2)
README.md
```

## Dane
**PostgreSQL:**
- `admin`: id, username UNIQUE, password_hash (Argon2id), created_at
- `auth_token`: id, admin_id FK CASCADE, token_hash CHAR(64) UNIQUE (SHA-256), expires_at, revoked_at NULL
- `series`: id, name VARCHAR(100), min_value DOUBLE PRECISION, max_value DOUBLE PRECISION, color CHAR(7) z CHECK na format, icon NULL, unit VARCHAR(20) NULL, CHECK(min_value < max_value)
- `sensor`: id, name VARCHAR(100), series_id FK→series ON DELETE CASCADE, api_key_hash CHAR(64) UNIQUE, created_at, last_measurement_at NULL

**InfluxDB 1.8:** baza `zai`, measurement `pomiar`.
- Tag: `series_id`. Pola: `value` (zawsze float, żeby uniknąć konfliktu typów pola) i `sensor_id` (pole, nie tag, żeby nie zwiększać kardynalności). Czas z precyzją ns.
- **Id wyniku** to nieprzezroczysty napis `"{seriesId}-{epoch_ns}"`; kontrakt dopuszcza `id` typu string. Odczyt po id: `SELECT … WHERE series_id=$s AND time=$t`.
- Kolizja (ten sam czas w tej samej serii nadpisałby punkt w Influksie): przed zapisem sprawdzamy, czy punkt istnieje; jeśli tak, przesuwamy czas o 1 ns. Przesunięcie jest niewidoczne, bo czas zwracamy z dokładnością do µs.
- Wszystkie zapytania InfluxQL używają `bind_params` (zapytania parametryzowane, T5.2).
- Usunięcie serii: `DELETE FROM pomiar WHERE series_id=$s` w Influksie, potem rekord w Postgresie (kaskadowo czujniki). Wyrejestrowanie czujnika usuwa tylko wiersz w Postgresie; punkty w Influksie zostają (F12).
- Influx nie jest wystawiony na zewnątrz, działa tylko w sieci compose.

## Zachowanie API (zgodne z kontraktem i testami)
- **Globalnie `/api/*`:**
  - `Accept` bez `application/json`, `application/problem+json`, `application/*` ani `*/*` → 406;
  - POST/PUT z treścią o typie innym niż JSON → 415;
  - uszkodzony JSON → 400;
  - każdy błąd zwraca `application/problem+json` z polami `title` i `status`, a przy walidacji także `errors[]`; nigdy nie zawiera śladu stosu.
- **Kolejność sprawdzania:** uwierzytelnienie (401) → typ treści (415) → składnia (400) → reguły (422/409).
- **Auth:**
  - `login` zwraca 200 `{accessToken, tokenType:"Bearer", expiresIn:3600}`; brak pól → 400, złe dane → 401;
  - `logout` → 204 i ustawia `revoked_at`;
  - `password`: złe bieżące hasło → 403, nowe krótsze niż 8 znaków → 422, sukces → 204.
  - Token losowy (`secrets.token_urlsafe(32)`), w bazie tylko SHA-256. Bez ciasteczek.
- **Series:**
  - GET publiczny;
  - POST → 201 z `Location: /api/series/{id}`;
  - PUT to pełna zamiana pól; 409, jeśli `MIN/MAX(value)` serii w Influksie wypada poza nowy przedział;
  - DELETE → 204;
  - `min ≥ max` → 422; walidowane `color` i `name` (1–100 znaków).
- **Sensors:**
  - wszystkie operacje wymagają admina;
  - POST → 201 + `Location` + jednorazowo `apiKey` (43 znaki); nieistniejąca seria → 422;
  - GET nigdy nie zwraca klucza ani jego skrótu.
- **Measurements:**
  - POST tylko z `X-API-Key`; sam Bearer → 401.
  - `value` musi być liczbą skończoną; `timestamp` opcjonalny: brak oznacza bieżący czas serwera, bez strefy przyjmujemy UTC, więcej niż 5 min w przyszłość → 422.
  - Wartość spoza [min, max] (granice włącznie) → 422, z wpisem `WARNING` w logu błędów (F4).
  - Po zapisie aktualizujemy `sensor.last_measurement_at`.
  - GET filtruje po `series` (lista po przecinku; niepoprawna → 400), `from`/`to` (domknięte; niepoprawne → 400), `sort` (`timestamp` | `-timestamp`), `limit` (1–10000, domyślnie 1000).
  - Zapytanie to jedno `SELECT value, sensor_id, series_id … ORDER BY time … LIMIT`. Bez `GROUP BY` Influx scala serie w jedną listę posortowaną po czasie.
  - `/api/measurements/{id}` obsługuje tylko GET; PUT/PATCH/DELETE → 405.
- **`/api/health`** → `{"status":"ok"}`.
- **NGINX:**
  - HTTP → 301 na HTTPS;
  - TLS z Let's Encrypt;
  - nagłówki dodawane `always`: `Content-Security-Policy` (`default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'`), `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `X-Frame-Options: DENY`, HSTS.
  - Flask dodaje te same nagłówki tylko w trybie dev bez NGINX-a (`SECURITY_HEADERS=1`), żeby nie było duplikatów.
  - CORS wyłączony.

## Generator (F13, T11): `generator/sensor_emulator.py` (argparse + requests)
- `--api URL`, `--key` lub zmienna `ZAI_SENSOR_KEY` (klucz nigdy nie jest wpisany w kod).
- Tryby:
  - `--mode backfill`: `--count N` wyników z przeszłości co `--step 30m`, kończąc na „teraz”;
  - `--mode live`: wysyła bieżący wynik co `--interval 10s` (do Ctrl+C albo do `--count`).
- Przebieg wartości: `--shape sine|random|walk|const`, `--min`, `--max`, `--period`, `--noise`, `--seed`.
- Każdy wynik wypisuje: ✔ zapisany (id, wartość, czas) albo ✘ ODRZUCONY z kodem HTTP i polami `title`/`detail` z Problem Details.
- `setup_demo.py` tworzy przez API admina serie i czujniki i wypisuje gotowe polecenia emulatora.

Serie przykładowe (F11), po około 96 punktów z 48 h co 30 min, przebieg sinusoidalny ze szumem:
1. Temperatura – salon (°C, 10…35)
2. Temperatura – ogród (°C, −30…45)
3. Wilgotność – ogród (%, 0…100)
4. Ciśnienie atmosferyczne (hPa, 950…1060)

## Wdrożenie
- **Lokalnie:** `docker compose up -d --build`, potem `docker compose exec app flask db upgrade && flask init-influx && flask create-admin`. NGINX działa lokalnie na certyfikacie self-signed generowanym przez skrypt.
- **VPS (do wybrania przez użytkownika, np. Mikrus, OVH, Hetzner, Azure for Students; min. 1 GB RAM):**
  1. Zainstalować Dockera i sklonować repo.
  2. Uzupełnić `.env` (`DOMAIN`, hasła).
  3. Uruchomić `scripts/init-letsencrypt.sh`, potem `docker compose up -d` i migracje oraz konto admina.
  4. Jeśli nie ma własnej domeny, użyć darmowej subdomeny DuckDNS albo `<ip>.sslip.io`.
- **Dane przykładowe:** z lokalnej maszyny uruchomić `setup_demo.py` i `sensor_emulator.py --mode backfill`, kierując je na publiczny adres.

## Repozytorium (T9)
`git init` z `.gitignore` (`.env`, `venv`, `__pycache__`, `node_modules`, `.DS_Store`, `certbot/`). Commity w małych krokach: szkielet + compose → modele i migracje → auth → series → sensors → measurements (Influx) → generator → nginx/TLS. Remote na GitHubie przez `gh`, jeśli jest skonfigurowany; w przeciwnym razie użytkownik doda go sam.

## Weryfikacja
1. `pytest backend/tests` (SQLite + MemoryStore): kody, `Location`, 406/415/400/422/409/405, kaskady, unieważnienie tokenu, brak sekretów w odpowiedziach.
2. Integracja: `docker compose up`, potem `setup_demo.py` + `sensor_emulator.py`, potem `node docs/spec/zai-tests.mjs --app https://localhost --user admin --pass … --stage E2` (z `NODE_TLS_REJECT_UNAUTHORIZED=0` przy certyfikacie self-signed). Cel: wszystkie testy `kontrakt`, `walidacja` i `bezpieczenstwo` zielone.
3. Po wdrożeniu na VPS: `node zai-tests.mjs --app https://<domena> … --stage E1`, cel 100% w A1. Kontrolnie także `--stage E2`.
4. Ręcznie: odrzucenie wartości spoza zakresu widoczne w emulatorze i w logu (`docker compose logs app`).