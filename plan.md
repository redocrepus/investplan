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
│   │   ├── global_panel.py   # Period, currency, tax, inflation
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
- [x] Implement `models/config.py` — top-level `SimConfig` (period, currency, tax)
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

### Stage 8 — Trigger System Refactoring ✅

Replaced the single-trigger `RebalancingParams` model with a flexible multi-trigger list per bucket, added cost basis tracking (FIFO/LIFO/AVCO), and enforced rebalancing cost rules (fees on both sides, capital gain tax, FX conversion).

**Model changes:**
- [x] Add `BucketTrigger` Pydantic model to `models/bucket.py`:
  - `trigger_type`: `"sell"` or `"buy"`
  - `subtype`: `"take_profit"` | `"share_exceeds"` (for sell), `"discount"` | `"share_below"` (for buy)
  - `threshold_pct`: float (the X value)
  - `target_bucket`: Optional[str] — target bucket (sell) or source bucket (buy)
  - `frequency`: `"monthly"` | `"yearly"`
- [x] Add `triggers: list[BucketTrigger] = []` field to `InvestmentBucket`
- [x] Add `cost_basis_method: CostBasisMethod = "fifo"` field to `InvestmentBucket` (values: `"fifo"`, `"lifo"`, `"avco"`)
- [x] Move `spending_priority`, `cash_floor_months`, `required_runaway_months` to `InvestmentBucket` directly
- [x] Remove `RebalancingParams` (its fields are now on `BucketTrigger` or `InvestmentBucket`)

**Engine changes:**
- [x] Refactor `engine/rebalancer.py` to iterate the trigger list:
  - [x] Sell/Take Profit: sell if `actual_growth% / target_growth% >= X`, proceeds → buy target bucket (apply fx if different currency)
  - [x] Sell/Share exceeds X%: sell if bucket share of portfolio > X%, proceeds → target bucket
  - [x] Buy/Discount >= X%: buy if `100*target_price/current_price - 100 > X%`, sell from source bucket to fund
  - [x] Buy/Share below X%: buy if bucket share of portfolio < X%, sell from source bucket to fund
  - [x] All trigger sells/buys: apply buy/sell fees on both sides, capital gain tax on realized gains, FX conversion + fee when cross-currency
  - [x] Runaway guard applies to trigger-based sells only (not expense coverage)
  - [x] Expense coverage (Phase 3) unchanged: sell in spending priority order, respect cash floors
- [x] Update `BucketState` dataclass to hold trigger list instead of single sell/buy trigger fields
- [x] Implement cost basis tracking per bucket (FIFO / LIFO / AVCO) for capital gains calculation
  - [x] Track purchase lots (price, amount) for FIFO/LIFO
  - [x] Track weighted average cost for AVCO
  - [x] Use chosen method when computing realized gains on sell
- [x] Update `engine/simulator.py` to initialize BucketState from new model fields

**GUI changes:**
- [x] Refactor `gui/dialogs/bucket_dialog.py`:
  - [x] Replace single sell/buy trigger fields with a trigger list (add/edit/remove) via `TriggerDialog`
  - [x] Each trigger row: type dropdown, subtype dropdown, threshold spin, target bucket combo
  - [x] Move spending_priority, cash_floor, required_runaway to "Expense Coverage" group
  - [x] Add cost basis method dropdown (FIFO / LIFO / AVCO) to bucket fields
- [x] Update `gui/panels/bucket_panel.py` — show trigger count in bucket list

**Tests & serialization:**
- [x] Update `tests/test_rebalancer.py` — test all four trigger subtypes, multi-trigger scenarios
- [x] Add tests for share% triggers (portfolio total calculation)
- [x] Add tests for cost basis methods (FIFO, LIFO, AVCO) — verify correct gain calculation
- [x] Add tests for cross-currency trigger rebalancing (fees, FX, tax)
- [x] Verify save/load roundtrip with new trigger model

### Stage 9 — Bug Fixes & Hardening

Critical fixes identified during financial review. Tests must be strengthened to assert correct values, not just non-zero output.

