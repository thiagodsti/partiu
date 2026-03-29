"""
CLI verification tool: cross-check imported flights against Ollama's view of the source email.

For each flight that has a cached source email, asks the LLM to extract flight data and
compares the result against what the parser stored. Flags mismatches for human review.

Usage:
    uv run python -m backend.tools.verify_flights_llm [options]

Options:
    --limit N         Check at most N flights (default: all)
    --user-id N       Only check flights for this user (optional)
    --model NAME      Ollama model (default: from OLLAMA_MODEL env or qwen2.5:1.5b)
    --ollama-url URL  Ollama base URL (default: from OLLAMA_URL env or http://localhost:11434)
    --output FILE     Write full JSON results to FILE
    --mismatches-only Only show/save flights with mismatches

Examples:
    # Check all flights that have a cached source email
    uv run python -m backend.tools.verify_flights_llm

    # Quick spot-check: first 20 flights, show mismatches only
    uv run python -m backend.tools.verify_flights_llm --limit 20 --mismatches-only

    # Save full report for review
    uv run python -m backend.tools.verify_flights_llm --output /tmp/flight_audit.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Verify imported flights against the LLM's view of the source email."
    )
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--user-id", type=int, default=0)
    p.add_argument("--model", default="")
    p.add_argument("--ollama-url", default="")
    p.add_argument("--output", default="")
    p.add_argument("--mismatches-only", action="store_true")
    return p.parse_args()


def _airports_match(stored: str, llm: str) -> bool:
    """True if both IATA codes are the same (case-insensitive)."""
    return stored.upper().strip() == llm.upper().strip()


def _fn_normalise(fn: str) -> str:
    return fn.upper().replace(" ", "").replace("\xa0", "").replace("-", "")


def _compare(stored: dict, llm_flights: list[dict]) -> dict:
    """
    Find the LLM flight that best matches the stored flight and return
    a diff dict.  Returns status='no_llm_match' if none found.
    """
    stored_fn = _fn_normalise(stored.get("flight_number") or "")
    stored_dep = (stored.get("departure_airport") or "").upper()
    stored_arr = (stored.get("arrival_airport") or "").upper()

    # Try to find a matching flight by number first, then by route
    best = None
    for f in llm_flights:
        llm_fn = _fn_normalise(f.get("flight_number") or "")
        llm_dep = (f.get("dep_airport") or "").upper()
        llm_arr = (f.get("arr_airport") or "").upper()
        if llm_fn == stored_fn:
            best = f
            break
        if llm_dep == stored_dep and llm_arr == stored_arr and not best:
            best = f

    if not best:
        return {
            "status": "no_llm_match",
            "mismatches": ["LLM found no matching flight number or route"],
        }

    mismatches = []
    llm_fn = _fn_normalise(best.get("flight_number") or "")
    llm_dep = (best.get("dep_airport") or "").upper()
    llm_arr = (best.get("arr_airport") or "").upper()

    if stored_fn and llm_fn and stored_fn != llm_fn:
        mismatches.append(f"flight_number: stored={stored_fn}  llm={llm_fn}")
    if llm_dep and not _airports_match(stored_dep, llm_dep):
        mismatches.append(f"dep_airport: stored={stored_dep}  llm={llm_dep}")
    if llm_arr and not _airports_match(stored_arr, llm_arr):
        mismatches.append(f"arr_airport: stored={stored_arr}  llm={llm_arr}")

    # Booking reference check (only if LLM has one)
    stored_ref = (stored.get("booking_reference") or "").upper().strip()
    llm_ref = (best.get("booking_reference") or "").upper().strip()
    if stored_ref and llm_ref and stored_ref != llm_ref:
        mismatches.append(f"booking_ref: stored={stored_ref}  llm={llm_ref}")

    return {
        "status": "mismatch" if mismatches else "ok",
        "mismatches": mismatches,
        "llm_flight": best,
    }


def main() -> None:
    args = _parse_args()

    if args.ollama_url:
        os.environ["OLLAMA_URL"] = args.ollama_url
    if args.model:
        os.environ["OLLAMA_MODEL"] = args.model
    if not os.environ.get("OLLAMA_URL"):
        os.environ["OLLAMA_URL"] = "http://localhost:11434"

    from backend.config import settings
    from backend.database import db_conn
    from backend.llm_parser import (
        _PROMPT_USER_TEMPLATE,
        _call_ollama,
        _validate_flight,
    )

    model = settings.OLLAMA_MODEL
    ollama_url = settings.OLLAMA_URL

    print(f"\nFlight Verifier — Ollama: {ollama_url}  Model: {model}")
    print("─" * 60)

    # --- ping Ollama ---
    try:
        import urllib.request

        urllib.request.urlopen(ollama_url.rstrip("/") + "/api/tags", timeout=5)
    except Exception as e:
        print(f"\n✗ Cannot reach Ollama at {ollama_url}: {e}")
        sys.exit(1)

    # --- load email cache ---
    cache_path = Path(settings.DB_PATH).parent / "email_cache.json"
    if not cache_path.exists():
        print("✗ Email cache not found. Run a sync first.")
        sys.exit(1)

    with open(cache_path, encoding="utf-8") as f:
        cache_list = json.load(f)
    cache: dict[str, dict] = {e["message_id"]: e for e in cache_list}
    print(f"Cache: {len(cache)} emails loaded")

    # --- load flights ---
    with db_conn() as conn:
        if args.user_id:
            rows = conn.execute(
                """SELECT id, flight_number, departure_airport, arrival_airport,
                          booking_reference, email_message_id, email_subject, user_id
                   FROM flights WHERE is_manually_added = 0 AND user_id = ?
                   ORDER BY departure_datetime""",
                (args.user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, flight_number, departure_airport, arrival_airport,
                          booking_reference, email_message_id, email_subject, user_id
                   FROM flights WHERE is_manually_added = 0
                   ORDER BY departure_datetime"""
            ).fetchall()

    flights = [dict(r) for r in rows]

    # Only flights whose source email is in the cache
    verifiable = [f for f in flights if f.get("email_message_id") in cache]
    skipped = len(flights) - len(verifiable)

    if not verifiable:
        print("No flights with cached source emails found.")
        sys.exit(0)

    if args.limit and len(verifiable) > args.limit:
        verifiable = verifiable[: args.limit]

    print(
        f"Flights: {len(flights)} total, {len(verifiable)} verifiable, {skipped} skipped (email not cached)"
    )
    if args.limit:
        print(f"Checking first {len(verifiable)} (--limit {args.limit})")
    print()

    results = []
    n_ok = n_mismatch = n_no_match = n_no_llm = 0
    latencies: list[float] = []

    for i, flight in enumerate(verifiable, 1):
        fn = flight["flight_number"]
        dep = flight["departure_airport"]
        arr = flight["arrival_airport"]
        label = f"[{i:3}/{len(verifiable)}]"
        email_entry = cache[flight["email_message_id"]]

        body_text = (email_entry.get("body") or "")[:4000]
        prompt = _PROMPT_USER_TEMPLATE.format(
            sender=email_entry.get("sender") or "",
            subject=email_entry.get("subject") or "",
            body=body_text,
        )

        t0 = time.monotonic()
        raw = _call_ollama(prompt, model, ollama_url)
        elapsed = time.monotonic() - t0
        latencies.append(elapsed)

        if raw is None:
            print(f"{label} ERROR  {fn} {dep}→{arr}")
            n_no_llm += 1
            results.append({**flight, "verify_status": "ollama_error", "mismatches": []})
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            n_no_llm += 1
            results.append({**flight, "verify_status": "json_error", "mismatches": []})
            continue

        llm_flights_raw = data.get("flights") or []
        booking_ref = data.get("booking_reference") or ""
        llm_flights = []
        for f in llm_flights_raw:
            if not isinstance(f, dict):
                continue
            if not f.get("booking_reference") and booking_ref:
                f["booking_reference"] = booking_ref
            if _validate_flight(f):
                llm_flights.append(f)

        if not data.get("has_flight") or not llm_flights:
            # LLM says no flight — might be a non-booking email (check-in reminder etc.)
            print(f"{label} ○ LLM no flight  {fn} {dep}→{arr}  ({elapsed:.1f}s)")
            n_no_match += 1
            results.append({**flight, "verify_status": "llm_no_flight", "mismatches": []})
            continue

        diff = _compare(flight, llm_flights)
        status = diff["status"]
        mismatches = diff["mismatches"]

        if status == "ok":
            if not args.mismatches_only:
                print(f"{label} ✓  {fn} {dep}→{arr}  ({elapsed:.1f}s)")
            n_ok += 1
        elif status == "mismatch":
            print(f"{label} ✗ MISMATCH  {fn} {dep}→{arr}  ({elapsed:.1f}s)")
            for m in mismatches:
                print(f"       {m}")
            n_mismatch += 1
        else:  # no_llm_match
            print(f"{label} ? NO MATCH  {fn} {dep}→{arr}  ({elapsed:.1f}s)")
            n_no_match += 1

        results.append(
            {
                **flight,
                "verify_status": status,
                "mismatches": mismatches,
                "llm_raw": data,
            }
        )

    # Summary
    avg_lat = sum(latencies) / len(latencies) if latencies else 0
    print()
    print("─" * 60)
    print(f"Checked   : {len(verifiable)}")
    print(f"  ✓ OK               : {n_ok:3}  ({100 * n_ok / len(verifiable):.0f}%)")
    print(f"  ✗ Mismatches       : {n_mismatch:3}  ({100 * n_mismatch / len(verifiable):.0f}%)")
    print(f"  ? LLM no match     : {n_no_match:3}  ({100 * n_no_match / len(verifiable):.0f}%)")
    print(f"  ! Errors           : {n_no_llm:3}  ({100 * n_no_llm / len(verifiable):.0f}%)")
    print(f"Avg latency : {avg_lat:.1f}s")

    if args.output:
        out_path = Path(args.output)
        if args.mismatches_only:
            to_save = [r for r in results if r.get("verify_status") not in ("ok", "llm_no_flight")]
        else:
            to_save = results
        out_path.write_text(json.dumps(to_save, indent=2, default=str))
        print(f"\nResults written to: {out_path}")

    if n_mismatch:
        print(f"\n⚠  {n_mismatch} flight(s) have mismatches — review with --output to get details.")


if __name__ == "__main__":
    main()
