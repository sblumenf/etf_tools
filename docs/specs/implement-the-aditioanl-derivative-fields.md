# Spec: Extend Derivative Schema to Capture Full NPORT-P Fields

## Overview

The current `Derivative` table stores 10 columns of position-level metadata from NPORT-P filings. The edgartools library parses 65+ fields per derivative, including swap pay/receive leg economics, option terms, forward settlement details, and unrealized P&L. This work extends the schema to capture the full data available from SEC filings across all derivative types.

## Background

NPORT-P filings report derivative positions under Item C.11. Each derivative type (forward, future, option, swap, swaption) has type-specific fields defined in the SEC's XSD schema. The edgartools library (`FundReport.from_filing()`) fully parses these into typed dataclasses. The current pipeline maps only identification and notional data, discarding the economic terms that describe what a position actually does.

For example, a total return swap on Visa stock currently stores: "SWP, Goldman Sachs, $26M, expires 2030." It discards: "Pay floating FEDL01+0bps, Receive total return of underlying, Unrealized P&L +$510K." Without the leg data, the swap's direction (long vs short) and financing terms are unknown.

## Scope

**In scope:**
- Extend the `Derivative` parent table with shared fields (unrealized_appreciation, currency, underlying identifiers)
- Create child tables: `derivative_swap`, `derivative_swap_leg`, `derivative_option`, `derivative_forward`
- Extend the NPORT parser to populate all new tables
- Flatten nested derivative info (option-on-swap, swaption-on-swap) as columns, not recursive FKs
- Store all `deriv_addl_*` fields (balance, units, value_usd, pct_val, asset_cat, issuer_cat, inv_country)
- Update unique constraint to include counterparty
- Expand test mocks + one integration test against a real filing

**Out of scope:**
- Alembic migration (testing phase, data re-run from scratch)
- Backfilling existing data
- CLI changes
- Any other parser (N-CSR, 485BPOS, 24F-2NT)

## Schema Design

### Rationale

Normalized child tables per derivative type. This avoids a wide parent table full of NULLs and correctly models the one-to-one (derivative → swap) and one-to-many (swap → legs) relationships. Swap legs use a two-row model (pay/receive as a `direction` column) because the pay and receive legs have identical structure — this is textbook relational normalization.

Futures do not get a child table because their only unique field (`payoff_profile`) moves to the parent.

### Parent Table Changes: `derivative`

Add these nullable columns:

| Column | Type | Source | Description |
|---|---|---|---|
| `unrealized_appreciation` | `Numeric` | All types `.unrealized_appreciation` | Mark-to-market gain/loss in USD |
| `currency` | `String(3)` | All types `.currency` | Notional/position currency (ISO) |
| `underlying_title` | `String(150)` | `deriv_addl_title` or `reference_entity_title` | Security title of underlying |
| `underlying_lei` | `String(20)` | `deriv_addl_lei` | LEI of underlying issuer |
| `underlying_isin` | `String(12)` | `reference_entity_isin` | ISIN of underlying |
| `underlying_ticker` | `String(20)` | `reference_entity_ticker` | Ticker of underlying |
| `underlying_other_id` | `String(50)` | `reference_entity_other_id` or `deriv_addl_identifier` | Other identifier |
| `underlying_other_id_type` | `String(50)` | `reference_entity_other_id_type` or `deriv_addl_identifier_type` | Type of other identifier |
| `underlying_balance` | `Numeric` | `deriv_addl_balance` | Balance/quantity of underlying |
| `underlying_units` | `String(50)` | `deriv_addl_units` | Units (shares, contracts, etc.) |
| `underlying_currency` | `String(3)` | `deriv_addl_currency` | Currency of underlying |
| `underlying_value_usd` | `Numeric` | `deriv_addl_value_usd` | USD value of underlying |
| `underlying_pct_value` | `Numeric` | `deriv_addl_pct_val` | % of fund net assets |
| `underlying_asset_cat` | `String(20)` | `deriv_addl_asset_cat` | Asset category |
| `underlying_issuer_cat` | `String(20)` | `deriv_addl_issuer_cat` | Issuer category |
| `underlying_inv_country` | `String(2)` | `deriv_addl_inv_country` | Country (ISO 2-letter) |
| `payoff_profile` | `String(10)` | `FutureDerivative.payoff_profile` | Long/Short (futures) |

