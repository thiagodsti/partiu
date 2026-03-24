"""
Boarding pass image extractor.

Handles extraction of boarding pass images from:
  1. PDF attachments (one page per passenger, rendered to PNG via pymupdf)
  2. HTML email bodies (base64-encoded inline images)

Extracted PNG bytes are returned to the caller for storage.
"""

import base64
import logging
import re

logger = logging.getLogger(__name__)

# Subject keywords that indicate a check-in confirmation / boarding pass email
_CHECKIN_SUBJECTS = [
    "boarding pass",
    "boarding card",
    "check-in confirmed",
    "check in confirmed",
    "checked in",
    "ready to fly",
    "passe de embarque",
    "cartão de embarque",
    "tarjeta de embarque",
    "web check-in",
    "online check-in",
    "mobile boarding pass",
    "embarque online",
]

# Keywords used to identify barcode images inside HTML emails
_BARCODE_IMG_KEYWORDS = {"barcode", "qr", "aztec", "boarding", "2d", "pdf417", "ticket", "qrcode"}


def is_checkin_email(email_msg) -> bool:
    """Return True if the email looks like a check-in confirmation with a boarding pass."""
    subject = (email_msg.subject or "").lower()
    if any(kw in subject for kw in _CHECKIN_SUBJECTS):
        return True
    # Also flag emails whose body mentions a boarding pass (even if subject doesn't)
    body = (email_msg.body or "").lower()
    if any(kw in body for kw in ("boarding pass", "boarding card", "passe de embarque", "cartão de embarque")):
        if email_msg.pdf_attachments:
            return True
    return False


def extract_from_pdf(pdf_bytes: bytes) -> list[bytes]:
    """
    Render each page of a PDF as a PNG image at 2× resolution.
    Returns a list of PNG image bytes, one per page.
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        logger.warning("pymupdf not installed — PDF boarding pass extraction unavailable")
        return []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        images = []
        mat = fitz.Matrix(2, 2)  # 2× scale for better scan quality at the gate
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=mat)
            images.append(pix.tobytes("png"))
        doc.close()
        return images
    except Exception as e:
        logger.warning("PDF boarding pass render failed: %s", e)
        return []


def extract_from_html(html: str) -> list[bytes]:
    """
    Extract boarding pass barcode images from HTML email body.
    Looks for base64-encoded inline images that appear to be barcodes.
    Returns a list of image bytes (PNG or JPEG).
    """
    if not html:
        return []

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[bytes, bool, int]] = []  # (bytes, has_keyword, size)

    for img in soup.find_all("img"):
        src = str(img.get("src", ""))
        m = re.match(r"data:image/(\w+);base64,(.+)", src, re.DOTALL)
        if not m:
            continue

        try:
            img_bytes = base64.b64decode(m.group(2).strip())
        except Exception:
            continue

        # Skip tiny images (logos, spacers)
        if len(img_bytes) < 500:
            continue

        # Check attributes for barcode-related keywords
        attrs = " ".join([
            str(img.get("alt", "")),
            str(img.get("id", "")),
            " ".join(img.get("class") or []),
            str(img.get("title", "")),
        ]).lower()

        has_keyword = any(kw in attrs for kw in _BARCODE_IMG_KEYWORDS)
        candidates.append((img_bytes, has_keyword, len(img_bytes)))

    if not candidates:
        return []

    # Prefer keyword-matched images; if none, take the largest (most likely a barcode)
    keyword_matches = [c[0] for c in candidates if c[1]]
    if keyword_matches:
        return keyword_matches

    candidates.sort(key=lambda c: c[2], reverse=True)
    return [candidates[0][0]]


def extract_boarding_pass_images(email_msg) -> list[dict]:
    """
    Extract all boarding pass images from an email.

    Returns a list of dicts: {image_bytes: bytes, source_page: int}
      - source_page is the 0-based page number for PDF, or index for HTML images.

    PDF attachments are tried first (higher quality); HTML fallback is used only
    if no PDF yields any images.
    """
    results = []

    for pdf_bytes in (email_msg.pdf_attachments or []):
        pages = extract_from_pdf(pdf_bytes)
        for page_num, img_bytes in enumerate(pages):
            results.append({"image_bytes": img_bytes, "source_page": page_num})

    if not results and email_msg.html_body:
        html_images = extract_from_html(email_msg.html_body)
        for idx, img_bytes in enumerate(html_images):
            results.append({"image_bytes": img_bytes, "source_page": idx})

    return results
