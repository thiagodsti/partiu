"""Tests for backend.tools.eval_llm_corpus (scoring only; Ollama is never called)."""

from unittest.mock import patch


def _row(kind, truth, got):
    return {
        "kind": kind,
        "rule": "AD",
        "subject": "s",
        "truth": sorted(truth),
        "got": sorted(got),
        "exact": len(set(truth) & set(got)),
        "route_only": 0,
        "wrong": 0,
        "error": "",
        "elapsed": 1.0,
    }


class TestRender:
    def test_an_extra_leg_on_another_date_is_not_fully_right(self):
        from backend.tools.eval_llm_corpus import render

        leg = ("AD4849", "VCP", "FLN", "2026-03-02")
        extra = ("AD4849", "VCP", "FLN", "2026-03-03")
        out = render("m", [_row("pos", [leg], [leg, extra])])
        assert "mails all right  0/1" in out
        assert "[pos AD]" in out

    def test_an_exact_mail_is_fully_right(self):
        from backend.tools.eval_llm_corpus import render

        leg = ("AD4849", "VCP", "FLN", "2026-03-02")
        out = render("m", [_row("pos", [leg], [leg])])
        assert "mails all right  1/1" in out


class TestLocalDate:
    def test_utc_date_becomes_the_departure_airports_date(self):
        from backend.tools.eval_llm_corpus import _local_date

        # 22:30 UTC is 01:30 the next day in Doha (UTC+3)
        with patch("backend.airports.timezone._get_airport_timezone", return_value="Asia/Qatar"):
            assert _local_date("2021-12-14 22:30", "DOH") == "2021-12-15"

    def test_unknown_airport_keeps_the_utc_date(self):
        from backend.tools.eval_llm_corpus import _local_date

        with patch("backend.airports.timezone._get_airport_timezone", return_value=None):
            assert _local_date("2021-12-14 22:30", "XXX") == "2021-12-14"
