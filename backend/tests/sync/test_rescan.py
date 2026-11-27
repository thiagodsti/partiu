"""
Test: a full sync forgets the processed-mail ledger, and a parser-version
change makes the next sync look back over the whole window and re-parse.

`fetch_emails_imap` is replaced so the tests can see the window the sync asked
for and hand back a mail already in the ledger.
"""

from datetime import UTC, datetime, timedelta

import pytest

from backend.parsers.email_connector import EmailMessage, ImapFetchResult


def _user(test_db):
    import backend.database as db_module

    conn = db_module.get_connection(test_db)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin, created_at) VALUES (1,'t','x',0,?)",
        (now,),
    )
    conn.executemany(
        "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code) VALUES (?,?,?,?)",
        [("ARN", "Stockholm Arlanda", "Stockholm", "SE"), ("LIS", "Lisbon", "Lisbon", "PT")],
    )
    conn.commit()
    from backend.parsers.shared import is_valid_iata, resolve_iata

    is_valid_iata.cache_clear()
    resolve_iata.cache_clear()
    return conn


def _creds():
    return {
        "id": 1,
        "gmail_address": "t@example.com",
        "gmail_app_password": "x",
        "imap_host": "imap.example.com",
        "imap_port": 993,
    }


def _mail(msgid="<r1@example.com>"):
    return EmailMessage(
        message_id=msgid,
        sender="tickets@example.com",
        subject="Electronic ticket receipt",
        body="ELECTRONIC TICKET RECEIPT\nBOOKING REF: RSCAN1\nTP 783 / 10NOV ARN - LIS 19:05 22:35\n",
        date=datetime(2027, 8, 1, tzinfo=UTC),
    )


@pytest.fixture
def fake_imap(monkeypatch):
    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        return ImapFetchResult(success=True, emails=[_mail()], error=None)

    monkeypatch.setattr("backend.sync.pipeline.fetch_emails_imap", fetch)
    return calls


@pytest.mark.usefixtures("test_db")
class TestFullSyncForgetsTheLedger:
    def test_reset_clears_processed_emails(self, test_db):
        from backend.sync.repository import SyncRepository

        conn = _user(test_db)
        repo = SyncRepository()
        repo.mark_email_processed(1, "<old@example.com>")
        repo.reset_last_synced(1)
        assert not repo.is_email_processed(1, "<old@example.com>")
        conn.close()

    def test_a_trashed_booking_comes_back_on_full_sync(self, test_db, fake_imap):
        from backend.sync.pipeline import run_email_sync_for_user
        from backend.sync.repository import SyncRepository

        conn = _user(test_db)
        run_email_sync_for_user(_creds())
        assert conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0] == 1
        # Delete the flight the way the app does now, then a plain sync: the
        # mail is back in the fetch but the ledger no longer blocks it.
        (fid,) = conn.execute("SELECT id FROM flights").fetchone()
        from backend.trash.service import trash_service

        trash_service.trash_flight(fid, 1)
        assert conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0] == 0
        SyncRepository().reset_last_synced(1)
        run_email_sync_for_user(_creds())
        assert conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0] == 1
        conn.close()


@pytest.mark.usefixtures("test_db")
class TestParserVersionRescan:
    def test_first_sync_records_the_version(self, test_db, fake_imap):
        from backend.parsers.builtin_rules import PARSER_VERSION
        from backend.sync.pipeline import run_email_sync_for_user
        from backend.sync.repository import SyncRepository

        conn = _user(test_db)
        run_email_sync_for_user(_creds())
        state = SyncRepository().get_latest_state(1)
        assert state is not None and state.parser_version == PARSER_VERSION
        conn.close()

    def test_an_incremental_sync_looks_back_one_day(self, test_db, fake_imap):
        from backend.sync.pipeline import run_email_sync_for_user

        conn = _user(test_db)
        run_email_sync_for_user(_creds())
        run_email_sync_for_user(_creds())
        since = fake_imap[-1]["since_date"]
        assert datetime.now(UTC) - since < timedelta(days=2)
        conn.close()

    def test_a_version_change_widens_the_window_and_re_reads_the_ledger(self, test_db, fake_imap):
        from backend.sync.pipeline import run_email_sync_for_user
        from backend.sync.repository import SyncRepository

        conn = _user(test_db)
        run_email_sync_for_user(_creds())
        repo = SyncRepository()
        repo.upsert_state(1, parser_version="0")  # as if the last sync ran under an older release
        # The one flight is trashed so the re-read has something to do.
        (fid,) = conn.execute("SELECT id FROM flights").fetchone()
        from backend.trash.service import trash_service

        trash_service.trash_flight(fid, 1)
        repo.mark_email_processed(1, "<r1@example.com>")  # ledger says "done"

        run_email_sync_for_user(_creds())
        since = fake_imap[-1]["since_date"]
        assert datetime.now(UTC) - since > timedelta(days=80), "rescan must use the full lookback"
        assert conn.execute("SELECT COUNT(*) FROM flights").fetchone()[0] == 1, (
            "ledger must be ignored"
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM activity_log WHERE action = 'sync.rescan'"
            ).fetchone()[0]
            == 1
        )
        # And it is a one-off: the next sync is incremental again.
        run_email_sync_for_user(_creds())
        assert datetime.now(UTC) - fake_imap[-1]["since_date"] < timedelta(days=2)
        conn.close()


