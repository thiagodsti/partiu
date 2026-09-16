"""
Measure parser coverage over a cached email corpus, tier by tier.

Usage:
    uv run python -m backend.tools.corpus_report [options]

Options:
    --cache FILE    Corpus JSON (default: data/email_cache.json) — a list of dicts
                    with message_id, sender, subject, body, html_body, date and
                    base64 pdf_attachments, as written by the sync's cache.
    --db FILE       SQLite database with a populated airports table (default:
                    data/partiu.db). Name resolution is silently disabled without
                    one, so measuring against an empty DB understates coverage.
    --json FILE     Also write every per-email row to FILE.
    --quiet         Print the per-rule table only, without the per-email lists.

Run it before and after a parser change and diff the two outputs. The table is
the headline; the lists under it are the point — a mail that matches a rule and
produces nothing is either correct silence (a receipt, a reminder) or a template
the rule cannot read, and only reading the subject tells which. Every gap found
in September 2026 sat in that list for months first.

Legs are counted after apply_airport_timezones + validate_flights, exactly as
the pipeline stores them, so an impossible leg counts for nothing here either.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Fields every extractor row carries; kept in one place so summarise() and the
# JSON dump agree on the schema.
ROW_FIELDS = (
    "domain",
    "subject",
    "blocked",
    "rule",
    "rule_legs",
    "gds_legs",
    "valid_legs",
    "stays",
    "rentals",
    "boarding_passes",
    "cancellations",
    "pdfs",
    "error",
)


def load_corpus(path: str | Path) -> list:
    """Rebuild EmailMessage objects from the cache JSON."""
    from backend.parsers.email_connector import EmailMessage

    emails = []
    for d in json.loads(Path(path).read_text(encoding="utf-8")):
        emails.append(
            EmailMessage(
                message_id=d.get("message_id", ""),
                sender=d.get("sender", ""),
                subject=d.get("subject", ""),
                body=d.get("body") or "",
                date=datetime.fromisoformat(d["date"]) if d.get("date") else None,
                html_body=d.get("html_body"),
                pdf_attachments=[base64.b64decode(p) for p in d.get("pdf_attachments") or []],
            )
        )
    return emails


def measure(email_msg, rules) -> dict:
    """Run every tier over one email and report what each produced."""
    from backend.airports.timezone import apply_airport_timezones
    from backend.parsers.car_rental import extract_car_rentals
    from backend.parsers.engine import (
        extract_flights_from_email,
        match_rule_to_email,
        merge_flights,
    )
    from backend.parsers.gds_eticket import extract_gds_eticket
    from backend.parsers.schema_org import extract_lodging_reservations
    from backend.parsers.validation import validate_flights
    from backend.sync.pipeline import _sender_domain, is_non_flight_domain

    row = {
        "domain": _sender_domain(email_msg.sender or ""),
        "subject": (email_msg.subject or "")[:80],
        "blocked": is_non_flight_domain(email_msg.sender or ""),
        "rule": None,
        "rule_legs": 0,
        "gds_legs": 0,
        "valid_legs": 0,
        "stays": 0,
        "rentals": 0,
        "boarding_passes": 0,
        "cancellations": 0,
        "pdfs": len(email_msg.pdf_attachments),
        "error": "",
        "legs": [],
    }
    try:
        row["stays"] = len(extract_lodging_reservations(email_msg))
        row["rentals"] = len(extract_car_rentals(email_msg))
        rule = match_rule_to_email(email_msg, rules)
        flights: list[dict] = []
        if rule is not None:
            row["rule"] = rule.airline_code or rule.airline_name
            flights = extract_flights_from_email(email_msg, rule)
            row["rule_legs"] = len(flights)
            if rule.boarding_pass_extractor:
                row["boarding_passes"] = len(rule.boarding_pass_extractor(email_msg) or [])
            if rule.cancellation_extractor:
                row["cancellations"] = len(rule.cancellation_extractor(email_msg) or [])
        gds = extract_gds_eticket(email_msg, rule)
        row["gds_legs"] = len(gds)
        if gds:
            flights = merge_flights(flights, gds)
        flights = [apply_airport_timezones(f) for f in flights]
        valid = validate_flights(flights, source=row["subject"][:60])
        row["valid_legs"] = len(valid)
        row["legs"] = [
            (
                f.get("flight_number"),
                f.get("departure_airport"),
                f.get("arrival_airport"),
                str(f.get("departure_datetime"))[:16],
            )
            for f in valid
        ]
    except Exception as e:  # noqa: BLE001 - one bad email must not stop the report
        row["error"] = f"{type(e).__name__}: {e}"[:160]
    return row


def _produced_anything(row: dict) -> bool:
    return bool(
        row["valid_legs"]
        or row["boarding_passes"]
        or row["cancellations"]
        or row["stays"]
        or row["rentals"]
    )


def summarise(rows: list[dict]) -> dict:
    """Aggregate per-email rows into the report's numbers and lists."""
    per_rule: dict[str, dict] = {}
    for r in rows:
        if not r["rule"]:
            continue
        stats = per_rule.setdefault(
            r["rule"],
            {
                "matched": 0,
                "with_flights": 0,
                "legs": 0,
                "boarding_passes": 0,
                "cancellations": 0,
                "nothing": [],
            },
        )
        stats["matched"] += 1
        stats["legs"] += r["valid_legs"]
        if r["valid_legs"]:
            stats["with_flights"] += 1
        if r["boarding_passes"]:
            stats["boarding_passes"] += 1
        if r["cancellations"]:
            stats["cancellations"] += 1
        if not _produced_anything(r):
            stats["nothing"].append(r)

    unmatched: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if not r["rule"] and not r["blocked"]:
            unmatched[r["domain"]].append(r)

    return {
        "total": len(rows),
        "blocked": sum(1 for r in rows if r["blocked"]),
        "rule_matched": sum(1 for r in rows if r["rule"]),
        "emails_with_flights": sum(1 for r in rows if r["valid_legs"]),
        "legs": sum(r["valid_legs"] for r in rows),
        "stays": sum(r["stays"] for r in rows),
        "rentals": sum(r["rentals"] for r in rows),
        "boarding_passes": sum(r["boarding_passes"] for r in rows),
        "cancellations": sum(r["cancellations"] for r in rows),
        "errors": [r for r in rows if r["error"]],
        "per_rule": dict(sorted(per_rule.items())),
        "unmatched_by_domain": dict(sorted(unmatched.items(), key=lambda kv: -len(kv[1]))),
        "blocked_producing": [r for r in rows if r["blocked"] and (r["stays"] or r["rentals"])],
        "blocked_silent": Counter(
            r["domain"] for r in rows if r["blocked"] and not (r["stays"] or r["rentals"])
        ),
    }


