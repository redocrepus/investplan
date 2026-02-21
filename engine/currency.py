"""FX rate simulation — log-normal random walk bounded by min/max."""

import numpy as np
from models.currency import CurrencySettings
from utils.volatility import get_volatility_spec, DistributionType


def simulate_fx_rates(
    settings: CurrencySettings,
    n_months: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Simulate monthly FX prices for a currency pair.

    Returns array of length n_months with prices in expenses currency.
    """
    spec = get_volatility_spec(settings.volatility)

    prices = np.empty(n_months)
    current = settings.initial_price

    if spec.distribution == DistributionType.CONSTANT:
        prices[:] = settings.avg_price
        return prices

    # Monthly drift toward average (mean-reverting log-normal)
    avg = settings.avg_price
    reversion_speed = 0.05

    for i in range(n_months):
        log_current = np.log(current)
        log_avg = np.log(avg)
        drift = reversion_speed * (log_avg - log_current)
        shock = rng.normal(0, spec.monthly_sigma)
        log_new = log_current + drift + shock
        current = np.exp(log_new)
        current = np.clip(current, settings.min_price, settings.max_price)
        prices[i] = current

    return prices
