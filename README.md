# Partiu ✈️

[![CI](https://github.com/thiagodsti/partiu/actions/workflows/pr.yml/badge.svg?branch=main)](https://github.com/thiagodsti/partiu/actions/workflows/pr.yml)
[![codecov](https://codecov.io/github/thiagodsti/partiu/branch/main/graph/badge.svg?token=7UC9WJZP8J)](https://codecov.io/github/thiagodsti/partiu)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Partiu** is a self-hosted alternative to TripIt — a personal flight tracker PWA that automatically reads your airline confirmation emails, parses the flight details, and organises everything into trips. No third-party account needed, no data leaving your server.

---

![demo](https://github.com/user-attachments/assets/1b772808-e56d-4580-84d9-361f6cec459a)

## Features

### Email sync & flight parsing
- Connects to Gmail (or any IMAP mailbox) and scans for flight confirmation emails
- Parses booking details: flight number, airports, times, seat, cabin class, passenger name, booking reference
- Generic PDF extraction fallback for attachments
- Built-in parser rules for 12 airlines (see [Supported airlines](#supported-airlines))
- **Optional Ollama LLM fallback**: when `OLLAMA_URL` is set, unknown-airline emails are sent to a local LLM as a last resort; output is validated (IATA codes, flight number format, required fields) against the airports DB before import — invalid data is rejected silently
- LLM fallback is used only for incremental sync, not full rescans
- Accepts forwarded emails via a built-in inbound SMTP server — no Gmail required
- Blocked sender domains: admin-configurable list of domains (e.g. Airbnb, Booking.com) that are silently skipped during sync
- Manual "sync now" trigger and configurable sync interval (admin)

### Trip & flight management
- Auto-groups flights into trips by booking reference, then 48h time proximity
- Create and edit trips and flights manually
- Shows outbound / return legs with connection badges and layover times
- Tracks flight status: upcoming, in-progress, completed
- Export any trip as an iCalendar (.ics) file
- Add notes per flight (up to 10,000 chars)
- Calendar-style day notes per trip

### Boarding passes & documents
- Extracts boarding passes from confirmation emails (BCBP barcode format)
- Manual upload of boarding pass images (PNG, JPEG, WebP)
- Upload trip documents: PDFs and images, up to 20 MB each, with multi-page PDF viewer
- Passenger name and seat parsed from BCBP data

### Trip sharing & collaboration
- Invite other Partiu users to a trip by username
- Pending / accepted / rejected invitation states with an in-app Invitations page
- Trusted users list: invitations from trusted users are auto-accepted
- Shared collaborators get full read/write access on trip content
- Owner can revoke access; collaborators can leave a trip
- Both owner and collaborators can rate trips (0.5–5 stars) and edit shared notes

### Travel statistics
- Total km travelled, total flights, total hours in the air
- Unique airports and countries visited
- Earth circumference laps
- Longest flight, top routes, top airports, top airlines
- Year filter with available-years selector

### Aircraft & flight enrichment
- Looks up aircraft type (Boeing 737-800, Airbus A320, …) while a flight is airborne
- Falls back to OpenSky Network if AviationStack is not configured
- Timezone-aware departure/arrival times (airport coordinates → TimezoneFinder)
- Live flight status tracking (delays, cancellations, estimated times)

### Destination images
- Auto-fetches a destination photo from Wikipedia for each trip
- Manual refresh to cycle to a different image

### Immich integration (optional)
- Create a photo album in your Immich instance for any completed trip
- Album is populated with photos taken during the trip's date range
- "Open Immich Album" button on trip cards once an album exists

### Notifications
- Web push notifications (VAPID) for flight reminders, check-in reminders, delays, new flights detected, and more
- In-app notification inbox with unread count badge
- Per-user notification preferences

### Authentication & security
- Username / password login with session cookies (30-day expiration, server-side revocable)
- TOTP-based 2FA — enable/disable from Settings; QR code for any authenticator app
- Login rate-limiting and TOTP lockout after repeated failures
- Audit logging of auth events

### Multi-user & admin
- Multi-user support with per-user Gmail/IMAP credentials
- Admin: create, list, update, reset passwords, delete users
- Admin: configure sync interval, max emails per sync, SMTP server, VAPID keys, airport data reload
- Per-user locale (English / Portuguese Brazil)

### PWA
- Installable on iOS and Android as a home screen app
- Works as a PWA — offline-capable shell, mobile-first responsive design

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

More airlines can be added by contributing a new rule (see [Contributing](#contributing)).

---

## Self-hosting

Partiu is designed to run on your own server — a VPS, a Raspberry Pi, or anything that can run Docker. Your flight data stays on your machine.

### Requirements

- Docker + Docker Compose
- A domain with HTTPS (required — session cookies use `Secure` flag)
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
| `AVIATIONSTACK_API_KEY` | | Free API key for aircraft type lookup |

All other settings (Gmail credentials, sync interval, SMTP server) are configured per-user or by the admin through the Settings page in the UI.

### First-run setup

On first visit, Partiu shows a setup page to create the admin account. After logging in, go to **Settings** to configure your Gmail address and App Password.

### Gmail App Password (per user)

1. Google Account → Security → 2-Step Verification → App passwords
2. Create one for "Mail" + "Other (Partiu)"
3. Paste the 16-character key in Settings → Gmail Account

### Two-Factor Authentication

Each user can enable TOTP-based 2FA from Settings → Two-Factor Authentication. Use any authenticator app (Google Authenticator, Authy, 1Password, etc.).

### AviationStack API Key (optional)

Provides aircraft type (e.g. Boeing 737-800) for airborne flights. The free plan includes 100 requests/month, enough for personal use.

1. Sign up at [aviationstack.com](https://aviationstack.com) — free plan
2. Copy your Access Key and add it to `.env` as `AVIATIONSTACK_API_KEY`

Falls back to [OpenSky Network](https://opensky-network.org) (free, no account needed) if not set.

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

> **Note:** Session cookies require HTTPS (`Secure` flag). For local development, access the app via a reverse proxy with a self-signed certificate or a tool like [mkcert](https://github.com/FiloSottile/mkcert).

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

# E2E tests (requires a running server at localhost:8000)
uv run playwright install chromium
uv run pytest frontend/tests/ -v
```

---

## CLI tools

Several developer tools live in `backend/tools/` for working with the parser pipeline and the LLM fallback.

### eval_eml_files — test models against .eml files

Runs one or two Ollama models against a list of `.eml` files and prints a side-by-side comparison. Useful for evaluating LLM prompt changes against known flight emails.

```bash
# Single file
uv run python -m backend.tools.eval_eml_files ~/Downloads/flight.eml

# Glob of files
uv run python -m backend.tools.eval_eml_files ~/Downloads/*.eml

# Compare two models
uv run python -m backend.tools.eval_eml_files ~/Downloads/*.eml \
    --models qwen2.5:0.5b,qwen2.5:1.5b

# Save full JSON report
uv run python -m backend.tools.eval_eml_files ~/Downloads/*.eml --output data/eml_compare.json
```

### compare_eval — compare two eval runs side by side

Compares two JSON result files produced by `eval_eml_files` and reports which emails one model extracted but the other didn't.

```bash
uv run python -m backend.tools.compare_eval \
    --a data/eval_1.5b.json \
    --b data/eval_0.5b.json \
    --output data/eval_diff.json
```

---

## LLM fallback — findings & limitations

The LLM fallback was evaluated against 114 real flight emails using two small local models via [Ollama](https://ollama.com):

| Model | Extracted | Invalid data | Rejected |
|---|---|---|---|
| `qwen2.5:1.5b` | 0 (0%) | 2 (2%) | 112 (98%) |
| `qwen2.5:0.5b` | 21 (18%) | 57 (50%) | 36 (32%) |

**Key findings:**

- **`qwen2.5:1.5b`** is too conservative — it rejects nearly everything, including obvious booking confirmation emails.
- **`qwen2.5:0.5b`** finds more flights but has a high invalid-data rate: it frequently confuses booking references with flight numbers, uses city names instead of IATA codes, and invents today's date instead of reading the date from the email. Most of these are caught by validation and never reach the DB.
- The validation layer (IATA format checks, required fields, airport DB lookup) is the critical safety net — it prevents hallucinated data from being imported regardless of model quality.
- For structured HTML airline emails (which is most of them), a dedicated rule-based parser will always outperform a small local LLM. The LLM is only useful for plain-text or unusual formats.

**Conclusion:** the LLM fallback is not reliable enough to replace parser rules for known airlines. It may work better with a larger or more capable model (e.g. `llama3`, `mistral`, or a cloud API), but this has not been tested.

To improve results, edit the system prompt in `backend/llm_parser.py` (`_PROMPT_SYSTEM`) and re-run `eval_eml_files` against known flight emails to measure the impact.

---

## Architecture

| Layer | Technology |
|---|---|
| Backend | FastAPI + APScheduler + SQLite (WAL mode) |
| Frontend | Svelte 5 + Vite (PWA) |
| Auth | Session cookies (itsdangerous) + bcrypt + TOTP 2FA |
| Email fetch | Gmail IMAP with App Password (per user) |
| Email receive | aiosmtpd (inbound SMTP server) |
| HTML parsing | BeautifulSoup4 + lxml |
| Aircraft data | AviationStack (primary) + OpenSky Network (fallback) |
| Photo albums | Immich (optional, self-hosted) |

---

## Contributing

Contributions are welcome! Here are the most impactful ways to help:

### Add support for a new airline

See **[CONTRIBUTING_PARSERS.md](CONTRIBUTING_PARSERS.md)** for the full step-by-step guide.

The short version:

```bash
# 1. Anonymize your .eml fixture
python tools/anonymize_eml.py ~/Downloads/confirmation.eml \
    --out backend/tests/fixtures/myairline_anonymized.eml

# 2. See what gets extracted (or what's missing)
python tools/parse_eml.py backend/tests/fixtures/myairline_anonymized.eml

# 3. Add rule + extractor, then scaffold a test automatically
python tools/parse_eml.py backend/tests/fixtures/myairline_anonymized.eml \
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
