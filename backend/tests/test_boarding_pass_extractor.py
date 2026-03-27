"""Tests for the boarding pass extractor module."""

import base64

import pytest
from conftest import load_eml_as_email_message

from backend.boarding_pass_extractor import (
    extract_from_html,
    is_checkin_email,
)
from backend.parsers.email_connector import EmailMessage


def _make_email(subject="", body="", html_body="", pdf_attachments=None):
    return EmailMessage(
        message_id="test-msg-id",
        sender="airline@example.com",
        subject=subject,
        body=body,
        date=None,
        html_body=html_body,
        pdf_attachments=pdf_attachments or [],
    )


# ---------------------------------------------------------------------------
# is_checkin_email
# ---------------------------------------------------------------------------


class TestIsCheckinEmail:
    def test_boarding_pass_in_subject(self):
        msg = _make_email(subject="Your boarding pass for LA8094")
        assert is_checkin_email(msg) is True

    def test_check_in_confirmed_in_subject(self):
        msg = _make_email(subject="Check-in confirmed")
        assert is_checkin_email(msg) is True

    def test_passe_de_embarque_in_subject(self):
        msg = _make_email(subject="Seu passe de embarque — LA8094")
        assert is_checkin_email(msg) is True

    def test_ready_to_fly_in_subject(self):
        msg = _make_email(subject="Ready to fly! LA1234")
        assert is_checkin_email(msg) is True

    def test_booking_confirmation_not_checkin(self):
        msg = _make_email(subject="Your booking confirmation LA8094")
        assert is_checkin_email(msg) is False

    def test_unrelated_subject_not_checkin(self):
        msg = _make_email(subject="Your monthly bank statement")
        assert is_checkin_email(msg) is False

    def test_boarding_pass_body_with_pdf(self):
        msg = _make_email(
            subject="Flight confirmation",
            body="Please find your boarding pass attached.",
            pdf_attachments=[b"%PDF-1.4 fake"],
        )
        assert is_checkin_email(msg) is True

    def test_boarding_pass_body_without_pdf_not_triggered(self):
        msg = _make_email(
            subject="Flight confirmation",
            body="Please find your boarding pass attached.",
        )
        # No PDF attached, so should NOT trigger
        assert is_checkin_email(msg) is False

    def test_case_insensitive_subject(self):
        msg = _make_email(subject="MOBILE BOARDING PASS")
        assert is_checkin_email(msg) is True

    # ------------------------------------------------------------------
    # Purchase / booking confirmation emails must NOT be flagged
    # ------------------------------------------------------------------

    def test_purchase_confirmation_with_cartao_de_embarque_in_body_not_checkin(self):
        """LATAM purchase emails mention 'cartão de embarque' as a tip, not as the pass itself."""
        msg = _make_email(
            subject="Você já comprou sua viagem a São Paulo",
            body="faça check-in e obtenha seu cartão de embarque digital.",
            pdf_attachments=[b"%PDF-1.4 fake comprovante"],
        )
        assert is_checkin_email(msg) is False

    def test_comprovante_subject_not_checkin(self):
        msg = _make_email(subject="Comprovante de viagem LA1234")
        assert is_checkin_email(msg) is False

    def test_booking_confirmation_subject_not_checkin_even_with_boarding_pass_body(self):
        msg = _make_email(
            subject="Your booking confirmation",
            body="You will receive your boarding pass soon.",
            pdf_attachments=[b"%PDF-1.4 fake"],
        )
        assert is_checkin_email(msg) is False

    def test_itinerary_subject_not_checkin(self):
        msg = _make_email(
            subject="Your itinerary for LA8094",
            body="boarding pass will be issued at check-in.",
            pdf_attachments=[b"%PDF-1.4 fake"],
        )
        assert is_checkin_email(msg) is False

    def test_cartao_de_embarque_body_no_pdf_not_checkin(self):
        """Body-only match (no PDF) should not trigger."""
        msg = _make_email(
            subject="Preparing for your trip",
            body="Lembre-se de obter seu cartão de embarque.",
        )
        assert is_checkin_email(msg) is False

    def test_passe_de_embarque_body_with_pdf_still_triggers(self):
        """'passe de embarque' in body + PDF is a valid boarding pass indicator."""
        msg = _make_email(
            subject="Prepare-se para voar",
            body="Seu passe de embarque está em anexo.",
            pdf_attachments=[b"%PDF-1.4 fake"],
        )
        assert is_checkin_email(msg) is True


# ---------------------------------------------------------------------------
# extract_from_html
# ---------------------------------------------------------------------------