**P0 — Critical calculation bugs:**
- [x] Fix `_compute_cost_basis()` in `engine/rebalancer.py` — converted `PurchaseLot` to unit-based tracking (`units = currency_amount / price`). Cost basis now correctly computed as `units_sold * lot.price` (FIFO/LIFO) or `units_sold * avg_cost` (AVCO). Previously cost basis always equaled sell amount, making capital gains tax always zero.
- [x] Fix Take Profit trigger threshold comparison — changed to `ratio * 100 >= threshold_pct` so threshold is consistently a percentage. Also uses `avg_cost` instead of `initial_price` for actual growth calculation per requirements. Previously entering threshold_pct=100 (meaning 100%) would never fire.
- [x] Fix `total_net_spent` when cash pool falls through to bucket selling — now sums `cash_pool.net_spent + sum(b.net_spent)`.
- [x] Strengthen cost basis tests with exact expected values (FIFO/LIFO/AVCO all verify precise cost basis amounts)
- [x] Add test verifying take profit trigger fires and produces correct sell amount (`test_triggers_with_exact_sell_amount`)

**P1 — Missing requirements & volatility bug:**
- [x] Implement expense coverage fallback in `engine/rebalancer.py` — when all buckets hit cash floor, sells in reverse spending priority order even if it violates the floor (per Requirements.md step 4)
- [x] Fix inflation volatility double-scaling in `engine/inflation.py` — removed erroneous `/ 12.0` that was killing volatility
- [x] Fix `use_cash_pool` condition in `engine/simulator.py` — now checks `initial_amount > 0 or refill_target_months > 0`
- [x] Add test for expense coverage fallback (`test_reverse_priority_fallback_when_all_at_floor`)
- [x] Add test verifying inflation volatility range matches profile (`test_mild_volatility_std_matches_sigma`, `test_crazy_volatility_has_more_variation_than_mild`)

**P2 — Logic fixes & financial modeling:**
- [x] Fix profitability ordering to use actual cost basis (`avg_cost`) instead of `initial_price` in `_bucket_profitability()`.
- [x] Fix sell amount calculation to account for fees/tax shrinkage — added `_estimate_net_yield()` to gross up sell amounts so net proceeds cover intended targets. Applied in expense coverage, cash pool refill, and buy trigger source sells.
- [x] Include cash pool in portfolio total for share% calculations — `_portfolio_total_expenses_currency` now accepts `cash_pool_amount` parameter, threaded through sell/buy triggers and available-to-sell checks.
- [x] Fix yearly trigger month logic — documented that month_idx=0 is the first month, triggers fire at 0, 12, 24, etc. Behavior is correct, just needed documentation.
- [x] Remove log-return clamping slack in `engine/bucket.py` — removed `±0.01` that allowed exceeding configured min/max growth range.
- [x] Add trigger target bucket reference validation in `gui/main_window.py` — rejects missing target/source buckets
- [x] Add currency mismatch validation — rejects buckets using currencies without FX settings
- [x] Prevent self-referential triggers — rejects target_bucket or source_buckets referencing the owning bucket
- [x] Yearly trigger logic covered by existing TestTriggerPeriodMonths tests (months 0, 12, 24, and non-fire months)

**P3 — Robustness improvements:**
- [x] Add exception handling in `SimulationThread` — errors now propagated via `error` signal to GUI with dialog + status bar
- [x] Improve `_autosave()` error handling — failures now shown in status bar instead of silently swallowed

**Volatility calibration notes** (for future tuning, no code change required now):
- Gov bonds σ=0.5%/mo (~1.7% annualized) — slightly low vs historical ~2-4%
- Gold σ=2.5%/mo (~8.7% annualized) — low vs historical ~12-15%
- Bitcoin σ=15%/mo (~52% annualized) — slightly low vs historical ~60-80%

### Stage 10 — Cash Pool & Trigger Period ✅

Added a cash pool (expenses-currency cash reserve) and changed trigger frequency from `"monthly"/"yearly"` to `period_months: int`.

**Model changes:**
- [x] Add `CashPool` Pydantic model to `models/config.py` (initial_amount, refill_target_months, cash_floor_months)
- [x] Add `cash_pool: CashPool` field to `SimConfig`
- [x] Replace `frequency: str` with `period_months: int` on `BucketTrigger` in `models/bucket.py`

**Engine changes:**
- [x] Add `CashPoolState` dataclass to `engine/rebalancer.py`
- [x] Reorder rebalance phases: sell triggers → cover expenses from cash pool → refill cash pool → buy triggers
- [x] Implement cash pool refill logic: sell most profitable bucket first, respect cash floors, apply fees/tax/FX
- [x] Update trigger period check: `month_idx % trigger.period_months != 0`
- [x] Update `engine/simulator.py`: init `CashPoolState`, pass to rebalancer, add output columns

