# Financial Terms Reference — 424B2 Structured Note Extraction

Distilled from: Julius Bär Derivatives Glossary, SSPA Swiss Structured Products Association,
SRP Academy (Structured Retail Products), Financial Pipeline A–Z, Travers Smith Derivatives Guide.

This reference is provided to Claude as extraction context for SEC 424B2 prospectus supplements.
Terms are grouped by functional area and include synonyms commonly found in US filings.

---

## 1. Product Types

**Structured Note / Structured Product**: A debt security issued by a financial institution
where the return is linked to one or more underlying assets (equity index, single stock,
commodity, interest rate). Combines a fixed-income component with embedded derivative(s).
US synonyms: "Equity-Linked Note", "Index-Linked Note", "Market-Linked Note."

**Principal-at-Risk Note**: Structured note with no capital guarantee — the investor's
principal may be partially or fully lost if the underlying breaches the barrier at maturity.
Distinct from capital-protected notes.

**Capital-Protected / Principal-Protected Note**: Guarantees return of at least the capital
protection level (often 100% of face value) at maturity, regardless of underlying performance.

**Reverse Convertible / Barrier Reverse Convertible (BRC)**: High-yield structured note.
The investor receives an enhanced fixed coupon but risks receiving underlying shares
(physical delivery) instead of par if the underlying falls below the barrier at maturity.
US filing synonyms: "Yield Enhancement Note," "Contingent Income Note," "Income Note,"
"Trigger Notes." The "conversion" = cash redemption converting into underlying shares.

**Autocall / Express Certificate / Auto-Callable Note**: Automatically redeems early when
the underlying meets a predefined trigger condition on a scheduled observation date (typically:
underlying ≥ autocall trigger level). Pays a fixed call premium on early redemption.
US filing synonyms: "Auto-Callable," "Knock-Out Notes," "Step-Down Callable."

**Callable Note / Issuer-Callable Note**: The *issuer* (not market performance) has the
option to redeem early on specified "Optional Redemption Dates" at "Optional Redemption
Prices." Distinct from autocalls — issuer redemption is at the issuer's commercial
discretion, not triggered by underlying price. Common label in US filings: "Callable" or
"Issuer Call Right." Redemption dates listed explicitly in the terms sheet.

**Buffer Note / Buffered Note**: Provides flat partial downside protection through a buffer
zone. Within the buffer (e.g., first 20% decline), investor bears no loss. Below the buffer,
losses are 1-for-1. DIFFERENT from a barrier: a buffer absorbs losses up to a threshold;
a barrier triggers a loss mechanism when breached.

**Digital / Binary / Point-to-Point Note**: Pays a fixed predetermined redemption amount if
the underlying closes above (or below) a specified trigger level at expiry; otherwise pays
a minimum or zero growth.

**Range Accrual Note**: Coupon accrues only for days the underlying stays within a
pre-specified range. Return = coupon × (days in range / total days).

---

## 2. Barrier & Downside Mechanics

**Barrier / Knock-In Level / Trigger Level (downside)**: The underlying price level that,
if breached, activates the downside mechanism (removes capital protection). Expressed as
% of initial strike (e.g., "Barrier = 60%" means underlying must not fall below 60% of
its initial fixing). In 424B2 filings, look for: "Barrier Level," "Knock-In Level,"
"Trigger Level," "Downside Threshold."

**Knock-In Event / Barrier Breach**: The moment the underlying price touches or crosses the
barrier. After a knock-in in a BRC, the issuer may deliver shares instead of cash at maturity.

**Down-and-In Put**: The embedded derivative in most barrier reverse convertibles. It is
inactive (does not exist) unless the underlying breaches the barrier — at which point it
activates and grants the issuer the right to deliver shares instead of par. The "down" =
barrier is below current price; "in" = option activates on breach.

