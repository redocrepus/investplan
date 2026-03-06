"""Rebalancing logic — multi-trigger system, cost basis tracking, expense coverage."""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from models.config import SimConfig
from models.bucket import (
    BucketTrigger, TriggerType, SellSubtype, BuySubtype, CostBasisMethod,
)
from engine.bucket import compute_sell, compute_buy


@dataclass
class PurchaseLot:
    """A single purchase lot for FIFO/LIFO cost basis tracking."""
    price: float   # price per unit at purchase time
    amount: float  # amount in bucket currency


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
    # Bucket-level rebalancing fields
    spending_priority: int = 0
    cash_floor_months: float = 0.0
    required_runaway_months: float = 6.0
    # Trigger list
    triggers: list[BucketTrigger] = field(default_factory=list)
    # Cost basis tracking
    cost_basis_method: CostBasisMethod = CostBasisMethod.FIFO
    purchase_lots: list[PurchaseLot] = field(default_factory=list)
    avg_cost: float = 0.0  # weighted average cost for AVCO
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


def get_conversion_fee_pct(bucket_currency: str, expenses_currency: str,
                           config: SimConfig) -> float:
    """Get conversion fee percentage for a currency pair."""
    if bucket_currency == expenses_currency:
        return 0.0
    for cs in config.currencies:
        if cs.code == bucket_currency:
            return cs.conversion_fee_pct
    return 0.0


def _add_purchase_lot(state: BucketState, amount: float, price: float):
    """Record a purchase lot and update AVCO."""
    if amount <= 0:
        return
    state.purchase_lots.append(PurchaseLot(price=price, amount=amount))
    # Update AVCO
    total_amount = sum(lot.amount for lot in state.purchase_lots)
    if total_amount > 0:
        total_cost = sum(lot.price * lot.amount for lot in state.purchase_lots)
        state.avg_cost = total_cost / total_amount


def _compute_cost_basis(state: BucketState, sell_amount: float) -> float:
    """Compute cost basis for a sell using the bucket's chosen method.

    Returns total cost basis for the sold amount. Also consumes lots for FIFO/LIFO.
    """
    if state.cost_basis_method == CostBasisMethod.AVCO:
        return min(sell_amount, state.amount)

    # FIFO or LIFO
    remaining = sell_amount
    cost_basis = 0.0
    if state.cost_basis_method == CostBasisMethod.FIFO:
        lots = state.purchase_lots  # consume from front
        while remaining > 0 and lots:
            lot = lots[0]
            take = min(remaining, lot.amount)
            cost_basis += take
            lot.amount -= take
            remaining -= take
            if lot.amount <= 0:
                lots.pop(0)
    else:  # LIFO
        lots = state.purchase_lots  # consume from back
        while remaining > 0 and lots:
            lot = lots[-1]
            take = min(remaining, lot.amount)
            cost_basis += take
            lot.amount -= take
            remaining -= take
            if lot.amount <= 0:
                lots.pop()

    # If we ran out of lots, treat remaining amount as full-basis principal
    if remaining > 0:
        cost_basis += remaining

    return cost_basis


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


def _portfolio_total_expenses_currency(
    bucket_states: list[BucketState],
    fx_rates: dict[str, float],
    expenses_currency: str,
) -> float:
    """Compute total portfolio value in expenses currency."""
    return sum(
        _bucket_value_in_expenses_currency(b, get_fx_rate(b.currency, expenses_currency, fx_rates))
        for b in bucket_states
    )


