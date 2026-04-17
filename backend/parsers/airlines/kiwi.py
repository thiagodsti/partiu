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

import re

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    enrich_flights,
    fix_overnight,
    make_flight_dict,
)

# Matches the "Segmento N para ... ARN → ... GDN" header line.
_segment_header_re = re.compile(
    r"^Segmento\s+\d+\b[^\n]*\b([A-Z]{3})\s*\S+\s*[^\n]*\b([A-Z]{3})\s*$",
    re.MULTILINE,
)

# Matches "N.º do voo: FR4678" (Portuguese) or "Flight no.: FR4678" (English)
_flight_number_re = re.compile(
    r"(?:N\.?\s*[oº°]\.?\s+do\s+voo|Flight\s+n[o°º]\.?)[:\s]+([A-Z]{2}\s*\d{2,5})",
    re.IGNORECASE,
)

# Matches "Transportadora: Ryanair"
_carrier_re = re.compile(r"(?:Transportadora|Carrier)[:\s]+([^\n]+)", re.IGNORECASE)


def _parse_segment_block(
    block: str,
    dep_airport: str,
    arr_airport: str,
    rule,
) -> dict | None:
    """Extract one flight from the text body of a Segmento block."""
    # Times: all "HH:MM IATA" lines — first is dep, last is arr
    time_matches = list(re.finditer(r"^(\d{1,2}:\d{2})\s+[A-Z]{3}\b", block, re.MULTILINE))
    if len(time_matches) < 2:
        return None

    dep_time_str = time_matches[0].group(1)
    arr_time_str = time_matches[-1].group(1)

    # Date: first line containing a 4-digit year
    date_m = re.search(r"(\d{1,2}\s+\w+\.?\s+\d{4})", block)
    if not date_m:
        return None
    dep_date = parse_flight_date(date_m.group(1))
    if not dep_date:
        return None

    # Flight number
    fn_m = _flight_number_re.search(block)
    if not fn_m:
        return None
    flight_number = fn_m.group(1).replace(" ", "")

    # Carrier name (for airline_name — airline_code comes from flight number)
    airline_code = flight_number[:2]
    carrier_m = _carrier_re.search(block)
    airline_name = carrier_m.group(1).strip() if carrier_m else airline_code

    dep_dt = _build_datetime(dep_date, dep_time_str)
    arr_dt = _build_datetime(dep_date, arr_time_str)
    if not dep_dt or not arr_dt:
        return None
    arr_dt = fix_overnight(dep_dt, arr_dt)

    # Kiwi bundles multiple carriers — override rule's airline info
    flight = make_flight_dict(rule, flight_number, dep_airport, arr_airport, dep_dt, arr_dt)
    if flight:
        flight["airline_name"] = airline_name
        flight["airline_code"] = airline_code
    return flight


def _extract_from_pdf(email_msg, rule) -> list[dict]:
    """Parse all Segmento blocks from PDF attachments."""
    if not getattr(email_msg, "pdf_attachments", None):
        return []

    from ..email_connector import _extract_text_from_pdf

    pdf_text = "\n".join(t for b in email_msg.pdf_attachments if (t := _extract_text_from_pdf(b)))
    if not pdf_text:
        return []

    flights = []
    headers = list(_segment_header_re.finditer(pdf_text))

    for i, header in enumerate(headers):
        block_end = headers[i + 1].start() if i + 1 < len(headers) else len(pdf_text)
        block = pdf_text[header.end() : block_end]
        flight = _parse_segment_block(block, header.group(1), header.group(2), rule)
        if flight:
            flights.append(flight)

    return flights


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a Kiwi.com email (reads PDF attachments)."""
    flights = _extract_from_pdf(email_msg, rule)
    # Enrich from PDF text (booking ref, passenger)
    if flights and getattr(email_msg, "pdf_attachments", None):
        from ..email_connector import _extract_text_from_pdf

        pdf_text = "\n".join(
            t for b in email_msg.pdf_attachments if (t := _extract_text_from_pdf(b))
        )
        return enrich_flights(flights, pdf_text)
    return flights