**American Barrier (Continuous Observation)**: The barrier is monitored continuously
throughout the product's life — any intraday breach triggers the knock-in. Most common
in US reverse convertibles. Filing clues: "at any time," "on any scheduled trading day,"
"continuous monitoring."

**European Barrier (Barrier at Maturity)**: The barrier is checked only at the final
fixing date. Filing clues: "only on the final observation date," "at maturity only."
Lower risk for the investor than an American barrier.

**Safety Buffer / Barrier Distance**: Percentage distance between current underlying price
and the barrier. E.g., underlying at 80%, barrier at 60% → 25% safety buffer.

**Buffer vs. Barrier distinction**: A buffer = flat protection zone (no loss until buffer
is exhausted). A barrier = binary trigger (protection intact until barrier hit, then fully
removed). Do not confuse these two structures.

**Downside Gearing**: Gearing applied to losses below the barrier or protection level. E.g.,
"2× downside gearing" means a 10% decline below barrier produces a 20% capital loss.

---

## 3. Autocall & Early Redemption

**Autocall Trigger / Observation Level / Call Level**: The underlying price level
(as % of initial strike) at which the product automatically redeems early. Common threshold:
100% (underlying at or above its initial level). Filing synonyms: "Call Trigger Level,"
"Automatic Redemption Level," "Knock-Out Level" (not to be confused with knock-in barrier).

**Observation Date / Autocall Date / Valuation Date**: Scheduled calendar dates on which
the autocall condition is evaluated. Common frequencies: monthly, quarterly, semi-annual,
annual. Look for date schedules in the "Observation Dates" or "Call Observation Dates" table.

**Call Premium / Redemption Amount (autocall)**: Amount paid when autocall triggers.
Typically: par + fixed coupon, or par × (1 + call premium rate). May step up over time
("escalating call premium").

**Step-Down Autocall**: Autocall trigger level decreases over observation dates (e.g.,
100% Year 1 → 95% Year 2 → 90% Year 3), making early redemption progressively easier.

**Memory / Accumulation Feature**: Missed (unpaid) conditional coupons accumulate and are
paid retroactively when the coupon barrier is next cleared. Ensures no coupon is
permanently lost.

**Optional Redemption (Issuer Call)**: Issuer's right to redeem at specified dates and
prices. Look for: "Optional Redemption Dates," "Optional Redemption Price," "Issuer may
redeem." This is an issuer right, not automatic. The issuer is NOT required to redeem.

---

## 4. Coupon Mechanics

**Fixed Coupon / Unconditional Coupon**: Paid on every scheduled payment date regardless
of underlying performance. Not conditional on barrier or trigger.

**Conditional Coupon / Contingent Coupon / Coupon at Risk**: Paid only if the underlying
is at or above the coupon barrier on the coupon observation date. If below the barrier,
the coupon is forfeited (unless memory feature applies). Filing labels: "Contingent
Coupon," "Conditional Coupon," "Barrier Coupon."

**Memory Coupon / Cumulative Coupon**: Missed conditional coupons accumulate and are
paid when the coupon barrier is next cleared. Ensures retroactive payment.

**Coupon Barrier**: The underlying price threshold (as % of strike) below which the
conditional coupon is not paid. Often lower than the knock-in barrier (e.g., coupon
barrier = 70%, knock-in barrier = 60%). Do not confuse with the capital protection
barrier.

**Accrual Coupon**: Coupon accrues for each day the underlying stays above (or within)
a specified level. Final coupon = rate × (qualifying days / total days).

**Step-Up / Step-Down Coupon**: Coupon rate that increases or decreases on a schedule
regardless of underlying performance. Common in callable notes.

---

## 5. Underlying & Pricing Terms

**Underlying / Reference Asset / Reference Stock / Reference Index**: The financial
instrument to which the note's payoff is linked. Types: single equity index (e.g.,
S&P 500, EuroStoxx 50, Nikkei 225), single stock, basket of stocks/indices, commodity,
interest rate. In 424B2 filings: "the Underlying," "the Reference Asset," "each
Reference Stock."

