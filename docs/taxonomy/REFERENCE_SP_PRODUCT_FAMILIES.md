# SP_MasterFile — Product Families Reference

Derived from SP_MasterFile.xlsx sheet names, EUSIPA codes, Short descriptions,
and Level 1–4 taxonomy labels. Purpose: establish a shared vocabulary for future
ingestion decisions — specifically, to prevent cross-family comparison errors.

---

## The Three Fundamental Families

Before any structural comparison can be made, every structured product must be
assigned to one of three non-overlapping families. Products from different families
**must never be compared against each other** on structural dimensions alone.

| Family | EUSIPA Range | MiFID Type | Primary Risk Driver |
|--------|-------------|------------|---------------------|
| **Investment Products** | 1xxx | 1a / 1b | Equity / index price path |
| **Leverage Products** | 2xxx | 1c | Leveraged equity / option payoff |
| **Credit Products** | 3xxx | 1b | Default / credit event on reference entities |

The EUSIPA code is the **fastest single-field family discriminator**. It appears
consistently in SP_MasterFile and in most European term sheets. When available,
it should be used as the mandatory first-pass filter before any further comparison.

---

## Family 1 — Investment Products (EUSIPA 1xxx)

These are structured notes or certificates with an equity or basket underlying.
The investor takes equity market risk but the payoff is shaped (capped, protected,
autocalled). No leverage, no credit risk as primary driver. Typically long-dated
(1–7 years).

### 1A — Capital Protected (EUSIPA 1100 / 1120 / 1140)
**Sheet:** `Capital protected` (40 product variants)

- Full 100% capital protection at maturity regardless of underlying performance.
- Upside: participation in positive basket/index performance, sometimes capped.
- Sub-variants by FX treatment: **Flexo** (FX-exposed), **Quanto** (FX-hedged).
- Sub-variants by upside shape: uncapped participation, capped, with average/Asian end,
  digital redemption bonus, range accrual.
- EUSIPA 1120 = Capital Protected Certificate with Barrier (conditional extra return);
  EUSIPA 1140 = Capital Protected Convertible.

**Key fields:** capital protection level (always 100%), participation ratio,
performance cap (if any), FX exposure, basket composition.

**Why this family cannot overlap with CLNs:** capital protection here means the
issuer guarantees full principal return via a bond floor. In a CLN, the nominal
can be reduced by credit events — the "protection" is credit-event-contingent,
not issuer-guaranteed.

---

### 1B — Autocall / Express Certificates (EUSIPA 1260)
**Sheet:** `Autocall` (12 product variants)

- Multi-underlying, worst-of observation.
- Three barrier levels: **call barrier** (triggers early redemption), **coupon barrier**
  (triggers periodic coupon payment), **risk barrier** (determines downside loss at maturity).
- Early redemption: if all underlyings are at or above the call barrier on any observation
  date, the note redeems at par + coupon.
- At maturity: three outcomes — full pay (above coupon barrier), par only (between coupon
  and risk barrier), or capital loss proportional to worst-performing underlying.
- Sub-variants by coupon: **flat coupon** (no memory) vs. **memory coupon** (unpaid
  coupons accumulate and are paid when barrier condition is met).

**Key fields:** call barrier, coupon barrier, risk barrier, observation dates,
coupon rate, memory flag.

**PRISM relevance:** directly maps to `yieldEnhancementAutocallCoupon` and
`yieldEnhancementAutocallBarrierCoupon` model families.

---

### 1C — Non-Capital Protected (EUSIPA 1240–1340 + 2100 / 2110)
**Sheet:** `Non-capital protected` (40 product variants)

The widest category. No guarantee of principal return. EUSIPA codes span from
investment certificates (13xx) to warrant-like structures (21xx) where full loss
is possible.

Sub-families present:

| Sub-type | EUSIPA | Description |
|----------|--------|-------------|
| Outperformance / Bonus Certificate | 1330 | Participation in upside; barrier protects at maturity if not breached |
| Capped Outperformance | 1240 | As above, but upside capped |
| Reverse Convertible / Discount | 1310 / 1320 | Coupon/discount paid; downside full equity exposure |
| Twin Win | 1340 | Absolute return: positive payoff in both rising and falling market |
| Warrant-style | 2100 / 2110 | High participation, total loss if out-of-money |

