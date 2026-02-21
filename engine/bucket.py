"""Bucket price simulation and buy/sell helpers."""

import numpy as np
from models.bucket import InvestmentBucket
from utils.volatility import get_volatility_spec, DistributionType


def simulate_bucket_prices(
    bucket: InvestmentBucket,
    n_months: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Simulate monthly prices for a bucket using log-normal random walk.

    Returns array of length n_months with prices in bucket's currency.
    """
    spec = get_volatility_spec(bucket.volatility)

    prices = np.empty(n_months)
    current = bucket.initial_price

    if spec.distribution == DistributionType.CONSTANT:
        # Constant growth at average rate
        monthly_growth = (1 + bucket.growth_avg_pct / 100.0) ** (1 / 12) - 1
        for i in range(n_months):
            current *= (1 + monthly_growth)
            prices[i] = current
        return prices

    # Log-normal random walk with monthly drift from average yearly growth
    monthly_drift = np.log(1 + bucket.growth_avg_pct / 100.0) / 12.0
    # Clamp growth bounds (convert yearly to monthly log terms)
    min_monthly_log = np.log(1 + bucket.growth_min_pct / 100.0) / 12.0
    max_monthly_log = np.log(1 + bucket.growth_max_pct / 100.0) / 12.0

    for i in range(n_months):
        log_return = rng.normal(monthly_drift, spec.monthly_sigma)
        # Clamp the log return
        log_return = np.clip(log_return, min_monthly_log - 0.01, max_monthly_log + 0.01)
        current *= np.exp(log_return)
        # Price can't go below a small floor
        current = max(current, 0.001)
        prices[i] = current

    return prices


def compute_sell(amount_currency: float, fee_pct: float) -> tuple[float, float]:
    """Sell an amount, deducting the fee.

    Returns (net_proceeds, fee_paid) both in the bucket's currency.
    """
    fee = amount_currency * fee_pct / 100.0
    net = amount_currency - fee
    return net, fee


def compute_buy(spend_currency: float, fee_pct: float) -> tuple[float, float]:
    """Buy with a given amount, deducting the fee first.

    Returns (amount_invested, fee_paid) both in the bucket's currency.
    """
    fee = spend_currency * fee_pct / 100.0
    invested = spend_currency - fee
    return invested, fee