**GUI changes:**
- [x] Add Cash Pool group box to `gui/panels/global_panel.py` (initial amount, refill target, cash floor)
- [x] Replace frequency combo with period_months spinner in `gui/dialogs/bucket_dialog.py`
- [x] Add Cash Pool column group to `gui/table/model.py` and `gui/table/header.py`

**Tests:**
- [x] Cash pool expense drawing, shortfall, refill, profitability ordering, cash floor respect, fees
- [x] Trigger `period_months` logic (monthly, quarterly, yearly)
- [x] `CashPool` and `BucketTrigger.period_months` model validation
- [x] Simulator cash pool output columns

### Stage 11 — Multi-Source Buy Triggers & Implicit Share% Floors/Ceilings ✅

Buy triggers now support multiple source buckets with profitability-based ordering, and share-based triggers create implicit portfolio share floors and ceilings.

**Model changes:**
- [x] Add `source_buckets: list[str]` field to `BucketTrigger` for buy triggers
- [x] Backward compat: auto-migrate `target_bucket` to `source_buckets` for buy triggers
- [x] Validation: buy triggers must have at least one source bucket

**Engine changes:**
- [x] Add `_get_share_floor()` and `_get_share_ceiling()` helpers
- [x] Add `_available_to_sell()` helper respecting cash floor + share% floor
- [x] Refactor `_execute_buy_trigger()` for multi-source (profitability ordering, sell down to floors)
- [x] Discount triggers: sell all available from sources (no arbitrary 10% cap)
- [x] Enforce buyer's share ceiling in `_execute_buy_trigger()`
- [x] Enforce target's share ceiling in `_execute_sell_trigger()`
- [x] Update `_refill_cash_pool()` to use `_available_to_sell()` (respects share% floors)

**GUI changes:**
- [x] Replace single Target/Source Bucket combobox with context-dependent UI
- [x] Sell triggers: single Target Bucket combobox (unchanged)
- [x] Buy triggers: ordered source bucket list with Add/Remove/Up/Down buttons
- [x] Updated trigger display to show source bucket list for buy triggers

**Tests:**
- [x] `TestMultiSourceBuyTrigger`: profitability ordering, cash floors, priority fallback, discount sell-all
- [x] `TestImplicitShareFloors`: share floor on source, share ceiling on target, cash pool refill, sell trigger target
- [x] `TestMultiSourceBackwardCompat`: auto-migration, roundtrip serialization
- [x] Model validation: source_buckets required, auto-migration, explicit not overwritten

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
4. Run sell triggers (period_months check): Take Profit, Share exceeds X% — subject to runaway guard
5. Cover expenses: if cash pool is insufficient, refill it first (5a), then draw from cash pool. If still insufficient, fall through to direct bucket selling.
   5a. Refill cash pool: if below refill trigger, sell from most profitable bucket first (respecting cash floors and share% floors) until reaching refill target or sources exhausted.
7. Run buy triggers (period_months check): Discount >= X%, Share falls below X% — funds from source bucket
8. Record all outputs to the DataFrame row

**Currency handling:** All cross-currency amounts are converted to Expenses currency at the current simulated FX rate. Fees apply on conversion.

---

## Future Plans

### Near Future
- [ ] Add inflation-to-asset-return correlation parameters per bucket (configurable coefficient, default 0)
- [ ] Add inter-bucket return correlation for Monte Carlo (correlation matrix or preset scenarios: crisis/normal/boom)
- [ ] Sell proceeds formula selection — implement Israeli tax law formula (requires web research on Israeli capital gains tax computation rules)
- [ ] Switch return distributions per volatility profile: Student's t (df=6) for gov-bonds, Student's t (df=8) for s&p500, Student's t (df=4) for bitcoin; keep log-normal for gold and constant

### Far Future
- [ ] Dividend / income yield modeling per bucket (annual_yield_%, paid monthly to cash pool)
- [ ] Monthly contribution / DCA modeling (amount, start/end month, target buckets)
- [ ] Cash pool annual yield parameter (savings account / money market return)
- [ ] Short-term vs. long-term capital gains tax rates (with configurable holding period threshold)
- [ ] Tax-advantaged account flag per bucket (skip capital gains tax on sells)
