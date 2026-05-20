import re

RECORD_PATTERN = re.compile(
    r"ID:\s*(?P<id>[A-Z0-9-]+)"
    r"\s+PRODUCT:\s*(?P<name>.+?)"
    r"(?:\s+PRICE:\s*S/\s*(?P<price>[\d.,]+))?"
    r"(?:\s+Stock\s*(?P<stock>\d+))?"
    r"\s*$",
    re.IGNORECASE,
)

OCR_ID_FIXES: dict[str, str] = str.maketrans("OlIS", "0115")
