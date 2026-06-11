r"""
Compiled extraction patterns and OCR correction maps.

Two scars from V3.2 bugs live here -- do not "simplify" them away:
  1. RECORD_PATTERN's name group is non-greedy (.+?) with a \s*$ anchor.
     A greedy .+ swallowed "PRICE: S/ 14.50 Stock 3" INTO the product name,
     so every record lost its price and stock silently.
  2. OCR_ID_FIXES deliberately does NOT map B->8. It used to -- and it
     corrupted legitimate alphanumeric IDs (ABC-001 became A8C-001).
     Only near-unambiguous OCR confusions stay: O->0, l->1, I->1, S->5.
"""
import re

# Line shape: ID: <id> PRODUCT: <name> [PRICE: S/ <price>] [Stock <n>]
# PRICE and Stock are optional groups -- a record without a price is still a
# record (it exits as Price=None downstream, never silently dropped).
RECORD_PATTERN = re.compile(
    r"ID:\s*(?P<id>[A-Z0-9-]+)"
    r"\s+PRODUCT:\s*(?P<name>.+?)"          # non-greedy: see module docstring, scar #1
    r"(?:\s+PRICE:\s*S/\s*(?P<price>[\d.,]+))?"
    r"(?:\s+Stock\s*(?P<stock>\d+))?"
    r"\s*$",
    re.IGNORECASE,
)

# Applied to the ID field ONLY -- running this over product names turns
# "SOLID" into "5O11D". The sanitizer enforces that boundary, not this map.
OCR_ID_FIXES: dict[str, str] = str.maketrans("OlIS", "0115")
