import re

RECORD_PATTERN = re.compile(
    r"ID:\s*(?P<id>[A-Z0-9-]+).*?"
    r"PRODUCT:\s*(?P<name>[^|]+).*?"
    r"(?:PRICE:\s*S/\s*(?P<price>[\d.]+))?.*?"
    r"(?:Stock\s*(?P<stock>\d+))?",
    re.IGNORECASE | re.DOTALL,
)

OCR_ID_FIXES: dict[str, str] = str.maketrans("OlIBS", "01185")
