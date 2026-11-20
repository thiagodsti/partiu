"""
Test: fetch_emails_imap downloads only the headers of mail that is not about
flights, and reports progress in steps instead of after every email.

`connect_imap` is replaced by a fake server holding a few raw messages.
"""

import email

import pytest

from backend.parsers import email_connector
from backend.parsers.email_connector import fetch_emails_imap


def _raw(n: int, sender: str, subject: str) -> bytes:
    return (
        f"From: {sender}\r\nSubject: {subject}\r\nMessage-ID: <m{n}@example.com>\r\n"
        f"Date: Mon, 02 Nov 2026 10:00:00 +0000\r\n\r\nBody {n}\r\n"
    ).encode()


class FakeImap:
    def __init__(self, messages: dict[bytes, bytes]):
        self.messages = messages
        self.fetches: list[tuple[bytes, str]] = []

    def select(self, folder, readonly=False):
        return "OK", [str(len(self.messages)).encode()]

    def search(self, charset, criteria):
        return "OK", [b" ".join(self.messages)]

    def fetch(self, message_set: str, parts):
        msg_id = message_set.encode()
        self.fetches.append((msg_id, parts))
        raw = self.messages[msg_id]
        if "HEADER.FIELDS" in parts:
            msg = email.message_from_bytes(raw)
            data = f"From: {msg['From']}\r\nSubject: {msg['Subject']}\r\n\r\n".encode()
        else:
            data = raw
        return "OK", [(msg_id + b" (" + parts.encode() + b")", data), b")"]

    def logout(self):
        return "BYE", []


@pytest.fixture
def server(monkeypatch):
    messages = {
        b"1": _raw(1, "news@shop.example", "Black Friday deals"),
        b"2": _raw(2, "noreply@airline.example", "Your booking confirmation"),
        b"3": _raw(3, "friend@example.com", "Dinner on Friday?"),
    }
    fake = FakeImap(messages)
    monkeypatch.setattr(email_connector, "connect_imap", lambda *a, **k: fake)
    return fake


def _fetch(**kwargs):
    return fetch_emails_imap(
        host="imap.example.com", port=993, username="u", password="p", **kwargs
    )


def test_only_matching_mail_is_downloaded_whole(server):
    result = _fetch()

    assert result.success
    assert [m.message_id for m in result.emails] == ["<m2@example.com>"]
    assert result.emails[0].body.strip() == "Body 2"
    full = [msg_id for msg_id, parts in server.fetches if parts == "(RFC822)"]
    assert full == [b"2"]
    headers = [msg_id for msg_id, parts in server.fetches if "HEADER.FIELDS" in parts]
    assert sorted(headers) == [b"1", b"2", b"3"]


def test_sender_pattern_match_is_downloaded(server):
    result = _fetch(sender_patterns=[r"@shop\.example"])

    assert sorted(m.message_id for m in result.emails) == ["<m1@example.com>", "<m2@example.com>"]


def test_progress_is_reported_in_steps_and_at_the_end(server):
    for n in range(4, 61):
        server.messages[str(n).encode()] = _raw(n, "news@shop.example", "Weekly news")
    reports = []

    _fetch(progress_callback=lambda fetched, total: reports.append((fetched, total)))

    assert reports == [(0, 60), (25, 60), (50, 60), (60, 60)]