**Key discriminating sub-type questions:**
- Is there a barrier at maturity? → Bonus/outperformance family
- Is there a coupon / discount in exchange for downside? → Reverse convertible / discount
- Is there both up and down positive performance? → Twin Win / Absolute Return
- Can 100% of invested amount be lost? → Warrant-style (EUSIPA 21xx)

---

### 1D — Minimum Redemption (EUSIPA 1240 / 1320 / 1330)
**Sheet:** `Minimum redemption` (18 product variants)

Partial capital protection: the investor is guaranteed a **minimum redemption
amount** (e.g. 80–90% of nominal), not full 100%. The upside participates in
basket performance above the floor, sometimes capped.

Structurally a bridge between Capital Protected and Non-Capital Protected:
- Higher protection level than typical barrier certificates.
- Lower protection than full capital guarantee.

Sub-variants: single underlying, multi underlying, with/without FX (Flexo/Quanto),
capped or uncapped upside.

---

## Family 2 — Leverage Products (EUSIPA 2xxx)

Short-dated, directional instruments with leverage. Full or near-full loss of
invested capital is a normal (not exceptional) scenario. MiFID type 1c.
**These products share no structural vocabulary with investment certificates.**
A "barrier" in a turbo is a knock-out trigger, not a capital protection floor.

### 2A — Warrants (EUSIPA 2100)
**Sheet:** `Warrants` (4 product variants)

Vanilla cash-settled PUT or CALL warrants. European exercise. Two sub-variants:
- Asian end: closing price = average over a final observation period.
- Standard end: single valuation date.
Payoff = max(0, strike − closing price) for PUT; total loss if out-of-the-money.

---

### 2B — Turbos / Knock-Out Warrants (EUSIPA 2200)
**Sheet:** `Turbos` (4 product variants)

Fixed-term (not open-end) knock-out certificates. Long or short direction.
Key mechanism: if the underlying touches the **knock-out level** at any point
during the lifetime, the note redeems immediately with partial or total capital loss.
If not knocked out, payoff = closing price − strike price (for long).
Dividends not adjusted in the underlying calculation.

---

### 2C — Mini Futures (EUSIPA 2210)
**Sheet:** `Mini futures` (4 product variants)

Open-end (no fixed maturity). The **financing level** (= strike) and **stop-loss
level** are adjusted daily. If the underlying reaches the stop-loss level,
early redemption occurs; some residual value may be returned (unlike total
knock-out). Dividends may be adjusted. Long or short variants.

---

### 2D — Constant Leverage / Bull & Bear Certificates (EUSIPA 2300)
**Sheet:** `BULL & BEAR` (8 product variants)

Daily rebalanced constant leverage certificates. Open-end. The note's **daily
performance = underlying's daily performance × leverage factor**.
- BULL: long direction
- BEAR: short/inverse direction
Total loss on a single day if (|daily performance| × leverage) ≥ 100%.
Sub-variants: Flexo (FX-exposed) vs. no Flexo; dividend-adjusted vs. not.

**This family is fundamentally different from all other families:** the payoff is
path-dependent at a daily granularity. There is no meaningful maturity payoff
formula; the value decays through daily compounding (volatility drag).

---

## Family 3 — Credit Products (EUSIPA 3100 / 3101)

The primary risk driver is the **default / credit event on one or more reference
entities** (a credit basket), not the price performance of an equity underlying.
A credit event (bankruptcy, failure to pay, restructuring, governmental intervention)
reduces the nominal amount or triggers loss of recovery value.

The coupon (zero, fixed, or floating) is structurally similar to an investment
product coupon — but its economic role is compensation for bearing credit risk,
not equity risk. These are also MiFID type 1b but are **incompatible with the
Payout_to_Features equity taxonomy** because that taxonomy has no credit-event
dimension.

