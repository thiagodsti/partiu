"""
Compare two eval_llm_parser JSON result files and find emails where the
models disagree. Saves the differing cases to a separate JSON file for
prompt improvement.

Usage:
    uv run python -m backend.tools.compare_eval \\
        --a data/eval_1.5b.json \\
        --b data/eval_0.5b.json \\
        --output data/eval_diff.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _score(result: dict) -> int:
    """
    Assign a numeric score to a result:
      2 = extracted valid flights
      1 = LLM said flight but validation failed (invalid_data)
      0 = rejected / no booking
     -1 = error (ollama_error, json_error, load_error, no_eml)
    """
    s = result.get("status", "")
    if s == "extracted":
        return 2
    if s == "invalid_data":
        return 1
    if s == "rejected":
        return 0
    return -1  # errors / no_eml


def main() -> None:
    p = argparse.ArgumentParser(description="Compare two eval result JSON files.")
    p.add_argument("--a", required=True, help="First eval JSON (e.g. eval_1.5b.json)")
    p.add_argument("--b", required=True, help="Second eval JSON (e.g. eval_0.5b.json)")
    p.add_argument("--output", default="data/eval_diff.json", help="Output file for differences")
    args = p.parse_args()

    data_a = json.loads(Path(args.a).read_text())
    data_b = json.loads(Path(args.b).read_text())

    label_a = Path(args.a).stem
    label_b = Path(args.b).stem

    # Index by email id
    index_b = {r["id"]: r for r in data_b}

    diffs = []
    only_in_a = []

    for r_a in data_a:
        eid = r_a["id"]
        r_b = index_b.get(eid)
        if r_b is None:
            only_in_a.append(eid)
            continue

        score_a = _score(r_a)
        score_b = _score(r_b)
        delta = abs(score_a - score_b)

        if delta == 0:
            continue  # no meaningful difference

        diffs.append(
            {
                "id": eid,
                "sender": r_a["sender"],
                "subject": r_a["subject"],
                "delta": delta,
                label_a: {
                    "status": r_a["status"],
                    "score": score_a,
                    "flights": r_a.get("flights", []),
                    "llm_raw": r_a.get("llm_raw"),
                },
                label_b: {
                    "status": r_b["status"],
                    "score": score_b,
                    "flights": r_b.get("flights", []),
                    "llm_raw": r_b.get("llm_raw"),
                },
            }
        )

    # Sort by biggest delta first, then by id
    diffs.sort(key=lambda x: (-x["delta"], x["id"]))

    out = {
        "summary": {
            "total_compared": len(data_a),
            "differing": len(diffs),
            "only_in_a": only_in_a,
        },
        "diffs": diffs,
    }

    out_path = Path(args.output)
    out_path.write_text(json.dumps(out, indent=2, default=str))

    # Print summary to stdout
    print(f"\nComparing  {label_a}  vs  {label_b}")
    print("─" * 60)

    def _counts(data: list[dict]) -> dict:
        c: dict[str, int] = {}
        for r in data:
            c[r["status"]] = c.get(r["status"], 0) + 1
        return c

    ca = _counts(data_a)
    cb = _counts(data_b)
    all_statuses = sorted(set(list(ca) + list(cb)))
    print(f"{'Status':<20} {label_a:>12} {label_b:>12}")
    print("─" * 46)
    for s in all_statuses:
        print(f"  {s:<18} {ca.get(s, 0):>12} {cb.get(s, 0):>12}")
    print()
    print(f"Emails with different outcomes : {len(diffs)}")
    if diffs:
        upgraded = [d for d in diffs if d[label_a]["score"] < d[label_b]["score"]]
        downgraded = [d for d in diffs if d[label_a]["score"] > d[label_b]["score"]]
        print(f"  {label_b} did BETTER  : {len(upgraded)}")
        print(f"  {label_a} did BETTER  : {len(downgraded)}")
        print()
        print("Top differences (for prompt improvement):")
        for d in diffs[:20]:
            print(
                f"  id={d['id']:3}  Δ={d['delta']}  "
                f"{label_a}={d[label_a]['status']:<14} "
                f"{label_b}={d[label_b]['status']:<14} "
                f"  {d['subject'][:45]}"
            )

    print()
    print(f"Full diff saved to: {out_path}")


if __name__ == "__main__":
    main()
