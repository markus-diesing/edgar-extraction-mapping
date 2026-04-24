"""
tests/test_underlying_field_config.py — Unit tests for underlying/field_config.py

All filesystem I/O uses ``tmp_path`` (pytest fixture) so the production YAML
is never touched.  The module-level in-process cache is invalidated between
tests via the ``_invalidate_cache()`` helper.
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
import yaml

import underlying.field_config as fc_module
from underlying.field_config import (
    FieldConfig,
    FieldDef,
    _invalidate_cache,
    _parse_yaml,
    _dump_yaml,
    load,
    save,
    get_enabled_fields,
    get_field,
    toggle_field,
    reorder_fields,
    update_fields,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_YAML = dedent("""\
    version: "1"
    fields:
      - name: company_name
        display_name: Company Name
        enabled: true
      - name: ticker
        display_name: Ticker
        enabled: true
      - name: sic_code
        display_name: SIC Code
        enabled: false
""")

MINIMAL_DICT: dict[str, Any] = yaml.safe_load(MINIMAL_YAML)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the in-process cache before every test."""
    _invalidate_cache()
    yield
    _invalidate_cache()


@pytest.fixture
def yaml_file(tmp_path, monkeypatch) -> Path:
    """Write MINIMAL_YAML to a temp file and patch config to point at it."""
    p = tmp_path / "underlying_field_config.yaml"
    p.write_text(MINIMAL_YAML, encoding="utf-8")
    monkeypatch.setattr(fc_module.config, "UNDERLYING_FIELD_CONFIG_FILE", p)
    return p


# ---------------------------------------------------------------------------
# _parse_yaml
# ---------------------------------------------------------------------------

class TestParseYaml:
    def test_parses_version(self):
        cfg = _parse_yaml(MINIMAL_DICT)
        assert cfg.version == "1"

    def test_parses_all_fields(self):
        cfg = _parse_yaml(MINIMAL_DICT)
        assert len(cfg.fields) == 3

    def test_enabled_flag(self):
        cfg = _parse_yaml(MINIMAL_DICT)
        names = {f.name: f.enabled for f in cfg.fields}
        assert names["company_name"] is True
        assert names["sic_code"] is False

    def test_display_name_preserved(self):
        cfg = _parse_yaml(MINIMAL_DICT)
        f = next(x for x in cfg.fields if x.name == "ticker")
        assert f.display_name == "Ticker"

    def test_duplicate_name_raises(self):
        bad = yaml.safe_load(dedent("""\
            version: "1"
            fields:
              - name: foo
                display_name: Foo
                enabled: true
              - name: foo
                display_name: Foo Again
                enabled: true
        """))
        with pytest.raises(ValueError, match="Duplicate"):
            _parse_yaml(bad)

    def test_empty_name_raises(self):
        bad = yaml.safe_load(dedent("""\
            version: "1"
            fields:
              - name: ""
                display_name: Empty
                enabled: true
        """))
        with pytest.raises(ValueError, match="no 'name'"):
            _parse_yaml(bad)

    def test_missing_fields_key_ok(self):
        cfg = _parse_yaml({"version": "2"})
        assert cfg.fields == []
        assert cfg.version == "2"

    def test_non_dict_entry_raises(self):
        bad = {"version": "1", "fields": ["not_a_dict"]}
        with pytest.raises(ValueError, match="not a mapping"):
            _parse_yaml(bad)


# ---------------------------------------------------------------------------
# _dump_yaml / round-trip
# ---------------------------------------------------------------------------