def render(summary: dict, *, quiet: bool = False) -> str:
    """Format the summary as the text the CLI prints."""
    out = [
        f"emails {summary['total']}  blocked {summary['blocked']}  rule matched {summary['rule_matched']}",
        f"emails with flights {summary['emails_with_flights']}  legs {summary['legs']}",
        f"stays {summary['stays']}  rentals {summary['rentals']}  "
        f"boarding passes {summary['boarding_passes']}  cancellations {summary['cancellations']}",
    ]
    if summary["errors"]:
        out.append(f"ERRORS {len(summary['errors'])}:")
        out += [f"  {r['domain']} | {r['subject'][:50]} | {r['error']}" for r in summary["errors"]]

    out.append("")
    out.append(
        f"{'rule':12} {'matched':>7} {'flights':>7} {'legs':>5} {'bp':>3} {'cancel':>6} {'nothing':>7}"
    )
    for code, s in summary["per_rule"].items():
        out.append(
            f"{code:12} {s['matched']:7} {s['with_flights']:7} {s['legs']:5} "
            f"{s['boarding_passes']:3} {s['cancellations']:6} {len(s['nothing']):7}"
        )
        if not quiet:
            out += [f"    - [{r['pdfs']}pdf] {r['subject']}" for r in s["nothing"]]

    if not quiet:
        out.append("")
        out.append("no rule, not blocked (domain, count, sample subjects):")
        for domain, rs in summary["unmatched_by_domain"].items():
            out.append(f"{len(rs):3} {domain}")
            out += [f"    - [{r['pdfs']}pdf] {r['subject']}" for r in rs[:3]]
        out.append("")
        out.append("blocked senders that still produced something:")
        out += [
            f"  {r['domain']} | {r['subject'][:50]} | stays {r['stays']} rentals {r['rentals']}"
            for r in summary["blocked_producing"]
        ]
        out.append("")
        out.append(
            "blocked, produced nothing: "
            + ", ".join(f"{d} ({n})" for d, n in summary["blocked_silent"].most_common())
        )
    return "\n".join(out)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Measure parser coverage over a cached email corpus.")
    p.add_argument("--cache", default="data/email_cache.json", help="Corpus JSON file")
    p.add_argument("--db", default="data/partiu.db", help="SQLite DB with an airports table")
    p.add_argument("--json", default="", help="Write per-email rows to this JSON file")
    p.add_argument("--quiet", action="store_true", help="Per-rule table only")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not Path(args.cache).exists():
        print(f"corpus not found: {args.cache}", file=sys.stderr)
        return 2
    if not Path(args.db).exists():
        print(
            f"database not found: {args.db} (name resolution needs a populated airports table)",
            file=sys.stderr,
        )
        return 2
    os.environ["DB_PATH"] = args.db
    logging.disable(logging.CRITICAL)

    from backend.parsers.builtin_rules import get_builtin_rules

    rules = sorted(get_builtin_rules(), key=lambda r: (-r.priority, r.airline_name))
    rows = [measure(e, rules) for e in load_corpus(args.cache)]
    print(render(summarise(rows), quiet=args.quiet))
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
