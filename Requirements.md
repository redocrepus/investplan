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
  - Target growth (in percent)
  - Target-trajectory rebalancing parameters inputs:
    - monthly/yearly
    - Sell trigger X: sell if `actual_growth%/target_growth% > X`
    - Stand-by bucket class (choose other buckets what to buy with the sold amount)
    - Buy-trigger X: buy if `100*target_price/current_price - 100 > X percent`
    - Buying priority (allow visually ordering the buckets)
    - Required Runaway (in months of expenses) before selling (to avoid selling in a market crash when the price is low and not having enough cash to cover expenses until the market recovers)
    - Spending priority (allow visually ordering the buckets in order of selling first to cover expenses)
    - Cash floor (in months of expenses caclulated after converted to expenses currency): When selling, keep at least this amount of cash in the bucket class (this + stand-by) to avoid selling a more profitable bucket just to cover expenses when the price is low and not having enough cash to cover expenses until the market recovers. If selling is needed to cover expenses and the bucket has hit the cash floor, sell from the next bucket in the spending priority list.

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