# Minimal valid 1×1 PNG bytes
_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_b64_img_tag(img_bytes: bytes, alt: str = "", extra: str = "") -> str:
    b64 = base64.b64encode(img_bytes).decode()
    return f'<img src="data:image/png;base64,{b64}" alt="{alt}" {extra}/>'


class TestExtractFromHtml:
    def test_empty_html_returns_empty(self):
        assert extract_from_html("") == []

    def test_no_images_returns_empty(self):
        assert extract_from_html("<html><body><p>No images here</p></body></html>") == []

    def test_tiny_image_ignored(self):
        b64 = base64.b64encode(b"x" * 10).decode()
        html = f'<img src="data:image/png;base64,{b64}" alt="barcode"/>'
        assert extract_from_html(html) == []

    def test_barcode_keyword_in_alt_picked_first(self):
        # Create two images: one larger (not barcode-labelled) and one smaller (barcode-labelled)
        large_bytes = b"x" * 2000
        barcode_bytes = b"y" * 1000

        large_b64 = base64.b64encode(large_bytes).decode()
        barcode_b64 = base64.b64encode(barcode_bytes).decode()

        html = (
            f'<img src="data:image/png;base64,{large_b64}" alt="banner"/>'
            f'<img src="data:image/png;base64,{barcode_b64}" alt="qrcode"/>'
        )
        result = extract_from_html(html)
        assert len(result) == 1
        assert result[0] == barcode_bytes

    def test_no_keyword_takes_largest(self):
        small_bytes = b"s" * 600
        large_bytes = b"l" * 2000

        small_b64 = base64.b64encode(small_bytes).decode()
        large_b64 = base64.b64encode(large_bytes).decode()

        html = (
            f'<img src="data:image/png;base64,{small_b64}" alt="logo"/>'
            f'<img src="data:image/png;base64,{large_b64}" alt="banner"/>'
        )
        result = extract_from_html(html)
        assert len(result) == 1
        assert result[0] == large_bytes

    def test_multiple_barcode_keywords_all_returned(self):
        img1 = b"a" * 600
        img2 = b"b" * 600

        b64_1 = base64.b64encode(img1).decode()
        b64_2 = base64.b64encode(img2).decode()

        html = (
            f'<img src="data:image/png;base64,{b64_1}" alt="barcode passenger 1"/>'
            f'<img src="data:image/png;base64,{b64_2}" alt="boarding pass passenger 2"/>'
        )
        result = extract_from_html(html)
        assert len(result) == 2

    def test_non_base64_img_ignored(self):
        html = '<img src="https://example.com/boarding.png" alt="barcode"/>'
        assert extract_from_html(html) == []

    def test_id_attribute_keyword_detected(self):
        img_bytes = b"z" * 800
        b64 = base64.b64encode(img_bytes).decode()
        html = f'<img src="data:image/png;base64,{b64}" id="qrcode-image"/>'
        result = extract_from_html(html)
        assert result == [img_bytes]


# ---------------------------------------------------------------------------
# Real-world fixture: LATAM purchase confirmation false-positive regression
# ---------------------------------------------------------------------------


class TestLatamPurchaseConfirmationNotCheckin:
    """
    Regression test for a LATAM "Você já comprou sua viagem" purchase confirmation
    email that was incorrectly flagged as a boarding pass email.

    The email body contains "cartão de embarque" as a travel tip
    ("Faça Check-in e obtenha seu cartão de embarque digital") and has a PDF
    attachment (purchase voucher) — both conditions that used to trigger
    is_checkin_email().  It must NOT be treated as a boarding pass email.

    Fixture: fixtures/latam_purchase_confirmation_anonymized.eml
    """

    @pytest.fixture(scope="class")
    def latam_purchase_email(self):
        return load_eml_as_email_message("latam_purchase_confirmation_anonymized.eml")

    def test_not_flagged_as_checkin(self, latam_purchase_email):
        assert is_checkin_email(latam_purchase_email) is False

    def test_has_pdf_attachment(self, latam_purchase_email):
        """Confirm the fixture does have a PDF (so it's a meaningful regression test)."""
        assert latam_purchase_email.pdf_attachments

    def test_body_contains_cartao_de_embarque(self, latam_purchase_email):
        """Confirm the triggering keyword is present in the body (so the fix is exercised)."""
        body = (latam_purchase_email.body or "") + (latam_purchase_email.html_body or "")
        assert "cartão de embarque" in body.lower() or "cartao de embarque" in body.lower()
