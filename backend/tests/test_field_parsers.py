"""
tests/test_field_parsers.py — Unit tests for extract/field_parsers.py

Covers every public parser function and the FIELD_PARSERS registry.
No network calls, no DB — pure unit tests.
"""
import pytest
from extract.field_parsers import (
    parse_text,
    parse_date,
    parse_percentage,
    parse_amount,
    parse_number,
    parse_cusip,
    parse_isin,
    parse_currency,
    parse_frequency,
    parse_observation_type,
    FIELD_PARSERS,
    _MONTH_NAMES,  # module-level constant (regression: was rebuilt per-call)
)


# ---------------------------------------------------------------------------
# parse_text
# ---------------------------------------------------------------------------

class TestParseText:
    def test_basic(self):
        assert parse_text("  Goldman Sachs  ") == "Goldman Sachs"

    def test_strips_footnote_markers(self):
        assert parse_text("Goldman Sachs*") == "Goldman Sachs"
        assert parse_text("Value†") == "Value"
        assert parse_text("Value(1)") == "Value"
        assert parse_text("Value[2]") == "Value"

    def test_empty_returns_none(self):
        assert parse_text("") is None
        assert parse_text("   ") is None
        assert parse_text("*(1)") is None


# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_iso_passthrough(self):
        assert parse_date("2029-03-21") == "2029-03-21"

    def test_month_name_full(self):
        assert parse_date("March 21, 2029") == "2029-03-21"
        assert parse_date("December 1, 2030") == "2030-12-01"

    def test_month_name_abbr(self):
        assert parse_date("Mar 21, 2029") == "2029-03-21"

    def test_strips_footnotes(self):
        assert parse_date("March 21, 2029*") == "2029-03-21"

    def test_phrase_prefix(self):
        assert parse_date("on or about March 21, 2029") == "2029-03-21"

    def test_iso_slash_format(self):
        assert parse_date("2029/03/21") == "2029-03-21"

    def test_unrecognised_returns_none(self):
        assert parse_date("TBD") is None
        assert parse_date("") is None

    def test_module_level_month_names(self):
        """Regression: _MONTH_NAMES must be a module-level dict, not None."""
        assert isinstance(_MONTH_NAMES, dict)
        assert len(_MONTH_NAMES) > 20
        assert _MONTH_NAMES["march"] == 3
        assert _MONTH_NAMES["jan"] == 1


# ---------------------------------------------------------------------------
# parse_percentage
# ---------------------------------------------------------------------------

class TestParsePercentage:
    def test_simple_percent(self):
        assert parse_percentage("70%") == pytest.approx(0.70)

    def test_decimal_percent(self):
        assert parse_percentage("70.00%") == pytest.approx(0.70)

    def test_percent_with_suffix(self):
        assert parse_percentage("70.00% of Initial Underlier Value") == pytest.approx(0.70)

    def test_prefers_per_annum_over_monthly(self):
        raw = "8.50% per annum or 0.7083% per month"
        assert parse_percentage(raw) == pytest.approx(0.085)

    def test_prefers_non_monthly(self):
        raw = "1,949.187, 80.00% of its Initial Level"
        assert parse_percentage(raw) == pytest.approx(0.80)

    def test_barrier_level(self):
        assert parse_percentage("$5,350.77 (80.00% of its Initial Level)") == pytest.approx(0.80)

    def test_no_percent_returns_none(self):
        assert parse_percentage("Goldman Sachs") is None

    def test_small_decimal_stays_as_is(self):
        # values ≤ 1.0 are treated as already-decimal
        assert parse_percentage("0.70%") == pytest.approx(0.70)


# ---------------------------------------------------------------------------
# parse_amount
# ---------------------------------------------------------------------------

class TestParseAmount:
    def test_dollar_with_commas(self):
        assert parse_amount("$1,372,000.00") == pytest.approx(1_372_000.0)

    def test_dollar_per_note(self):
        assert parse_amount("$1,000 per note") == pytest.approx(1_000.0)

    def test_no_symbol(self):
        assert parse_amount("1,372,000") == pytest.approx(1_372_000.0)

    def test_us_dollar(self):
        assert parse_amount("US$ 2,000,000") == pytest.approx(2_000_000.0)

    def test_unrecognised_returns_none(self):
        assert parse_amount("N/A") is None


