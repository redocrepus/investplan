# Investment Planner

Application for investment strategy planning and Monte Carlo simulation.

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

## Test

```bash
pytest tests/ -v
```

## Build (Windows .exe)

```bash
pyinstaller --onefile main.py
```

The executable will be in the `dist/` folder.