**Strike / Strike Level / Initial Level / Initial Fixing Level / Initial Stock Price**:
The reference price of the underlying set at the product's inception (initial fixing date).
All performance calculations are relative to this level (conventionally = 100%).
Filing synonyms: "Initial Underlying Level," "Starting Level," "Strike Price."

**Initial Fixing Date / Trade Date / Strike Date / Pricing Date**: The date on which the
strike, barrier, and trigger levels are established. Often the same as or close to
the trade date.

**Final Fixing Date / Final Observation Date / Final Valuation Date / Determination Date**:
The last observation date before maturity at which the final underlying level is recorded
to determine redemption. Filing synonyms: "Final Measurement Date," "Valuation Date."

**Worst-of Basket**: The payoff is determined by the worst-performing underlying among
all basket constituents. Offers higher yield than single-underlying notes because of
the added correlation risk. Standard in multi-underlying BRCs and autocalls.
Issuer-specific synonyms: JPMorgan uses **"Least Performing"** or **"Lowest Performing"**
(e.g., "the Least Performing of the DJIA, Russell 2000 and S&P 500"); Citigroup may
use "Worst Performing"; European issuers often use "Worst-of." When a filing says
"Least Performing of [Index A, B, C]", extract all three as separate underlyings (U1,
U2, U3) — do not treat the phrase as a single underlying name.

**Best-of Basket**: Payoff determined by best-performing underlying. Less common; found
in certain participation or capital-protected structures.

**Participation Rate**: Percentage of the underlying's positive performance credited to
the investor. 100% = full upside; 150% = leveraged upside. Common in capital-protected
structures. Filing synonyms: "Upside Participation," "Participation Factor."

**Cap / Maximum Return**: The maximum return the investor can receive regardless of how
far the underlying rises. A capped note limits upside. Filing label: "Maximum Redemption
Amount," "Cap Level," "Maximum Return."

**Floor / Capital Protection Level**: The minimum amount the investor receives at maturity.
100% floor = full principal protection; 90% floor = maximum 10% principal loss.

**Quanto**: A note where the underlying is denominated in a foreign currency but the
payoff is paid in the investor's local currency, removing exchange-rate risk.

**Rainbow / Multi-Underlying**: Options or notes based on multiple underlyings where
payoff depends on ranked performance (best-of, worst-of).

---

## 6. Settlement & Lifecycle

**Cash Settlement**: Redemption paid in cash. Most common in note products.

**Physical Delivery / Physical Settlement**: Investor receives actual underlying shares
instead of cash at maturity. Typically triggered by a barrier breach in a BRC. Shares
delivered = notional ÷ initial fixing price (adjusted for ratio/allocation rate). The
investor receives shares worth less than par.

**Allocation Rate / Ratio**: Number of underlying units delivered per note upon physical
settlement. Allocation Rate = Denomination ÷ Initial Fixing Level.

**Denomination / Face Value / Principal Amount / Notional**: The base unit of the note
(e.g., $1,000). All redemption amounts are expressed as % of this amount.

**Trade Date**: Date when terms are agreed.

**Issue Date / Settlement Date**: Date when investor pays and note is issued. Typically
T+2 or T+3 business days after Trade Date.

**Maturity Date / Final Payment Date**: Date when the final redemption is paid.

**Tenor / Term**: Duration of the note (e.g., "3-year notes," "18-month tenor").

**CUSIP**: 9-character US identifier assigned to each note issuance. Found on the cover
page of 424B2 filings.

**ISIN**: 12-character international securities identification number.

---

## 7. Parties & Roles

**Issuer**: Financial institution creating and selling the structured note. Investors bear
the issuer's credit risk (unsecured creditors). Common US structured note issuers:
UBS, Citigroup, Barclays, Goldman Sachs, Wells Fargo, Morgan Stanley, JPMorgan, BofA.

