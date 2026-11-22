"""
Score the LLM fallback against the rule parsers over a cached email corpus.

Usage:
    uv run python -m backend.tools.eval_llm_corpus --model qwen3:4b-instruct [options]

Options:
    --cache FILE      Corpus JSON (default: data/email_cache.json), as for corpus_report.
    --db FILE         SQLite DB with a populated airports table (default: data/partiu.db).
    --model NAME      Ollama model to score (required).
    --ollama-url URL  Ollama base URL (default: OLLAMA_URL, else http://localhost:11434).
    --per-rule N      Mails with legs to take per airline rule (default: 2).
    --negatives N     Mails without anything travel-shaped to add (default: 15).
    --seed N          Sampling seed (default: 42), so two runs see the same mails.
    --json FILE       Also write every per-mail row, raw model answer included.

Ground truth is what the airline rules extract today (corpus_report's measure(),
after timezones and validation). That makes this a proxy: in production the LLM
only sees mails no rule could read, but those have no answer key, and a model
that cannot read a known Azul confirmation will not read an unknown airline's.

A leg counts as right only when flight number, both airports and departure date
all match. "Route right, date wrong" and "wrong legs" (a route the truth does not
have, an inverted one included) are reported apart, because a wrong leg is worse
than a missing one: it lands in the trip looking ordinary. The negatives are
mails with no legs, stays or rentals; a reminder about a real trip can still
make the model report real flights there, so read those rows before calling
them hallucinations.

The prompt, schema, body builder, validator and Ollama call are production's,
so a prompt change can be measured before it ships. On a CPU-only box expect
roughly a minute per mail for a 4B model.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from pathlib import Path


def _leg_key(fn, dep, arr, date) -> tuple[str, str, str, str]:
    fn = (fn or "").upper().replace(" ", "").replace("\xa0", "").replace("-", "")
    return (fn, (dep or "").upper(), (arr or "").upper(), str(date or "")[:10])


def _local_date(utc_text: str, airport: str) -> str:
    """The departure's calendar date at its airport.

    measure() reports legs after apply_airport_timezones, in UTC, while a mail
    (and so the model) gives local times: a 01:30 departure from Doha is the
    previous day in UTC. Compare like with like.
    """
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from backend.airports.timezone import _get_airport_timezone

    tz = _get_airport_timezone(airport) if airport else None
    try:
        dt = datetime.fromisoformat(utc_text)
    except ValueError:
        return utc_text[:10]
    if not tz:
        return utc_text[:10]
    return dt.replace(tzinfo=UTC).astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")


def pick_sample(rows: list[dict], per_rule: int, negatives: int, seed: int) -> list[dict]:
    """A few mails per airline rule, so no single template dominates, plus negatives."""
    rng = random.Random(seed)
    by_rule: dict[str, list[dict]] = {}
    for r in rows:
        if r["valid_legs"] and not r["blocked"]:
            by_rule.setdefault(str(r["rule"]), []).append(r)
    sample = []
    for rule in sorted(by_rule):
        group = by_rule[rule][:]
        rng.shuffle(group)
        sample += [dict(r, kind="pos") for r in group[:per_rule]]
    neg = [
        r
        for r in rows
        if not r["valid_legs"] and not r["blocked"] and not r["stays"] and not r["rentals"]
    ]
    sample += [dict(r, kind="neg") for r in rng.sample(neg, min(negatives, len(neg)))]
    return sample


def score(email_msg, row: dict, model: str, ollama_url: str, timeout: int) -> dict:
    """Run the production prompt over one mail and compare with the rule legs."""
    from backend.integrations.llm import parser as llm

    body = llm.build_llm_body(email_msg)
    prompt = llm._PROMPT_USER_TEMPLATE.format(
        today=email_msg.date.strftime("%Y-%m-%d") if email_msg.date else "",
        sender=email_msg.sender or "",
        subject=email_msg.subject or "",
        body=body,
    )
    mail_text = f"{email_msg.subject or ''}\n{body}"
    t0 = time.monotonic()
    raw = llm._call_ollama(prompt, model, ollama_url, timeout=timeout)
    elapsed = time.monotonic() - t0
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {}
    got = set()
    if data.get("has_flight"):
        ref = data.get("booking_reference") or ""
        for f in data.get("flights") or []:
            if not isinstance(f, dict):
                continue
            if not f.get("booking_reference") and ref:
                f["booking_reference"] = ref
            llm._prefix_flight_number(f)
            if llm._validate_flight(f) and llm._flight_number_in_text(f, mail_text):
                got.add(
                    _leg_key(
                        f.get("flight_number"),
                        f.get("dep_airport"),
                        f.get("arr_airport"),
                        f.get("dep_datetime") or f.get("dep_date"),
                    )
                )
    truth = (
        {_leg_key(fn, dep, arr, _local_date(when, dep)) for fn, dep, arr, when in row["legs"]}
        if row["kind"] == "pos"
        else set()
    )
    truth_routes = {t[:3] for t in truth}
    exact = len(truth & got)
    return {
        "kind": row["kind"],
        "rule": row["rule"],
        "subject": row["subject"],
        "truth": sorted(truth),
        "got": sorted(got),
        "exact": exact,
        "route_only": len({g[:3] for g in got} & truth_routes) - exact,
        "wrong": len([g for g in got if g[:3] not in truth_routes]),
        "error": "" if raw is not None else "ollama request failed",
        "elapsed": round(elapsed, 1),
        "raw": (raw or "")[:2000],
    }


def render(model: str, results: list[dict]) -> str:
    pos = [r for r in results if r["kind"] == "pos"]
    neg = [r for r in results if r["kind"] == "neg"]
    legs = sum(len(r["truth"]) for r in pos)
    exact = sum(r["exact"] for r in pos)
    full = sum(1 for r in pos if r["got"] == r["truth"])
    times = sorted(r["elapsed"] for r in results) or [0]
    lines = [
        f"model {model}",
        f"  legs right       {exact}/{legs}" + (f" ({100 * exact // legs}%)" if legs else ""),
        f"  route, date off  {sum(r['route_only'] for r in pos)}",
        f"  wrong legs       {sum(r['wrong'] for r in pos)}",
        f"  mails all right  {full}/{len(pos)}",
        f"  negatives w/ leg {sum(1 for r in neg if r['got'])}/{len(neg)}",
        f"  failed requests  {sum(1 for r in results if r['error'])}",
        f"  seconds/mail     median {times[len(times) // 2]}, max {times[-1]}",
        "",
        "Mails not fully right:",
    ]
    for r in results:
        bad = r["got"] if r["kind"] == "neg" else r["got"] != r["truth"]
        if bad:
            lines.append(f"  [{r['kind']} {r['rule']}] {r['subject'][:60]} {r['error']}")
            lines.append(f"      want {r['truth']}")
            lines.append(f"      got  {r['got']}")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Score the LLM fallback against the rule parsers.")
    p.add_argument("--cache", default="data/email_cache.json", help="Corpus JSON file")
    p.add_argument("--db", default="data/partiu.db", help="SQLite DB with an airports table")
    p.add_argument("--model", required=True, help="Ollama model name")
    p.add_argument("--ollama-url", default="", help="Ollama base URL")
    p.add_argument("--per-rule", type=int, default=2, help="Mails with legs per airline rule")
    p.add_argument("--negatives", type=int, default=15, help="Mails without legs to add")
    p.add_argument("--seed", type=int, default=42, help="Sampling seed")
    p.add_argument("--timeout", type=int, default=600, help="Seconds per Ollama request")
    p.add_argument("--json", default="", help="Write per-mail rows to this JSON file")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    for path, what in ((args.cache, "corpus"), (args.db, "database")):
        if not Path(path).exists():
            print(f"{what} not found: {path}", file=sys.stderr)
            return 2
    os.environ["DB_PATH"] = args.db
    logging.disable(logging.CRITICAL)
    ollama_url = args.ollama_url or os.environ.get("OLLAMA_URL") or "http://localhost:11434"

    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.tools.corpus_report import load_corpus, measure

    rules = sorted(get_builtin_rules(), key=lambda r: (-r.priority, r.airline_name))
    emails = load_corpus(args.cache)
    rows = []
    for e in emails:
        row = measure(e, rules)
        row["message_id"] = e.message_id
        rows.append(row)
    by_id = {e.message_id: e for e in emails}
    sample = pick_sample(rows, args.per_rule, args.negatives, args.seed)

    results = []
    for i, row in enumerate(sample, 1):
        r = score(by_id[row["message_id"]], row, args.model, ollama_url, args.timeout)
        results.append(r)
        print(
            f"[{i}/{len(sample)}] {r['kind']} {str(r['rule']):8} right {r['exact']}/"
            f"{len(r['truth'])} wrong {r['wrong']} {r['elapsed']}s {r['error']}",
            file=sys.stderr,
            flush=True,
        )
    print(render(args.model, results))
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
