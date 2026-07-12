# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development rules

- **After every new feature**, update both `README.md` and `CLAUDE.md` to reflect the new capability — add it to the relevant section in the Features list of each file.

- **After adding support for a new airline**, update the supported airlines table in `README.md`, the airline rules count and list in both `README.md` and `CLAUDE.md`, and increment `RULES_VERSION` in `backend/parsers/builtin_rules.py`.

- **After every implementation**, always run all three checks before considering the work done:
  1. `uv run ruff check backend/` — fix any lint errors (use `--fix` for auto-fixable ones)
  2. `uv run ty check backend/` — fix all type errors
  3. `cd frontend && npm run lint` — fix any ESLint errors

- **Always write tests** for every new feature or bug fix without being asked:
  - **Backend**: for a layered feature package (`backend/<feature>/` with routes/service/repository — e.g. `notifications`, `packing`, `expenses`, `boarding_passes`, `shares`), place its tests in `backend/tests/<feature>/`, mirroring the package (`test_repository.py`-style files per layer plus the black-box `test_api_*.py`). For everything else, place tests directly in `backend/tests/` following existing patterns. Both use: class per module, `asyncio.run()` for async, `test_db` fixture, mock with `unittest.mock`. Keep coverage above 70%.
  - **Frontend**: add unit tests as `*.test.ts` files alongside the source (e.g. `utils.test.ts`, `ComponentName.test.ts`) using Vitest + `@testing-library/svelte`. Run with `npm test` inside `frontend/`. Both are already configured.
  - **E2E**: for every new feature, add a Playwright test in `frontend/tests/` as a `*.spec.ts` file. E2E tests require the server running at `http://localhost:8000`. For bug fixes, E2E is optional but preferred if the fix touches a user-facing flow.

## Commands

### Backend

