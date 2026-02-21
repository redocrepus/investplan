"""Inflation simulation — mean-reverting random walk."""

import numpy as np
from models.inflation import InflationSettings
from utils.volatility import get_inflation_volatility_spec, DistributionType


def simulate_monthly_inflation(
    settings: InflationSettings,
    n_months: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Simulate monthly inflation rates as a mean-reverting random walk.

    Returns an array of length n_months with monthly inflation rates (as fractions,
    e.g. 0.002 for 0.2% monthly inflation).
    """
    spec = get_inflation_volatility_spec(settings.volatility)
    # Convert annual percentages to monthly fractions
    avg_monthly = settings.avg_pct / 100.0 / 12.0
    min_monthly = settings.min_pct / 100.0 / 12.0
    max_monthly = settings.max_pct / 100.0 / 12.0

    rates = np.empty(n_months)
    current = avg_monthly

    if spec.distribution == DistributionType.CONSTANT:
        rates[:] = avg_monthly
        return rates

    # Mean-reversion speed
    reversion_speed = 0.1

    for i in range(n_months):
        # Mean-reverting step
        drift = reversion_speed * (avg_monthly - current)
        shock = rng.normal(0, spec.monthly_sigma / 12.0)
        current = current + drift + shock
        # Clamp to bounds
        current = np.clip(current, min_monthly, max_monthly)
        rates[i] = current

    return rates