class TestDumpYaml:
    def test_round_trip(self):
        cfg = _parse_yaml(MINIMAL_DICT)
        dumped = _dump_yaml(cfg)
        reloaded = yaml.safe_load(dumped)
        cfg2 = _parse_yaml(reloaded)
        assert cfg.version == cfg2.version
        assert [f.name for f in cfg.fields] == [f.name for f in cfg2.fields]
        assert [f.enabled for f in cfg.fields] == [f.enabled for f in cfg2.fields]

    def test_enabled_false_preserved(self):
        cfg = _parse_yaml(MINIMAL_DICT)
        dumped = _dump_yaml(cfg)
        reloaded = yaml.safe_load(dumped)
        sic = next(x for x in reloaded["fields"] if x["name"] == "sic_code")
        assert sic["enabled"] is False


# ---------------------------------------------------------------------------
# FieldConfig properties
# ---------------------------------------------------------------------------

class TestFieldConfigProperties:
    def test_enabled_fields(self):
        cfg = _parse_yaml(MINIMAL_DICT)
        enabled = cfg.enabled_fields
        assert all(f.enabled for f in enabled)
        assert len(enabled) == 2

    def test_field_names(self):
        cfg = _parse_yaml(MINIMAL_DICT)
        assert cfg.field_names == ["company_name", "ticker", "sic_code"]

    def test_get_existing(self):
        cfg = _parse_yaml(MINIMAL_DICT)
        f = cfg.get("ticker")
        assert f is not None
        assert f.display_name == "Ticker"

    def test_get_missing_returns_none(self):
        cfg = _parse_yaml(MINIMAL_DICT)
        assert cfg.get("nonexistent") is None

    def test_to_dict(self):
        cfg = _parse_yaml(MINIMAL_DICT)
        d = cfg.to_dict()
        assert d["version"] == "1"
        assert len(d["fields"]) == 3
        assert d["fields"][0]["name"] == "company_name"


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------

class TestLoadSave:
    def test_load_reads_yaml(self, yaml_file):
        cfg = load()
        assert len(cfg.fields) == 3
        assert cfg.version == "1"

    def test_load_cached(self, yaml_file):
        cfg1 = load()
        cfg2 = load()
        assert cfg1 is cfg2   # same object from cache

    def test_load_missing_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fc_module.config, "UNDERLYING_FIELD_CONFIG_FILE",
                            tmp_path / "does_not_exist.yaml")
        with pytest.raises(FileNotFoundError):
            load()

    def test_save_bumps_version(self, yaml_file):
        cfg = load()
        assert cfg.version == "1"
        save(cfg)
        assert cfg.version == "2"

    def test_save_persists_to_disk(self, yaml_file):
        cfg = load()
        cfg.fields[0].display_name = "CHANGED"
        save(cfg)
        # Reload from disk
        raw = yaml.safe_load(yaml_file.read_text())
        assert raw["fields"][0]["display_name"] == "CHANGED"

    def test_save_invalidates_cache(self, yaml_file):
        cfg1 = load()
        save(cfg1)
        cfg2 = load()   # must reload from disk
        # Different object, but same data
        assert cfg1 is not cfg2
        assert cfg2.version == "2"

    def test_save_non_numeric_version_unchanged(self, yaml_file):
        cfg = load()
        cfg.version = "v1-alpha"
        save(cfg)
        assert cfg.version == "v1-alpha"   # non-numeric → left as-is


# ---------------------------------------------------------------------------
# get_enabled_fields / get_field
# ---------------------------------------------------------------------------

class TestGetters:
    def test_get_enabled_fields(self, yaml_file):
        fields = get_enabled_fields()
        assert all(f.enabled for f in fields)
        assert len(fields) == 2

    def test_get_field_existing(self, yaml_file):
        f = get_field("sic_code")
        assert f is not None
        assert f.enabled is False

    def test_get_field_missing(self, yaml_file):
        assert get_field("no_such_field") is None


# ---------------------------------------------------------------------------
# toggle_field
# ---------------------------------------------------------------------------