**Unique constraint change:** Replace `derivative_uniq` with `(etf_id, report_date, derivative_type, underlying_name, filing_date, counterparty)`.

### New Table: `derivative_swap`

One row per swap derivative. One-to-one FK to `derivative.id`.

| Column | Type | Source | Description |
|---|---|---|---|
| `id` | `Integer` (PK) | Auto | Primary key |
| `derivative_id` | `Integer` (FK, unique) | `derivative.id` | Parent derivative |
| `upfront_payment` | `Numeric` | `swp.upfront_payment` | Upfront payment amount |
| `upfront_payment_currency` | `String(3)` | `swp.payment_currency` | Upfront payment currency |
| `upfront_receipt` | `Numeric` | `swp.upfront_receipt` | Upfront receipt amount |
| `upfront_receipt_currency` | `String(3)` | `swp.receipt_currency` | Upfront receipt currency |
| `swap_flag` | `String(1)` | `swp.swap_flag` | Y/N |

### New Table: `derivative_swap_leg`

Two rows per swap (pay leg + receive leg). FK to `derivative_swap.id`.

| Column | Type | Source | Description |
|---|---|---|---|
| `id` | `Integer` (PK) | Auto | Primary key |
| `swap_id` | `Integer` (FK) | `derivative_swap.id` | Parent swap |
| `direction` | `String(7)` | Literal `"pay"` or `"receive"` | Leg direction |
| `leg_type` | `String(10)` | `"fixed"`, `"floating"`, or `"other"` | Determined from which fields are populated |
| `fixed_rate` | `Numeric` | `swp.fixed_rate_pay/receive` | Fixed rate (decimal, e.g. 0.045) |
| `fixed_amount` | `Numeric` | `swp.fixed_amount_pay/receive` | Fixed payment amount |
| `fixed_currency` | `String(3)` | `swp.fixed_currency_pay/receive` | Fixed leg currency |
| `floating_index` | `String(100)` | `swp.floating_index_pay/receive` | Index name (e.g. "FEDL01 INDEX") |
| `floating_spread` | `Numeric` | `swp.floating_spread_pay/receive` | Spread over index (bps as decimal) |
| `floating_amount` | `Numeric` | `swp.floating_amount_pay/receive` | Floating payment amount |
| `floating_currency` | `String(3)` | `swp.floating_currency_pay/receive` | Floating leg currency |
| `tenor` | `String(20)` | `swp.floating_tenor_pay/receive` | Tenor value |
| `tenor_unit` | `String(10)` | `swp.floating_tenor_unit_pay/receive` | Tenor unit (Day, Month, Year) |
| `reset_date_tenor` | `String(20)` | `swp.floating_reset_date_tenor_pay/receive` | Reset date tenor |
| `reset_date_unit` | `String(10)` | `swp.floating_reset_date_unit_pay/receive` | Reset date unit |
| `other_description` | `Text` | `swp.other_description_pay/receive` | Description when leg_type="other" |

**Unique constraint:** `(swap_id, direction)`

### New Table: `derivative_option`

One row per option, swaption, or warrant. One-to-one FK to `derivative.id`.

| Column | Type | Source | Description |
|---|---|---|---|
| `id` | `Integer` (PK) | Auto | Primary key |
| `derivative_id` | `Integer` (FK, unique) | `derivative.id` | Parent derivative |
| `put_or_call` | `String(4)` | `opt.put_or_call` | "Put" or "Call" |
| `written_or_purchased` | `String(10)` | `opt.written_or_purchased` | "Written" or "Purchased" |
| `share_number` | `Numeric` | `opt.share_number` | Number of shares/units |
| `exercise_price` | `Numeric` | `opt.exercise_price` | Strike price |
| `exercise_price_currency` | `String(3)` | `opt.exercise_price_currency` | Strike currency |
| `index_name` | `String(150)` | `opt.index_name` | Index name (for index options) |
| `index_identifier` | `String(50)` | `opt.index_identifier` | Index identifier |
| `nested_deriv_type` | `String(20)` | Type of nested derivative | FWD, SWP, FUT, or NULL |
| `nested_deriv_notional` | `Numeric` | Nested derivative's notional | Notional of nested derivative |
| `nested_deriv_counterparty` | `String(500)` | Nested derivative's counterparty | Counterparty of nested derivative |
| `nested_deriv_currency` | `String(3)` | Nested derivative's currency | Currency of nested derivative |

