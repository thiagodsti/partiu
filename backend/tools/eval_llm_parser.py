"""
CLI evaluation tool: run the LLM parser against the failed email queue.

Usage:
    uv run python -m backend.tools.eval_llm_parser [options]

Options:
    --limit N       Process at most N emails (default: all)
    --model NAME    Ollama model to use (default: from OLLAMA_MODEL env or qwen2.5:1.5b)
    --ollama-url URL  Ollama base URL (default: from OLLAMA_URL env or http://localhost:11434)
    --output FILE   Write full results JSON to FILE (optional)
    --user-id N     Only process failed emails for this user (optional)

Examples:
    # Quick test: first 20 emails against local Ollama
    uv run python -m backend.tools.eval_llm_parser --limit 20

    # Full run with a different model, save results
    uv run python -m backend.tools.eval_llm_parser --model phi3:mini --output results.json

    # Override Ollama URL (e.g. if running in Docker)
    uv run python -m backend.tools.eval_llm_parser --ollama-url http://localhost:11434 --limit 50
"""

from __future__ import annotations

import argparse
import email as _email_lib
import email.utils as _eu
import json
import os
import sys
import time
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Evaluate the LLM flight parser against the failed email queue."
    )
    p.add_argument("--limit", type=int, default=0, help="Max emails to process (0 = all)")
    p.add_argument("--model", default="", help="Ollama model name")
    p.add_argument("--ollama-url", default="", help="Ollama base URL")
    p.add_argument("--output", default="", help="Write JSON results to this file")
    p.add_argument("--user-id", type=int, default=0, help="Only process this user's emails")
    return p.parse_args()


def _load_email(eml_path: str):
    """Load an EmailMessage from a saved .eml file."""
    from backend.parsers.email_connector import (
        EmailMessage,
        decode_header_value,
        get_email_body_and_html,
    )

    raw = Path(eml_path).read_bytes()
    msg = _email_lib.message_from_bytes(raw)

    sender = decode_header_value(msg.get("From", ""))
    subject = decode_header_value(msg.get("Subject", ""))
    message_id = msg.get("Message-ID", f"eval-{Path(eml_path).stem}")
    body, raw_html, pdf_bytes_list = get_email_body_and_html(msg)

    msg_date = None
    date_str = msg.get("Date", "")
    if date_str:
        try:
            msg_date = _eu.parsedate_to_datetime(date_str)
        except Exception:
            pass

    return EmailMessage(
        message_id=message_id,
        sender=sender,
        subject=subject,
        body=body,
        date=msg_date,
        html_body=raw_html,
        pdf_attachments=pdf_bytes_list,
        raw_eml=raw,
    )


