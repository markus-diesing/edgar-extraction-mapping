# SP_MasterFile × Payout_to_Features — Overlap Analysis (v2)

**Method:** Structural feature matching, done analytically entry-by-entry.
Only equity sheets are considered (EUSIPA 1xxx). All CLN and leverage sheets
are excluded before any comparison begins (see post-mortem).

**Matching rules applied:**
1. EUSIPA family filter first — no cross-family comparisons.
2. CALL_TYPE, DOWNSIDE_PROTECTION_TYPE, and COUPON_TYPE must all agree.
3. All material boolean flags (memory, coupon barrier, participation, capped,
   absolute return) must agree.
4. SP "Buffer" / "soft protection" concepts have no counterpart in PF — these
   are left unmatched rather than forcing a closest-neighbour.
5. FX treatment (Flexo / Quanto) and basket construction (worst-of, TOM strategy)
   are invisible in the PF feature vector — matches are flagged accordingly.

**Confidence levels:**
- **HIGH** — all key structural dimensions agree; only invisible dimensions differ
- **MEDIUM** — most dimensions agree; one material dimension is ambiguous

**Excluded from comparison (no PF counterpart):**
- CLN zero coupon, CLN fixed coupon, CLN floating coupon, Credit overlay (EUSIPA 3100)
- BULL & BEAR (2300), Warrants (2100/2110), Mini futures (2210), Turbos (2200)

---

## Matches

### Group A — Autocall sheet (EUSIPA 1260)

All SP autocall products share: CALL=AUTO_CALLABLE, PROT=BARRIER (risk barrier),
coupon conditioned on a coupon barrier. The two structural sub-variants are whether
unpaid coupons accumulate (memory) or not (flat). A third variant adds capital
guarantee (no risk barrier → PROT=FLOOR).

| SP entry | SP taxonomy | PF match | Matching dims | Notes |
|----------|------------|----------|---------------|-------|
| SE0006993184, SE0008587455 | Autocall > Worst of > Flat coupon | **Barrier Auto-Callable Contingent Yield Note** | CALL=AUTO, PROT=BARRIER, CPN=CONTINGENT, HAS_COUPON_BARRIER=T, memory=F | HIGH. Coupon depends on coupon barrier (contingent). Worst-of construction invisible in PF. |
| FI4000053178, SE0006261947, SE0004575314, FI4000177118, SE0005506029, SE0005506029 | Autocall > Worst of or Single underlying > Memory coupon | **Barrier Auto-Callable Memory Yield Note** | CALL=AUTO, PROT=BARRIER, CPN=CONTINGENT, HAS_COUPON_BARRIER=T, HAS_COUPON_MEMORY=T | HIGH. SP has both multi- and single-underlying variants; all map to the same PF entry since PF has no worst-of dimension. |
| XS1311310384 | Autocall > Worst of > Memory coupon > Capital guaranteed | **Floor Auto-Callable Memory Yield Note** | CALL=AUTO, PROT=FLOOR, CPN=CONTINGENT, HAS_COUPON_BARRIER=T, HAS_COUPON_MEMORY=T | HIGH. Capital protection removes the risk barrier → PROT=FLOOR instead of BARRIER. |

**Not matched (Autocall sheet):**
- *Two-coupon variants* (SE0006993192, SE0005366390, XS1322968394): a flat coupon and a memory coupon coexist on the same product. PF has no dual-coupon structure — no clean match.
- *FX / currency pair underlying* (FI4000149547): autocall on a currency pair. PF has no FX underlying dimension — excluded rather than forced.

---

### Group B — Capital protected sheet (EUSIPA 1100 / 1120 / 1140)

All entries have full 100% capital protection. PF maps these to PROT=FLOOR (a guaranteed minimum at the protection level) or PROT=FULL. CALL=NONE throughout. The sub-variants are upside shape (uncapped, capped, digital, rainbow) and whether a coupon also accompanies the participation.