def _execute_sell_trigger(
    trigger: BucketTrigger,
    seller: BucketState,
    bucket_states: list[BucketState],
    month_expense: float,
    fx_rates: dict[str, float],
    config: SimConfig,
) -> None:
    """Execute a single sell trigger if conditions are met."""
    expenses_currency = config.expenses_currency
    capital_gain_tax_pct = config.capital_gain_tax_pct
    name_to_state = {b.name: b for b in bucket_states}

    # Runaway guard
    runway = _cash_runway_months(bucket_states, month_expense, fx_rates, expenses_currency)
    if runway < seller.required_runaway_months:
        return

    sell_amount = 0.0

    if trigger.subtype == SellSubtype.TAKE_PROFIT.value:
        # Sell if actual_growth% / target_growth% >= threshold
        if seller.target_growth_pct == 0 or seller.initial_price <= 0:
            return
        actual_growth = (seller.price - seller.initial_price) / seller.initial_price * 100.0
        ratio = actual_growth / seller.target_growth_pct
        if ratio < trigger.threshold_pct:
            return
        # Sell the excess above target
        target_price = seller.initial_price * (1 + seller.target_growth_pct / 100.0)
        excess_per_unit = seller.price - target_price
        if excess_per_unit <= 0:
            return
        fraction_excess = excess_per_unit / seller.price
        sell_amount = seller.amount * fraction_excess

    elif trigger.subtype == SellSubtype.SHARE_EXCEEDS.value:
        # Sell if bucket's share of portfolio > threshold%
        portfolio_total = _portfolio_total_expenses_currency(bucket_states, fx_rates, expenses_currency)
        if portfolio_total <= 0:
            return
        seller_fx = get_fx_rate(seller.currency, expenses_currency, fx_rates)
        seller_value = seller.amount * seller_fx
        share_pct = seller_value / portfolio_total * 100.0
        if share_pct <= trigger.threshold_pct:
            return
        # Sell excess to bring share down to threshold
        target_value = portfolio_total * trigger.threshold_pct / 100.0
        excess_value = seller_value - target_value
        if excess_value <= 0:
            return
        sell_amount = excess_value / seller_fx if seller_fx > 0 else 0

    if sell_amount <= 0:
        return

    # Execute the sell
    net_proceeds, fee = compute_sell(sell_amount, seller.buy_sell_fee_pct)
    seller_fx = get_fx_rate(seller.currency, expenses_currency, fx_rates)

    # Capital gains tax using cost basis
    cost_basis = _compute_cost_basis(seller, sell_amount)
    gain = net_proceeds - cost_basis
    tax = max(0, gain * capital_gain_tax_pct / 100.0)
    after_tax = net_proceeds - tax

    seller.amount -= sell_amount
    seller.amount_sold += sell_amount
    seller.fees_paid += fee * seller_fx
    seller.tax_paid += tax * seller_fx

    # Buy into target bucket if configured
    if trigger.target_bucket and trigger.target_bucket in name_to_state:
        target = name_to_state[trigger.target_bucket]
        target_fx = get_fx_rate(target.currency, expenses_currency, fx_rates)

        # Convert proceeds: seller currency -> expenses currency -> target currency
        proceeds_expenses = after_tax * seller_fx

        # Apply FX conversion fee if cross-currency
        seller_conv_fee_pct = get_conversion_fee_pct(seller.currency, expenses_currency, config)
        if seller.currency != expenses_currency:
            fx_fee = proceeds_expenses * seller_conv_fee_pct / 100.0
            proceeds_expenses -= fx_fee
            seller.fees_paid += fx_fee

        target_conv_fee_pct = get_conversion_fee_pct(target.currency, expenses_currency, config)
        if target.currency != expenses_currency:
            fx_fee = proceeds_expenses * target_conv_fee_pct / 100.0
            proceeds_expenses -= fx_fee
            target.fees_paid += fx_fee

        buy_amount_target = proceeds_expenses / target_fx if target_fx > 0 else 0
        invested, buy_fee = compute_buy(buy_amount_target, target.buy_sell_fee_pct)
        target.amount += invested
        target.amount_bought += invested
        target.fees_paid += buy_fee * target_fx
        _add_purchase_lot(target, invested, target.price)


