# EUSIPA & SSPA Structured Product Classification Codes

Reference for ingestion decisions. Primary use: **family-level triage before
any structural comparison**. If the EUSIPA or SSPA code of an incoming product
is known, its product family can be determined in one lookup.

Sources: eusipa.eu (governance/product map), sspa.ch/en/products/
Fetched: 2026-03-23

---

## EUSIPA Classification

### Category 11 — Capital Protection (Investment, 1a/1b MiFID)

| Code | Name | Key Characteristics |
|------|------|---------------------|
| 1100 | Uncapped Capital Protection | Min. redemption = capital protection level; unlimited upside; coupon possible |
| 1110 | Exchangeable Certificates | Capital protection + conversion upside; benefits from rising volatility |
| 1120 | Capped Capital Protection | Capital protection + participation up to cap |
| 1130 | Capital Protection with Knock-Out | Capital protection + participation until knock-out; rebate possible |
| 1140 | Capital Protection with Coupon | Capital protection; coupon dependent on underlying performance |

### Category 12 — Yield Enhancement (Investment, 1a/1b MiFID)

| Code | Name | Key Characteristics |
|------|------|---------------------|
| 1200 | Discount Certificates | Underlying at discount; cap; delivery if below strike |
| 1210 | Barrier Discount | Discount + barrier; turns into Discount Certificate if barrier breached |
| 1220 | Reverse Convertibles | Fixed coupon always paid; delivery if below strike |
| 1230 | Barrier Reverse Convertible | Fixed coupon; conditional capital protection via barrier |
| 1240 | Capped Outperformance Certificates | 1:1 below strike; disproportionate participation above; capped upside |
| 1250 | Capped Bonus Certificates | Bonus if barrier never breached; upside capped |
| 1260 | Express Certificates | **Autocall**: early redemption if underlying above strike on observation date; conditional capital protection |

### Category 13 — Participation (Investment, 1a/1b MiFID)

| Code | Name | Key Characteristics |
|------|------|---------------------|
| 1300 | Tracker Certificates | 1:1 participation; Bull or Bear variants |
| 1310 | Outperformance Certificates | 1:1 below strike; disproportionate upside participation |
| 1320 | Bonus Certificates | Participation + min. redemption at strike if barrier not breached |
| 1330 | Outperformance Bonus Certificates | Outperformance + bonus floor if barrier not breached |
| 1340 | Twin-Win Certificates | Profits in both rising and falling market; until barrier breach |

### Category 14 — Credit Linked Notes (Investment with credit risk, 1b MiFID)

> **Important:** Current EUSIPA standard places CLNs in category 14 (codes 1440–1460).
> Older documents and legacy systems (including some SP_MasterFile entries) use
> code **3100** for CLNs. Treat 3100 and 14xx as the same product family.

| Code | Name | Key Characteristics |
|------|------|---------------------|
| 1440 | Credit Linked Note — Linear | Proportional credit event exposure; total loss possible |
| 1450 | Credit Linked Note — Equity Tranche | First-loss tranche; leveraged exposure to first credit events |
| 1460 | Credit Linked Note — Mezz./Senior Tranche | Buffer absorbs first N events; affected only above threshold |

### Category 21–23 — Leverage Products (1c MiFID)

| Code | Name | Key Characteristics |
|------|------|---------------------|
| 2100 | Warrants | Call/Put; leveraged; time value decay; total loss possible |
| 2110 | Spread Warrants | Bull/Bear spread; leveraged; capped upside |
| 2200 | Knock-Out Warrants | Leveraged; expires worthless if barrier breached; minimal vol sensitivity |
| 2205 | Open-End Knock-Out Warrants | As 2200 but open-ended; daily barrier adjustment |
| 2210 | Mini-Futures | Long/Short; stop-loss differs from strike; residual value after stop-loss |
| 2230 | Double Knock-Out Warrants | Upper and lower barriers; expires worthless if either breached |
| 2300 | Constant Leverage Certificate | Daily-rebalanced Bull/Bear; constant leverage; path-dependent |

---

## SSPA Classification

SSPA uses five categories: Capital Protection / Yield Enhancement / Participation /
With Additional Credit Risk / Leverage. The "With Additional Credit Risk" category
is SSPA's explicit acknowledgement that credit risk can overlay any structural family.

### Capital Protection

| Code | Name | Notes vs. EUSIPA |
|------|------|------------------|
| 1100 | Capital Protection Note with Participation | = EUSIPA 1100 |
| 1130 | Capital Protection Note with Barrier | = EUSIPA 1130 (SSPA avoids "Knock-Out") |
| 1135 | Capital Protection Note with Twin-Win | **SSPA only** — no EUSIPA equivalent |
| 1140 | Capital Protection Note with Coupon | = EUSIPA 1140 |

