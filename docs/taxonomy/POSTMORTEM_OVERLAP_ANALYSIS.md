# Post-Mortem: Why the SP_MasterFile × Payout_to_Features Overlap Analysis Was Wrong

**Status:** Analysis result discarded. Must not be used in any process flow.

---

## What Was Attempted

A feature-vector scoring algorithm compared each product entry from SP_MasterFile
against all 196 entries in Payout_to_Features. For each SP product a 14-dimension
feature vector was derived from its sheet name and taxonomy labels (L1–L4). This
vector was scored against every PF entry using weighted matching, and entries
scoring ≥ 0.85 were reported as "high-confidence matches."

---

## Root Cause 1 — Category Error: Payout_to_Features Is a Pure Equity Taxonomy

The 22-dimensional feature vector in `payout_features.json` has exactly three
values for `PRODUCT_SUB_TYPE`: **GROWTH** (87), **PROTECTION** (63), **YIELD** (46).
Total: 196. There are **zero Credit Linked Note entries** in the file.

SP_MasterFile, by contrast, contains four full credit product families:

| Sheet                  | Entries |
|------------------------|---------|
| CLN zero coupon        | 7       |
| CLN fixed coupon       | 7       |
| CLN floating coupon    | 22      |
| Credit overlay         | 17      |
| **Total credit family**| **53**  |

The algorithm was asked to find overlaps between 53 credit products and a reference
taxonomy that contains no credit products at all. Every single one of those 53
matches is structurally a false positive.

---

## Root Cause 2 — No Asset-Class Dimension in the Feature Vector

The 22 dimensions in Payout_to_Features describe **product structure** (does it
have a barrier? is there autocall? is the coupon contingent?) but contain no
dimension for **underlying risk type** (equity risk vs. credit/default risk vs.
interest rate risk).

This means a CLN fixed coupon product and a Reverse Convertible can produce an
**identical feature vector**:

| Dimension                   | CLN (fixed, barrier on credit event) | Reverse Convertible (barrier on equity) |
|-----------------------------|--------------------------------------|------------------------------------------|
| PRODUCT_SUB_TYPE            | YIELD (assigned by algorithm)        | YIELD                                    |
| CALL_TYPE                   | NONE                                 | NONE                                     |
| DOWNSIDE_PROTECTION_TYPE    | NONE                                 | NONE                                     |
| COUPON_TYPE                 | FIXED                                | FIXED                                    |
| HAS_COUPON_BARRIER          | true (credit event = barrier)        | true (equity barrier)                    |
| HAS_COUPON_MEMORY           | false                                | false                                    |

Weighted score: 3+3+3+2+2+2 = **15/15 = 1.00** — a perfect match between two
completely unrelated products.

The defining characteristic of a CLN — that its risk is the **default probability
of a reference entity**, not the price path of an equity underlying — is simply
invisible to a feature vector designed for equity structured products.

---

## Root Cause 3 — The Mapping Function Collapsed Credit into Equity Categories

The `sp_to_features()` function in the matching script assigned CLN sheets to
`PRODUCT_SUB_TYPE = "YIELD"` because YIELD was the closest available category.
But "YIELD" in Payout_to_Features means yield-enhancement *equity* products
(autocallables, reverse convertibles, barrier notes). Assigning CLNs the same
label handed the algorithm a weight-3 match on the most discriminating dimension
before any other comparison happened.

---

## Root Cause 4 — The Algorithm Always Produces a Match

There is no "incompatible" outcome in the scoring function. Every SP entry is
ranked against all 196 PF entries and the best score is returned regardless of
how poor that score actually is in absolute terms. The 0.85 threshold was meant
to filter noise, but it is too easily reached when the top-3 categorical dimensions
(total weight 9 out of 23) all align superficially, as shown above for CLNs.

---

## What Could Have Prevented This

### Mandatory first-pass filter: asset class
Before any structural comparison, products should be sorted into non-overlapping
risk families:

- Equity-linked structured products
- Credit-linked / reference-entity-dependent products
- Rates / FX-linked products

Only products within the same family should ever be compared. CLNs should never
enter the comparison against the Payout_to_Features equity taxonomy.

### Explicit "no-match" outcome
If the best structural score is below a meaningful minimum (e.g. < 0.60), the
result should be reported as "no equivalent in reference taxonomy" rather than
forcing the closest equity proxy.

### Description-first validation
SP_MasterFile contains short textual descriptions per product. The CLN descriptions
explicitly mention "credit event", "reference entity", "default risk", "spread".
A keyword pre-filter on these terms would immediately quarantine the CLN family
from any equity taxonomy match before the vector scoring begins.

### Awareness of taxonomy scope before matching
Before running any cross-file comparison, the scope of each file should be checked:
"Does File A cover the same product universe as File B?" If one file covers equity
products only and the other includes credit products, the non-overlapping families
must be excluded from the comparison — or the absence of a match must itself be
treated as information.

---

## What This Analysis Is Good For (and What It Is Not)

**Valid for equity families only, with caveats:**
For the four equity-focused sheets in SP_MasterFile (Autocall, Capital protected,
Non-capital protected, Minimum redemption) the vector-based approach *may* produce
useful rough signals — those sheets and Payout_to_Features share the same
structural language. Even there, individual matches need manual validation because
the taxonomy labels in the two files do not use identical vocabulary.

**Not valid for credit families:**
All CLN and Credit overlay matches are false positives. The methodology cannot
produce meaningful results for these product families against the current
Payout_to_Features reference.

**Must not be used in the process flow:**
This analysis was a one-off exploratory exercise. Its output must not influence
PRISM classification, field extraction, schema mapping, or any automated step
in the ingestion pipeline. The correct approach for PRISM classification is the
document-evidence path already implemented (classifier + classificationHints),
not a cross-reference to this taxonomy overlap.

---

## Cleanup

- Script files `/tmp/overlap_*.py` and `/tmp/overlap_results.json` are in `/tmp`
  and will be cleaned up by the OS automatically.
- No output from this analysis has been persisted to `files/` as a reference.
- `ANALYSIS_SP_MASTERFILE.md` overlap section should be treated as preliminary
  notes only, not as validated findings.