| SP entry | SP taxonomy | PF match | Matching dims | Notes |
|----------|------------|----------|---------------|-------|
| CP 1, 2, 7, 8, 9, 12, 14, 26, 31 (EUSIPA 1100) | Multi/single underlying > Participation ratio > Flexo or Quanto | **Floor Uncapped Growth Note** | CALL=NONE, PROT=FLOOR, CPN=NONE, HAS_UPSIDE_PARTICIPATION=T | HIGH. Uncapped equity participation with capital floor. FX treatment (Flexo/Quanto) invisible. |
| CP 3, 4 (EUSIPA 1100) | Multi underlying with best replacement > Participation ratio | **Floor Uncapped Growth Note** | CALL=NONE, PROT=FLOOR, CPN=NONE, HAS_UPSIDE_PARTICIPATION=T | HIGH. Best-replacement basket is a construction variant; structural payoff is identical to plain participation. |
| CP 5, 16 (EUSIPA 1120) | Multi underlying > Participation ratio > Capped | **Floor Capped Growth Note** | CALL=NONE, PROT=FLOOR, CPN=NONE, HAS_UPSIDE_PARTICIPATION=T, HAS_MAXIMUM_RETURN=T | HIGH. Capped upside with capital floor. |
| CP 6 (EUSIPA 1120) | Multi underlying > Capped coupon | **Floor Contingent Yield CD** | CALL=NONE, PROT=FLOOR, CPN=CONTINGENT, HAS_COUPON_BARRIER=T | MEDIUM. Coupon paid if basket positive = contingent on performance. Cap on coupon = HAS_MAXIMUM_RETURN, which PF does not flag for this entry. |
| CP 27, 28, 29, 30, 36 (EUSIPA 1100) | Single/multi underlying > Participation ratio > Fixed coupon (Guaranteed) | **Floor Fixed Yield Uncapped Growth Note** | CALL=NONE, PROT=FLOOR, CPN=FIXED, HAS_UPSIDE_PARTICIPATION=T | HIGH. Guaranteed fixed coupon paid regardless of performance, plus upside participation. |
| CP 35 (EUSIPA 1100) | Multi underlying FX > Participation ratio > Rainbow | **Floor Capped Allocation CD** | CALL=NONE, PROT=FLOOR, CPN=NONE, HAS_UPSIDE_PARTICIPATION=T, HAS_RAINBOW=T | HIGH. Rainbow/best-of basket structure matches HAS_RAINBOW. FX pairing invisible. |
| CP 15 (EUSIPA 1100) | Multi underlying FX > Participation ratio > Best of | **Floor Capped Allocation CD** | CALL=NONE, PROT=FLOOR, CPN=NONE, HAS_UPSIDE_PARTICIPATION=T, HAS_RAINBOW=T | HIGH. "Best of" is semantically the same as Rainbow in PF terminology. |
| CP 20, 21, 37, 38, 39 (EUSIPA 1120, rate-linked) | Single underlying (rate) > Floating interest > Cap or Floor and cap | **Floor Floating Yield CD** | CALL=NONE, PROT=FLOOR, CPN=FLOATING | HIGH. Capital protected, floating rate coupon. Floor/cap on the rate itself is a feature not captured in PF. |
| CP 19 (EUSIPA 1100, rate-linked) | Single underlying (interest rate) > Fixed interest rate, accumulated | **Floor Fixed Yield Note** | CALL=NONE, PROT=FLOOR, CPN=FIXED | HIGH. Compounding fixed interest with capital protection = fixed yield + floor. |

**Not matched (Capital protected sheet):**
- *Turn-of-month strategy* (CP 10, 11, 13, 31): the underlying performance is calculated on a monthly rebalancing rule (TOM). PF has no strategy/path-dependent dimension — excluded.
- *Monthly capped + lock-in* (CP 32, EUSIPA 1140): performance cap applied monthly with a lock-in on accumulated gains. No PF equivalent for lock-in mechanics.
- *CMS spread / relative difference between two rates* (CP 18, 22, 23, 24, 33, 34, 40): these link return to the spread between two interest rates. PF has no rate-differential or CMS dimension. Structurally similar to range accrual but not the same.
- *CP 42 (EUSIPA 1120, barrier on rate spread)*: conditional capital protection dependent on a rate barrier. PROT is conditionally FLOOR — PF has no "conditional floor" concept.

---

### Group C — Non-capital protected sheet (EUSIPA 1240–1340 / 2100)

Pre-filter applied: entries with EUSIPA 2100 / 2110 (warrant-style, total loss possible) are excluded — they have no PF counterpart in the equity investment taxonomy.

Remaining entries (EUSIPA 1240–1340) are yield enhancement and participation certificates where the downside risk is full equity exposure below a barrier (or unconditionally).

