# Investment Planner

Application for investment strategy planning and Monte Carlo simulation.

## Features

- Configurable investment buckets with growth, volatility, and rebalancing parameters
- Cash pool: expenses-currency cash reserve with auto-refill from most profitable buckets
- Multi-trigger system per bucket: sell (take profit, share exceeds) and buy (discount, share below) triggers with configurable period (every N months) and multi-source buy funding
- Capital gains cost basis tracking: FIFO, LIFO, or AVCO per bucket
- Rebalancing cost rules: buy/sell fees on both sides, capital gain tax, FX conversion fees
- Monthly expense periods with inflation adjustment
- Multi-currency support with FX simulation
- Implicit share% floors/ceilings derived from triggers (share_below = floor, share_exceeds = ceiling)
- Expense coverage via cash pool (when active) or spending priority cascade with cash floor guards, runaway protection, and reverse-priority fallback when all buckets hit floor
- Monte Carlo simulation with success rate and percentile statistics
- Save/load configuration to JSON
- Auto-save/restore last session on exit/launch
- Export simulation results to CSV
- Input validation with error messages before simulation

## Prerequisites

- Python 3.11+

## Install

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Dev Run

```bash
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

python main.py
```

This launches the GUI with:
- **Left panel** — Global settings, expenses, buckets, and currency configuration
- **Right panel** — Simulation results table with collapsible bucket column groups
- **Toolbar** — Run Simulation, Run Monte Carlo, Save/Load Config, Export CSV

The last session's configuration is automatically restored on launch.

## Test

```bash
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

python -m pytest tests/ -v
```

## Build (Windows .exe)

```bash
# Windows
.venv\Scripts\activate

python -m PyInstaller investplan.spec
```

The executable `InvestmentPlanner.exe` will be in the `dist/` folder.

Alternatively, for a quick single-file build:

```bash
python -m PyInstaller --onefile --noconsole main.py
```
