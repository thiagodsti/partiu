# Adding a new airline parser

This guide walks you through adding support for a new airline from scratch.
The Kiwi.com parser is used as a worked example throughout.

---

## Prerequisites

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

---

## Step 1 — Get a confirmation email

Forward or export a flight confirmation email as a `.eml` file from your mail client:

- **Gmail**: open the email → three-dot menu → "Download message"
- **Apple Mail**: File → Save As → Format: Raw Message Source
- **Thunderbird**: File → Save As → EML format

---

## Step 2 — Anonymize it

Run the anonymizer to strip PII before committing the fixture:

```bash
python tools/anonymize_eml.py ~/Downloads/myairline_confirmation.eml \
    --out backend/tests/fixtures/myairline_anonymized.eml
```

The script automatically replaces email addresses, phone numbers and detected passenger names. It will print anything it found:

```
  Detected probable names: ['John Michael Smith']
  ✅  Written to backend/tests/fixtures/myairline_anonymized.eml

  ⚠️  Please review the output manually before committing:
      - Passenger name in unusual HTML locations
      - Passport / ID numbers
      - Loyalty programme numbers
      - Credit card last 4 digits
```

Open the output file and do a quick manual scan before continuing.

---

## Step 3 — See what the parser already extracts

```bash
python tools/parse_eml.py backend/tests/fixtures/myairline_anonymized.eml
```

**Three possible outcomes:**

### A) A rule matched and all flights look correct ✅

```
  ✅  Rule matched: 'MyAirline' (extractor: 'myairline')
  ✅  3 flight(s) extracted:
  [0] LA100     GRU → SCL  2024-06-01T10:00  LATAM Airlines
  ...
```

