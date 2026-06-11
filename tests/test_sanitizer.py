import pytest
from src.dih_engine.sanitizer.core import DataSanitizer


@pytest.fixture
def engine():
    return DataSanitizer()


class TestIsNoise:
    def test_rejects_exact_blacklist_word(self, engine):
        assert engine.is_noise("TOTAL 100.00") is True

    def test_rejects_blacklist_word_with_surrounding_text(self, engine):
        assert engine.is_noise("Please pay TOTAL 50.00") is True

    def test_allows_substring_that_is_not_whole_word(self, engine):
        # Regression: bug #7 — 'TOTALIZER' must NOT trigger 'TOTAL' blacklist entry
        assert engine.is_noise("TOTALIZER CHARGER 9.99") is False

    def test_case_insensitive_rejection(self, engine):
        assert engine.is_noise("subtotal 200.00") is True

    def test_allows_clean_product_line(self, engine):
        assert engine.is_noise("01234 LAPTOP CHARGER 49.99") is False


class TestExtractData:
    def test_happy_path_returns_approved(self, engine):
        result = engine.extract_data("O01234 SOME PRODUCT 14.50")
        assert result is not None
        assert result["status"] == "APPROVED"
        assert result["id"] == "001234"   # O corrected to 0
        assert result["amount"] == "14.50"

    def test_ocr_o_corrected_to_zero(self, engine):
        result = engine.extract_data("OO1234 ITEM 9.99")
        assert result["id"] == "001234"

    def test_noise_line_returns_none(self, engine):
        assert engine.extract_data("TOTAL 500.00") is None

    def test_id_only_returns_partial(self, engine):
        # Line has an ID but no trailing amount
        result = engine.extract_data("01234 PRODUCT WITH NO PRICE")
        assert result is not None
        assert result["status"] == "PARTIAL"
        assert result["id"] == "01234"
        assert result["amount"] is None

    def test_id_must_be_at_start_of_line(self, engine):
        # ID in the middle of the line — should not match due to re.match anchoring
        result = engine.extract_data("PREFIX 01234 PRODUCT 5.00")
        assert result is not None
        assert result["id"] is None   # ID not at start, so not captured

    def test_empty_string_returns_none(self, engine):
        assert engine.extract_data("") is None

    def test_whitespace_only_returns_none(self, engine):
        assert engine.extract_data("   \t  ") is None

    def test_comma_decimal_normalized(self, engine):
        result = engine.extract_data("01234 ITEM 14,50")
        assert result is not None
        assert result["amount"] == "14.50"


class TestAmountLocaleNormalization:
    """Grouped thousand-separator amounts: European and US conventions.

    Before this feature the amount pattern silently rejected grouped amounts:
    the record fell to PARTIAL with amount=None — silent data loss, not a
    visible error. The 2-decimal tail contract resolves locale ambiguity
    without detection: rightmost separator = decimal mark, always.
    """

    def test_european_format_dot_thousands_comma_decimal(self, engine):
        result = engine.extract_data("01234 INDUSTRIAL PRESS 1.234,50")
        assert result["status"] == "APPROVED"
        assert result["amount"] == "1234.50"

    def test_us_format_comma_thousands_dot_decimal(self, engine):
        result = engine.extract_data("01234 INDUSTRIAL PRESS 1,234.50")
        assert result["status"] == "APPROVED"
        assert result["amount"] == "1234.50"

    def test_european_multigroup_millions(self, engine):
        result = engine.extract_data("01234 WAREHOUSE LOT 1.234.567,89")
        assert result["amount"] == "1234567.89"

    def test_us_multigroup_millions(self, engine):
        result = engine.extract_data("01234 WAREHOUSE LOT 1,234,567.89")
        assert result["amount"] == "1234567.89"

    def test_plain_decimals_unchanged_regression(self, engine):
        # The two pre-existing shapes must keep working exactly as before.
        assert engine.extract_data("01234 ITEM 14,50")["amount"] == "14.50"
        assert engine.extract_data("01234 ITEM 14.50")["amount"] == "14.50"
        assert engine.extract_data("01234 ITEM 12345,99")["amount"] == "12345.99"

    def test_date_like_token_still_not_captured(self, engine):
        # 12.06.26 has 2-digit groups -- fails both pattern alternatives.
        # Must stay PARTIAL (id only), never misread a date as an amount.
        result = engine.extract_data("01234 BATCH 12.06.26")
        assert result["status"] == "PARTIAL"
        assert result["amount"] is None
