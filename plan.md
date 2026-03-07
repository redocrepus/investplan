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

Directory structure, Pydantic models (`SimConfig`, `InflationSettings`, `ExpensePeriod`, `OneTimeExpense`, `CurrencySettings`, `InvestmentBucket`), volatility profiles, currency list, and model validation tests.

### Stage 2 — Financial Engine (no GUI) ✅

Engine modules: inflation random walk, FX simulation, bucket price growth, expense computation, rebalancer (expense coverage with cash floors, runaway guard, sell/buy triggers), simulator orchestrator, and Monte Carlo runner. Full unit and integration tests.

### Stage 3 — Main Window Shell ✅

QMainWindow with splitter layout, toolbar (Run Simulation, Monte Carlo, Save/Load Config), and status bar.

### Stage 4 — Table View ✅

QAbstractTableModel backed by DataFrame, two-level header with collapsible bucket column groups and individual columns, monthly/yearly toggle, cell coloring (red for underfunded), currency/percent formatting.

### Stage 5 — Input Panels & Dialogs ✅

Global settings panel (period, currency, tax, inflation), expense panel (periods + one-time), currency panel (per-currency FX settings), bucket panel with full editor dialog (all fields, triggers, cost basis), and Monte Carlo dialog (progress bar, success %, percentile curves).

### Stage 6 — Persistence & UX Polish ✅

JSON save/load, unsaved-changes prompt, auto-save/restore on exit/launch, input validation with error messages, tooltips on all fields, CSV/Excel export.

### Stage 7 — Packaging & Docs ✅

Pinned `requirements.txt`, PyInstaller spec for Windows `.exe`, README finalized.

### Stage 8 — Trigger System Refactoring ✅

Replaced single-trigger `RebalancingParams` with flexible multi-trigger list per bucket (`BucketTrigger` model), added cost basis tracking (FIFO/LIFO/AVCO), and enforced rebalancing cost rules (fees on both sides, capital gain tax, FX conversion). Four trigger subtypes: sell (take_profit, share_exceeds), buy (discount, share_below). Full GUI support with trigger list editor and cost basis method dropdown.

### Stage 9 — Bug Fixes & Hardening ✅

Critical fixes from financial review: cost basis tracking, take profit threshold, total_net_spent, expense coverage fallback, inflation volatility, use_cash_pool condition, profitability ordering, sell amount shrinkage, share% portfolio total, trigger month logic, log-return clamping, input validation (trigger refs, currency mismatch, self-referential triggers), exception handling, and autosave error handling.

### Stage 10 — Cash Pool & Trigger Period ✅

Added cash pool (expenses-currency cash reserve with auto-refill from most profitable buckets) and changed trigger frequency from `"monthly"/"yearly"` to `period_months: int`. Cash pool model, state tracking, refill logic, GUI controls, and output columns.

### Stage 11 — Multi-Source Buy Triggers & Implicit Share% Floors/Ceilings ✅

Buy triggers now support multiple source buckets with profitability-based ordering. Share-based triggers create implicit portfolio share floors (`share_below` → floor) and ceilings (`share_exceeds` → ceiling) enforced across triggers and cash pool refill. Backward-compatible auto-migration from `target_bucket` to `source_buckets`.

### Stage 12 — Financial Review Fixes ✅

Bucket amount market-value revaluation, expense coverage profitability ordering, cash pool floor enforcement, per-phase trigger snapshot evaluation, discount trigger cost basis fix, share-exceeds single-pass documentation, and sell trigger ceiling pre-limiting for proceeds in transit.

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
1. Apply growth to all bucket prices and revalue amounts (market value tracking: `amount *= new_price / old_price`)
2. Apply FX changes
3. Calculate this month's expenses (inflation-adjusted)
4. Run sell triggers (period_months check, snapshot-based condition evaluation): Take Profit, Share exceeds X% — subject to runaway guard, target ceiling pre-limiting
5. Cover expenses: draw from cash pool (respecting cash floor), refill if needed (5a). If still insufficient, sell from buckets (most profitable first, then by spending priority; reverse-priority fallback when all at floor).
   5a. Refill cash pool: if below refill trigger, sell from most profitable bucket first (respecting cash floors and share% floors) until reaching refill target or sources exhausted.
7. Run buy triggers (period_months check, snapshot-based condition evaluation): Discount >= X%, Share falls below X% — funds from source bucket
8. Record all outputs to the DataFrame row

**Currency handling:** All cross-currency amounts are converted to Expenses currency at the current simulated FX rate. Fees apply on conversion.

---

## Stage 13 — Financial Review Fixes II

Findings from the second financial review (requirements → plan → implementation → tests).

### P1 — Bugs

- [x] **A. Expense coverage first pass ignores implicit share% floors** — `_cover_expenses_from_buckets` only respects `cash_floor_months`; it does not enforce the implicit share% floor from `share_below` triggers. Compare with `_available_to_sell()` which respects both. Requirements say expense coverage can violate these limits "as a last resort", implying the first pass (profitability-ordered) should respect them, with only the reverse-priority fallback violating them. Fix: use `_available_to_sell()` or replicate its dual-floor logic in the first pass.
- [x] **B. Multiple share-based triggers allowed but only first used** — `_get_share_floor` / `_get_share_ceiling` return the first matching trigger's threshold, silently ignoring duplicates. Fix: validate in `InvestmentBucket` that at most one `share_below` buy trigger and one `share_exceeds` sell trigger exist per bucket. Reject duplicates at the model level.
- [x] **C. CashPool missing cross-field validation** — Requirements say `refill_target_months` must be >= `refill_trigger_months`. No validation exists; users can create nonsensical configs (e.g., trigger=24, target=12). Fix: add a `model_validator` to `CashPool`.
- [x] **D. Profitability ordering uses avg_cost for all cost basis methods** — `_bucket_profitability` always uses `avg_cost` regardless of FIFO/LIFO. For buckets with highly varied lot prices, the true profitability of the next units to sell can differ significantly. This is a bug: profitability must be consistent with the actual cost basis method used for taxation. Fix: compute profitability from the actual next-to-sell lots (front for FIFO, back for LIFO) instead of avg_cost.

### P2 — Design Concerns

- [x] **E. Cross-currency routing always goes through expenses currency** — Sell trigger proceeds route seller→expenses→target currency, even when seller and target share the same foreign currency (e.g., both EUR). This double-charges FX conversion fees. Fix: when seller and target currencies match, short-circuit the FX conversion — only convert to expenses currency the amount required to pay capital gains tax, then transfer the rest directly.
- [x] **F. `_estimate_net_yield` floors at 1%** — `max(net_yield, 0.01)` prevents division-by-zero in gross-up calculations, but in extreme fee+tax scenarios actual yield could be below 1%, causing the gross-up to underestimate the sell amount needed. Fix: remove the floor. Extract a `_gross_up(target_net, net_yield) -> float | None` helper that returns `None` when yield <= 0. Callers skip the source (continue to next bucket) when `None` is returned.

### P3 — Ambiguities / Documentation

- [x] **G. One-time expenses are inflation-adjusted without documentation** — `compute_monthly_expenses` applies cumulative inflation to one-time expenses. Requirements didn't explicitly specify this. Documented in requirements.md and GUI tooltip.

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
