"""
Kiwi.com flight extractor.

Kiwi is an OTA (Online Travel Agency) that bundles flights from multiple
carriers. The HTML email body is mostly decorative; all the flight detail
lives in the PDF e-ticket attachment.

Each PDF "Segmento" block looks like:

    Segmento 1 para Gdańsk, Estocolmo ARN → Gdańsk GDN
    06:35 ARN Estocolmo, Suécia
    qui., 14 mai. 2026 Aeroporto de Estocolmo-Arlanda Transportadora: Ryanair
    N.º do voo: FR4678
    07:55 GDN Gdańsk, Polónia

The extractor also handles English Kiwi PDFs which use "Flight no.: FR4678".
"""

import logging
import re
from datetime import timedelta

from ..engine import parse_flight_date
from ..shared import _build_datetime

logger = logging.getLogger(__name__)

# Matches the "Segmento N para ... ARN → ... GDN" header line.
# The two trailing IATA codes are the dep and arr airports.
_SEGMENT_HEADER_RE = re.compile(
    r'^Segmento\s+\d+\b[^\n]*\b([A-Z]{3})\s*\S+\s*[^\n]*\b([A-Z]{3})\s*$',
    re.MULTILINE,
)

# Matches "N.º do voo: FR4678" (Portuguese) or "Flight no.: FR4678" (English)
_FLIGHT_NUM_RE = re.compile(
    r'(?:N\.?\s*[oº°]\.?\s+do\s+voo|Flight\s+n[o°º]\.?)[:\s]+([A-Z]{2}\s*\d{2,5})',
    re.IGNORECASE,
)

# Matches "Transportadora: Ryanair"
_CARRIER_RE = re.compile(r'(?:Transportadora|Carrier)[:\s]+([^\n]+)', re.IGNORECASE)


def extract(email_msg, rule) -> list[dict]:
    """Unified entry point: delegates to extract_bs4 (which reads from PDF)."""
    return extract_bs4(email_msg.html_body or "", rule, email_msg)


def extract_bs4(html: str, rule, email_msg) -> list[dict]:
    """Entry point — ignores HTML and works from the PDF attachment."""
    pdf_text = email_msg.get_pdf_text() if hasattr(email_msg, 'get_pdf_text') else ''
    if not pdf_text and hasattr(email_msg, 'pdf_attachments') and email_msg.pdf_attachments:
        from ..email_connector import _extract_text_from_pdf
        pdf_text = '\n'.join(
            t for b in email_msg.pdf_attachments
            if (t := _extract_text_from_pdf(b))
        )
    if not pdf_text:
        return []

    booking_ref = _extract_booking_ref(pdf_text)
    passenger = _extract_passenger(pdf_text)
    return _parse_segments(pdf_text, booking_ref, passenger)


def _extract_booking_ref(pdf_text: str) -> str:
    """Extract the overall Kiwi booking number."""
    m = re.search(r'N[UÚ]MERO\s+DE\s+RESERVA\s+([\d\s]+)', pdf_text, re.IGNORECASE)
    if m:
        return m.group(1).replace(' ', '')
    # English fallback: "Booking number 755 885 086"
    m = re.search(r'Booking\s+number[:\s]+([\d\s]+)', pdf_text, re.IGNORECASE)
    return m.group(1).replace(' ', '') if m else ''


def _extract_passenger(pdf_text: str) -> str:
    """Extract the name of the first passenger listed."""
    m = re.search(
        r'(?:Ms\.|Mr\.|Mrs\.|Miss)\s+([A-ZÀ-ÿ][a-zA-ZÀ-ÿ\s]+?)\s+\d',
        pdf_text,
    )
    return m.group(1).strip() if m else ''


def _parse_segments(pdf_text: str, booking_ref: str, passenger: str) -> list[dict]:
    """Parse each 'Segmento N' block and return one flight dict per block."""
    flights = []
    headers = list(_SEGMENT_HEADER_RE.finditer(pdf_text))

    for i, header in enumerate(headers):
        dep_airport = header.group(1)
        arr_airport = header.group(2)
        block_start = header.end()
        block_end = headers[i + 1].start() if i + 1 < len(headers) else len(pdf_text)
        block = pdf_text[block_start:block_end]

        flight = _parse_segment_block(block, dep_airport, arr_airport, booking_ref, passenger)
        if flight:
            flights.append(flight)

    return flights


def _parse_segment_block(
    block: str, dep_airport: str, arr_airport: str, booking_ref: str, passenger: str
) -> dict | None:
    """Extract flight data from the text body of one Segmento block."""
    # All "HH:MM IATA" occurrences — first is dep, last is arr
    time_airport_matches = list(
        re.finditer(r'^(\d{1,2}:\d{2})\s+[A-Z]{3}\b', block, re.MULTILINE)
    )
    if len(time_airport_matches) < 2:
        return None

    dep_time_str = time_airport_matches[0].group(1)
    arr_time_str = time_airport_matches[-1].group(1)

    # Date: find the first line that contains a 4-digit year
    date_m = re.search(r'(\d{1,2}\s+\w+\.?\s+\d{4})', block)
    if not date_m:
        return None
    dep_date = parse_flight_date(date_m.group(1))
    if not dep_date:
        return None

    # Flight number
    fn_m = _FLIGHT_NUM_RE.search(block)
    if not fn_m:
        return None
    flight_number = fn_m.group(1).replace(' ', '')

    # Carrier name and code from flight number prefix
    airline_code = flight_number[:2]
    carrier_m = _CARRIER_RE.search(block)
    airline_name = carrier_m.group(1).strip() if carrier_m else airline_code

    # Arrival date: same as departure unless time wraps past midnight
    dep_h, dep_m = map(int, dep_time_str.split(':'))
    arr_h, arr_m = map(int, arr_time_str.split(':'))
    arr_date = dep_date
    if arr_h < dep_h or (arr_h == dep_h and arr_m < dep_m):
        arr_date = dep_date + timedelta(days=1)

    dep_dt = _build_datetime(dep_date, dep_time_str)
    arr_dt = _build_datetime(arr_date, arr_time_str)
    if not dep_dt or not arr_dt:
        return None

    return {
        'airline_name': airline_name,
        'airline_code': airline_code,
        'flight_number': flight_number,
        'departure_airport': dep_airport,
        'arrival_airport': arr_airport,
        'departure_datetime': dep_dt,
        'arrival_datetime': arr_dt,
        'booking_reference': booking_ref,
        'passenger_name': passenger,
        'seat': '',
        'cabin_class': '',
        'departure_terminal': '',
        'arrival_terminal': '',
        'departure_gate': '',
        'arrival_gate': '',
    }
