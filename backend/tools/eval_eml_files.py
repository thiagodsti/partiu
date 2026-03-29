"""
Run two Ollama models against a list of .eml files and compare results.

Usage:
    uv run python -m backend.tools.eval_eml_files [eml_files...] [options]

Options:
    --models A,B    Comma-separated model names (default: qwen2.5:0.5b,qwen2.5:1.5b)
    --ollama-url    Ollama base URL (default: http://localhost:11434)
    --output FILE   Write JSON results to FILE (optional)

Examples:
    uv run python -m backend.tools.eval_eml_files ~/Downloads/*.eml
    uv run python -m backend.tools.eval_eml_files ~/Downloads/*.eml --output data/eml_compare.json
"""

from __future__ import annotations

import argparse
import email as _email_lib
import email.utils as _eu
import json
import os
import time
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate two models against .eml files.")
    p.add_argument("eml_files", nargs="+", help=".eml files to process")
    p.add_argument(
        "--models", default="qwen2.5:0.5b,qwen2.5:1.5b", help="Comma-separated model names"
    )
    p.add_argument("--ollama-url", default="", help="Ollama base URL")
    p.add_argument("--output", default="", help="Write JSON results to this file")
    return p.parse_args()


def _load_email(eml_path: str):
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


def _run_model(email_msg, model: str, ollama_url: str) -> dict:
    from datetime import UTC, datetime

    from bs4 import BeautifulSoup

    from backend.llm_parser import _PROMPT_USER_TEMPLATE, _call_ollama, _validate_flight

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    body_text = email_msg.body or ""
    if not body_text and email_msg.html_body:
        body_text = BeautifulSoup(email_msg.html_body, "lxml").get_text(separator="\n")
    body_text = body_text[:4000]
    prompt = _PROMPT_USER_TEMPLATE.format(
        today=today,
        sender=email_msg.sender or "",
        subject=email_msg.subject or "",
        body=body_text,
    )

    t0 = time.monotonic()
    raw = _call_ollama(prompt, model, ollama_url)
    elapsed = time.monotonic() - t0

    if raw is None:
        return {"status": "ollama_error", "flights": [], "elapsed": elapsed}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "status": "json_error",
            "raw_response": raw[:200],
            "flights": [],
            "elapsed": elapsed,
        }

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
    elif has_flight and not valid_flights:
        status = "invalid_data"
    else:
        status = "rejected"

    return {"status": status, "llm_raw": data, "flights": valid_flights, "elapsed": elapsed}


def main() -> None:
    args = _parse_args()

    if args.ollama_url:
        os.environ["OLLAMA_URL"] = args.ollama_url
    if not os.environ.get("OLLAMA_URL"):
        os.environ["OLLAMA_URL"] = "http://localhost:11434"

    ollama_url = os.environ["OLLAMA_URL"]
    models = [m.strip() for m in args.models.split(",")]
    eml_files = [p for p in args.eml_files if Path(p).exists()]

    print(f"\nModels   : {' vs '.join(models)}")
    print(f"Emails   : {len(eml_files)}")
    print(f"Ollama   : {ollama_url}")
    print("─" * 70)

    results = []

    for eml_path in eml_files:
        name = Path(eml_path).name
        try:
            email_msg = _load_email(eml_path)
        except Exception as e:
            print(f"ERROR loading {name}: {e}")
            continue

        print(f"\n{name}")
        print(f"  Subject : {email_msg.subject}")
        print(f"  From    : {email_msg.sender}")

        row: dict = {
            "file": name,
            "subject": email_msg.subject,
            "sender": email_msg.sender,
            "models": {},
        }

        for model in models:
            result = _run_model(email_msg, model, ollama_url)
            row["models"][model] = result
            status = result["status"]
            elapsed = result.get("elapsed", 0)

            if status == "extracted":
                fn_list = ", ".join(f.get("flight_number") or "?" for f in result["flights"])
                airports = ", ".join(
                    f"{f.get('dep_airport')}→{f.get('arr_airport')}" for f in result["flights"]
                )
                print(f"  [{model}] ✓ FLIGHTS  [{fn_list}]  {airports}  ({elapsed:.1f}s)")
            elif status == "invalid_data":
                print(
                    f"  [{model}] ✗ INVALID  (found flight but failed validation)  ({elapsed:.1f}s)"
                )
                # Show what the model returned for debugging
                raw_flights = result.get("llm_raw", {}).get("flights") or []
                for f in raw_flights[:2]:
                    print(f"           → {f}")
            elif status == "rejected":
                print(f"  [{model}] — rejected  ({elapsed:.1f}s)")
            else:
                print(f"  [{model}] ✗ {status}  ({elapsed:.1f}s)")

        results.append(row)

    # Summary
    print("\n" + "─" * 70)
    print(f"{'File':<45} " + "  ".join(f"{m:<20}" for m in models))
    print("─" * 70)
    for row in results:
        statuses = [row["models"].get(m, {}).get("status", "?") for m in models]
        agree = "✓ agree" if len(set(statuses)) == 1 else "✗ differ"
        print(f"  {row['file'][:43]:<43} " + "  ".join(f"{s:<20}" for s in statuses) + f"  {agree}")

    if args.output:
        Path(args.output).write_text(json.dumps(results, indent=2, default=str))
        print(f"\nFull results written to: {args.output}")


if __name__ == "__main__":
    main()