### New Table: `derivative_forward`

One row per forward. One-to-one FK to `derivative.id`.

| Column | Type | Source | Description |
|---|---|---|---|
| `id` | `Integer` (PK) | Auto | Primary key |
| `derivative_id` | `Integer` (FK, unique) | `derivative.id` | Parent derivative |
| `currency_sold` | `String(3)` | `fwd.currency_sold` | Currency sold |
| `amount_sold` | `Numeric` | `fwd.amount_sold` | Amount sold |
| `currency_purchased` | `String(3)` | `fwd.currency_purchased` | Currency purchased |
| `amount_purchased` | `Numeric` | `fwd.amount_purchased` | Amount purchased |
| `settlement_date` | `Date` | `fwd.settlement_date` | Settlement date |

## Parser Changes

### File: `src/etf_pipeline/parsers/nport.py`

**Modify `_map_investment_to_derivative()`:**
- Populate all new parent-level columns (unrealized_appreciation, currency, underlying_* fields) for every derivative type
- Return child table objects alongside the Derivative object (or return a composite structure)

**Add helper functions:**
- `_build_derivative_swap(swp: SwapDerivative) -> DerivativeSwap` — creates swap row
- `_build_swap_legs(swp: SwapDerivative, swap_id) -> list[DerivativeSwapLeg]` — creates pay + receive leg rows
- `_build_derivative_option(opt: OptionDerivative) -> DerivativeOption` — creates option row with flattened nested info
- `_build_derivative_forward(fwd: ForwardDerivative) -> DerivativeForward` — creates forward row

**Modify the caller** (the function that iterates investments and commits to DB):
- After creating the Derivative row and flushing (to get `derivative.id`), create the appropriate child table row(s)
- Use `session.flush()` between parent and child inserts to ensure FK availability

### Field Mapping by Derivative Type

**Forwards:**
- Parent: `unrealized_appreciation`, `currency` (from `deriv_addl_currency`), all `underlying_*` from `deriv_addl_*`
- Child (derivative_forward): `currency_sold`, `amount_sold`, `currency_purchased`, `amount_purchased`, `settlement_date`

**Futures:**
- Parent: `unrealized_appreciation`, `currency`, `payoff_profile`, all `underlying_*` from `reference_entity_*`
- No child table

**Options:**
- Parent: `unrealized_appreciation`, `currency`, `delta` (already stored), all `underlying_*` from `reference_entity_*`
- Child (derivative_option): `put_or_call`, `written_or_purchased`, `share_number`, `exercise_price`, `exercise_price_currency`, `index_name`, `index_identifier`, `nested_deriv_*`

**Swaptions:**
- Parent: `unrealized_appreciation`, all `underlying_*`
- Child (derivative_option): same as options. Swaptions use the same table — they share identical field structure.
- Nested swap flattened into `nested_deriv_*` columns

**Swaps:**
- Parent: `unrealized_appreciation`, `currency`, all `underlying_*` from `deriv_addl_*` or `reference_entity_*`
- Child (derivative_swap): `upfront_payment`, `upfront_payment_currency`, `upfront_receipt`, `upfront_receipt_currency`, `swap_flag`
- Child (derivative_swap_leg): two rows, one for pay, one for receive. Determine `leg_type` from which edgartools fields are populated (if `fixed_rate_pay` is set → "fixed"; if `floating_index_pay` is set → "floating"; if `other_description_pay` is set → "other")

### Delta Handling

The edgartools `delta` field is `Union[Decimal, str]` because some filings report `"XXXX"` (not calculable). The current `delta` column is `Numeric`. Store `None` when the value is the string `"XXXX"`.

## User Stories

### US-1: Extend Derivative Parent Table
**Description:** Add shared columns (unrealized_appreciation, currency, underlying_* identifiers and position details, payoff_profile) to the Derivative model. Update unique constraint to include counterparty.
**Acceptance Criteria:**
- All 17 new columns exist on the Derivative model
- Unique constraint is `(etf_id, report_date, derivative_type, underlying_name, filing_date, counterparty)`
- `create_all()` creates the updated table without errors
- Existing tests pass (new columns are nullable)

