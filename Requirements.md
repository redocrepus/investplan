# General

Application for investment strategy planning and simulation.
GUI: Excel like table where rows are months and columns are customizable financial data.

## Input

- Total investment period (in years)
- Expenses currency (allow selecting from a list of common currencies. Suggest the locale currency by default).
- Total hedge amount (in Expenses currency)
- Add monthly expense periods (by default 0, each period last until next period or until the entire investment period)
  - start month N of year K
  - amount min/max
  - average amount
  - Expenses volatility during the period [constant(average), moderate, crazy]
- Capital gain tax (in percent)
- [optional] Add special 1-time expense at month N of year K
- Inflation
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
  - Capital gains cost basis method: FIFO (default), LIFO, or AVCO
  - Target growth (in percent)
  - Spending priority (allow visually ordering the buckets in order of selling first to cover expenses). All buckets are subject to selling if needed to cover expenses, in order of spending priority.
  - Cash floor (in months of expenses calculated after converted to expenses currency): When selling to cover expenses, keep at least this amount in the bucket. If the bucket has hit the cash floor, sell from the next bucket in the spending priority list.
  - Required Runaway (in months of expenses) before trigger-based selling (to avoid selling in a market crash when the price is low)
  - Allow adding triggers to each bucket. Each trigger is one of two types:
    - **Sell triggers** (subtypes):
      1. **Take Profit**: sell if `actual_growth% / target_growth% >= X`. Use profit to refill a configurable target bucket.
      2. **Share exceeds X%**: sell if the bucket's share of the total portfolio (in expenses currency) exceeds X%.
    - **Buy triggers** (subtypes):
      1. **Discount >= X%**: buy if `100 * target_price / current_price - 100 > X%`. Funds come from a configurable source bucket that should be sold to cover the buy amount. If needed, fx should be applied.
      2. **Share falls below X%**: buy if the bucket's share of the total portfolio (in expenses currency) falls below X%. Funds come from a configurable source bucket.
  - Multiple triggers can be added to a single bucket
  - **Rebalancing cost rules:** When a trigger causes selling bucket A to buy bucket B:
    - Buy/sell fees are applied on both the sell side (bucket A fee) and the buy side (bucket B fee)
    - Capital gain tax is applied on any realized gain from the sell (using the bucket's chosen cost basis method)
    - If bucket A and bucket B are in different currencies, FX conversion is applied at the current simulated rate (plus conversion fee)

- For each non-Expenses currecy:
  - Initial price (in Expenses currency)
  - Expected Min/Max
  - Expected average (in Expenses currency)
  - Volatility profile [const(average), gov-bonds, s&p500, gold, bitcoin]
  - Conversion fee to/from the Expenses currency (in percent)

All the parameters should be editable at any time between simulations.


## Output

### Columns that are always displayed:
- Year/month number (allow toggling between a row showing per year and per number)
- Inflation
- Expenses
- Total Net-Spent (in Expenses currency) This is the sum of Net-Spent of all buckets. This column is for validation. It  should be always equal to the expenses column. If it is less than the expenses column, mark the cell in red to indicate that the strategy is not covering the expenses.

### Columns per bucket

Allow expanding collapsing per-bucket related column ranges (In addition to column headers, there shouold be an extra header row for the bucket headers).
Allow expanding collapsing individual columns.
When collapsed show:
- Price (in currency)
- Price (in Expenses currency)
- Total amount at the end of the month/year (in currency)
- Total amount at the end of the month/year (in Expenses currency)
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