Jump straight to [Step 6 — Write the test](#step-6--write-the-test).

### B) A rule matched but 0 flights extracted ⚠️

The `sender_pattern` / `subject_pattern` already matches but the extractor returns nothing. You need to fix or write the extractor — see [Step 5](#step-5--write-the-extractor).

### C) No rule matched ❌

```
  ❌  No rule matched.
  → You need to add a new rule to backend/parsers/builtin_rules.py
```

Continue from [Step 4](#step-4--add-a-rule).

---

## Step 4 — Add a rule

Open `backend/parsers/builtin_rules.py` and add an entry to the `BUILTIN_RULES` list.

**Fields:**

| Field | Description | Example |
|---|---|---|
| `airline_name` | Display name | `"Ryanair"` |
| `airline_code` | IATA carrier code (empty for OTAs) | `"FR"` |
| `sender_pattern` | Regex matching the From address | `r'@ryanair\.com'` |
| `subject_pattern` | Regex matching the Subject (optional) | `r'boarding pass'` |
| `body_pattern` | Regex with named groups for generic fallback | `r''` |
| `custom_extractor` | Key for your extractor function | `"ryanair"` |
| `priority` | `10` for direct airlines, `5` for OTAs | `10` |

**Example (Kiwi.com):**

```python
BuiltinAirlineRule(
    airline_name="Kiwi.com",
    airline_code="",
    sender_pattern=r'(kiwi\.com|tickets@kiwi)',
    subject_pattern=r'(Reserva|Booking|itinerary|reservation|viagem|trip)',
    body_pattern=r'',
    custom_extractor="kiwi",
    date_format="%d %b %Y",
    time_format="%H:%M",
    is_active=True,
    is_builtin=True,
    priority=5,
),
```

> **Forwarded emails**: if users will forward the email to Partiu (rather than having it synced directly), the outer `From` header will be their personal address, not the airline's. The rule will still match because the engine also scans the email body for embedded `From:` and `Subject:` lines from the forwarded message.

After adding the rule, bump `RULES_VERSION` by 1 (e.g. `'13'` → `'14'`). This triggers a full rescan of existing emails.

Re-run the parse script to check the rule matches:

```bash
python tools/parse_eml.py backend/tests/fixtures/myairline_anonymized.eml
```

---

## Step 5 — Write the extractor

Create `backend/parsers/airlines/myairline.py`:

```python
"""
MyAirline confirmation email extractor.

Email format: HTML body with a flight table.
Relevant HTML: <table class="flight-details"> with rows for each leg.
"""

from bs4 import BeautifulSoup

from ..shared import _make_flight_dict, _make_aware


def extract_bs4(html: str, rule, email_msg) -> list[dict]:
    """Extract flights from the HTML body."""
    soup = BeautifulSoup(html, "lxml")
    flights = []

    for row in soup.select("table.flight-details tr.flight-row"):
        flight_number = row.select_one(".flight-number").get_text(strip=True)
        dep_airport   = row.select_one(".dep-airport").get_text(strip=True)
        arr_airport   = row.select_one(".arr-airport").get_text(strip=True)
        dep_time      = row.select_one(".dep-time").get_text(strip=True)
        arr_time      = row.select_one(".arr-time").get_text(strip=True)
        dep_date      = row.select_one(".dep-date").get_text(strip=True)

        dep_dt = _make_aware(dep_date, dep_time, rule.date_format, rule.time_format, dep_airport)
        arr_dt = _make_aware(dep_date, arr_time, rule.date_format, rule.time_format, arr_airport)

        flights.append(_make_flight_dict(
            rule=rule,
            flight_number=flight_number,
            departure_airport=dep_airport,
            arrival_airport=arr_airport,
            departure_datetime=dep_dt,
            arrival_datetime=arr_dt,
        ))

    return flights
```

### Key helpers in `backend/parsers/shared.py`

| Helper | What it does |
|---|---|
| `_make_aware(date_str, time_str, date_fmt, time_fmt, iata)` | Parses a local date+time string and converts to UTC using the airport's timezone |
| `_make_flight_dict(rule, flight_number, ...)` | Returns a complete flight dict with all required fields |
| `_get_text(element)` | Safe `.get_text(strip=True)` that returns `""` on None |
| `_extract_booking_reference(text)` | Common booking ref patterns |
| `_extract_passenger_name(text)` | Common passenger name patterns |

### Register the extractor

Open `backend/parsers/airlines/__init__.py` and add two lines:

```python
from .myairline import extract_bs4 as _myairline   # add import

_EXTRACTORS = {
    ...
    "myairline": _myairline,                        # add entry
}
```

Iterate on the extractor until the parse script shows the correct output:

```bash
python tools/parse_eml.py backend/tests/fixtures/myairline_anonymized.eml
```

---

## Step 6 — Write the test

Use `--generate-test` to scaffold a ready-to-run test file from the live output:

```bash
python tools/parse_eml.py backend/tests/fixtures/myairline_anonymized.eml \
    --generate-test \
    --out backend/tests/test_myairline_parser.py
```

This generates a complete pytest file with one class per leg and assertions for every field. Review the generated file, fix anything that looks wrong (the generator is a starting point, not gospel), then run it:

```bash
pytest backend/tests/test_myairline_parser.py -v
```

All tests should be green. If not, fix the extractor and re-run.

### What a good test looks like

The [Kiwi test](backend/tests/test_kiwi_parser.py) is the reference. Key things it covers:

- **Rule matching** — `test_rule_is_found`, `test_rule_name`
- **Flight count** — exactly N flights extracted
- **Per-leg fields** — `flight_number`, `departure_airport`, `arrival_airport`, `airline_code`, `departure_datetime`, `arrival_datetime`
- **Booking reference** — present on all legs, correct value

---

## Step 7 — Run the full test suite

```bash
pytest backend/tests/ -v --cov=backend --cov-fail-under=70
```

Make sure coverage stays above 70% and no existing tests are broken.

---

## Step 8 — Open a PR

- Put the anonymized `.eml` in `backend/tests/fixtures/`
- Put the test in `backend/tests/test_<airline>_parser.py`
- Add the rule to `backend/parsers/builtin_rules.py` (and bump `RULES_VERSION`)
- Add the extractor to `backend/parsers/airlines/<airline>.py`
- Register it in `backend/parsers/airlines/__init__.py`
- Update the supported airlines table in `README.md`

---

## Troubleshooting

**"No rule matched"** — check that `sender_pattern` matches the From address in your `.eml`. Look at the `From:` line printed by `parse_eml.py`. If the email is forwarded, look for the embedded `From:` line inside the body.

**"0 flights extracted"** — the extractor ran but returned nothing. Add some `print()` statements inside your extractor and re-run `parse_eml.py` to see what the HTML/PDF actually contains.

**Datetime parsing errors** — check `date_format` and `time_format` in the rule match the format in the email. Use Python's `strptime` format codes.

**Timezone is wrong** — `_make_aware` looks up the airport's timezone from the database. Make sure `load_airports.py` has been run and the departure/arrival IATA codes are correct.