### US-2: Create Derivative Swap Tables
**Description:** Add `DerivativeSwap` and `DerivativeSwapLeg` models with FK relationships.
**Acceptance Criteria:**
- `DerivativeSwap` has FK to `derivative.id` with unique constraint
- `DerivativeSwapLeg` has FK to `derivative_swap.id` with unique constraint on `(swap_id, direction)`
- Cascade delete configured: deleting a Derivative deletes its swap and legs
- `create_all()` succeeds

### US-3: Create Derivative Option Table
**Description:** Add `DerivativeOption` model for options, swaptions, and warrants.
**Acceptance Criteria:**
- `DerivativeOption` has FK to `derivative.id` with unique constraint
- Includes `nested_deriv_*` columns for flattened nested derivative info
- Cascade delete configured
- `create_all()` succeeds

### US-4: Create Derivative Forward Table
**Description:** Add `DerivativeForward` model.
**Acceptance Criteria:**
- `DerivativeForward` has FK to `derivative.id` with unique constraint
- Cascade delete configured
- `create_all()` succeeds

### US-5: Update NPORT Parser — Parent Fields
**Description:** Modify `_map_investment_to_derivative()` to populate all new parent columns for every derivative type.
**Acceptance Criteria:**
- `unrealized_appreciation` populated for all derivative types
- `currency` populated from the appropriate source per type
- All `underlying_*` fields populated from `deriv_addl_*` or `reference_entity_*` as appropriate
- `payoff_profile` populated for futures
- Unit tests verify each field for each derivative type using mocks

### US-6: Update NPORT Parser — Swap Child Tables
**Description:** Add swap and swap leg creation to the parser.
**Acceptance Criteria:**
- Swap derivatives create a `DerivativeSwap` row with upfront payment/receipt data
- Two `DerivativeSwapLeg` rows created (pay + receive) with correct leg_type determination
- Floating leg fields (index, spread, tenor, reset) populated correctly
- Fixed leg fields (rate, amount, currency) populated correctly
- "Other" leg type stores description text
- Unit tests verify a complete swap with both legs

### US-7: Update NPORT Parser — Option and Forward Child Tables
**Description:** Add option and forward child table creation to the parser.
**Acceptance Criteria:**
- Options create a `DerivativeOption` row with put/call, strike, shares
- Swaptions create a `DerivativeOption` row with nested swap info flattened
- Forwards create a `DerivativeForward` row with currencies and settlement date
- Nested derivative info (when present) populates `nested_deriv_*` columns
- Unit tests verify each derivative type

### US-8: Integration Test Against Real Filing
**Description:** Add one integration test that parses a real NPORT-P filing from EDGAR and verifies key fields are populated.
**Acceptance Criteria:**
- Test marked with `@pytest.mark.integration` (or similar marker to skip in CI)
- Fetches a known filing with swap derivatives
- Verifies that parent fields, swap child, and swap legs are all populated with non-null values
- Test can be run manually with `pytest -m integration`

## Implementation Phases

### Phase 1: Schema (US-1 through US-4)
Add all new models and columns. Run `create_all()`. Verify existing tests still pass.

### Phase 2: Parser — Parent Fields (US-5)
Update `_map_investment_to_derivative()` for parent columns. Add unit tests for each derivative type.

### Phase 3: Parser — Child Tables (US-6, US-7)
Add child table creation. Add unit tests for swap legs, option terms, forward terms.

### Phase 4: Integration Test (US-8)
Add real-filing integration test. Run full test suite.

## Verification

- `pytest tests/` — all existing + new unit tests pass
- `pytest -m integration` — real filing integration test passes
- Manually verify via `python -m etf_pipeline run-nport --ticker <ticker>` that derivative child tables are populated

## Technical Notes

- SQLAlchemy `relationship()` with `cascade="all, delete-orphan"` on parent side for child tables
- `session.flush()` after inserting Derivative row to obtain `derivative.id` before inserting child rows
- The `_clean_str()` helper already handles "N/A" → None conversion; reuse it for new string fields
- The `_parse_date()` helper already handles date string parsing; reuse for `settlement_date`
