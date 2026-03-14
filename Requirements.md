# General

Application for investment strategy planning and simulation.
GUI: Excel like table where rows are months and columns are customizable financial data.

## Input

- Total investment period (in years)
- Expenses currency (allow selecting from a list of common currencies. Suggest the locale currency by default).
- Add monthly expense periods (by default 0, each period last until next period or until the entire investment period)
  - start month N of year K
  - amount min/max
  - average amount
  - Expenses volatility during the period [constant(average), moderate, crazy]
- Capital gain tax (in percent)
- Sell proceeds formula (selectable; determines how gross proceeds, fees, and tax are computed for each sell). Initially only one formula is available: Israeli tax law. Under Israeli tax law, brokerage fees are an allowable deduction from capital gains (fees are deducted before computing taxable gain).
- [optional] Add special 1-time expense at month N of year K (inflation-adjusted to the target month)
- Inflation (month 0 is neutral — no inflation applied; compounding starts from month 1)
  - Expected min/max (in percent)
  - Expected average (in percent)
  - Volatility [constant(average), mild, crazy]
- Allow adding investment buckets. Each bucket's input:
  - Name
  - currency (allow selecting from a list of common currencies. Expenses currency and dollar on top).
  - Initial price (in currency)
  - Initial amount (in currency)
  - Expected yearly growth min/max (in percent)
  - Expected yearly average growth (in percent)
  - Volatility profile [const(average), gov-bonds, s&p500, gold, bitcoin]
  - Buy/Sell fee (in percent)
  - Capital gains cost basis method: FIFO (default), LIFO, or AVCO. Cost basis is always tracked in the expenses currency.
  - Target growth (in percent). Used by Take Profit triggers: `actual_growth%` is defined as `(current_price_exp - cost_basis_per_unit_exp) / cost_basis_per_unit_exp * 100`, where both values are in expenses currency. `cost_basis_per_unit_exp` is determined by the bucket's chosen cost basis method (FIFO/LIFO/AVCO) and captures FX rates at purchase time. For cross-currency buckets, FX gains/losses are included in the growth calculation.
  - Spending priority (allow visually ordering the buckets in order of selling first to cover expenses). All buckets are subject to selling if needed to cover expenses, in order of spending priority.
  - Cash floor (in months of expenses calculated after converted to expenses currency): When selling (including for expenses coverage), keep at least this amount in the bucket if possible (to avoid selling other assets a market crash when the price is low).

  
  - Each trigger has a `period_months` parameter (integer >= 1): the trigger is checked every N months. 1 = monthly, 12 = yearly, any value supported.
  - Allow adding triggers to each bucket. Each trigger is one of two types:
    - **Sell triggers** (subtypes):
      1. **Take Profit**: sell if `actual_growth% / target_growth% >= X`. Use profit to refill a configurable target bucket. Target bucket's implicit share ceiling is respected.
      2. **Share exceeds X%**: sell if the bucket's share of the total portfolio (in expenses currency) exceeds X%. This threshold also acts as an **implicit ceiling** — other triggers will not buy into this bucket past X%.
    - **Buy triggers** (subtypes):
      1. **Discount >= X%**: buy if `100 * target_price / current_price - 100 > X%`. Funds come from an ordered list of **source buckets** (sold in profitability order — most profitable first; if all losing, in list priority order). Each source is sold down to its floors. If needed, fx should be applied.
      2. **Share falls below X%**: buy if the bucket's share of the total portfolio (in expenses currency) falls below X%. Funds come from source buckets (same ordering as discount). This threshold also acts as an **implicit floor** — other triggers and cash pool refill will not sell from this bucket below X%.
    - **Implicit share% limits**: Share-based triggers create implicit boundaries that apply across the system:
      - `share_below X%` → implicit floor: triggers and cash pool refill will not sell this bucket below X% portfolio share
      - `share_exceeds X%` → implicit ceiling: triggers will not buy into this bucket above X% portfolio share
      - Expense coverage first pass (profitability-ordered) respects these limits; only the reverse-priority fallback violates them as a last resort (expenses must be covered)
  - Multiple triggers can be added to a single bucket, but at most one `share_below` buy trigger and one `share_exceeds` sell trigger per bucket
  - **Trigger execution order within a month:** Sell triggers first, then expense coverage, then cash pool refill, then buy triggers. All triggers are evaluated on a snapshot of portfolio state at the start of their phase (not re-evaluated after each execution within the same phase).
  - **Rebalancing cost rules:** When a trigger causes selling bucket A to buy bucket B:
    - Buy/sell fees are applied on both the sell side (bucket A fee) and the buy side (bucket B fee)
    - Capital gain tax is applied on any realized gain from the sell (using the bucket's chosen cost basis method)
    - If bucket A and bucket B are in different currencies, FX conversion is applied at the current simulated rate (plus conversion fee). When bucket A and bucket B share the same foreign currency, proceeds transfer directly without double FX conversion — only the capital gains tax amount (if any) is converted to expenses currency.

- For each non-Expenses currecy:
  - Initial price (in Expenses currency)
  - Expected Min/Max
  - Expected average (in Expenses currency)
  - Volatility profile [const(average), gov-bonds, s&p500, gold, bitcoin]
  - Conversion fee to/from the Expenses currency (in percent)

- Cash Pool (expenses-currency cash reserve)
  - Initial amount (in expenses currency)
  - Refill trigger (in months of expenses): when the cash pool drops below this level, auto-refill begins
  - Refill target (in months of expenses): refill sells from buckets until the cash pool reaches this level (or sources are exhausted). Must be >= refill trigger.
  - Cash floor (in months of expenses): hard floor for the cash pool itself. All cash floor values are recalculated monthly using current inflation-adjusted expenses.
  - All expenses are drawn from the cash pool. If the cash pool doesn't have enough to cover the month's expenses, sell from buckets to refill the cash pool to its refill target first (using the refill source order below), then draw the expenses. If refill cannot fully top it up (all sources at floor), draw whatever the cash pool has, then fall through to direct bucket selling (spending priority cascade) for the remainder.
  - Refill source order: sell from the most profitable bucket first (gross gain after FX + fees). If no profitable buckets, sell in spending priority order. Source bucket cash floors and implicit share% floors are respected.
  - Sell fees, capital gains tax (using source bucket's cost basis method), and FX conversion fees apply during refill.

All the parameters should be editable at any time between simulations.

## Monthly order of operations
At the beginning of each month:
1. Apply growth to all bucket prices
2. Apply FX rate changes
3. Calculate this month's expenses (inflation-adjusted from the defined expense periods)
4. Run sell triggers (period_months check): Take Profit, Share exceeds X% — subject to runaway guard
5. Cover expenses: if cash pool is insufficient, refill it first (see step 5.1), then draw from cash pool. If still insufficient after refill, fall through to direct bucket selling.
   1. Refill cash pool: if below refill trigger, sell from most profitable bucket first (respecting cash floors and implicit share% floors) until cash pool reaches refill target or sources exhausted.
6. Run buy triggers (period_months check): Discount >= X%, Share falls below X% — funds from source buckets
7. Record all outputs

## Expense coverage rules
When covering expenses (step 5 above):
1. If the cash pool balance is below the month's expenses, refill it to refill target first (step 5.1). Then draw from the cash pool. If still insufficient after refill, draw whatever is available and fall through to direct bucket selling for the remainder.
2. Sell from buckets in order of highest profitability, respecting the cash floor guards and implicit share% floors. The profitability of selling a bucket is calculated as the gross gain of the next lots to sell (per the bucket's cost basis method: FIFO front, LIFO back, AVCO average) after converting to expenses currency applying the current FX rate if needed and the fees.
3. If there are no profitable buckets to sell, sell from buckets in order of spending priority, respecting the cash floor guards, even if it means selling at a loss.
4. If all buckets hit the cash floor, sell in the reverse order of spending priority, even if it means selling at a loss AND violating the cash floor. This preserves the most stable assets (highest priority) as long as possible during financial distress.



## Output

### Columns that are always displayed:
- Year/month number (allow toggling between a row showing per year and per number)
- Inflation
- Expenses
- Cash Pool balance (in expenses currency)
- Cash Pool balance (in months of current expenses)
- Total Net-Spent (in Expenses currency) This is the sum of Net-Spent of all buckets. This column is for validation. It  should be always equal to the expenses column. If it is less than the expenses column, mark the cell in red to indicate that the strategy is not covering the expenses. If it is more that the expenses  column, show an error message to indicate that there is a problem with the calculations (there is no sense in covering more than the expenses, this means that there is a problem in the calculations, for example not applying the cash floor correctly).

### Columns per bucket

Allow expanding collapsing per-bucket related column ranges (In addition to column headers, there shouold be an extra header row for the bucket headers).
Allow expanding collapsing individual columns.
When collapsed show:
- Price (in currency)
- Price (in Expenses currency)
- Total amount at the end of the month/year (in currency)
- Total amount at the end of the month/year (in Expenses currency)
- If the Total amount at the end of the month/year (in Expenses currency) is less than Cash floor, mark the cell in red to indicate that the cash floor has been violated.
When expanded, in addition show:
- Amount sold (in currency)
- Amount sold (in Expenses currency)
- Amount bought (in currency)
- Fees payed (in Expenses currency)
- Tax payed (in Expenses currency)
- Net-Spent amount (amount converted to Expenses currency remaining after tax and fees)

## Additional requirements

- Allow running N simulations (with randomization of the parameters according to the expected min/max/average/volatility) and tell the percentage of simulations that succeeded in covering the expenses for the entire investment period.
- Allow saving and loading the full configuration (all input parameters) to/from a file, so that sessions can be resumed and shared.
- When exiting with unsaved changes, prompt the user to save before closing.
- Must be easily extendable to add more parameters and more complex strategies in the future.
- Must be easily runnable on windows.
- Cross-platform - advantage.