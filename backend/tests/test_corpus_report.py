"""
Test: the corpus coverage report (backend/tools/corpus_report.py).

The real corpus is local and gitignored, so these tests drive the tool with
in-memory emails and hand-built rows. What they pin: a row reports the tier
that produced its legs, the aggregation puts a matched-but-silent mail on its
rule's "nothing" list, and the rendered text carries the headline numbers.
"""

import json
from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture

from backend.tools import corpus_report


def _row(**overrides):
    base = {
        "domain": "example.com",
        "subject": "s",
        "blocked": False,
        "rule": None,
        "rule_legs": 0,
        "gds_legs": 0,
        "valid_legs": 0,
        "stays": 0,
        "rentals": 0,
        "boarding_passes": 0,
        "cancellations": 0,
        "pdfs": 0,
        "error": "",
        "legs": [],
    }
    base.update(overrides)
    return base


class TestSummarise:
    def test_counts_and_per_rule_table(self):
        rows = [
            _row(rule="TP", rule_legs=2, valid_legs=2, subject="receipt"),
            _row(rule="TP", subject="upgrade offer"),
            _row(rule="LA", boarding_passes=1, subject="cartão de embarque"),
            _row(domain="shop.example", subject="order"),
            _row(domain="airbnb.com", blocked=True, stays=1),
            _row(domain="tripit.com", blocked=True),
        ]
        s = corpus_report.summarise(rows)
        assert (s["total"], s["blocked"], s["rule_matched"]) == (6, 2, 3)
        assert (s["emails_with_flights"], s["legs"], s["stays"]) == (1, 2, 1)
        assert s["per_rule"]["TP"]["with_flights"] == 1
        assert [r["subject"] for r in s["per_rule"]["TP"]["nothing"]] == ["upgrade offer"]
        # A boarding-pass enrichment counts as having produced something
        assert s["per_rule"]["LA"]["nothing"] == []
        assert list(s["unmatched_by_domain"]) == ["shop.example"]
        assert [r["domain"] for r in s["blocked_producing"]] == ["airbnb.com"]
        assert dict(s["blocked_silent"]) == {"tripit.com": 1}

    def test_errors_are_listed(self):
        s = corpus_report.summarise([_row(error="ValueError: boom")])
        assert len(s["errors"]) == 1


class TestRender:
    def test_headline_and_table(self):
        s = corpus_report.summarise(
            [_row(rule="TP", valid_legs=2), _row(rule="TP", subject="silent one")]
        )
        text = corpus_report.render(s)
        assert "emails with flights 1  legs 2" in text
        assert "TP " in text and "silent one" in text

    def test_quiet_drops_the_lists(self):
        s = corpus_report.summarise([_row(rule="TP", subject="silent one")])
        assert "silent one" not in corpus_report.render(s, quiet=True)


class TestMeasure:
    def test_reports_the_tier_that_read_the_mail(self, seeded_airports_db):
        from backend.parsers.builtin_rules import get_builtin_rules

        rules = sorted(get_builtin_rules(), key=lambda r: (-r.priority, r.airline_name))
        row = corpus_report.measure(
            load_anonymized_fixture("tap_eticket_columnar_anonymized.json"), rules
        )
        assert row["rule"] == "TP"
        assert row["valid_legs"] == 2
        assert row["gds_legs"] == 2
        assert [leg[0] for leg in row["legs"]] == ["TP783", "TP780"]
        assert row["error"] == ""

    def test_a_raising_extractor_is_reported_not_raised(self, seeded_airports_db, monkeypatch):
        from backend.parsers import schema_org

        def boom(_):
            raise RuntimeError("bad markup")

        monkeypatch.setattr(schema_org, "extract_lodging_reservations", boom)
        from backend.parsers.email_connector import EmailMessage

        msg = EmailMessage(
            message_id="x",
            sender="a@example.com",
            subject="s",
            body="",
            date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        row = corpus_report.measure(msg, [])
        assert row["error"].startswith("RuntimeError")


class TestCli:
    def test_end_to_end_on_a_tiny_corpus(self, tmp_path, seeded_airports_db, capsys):
        fixture = json.loads(
            (
                corpus_report.Path(__file__).parent
                / "fixtures"
                / "tap_eticket_columnar_anonymized.json"
            ).read_text()
        )
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps([fixture]))
        rc = corpus_report.main(
            [
                "--cache",
                str(cache),
                "--db",
                seeded_airports_db,
                "--json",
                str(tmp_path / "rows.json"),
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "emails with flights 1  legs 2" in out
        assert json.loads((tmp_path / "rows.json").read_text())[0]["rule"] == "TP"

    def test_missing_corpus_is_a_clean_exit(self, tmp_path, capsys):
        assert corpus_report.main(["--cache", str(tmp_path / "nope.json")]) == 2
        assert "corpus not found" in capsys.readouterr().err
