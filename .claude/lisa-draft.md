# Draft Spec: Extend Derivative Fields

## Context
The current Derivative table stores 10 columns of position-level metadata. edgartools parses 65+ fields per derivative from NPORT-P filings. 85% of available data is dropped during ingestion. This work extends the schema to capture the full economic terms.

## Decisions Made
- **Scope:** All derivative types (swaps, futures, options, forwards, swaptions)
- **Schema approach:** Normalized child tables for type-specific fields + shared fields on parent table
- **Swap legs:** Two-row model in a `derivative_swap_leg` table with direction column (pay/receive)
- **Migration:** Schema-only, no backfill needed (testing phase, data re-run from scratch)
- **Nested derivatives:** Flatten nested derivative info as extra columns on parent (no recursion)
- **Unique constraint:** Add `counterparty` to existing unique constraint

## Schema Design (Draft)

### Parent table changes (Derivative)
Add shared fields available for ALL derivative types:
- `unrealized_appreciation` (Numeric) — mark-to-market P&L
- `currency` (String) — notional/position currency
- `underlying_title` (String) — title of underlying security
- `underlying_lei` (String) — LEI of underlying
- `underlying_isin` (String) — ISIN of underlying
- `underlying_ticker` (String) — ticker of underlying
- `payoff_profile` (String) — long/short (futures)
- Expand unique constraint to include `counterparty`

### Child table: derivative_swap
One row per swap derivative. FK to derivative.id.
- `upfront_payment`, `payment_currency`
- `upfront_receipt`, `receipt_currency`
- `swap_flag` (Y/N)
- `termination_date`

### Child table: derivative_swap_leg
Two rows per swap (pay + receive). FK to derivative_swap.id.
- `direction` (pay/receive)
- `leg_type` (fixed/floating/other)
- `fixed_rate`, `fixed_amount`, `fixed_currency`
- `floating_index`, `floating_spread`, `floating_amount`, `floating_currency`
- `tenor`, `tenor_unit`, `reset_date_tenor`, `reset_date_unit`
- `other_description`

### Child table: derivative_option
One row per option/swaption/warrant. FK to derivative.id.
- `put_or_call`, `written_or_purchased`
- `share_number`, `exercise_price`, `exercise_price_currency`
- `index_name`, `index_identifier`
- Nested derivative flattened fields: `nested_deriv_type`, `nested_deriv_notional`, `nested_deriv_counterparty`

### Child table: derivative_forward
One row per forward. FK to derivative.id.
- `currency_sold`, `amount_sold`
- `currency_purchased`, `amount_purchased`
- `settlement_date`

### Futures
Futures-specific fields (payoff_profile) go on parent. No separate table needed — futures have minimal extra fields beyond what parent already stores.

## Parser Changes
- Extend `_map_investment_to_derivative()` to populate new parent columns
- Add helper functions to create child table records for each derivative type
- Map ALL edgartools fields to database columns

## Testing
- Extend existing NPORT test mocks to verify new fields
- Add tests for each derivative type's child table population
- Verify unique constraint with counterparty
