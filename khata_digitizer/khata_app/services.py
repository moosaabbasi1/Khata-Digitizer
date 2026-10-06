"""
The AI & OCR pipeline for Khata chits.

Kept separate from views.py on purpose (per the project roadmap) so the
image-processing logic can be tested, swapped, or tuned independently of
the request/response cycle. views.py (Phase 5) will call
`process_chit_image()` and hand the shopkeeper the result to review before
anything is saved to ChitItem.
"""

import re
from dataclasses import dataclass, field

import cv2
import numpy as np
import pytesseract

# Both languages, since a single chit commonly mixes Urdu item names with
# Latin-script numerals/prices. Tesseract accepts a "+"-joined language list.
OCR_LANGUAGES = "eng+urd"

# A conservative Tesseract page-segmentation mode: 6 = "assume a single
# uniform block of text", which suits a chit photo better than the default
# (which expects a full page layout with columns, etc.)
TESSERACT_CONFIG = "--oem 3 --psm 6"


def preprocess_image(image_bytes: bytes) -> np.ndarray:
    """
    Clean up a photographed handwritten chit so OCR has the best chance:
    - grayscale (color carries no information Tesseract needs, and it
      halves the data OCR has to process)
    - denoise (phone photos of paper are usually grainy/textured)
    - adaptive thresholding (turns it into clean black-on-white, robust to
      uneven lighting across a handheld photo — a plain global threshold
      would fail on chits photographed with a shadow across them)
    """
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode image — is this a valid image file?")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, h=10)
    thresholded = cv2.adaptiveThreshold(
        denoised,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,
        C=15,
    )
    return thresholded


def extract_text(preprocessed_image: np.ndarray) -> str:
    """Run Tesseract OCR (English + Urdu) over a preprocessed image."""
    return pytesseract.image_to_string(
        preprocessed_image, lang=OCR_LANGUAGES, config=TESSERACT_CONFIG
    )


# Matches a line ending in a number, optionally with "Rs"/"Rs." /₨ before it,
# e.g. "Sugar 2kg   Rs 240", "Tea 1     90", "دودھ 1 لیٹر 180"
_ITEM_LINE_RE = re.compile(
    r"^(?P<name>.+?)\s+(?:Rs\.?|₨)?\s*(?P<price>\d+(?:\.\d{1,2})?)\s*$"
)


@dataclass
class ParsedChitItem:
    item_name: str
    price: float
    quantity: float = 1.0
    raw_line: str = ""


@dataclass
class ParsedChit:
    items: list = field(default_factory=list)
    raw_text: str = ""
    unparsed_lines: list = field(default_factory=list)


def parse_chit_text(raw_text: str) -> ParsedChit:
    """
    Turn raw OCR text into structured (item_name, price) rows.

    This is intentionally a simple line-based heuristic, not a full NLP
    parser — handwritten chit layouts vary too much between shopkeepers to
    solve generally. It's expected to get some lines wrong; that's exactly
    why Phase 5 shows the shopkeeper an editable review form instead of
    saving this output directly.
    """
    result = ParsedChit(raw_text=raw_text)

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue

        match = _ITEM_LINE_RE.match(line)
        if match:
            name = match.group("name").strip(" -.:")
            try:
                price = float(match.group("price"))
            except ValueError:
                result.unparsed_lines.append(line)
                continue
            result.items.append(
                ParsedChitItem(item_name=name, price=price, raw_line=line)
            )
        else:
            result.unparsed_lines.append(line)

    return result


def process_chit_image(image_bytes: bytes) -> ParsedChit:
    """
    Full pipeline entry point: raw uploaded bytes in, structured (and
    still-unreviewed) chit data out. This is the single function Phase 5's
    upload view should call.
    """
    preprocessed = preprocess_image(image_bytes)
    raw_text = extract_text(preprocessed)
    return parse_chit_text(raw_text)
