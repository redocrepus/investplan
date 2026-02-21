# Investment Planner

Application for investment strategy planning and Monte Carlo simulation.

## Features

- Configurable investment buckets with growth, volatility, and rebalancing parameters
- Monthly expense periods with inflation adjustment
- Multi-currency support with FX simulation
- Target-trajectory rebalancing with sell/buy triggers, runaway guard, and cash-floor cascade
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
python main.py
```

This launches the GUI with:
- **Left panel** — Global settings, expenses, buckets, and currency configuration
- **Right panel** — Simulation results table with collapsible bucket column groups
- **Toolbar** — Run Simulation, Run Monte Carlo, Save/Load Config, Export CSV

The last session's configuration is automatically restored on launch.

## Test

```bash
pytest tests/ -v
```

## Build (Windows .exe)

```bash
pyinstaller investplan.spec
```

The executable `InvestmentPlanner.exe` will be in the `dist/` folder.

Alternatively, for a quick single-file build:

```bash
pyinstaller --onefile --noconsole main.py
```
