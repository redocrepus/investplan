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

## Implementation Stages

### Stage 1 — Project Skeleton & Data Models
- [ ] Create directory structure and `requirements.txt`
- [ ] Implement `models/config.py` — top-level `SimConfig` (period, currency, tax, hedge)
- [ ] Implement `models/inflation.py` — `InflationSettings` (min/max/avg/volatility)
- [ ] Implement `models/expense.py` — `ExpensePeriod`, `OneTimeExpense`
- [ ] Implement `models/currency.py` — `CurrencySettings` (FX min/max/avg/volatility/fee)
- [ ] Implement `models/bucket.py` — `InvestmentBucket` + `RebalancingParams`
- [ ] Implement `utils/currency_list.py` (ISO list + locale default)
- [ ] Implement `utils/volatility.py` (named profiles → (σ_monthly, distribution) mappings)
- [ ] Write unit tests for model validation

### Stage 2 — Financial Engine (no GUI)
- [ ] `engine/inflation.py` — monthly inflation random walk (const / mild / crazy)
- [ ] `engine/currency.py` — monthly FX rate random walk per non-expenses currency
- [ ] `engine/bucket.py` — monthly price growth, dividends/interest accrual
- [ ] `engine/expenses.py` — monthly expense draw, volatility, one-time events
- [ ] `engine/rebalancer.py`
  - [ ] Target-trajectory sell trigger logic (`actual_growth% / target_growth% > X`)
  - [ ] Standby bucket buy-trigger logic (`100*target_price/current_price - 100 > X`)
  - [ ] Runaway guard (don't sell if cash runway < required months)
  - [ ] Cash-floor guard (don't sell bucket below cash floor; cascade to next in spending priority)
  - [ ] Fee and capital-gains-tax deduction on sell
- [ ] `engine/simulator.py` — orchestrate one full simulation, return `pd.DataFrame`
- [ ] `engine/montecarlo.py` — run N simulations, return success rate + percentile frames
- [ ] Write unit tests for each engine module (deterministic seed)
- [ ] Integration test: full 10-year run, assert total net-spent == total expenses

### Stage 3 — Main Window Shell
- [ ] `gui/main_window.py` — QMainWindow with splitter (left panel / right table)
- [ ] Toolbar: **Run Simulation**, **Run Monte Carlo**, **Save Config**, **Load Config**
- [ ] Status bar showing last-run success/failure summary

### Stage 4 — Table View
- [ ] `gui/table/model.py` — QAbstractTableModel backed by simulator DataFrame
  - [ ] Support toggling between monthly and yearly row view
- [ ] `gui/table/header.py` — two-level QHeaderView (Bucket name row + column name row)
- [ ] Collapsible bucket column groups (collapse to 4 summary columns)
- [ ] Collapsible individual columns within a bucket
- [ ] `gui/table/delegates.py`
  - [ ] Red cell when Total Net-Spent < Expenses
  - [ ] Currency-formatted numbers
  - [ ] Percent-formatted cells

### Stage 5 — Input Panels & Dialogs
- [ ] `gui/panels/global_panel.py`
  - [ ] Investment period (years spinner)
  - [ ] Expenses currency (combobox, locale default)
  - [ ] Total hedge amount
  - [ ] Capital gain tax %
  - [ ] Inflation settings (min/max/avg/volatility)
- [ ] `gui/panels/expense_panel.py`
  - [ ] List of expense periods (start month/year, min/max/avg amount, volatility)
  - [ ] Add / edit / remove buttons → `expense_dialog.py`
  - [ ] One-time expense list with add/edit/remove
- [ ] `gui/panels/currency_panel.py`
  - [ ] One section per non-expenses currency found in buckets
  - [ ] Initial price, min/max/avg, volatility, conversion fee
- [ ] `gui/panels/bucket_panel.py`
  - [ ] List of investment buckets with add/edit/remove/reorder
  - [ ] Opens `bucket_dialog.py` for full editing
- [ ] `gui/dialogs/bucket_dialog.py`
  - [ ] All bucket fields (name, currency, initial price/amount, growth min/max/avg, volatility, fees, target growth)
  - [ ] Rebalancing section (monthly/yearly, sell trigger, standby bucket, buy trigger, buying priority, required runaway, spending priority, cash floor)
- [ ] `gui/dialogs/montecarlo_dialog.py`
  - [ ] N simulations spinner
  - [ ] Progress bar
  - [ ] Results: success %, percentile curves (10th / 50th / 90th portfolio value)

### Stage 6 — Persistence & UX Polish
- [ ] Save / load `SimConfig` to JSON file
- [ ] Auto-save last config on exit, restore on launch
- [ ] Input validation with inline error messages
- [ ] Tooltips on all input fields explaining the parameter
- [ ] Export simulation table to CSV / Excel (via pandas)

### Stage 7 — Packaging & Docs
- [ ] `requirements.txt` with pinned versions
- [ ] PyInstaller spec → single `.exe` for Windows
- [ ] Short `README.md` (install, run, build)

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
4. Run rebalancer: check sell triggers → sell → apply fees/tax → buy standby assets
5. If still short on expenses: cascade through spending priority (respecting cash floors)
6. Record all outputs to the DataFrame row

**Currency handling:** All cross-currency amounts are converted to Expenses currency at the current simulated FX rate. Fees apply on conversion.