| SP entry | SP taxonomy | PF match | Matching dims | Notes |
|----------|------------|----------|---------------|-------|
| NCP 1, 9, 10, 16, 17 (EUSIPA 1330) | Single/multi underlying > Participation ratio > European DIP Barrier | **Barrier Uncapped Growth Note** | CALL=NONE, PROT=BARRIER, CPN=NONE, HAS_UPSIDE_PARTICIPATION=T | HIGH. Participation above strike; full downside below European barrier at maturity. |
| NCP 5, 7 (EUSIPA 1240) | Single underlying > Participation ratio > Capped > European DIP Barrier | **Barrier Capped Growth Note** | CALL=NONE, PROT=BARRIER, CPN=NONE, HAS_UPSIDE_PARTICIPATION=T, HAS_MAXIMUM_RETURN=T | HIGH. Capped participation + hard barrier. |
| NCP 23 (EUSIPA 1240) | Single underlying > Participation ratio > Capped > American DIP Barrier | **Barrier Capped Growth Note** | CALL=NONE, PROT=BARRIER, CPN=NONE, HAS_UPSIDE_PARTICIPATION=T, HAS_MAXIMUM_RETURN=T | HIGH. Structurally identical to European barrier variant at the PF feature level; observation style (American vs. European) is not captured in PF. |
| NCP 11 (EUSIPA 1320) | Single underlying > Fixed coupon > American DIP Barrier | **Barrier Fixed Yield Note** | CALL=NONE, PROT=BARRIER, CPN=FIXED | HIGH. Guaranteed fixed coupon (always paid) + hard downside barrier. The American vs. European observation style is not a PF dimension. |
| NCP 12, 22 (EUSIPA 1320) | Multi/single underlying > Fixed coupon (guaranteed) > European or American DIP Barrier | **Barrier Fixed Yield Note** | CALL=NONE, PROT=BARRIER, CPN=FIXED | HIGH. Same as NCP 11. Worst-of construction invisible in PF. |
| NCP 8 (EUSIPA 1340) | Single underlying > 2 Participation ratios > Twin win > European DIP Barrier | **Barrier Dual Directional Uncapped Growth Note** | CALL=NONE, PROT=BARRIER, CPN=NONE, HAS_UPSIDE_PARTICIPATION=T, HAS_ABSOLUTE_RETURN=T | HIGH. Twin-win = absolute return (profit in both directions). Barrier applies if touched at maturity. |

**Not matched (Non-capital protected sheet):**
- *EUSIPA 2100 / 2110 warrant-style* (NCP 2, 14, 15): total loss of invested capital possible. PF GROWTH sub-type does not include total-loss products. Excluded by family filter.
- *Floating coupon (guaranteed) + barrier, worst-of* (NCP 6, 20, 39, EUSIPA 1250): SP describes a guaranteed floating coupon with a hard downside barrier. PF entries combining barrier + floating coupon all have HAS_COUPON_BARRIER=true (conditional coupon), which contradicts the SP's guaranteed coupon. No clean match.
- *Coupon + participation ratio + barrier* (NCP 21, 24, 25, 26, EUSIPA 1320): the payoff is max(coupon, equity participation) or coupon + participation below barrier. PF has no "maximum of two payoffs" dimension. Excluded.
- *Simple tracker, no barrier* (NCP 4, 27, EUSIPA 1310): pure 1:1 participation with no protection. PF GROWTH entries with PROT=NONE are "Uncapped Growth Note" (PROT=FULL) or "Digital Uncapped Growth Note" — neither maps cleanly to an unprotected tracker with full downside.
- *Rate-linked / FX-linked* (NCP 19, 28, 29, 34, 36, 41): various interest-rate differential, CMS spread, and FX structured payoffs. Not representable in the equity-feature PF vector.

---

### Group D — Minimum redemption sheet (EUSIPA 1240 / 1320 / 1330)

These are structurally identical to capital protected participation notes, but with a partial floor (e.g. 80–90% of nominal rather than 100%). PF maps all of these to PROT=FLOOR — the same code as for 100% capital protected products. PF does not capture the floor level, so minimum redemption and capital protected products with the same upside shape collapse to the same PF entry.

| SP entry | SP taxonomy | PF match | Matching dims | Notes |
|----------|------------|----------|---------------|-------|
| MR 1, 3, 5, 6, 7, 8, 9, 11, 14, 15, 16, 18 (EUSIPA 1330) | Single/multi underlying > Participation ratio | **Floor Uncapped Growth Note** | CALL=NONE, PROT=FLOOR, CPN=NONE, HAS_UPSIDE_PARTICIPATION=T | HIGH. Payoff structure identical to Capital Protected uncapped. PF cannot distinguish floor level. |
| MR 2, 10, 12, 17 (EUSIPA 1240) | Single/multi underlying > Participation ratio > Capped | **Floor Capped Growth Note** | CALL=NONE, PROT=FLOOR, CPN=NONE, HAS_UPSIDE_PARTICIPATION=T, HAS_MAXIMUM_RETURN=T | HIGH. Capped participation + partial floor. Indistinguishable from Capital Protected capped at PF feature level. |
| MR 4 (EUSIPA 1320) | Single underlying > Participation ratio > Guaranteed fixed coupon | **Floor Fixed Yield Uncapped Growth Note** | CALL=NONE, PROT=FLOOR, CPN=FIXED, HAS_UPSIDE_PARTICIPATION=T | HIGH. Partial floor + guaranteed coupon + participation. |