class TestToggleField:
    def test_enable_disabled_field(self, yaml_file):
        cfg = toggle_field("sic_code", True)
        assert cfg.get("sic_code").enabled is True
        # Persisted to disk
        raw = yaml.safe_load(yaml_file.read_text())
        sic = next(x for x in raw["fields"] if x["name"] == "sic_code")
        assert sic["enabled"] is True

    def test_disable_enabled_field(self, yaml_file):
        cfg = toggle_field("company_name", False)
        assert cfg.get("company_name").enabled is False

    def test_unknown_field_raises_key_error(self, yaml_file):
        with pytest.raises(KeyError, match="unknown_field"):
            toggle_field("unknown_field", True)


# ---------------------------------------------------------------------------
# reorder_fields
# ---------------------------------------------------------------------------

class TestReorderFields:
    def test_reorder_all(self, yaml_file):
        cfg = reorder_fields(["sic_code", "ticker", "company_name"])
        assert cfg.field_names == ["sic_code", "ticker", "company_name"]

    def test_partial_order_appends_rest(self, yaml_file):
        # Only specify two out of three → third appended at end
        cfg = reorder_fields(["sic_code", "company_name"])
        assert cfg.field_names[0] == "sic_code"
        assert cfg.field_names[1] == "company_name"
        assert "ticker" in cfg.field_names

    def test_unknown_names_ignored(self, yaml_file):
        cfg = reorder_fields(["ticker", "does_not_exist", "company_name"])
        # All original names still present
        for name in ["company_name", "ticker", "sic_code"]:
            assert name in cfg.field_names

    def test_empty_list_appends_all(self, yaml_file):
        cfg = reorder_fields([])
        assert len(cfg.fields) == 3   # none lost


# ---------------------------------------------------------------------------
# update_fields
# ---------------------------------------------------------------------------

class TestUpdateFields:
    def test_update_display_name(self, yaml_file):
        cfg = update_fields([{"name": "ticker", "display_name": "Exchange Ticker"}])
        assert cfg.get("ticker").display_name == "Exchange Ticker"

    def test_update_enabled(self, yaml_file):
        cfg = update_fields([{"name": "sic_code", "enabled": True}])
        assert cfg.get("sic_code").enabled is True

    def test_unknown_name_silently_skipped(self, yaml_file):
        cfg = update_fields([{"name": "ghost_field", "enabled": True}])
        # No error; original fields unchanged in count
        assert len(cfg.fields) == 3

    def test_order_reflects_update_order(self, yaml_file):
        cfg = update_fields([
            {"name": "sic_code"},
            {"name": "ticker"},
        ])
        names = cfg.field_names
        assert names.index("sic_code") < names.index("ticker")

    def test_persisted_to_disk(self, yaml_file):
        update_fields([{"name": "company_name", "display_name": "Issuer Name"}])
        raw = yaml.safe_load(yaml_file.read_text())
        cn = next(x for x in raw["fields"] if x["name"] == "company_name")
        assert cn["display_name"] == "Issuer Name"

    def test_all_fields_preserved_after_update(self, yaml_file):
        cfg = update_fields([{"name": "ticker", "display_name": "New Name"}])
        assert len(cfg.fields) == 3


# ---------------------------------------------------------------------------
# M4 / M5 additions — YAML error handling and disk persistence
# ---------------------------------------------------------------------------

