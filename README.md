# Investment Planner

Application for investment strategy planning and Monte Carlo simulation.

## Features

- Configurable investment buckets with growth, volatility, and rebalancing parameters
- Monthly expense periods with inflation adjustment
- Multi-currency support with FX simulation
- Target-trajectory rebalancing with sell/buy triggers, runaway guard, and cash-floor cascade
- Monte Carlo simulation with success rate and percentile statistics
- Save/load configuration to JSON
- Export simulation results to CSV

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

## Test

```bash
pytest tests/ -v
```

## Build (Windows .exe)

```bash
pyinstaller --onefile main.py
```

The executable will be in the `dist/` folder.