**Not matched (Minimum redemption sheet):**
- *Interest-rate linked partial protection* (MR 13, EUSIPA 1240, CMS spread / floating interest floor and cap): same reasoning as Capital Protected rate-linked. No PF equivalent for CMS spread mechanics.

---

## Consolidated Match Table

| # | SP Sheet | SP EUSIPA | SP Structural Category | PF Match | Confidence |
|---|---------|-----------|------------------------|----------|------------|
| 1 | Autocall | 1260 | Worst-of / single, flat/contingent coupon, coupon barrier, risk barrier | Barrier Auto-Callable Contingent Yield Note | HIGH |
| 2 | Autocall | 1260 | Worst-of / single, memory coupon, coupon barrier, risk barrier | Barrier Auto-Callable Memory Yield Note | HIGH |
| 3 | Autocall | 1260 | Capital guaranteed autocall, memory coupon | Floor Auto-Callable Memory Yield Note | HIGH |
| 4 | Capital protected | 1100 | Equity participation, uncapped, no coupon | Floor Uncapped Growth Note | HIGH |
| 5 | Capital protected | 1100 | Equity participation, uncapped, no coupon, best-replacement basket | Floor Uncapped Growth Note | HIGH |
| 6 | Capital protected | 1120 | Equity participation, capped, no coupon | Floor Capped Growth Note | HIGH |
| 7 | Capital protected | 1100 | Equity participation, guaranteed fixed coupon at each date or maturity | Floor Fixed Yield Uncapped Growth Note | HIGH |
| 8 | Capital protected | 1100 | Rainbow / best-of basket, participation, no coupon | Floor Capped Allocation CD | HIGH |
| 9 | Capital protected | 1120 | Floating reference rate, capital floor | Floor Floating Yield CD | HIGH |
| 10 | Capital protected | 1100 | Fixed accumulated interest rate, capital floor | Floor Fixed Yield Note | HIGH |
| 11 | Capital protected | 1120 | Coupon contingent on basket performance, capped coupon | Floor Contingent Yield CD | MEDIUM |
| 12 | Non-capital prot. | 1330 | Equity participation, European barrier at maturity | Barrier Uncapped Growth Note | HIGH |
| 13 | Non-capital prot. | 1240 | Equity participation, capped, European or American barrier | Barrier Capped Growth Note | HIGH |
| 14 | Non-capital prot. | 1320 | Guaranteed fixed coupon, American or European barrier | Barrier Fixed Yield Note | HIGH |
| 15 | Non-capital prot. | 1340 | Twin-win (absolute return), European barrier | Barrier Dual Directional Uncapped Growth Note | HIGH |
| 16 | Minimum redemption | 1330 | Equity participation, uncapped, partial floor | Floor Uncapped Growth Note | HIGH |
| 17 | Minimum redemption | 1240 | Equity participation, capped, partial floor | Floor Capped Growth Note | HIGH |
| 18 | Minimum redemption | 1320 | Guaranteed fixed coupon, participation, partial floor | Floor Fixed Yield Uncapped Growth Note | HIGH |

---

## What the PF Feature Vector Cannot Distinguish

Several important distinctions that exist in the SP taxonomy are invisible in PF:

| SP distinction | PF status |
|---------------|-----------|
| 100% capital protection vs. minimum redemption (e.g. 80%) | Both → PROT=FLOOR. Floor level not captured. |
| Worst-of multi-underlying vs. single underlying | Not a PF dimension. |
| European barrier (at maturity only) vs. American barrier (continuous) | Not a PF dimension. |
| FX-exposed (Flexo) vs. FX-hedged (Quanto) | Not a PF dimension. |
| Classic basket vs. best-replacement vs. rainbow basket | Only rainbow captured (HAS_RAINBOW). |
| Turn-of-month performance strategy | Not a PF dimension. |
| Lock-in feature on accumulated gains | Not a PF dimension. |
| CMS spread / rate differential underlying | Not a PF dimension (PF is equity-centric). |

These gaps are by design — PF describes US-market structured note archetypes, while SP_MasterFile covers Nordics/European market specifics. The overlaps found above are real, but the PF taxonomy will never be a complete representation of the SP product universe.