### 3A — CLN Zero Coupon (EUSIPA 3100)
**Sheet:** `CLN zero coupon` (7 product variants)

No periodic coupon. The note pays a **target redemption amount** at maturity.
Each credit event in the basket reduces the target by a predefined percentage
(linear loss) or zero recovery.

Sub-variants by loss mechanism: **linear** (each credit event reduces proportionally),
**tranched mezzanine** (a buffer absorbs first N events; additional events cause
outsized loss).

---

### 3B — CLN Fixed Coupon (EUSIPA 3100)
**Sheet:** `CLN fixed coupon` (7 product variants)

Fixed interest paid on each interest payment date (on the adjusted nominal).
Nominal is reduced by credit events. Two recovery variants:
- **Zero recovery:** entire basket exposure lost on credit event.
- **Market recovery (SAE):** market recovery value of the defaulted entity is
  paid at the next interest payment date; note continues on adjusted nominal.

Sub-variants: linear, tranched mezzanine (buffer), tranched junior/equity (first
loss tranche — most risky).

---

### 3C — CLN Floating Coupon (EUSIPA 3100)
**Sheet:** `CLN floating coupon` (22 product variants)

Floating interest (reference rate + margin) paid on adjusted nominal.
Otherwise structurally identical to fixed coupon CLN, with the same credit
event mechanics and tranche sub-variants.

Additional sub-variant unique to this sheet: **split coupon** — a fixed margin
paid on the *adjusted* nominal (credit-risky part) plus a floating reference rate
paid on the full *nominal* (non-risky part). This is the most complex coupon
structure in the entire file.

Tranches present: linear, junior/equity (first loss), mezzanine (buffer).

---

### 3D — Credit Overlay (EUSIPA 3100 / 3101)
**Sheet:** `Credit overlay` (17 product variants)

A **hybrid structure**: the primary risk is credit default (as in CLNs), but
the product additionally links the redemption amount or a bonus payment to the
performance of an equity basket.

- Credit basket determines the maximum redemption amount (target or nominal).
- Equity basket determines the upside bonus via a participation ratio.
- Both Flexo (FX-exposed) and Quanto (FX-hedged) variants exist.

**This is the most important family to classify correctly.** It is superficially
similar to a capital protected equity note (participation + floor), but the floor
is **credit-event-contingent**, not issuer-guaranteed. The presence of "credit
basket", "observation period", "credit event exposure" in the term sheet is
the distinguishing signal.

---

## Summary: Decision Tree for Future Ingestion

When encountering a new product or range of products:

```
Step 1 — Check EUSIPA code (or equivalent standard code)
         1xxx → Family 1: Investment Product (equity-linked)
         2xxx → Family 2: Leverage Product (stop here if no PRISM model exists)
         3xxx → Family 3: Credit Product (stop here if no PRISM model exists)

Step 2 — Within Family 1, identify sub-family:
         Does the term sheet mention "credit event" or "reference entity"?
           → Re-classify as Family 3, not Family 1.
         Is principal 100% protected regardless of underlying?
           → 1A Capital Protected
         Is there a minimum redemption amount (>0, <100%)?
           → 1D Minimum Redemption
         Is there autocall / early redemption observation?
           → 1B Autocall / Express
         Otherwise:
           → 1C Non-Capital Protected (check for barrier, twin-win, reverse convertible)

Step 3 — Only now compare structural features (barrier level, coupon type,
         autocall mechanics, participation) against the reference taxonomy.
```

---

## PRISM Model Coverage (Current)

All nine current PRISM models map to **Family 1 — Investment Products** only.
No PRISM model currently covers Family 2 (Leverage) or Family 3 (Credit).

When a Family 2 or Family 3 product is ingested, the classifier should:
- Recognize that no PRISM model matches by design (not by poor classification).
- Return `payout_type_id: "unknown"` with `status: "needs_review"`.
- Ideally surface a reason: "Product family (credit/leverage) has no current
  PRISM model counterpart."

This is different from "the classifier is uncertain" — it is "the model space
does not yet cover this family."
