"""Monte Carlo simulation — run N simulations and collect statistics."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd
from models.config import SimConfig
from engine.simulator import run_simulation


@dataclass
class MonteCarloResult:
    """Results from a Monte Carlo run."""
    n_simulations: int
    success_count: int
    success_rate: float  # 0.0 to 1.0
    percentile_10: pd.DataFrame
    percentile_50: pd.DataFrame
    percentile_90: pd.DataFrame


def run_monte_carlo(
    config: SimConfig,
    n_simulations: int = 100,
    seed: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> MonteCarloResult:
    """Run N simulations and compute success rate + percentile frames.

    A simulation is "successful" if total_net_spent >= expenses for every month.
    """
    base_rng = np.random.default_rng(seed)

    all_total_net_spent: list[np.ndarray] = []
    all_expenses: list[np.ndarray] = []
    all_frames: list[pd.DataFrame] = []
    success_count = 0

    for i in range(n_simulations):
        # Derive a child RNG for each simulation
        child_seed = base_rng.integers(0, 2**31)
        rng = np.random.default_rng(child_seed)

        df = run_simulation(config, rng)
        all_frames.append(df)
        all_total_net_spent.append(df["total_net_spent"].values)
        all_expenses.append(df["expenses"].values)

        # Check success: net_spent covers expenses every month (with small tolerance)
        shortfall = df["expenses"].values - df["total_net_spent"].values
        if np.all(shortfall <= 0.01):  # small tolerance for floating point
            success_count += 1

        if progress_callback:
            progress_callback(i + 1, n_simulations)

    # Compute percentile frames from total_net_spent
    n_months = config.period_years * 12
    net_spent_matrix = np.array(all_total_net_spent)  # shape: (n_sims, n_months)

    # Use the first frame as template for structure
    template = all_frames[0][["year", "month"]].copy()

    def _percentile_frame(pct: float) -> pd.DataFrame:
        frame = template.copy()
        frame["total_net_spent"] = np.percentile(net_spent_matrix, pct, axis=0)
        frame["expenses"] = np.percentile(
            np.array(all_expenses), pct, axis=0
        )
        # Add per-bucket amounts at this percentile
        for col in all_frames[0].columns:
            if col.endswith("_amount_exp"):
                vals = np.array([f[col].values for f in all_frames])
                frame[col] = np.percentile(vals, pct, axis=0)
        return frame

    return MonteCarloResult(
        n_simulations=n_simulations,
        success_count=success_count,
        success_rate=success_count / n_simulations if n_simulations > 0 else 0.0,
        percentile_10=_percentile_frame(10),
        percentile_50=_percentile_frame(50),
        percentile_90=_percentile_frame(90),
    )
