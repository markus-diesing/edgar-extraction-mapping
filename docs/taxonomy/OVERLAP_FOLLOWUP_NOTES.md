# Overlap Analysis — Follow-up Notes

**Date:** 2026-03-23
**Status:** Parked, ready to resume

---

## What was established

1. **18 high-confidence matches** between SP_MasterFile equity products and the Payout_to_Features
   taxonomy exist, covering four product families: Autocall (1260), Capital Protected (1100/1120),
   Non-Capital Protected (1240–1340), and Minimum Redemption.
   Full table: see `OVERLAP_SP_VS_PAYOUT_FEATURES.md`.

2. **CLN and leverage products have zero overlap** with the Payout_to_Features taxonomy.
   PF is an equity-only structured product vocabulary. EUSIPA 3100 (CLN) and 2xxx (leverage) are
   categorically distinct and must never be compared against PF entries.

3. **What PF cannot distinguish** (dimensions missing from the 22-feature vector):
   - Floor level (100% capital protection vs. 80% minimum redemption)
   - Worst-of vs. single underlying
   - European vs. American barrier observation
   - FX treatment (Quanto vs. Flexo)
   - Turn-of-month or path-dependent strategies
   - CMS spread / rate-differential underlyings
   - Lock-in features

4. **First algorithm failure root cause** (see `POSTMORTEM_OVERLAP_ANALYSIS.md`):
   - No asset-class dimension in the 22-dim vector
   - All CLN entries forcibly mapped to PRODUCT_SUB_TYPE="YIELD" (wrong)
   - Algorithm always produces a "best" match — it had no null output
   - Structural features (coupon, barrier) looked similar even across credit/equity boundary

---

## Open questions for follow-up

- **How far does the PF ↔ SP match set extend to the PRISM model layer?**
  PF has 196 entries; only 9 PRISM models exist today. Mapping the 18 matched groups
  to PRISM models requires the PF → PRISM mapping that is still in progress (see OPEN_TASKS A1).

- **Can we invert the matching for EDGAR ingestion?**
  If a new EDGAR filing is classified as `yieldEnhancementAutocallBarrierCoupon` (PRISM),
  can we use the PF matches to confirm which SP_MasterFile template family it resembles?
  This would be a useful cross-check, but only after the PF → PRISM bridge is built.

- **CMS spread / rate-linked capital protected notes** (CP 17–24, 33–34, 37–40):
  These are not representable in PF. If PRISM ever adds interest-rate structured product
  models, these SP entries would be the reference dataset.

- **Credit overlay products** (SP_MasterFile "Credit overlay" sheet):
  These combine credit default risk on a reference basket with equity upside participation.
  They sit between the credit and equity families. No PRISM model for this yet; worth
  flagging when the PRISM team expands into credit products.

---

## Recommended next action

When the PF → PRISM mapping becomes available, run: for each of the 18 matched SP/PF groups,
identify which PRISM model(s) the PF entry maps to. This will produce a three-way
SP ↔ PF ↔ PRISM lookup table that can be used to validate future EDGAR classifications.