def _execute_buy_trigger(
    trigger: BucketTrigger,
    buyer: BucketState,
    bucket_states: list[BucketState],
    month_expense: float,
    fx_rates: dict[str, float],
    config: SimConfig,
) -> None:
    """Execute a single buy trigger if conditions are met."""
    expenses_currency = config.expenses_currency
    capital_gain_tax_pct = config.capital_gain_tax_pct
    name_to_state = {b.name: b for b in bucket_states}

    should_buy = False
    buy_value_expenses = 0.0  # how much to buy in expenses currency

    if trigger.subtype == BuySubtype.DISCOUNT.value:
        # Buy if 100 * target_price / current_price - 100 > threshold%
        target_price = buyer.initial_price * (1 + buyer.target_growth_pct / 100.0)
        if buyer.price <= 0:
            return
        discount_pct = 100.0 * target_price / buyer.price - 100.0
        if discount_pct <= trigger.threshold_pct:
            return
        should_buy = True

    elif trigger.subtype == BuySubtype.SHARE_BELOW.value:
        # Buy if bucket's share of portfolio < threshold%
        portfolio_total = _portfolio_total_expenses_currency(bucket_states, fx_rates, expenses_currency)
        if portfolio_total <= 0:
            return
        buyer_fx = get_fx_rate(buyer.currency, expenses_currency, fx_rates)
        buyer_value = buyer.amount * buyer_fx
        share_pct = buyer_value / portfolio_total * 100.0
        if share_pct >= trigger.threshold_pct:
            return
        should_buy = True
        # Calculate how much to buy to reach target share
        target_value = portfolio_total * trigger.threshold_pct / 100.0
        buy_value_expenses = target_value - buyer_value

    if not should_buy:
        return

    # Source bucket to sell from
    if not trigger.target_bucket or trigger.target_bucket not in name_to_state:
        return
    source = name_to_state[trigger.target_bucket]

    # Runaway guard on the source bucket
    runway = _cash_runway_months(bucket_states, month_expense, fx_rates, expenses_currency)
    if runway < source.required_runaway_months:
        return

    source_fx = get_fx_rate(source.currency, expenses_currency, fx_rates)
    buyer_fx = get_fx_rate(buyer.currency, expenses_currency, fx_rates)

    # For discount trigger, use a reasonable buy amount (e.g., 10% of source holdings)
    if trigger.subtype == BuySubtype.DISCOUNT.value:
        buy_value_expenses = source.amount * source_fx * 0.1  # buy with 10% of source

    if buy_value_expenses <= 0:
        return

    # Don't sell more than what's available in source (respect cash floor)
    source_value_expenses = source.amount * source_fx
    source_floor = source.cash_floor_months * month_expense
    available_expenses = max(0, source_value_expenses - source_floor)
    buy_value_expenses = min(buy_value_expenses, available_expenses)

    if buy_value_expenses <= 0:
        return

    # Sell from source
    sell_amount_source = buy_value_expenses / source_fx if source_fx > 0 else 0
    net_proceeds, sell_fee = compute_sell(sell_amount_source, source.buy_sell_fee_pct)

    # Capital gains tax on source sell
    cost_basis = _compute_cost_basis(source, sell_amount_source)
    gain = net_proceeds - cost_basis
    tax = max(0, gain * capital_gain_tax_pct / 100.0)
    after_tax = net_proceeds - tax

    source.amount -= sell_amount_source
    source.amount_sold += sell_amount_source
    source.fees_paid += sell_fee * source_fx
    source.tax_paid += tax * source_fx

    # Convert to expenses currency
    proceeds_expenses = after_tax * source_fx

    # Apply FX conversion fees if cross-currency
    source_conv_fee_pct = get_conversion_fee_pct(source.currency, expenses_currency, config)
    if source.currency != expenses_currency:
        fx_fee = proceeds_expenses * source_conv_fee_pct / 100.0
        proceeds_expenses -= fx_fee
        source.fees_paid += fx_fee

    buyer_conv_fee_pct = get_conversion_fee_pct(buyer.currency, expenses_currency, config)
    if buyer.currency != expenses_currency:
        fx_fee = proceeds_expenses * buyer_conv_fee_pct / 100.0
        proceeds_expenses -= fx_fee
        buyer.fees_paid += fx_fee

    # Buy into buyer bucket
    buy_amount_buyer = proceeds_expenses / buyer_fx if buyer_fx > 0 else 0
    invested, buy_fee = compute_buy(buy_amount_buyer, buyer.buy_sell_fee_pct)
    buyer.amount += invested
    buyer.amount_bought += invested
    buyer.fees_paid += buy_fee * buyer_fx
    _add_purchase_lot(buyer, invested, buyer.price)


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

    # --- Phase 1: Execute sell triggers ---
    for b in bucket_states:
        for trigger in b.triggers:
            if trigger.trigger_type != TriggerType.SELL:
                continue
            if trigger.frequency == "yearly" and month_idx % 12 != 0:
                continue
            _execute_sell_trigger(trigger, b, bucket_states, month_expense, fx_rates, config)

    # --- Phase 2: Execute buy triggers ---
    for b in bucket_states:
        for trigger in b.triggers:
            if trigger.trigger_type != TriggerType.BUY:
                continue
            if trigger.frequency == "yearly" and month_idx % 12 != 0:
                continue
            _execute_buy_trigger(trigger, b, bucket_states, month_expense, fx_rates, config)

    # --- Phase 3: Cover expenses via spending priority cascade ---
    remaining_expense = month_expense
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

        # Tax on gains using cost basis
        cost_basis = _compute_cost_basis(b, sell_bucket_currency)
        gain = net_proceeds - cost_basis
        tax = max(0, gain * capital_gain_tax_pct / 100.0)
        after_tax = net_proceeds - tax

        # Apply FX conversion fee if needed
        conv_fee_pct = get_conversion_fee_pct(b.currency, expenses_currency, config)
        net_in_expenses = after_tax * fx
        if b.currency != expenses_currency:
            fx_fee = net_in_expenses * conv_fee_pct / 100.0
            net_in_expenses -= fx_fee
            b.fees_paid += fx_fee

        b.amount -= sell_bucket_currency
        b.amount_sold += sell_bucket_currency
        b.fees_paid += fee * fx
        b.tax_paid += tax * fx
        b.net_spent += net_in_expenses

        remaining_expense -= net_in_expenses

    total_covered = month_expense - max(0, remaining_expense)
    return total_covered
