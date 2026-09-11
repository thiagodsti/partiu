# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development rules

- **After every new feature**, update both `README.md` and `CLAUDE.md` to reflect the new capability — add it to the relevant section in the Features list of each file.

- **After adding support for a new airline**, update the supported airlines table in `README.md`, the airline rules count and list in both `README.md` and `CLAUDE.md`, and increment `PARSER_VERSION` in `backend/parsers/builtin_rules.py` (a version mismatch makes the next sync a full rescan).

- **Email fixtures carry real mail, so scrub them everywhere before committing** — not only the HTML body, which is the only place the early passes touched. Personal data also hides in: PDF attachments (passenger names and two dates of birth survived there until they were redacted with PyMuPDF), RFC2047-encoded headers (a surname sat inside the SAS e-ticket's `Subject`, invisible to any raw-text search), attachment filenames (e-ticket numbers), booking references, frequent-flyer numbers, and ESP tokens in URLs — the Lufthansa `?enc=`, Austrian e-paper and BA `?code=` links are manage-my-booking deep links, not just trackers. `backend/tests/test_fixture_privacy.py` is the tripwire for the common shapes; it is not a proof, so read a new fixture before adding it. After rewriting a fixture, prove the change is inert by diffing extraction before/after rather than trusting the suite: several assertions loop over the extracted flights and pass vacuously on an empty result.

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
- **`parsers/engine.py`** — Rule matching + `merge_flights`, plus the multilingual `parse_flight_date`. `match_rule_to_email` also reads *forwarded* headers out of the body, and the labels are localised to the **forwarder's** UI language, not the sender's (Gmail in pt-BR writes `De:`, not `From:`) — matching English only meant forwarded itineraries reached no rule. Deliberately holds no extraction logic of its own any more: the generic PDF pattern that used to be merged into every rule's result was removed with the line scanners
- **`parsers/shared.py`** — Helper library every airline extractor builds on (`scan_flights`, `resolve_iata`, `make_flight_dict`, date/time helpers). Two things here are load-bearing for correctness across all airlines: (1) `make_flight_dict` is the single choke point where a leg can be refused, and it enforces `validate_flight_number` — SAS prints `SK1829 | Airbus A320neo` and `A3` (Aegean) is in its codeshare prefix list, so aircraft types were being stored as flights; (2) `scan_flights`' two-line lookbehind prefers IATA codes found at or after the flight-number line, because on a multi-leg itinerary the lookbehind otherwise reaches into the *previous* leg's arrival airport and collapses the leg to `BCN → BCN`
- **`parsers/gds_eticket.py`** — Airline-independent parser for GDS ticket receipts (ITR / ITR-EMD). Handles two renderings of the same document: the **table layout** (HTML `<tr>` per leg — a cell's meaning comes from its column) and the **compact layout** (`AF 871 / 12NOV Cape Town - Paris CDG 07:55 19:15`, found in the PDF attachment when the HTML part is only a cover note). It reads the PDF itself rather than relying on the caller having folded PDF text into `body`. Compact-layout dates carry no year, so `_resolve_receipt_date` resolves them *forward* from the issue date — a receipt is always issued before travel, which is why that inference is safe here and not in `validation.py`. **Extraction order in `sync/pipeline.py` is by trustworthiness: (1) the airline's own rule, (2) this GDS parser — *merged* into the rule's result via `engine.merge_flights`, not used only as a fallback, (3) LLM.** Merging (rather than falling back) matters because an airline rule can silently drop legs on a multi-carrier itinerary — an ARN→AMS→LHR→JNB ticket came through the SAS rule as the final leg alone. There is no generic-line-scanner tier between (2) and (3) any more, and `test_gds_eticket_parser.py::TestExtractionOrder` fails if one is reintroduced — see the pipeline comment where it used to sit
- **`parsers/validation.py`** — Plausibility gate every extraction path passes through in `sync/pipeline.py`, applied **after** `apply_airport_timezones` so durations are real UTC. Prefers dropping a leg over storing a wrong one; every drop is logged with its reason. Note what it *cannot* do: a wrong-but-ordinary leg (right airports, plausible duration, wrong direction or wrong year) sails through, which is why extraction is kept structural rather than leaning on this gate to clean up guesses
- **No generic extraction tier — on purpose.** There used to be one (`parsers/generic_html.py` plus a generic PDF regex): anchor on any flight-number-shaped token, then scan nearby lines for airports/times/dates. Measured across a 372-email corpus, *every* leg it was the sole source of was wrong or incomplete — a Ryanair round trip with both legs pointing the same way, a TAP receipt reading the `NVA` not-valid-after label as Neiva, e-tickets dated a year off, LATAM round trips missing the return, Lufthansa itineraries reduced from six legs to one. Each airline template it had been covering is now read by that airline's own rule (see `test_airline_rule_coverage.py`), which yields *more* legs than the scanners did, correctly. If a new email format shows up unparsed, add a rule for it or let the LLM take it — do not reintroduce a proximity-guessing tier
- **`parsers/builtin_rules.py`** — Airline rules keyed to `PARSER_VERSION = '31'`; supported: LATAM (LA), SAS (SK), Norwegian (DY), Azul (AD), Lufthansa (LH), British Airways (BA), ITA Airways (AZ), Kiwi.com, Ryanair (FR), Austrian Airlines (OS), TAP Air Portugal (TP), Finnair (AY), Wizz Air (W6), Brussels Airlines (SN), Iberia (IB), Vueling (VY), Qatar Airways (QR), Turkish Airlines (TK), Pegasus Airlines (PC). `SUBJECT_PATTERN` gates every rule after the sender matches, so a missing keyword there silently disables an airline — "Resehandlingar" was the reason Norwegian's travel-document mails reached no rule at all; `ticket` had to be added there for Turkish Airlines, whose subject is just "Turkish Airlines - Ticket Details", and `rezerv` for Pegasus, because `reserv` does not match the Turkish "Rezervasyon"
- **`sync/grouping.py`** — Auto-groups flights into trips by booking reference, then 48h time proximity
- **Outbound/Return detection** (`utils.splitLegs`) keys off the flights themselves — last arrival airport equals first departure airport — *not* `trip.origin_airport` / `trip.destination_airport`. Those two disagree about their meaning: `_recompute_span` sets destination to the **final** arrival, which on a round trip is the origin, so the old `origin === destination → don't split` guard meant a real FRA→PEK→FRA trip never split — the one case the split exists for. Note the same mismatch still affects the Wikipedia destination photo, which looks up `destination_airport`
- **`auth/`** — Session cookies (itsdangerous), bcrypt passwords, TOTP 2FA, audit logging (`audit_log.py`); also re-exports cross-cutting authorization helpers (`get_current_user`, `can_access_trip`, etc.) imported as `from ..auth import ...` throughout the backend
- **`smtp_server.py`** — aiosmtpd inbound SMTP on port 2525 for email forwarding
- **`utils/`** — Generic, dependency-light helpers with no DB access, used across every feature: `dates.py` (flight-number validation, ISO datetime conversion, duration/status calc — re-exported from `utils/__init__.py` for import-path stability), `text.py` (`fold_text` — accent folding, shared by airport name resolution and the CSV loader that writes the folded columns), `i18n.py` (minimal backend translations reusing the frontend's locale JSON files — resolved from `$LOCALES_DIR`, then `frontend/src/locales/` for a repo checkout, then `backend/locales/`, which the Dockerfile populates from the same files because the image ships only the *built* frontend. An unresolved key falls back to the key itself, which reaches users as a raw `notif.*` string in a push notification, so a missing locale file is logged at error level rather than silently)
- **`airports/`** — `repository.py` (AirportRepository: search + IATA lookup + CSV bulk-load-if-empty seeding, plus `backfill_rank_columns()` / `seed_aliases_from_keywords()` — run at startup from `main.py` — which populate the `type` / `scheduled_service` ranking columns, the accent-folded search columns, and exonym aliases derived from the CSV's `keywords`; curated aliases from migration `0022` deliberately outrank those. The backfill downloads `airports.csv` when absent (`_ensure_csv()`), because `data/` is a mounted volume and an upgraded instance typically has a populated table but no CSV. Completion is recorded in `global_settings` under `airport_rank_backfill_done` rather than inferred from the data — a few stored airports are retired upstream and keep a NULL `type` forever — and the flag is only set when the CSV pass actually ran, so an instance that was offline at upgrade time retries on its next start) + `routes.py` (`GET /api/airports/search`, `GET /api/airports/{iata}`) + `timezone.py` (converts naive local flight times to UTC using airport coordinates + TimezoneFinder — lives here rather than in `utils/` because it touches the DB, and not in `flights/` because `parsers/` needs it too and parsers/flights are kept independent). Lighter than the full routes→service→repository layering since there's no business logic in the routes. Other packages still query the `airports` table directly for their own narrow needs (parsers/, sync/grouping.py, trips/, settings/) rather than going through this repository.
- **`segments/`** — Manually-added non-flight transport legs (train, bus, ferry, car) on a trip: full routes→service→repository layering over the `trip_segments` table, plus the `GET /api/stations/search` type-ahead endpoint. Deliberately a **separate table from `flights`**, not a `transport_type` discriminator on it — `flights` carries ~15 flight-only columns and ten backend modules query it directly, so a discriminator would need a `WHERE type = 'flight'` guard at every one of those call sites and the first missed guard feeds a bus into `integrations/aircraft/sync.py`. Places are a free-text label plus **optional** coordinates rather than an IATA code (stations are not in the `airports` table); nullable coordinates are what let a hand-typed place still save, at the cost of its map line and timezone conversion. Times are stored UTC like flights, but the zone comes from the station's coordinates via `airports.timezone.get_timezone_for_coords` rather than from an airport lookup. `service.update_segment` merges a PATCH onto the stored row before validating — `_build_values` always emits a full row, so without the merge a one-field PATCH nulls everything else *and* skips validating the changed end against the unchanged one. The `type` column has no CHECK constraint so accommodation (`stay`) can join later without a SQLite table rebuild
- **`routes/`** — Leftover pre-refactor routes not yet folded into a feature package: `version.py` (app version endpoint)
- **`integrations/`** — Third-party API clients, one subpackage per provider: `immich/client.py` (album create/check), `aircraft/client.py` (AviationStack → OpenSky → hexdb.io lookups) + `aircraft/sync.py` (background aircraft-type sync job) + `aircraft/status_sync.py` (background live flight-status sync job, also AviationStack) + `aircraft/repository.py` (AircraftTypeRepository: the local `aircraft_types` cache table, seed data, and the one-time flight-row name-normalization sweep), `llm/parser.py` (optional Ollama LLM fallback; `llm_extract_flights(email_msg)` returns validated flights or `[]` when disabled; validates IATA codes against airports DB before returning), `wikipedia/client.py` (destination photo fetch + local WebP cache), `photon/client.py` (OpenStreetMap station type-ahead for `segments/`; `lang=en` and `osm_tag` are both load-bearing — without the former Photon answers in the local script and Latin-script queries barely match, without the latter every street sharing the name comes back. Chosen over an offline GeoNames load on coverage: GeoNames holds 669 stations in China against OSM's 17,320, and lacks Xi'an North entirely). Feature packages (trips, flights, sync, settings) call into these as clients rather than owning the third-party integration logic themselves.

### Frontend (`frontend/src/`)
- **Svelte 5** SPA with Vite; TypeScript throughout
- **`App.svelte`** — SPA router, auth checks, main layout
- **`api/client.ts`** — All HTTP calls to the backend
- **`lib/authStore.ts`** — Auth state (session user)
- `components/TripTransport.svelte` — the trip page's **Transport** section: flights and ground legs in one list, grouped Outbound / Getting around / Return by `utils.splitTransport`. Both kinds normalise to a `TransportLeg` so layovers, day dividers and leg totals are computed once (`legStats`, `connectionInfo`, `dateDividerInfo` all take legs, not flights); the rows stay separate components because `FlightRow` links to `FlightDetailPage` and a ground leg has no such page — `SegmentRow` opens the inline editor instead. `components/StationInput.svelte` is the station autocomplete. `utils.toLocalInputValue` seeds the edit form: `<input type="datetime-local">` has no timezone of its own, so without it a Beijing train opened in a European browser shows the wrong hour and silently moves on save
- `pages/EditFlightPage.svelte` — full-page flight editor, reached from the owner-only **Edit Flight** button on `FlightDetailPage` (a ground leg's inline editor has no flight equivalent because a flight has a detail page to hang it off). It resubmits **every** field on save, which is why the backend's `update_flight` re-runs `apply_airport_timezones` and recomputes duration/status: the two datetimes go out as naive local time at each airport (seeded by `utils.toLocalInputValue`, the same helper `TripTransport` uses), never as the stored UTC. The route exists under both `/trips/…` and `/history/…` and derives which from `$location`, like `FlightDetailPage`
- `components/TripMap.svelte` — the **Move map / Lock map** toggle exists because `dragging` starts off on touch devices (a full-width map answering vertical swipes traps the page scroll) and there was otherwise no way to turn it back on; the button flips `map.dragging` imperatively, and the map's creation effect reads that state through `untrack` so flipping it doesn't tear the map down and rebuild it. Wheel zoom stays off in both states — it has no gesture of its own to trap and would just steal the page's scroll; zooming is the +/- control and pinch. Touch detection is done locally (`ontouchstart` / `maxTouchPoints`) rather than via `L.Browser.touch`, which is only readable after Leaflet's dynamic import has resolved — too late to create the map in the right state.
- `components/TripMap.svelte`'s OSM fallback is for a CARTO that is *unreachable* (adblocker, DNS filter), and demotes only after `UNREACHABLE_TILE_FAILURES` errors **with no tile having loaded** — a layer that drew even one tile is reachable and is never demoted. Switching on the first `tileerror` meant one dropped request on a phone swapped the basemap for OSM, whose labels are in the local language (上海) where CARTO Voyager's are Latin (SHANGHAI), so a working map "turned Chinese" on mobile while a desktop that never dropped a tile stayed correct. `sw.js` was the other half: its catch-all `networkFirst` matched on pathname alone and so answered dropped *cross-origin* tile requests with a JSON 503, manufacturing the hard error — it now returns early for anything not same-origin
- `components/TripMap.svelte` reads `carto_api_key` off `$currentUser` (see the `/api/auth/me` note below) and **only adds the CARTO layer when it is set** — unkeyed Voyager tiles come back as a normal 200 carrying an "API KEY REQUIRED" watermark, so the `tileerror` → OSM fallback never fires on them; keyless installs go straight to OSM instead
- Pages: TripsListPage, TripDetailPage, FlightDetailPage, EditFlightPage, HistoryPage, StatsPage, SettingsPage, NotificationsPage, InvitationsPage, LoginPage, SetupPage, UsersPage (admin)

### Data & Config
- SQLite at `data/partiu.db` (gitignored); seed airports with `python load_airports.py`
- Environment via `.env` (see `.env.example`); key vars: `SECRET_KEY`, `DB_PATH`, `DISABLE_SCHEDULER`, `AVIATIONSTACK_API_KEY`, `PHOTON_URL`, `CARTO_API_KEY`, `OLLAMA_URL`, `OLLAMA_MODEL`
- Server-side config the **frontend** needs rides along on `GET /api/auth/me` (`MeResponseDTO`), which is where `ANNOUNCEMENT` and `CARTO_API_KEY` are surfaced. Not a Vite build-time var on purpose: the Docker image is built before any deployer has a key, so a build-time value would force a rebuild per install
- PWA icons generated by `generate_icons.py`

### CI (`.github/workflows/pr.yml`)
Runs: backend tests (70% coverage gate) + frontend lint/type-check + E2E tests (Playwright).

## Features

### Trip & flight management
- Auto-groups flights into trips by booking reference, then 48h time proximity
- Create/edit trips and flights manually; delete (owner only). Editing a flight covers every field (route, times, terminals, gates, seat, cabin, booking ref, passenger, notes); times are typed as local time at each airport and re-localised to UTC on save, which also recomputes duration/status and the trip's span
- Export trips as iCalendar (.ics) files — `trips/ical_service.py` emits flights and `trip_segments` as timed VEVENTs (both with a `-PT1H` VALARM) and each non-empty day-planner day as an **all-day** VEVENT. Three details there are load-bearing: all-day `DTEND` is *exclusive* (next day, or clients render a zero-length event and hide it); TEXT values go through `_escape` because an unescaped comma or semicolon splits a field into a value list, which free-text notes produce constantly; and lines are folded to 75 octets by `_fold`, which backs off on `encoded[end]` rather than `encoded[end - 1]` — the latter stops on a lead byte and eats the character, mangling CJK station names
- Notes per flight (up to 10,000 chars); calendar-style day notes per trip
- Trip rating (0.5–5 stars in 0.5 increments)
- **Trip expenses**: add itemised expenses per trip (description, amount, currency); totals grouped by currency shown in trip detail and trip cards; 41 supported currencies; per-user default currency (set in Settings)
- **Expense splitting**: each expense records who paid (`paid_by`: a collaborator or a guest, defaults to the creator) and who it's split equally between (`participants`, defaults to everyone currently on the trip); expense rows show who added them; `GET /api/trips/{trip_id}/expenses/balances` returns each participant's net balance per currency (what they paid minus their share)
- **Guests**: non-account trip companions for splitting expenses with people who don't have a Partiu account (`POST /api/guests` creates one, owned by the caller; `GET /api/guests` lists the caller's own; `PATCH /api/guests/{id}` renames one; `DELETE /api/guests/{id}` — blocked while referenced by an existing expense); a guest can't be deleted while referenced by an existing expense; guests are scoped per trip — `GET /api/trips/{trip_id}/expenses/participants` (the payer/split-between picker) only surfaces trip collaborators plus guests already tagged on *that* trip, not every guest the caller has ever created, so a guest added on one trip doesn't leak into an unrelated trip's picker; paid_by/participants validation on create/update additionally accepts a guest the caller owns but hasn't tagged on this trip yet, so a freshly quick-added guest can be used immediately as that first expense's payer/participant; a Settings section (add/rename/delete) manages the caller's own guest address book directly, independent of any single trip

### Ground transport (train, bus, ferry, car)
- Manually-added non-flight legs on a trip (`POST /api/trips/{trip_id}/segments`) — no email parsing, by design
- Station type-ahead via Photon/OpenStreetMap (`GET /api/stations/search`), returning real station coordinates
- Local times at each station are converted to UTC using the timezone derived from those coordinates, so cross-timezone durations are real elapsed time
- Ground legs render on `TripMap` as dashed straight lines colour-coded per type, distinct from the great-circle flight arcs, and appear in the **day planner** interleaved with that day's flights in time order (`TripDayCard` sorts on the real instant, not the printed local time, since a day's two ends can sit in different zones)
- `TripRepository._recompute_span` unions flights **and** `trip_segments` for the trip's start/end dates — the planner renders one card per day in that range, so a day holding only a train had no card to appear in until segments counted. Origin/destination stay flight-only (they are IATA codes; a station has none). The MIN/MAX there are the *aggregate* forms: the two-argument scalars return NULL when either side is empty, which would blank the span of a flights-only or segments-only trip. `SegmentService` calls `recompute_span` after every mutation
- The geocoder is optional (`PHOTON_URL`): a hand-typed place saves fine, it just gets no map line and no timezone conversion
- **Not counted in Stats** — `stats/repository.py` never reads `trip_segments`; travel statistics stay flight-only

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
- Built-in airline rules — 19 supported: LATAM (LA), SAS (SK), Norwegian (DY), Azul (AD), Lufthansa (LH), British Airways (BA), ITA Airways (AZ), Kiwi.com, Ryanair (FR), Austrian Airlines (OS), TAP Air Portugal (TP), Finnair (AY), Wizz Air (W6), Brussels Airlines (SN), Iberia (IB), Vueling (VY), Qatar Airways (QR), Turkish Airlines (TK), Pegasus Airlines (PC); `PARSER_VERSION = '31'`
- **Structural extraction only** — no generic proximity-guessing tier; see the `parsers/validation.py` entry above for why it was removed and what replaced it
- Localised forwarded-message headers (`De:`, `Von:`, `Från:`, …) so forwarded itineraries still reach their airline rule
- Cancelled legs are recognised and skipped: Lufthansa schedule-change mails reprint the dropped leg (`Estatuto: Cancelada`), and Finnair's cancellation notice reprints the whole itinerary in the confirmation layout
- **Airline-independent GDS e-ticket parser** (`parsers/gds_eticket.py`): reads the shared Amadeus/Sabre/Travelport ticket-receipt (ITR / ITR-EMD) table layout for any issuing airline, including per-leg terminals; prefers the bare IATA pairs the receipt restates in its baggage blocks over city-name resolution
- **Turkish Airlines** (`parsers/airlines/turkish.py`) reads TK's own branded "Ticket Details" mail — *not* a GDS receipt, so `gds_eticket` finds no marker in it — in both renderings: the HTML leg blocks and, as a fallback, the `TicketDetails.pdf` detail blocks. Neither rendering repeats the date inside a leg block, so both resolve it from the nearest line above that is a bare date or a route header (`Istanbul (IST) - Denizli (DNZ)`); "nearest line that parses as a date" would reach the `Transaction date:` line at the top and file every leg on the issue date. Passenger and booking reference are read from TK's own labels because this layout defeats the shared extractors — its "Passenger name" heading is followed by a route, and the PDF prints the greeting between "Reservation code" and the code. Turkish month names live in `engine.MONTH_MAP`
- **Pegasus Airlines** (`parsers/airlines/pegasus.py`) reads PC's Turkish-language "Rezervasyonun onaylandı!" confirmation. There is no attachment behind it, so the HTML leg block is the only rendering. The block is walked line by line rather than matched by one regex: the duration line and both terminal lines are independently optional, and a regex with three optional filler lines drifts onto the next leg's values as soon as one is missing. The date is never inside the block, so it comes from the nearest *bare-date* line above — "nearest line containing a date" would reach `Check-in Açılış: 12 Eylül 2026 02:45` at the top of the mail and file the outbound leg on the check-in opening day. The anchor is pinned to `PC` rather than `[A-Z]{2}` so no other carrier's number starts a block, and the passenger comes from PC's own greeting ("Sevgili …"), which the shared extractor does not recognise
- **Plausibility gate** (`parsers/validation.py`): drops legs that are physically impossible (great-circle distance vs. elapsed time, arrival before departure, same origin and destination) rather than storing them, reports broken leg chains, and rolls year-less dates forward when an itinerary would otherwise travel backwards across New Year
- **Ranked airport-name resolution** (`resolve_iata` in `parsers/shared.py`): scored, accent-folded, word-boundary matching using the `type` / `scheduled_service` ranking columns; returns `''` rather than guessing
- **Ollama LLM fallback** (optional): set `OLLAMA_URL` + `OLLAMA_MODEL` in `.env`; used as last resort for incremental sync; `run.sh` auto-starts Ollama if binary present; optional `ollama` service in `docker-compose.yml`
- CLI eval tool: `uv run python -m backend.tools.eval_eml_files` — tests LLM against `.eml` files (pass file or glob)
- Blocked sender domains: admin-managed list of domains silently skipped during sync (e.g. Airbnb, Booking.com)
- Manual sync trigger and configurable sync interval + email limit (admin)
- **Upload .eml files directly** from the trips list (`POST /api/sync/upload-eml`): parses uploaded `.eml` files through the same engine (rules → GDS e-ticket → LLM) and imports flights
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
TripsListPage, TripDetailPage, FlightDetailPage, EditFlightPage, HistoryPage, StatsPage, SettingsPage, NotificationsPage, InvitationsPage, UsersPage (admin), LoginPage, SetupPage
