"""Orchestrates a single simulation run, returning a DataFrame."""

import numpy as np
import pandas as pd
from models.config import SimConfig
from models.bucket import InvestmentBucket
from engine.inflation import simulate_monthly_inflation
from engine.currency import simulate_fx_rates
from engine.bucket import simulate_bucket_prices
from engine.expenses import compute_monthly_expenses
from engine.rebalancer import (
    BucketState, CashPoolState, PurchaseLot, execute_rebalance,
    get_fx_rate, _add_purchase_lot,
)


def _init_bucket_state(bucket: InvestmentBucket) -> BucketState:
    """Create a BucketState from a bucket model."""
    state = BucketState(
        name=bucket.name,
        currency=bucket.currency,
        price=bucket.initial_price,
        amount=bucket.initial_amount,
        initial_price=bucket.initial_price,
        target_growth_pct=bucket.target_growth_pct,
        buy_sell_fee_pct=bucket.buy_sell_fee_pct,
        spending_priority=bucket.spending_priority,
        cash_floor_months=bucket.cash_floor_months,
        required_runaway_months=bucket.required_runaway_months,
        triggers=list(bucket.triggers),
        cost_basis_method=bucket.cost_basis_method,
    )
    # Initialize with one lot at initial price
    _add_purchase_lot(state, bucket.initial_amount, bucket.initial_price)
    return state


def run_simulation(config: SimConfig, rng: np.random.Generator) -> pd.DataFrame:
    """Run a single simulation and return results as a DataFrame.

    Columns include: year, month, inflation, expenses, total_net_spent,
    cash_pool_amount, cash_pool_net_spent,
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
        state = _init_bucket_state(bucket)
        bucket_states.append(state)

    # Initialize cash pool
    cash_pool = CashPoolState(
        amount=config.cash_pool.initial_amount,
        refill_trigger_months=config.cash_pool.refill_trigger_months,
        refill_target_months=config.cash_pool.refill_target_months,
        cash_floor_months=config.cash_pool.cash_floor_months,
    )
    # Only use cash pool if it has a meaningful configuration
    # (either has initial cash or has a refill target with buckets to sell from)
    use_cash_pool = config.cash_pool.initial_amount > 0

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
            cash_pool=cash_pool if use_cash_pool else None,
        )

        # Build row
        row: dict[str, float] = {
            "year": year,
            "month": month,
            "inflation": inflation_rates[m],
            "expenses": expenses[m],
            "total_net_spent": (
                cash_pool.net_spent if use_cash_pool
                else sum(b.net_spent for b in bucket_states)
            ),
            "cash_pool_amount": cash_pool.amount,
            "cash_pool_net_spent": cash_pool.net_spent,
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
