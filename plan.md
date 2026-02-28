# Investment Planner — Implementation Plan

## Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | **Python 3.11+** | Easy Windows install, rich ecosystem, fast numerics |
| GUI | **PyQt6** | Best-in-class table widget, collapsible headers, cross-platform |
| Numerics | **NumPy** | Vectorized Monte Carlo simulations |
| Data | **Pandas** | DataFrame-based simulation output, easy CSV/Excel export |
| Validation | **Pydantic v2** | Clean, typed data models with validation |
| Packaging | **PyInstaller** | Single-exe Windows distribution |
| Tests | **pytest** | Unit tests for the financial engine |

**Running on Windows:** `pip install -r requirements.txt && python main.py`

---

## Architecture Overview

```
investplan/
├── main.py                   # Entry point
├── models/                   # Pydantic data models
│   ├── config.py             # Top-level simulation config
│   ├── bucket.py             # Investment bucket + rebalancing params
│   ├── expense.py            # Expense periods + one-time expenses
│   ├── currency.py           # Currency exchange settings
│   └── inflation.py          # Inflation settings
├── engine/                   # Financial simulation (no GUI deps)
│   ├── simulator.py          # Orchestrates one simulation run
│   ├── inflation.py          # Inflation random walk
│   ├── currency.py           # FX random walk
│   ├── bucket.py             # Per-bucket growth, buy/sell logic
│   ├── rebalancer.py         # Target-trajectory rebalancing
│   ├── expenses.py           # Monthly expense draw-down
│   └── montecarlo.py         # Run N simulations, collect stats
├── gui/                      # PyQt6 views (no business logic)
│   ├── main_window.py        # Main window + toolbar
│   ├── table/
│   │   ├── model.py          # QAbstractTableModel backed by sim output
│   │   ├── header.py         # Two-level header (bucket / column)
│   │   └── delegates.py      # Cell coloring, number formatting
│   ├── panels/
│   │   ├── global_panel.py   # Period, currency, tax, hedge, inflation
│   │   ├── bucket_panel.py   # Add/edit/remove investment buckets
│   │   ├── expense_panel.py  # Expense periods + one-time expenses
│   │   └── currency_panel.py # Per-currency FX settings
│   └── dialogs/
│       ├── bucket_dialog.py  # Full bucket editor dialog
│       ├── expense_dialog.py
│       └── montecarlo_dialog.py  # N-simulation runner + results
├── utils/
│   ├── volatility.py         # Volatility profile → σ mappings
│   └── currency_list.py      # ISO currency list + locale detection
├── requirements.txt
└── tests/
    ├── test_inflation.py
    ├── test_bucket.py
    ├── test_rebalancer.py
    └── test_simulator.py
```

---

## Global Requirements

- **`README.md` must be kept up-to-date at all times throughout development.** It must always contain clear, accurate instructions for:
  - **Install** — setting up a Python virtual environment and installing dependencies
  - **Dev run** — running the app directly from source (`python main.py`)
  - **Test** — running the test suite (`pytest`)
  - **Build** — producing the standalone Windows `.exe` via PyInstaller
  - **Run** — launching the built executable
  - Any environment prerequisites (Python version, OS, etc.)
- **Checklists in this plan must be maintained during implementation.** When a task is completed, update its checkbox from `[ ]` to `[x]`. This keeps the plan a living document that reflects actual progress.

---

## Implementation Stages

### Stage 1 — Project Skeleton & Data Models ✅
- [x] Create directory structure and `requirements.txt`
- [x] Implement `models/config.py` — top-level `SimConfig` (period, currency, tax, hedge)
- [x] Implement `models/inflation.py` — `InflationSettings` (min/max/avg/volatility)
- [x] Implement `models/expense.py` — `ExpensePeriod`, `OneTimeExpense`
- [x] Implement `models/currency.py` — `CurrencySettings` (FX min/max/avg/volatility/fee)
- [x] Implement `models/bucket.py` — `InvestmentBucket` + `RebalancingParams`
- [x] Implement `utils/currency_list.py` (ISO list + locale default)
- [x] Implement `utils/volatility.py` (named profiles → (σ_monthly, distribution) mappings)
- [x] Write unit tests for model validation

