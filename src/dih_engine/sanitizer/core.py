"""
Universal Data Sanitizer Core
Author: Diego Alonso Del Río García

Logic engine to clean, sanitize, and structure raw/garbage text from OCR outputs.
Applies Zero-Trust principles and tolerance to AI/OCR hallucinations.
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Common OCR character confusions: digit↔letter swaps
OCR_CORRECTIONS: dict[str, str] = {
    "O": "0",
    "l": "1",
    "I": "1",
    "B": "8",
    "S": "5",
}


class DataSanitizer:
    def __init__(self) -> None:
        # Anchored at start of line — use re.match(), not re.search(), with this pattern.
        # Tolerates O↔0 confusion common in OCR-scanned product/transaction IDs.
        self._id_pattern = re.compile(r"^([0-9O]{4,14})\s+")

        # Finds isolated monetary amounts at the end of a line.
        # Negative lookbehind (?<!\S) requires the amount be preceded by whitespace.
        self._amount_pattern = re.compile(r"(?<!\S)(\d{1,5}[.,]\d{2})\s*[A-Za-z]?\s*$")

        self._blacklist: list[str] = [
            "TOTAL", "SUBTOTAL", "TAX", "CASH", "CARD",
            "DATE:", "TIME:", "CUSTOMER", "ID:", "CASHIER",
        ]
        # Pre-compile word-boundary patterns once at init — not per call.
        self._noise_patterns: list[re.Pattern] = [
            re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE)
            for w in self._blacklist
        ]

    def is_noise(self, line: str) -> bool:
        """
        Returns True if the line contains a blacklisted token as a whole word.
        Substring matches do not count — 'TOTALIZER' does not trigger 'TOTAL'.
        """
        for pattern in self._noise_patterns:
            if pattern.search(line):
                logger.debug("noise_detected line=%r matched=%s", line[:60], pattern.pattern)
                return True
        return False

    def _correct_id(self, raw: str) -> str:
        """Applies OCR character corrections to an extracted ID string."""
        return "".join(OCR_CORRECTIONS.get(ch, ch) for ch in raw)

    def _normalize_amount(self, raw: str) -> str:
        """
        Normalizes a captured amount string to a dot-decimal format.
        Handles both comma-decimal ('14,50') and period-decimal ('14.50').
        Does NOT handle European thousand separators like '1.234,50' — that
        requires domain-specific disambiguation and is a documented limitation.
        """
        return raw.replace(",", ".")

    def extract_data(self, line: str) -> Optional[dict]:
        """
        Attempts to extract an ID and a monetary amount from a raw OCR line.

        Returns None if the line is classified as noise.
        Returns a dict with keys: id, amount, status.
        Status is one of: APPROVED, PARTIAL, REJECTED.
        """
        if not line or not line.strip():
            return None

        if self.is_noise(line):
            return None

        result: dict = {"id": None, "amount": None, "status": "REJECTED"}

        # re.match anchors to start of string — correct for the ^ in the pattern.
        id_match = self._id_pattern.match(line)
        if id_match:
            result["id"] = self._correct_id(id_match.group(1))
            logger.debug("id_extracted raw=%r corrected=%r", id_match.group(1), result["id"])

        amount_match = self._amount_pattern.search(line)
        if amount_match:
            result["amount"] = self._normalize_amount(amount_match.group(1))
            logger.debug("amount_extracted raw=%r normalized=%r", amount_match.group(1), result["amount"])

        if result["id"] and result["amount"]:
            result["status"] = "APPROVED"
        elif result["id"] or result["amount"]:
            result["status"] = "PARTIAL"

        return result


if __name__ == "__main__":
    engine = DataSanitizer()
    samples = [
        "O01234 DUSTY PRODUCT NAME 14.50",
        "TOTAL 100.00",
        "TOTALIZER CHARGER 9.99",
        "3D PRINTER MODEL X 299.99",
        "",
    ]
    for raw in samples:
        print(f"Input:  {raw!r}")
        print(f"Output: {engine.extract_data(raw)}")
        print()
