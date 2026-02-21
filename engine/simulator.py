"""Orchestrates a single simulation run, returning a DataFrame."""

import numpy as np
import pandas as pd
from models.config import SimConfig
from engine.inflation import simulate_monthly_inflation
from engine.currency import simulate_fx_rates
from engine.bucket import simulate_bucket_prices
from engine.expenses import compute_monthly_expenses
from engine.rebalancer import BucketState, execute_rebalance, get_fx_rate


def _init_bucket_state(bucket, price: float) -> BucketState:
    """Create a BucketState from a bucket model and initial price."""
    return BucketState(
        name=bucket.name,
        currency=bucket.currency,
        price=price,
        amount=bucket.initial_amount,
        initial_price=bucket.initial_price,
        target_growth_pct=bucket.target_growth_pct,
        buy_sell_fee_pct=bucket.buy_sell_fee_pct,
        sell_trigger=bucket.rebalancing.sell_trigger,
        standby_bucket=bucket.rebalancing.standby_bucket,
        buy_trigger=bucket.rebalancing.buy_trigger,
        buying_priority=bucket.rebalancing.buying_priority,
        required_runaway_months=bucket.rebalancing.required_runaway_months,
        spending_priority=bucket.rebalancing.spending_priority,
        cash_floor_months=bucket.rebalancing.cash_floor_months,
        frequency=bucket.rebalancing.frequency,
    )


def run_simulation(config: SimConfig, rng: np.random.Generator) -> pd.DataFrame:
    """Run a single simulation and return results as a DataFrame.

    Columns include: year, month, inflation, expenses, total_net_spent,
    plus per-bucket columns (price, price_exp, amount, amount_exp,
    sold, sold_exp, bought, fees, tax, net_spent).
    """
    n_months = config.period_years * 12

    # Simulate inflation
    inflation_rates = simulate_monthly_inflation(config.inflation, n_months, rng)

    # Simulate FX rates for each non-expenses currency
    fx_price_series: dict[str, np.ndarray] = {}
    for cs in config.currencies:
        fx_price_series[cs.code] = simulate_fx_rates(cs, n_months, rng)

    # Simulate bucket prices
    bucket_price_series: dict[str, np.ndarray] = {}
    for bucket in config.buckets:
        bucket_price_series[bucket.name] = simulate_bucket_prices(bucket, n_months, rng)

    # Compute monthly expenses
    expenses = compute_monthly_expenses(
        config.expense_periods, config.one_time_expenses,
        inflation_rates, n_months, rng,
    )

    # Initialize bucket states
    bucket_states = []
    for bucket in config.buckets:
        state = _init_bucket_state(bucket, bucket.initial_price)
        bucket_states.append(state)

    # Monthly simulation loop
    rows = []
    for m in range(n_months):
        year = m // 12 + 1
        month = m % 12 + 1

        # Update bucket prices
        for i, bucket in enumerate(config.buckets):
            bucket_states[i].price = bucket_price_series[bucket.name][m]

        # Build current FX rates dict
        current_fx: dict[str, float] = {}
        for cs in config.currencies:
            current_fx[cs.code] = fx_price_series[cs.code][m]

        # Execute rebalancing and expense coverage
        total_covered = execute_rebalance(
            bucket_states, expenses[m], current_fx, config, m,
        )

        # Build row
        row: dict[str, float] = {
            "year": year,
            "month": month,
            "inflation": inflation_rates[m],
            "expenses": expenses[m],
            "total_net_spent": sum(b.net_spent for b in bucket_states),
        }

        # Per-bucket columns
        for b in bucket_states:
            fx = get_fx_rate(b.currency, config.expenses_currency, current_fx)
            prefix = b.name
            row[f"{prefix}_price"] = b.price
            row[f"{prefix}_price_exp"] = b.price * fx
            row[f"{prefix}_amount"] = b.amount
            row[f"{prefix}_amount_exp"] = b.amount * fx
            row[f"{prefix}_sold"] = b.amount_sold
            row[f"{prefix}_sold_exp"] = b.amount_sold * fx
            row[f"{prefix}_bought"] = b.amount_bought
            row[f"{prefix}_fees"] = b.fees_paid
            row[f"{prefix}_tax"] = b.tax_paid
            row[f"{prefix}_net_spent"] = b.net_spent

        rows.append(row)

    return pd.DataFrame(rows)
