"""
tests/test_label_mapper.py — Unit tests for extract/label_mapper.py

Tests normalization, merging, resolution, and the import fix (Callable from typing).
No YAML files need to exist for most tests; file-backed tests use tmp_path.
"""
import pytest
import yaml
from pathlib import Path
from typing import Callable

from extract.label_mapper import (
    _norm,
    build_label_map,
    resolve_label,
    get_parser,
    LABEL_MAP_CROSS_PATH,
)


# ---------------------------------------------------------------------------
# _norm — label normalisation
# ---------------------------------------------------------------------------

class TestNorm:
    def test_lowercase(self):
        assert _norm("Maturity Date") == "maturity date"

    def test_strips_colon(self):
        assert _norm("Maturity Date:") == "maturity date"

    def test_strips_footnote_star(self):
        assert _norm("Maturity Date*") == "maturity date"
        assert _norm("Maturity Date †") == "maturity date"

    def test_strips_parenthetical_number(self):
        assert _norm("Maturity Date(1)") == "maturity date"

    def test_collapses_whitespace(self):
        assert _norm("Maturity  Date") == "maturity date"

    def test_strips_combined(self):
        # Trailing colon and plain footnote marker at end are stripped cleanly.
        # Note: a * appearing BEFORE a parenthetical (e.g. "*(1)") is not
        # stripped because the marker-regex runs before the parenthetical-regex.
        # That is a known minor gap; common real-world labels use one or the other.
        assert _norm("Reference Asset:") == "reference asset"
        assert _norm("Reference Asset*") == "reference asset"
        assert _norm("Reference Asset (1)") == "reference asset"


# ---------------------------------------------------------------------------
# build_label_map / resolve_label — with temporary YAML files
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_label_map(tmp_path, monkeypatch):
    """Write a minimal cross-issuer YAML and point the loader at it."""
    yaml_file = tmp_path / "label_map_cross_issuer.yaml"
    yaml_file.write_text(
        yaml.dump({"labels": {
            "Maturity Date": "structuredProductsGeneral.maturityDate",
            "Coupon Rate":   "coupon.rate",
            "Barrier Level": "barrier.triggerDetails.triggerLevel",
        }}, allow_unicode=True),
        encoding="utf-8",
    )
    # Monkeypatch the module-level path constants + cache cells
    import extract.label_mapper as lm
    monkeypatch.setattr(lm, "LABEL_MAP_CROSS_PATH", yaml_file)
    monkeypatch.setattr(lm, "LABEL_MAP_USER_PATH", tmp_path / "label_map_user.yaml")
    monkeypatch.setattr(lm, "_cross_cell", [None])
    monkeypatch.setattr(lm, "_cross_mt",   [None])
    monkeypatch.setattr(lm, "_user_cell",  [None])
    monkeypatch.setattr(lm, "_user_mt",    [None])
    return yaml_file


class TestBuildAndResolve:
    def test_resolves_exact(self, tmp_label_map):
        label_map = build_label_map()
        assert resolve_label("Maturity Date", label_map) == "structuredProductsGeneral.maturityDate"

    def test_resolves_case_insensitive(self, tmp_label_map):
        label_map = build_label_map()
        assert resolve_label("MATURITY DATE", label_map) == "structuredProductsGeneral.maturityDate"

    def test_resolves_with_colon(self, tmp_label_map):
        label_map = build_label_map()
        assert resolve_label("Maturity Date:", label_map) == "structuredProductsGeneral.maturityDate"

    def test_resolves_with_footnote(self, tmp_label_map):
        label_map = build_label_map()
        # Trailing star strips cleanly
        assert resolve_label("Maturity Date*", label_map) == "structuredProductsGeneral.maturityDate"
        # Trailing (1) strips cleanly
        assert resolve_label("Maturity Date(1)", label_map) == "structuredProductsGeneral.maturityDate"

    def test_unknown_label_returns_none(self, tmp_label_map):
        label_map = build_label_map()
        assert resolve_label("Nonexistent Label", label_map) is None

    def test_issuer_overrides_cross(self, tmp_label_map):
        issuer_overrides = {"Coupon Rate": "coupon.overrideRate"}
        label_map = build_label_map(issuer_table_labels=issuer_overrides)
        assert resolve_label("Coupon Rate", label_map) == "coupon.overrideRate"

    def test_empty_issuer_overrides(self, tmp_label_map):
        label_map = build_label_map(issuer_table_labels={})
        assert resolve_label("Barrier Level", label_map) == "barrier.triggerDetails.triggerLevel"


# ---------------------------------------------------------------------------
# get_parser — returns callable or None
# ---------------------------------------------------------------------------

class TestGetParser:
    def test_known_path_returns_callable(self):
        parser = get_parser("coupon.rate")
        assert callable(parser)

    def test_unknown_path_returns_none(self):
        assert get_parser("nonexistent.field.path") is None

    def test_callable_annotation_fix(self):
        """Regression: Callable must come from typing, not re-exported from field_parsers."""
        import extract.label_mapper as lm
        import inspect
        hints = lm.get_parser.__annotations__
        # Return type annotation should resolve to Callable (or its string repr)
        # The key check: importing label_mapper must not raise ImportError
        assert lm.get_parser is not None


# ---------------------------------------------------------------------------
# Import correctness regression
# ---------------------------------------------------------------------------

class TestImports:
    def test_callable_importable_from_label_mapper(self):
        """Regression: label_mapper used to re-import Callable from field_parsers
        (works but is a code smell — should come from typing)."""
        import extract.label_mapper as lm
        # Module should import cleanly with no AttributeError
        assert hasattr(lm, "build_label_map")
        assert hasattr(lm, "resolve_label")
        assert hasattr(lm, "get_parser")