def main() -> None:
    args = _parse_args()

    # Override env vars from CLI flags before importing config
    if args.ollama_url:
        os.environ["OLLAMA_URL"] = args.ollama_url
    if args.model:
        os.environ["OLLAMA_MODEL"] = args.model

    # Default Ollama URL for local dev if nothing set at all
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

    print(f"\nLLM Eval — Ollama: {ollama_url}  Model: {model}")
    print("─" * 60)

    # Fetch rows from failed_emails
    with db_conn() as conn:
        if args.user_id:
            rows = conn.execute(
                "SELECT * FROM failed_emails WHERE user_id = ? ORDER BY created_at",
                (args.user_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM failed_emails ORDER BY created_at").fetchall()

    rows = [dict(r) for r in rows]

    if not rows:
        print("No failed emails found.")
        return

    if args.limit and len(rows) > args.limit:
        rows = rows[: args.limit]
        print(f"Processing {len(rows)} emails (limited by --limit {args.limit})")
    else:
        print(f"Processing {len(rows)} emails")

    # --- ping Ollama first ---
    try:
        import urllib.request

        urllib.request.urlopen(ollama_url.rstrip("/") + "/api/tags", timeout=5)
    except Exception as e:
        print(f"\n✗ Cannot reach Ollama at {ollama_url}: {e}")
        print("  Start Ollama or set --ollama-url / OLLAMA_URL correctly.")
        sys.exit(1)

    print()

    results = []
    n_extracted = 0
    n_rejected = 0
    n_failed = 0
    n_no_eml = 0
    latencies: list[float] = []

    for i, row in enumerate(rows, 1):
        eml_path = row.get("eml_path")
        label = f"[{i:3}/{len(rows)}]"

        if not eml_path or not Path(eml_path).exists():
            print(f"{label} SKIP  (no .eml file)  {row['sender'][:50]}")
            n_no_eml += 1
            results.append(
                {
                    "id": row["id"],
                    "sender": row["sender"],
                    "subject": row["subject"],
                    "status": "no_eml",
                    "flights": [],
                }
            )
            continue

        try:
            email_msg = _load_email(eml_path)
        except Exception as e:
            print(f"{label} ERROR (load failed: {e})")
            n_failed += 1
            results.append(
                {
                    "id": row["id"],
                    "sender": row["sender"],
                    "subject": row["subject"],
                    "status": "load_error",
                    "error": str(e),
                    "flights": [],
                }
            )
            continue

        body_text = (email_msg.body or "")[:4000]
        prompt = _PROMPT_USER_TEMPLATE.format(
            sender=email_msg.sender or "",
            subject=email_msg.subject or "",
            body=body_text,
        )

        t0 = time.monotonic()
        raw = _call_ollama(prompt, model, ollama_url)
        elapsed = time.monotonic() - t0
        latencies.append(elapsed)

        if raw is None:
            print(f"{label} ERROR (Ollama timeout/error)  {row['subject'][:50]}")
            n_failed += 1
            results.append(
                {
                    "id": row["id"],
                    "sender": row["sender"],
                    "subject": row["subject"],
                    "status": "ollama_error",
                    "flights": [],
                }
            )
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            print(f"{label} ERROR (bad JSON)  {row['subject'][:50]}")
            n_failed += 1
            results.append(
                {
                    "id": row["id"],
                    "sender": row["sender"],
                    "subject": row["subject"],
                    "status": "json_error",
                    "raw_response": raw[:200],
                    "flights": [],
                }
            )
            continue

        has_flight = data.get("has_flight", False)
        raw_flights = data.get("flights") or []
        booking_ref = data.get("booking_reference") or ""

        valid_flights = []
        for f in raw_flights:
            if isinstance(f, dict) and not f.get("booking_reference") and booking_ref:
                f["booking_reference"] = booking_ref
            if isinstance(f, dict) and _validate_flight(f):
                valid_flights.append(f)

        if has_flight and valid_flights:
            status = "extracted"
            n_extracted += 1
            fn_list = ", ".join(f.get("flight_number", "?") for f in valid_flights)
            print(f"{label} ✓ FLIGHTS  [{fn_list}]  {row['subject'][:45]}  ({elapsed:.1f}s)")
        elif has_flight and not valid_flights:
            # LLM said yes but validation failed
            status = "invalid_data"
            n_failed += 1
            print(
                f"{label} ✗ INVALID  (LLM said flight but data failed validation)  {row['subject'][:40]}  ({elapsed:.1f}s)"
            )
        else:
            status = "rejected"
            n_rejected += 1
            print(f"{label} — rejected  {row['subject'][:52]}  ({elapsed:.1f}s)")

        results.append(
            {
                "id": row["id"],
                "sender": row["sender"],
                "subject": row["subject"],
                "status": status,
                "llm_raw": data,
                "flights": valid_flights,
            }
        )

    # Summary
    avg_lat = sum(latencies) / len(latencies) if latencies else 0
    total_t = sum(latencies)
    print()
    print("─" * 60)
    print(f"Processed : {len(rows)}")
    print(f"  ✓ Flights extracted  : {n_extracted:3}  ({100 * n_extracted / len(rows):.0f}%)")
    print(f"  — Rejected (no data) : {n_rejected:3}  ({100 * n_rejected / len(rows):.0f}%)")
    print(f"  ✗ Errors / invalid   : {n_failed:3}  ({100 * n_failed / len(rows):.0f}%)")
    print(f"  ○ No .eml file       : {n_no_eml:3}  ({100 * n_no_eml / len(rows):.0f}%)")
    print(f"Avg latency : {avg_lat:.1f}s   Total: {total_t:.0f}s")
    print(f"Model       : {model}")

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(results, indent=2, default=str))
        print(f"\nFull results written to: {out_path}")


if __name__ == "__main__":
    main()