@pytest.fixture
def llm_flags(monkeypatch):
    """Record the use_llm each sync passes on, while still processing the mail."""
    from backend.sync import pipeline

    seen = []
    real = pipeline._process_emails

    def spy(emails, user_id, *args, **kwargs):
        seen.append(kwargs.get("use_llm"))
        return real(emails, user_id, *args, **kwargs)

    monkeypatch.setattr(pipeline, "_process_emails", spy)
    return seen


@pytest.mark.usefixtures("test_db")
class TestLlmOnIncrementalSyncsOnly:
    """The LLM costs about a minute per unknown mail on a CPU: a sync that reads
    the whole lookback window must not send it hundreds."""

    def test_first_sync_skips_the_llm(self, test_db, fake_imap, llm_flags):
        from backend.sync.pipeline import run_email_sync_for_user

        conn = _user(test_db)
        run_email_sync_for_user(_creds())
        assert llm_flags == [False]
        conn.close()

    def test_incremental_sync_uses_the_llm(self, test_db, fake_imap, llm_flags):
        from backend.sync.pipeline import run_email_sync_for_user

        conn = _user(test_db)
        run_email_sync_for_user(_creds())
        run_email_sync_for_user(_creds())
        assert llm_flags == [False, True]
        conn.close()

    def test_full_sync_skips_the_llm(self, test_db, fake_imap, llm_flags):
        from backend.sync.pipeline import run_email_sync_for_user
        from backend.sync.repository import SyncRepository

        conn = _user(test_db)
        run_email_sync_for_user(_creds())
        SyncRepository().reset_last_synced(1)
        run_email_sync_for_user(_creds())
        assert llm_flags == [False, False]
        conn.close()

    def test_parser_version_rescan_skips_the_llm(self, test_db, fake_imap, llm_flags):
        from backend.sync.pipeline import run_email_sync_for_user
        from backend.sync.repository import SyncRepository

        conn = _user(test_db)
        run_email_sync_for_user(_creds())
        SyncRepository().upsert_state(1, parser_version="0")
        run_email_sync_for_user(_creds())
        assert llm_flags == [False, False]
        conn.close()


@pytest.mark.usefixtures("test_db")
class TestStructuralReadersAreFetched:
    def test_a_booking_com_car_mail_reaches_the_importer_on_sync(self, test_db, monkeypatch):
        """Uploading the .eml bypasses the IMAP fetch filter, so it worked while
        a full sync never downloaded the mail: its subject says "car rental ...
        is confirmed", which matches no flight keyword and no airline sender.
        The sync must hand the structural reader's senders to the filter and
        import the confirmation once the mail is fetched.
        """
        from unittest.mock import patch

        from conftest import load_eml_as_email_message

        from backend.parsers.email_connector import _matches_flight_filter
        from backend.sync import car_rentals_import
        from backend.sync.pipeline import run_email_sync_for_user

        conn = _user(test_db)
        email = load_eml_as_email_message("booking_car_budget_anonymized.eml")
        calls = []

        def fetch(**kwargs):
            calls.append(kwargs)
            return ImapFetchResult(success=True, emails=[email], error=None)

        monkeypatch.setattr("backend.sync.pipeline.fetch_emails_imap", fetch)
        with patch.object(car_rentals_import, "_geocode", return_value=(36.72, -4.42, "ES")):
            run_email_sync_for_user(_creds())

        assert calls
        assert _matches_flight_filter(email.sender, email.subject, calls[0]["sender_patterns"])
        assert conn.execute("SELECT COUNT(*) FROM trip_car_rentals").fetchone()[0] == 1
        conn.close()