# ---------------------------------------------------------------------------
# parse_cusip / parse_isin
# ---------------------------------------------------------------------------

class TestParseIdentifiers:
    def test_cusip_plain(self):
        assert parse_cusip("06749FWA3") == "06749FWA3"

    def test_cusip_from_combined(self):
        assert parse_cusip("06749FWA3 / US06749FWA31") == "06749FWA3"

    def test_isin_plain(self):
        assert parse_isin("US06749FWA31") == "US06749FWA31"

    def test_isin_from_combined(self):
        assert parse_isin("06749FWA3 / US06749FWA31") == "US06749FWA31"

    def test_cusip_not_found_returns_none(self):
        assert parse_cusip("N/A") is None

    def test_isin_not_found_returns_none(self):
        assert parse_isin("N/A") is None


# ---------------------------------------------------------------------------
# parse_currency
# ---------------------------------------------------------------------------

class TestParseCurrency:
    def test_iso_code(self):
        assert parse_currency("USD") == "USD"
        assert parse_currency("EUR") == "EUR"

    def test_plain_text(self):
        assert parse_currency("U.S. dollars") == "USD"
        assert parse_currency("US dollars") == "USD"
        assert parse_currency("United States dollars") == "USD"

    def test_with_parenthetical(self):
        assert parse_currency("USD (United States Dollars)") == "USD"

    def test_unknown_returns_none(self):
        assert parse_currency("Pesos") is None


# ---------------------------------------------------------------------------
# parse_frequency
# ---------------------------------------------------------------------------

class TestParseFrequency:
    def test_monthly(self):
        assert parse_frequency("monthly") == {"$type": "monthly"}
        assert parse_frequency("per month") == {"$type": "monthly"}

    def test_quarterly(self):
        assert parse_frequency("quarterly") == {"$type": "quarterly"}

    def test_semi_annual(self):
        assert parse_frequency("semi-annual") == {"$type": "semiAnnually"}
        assert parse_frequency("semiannual") == {"$type": "semiAnnually"}

    def test_annual(self):
        assert parse_frequency("annually") == {"$type": "annually"}
        assert parse_frequency("per year") == {"$type": "annually"}

    def test_unknown_returns_none(self):
        assert parse_frequency("ad hoc") is None


# ---------------------------------------------------------------------------
# parse_observation_type
# ---------------------------------------------------------------------------

class TestParseObservationType:
    def test_european(self):
        assert parse_observation_type("European") == "european"
        assert parse_observation_type("observed at maturity") == "european"

    def test_american(self):
        assert parse_observation_type("American") == "american"
        assert parse_observation_type("daily monitoring") == "american"

    def test_periodic(self):
        assert parse_observation_type("on each Observation Date") == "periodic"

    def test_unknown_returns_none(self):
        assert parse_observation_type("n/a") is None


# ---------------------------------------------------------------------------
# FIELD_PARSERS registry
# ---------------------------------------------------------------------------

class TestFieldParsersRegistry:
    def test_registry_is_populated(self):
        assert len(FIELD_PARSERS) > 10

    def test_known_keys_present(self):
        assert "structuredProductsGeneral.maturityDate" in FIELD_PARSERS
        assert "coupon.rate" in FIELD_PARSERS
        assert "barrier.triggerDetails.triggerLevel" in FIELD_PARSERS
        assert "identifiers.cusip" in FIELD_PARSERS

    def test_no_generic_keys(self):
        """Regression: Generic → General rename — no old paths should remain."""
        for key in FIELD_PARSERS:
            assert "Generic" not in key, f"Old 'Generic' path found: {key}"

    def test_all_values_are_callable(self):
        for key, fn in FIELD_PARSERS.items():
            assert callable(fn), f"Parser for {key!r} is not callable"