> **IMPORTANT:** This project uses [uv](https://docs.astral.sh/uv/) for dependency management. Use `uv run` for all Python commands — no venv activation needed.

```bash
# Setup
uv sync

# Run
uv run uvicorn backend.main:app --reload

# Lint
uv run ruff check backend/

# Type check
uv run ty check backend/

# Dead code detection (manual, review output — expect false positives from FastAPI handlers)
uv run vulture backend/ --exclude backend/tests/

# Tests
uv run pytest backend/tests/ -v
uv run pytest backend/tests/test_api_auth.py::TestAuth::test_login -v  # single test
uv run pytest --cov=backend --cov-fail-under=70                        # with coverage (70% minimum enforced)
```

### Frontend
```bash
cd frontend
npm install
npm run dev       # dev server at localhost:5173
npm run build     # production build (svelte-check + vite)
npm run lint      # ESLint
npm run check     # svelte-check (type errors fail build)
```

### E2E Tests
```bash
cd frontend
npx playwright install chromium
npm run test:e2e
```

### Docker
```bash
docker compose up -d --build
```

## Architecture

**Partiu** is a self-hosted flight tracker PWA. Flight data flows from email → IMAP fetch → HTML/PDF parse → SQLite → REST API → Svelte frontend.

### Backend (`backend/`)
- **`main.py`** — FastAPI app entry point; mounts frontend static files, initializes DB, starts scheduler and SMTP server
- **`database.py`** — Raw sqlite3 (no ORM), WAL mode, connection helpers (`db_conn`/`db_write`), Alembic migration bootstrapping, and `init_database()`'s startup sequencing (credential-encryption migrations + aircraft-type normalization/seeding). Domain-table seed data and queries live in their owning package's repository (`airports/repository.py`, `integrations/aircraft/repository.py`), not here.
- **`scheduler.py`** — APScheduler runs email sync every 10 min and aircraft sync daily
- **`sync/pipeline.py`** — Main pipeline: fetch emails → parse → extract flights → group into trips (via `sync/grouping.py`); `use_llm` flag enables LLM fallback for incremental sync (disabled for full rescan). `sync/service.py` (the `/api/sync/*` routes' use-case layer) calls into it rather than owning the pipeline itself.
- **`parsers/engine.py`** — Extraction engine: tries BS4 HTML parsing first, then regex fallback, then PDF
- **`parsers/builtin_rules.py`** — Airline rules keyed to `PARSER_VERSION = '27'`; supported: LATAM (LA), SAS (SK), Norwegian (DY), Azul (AD), Lufthansa (LH), British Airways (BA), ITA Airways (AZ), Kiwi.com, Ryanair (FR), Austrian Airlines (OS), TAP Air Portugal (TP), Finnair (AY), Wizz Air (W6), Brussels Airlines (SN), Iberia (IB)
- **`sync/grouping.py`** — Auto-groups flights into trips by booking reference, then 48h time proximity
- **`auth/`** — Session cookies (itsdangerous), bcrypt passwords, TOTP 2FA, audit logging (`audit_log.py`); also re-exports cross-cutting authorization helpers (`get_current_user`, `can_access_trip`, etc.) imported as `from ..auth import ...` throughout the backend
- **`smtp_server.py`** — aiosmtpd inbound SMTP on port 2525 for email forwarding
- **`utils/`** — Generic, dependency-light helpers with no DB access, used across every feature: `dates.py` (flight-number validation, ISO datetime conversion, duration/status calc — re-exported from `utils/__init__.py` for import-path stability), `i18n.py` (minimal backend translations reusing the frontend's locale JSON files)
- **`airports/`** — `repository.py` (AirportRepository: search + IATA lookup + CSV bulk-load-if-empty seeding) + `routes.py` (`GET /api/airports/search`, `GET /api/airports/{iata}`) + `timezone.py` (converts naive local flight times to UTC using airport coordinates + TimezoneFinder — lives here rather than in `utils/` because it touches the DB, and not in `flights/` because `parsers/` needs it too and parsers/flights are kept independent). Lighter than the full routes→service→repository layering since there's no business logic in the routes. Other packages still query the `airports` table directly for their own narrow needs (parsers/, sync/grouping.py, trips/, settings/) rather than going through this repository.
- **`routes/`** — Leftover pre-refactor routes not yet folded into a feature package: `version.py` (app version endpoint)
- **`integrations/`** — Third-party API clients, one subpackage per provider: `immich/client.py` (album create/check), `aircraft/client.py` (AviationStack → OpenSky → hexdb.io lookups) + `aircraft/sync.py` (background aircraft-type sync job) + `aircraft/status_sync.py` (background live flight-status sync job, also AviationStack) + `aircraft/repository.py` (AircraftTypeRepository: the local `aircraft_types` cache table, seed data, and the one-time flight-row name-normalization sweep), `llm/parser.py` (optional Ollama LLM fallback; `llm_extract_flights(email_msg)` returns validated flights or `[]` when disabled; validates IATA codes against airports DB before returning), `wikipedia/client.py` (destination photo fetch + local WebP cache). Feature packages (trips, flights, sync, settings) call into these as clients rather than owning the third-party integration logic themselves.

### Frontend (`frontend/src/`)
- **Svelte 5** SPA with Vite; TypeScript throughout
- **`App.svelte`** — SPA router, auth checks, main layout
- **`api/client.ts`** — All HTTP calls to the backend
- **`lib/authStore.ts`** — Auth state (session user)
- Pages: TripsListPage, TripDetailPage, FlightDetailPage, HistoryPage, StatsPage, SettingsPage, NotificationsPage, InvitationsPage, LoginPage, SetupPage, UsersPage (admin)

### Data & Config
- SQLite at `data/partiu.db` (gitignored); seed airports with `python load_airports.py`
- Environment via `.env` (see `.env.example`); key vars: `SECRET_KEY`, `DB_PATH`, `DISABLE_SCHEDULER`, `AVIATIONSTACK_API_KEY`, `OLLAMA_URL`, `OLLAMA_MODEL`
- PWA icons generated by `generate_icons.py`

### CI (`.github/workflows/pr.yml`)
Runs: backend tests (70% coverage gate) + frontend lint/type-check + E2E tests (Playwright).

## Features

### Trip & flight management
- Auto-groups flights into trips by booking reference, then 48h time proximity
- Create/edit trips and flights manually; delete (owner only)
- Export trips as iCalendar (.ics) files
- Notes per flight (up to 10,000 chars); calendar-style day notes per trip
- Trip rating (0.5–5 stars in 0.5 increments)
- **Trip expenses**: add itemised expenses per trip (description, amount, currency); totals grouped by currency shown in trip detail and trip cards; 41 supported currencies; per-user default currency (set in Settings)
- **Expense splitting**: each expense records who paid (`paid_by`: a collaborator or a guest, defaults to the creator) and who it's split equally between (`participants`, defaults to everyone currently on the trip); expense rows show who added them; `GET /api/trips/{trip_id}/expenses/balances` returns each participant's net balance per currency (what they paid minus their share)
- **Guests**: non-account trip companions for splitting expenses with people who don't have a Partiu account (`POST /api/guests` creates one, owned by the caller; `GET /api/guests` lists the caller's own; `PATCH /api/guests/{id}` renames one; `DELETE /api/guests/{id}` — blocked while referenced by an existing expense); a guest can't be deleted while referenced by an existing expense; guests are scoped per trip — `GET /api/trips/{trip_id}/expenses/participants` (the payer/split-between picker) only surfaces trip collaborators plus guests already tagged on *that* trip, not every guest the caller has ever created, so a guest added on one trip doesn't leak into an unrelated trip's picker; paid_by/participants validation on create/update additionally accepts a guest the caller owns but hasn't tagged on this trip yet, so a freshly quick-added guest can be used immediately as that first expense's payer/participant; a Settings section (add/rename/delete) manages the caller's own guest address book directly, independent of any single trip

### Trip sharing & collaboration
- Invite users to a trip by username; pending/accepted/rejected invitation states
- Trusted users list: invitations from trusted users are auto-accepted
- Shared collaborators get full read/write access on trip content
- Owner can revoke access; collaborators can leave a trip
- Both owner and collaborators can rate trips and edit shared trip notes
- Invitations page (`/invitations`) — accept or reject pending invitations

### Boarding passes & documents
- Extracts boarding passes from confirmation emails (BCBP barcode format)
- Manual boarding pass image upload (PNG, JPEG, WebP)
- Trip documents: upload PDFs/images up to 20 MB; multi-page PDF viewer
- BCBP parsing: passenger name and seat extracted automatically

### Email sync & parsing
- IMAP sync (Gmail App Password or custom IMAP host/port) per user
- Built-in airline rules — 15 supported: LATAM (LA), SAS (SK), Norwegian (DY), Azul (AD), Lufthansa (LH), British Airways (BA), ITA Airways (AZ), Kiwi.com, Ryanair (FR), Austrian Airlines (OS), TAP Air Portugal (TP), Finnair (AY), Wizz Air (W6), Brussels Airlines (SN), Iberia (IB); `PARSER_VERSION = '27'`
- PDF extraction fallback
- **Ollama LLM fallback** (optional): set `OLLAMA_URL` + `OLLAMA_MODEL` in `.env`; used as last resort for incremental sync; `run.sh` auto-starts Ollama if binary present; optional `ollama` service in `docker-compose.yml`
- CLI eval tool: `uv run python -m backend.tools.eval_eml_files` — tests LLM against `.eml` files (pass file or glob)
- Blocked sender domains: admin-managed list of domains silently skipped during sync (e.g. Airbnb, Booking.com)
- Manual sync trigger and configurable sync interval + email limit (admin)
- **Upload .eml files directly** from the trips list (`POST /api/sync/upload-eml`): parses uploaded `.eml` files through the same engine (rules → generic HTML/PDF → LLM) and imports flights
- Inbound SMTP server (aiosmtpd, default port 2525) for email forwarding

### Flight enrichment
- Aircraft type lookup: AviationStack → OpenSky Network fallback; result cached
- Timezone-aware departure/arrival times (airport coords + TimezoneFinder)
- Live flight status tracking (delays, cancellations, estimated times)

### Travel statistics (Stats page)
- Total km, flights, hours in air, unique airports, unique countries, Earth laps
- Longest flight, top 5 routes/airports/airlines
- Year filter with available-years selector

### Destination images
- Auto-fetch trip destination photo from Wikipedia; manual refresh

### Immich integration (optional)
- Create Immich album for a trip populated with photos in the trip's date range
- "Open Immich Album" deep link once album exists; per-user URL + API key (encrypted)

### Notifications
- Web push notifications via VAPID (flight reminders, delays, check-in, new flights, boarding passes, failed parses)
- In-app notification inbox with unread count badge; per-user preferences
- Admin: generate/manage VAPID keys; test push endpoint

### Authentication & security
- Username/password + session cookies (30-day, server-side revocable)
- TOTP 2FA (enable/disable from Settings; QR code for any authenticator app)
- Login rate-limit (5/min per IP); TOTP lockout after 5 failures in 15 min
- Audit logging of auth events; password change requires 2FA code

### Multi-user & admin
- Per-user IMAP credentials, SMTP recipient, Immich config, notification prefs, locale (en / pt-BR)
- Admin: create/list/update/reset-password/delete users
- Admin: sync interval, max emails per sync, first-sync lookback days, SMTP server toggle/port/domain, VAPID, airport data reload

### Frontend pages
TripsListPage, TripDetailPage, FlightDetailPage, HistoryPage, StatsPage, SettingsPage, NotificationsPage, InvitationsPage, UsersPage (admin), LoginPage, SetupPage
