"""
Pydantic request/response contracts for the dih-engine API.

The response status extends the sanitizer's taxonomy with NOISE: the engine
returns None for blacklisted/empty lines, and the API surfaces that as an
explicit status instead of a null body -- the caller always gets a typed
answer, never a guess about what absence means.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

# A single OCR line is never legitimately this long; anything bigger is a
# pasted file or an abuse attempt, and belongs on the /extract endpoint.
MAX_LINE_LENGTH = 10_000


class SanitizeRequest(BaseModel):
    line: str = Field(
        ...,
        max_length=MAX_LINE_LENGTH,
        description="One raw OCR line to sanitize",
        examples=["O01234 DUSTY PRODUCT NAME 14,50"],
    )


class SanitizeResponse(BaseModel):
    id: Optional[str] = None
    amount: Optional[str] = None
    status: Literal["APPROVED", "PARTIAL", "REJECTED", "NOISE"]


# Sync /extract cap: ~5 MB of text. Bigger payloads belong to the async jobs
# endpoint -- a sync request that takes minutes is a client timeout, not a
# feature.
MAX_EXTRACT_TEXT_LENGTH = 5_000_000


class ExtractRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        max_length=MAX_EXTRACT_TEXT_LENGTH,
        description="Raw OCR text -- the full file content, newline-separated lines",
        examples=["ID: ABC-001 PRODUCT: Industrial Press PRICE: S/ 1499.90 Stock 4"],
    )


class ExtractAudit(BaseModel):
    total: int
    matched: int
    skipped: int


class ExtractResponse(BaseModel):
    records: list[dict]
    audit: ExtractAudit


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
