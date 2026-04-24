"""
Underlying Data Module — Shared utilities.

Small functions used by more than one module within the ``underlying`` package.
Placed here to avoid circular imports between ``edgar_underlying_client`` and
``currentness`` (the former already imports from the latter).
"""
from __future__ import annotations


def detect_reporting_form(forms: list[str]) -> str:
    """Infer the primary reporting form from a filing history list.

    Scans the first 30 entries for ``20-F`` or ``40-F`` forms; falls back to
    ``"10-K"`` when neither is found (covers the vast majority of US issuers).

    Parameters
    ----------
    forms:
        The ``form`` list from ``submissions["filings"]["recent"]``.

    Returns
    -------
    str
        One of ``"10-K"``, ``"20-F"``, or ``"40-F"``.
    """
    sample = forms[:30]
    if any(f == "20-F" for f in sample):
        return "20-F"
    if any(f == "40-F" for f in sample):
        return "40-F"
    return "10-K"
