# Partiu ✈️

[![CI](https://github.com/thiagodsti/partiu/actions/workflows/pr.yml/badge.svg?branch=main)](https://github.com/thiagodsti/partiu/actions/workflows/pr.yml)
[![codecov](https://codecov.io/github/thiagodsti/partiu/branch/main/graph/badge.svg?token=7UC9WJZP8J)](https://codecov.io/github/thiagodsti/partiu)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Partiu** is a self-hosted alternative to TripIt — a personal flight tracker PWA that automatically reads your airline confirmation emails, parses the flight details, and organises everything into trips. No third-party account needed, no data leaving your server.

---

![Partiu walkthrough: trips list, a trip page, the trip planner board and plan map, and stats](docs/demo.gif)

## Live demo

Want to try it before self-hosting? A public demo is available at:

**[https://partiu-demo.teda.work](https://partiu-demo.teda.work)**

| Field | Value |
|---|---|
| Username | `demo` |
| Password | `demo1234` |

> **Note:** The demo is reset every 6 hours with fresh sample data. Any changes you make will be wiped on the next reset. The upcoming "Lisbon & Oslo" trip comes with stays and a filled-in trip planner to explore.

---

## Features

### Email import
- Reads your Gmail (or any IMAP mailbox) and turns airline confirmation emails into flights: flight number, airports, times, seat, cabin, passenger and booking reference
- Built-in support for [19 airlines](#supported-airlines), plus a shared parser for the standard e-ticket receipts (Amadeus, Sabre, Travelport) that any airline can issue, and the flight markup many airlines embed for Gmail
- Schedule changes update the flights you already have and show the previous times; cancellation emails mark flights as cancelled (never deleted)
- Boarding-pass emails (Lufthansa, LATAM) fill in seat, gate and terminal on the flight you already have
- Hotel bookings from Airbnb, Booking.com and Trip.com, and car rentals from Hertz, Sixt and Europcar, import themselves; a stated price becomes a trip expense
- Implausible results (arrival before departure, impossible speeds) are dropped rather than stored
- Optional local LLM fallback (Ollama) for emails no parser recognises — [how well it does](AGENTS.md#llm-fallback--findings--limitations)
- Also accepts forwarded emails through a built-in SMTP server, or `.eml` files uploaded from the trips list

### Trips
- Flights are grouped into trips automatically, by booking reference and time proximity; trips and flights can also be created and edited by hand
- One itinerary per trip with flights, trains, buses, ferries and drives together, grouped into outbound / getting around / return, with layover times
- Stays (hotels, Airbnbs, hostels) and car rentals, each in its own section, with uncovered nights flagged
- A map of every trip: flights as great-circle arcs, ground legs as dashed lines
- A day-by-day planner on the trip page, notes per flight and per day, a packing list, documents (PDFs and images) and boarding passes
- Export any trip to your calendar (.ics), in the local time of each place
- Deleted trips and flights go to a trash in Settings and can be restored

### Trip planner
- A planner page per trip: a route of cities with dates, and a board with one column per day showing the city, transport, the night's stay (or a "no stay" warning), things to do and notes
- Things to do have a status (idea → to book → booked → done), an optional time and a place, and can be dragged between days
- Search for places to visit near the route, keep unscheduled ideas, and track before-the-trip to-dos with an assignee
- A map of the whole plan; click a day to focus on it. Place names follow your profile language (English or Portuguese)
- Everything saves as you go; on a phone the board becomes stacked day cards

### Money and people
- Itemised expenses per trip in 41 currencies, split between the people on the trip, with per-person balances
- Guests: companions without a Partiu account can pay for and share expenses
- A budget per trip that counts your share, can be shared with a partner, and turns amber and then red as it runs out
- Share a trip with other Partiu users as collaborators; invitations from trusted users are accepted automatically

### Statistics and extras
- Distance, flights, hours in the air, airports and countries visited (trains, stays and car rentals count toward countries), top routes and airlines, by year
- Aircraft type and live flight status (AviationStack, with OpenSky as a fallback)
- A destination photo for each trip from Wikipedia
- Optional Immich integration: create a photo album for a trip from the photos taken during it
- Web push and in-app notifications: reminders, delays, check-in, new flights

### Accounts and security
- Multi-user, each with their own mailbox, settings and language (English / Portuguese)
- TOTP two-factor authentication, sign-in rate limiting and an audit log
- Personal API keys (read-only or read/write) for scripts and other services
- A demo mode for public instances

### Interface
- Installable PWA for iOS and Android, responsive from phone to desktop
- Light and dark themes and five accent colours

## Supported airlines

| Airline | IATA Code |
|---|---|
| LATAM Airlines | LA |
| SAS Scandinavian Airlines | SK |
| Norwegian Air Shuttle | DY |
| Azul Brazilian Airlines | AD |
| Lufthansa | LH |
| British Airways (+ Iberia legs on BA itineraries) | BA |
| ITA Airways | AZ |
| Kiwi.com (multi-airline bookings) | — |
| Ryanair | FR |
| Austrian Airlines | OS |
| TAP Air Portugal (check-in, boarding pass, booking confirmation, e-ticket receipt) | TP |
| Finnair | AY |
| Wizz Air | W6 |
| Brussels Airlines | SN |
| Iberia | IB |
| Vueling | VY |
| Qatar Airways | QR |
| Turkish Airlines (branded "Ticket Details" mail — HTML and PDF renderings) | TK |
| Pegasus Airlines (Turkish-language booking confirmation) | PC |

More airlines can be added by contributing a new rule (see [Contributing](#contributing)).

---

## Self-hosting

Partiu is designed to run on your own server — a VPS, a Raspberry Pi, or anything that can run Docker. Your flight data stays on your machine.

### Requirements

- Docker + Docker Compose
- A domain with HTTPS (recommended for production — set `SECURE_COOKIES=false` to disable if needed)
- A Gmail account with an **App Password** per user (or any IMAP-compatible mailbox)

### Deploy with Docker Compose

```bash
git clone https://github.com/your-username/partiu
cd partiu
cp .env.example .env
# Edit .env — at minimum set SECRET_KEY (see below)
docker compose up -d --build
```

Open `https://your-domain` and complete the first-run setup to create your admin account.

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✓ | Secret key for signing session cookies. Generate with `openssl rand -hex 32` |
| `DB_PATH` | | Path to the SQLite database (default: `./data/partiu.db`) |
| `DISABLE_SCHEDULER` | | Set to `true` to disable background email sync (useful for dev) |
| `DISABLE_RATE_LIMITS` | | **Test servers only.** Set to `true` to turn off the per-IP limits (5 sign-ins/minute, the failed-login lockout, upload limits) so the E2E suite can run; logged as a warning at startup. Never set it in production |
| `AVIATIONSTACK_API_KEY` | | Free API key for aircraft type lookup |
| `CARTO_API_KEY` | | Key for the trip map's CARTO Voyager basemap tiles (see below). Unset, the map uses plain OpenStreetMap tiles |
| `PHOTON_URL` | | Geocoder for the station, hotel and address pickers (default: `https://photon.komoot.io`). Point at a self-hosted [Photon](https://github.com/komoot/photon) instance, or set it empty to disable the lookup and type places as plain text — note that a place with no coordinates gets no map pin, no timezone conversion, and does not count toward visited countries |
| `OLLAMA_URL` | | Ollama endpoint for the LLM parsing fallback (e.g. `http://ollama:11434`). Unset, the fallback is disabled and only the built-in airline rules run |
| `OLLAMA_MODEL` | | Model for the fallback (default: `qwen3:4b-instruct`) |
| `OLLAMA_NUM_CTX` | | Context window sent with every request, in tokens (default: `8192`). Ollama's own default of 4096 is too small for long itineraries, and Ollama refuses rather than truncates |
| `SECURE_COOKIES` | | Set to `false` when testing over plain HTTP on a local network. Leave `true` in production |
| `ANNOUNCEMENT` | | A short message shown as a banner to every signed-in user |
| `DEMO_MODE` | | Set to `true` on a public demo instance: the login page prints the shared demo credentials with a one-click sign-in, a permanent banner says the account is shared, the sign-in throttles are relaxed, and credential/account changes are refused (see below). Off by default, and while it is off the endpoint serving the credentials returns nothing |
| `DEMO_USERNAME` | | Username published by `DEMO_MODE` (default: `demo`). Advertises an account; does not create one |
| `DEMO_PASSWORD` | | Password published by `DEMO_MODE` (default: `demo1234`) |
| `PARTIU_VERSION` | | The running version, shown in the UI and used for the update check. Normally set to the Docker image tag |

Which of these are set is visible at a glance in **Settings → Optional integrations** (admin only), along with what each one adds. It is also summarised in one line at INFO level on startup. Nothing here is required: every integration degrades a single feature rather than breaking the app.

All other settings (Gmail credentials, sync interval, SMTP server) are configured per-user or by the admin through the Settings page in the UI.

### First-run setup

On first visit, Partiu shows a setup page to create the admin account. After logging in, go to **Settings** to configure your Gmail address and App Password.

### Gmail App Password (per user)

1. Google Account → Security → 2-Step Verification → App passwords
2. Create one for "Mail" + "Other (Partiu)"
3. Paste the 16-character key in Settings → Gmail Account

### Two-Factor Authentication

Each user can enable TOTP-based 2FA from Settings → Two-Factor Authentication. Use any authenticator app (Google Authenticator, Authy, 1Password, etc.).

### API keys

Settings → API keys → *Create key*. Copy the value straight away — it is never shown again. Then:

```bash
curl -H "Authorization: Bearer partiu_…" https://your-partiu/api/trips
curl -H "Authorization: Bearer partiu_…" https://your-partiu/api/auth/me   # who the key belongs to
```

A *read only* key gets 403 on anything but GET. Keys are meant for server-to-server use; the API sends no CORS headers for other origins.

### AviationStack API Key (optional)

Provides aircraft type (e.g. Boeing 737-800) for airborne flights. The free plan includes 100 requests/month, enough for personal use.

1. Sign up at [aviationstack.com](https://aviationstack.com) — free plan
2. Copy your Access Key and add it to `.env` as `AVIATIONSTACK_API_KEY`

Falls back to [OpenSky Network](https://opensky-network.org) (free, no account needed) if not set.

### CARTO basemap API key (optional)

The trip map draws on [CARTO](https://carto.com)'s Voyager basemap. CARTO now requires an API key for its tiles and stamps unkeyed ones with an "API KEY REQUIRED" watermark.

1. Request a free key at [carto.com/basemaps/apikey](https://carto.com/basemaps/apikey/) (5M tile requests/month)
2. Add it to `.env` as `CARTO_API_KEY` and restart the container

It is read at runtime, not baked in at build time, so the published Docker image picks up your key without rebuilding. Leave it unset and the map falls back to plain OpenStreetMap tiles, which need no key — you lose the Voyager styling and get place names in the local language (上海 rather than Shanghai), nothing else.

The same OpenStreetMap fallback also catches a CARTO blocked by an adblocker or DNS filter. You can tell which basemap you are looking at from the attribution in the map's bottom-right corner: `© OSM © CARTO` is the keyed Voyager basemap, `© OpenStreetMap` alone is the fallback.

### Immich integration (optional)

[Immich](https://immich.app) is a self-hosted photo management platform. Partiu can automatically create an Immich album for each completed trip using photos taken during the trip's date range.

**Setup:**

1. In your Immich instance, go to **Account Settings → API Keys** and create a new API key
2. Grant the following permissions to the key:

   | Permission | Why |
   |---|---|
   | `asset.read` | Find photos within the trip date range |
   | `asset.view` | Access asset metadata |
   | `asset.download` | Required alongside read for full access |
   | `asset.copy` | Needed for album operations |
   | `album.create` | Create the trip album |
   | `album.read` | Read album details |
   | `album.update` | Update album contents |
   | `albumAsset.create` | Add photos to the album |

3. In Partiu, go to **Settings → Immich** and enter:
   - **Immich URL** — base URL of your Immich instance (e.g. `https://photos.yourdomain.com`)
   - **API Key** — the key you created above
4. Click **Test Connection** to verify — then **Save**

Once configured, a **Create Immich Album** button will appear on any completed trip (in both the trip detail view and the history page). If an album was already created for that trip, the button changes to **Open Immich Album** and takes you directly to it.

To recreate an album, delete it in Immich first — the button will revert to "Create".

> **Known issue:** when tapping "Open Immich Album" on iOS/Android, the deep link navigates correctly to the album only if the Immich app is already open. If the app is fully closed, it will launch but land on the home page instead of the album. This is a bug in the Immich mobile app's cold-start deep link handling — tracked at [immich-app/immich#27069](https://github.com/immich-app/immich/issues/27069).

### Inbound SMTP (email forwarding)

Instead of — or in addition to — Gmail IMAP sync, you can forward emails directly to Partiu:

1. Enable the SMTP server in Settings (admin only) and choose a port (default `2525`)
2. Point your domain's MX record to your server, or set up an email alias that forwards to `your-server:2525`
3. Forward any flight confirmation email to the configured recipient address

This is useful if you use a non-Gmail provider or want instant processing without waiting for the next IMAP poll.

### Router / DNS setup (for inbound SMTP)

| DNS record | Value |
|---|---|
| `A mail.yourdomain.com` | Your server's public IP |
| `MX yourdomain.com` | `mail.yourdomain.com` (priority 10) |

Forward port `25` (or `2525`) on your router/firewall to the server running Partiu.

---

## Local development

### Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node.js 24+

### Quick start (both services at once)

```bash
bash run.sh
```

`run.sh` starts the backend and frontend in parallel and stops both when you press `Ctrl+C`.

| Service | URL |
|---|---|
| Backend API | http://localhost:8000 |
| Frontend dev server | http://localhost:5173 |

> **Note:** For local development, set `SECURE_COOKIES=false` in your `.env` — no HTTPS or certificate needed. Browsers also treat `localhost` as a secure context, so `secure` cookies work over plain HTTP on localhost even without this flag.

### Backend

```bash
uv sync
uv run uvicorn backend.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # Vite dev server at localhost:5173
```

### Tests

```bash
# Backend unit tests
uv run pytest backend/tests/ -v --cov=backend --cov-fail-under=70

# E2E tests: starts its own server on a scratch database (with a per-run
# SECRET_KEY unless you export one), waits for it, runs Playwright and stops it.
# Refuses to run if port 8000 is already in use, since global setup would
# otherwise create test accounts in that server's database.
# On Linux, use `npx playwright install --with-deps chromium` to also get the
# system libraries Chromium needs.
(cd frontend && npm ci && npx playwright install chromium && npm run build)
scripts/run_e2e.sh                       # or: scripts/run_e2e.sh tests/foo.spec.ts
```

---

## CLI tools

Developer tools for the parser pipeline and the LLM fallback live in `backend/tools/`; see [AGENTS.md](AGENTS.md#cli-tools) for full usage.

| Tool | What it does |
|---|---|
| `corpus_report` | Parser coverage over your cached email corpus; run before and after a parser change |
| `inspect_eml` | Run one `.eml` through the full production pipeline and see what each step extracted |
| `inspect_eml_llm` | Send one `.eml` straight to the LLM and show the raw answer and validation |
| `eval_llm_corpus` | Score the LLM fallback against what the airline rules extract |
| `eval_eml_files` / `compare_eval` | Compare one or two Ollama models over a set of `.eml` files |

Run any of them with `uv run python -m backend.tools.<name> --help`.

---

## Architecture

| Layer | Technology |
|---|---|
| Backend | FastAPI + APScheduler + SQLite (WAL mode) |
| Frontend | Svelte 5 + Vite (PWA) |
| Auth | Session cookies (itsdangerous) + bcrypt + TOTP 2FA + hashed Bearer API keys |
| Email fetch | Gmail IMAP with App Password (per user) |
| Email receive | aiosmtpd (inbound SMTP server) |
| HTML parsing | BeautifulSoup4 + lxml |
| Aircraft data | AviationStack (primary) + OpenSky Network (fallback) |
| Photo albums | Immich (optional, self-hosted) |
| Station lookup | Photon / OpenStreetMap (optional, self-hostable) |
| Maps | Leaflet with CARTO / OpenStreetMap tiles; the planner map uses MapLibre with OpenFreeMap vector tiles |

---

## Contributing

Contributions are welcome! Here are the most impactful ways to help:

### Add support for a new airline

See **[CONTRIBUTING_PARSERS.md](CONTRIBUTING_PARSERS.md)** for the full step-by-step guide.

The short version:

```bash
# 1. Anonymize your .eml fixture
uv run python tools/anonymize_eml.py ~/Downloads/confirmation.eml \
    --out backend/tests/fixtures/myairline_anonymized.eml

# 2. See what gets extracted (or what's missing)
uv run python tools/parse_eml.py backend/tests/fixtures/myairline_anonymized.eml

# 3. Add rule + extractor, then scaffold a test automatically
uv run python tools/parse_eml.py backend/tests/fixtures/myairline_anonymized.eml \
    --generate-test --out backend/tests/test_myairline_parser.py
```

### Report a parsing failure

Open an issue and attach (or paste) the relevant parts of the email — subject line, sender address, and the text body (redact personal info if needed). HTML structure matters most.

### General guidelines

- Keep changes focused — one airline or one bug fix per PR
- Don't add dependencies unless absolutely necessary
- Backend: follow existing patterns (raw `sqlite3`, no ORM, plain dicts)
- Frontend: Svelte 5 with `$state` / `$derived` runes, no extra UI frameworks

---

## License

MIT
