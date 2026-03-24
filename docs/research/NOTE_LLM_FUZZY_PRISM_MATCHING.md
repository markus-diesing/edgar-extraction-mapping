# LLM-Based PRISM Model Matching — Fuzzy Recognition Without 1:1 Correspondence

**Author:** Markus / Claude Code
**Date:** 2026-03-22
**Context:** Arose from discussion of whether an LLM can correctly assign a PRISM model to a filing that does not exactly match any of the 196 payout types in Payout_to_Features.xlsx

---

## The Question

If we add classificationHints to the PRISM schema and present the 196-item payout feature list as context, can an LLM correctly recognise a filing's PRISM model even when the filing is not a 1:1 match to any entry in the list?

**Answer: yes — and this is one of the things LLMs do genuinely well.**

---

## Why LLMs Tolerate Imperfect Matches

An LLM reading classificationHints and an extracted feature dict does not do exact string matching. It reasons about similarity. If the hints describe *"pays a contingent coupon above a barrier, autocalls at par plus coupon, capital at risk below a knock-in"* and the filing has a contingent coupon, a step-down autocall trigger, and a barrier — but no memory feature — the LLM will still assign that PRISM model with high confidence. It recognises the structural family, not an exact template.

This is fundamentally different from a lookup table, which either matches or fails.

---

## Why the Vocabulary Match Is Strong Here

The 22-feature vocabulary from the xlsx uses the same semantic terms that appear verbatim or near-verbatim in EDGAR filings: "contingent coupon", "knock-in barrier", "autocall trigger", "buffer protection". The classificationHints will use the same language. The LLM is doing semantic alignment between two things written in the same financial vocabulary — not between a document and an abstract schema.

---

## Why the Cluster Structure Protects Accuracy

The four top-level features (PRODUCT_SUB_TYPE, DOWNSIDE_PROTECTION_TYPE, COUPON presence/type, CALL_TYPE) produce tight, stable clusters — one per PRISM model. Secondary features vary within a cluster but do not change the PRISM assignment. The LLM only needs to get the cluster right, and cluster-level reasoning is substantially more robust to variation than exact-variant matching.

This means a novel product that has never appeared in any training data will still land in the right PRISM cluster as long as it shares the defining features of that cluster.

---

## Where It Can Still Fail

**Adjacent model confusion:** Two PRISM models that share many features (e.g. a yield-enhancement note with a buffer vs. with a barrier) can confuse the classifier when the filing uses vague downside language. Counter-features in the model profile address this: the profile for each model explicitly contra-indicates the features that distinguish its nearest neighbour.

**Genuinely novel models:** A product that doesn't fit any existing PRISM model will still be assigned the closest one rather than producing an "I don't know" output. The three-state confidence system (classified / needs_classification_review / needs_review) is the safeguard: low confidence surfaces the case to a human rather than silently misclassifying it.

---

## What the 196-Item List Adds for the LLM

The list is not presented row by row. It provides **vocabulary density** — the named payout type labels ("Barrier Auto-Callable Memory Yield Note", "Buffer Dual Directional Digital Uncapped Growth Note") give the LLM a richer description of what falls within each PRISM cluster. The LLM uses this not for lookup but for context: it builds a better internal model of the cluster's boundary conditions and edge cases.

A filing that calls itself "Contingent Income Auto-Callable Securities" will match `yieldEnhancementAutocall` not because that title appears in the list, but because feature extraction produces YIELD + BARRIER + CONTINGENT + AUTO_CALLABLE, which lands squarely in that cluster — which the list helped define.

---

## The Combined Effect

`classificationHints` (model-level prose + feature profile) + the 22-dimension feature vocabulary (from Payout_to_Features) + cluster-aware model profiles (required / typical / counter-features) gives the LLM:

- Enough context to classify all known product variants correctly
- Graceful degradation to "closest cluster" for novel variants (rather than hard failure)
- A confidence signal that distinguishes certain assignments from uncertain ones

The system is robust to new product variants in the same way a knowledgeable human analyst is: the analyst has never seen that exact term sheet before, but recognises the structural family immediately from its defining features.

---

## Implication for System Design

The 196-item list should never be positioned as a lookup gate. It is a vocabulary and calibration resource. Classification is always performed at the PRISM-model level using feature profiles; the list enriches and validates that classification but does not determine it. A filing that matches none of the 196 types is not an error — it is either a known-cluster novel variant (classified with normal confidence) or a genuinely new product type (flagged for review).