**Guarantor**: Entity (usually the parent company of the issuer) guaranteeing the issuer's
obligations. E.g., UBS AG (Guarantor) guarantees notes issued by UBS Finance LLC (Issuer).
Guarantor's LEI and full legal name appear in the terms sheet.

**Calculation Agent**: Party responsible for calculating final fixing levels, determining
whether a barrier breach occurred, computing the redemption amount, and resolving disputes.
Almost always the issuer or an affiliate.

**Depositary / DTC**: The Depository Trust Company (DTC) holds global notes and maintains
beneficial ownership records for US-registered notes.

**LEI (Legal Entity Identifier)**: 20-character alphanumeric identifier for legal entities
in financial transactions. Preferred identifier for Issuer and Guarantor fields in PRISM.

---

## 8. Risk Concepts & General Terms

**Issuer Risk / Credit Risk**: Risk that the issuer defaults on its obligations. Unlike
deposits, structured notes are NOT insured.

**Market Risk**: Risk of loss from adverse underlying price movements.

**Implied Volatility**: Expected volatility of the underlying priced into the embedded
options. Higher volatility → higher coupon or better terms for the investor (they are
selling optionality).

**Historic Volatility**: Actual observed price fluctuation of the underlying over a past period.

**Correlation (Worst-of context)**: In worst-of baskets, lower correlation between
underlyings increases the probability the worst-of falls sharply, justifying the higher
coupon offered. Correlation is a key risk driver not always stated explicitly in filings.

**Greeks**: Delta, Gamma, Vega, Theta, Rho — standard option sensitivity measures.
Vega (volatility sensitivity) and Theta (time decay) are most relevant for structured
product valuation.

**Bid-Ask Spread**: Difference between the price at which the note can be bought (ask) and
sold (bid) in the secondary market. Wider for less liquid products.

**Fair Value / Theoretical Value**: The theoretical value of a structured product based on
its component options and bond, calculated using models like Black-Scholes.

**Termsheet / Pricing Supplement**: Short document setting out the specific terms of an
individual note issuance. The 424B2 IS the termsheet filed with the SEC.

---

## 9. Common 424B2 Filing Vocabulary (Synonym Map)

| PRISM field concept              | Common 424B2 labels                                                                        |
|----------------------------------|--------------------------------------------------------------------------------------------|
| Strike / Initial Level           | "Initial Stock Price," "Starting Level," "Initial Underlying Level," "Initial Value"       |
| Barrier / Knock-In Level         | "Barrier Level," "Trigger Level," "Knock-In Level," "Downside Threshold"                   |
| Autocall Trigger                 | "Call Trigger Level," "Observation Level," "Automatic Redemption Level"                    |
| Coupon Barrier                   | "Coupon Barrier Level," "Income Barrier," "Contingent Coupon Trigger," "Interest Barrier"  |
| Observation Date                 | "Autocall Date," "Valuation Date," "Review Date," "Determination Date"                     |
| Physical Delivery                | "Delivery of Shares," "Share Settlement," "Alternative Settlement"                         |
| Calculation Agent                | "Calculation Agent," "Determination Agent"                                                 |
| Notional / Face Value            | "Principal Amount," "Face Amount," "Denomination," "Aggregate Principal"                   |
| Participation Rate               | "Participation Factor," "Upside Participation," "Return Rate"                              |
| Issuer Call                      | "Optional Redemption," "Issuer Redemption Right," "Call Option"                            |
| Memory Coupon                    | "Memory Feature," "Cumulative Coupon," "Catch-Up Coupon"                                   |
| Worst-of Basket                  | "Worst-of," "Worst Performing," **"Least Performing" (JPMorgan)**, "Lowest Performing"     |
| Digital Coupon / Floor Return    | "Contingent Digital Return," "Digital Return," "Fixed Digital," "Binary Coupon"            |
| Payout Formula                   | "Payment at Maturity," "Redemption Amount," "Payout," "Payment Upon Maturity"              |