class TestYamlErrorHandling:
    """load() raises clear ValueError messages on malformed YAML."""

    def test_invalid_yaml_syntax_raises_valueerror(self, tmp_path, monkeypatch):
        """A YAML syntax error produces a helpful ValueError, not a raw YAMLError."""
        bad_file = tmp_path / "underlying_field_config.yaml"
        bad_file.write_text("version: 1\nfields: [\n  - bad: yaml: [unclosed", encoding="utf-8")
        monkeypatch.setattr(fc_module.config, "UNDERLYING_FIELD_CONFIG_FILE", bad_file)
        _invalidate_cache()
        with pytest.raises(ValueError, match="invalid YAML"):
            load()

    def test_non_mapping_yaml_raises_valueerror(self, tmp_path, monkeypatch):
        """A YAML file whose root is a list (not a mapping) raises a clear error."""
        bad_file = tmp_path / "underlying_field_config.yaml"
        bad_file.write_text("- just\n- a\n- list\n", encoding="utf-8")
        monkeypatch.setattr(fc_module.config, "UNDERLYING_FIELD_CONFIG_FILE", bad_file)
        _invalidate_cache()
        with pytest.raises(ValueError, match="expected a YAML mapping"):
            load()

    def test_fields_not_a_list_raises_valueerror(self, tmp_path, monkeypatch):
        """'fields' key that is a string (not a list) raises a clear error."""
        bad_file = tmp_path / "underlying_field_config.yaml"
        bad_file.write_text('version: "1"\nfields: "not-a-list"\n', encoding="utf-8")
        monkeypatch.setattr(fc_module.config, "UNDERLYING_FIELD_CONFIG_FILE", bad_file)
        _invalidate_cache()
        with pytest.raises(ValueError, match="'fields' must be a list"):
            load()

    def test_field_missing_name_raises_valueerror(self, tmp_path, monkeypatch):
        """A field entry with no 'name' key raises a clear error."""
        bad_file = tmp_path / "underlying_field_config.yaml"
        bad_file.write_text(
            'version: "1"\nfields:\n  - display_name: No Name\n    enabled: true\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(fc_module.config, "UNDERLYING_FIELD_CONFIG_FILE", bad_file)
        _invalidate_cache()
        with pytest.raises(ValueError, match="no 'name'"):
            load()

    def test_duplicate_field_name_raises_valueerror(self, tmp_path, monkeypatch):
        """Duplicate field names in YAML are rejected."""
        bad_file = tmp_path / "underlying_field_config.yaml"
        bad_file.write_text(
            'version: "1"\nfields:\n'
            '  - name: foo\n    display_name: Foo\n    enabled: true\n'
            '  - name: foo\n    display_name: Foo Again\n    enabled: true\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(fc_module.config, "UNDERLYING_FIELD_CONFIG_FILE", bad_file)
        _invalidate_cache()
        with pytest.raises(ValueError, match="Duplicate field name"):
            load()


class TestDiskPersistence:
    """save() writes valid YAML to disk that can be round-tripped through load()."""

    def test_save_and_reload_roundtrip(self, tmp_path, monkeypatch):
        """A saved FieldConfig can be reloaded from disk with identical data."""
        yaml_file = tmp_path / "underlying_field_config.yaml"
        monkeypatch.setattr(fc_module.config, "UNDERLYING_FIELD_CONFIG_FILE", yaml_file)
        _invalidate_cache()

        original = FieldConfig(
            version="5",
            fields=[
                FieldDef(name="alpha", display_name="Alpha Label", enabled=True),
                FieldDef(name="beta",  display_name="Beta Label",  enabled=False),
            ],
        )
        save(original)

        # Version should have been bumped on save
        assert yaml_file.exists()
        _invalidate_cache()
        reloaded = load()

        assert reloaded.version == "6"           # bumped from 5 → 6
        assert len(reloaded.fields) == 2
        assert reloaded.fields[0].name == "alpha"
        assert reloaded.fields[0].enabled is True
        assert reloaded.fields[1].name == "beta"
        assert reloaded.fields[1].enabled is False

    def test_save_creates_parent_directories(self, tmp_path, monkeypatch):
        """save() creates missing parent directories rather than raising FileNotFoundError."""
        nested = tmp_path / "a" / "b" / "underlying_field_config.yaml"
        monkeypatch.setattr(fc_module.config, "UNDERLYING_FIELD_CONFIG_FILE", nested)
        _invalidate_cache()
        cfg = FieldConfig(version="1", fields=[FieldDef(name="x", display_name="X", enabled=True)])
        save(cfg)   # should not raise
        assert nested.exists()
