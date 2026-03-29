"""Tests for the email anonymizer."""

from backend.email_anonymizer import _anonymize_html, _anonymize_text, anonymize_email


def _flight_numbers():
    return {"LA1234", "DY456"}


class TestAnonymizeText:
    def test_cpf_replaced(self):
        assert _anonymize_text("CPF: 123.456.789-01", set()) == "CPF: 000.000.000-00"

    def test_email_replaced(self):
        assert _anonymize_text("contact john.doe@airline.com", set()) == "contact test@example.com"

    def test_card_replaced(self):
        assert (
            _anonymize_text("Card 1234 5678 9012 3456 used", set())
            == "Card XXXX XXXX XXXX XXXX used"
        )

    def test_caps_name_replaced(self):
        result = _anonymize_text("Passenger: JOHN DOE", set())
        assert result is not None and "TEST PASSENGER" in result

    def test_flight_number_preserved(self):
        fns = {"LA1234"}
        result = _anonymize_text("Flight LA1234 departs GRU", fns)
        assert result is not None and "LA1234" in result

    def test_iata_code_not_replaced(self):
        # 2-letter codes should not be treated as names
        result = _anonymize_text("Airline: LA SK DY", set())
        assert result is not None and "TEST PASSENGER" not in result

    def test_booking_context_replaced(self):
        result = _anonymize_text("Booking reference: XY23AB", set())
        assert result is not None and "TESTRF" in result

    def test_phone_replaced(self):
        result = _anonymize_text("Phone: +55 11 98765-4321", set())
        assert result is not None and "+1 555 000 0000" in result

    def test_none_returns_none(self):
        assert _anonymize_text(None, set()) is None


class TestAnonymizeHtml:
    def test_preserves_tags(self):
        html = "<p>Hello JOHN DOE</p>"
        result = _anonymize_html(html, set())
        assert result is not None and "<p>" in result
        assert result is not None and "</p>" in result

    def test_anonymizes_text_nodes(self):
        html = "<p>Passenger: JOHN DOE</p>"
        result = _anonymize_html(html, set())
        assert result is not None and "TEST PASSENGER" in result

    def test_email_in_attr_replaced(self):
        html = '<a href="mailto:john@airline.com">Contact</a>'
        result = _anonymize_html(html, set())
        assert result is not None and "john@airline.com" not in result

    def test_none_returns_none(self):
        assert _anonymize_html(None, set()) is None


class _FakeEmail:
    def __init__(self):
        self.message_id = "<msg123@airline.com>"
        self.sender = "JOHN DOE <confirm@airline.com>"
        self.subject = "Your booking LA1234 is confirmed"
        self.date = None
        self.body = (
            "Dear JOHN DOE, your flight LA1234 on 2024-05-10 is confirmed. CPF: 123.456.789-01"
        )
        self.html_body = "<p>Dear JOHN DOE</p><p>Flight LA1234</p>"
        self.pdf_attachments = [b"fakepdf"]


class TestAnonymizeEmail:
    def test_sender_domain_preserved(self):
        result = anonymize_email(_FakeEmail())
        assert "@airline.com" in result["sender"]

    def test_sender_local_part_anonymized(self):
        result = anonymize_email(_FakeEmail())
        assert "JOHN" not in result["sender"]

    def test_subject_preserved(self):
        result = anonymize_email(_FakeEmail())
        # Subject kept as-is (rarely contains PII, important for parser matching)
        assert "LA1234" in result["subject"]

    def test_body_cpf_removed(self):
        result = anonymize_email(_FakeEmail())
        assert "123.456.789-01" not in (result["body"] or "")
        assert "000.000.000-00" in (result["body"] or "")

    def test_body_flight_number_preserved(self):
        result = anonymize_email(_FakeEmail())
        assert "LA1234" in (result["body"] or "")

    def test_pdf_attachments_dropped(self):
        result = anonymize_email(_FakeEmail())
        assert result["pdf_attachments"] == []

    def test_message_id_anonymized(self):
        result = anonymize_email(_FakeEmail())
        assert "<msg123@airline.com>" != result["message_id"]
        assert result["message_id"].endswith("@example.com>")

    def test_html_body_structure_preserved(self):
        result = anonymize_email(_FakeEmail())
        assert "<p>" in (result["html_body"] or "")