### Stage 2 — Financial Engine (no GUI) ✅
- [x] `engine/inflation.py` — monthly inflation random walk (const / mild / crazy)
- [x] `engine/currency.py` — monthly FX rate random walk per non-expenses currency
- [x] `engine/bucket.py` — monthly price growth, dividends/interest accrual
- [x] `engine/expenses.py` — monthly expense draw, volatility, one-time events
- [x] `engine/rebalancer.py`
  - [x] Expense coverage: sell from buckets in spending priority order (all buckets eligible)
  - [x] Cash-floor guard (don't sell bucket below cash floor; cascade to next in spending priority)
  - [x] Fee and capital-gains-tax deduction on sell
  - [x] Runaway guard (don't trigger-sell if cash runway < required months)
  - [x] Sell triggers: Take Profit (profit → target bucket), if profit exceeds X% of the target growth.
  - [x] Buy triggers: Discount >= X% (buy from source bucket).
- [x] `engine/simulator.py` — orchestrate one full simulation, return `pd.DataFrame`
- [x] `engine/montecarlo.py` — run N simulations, return success rate + percentile frames
- [x] Write unit tests for each engine module (deterministic seed)
- [x] Integration test: full 2-year run, assert total net-spent ≈ total expenses

### Stage 3 — Main Window Shell ✅
- [x] `gui/main_window.py` — QMainWindow with splitter (left panel / right table)
- [x] Toolbar: **Run Simulation**, **Run Monte Carlo**, **Save Config**, **Load Config**
- [x] Status bar showing last-run success/failure summary

### Stage 4 — Table View ✅
- [x] `gui/table/model.py` — QAbstractTableModel backed by simulator DataFrame
  - [x] Support toggling between monthly and yearly row view
- [x] `gui/table/header.py` — two-level QHeaderView (Bucket name row + column name row)
- [x] Collapsible bucket column groups (collapse to 4 summary columns)
- [x] Collapsible individual columns within a bucket
- [x] `gui/table/delegates.py`
  - [x] Red cell when Total Net-Spent < Expenses
  - [x] Currency-formatted numbers
  - [x] Percent-formatted cells

### Stage 5 — Input Panels & Dialogs ✅
- [x] `gui/panels/global_panel.py`
  - [x] Investment period (years spinner)
  - [x] Expenses currency (combobox, locale default)
  - [x] Total hedge amount
  - [x] Capital gain tax %
  - [x] Inflation settings (min/max/avg/volatility)
- [x] `gui/panels/expense_panel.py`
  - [x] List of expense periods (start month/year, min/max/avg amount, volatility)
  - [x] Add / edit / remove buttons → `expense_dialog.py`
  - [x] One-time expense list with add/edit/remove
- [x] `gui/panels/currency_panel.py`
  - [x] One section per non-expenses currency found in buckets
  - [x] Initial price, min/max/avg, volatility, conversion fee
- [x] `gui/panels/bucket_panel.py`
  - [x] List of investment buckets with add/edit/remove/reorder
  - [x] Opens `bucket_dialog.py` for full editing
- [x] `gui/dialogs/bucket_dialog.py`
  - [x] All bucket fields (name, currency, initial price/amount, growth min/max/avg, volatility, fees, target growth)
  - [x] Rebalancing section (monthly/yearly, sell trigger, standby bucket, buy trigger, buying priority, required runaway, spending priority, cash floor)
- [x] `gui/dialogs/montecarlo_dialog.py`
  - [x] N simulations spinner
  - [x] Progress bar
  - [x] Results: success %, percentile curves (10th / 50th / 90th portfolio value)

### Stage 6 — Persistence & UX Polish ✅
- [x] Save / load `SimConfig` to JSON file
- [x] Track unsaved changes; on exit, prompt "Save before closing?" (Save / Discard / Cancel) if there are unsaved changes
- [x] Auto-save last config on exit, restore on launch
- [x] Input validation with inline error messages
- [x] Tooltips on all input fields explaining the parameter
- [x] Export simulation table to CSV / Excel (via pandas)

### Stage 7 — Packaging & Docs ✅
- [x] `requirements.txt` with pinned versions
- [x] PyInstaller spec → single `.exe` for Windows
- [x] Final review of `README.md` for completeness and accuracy

### Stage 8 — Trigger System Refactoring

Currently `RebalancingParams` has a single sell trigger (take profit) and a single buy trigger (discount), plus `frequency`, `standby_bucket`, `buying_priority`, `spending_priority`, `cash_floor_months`, `required_runaway_months`. This stage replaces the single-trigger model with a flexible multi-trigger list per bucket.

**Model changes:**
- [ ] Add `BucketTrigger` Pydantic model to `models/bucket.py`:
  - `trigger_type`: `"sell"` or `"buy"`
  - `subtype`: `"take_profit"` | `"share_exceeds"` (for sell), `"discount"` | `"share_below"` (for buy)
  - `threshold_pct`: float (the X value)
  - `target_bucket`: Optional[str] — standby bucket (sell) or source bucket (buy)
  - `frequency`: `"monthly"` | `"yearly"`
- [ ] Add `triggers: list[BucketTrigger] = []` field to `InvestmentBucket`
- [ ] Add `cost_basis_method: str = "fifo"` field to `InvestmentBucket` (values: `"fifo"`, `"lifo"`, `"avco"`)
- [ ] Keep `spending_priority`, `cash_floor_months`, `required_runaway_months` on `InvestmentBucket` directly (move out of `RebalancingParams`)
- [ ] Remove `RebalancingParams` (its remaining fields are now on `BucketTrigger` or `InvestmentBucket`)

**Engine changes:**
- [ ] Refactor `engine/rebalancer.py` to iterate the trigger list:
  - [ ] Sell/Take Profit: sell if `actual_growth% / target_growth% >= X`, proceeds → buy target bucket (apply fx if different currency)
  - [ ] Sell/Share exceeds X%: sell if bucket share of portfolio > X%, proceeds → but target bucket
  - [ ] Buy/Discount >= X%: buy if `100*target_price/current_price - 100 > X%`, sell from source bucket to fund
  - [ ] Buy/Share below X%: buy if bucket share of portfolio < X%, sell from source bucket to fund
  - [ ] All trigger sells/buys: apply buy/sell fees on both sides, capital gain tax on realized gains, FX conversion + fee when cross-currency
  - [ ] Runaway guard applies to trigger-based sells only (not expense coverage)
  - [ ] Expense coverage (Phase 2) unchanged: sell in spending priority order, respect cash floors
- [ ] Update `BucketState` dataclass to hold trigger list instead of single sell/buy trigger fields
- [ ] Implement cost basis tracking per bucket (FIFO / LIFO / AVCO) for capital gains calculation
  - [ ] Track purchase lots (price, amount) for FIFO/LIFO
  - [ ] Track weighted average cost for AVCO
  - [ ] Use chosen method when computing realized gains on sell
- [ ] Update `engine/simulator.py` to pass portfolio totals to rebalancer (needed for share% triggers)

**GUI changes:**
- [ ] Refactor `gui/dialogs/bucket_dialog.py`:
  - [ ] Replace single sell/buy trigger fields with a trigger list (add/edit/remove)
  - [ ] Each trigger row: type dropdown, subtype dropdown, threshold spin, target bucket combo
  - [ ] Move spending_priority, cash_floor, required_runaway out of the old rebalancing group
  - [ ] Add cost basis method dropdown (FIFO / LIFO / AVCO) to bucket fields
- [ ] Update `gui/panels/bucket_panel.py` — show trigger count/summary in bucket list

**Tests & serialization:**
- [ ] Update `tests/test_rebalancer.py` — test all four trigger subtypes, multi-trigger scenarios
- [ ] Add tests for share% triggers (need portfolio total calculation)
- [ ] Add tests for cost basis methods (FIFO, LIFO, AVCO) — verify correct gain calculation
- [ ] Add tests for cross-currency trigger rebalancing (fees, FX, tax)
- [ ] Verify save/load roundtrip with new trigger model (backward-compatible with old JSON if possible)

---

## Key Design Decisions

**Separation of engine and GUI:** The entire `engine/` package has zero PyQt6 imports. This makes it independently testable and reusable (e.g., web front-end later).

**Volatility profiles → σ mapping:**
| Profile | Monthly σ (approx) |
|---|---|
| constant | 0 |
| mild / gov-bonds | 0.5 % |
| moderate / s&p500 | 4 % |
| crazy / bitcoin | 15 % |

Growth and FX rates are modeled as log-normal random walks. Inflation uses a mean-reverting walk.

**Rebalancing order of operations (per month):**
1. Apply growth to all bucket prices
2. Apply FX changes
3. Calculate this month's expenses (inflation-adjusted)
4. Run sell triggers: Take Profit (profit → standby bucket), Share exceeds X% — subject to runaway guard
5. Run buy triggers: Discount >= X%, Share falls below X% — funds from configured source bucket
6. Cover expenses: sell from buckets in spending priority order (respecting cash floors)
7. Record all outputs to the DataFrame row

**Currency handling:** All cross-currency amounts are converted to Expenses currency at the current simulated FX rate. Fees apply on conversion.
