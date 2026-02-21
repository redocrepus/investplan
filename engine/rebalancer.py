"""Rebalancing logic — sell/buy triggers, runaway guard, cash-floor cascade."""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from models.config import SimConfig
from engine.bucket import compute_sell, compute_buy


@dataclass
class BucketState:
    """Mutable state for a single bucket during simulation."""
    name: str
    currency: str
    price: float               # current price in bucket currency
    amount: float              # total holding in bucket currency
    initial_price: float       # price at start for growth calculation
    target_growth_pct: float
    buy_sell_fee_pct: float
    # Rebalancing params (copied from model for convenience)
    sell_trigger: float = 1.5
    standby_bucket: str | None = None
    buy_trigger: float = 5.0
    buying_priority: int = 0
    required_runaway_months: float = 6.0
    spending_priority: int = 0
    cash_floor_months: float = 0.0
    frequency: str = "monthly"
    # Tracking for this month
    amount_sold: float = 0.0
    amount_bought: float = 0.0
    fees_paid: float = 0.0
    tax_paid: float = 0.0
    net_spent: float = 0.0


def get_fx_rate(bucket_currency: str, expenses_currency: str,
                fx_rates: dict[str, float]) -> float:
    """Get FX rate to convert from bucket currency to expenses currency."""
    if bucket_currency == expenses_currency:
        return 1.0
    return fx_rates.get(bucket_currency, 1.0)


def check_sell_trigger(bucket: BucketState) -> bool:
    """Check if bucket's actual growth exceeds target by the sell trigger ratio."""
    if bucket.target_growth_pct == 0:
        return False
    if bucket.initial_price <= 0:
        return False
    actual_growth = (bucket.price - bucket.initial_price) / bucket.initial_price * 100.0
    target_growth = bucket.target_growth_pct
    if target_growth == 0:
        return actual_growth > 0
    ratio = actual_growth / target_growth
    return ratio > bucket.sell_trigger


def check_buy_trigger(bucket: BucketState) -> bool:
    """Check if standby bucket price is low enough to warrant buying."""
    target_price = bucket.initial_price * (1 + bucket.target_growth_pct / 100.0)
    if bucket.price <= 0:
        return False
    discount_pct = 100.0 * target_price / bucket.price - 100.0
    return discount_pct > bucket.buy_trigger


def _bucket_value_in_expenses_currency(
    bucket: BucketState, fx_rate: float,
) -> float:
    """Total bucket value in expenses currency."""
    return bucket.amount * fx_rate


def _cash_runway_months(
    bucket_states: list[BucketState],
    monthly_expense: float,
    fx_rates: dict[str, float],
    expenses_currency: str,
) -> float:
    """Compute total portfolio value in months of expenses."""
    if monthly_expense <= 0:
        return float("inf")
    total = sum(
        _bucket_value_in_expenses_currency(b, get_fx_rate(b.currency, expenses_currency, fx_rates))
        for b in bucket_states
    )
    return total / monthly_expense


def execute_rebalance(
    bucket_states: list[BucketState],
    month_expense: float,
    fx_rates: dict[str, float],
    config: SimConfig,
    month_idx: int,
) -> float:
    """Execute full rebalancing pass for one month.

    Returns the total amount covered toward expenses (in expenses currency).
    """
    expenses_currency = config.expenses_currency
    capital_gain_tax_pct = config.capital_gain_tax_pct

    # Reset monthly tracking
    for b in bucket_states:
        b.amount_sold = 0.0
        b.amount_bought = 0.0
        b.fees_paid = 0.0
        b.tax_paid = 0.0
        b.net_spent = 0.0

    # --- Phase 1: Target-trajectory rebalancing (sell overperformers, buy standby) ---
    name_to_state = {b.name: b for b in bucket_states}

    for b in bucket_states:
        # Check frequency
        if b.frequency == "yearly" and month_idx % 12 != 0:
            continue

        if not check_sell_trigger(b):
            continue

        # Runaway guard
        runway = _cash_runway_months(bucket_states, month_expense, fx_rates, expenses_currency)
        if runway < b.required_runaway_months:
            continue

        # Calculate excess to sell
        target_price = b.initial_price * (1 + b.target_growth_pct / 100.0)
        excess_per_unit = b.price - target_price
        if excess_per_unit <= 0:
            continue

        # Sell only the excess portion (proportional to holdings)
        fraction_excess = excess_per_unit / b.price
        sell_amount = b.amount * fraction_excess

        if sell_amount <= 0:
            continue

        net_proceeds, fee = compute_sell(sell_amount, b.buy_sell_fee_pct)
        fx = get_fx_rate(b.currency, expenses_currency, fx_rates)

        # Capital gains tax on the gain portion
        cost_basis = sell_amount * (b.initial_price / b.price)
        gain = net_proceeds - cost_basis
        tax = max(0, gain * capital_gain_tax_pct / 100.0)
        after_tax = net_proceeds - tax

        b.amount -= sell_amount
        b.amount_sold += sell_amount
        b.fees_paid += fee * fx
        b.tax_paid += tax * fx

        # Buy into standby bucket if configured
        if b.standby_bucket and b.standby_bucket in name_to_state:
            standby = name_to_state[b.standby_bucket]
            if check_buy_trigger(standby):
                # Convert proceeds to standby currency
                standby_fx = get_fx_rate(standby.currency, expenses_currency, fx_rates)
                buy_amount_standby = after_tax * fx / standby_fx if standby_fx > 0 else 0
                invested, buy_fee = compute_buy(buy_amount_standby, standby.buy_sell_fee_pct)
                standby.amount += invested
                standby.amount_bought += invested
                standby.fees_paid += buy_fee * standby_fx

    # --- Phase 2: Cover expenses via spending priority cascade ---
    remaining_expense = month_expense
    # Sort by spending priority (lower = sell first)
    spending_order = sorted(bucket_states, key=lambda b: b.spending_priority)

    for b in spending_order:
        if remaining_expense <= 0:
            break

        fx = get_fx_rate(b.currency, expenses_currency, fx_rates)
        if fx <= 0:
            continue

        bucket_value_expenses = b.amount * fx

        # Cash floor: keep at least cash_floor_months of expenses
        floor_amount_expenses = b.cash_floor_months * month_expense
        available_expenses = max(0, bucket_value_expenses - floor_amount_expenses)

        if available_expenses <= 0:
            continue

        sell_expenses = min(remaining_expense, available_expenses)
        sell_bucket_currency = sell_expenses / fx

        net_proceeds, fee = compute_sell(sell_bucket_currency, b.buy_sell_fee_pct)

        # Tax on gains
        if b.price > 0:
            cost_basis = sell_bucket_currency * (b.initial_price / b.price)
        else:
            cost_basis = 0
        gain = net_proceeds - cost_basis
        tax = max(0, gain * capital_gain_tax_pct / 100.0)
        after_tax = net_proceeds - tax
        net_in_expenses = after_tax * fx

        b.amount -= sell_bucket_currency
        b.amount_sold += sell_bucket_currency
        b.fees_paid += fee * fx
        b.tax_paid += tax * fx
        b.net_spent += net_in_expenses

        remaining_expense -= net_in_expenses

    total_covered = month_expense - max(0, remaining_expense)
    return total_covered
