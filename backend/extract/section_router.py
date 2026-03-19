"""
section_router.py — maps PRISM model names to ordered section groups for
section-by-section extraction.

Section specs (system_note, search_headers, max_chars) live in
files/sections/section_specs.yaml and are loaded via sections.section_loader.
"""
from dataclasses import dataclass, field
from typing import Any
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import sections.section_loader as section_loader

@dataclass
class SectionSpec:
    name: str
    schema_keys: list[str]
    search_headers: list[str]
    max_chars: int
    system_note: str
    required_for: set[str] = field(default_factory=set)


# Maps model name → ordered list of section names to run
MODEL_SECTIONS: dict[str, list[str]] = {
    "yieldEnhancementCoupon": [
        "identifiers", "product_generic", "underlying_terms",
        "protection", "coupon", "parties",
    ],
    "yieldEnhancementBarrierCoupon": [
        "identifiers", "product_generic", "underlying_terms",
        "protection", "coupon", "parties",
    ],
    "yieldEnhancementAutocallCoupon": [
        "identifiers", "product_generic", "underlying_terms",
        "protection", "autocall", "coupon", "parties",
    ],
    "yieldEnhancementAutocallBarrierCoupon": [
        "identifiers", "product_generic", "underlying_terms",
        "protection", "autocall", "coupon", "parties",
    ],
    "yieldEnhancementAutocall": [
        "identifiers", "product_generic", "underlying_terms",
        "protection", "autocall", "parties",
    ],
    "forwardKoStripEquity": [
        "identifiers", "product_generic", "underlying_terms", "parties",
    ],
    "equityShare": ["identifiers", "parties"],
    "index":       ["identifiers"],
    "depositaryReceipt": ["identifiers", "parties"],
}

_ALL_SECTIONS = [
    "identifiers", "product_generic", "underlying_terms",
    "protection", "autocall", "coupon", "parties",
]


def _build_spec(name: str, raw: dict) -> SectionSpec:
    return SectionSpec(
        name=name,
        schema_keys=raw.get("schema_keys", []),
        search_headers=raw.get("search_headers", []),
        max_chars=raw.get("max_chars", 10000),
        system_note=raw.get("system_note", ""),
        required_for=set(raw.get("required_for", [])),
    )


def get_sections_for_model(model_name: str) -> list[SectionSpec]:
    """Return ordered list of SectionSpec for the given model name.
    Falls back to all sections for unrecognised model names."""
    raw_specs = section_loader.get_section_specs()
    section_names = MODEL_SECTIONS.get(model_name, _ALL_SECTIONS)
    result = []
    for sname in section_names:
        if sname in raw_specs:
            result.append(_build_spec(sname, raw_specs[sname]))
    return result


def get_all_section_specs() -> dict[str, SectionSpec]:
    """Return all section specs as a dict (for inspection / testing)."""
    raw_specs = section_loader.get_section_specs()
    return {name: _build_spec(name, raw) for name, raw in raw_specs.items()}