### Yield Enhancement

| Code | Name | Notes vs. EUSIPA |
|------|------|------------------|
| 1200 | Discount Certificate | = EUSIPA 1200 |
| 1210 | Barrier Discount Certificate | = EUSIPA 1210 |
| 1220 | Reverse Convertible | = EUSIPA 1220 |
| 1230 | Barrier Reverse Convertible | = EUSIPA 1230 |
| 1255 | Conditional Coupon Reverse Convertible | **SSPA only** — barrier-less autocall/Express |
| 1260 | Conditional Coupon Barrier Reverse Convertible | **⚠ Code collision** — see note below |

### Participation

| Code | Name | Notes vs. EUSIPA |
|------|------|------------------|
| 1300 | Tracker Certificate | = EUSIPA 1300 |
| 1310 | Outperformance Certificate | = EUSIPA 1310 |
| 1320 | Bonus Certificate | = EUSIPA 1320 |
| 1330 | Bonus Outperformance Certificate | = EUSIPA 1330 (word order differs) |
| 1340 | Twin Win Certificate | = EUSIPA 1340 |

### With Additional Credit Risk (SSPA-specific category)

> SSPA takes a different architectural approach to CLNs than EUSIPA. Rather than
> a standalone credit category, SSPA models CLNs as "any existing structure + credit
> risk overlay". This reflects the Credit Overlay products in SP_MasterFile well.

| Code | Name | Description |
|------|------|-------------|
| 1400 | Credit Linked Note | Synthetic credit exposure to reference debtor; coupon = premium; capital at risk on credit event |
| 1410 | Conditional Capital Protection Note with additional credit risk | Capital protection structure + credit exposure on reference debtor |
| 1420 | Yield Enhancement Certificate with additional credit risk | Yield enhancement (reverse convertible, discount) + credit exposure |
| 1430 | Participation Certificate with additional credit risk | Participation structure + credit exposure |

### Leverage Products

| Code | Name | Notes vs. EUSIPA |
|------|------|------------------|
| 2100 | Warrant | = EUSIPA 2100 |
| 2110 | Spread Warrant | = EUSIPA 2110 |
| 2200 | Warrant with Knock-Out | = EUSIPA 2200 (name differs) |
| 2210 | Mini-Future | = EUSIPA 2210 |
| 2300 | Constant Leverage Certificate | = EUSIPA 2300 |

---

## Critical Note: Code 1260 Collision

**EUSIPA 1260** = Express Certificate (early redemption if underlying is above
strike on any observation date — a "vanilla" autocall without a barrier).

**SSPA 1260** = Conditional Coupon Barrier Reverse Convertible (autocall structure
*with* a coupon barrier — equivalent to what the market calls an "Express BRC").

Both are autocall-type products, but with different barrier mechanics. When a
product carries a "1260" code, the issuing context (Nordic/EUSIPA vs. Swiss/SSPA)
determines which definition applies. The SP_MasterFile Autocall sheet uses
EUSIPA 1260 = vanilla Express Certificate.

---

## Legacy Code 3100

Several SP_MasterFile CLN entries carry EUSIPA code **3100**. This was used in
older EUSIPA product maps for Credit Linked Notes before the current category 14
(1440–1460) structure was adopted. For all practical purposes:

> **3100 = CLN family. Treat identically to 1440–1460.**

Any product with code 3100, 1400, 1410, 1420, 1430, 1440, 1450, or 1460 is a
credit-linked product and must not be compared against equity structured product
taxonomies.

---

## Family Lookup Table (quick reference)

| Code range | Family | Can compare with equity taxonomy? |
|------------|--------|-----------------------------------|
| 1100–1140 | Capital Protection (equity-linked) | Yes |
| 1200–1260 | Yield Enhancement (equity-linked) | Yes |
| 1300–1340 | Participation (equity-linked) | Yes |
| 1400–1460, 3100 | Credit Linked Notes | **No** |
| 2100–2300 | Leverage Products | **No** |

---

## Implication for PRISM Ingestion

Current PRISM models cover equity-linked investment products only (codes 1200–1260
range, primarily). When a new product batch is received:

1. Extract the EUSIPA or SSPA code from the term sheet or metadata.
2. Consult the family lookup table above.
3. If code falls in 1400–1460 / 3100 / 2100–2300: flag as "no current PRISM model
   for this product family" before attempting classification.
4. If code falls in 1100–1340: proceed to structural classification against PRISM models.

This single check would have prevented all false-positive CLN matches in the
previous overlap analysis exercise.
