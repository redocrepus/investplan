"""Rebalancing logic — multi-trigger system, cost basis tracking, cash pool, expense coverage."""

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


@dataclass
class CashPoolState:
    """Mutable state for the cash pool (expenses currency only)."""
    amount: float = 0.0
    refill_trigger_months: float = 12.0
    refill_target_months: float = 24.0
    cash_floor_months: float = 6.0
    # Monthly tracking
    net_spent: float = 0.0  # expenses drawn this month


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


def _get_share_floor(bucket_state: BucketState) -> float | None:
    """Return implicit share% floor from share_below buy triggers, or None."""
    for t in bucket_state.triggers:
        if t.trigger_type == TriggerType.BUY and t.subtype == BuySubtype.SHARE_BELOW.value:
            return t.threshold_pct
    return None


def _get_share_ceiling(bucket_state: BucketState) -> float | None:
    """Return implicit share% ceiling from share_exceeds sell triggers, or None."""
    for t in bucket_state.triggers:
        if t.trigger_type == TriggerType.SELL and t.subtype == SellSubtype.SHARE_EXCEEDS.value:
            return t.threshold_pct
    return None


def _available_to_sell(
    bucket: BucketState,
    month_expense: float,
    fx_rate: float,
    bucket_states: list[BucketState],
    fx_rates: dict[str, float],
    expenses_currency: str,
) -> float:
    """Compute how much (in expenses currency) can be sold from a bucket respecting all floors.

    Floors considered:
    1. Cash floor: bucket.cash_floor_months * month_expense
    2. Share% floor: if bucket has a share_below X% trigger, don't sell below portfolio_total * X%
    Returns amount in expenses currency.
    """
    bucket_value = bucket.amount * fx_rate
    # Cash floor
    cash_floor = bucket.cash_floor_months * month_expense
    # Share% floor
    share_floor_pct = _get_share_floor(bucket)
    share_floor = 0.0
    if share_floor_pct is not None:
        portfolio_total = _portfolio_total_expenses_currency(bucket_states, fx_rates, expenses_currency)
        share_floor = portfolio_total * share_floor_pct / 100.0
    effective_floor = max(cash_floor, share_floor)
    return max(0.0, bucket_value - effective_floor)


def _bucket_profitability(
    b: BucketState, fx_rate: float, fee_pct: float,
    conv_fee_pct: float, expenses_currency: str,
) -> float:
    """Compute profitability of selling from a bucket: gross gain after FX + fees."""
    value_exp = b.amount * fx_rate
    fee_cost = value_exp * fee_pct / 100.0
    conv_cost = 0.0
    if b.currency != expenses_currency:
        conv_cost = value_exp * conv_fee_pct / 100.0
    # Gain = current value - cost basis (approximated by initial price ratio)
    if b.initial_price > 0:
        gain_ratio = (b.price - b.initial_price) / b.initial_price
    else:
        gain_ratio = 0.0
    gross_gain = value_exp * gain_ratio - fee_cost - conv_cost
    return gross_gain


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

        # Enforce target's share ceiling (implicit from share_exceeds trigger)
        target_ceiling_pct = _get_share_ceiling(target)
        if target_ceiling_pct is not None:
            portfolio_total = _portfolio_total_expenses_currency(bucket_states, fx_rates, expenses_currency)
            target_value = target.amount * target_fx
            ceiling_value = portfolio_total * target_ceiling_pct / 100.0
            headroom = max(0.0, ceiling_value - target_value)
            proceeds_expenses = min(proceeds_expenses, headroom)

        if proceeds_expenses <= 0:
            return

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
    """Execute a single buy trigger if conditions are met.

    Sells from source_buckets in profitability order (profitable first, then
    user-defined priority order for losing sources). Each source is sold down
    to its floors (cash floor + implicit share% floor).
    """
    expenses_currency = config.expenses_currency
    capital_gain_tax_pct = config.capital_gain_tax_pct
    name_to_state = {b.name: b for b in bucket_states}

    should_buy = False
    buy_value_expenses = 0.0  # how much to buy in expenses currency (0 = unlimited/all available)
    unlimited_buy = False

    if trigger.subtype == BuySubtype.DISCOUNT.value:
        # Buy if 100 * target_price / current_price - 100 > threshold%
        target_price = buyer.initial_price * (1 + buyer.target_growth_pct / 100.0)
        if buyer.price <= 0:
            return
        discount_pct = 100.0 * target_price / buyer.price - 100.0
        if discount_pct <= trigger.threshold_pct:
            return
        should_buy = True
        unlimited_buy = True  # sell all available from sources down to floors

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

    # Resolve source buckets
    sources = []
    for sname in trigger.source_buckets:
        if sname in name_to_state:
            sources.append(name_to_state[sname])
    if not sources:
        return

    # Enforce buyer's share ceiling (implicit from share_exceeds trigger)
    buyer_fx = get_fx_rate(buyer.currency, expenses_currency, fx_rates)
    buyer_ceiling_pct = _get_share_ceiling(buyer)
    if buyer_ceiling_pct is not None:
        portfolio_total = _portfolio_total_expenses_currency(bucket_states, fx_rates, expenses_currency)
        buyer_value = buyer.amount * buyer_fx
        ceiling_value = portfolio_total * buyer_ceiling_pct / 100.0
        headroom = max(0.0, ceiling_value - buyer_value)
        if not unlimited_buy:
            buy_value_expenses = min(buy_value_expenses, headroom)
        else:
            buy_value_expenses = headroom
            unlimited_buy = False
        if buy_value_expenses <= 0:
            return

    # Compute profitability for each source and sort
    source_info = []
    for s in sources:
        s_fx = get_fx_rate(s.currency, expenses_currency, fx_rates)
        conv_fee_pct = get_conversion_fee_pct(s.currency, expenses_currency, config)
        profit = _bucket_profitability(s, s_fx, s.buy_sell_fee_pct, conv_fee_pct, expenses_currency)
        avail = _available_to_sell(s, month_expense, s_fx, bucket_states, fx_rates, expenses_currency)
        source_info.append((s, profit, s_fx, avail))

    # Sort: profitable descending first, then unprofitable in original list order
    profitable = [(s, p, fx, av) for s, p, fx, av in source_info if p > 0]
    unprofitable = [(s, p, fx, av) for s, p, fx, av in source_info if p <= 0]
    profitable.sort(key=lambda x: x[1], reverse=True)
    # unprofitable keeps original order (user-defined priority)
    sorted_sources = profitable + unprofitable

    # Sell from sources
    remaining_need = buy_value_expenses
    total_proceeds_expenses = 0.0

    for source, _profit, source_fx, available in sorted_sources:
        if not unlimited_buy and remaining_need <= 0:
            break
        if available <= 0 or source_fx <= 0:
            continue

        # Runaway guard on the source bucket
        runway = _cash_runway_months(bucket_states, month_expense, fx_rates, expenses_currency)
        if runway < source.required_runaway_months:
            continue

        if unlimited_buy:
            sell_expenses = available
        else:
            sell_expenses = min(remaining_need, available)

        sell_bucket_currency = sell_expenses / source_fx

        net_proceeds, sell_fee = compute_sell(sell_bucket_currency, source.buy_sell_fee_pct)

        # Capital gains tax on source sell
        cost_basis = _compute_cost_basis(source, sell_bucket_currency)
        gain = net_proceeds - cost_basis
        tax = max(0, gain * capital_gain_tax_pct / 100.0)
        after_tax = net_proceeds - tax

        source.amount -= sell_bucket_currency
        source.amount_sold += sell_bucket_currency
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

        total_proceeds_expenses += proceeds_expenses
        if not unlimited_buy:
            remaining_need -= proceeds_expenses

    if total_proceeds_expenses <= 0:
        return

    # Apply buyer FX conversion fee if cross-currency
    buyer_conv_fee_pct = get_conversion_fee_pct(buyer.currency, expenses_currency, config)
    if buyer.currency != expenses_currency:
        fx_fee = total_proceeds_expenses * buyer_conv_fee_pct / 100.0
        total_proceeds_expenses -= fx_fee
        buyer.fees_paid += fx_fee

    # Buy into buyer bucket
    buy_amount_buyer = total_proceeds_expenses / buyer_fx if buyer_fx > 0 else 0
    invested, buy_fee = compute_buy(buy_amount_buyer, buyer.buy_sell_fee_pct)
    buyer.amount += invested
    buyer.amount_bought += invested
    buyer.fees_paid += buy_fee * buyer_fx
    _add_purchase_lot(buyer, invested, buyer.price)


def _refill_cash_pool(
    cash_pool: CashPoolState,
    bucket_states: list[BucketState],
    month_expense: float,
    fx_rates: dict[str, float],
    config: SimConfig,
) -> None:
    """Refill cash pool from investment buckets when below target.

    Sells from most profitable bucket first, respecting source cash floors.
    If no profitable buckets, sells in spending priority order.
    """
    if month_expense <= 0:
        return

    trigger_amount = cash_pool.refill_trigger_months * month_expense
    if cash_pool.amount >= trigger_amount:
        return

    target_amount = cash_pool.refill_target_months * month_expense

    needed = target_amount - cash_pool.amount
    expenses_currency = config.expenses_currency
    capital_gain_tax_pct = config.capital_gain_tax_pct

    # Compute profitability for each bucket
    bucket_profit = []
    for b in bucket_states:
        fx = get_fx_rate(b.currency, expenses_currency, fx_rates)
        conv_fee_pct = get_conversion_fee_pct(b.currency, expenses_currency, config)
        profit = _bucket_profitability(b, fx, b.buy_sell_fee_pct, conv_fee_pct, expenses_currency)
        bucket_profit.append((b, profit, fx))

    # Separate profitable and unprofitable
    profitable = [(b, p, fx) for b, p, fx in bucket_profit if p > 0]
    unprofitable = [(b, p, fx) for b, p, fx in bucket_profit if p <= 0]

    # Sort profitable by profitability descending (sell most profitable first)
    profitable.sort(key=lambda x: x[1], reverse=True)
    # Sort unprofitable by spending priority ascending
    unprofitable.sort(key=lambda x: x[0].spending_priority)

    # Try profitable first, then unprofitable
    sell_order = profitable + unprofitable

    for b, _profit, fx in sell_order:
        if needed <= 0:
            break
        if fx <= 0:
            continue

        available_expenses = _available_to_sell(
            b, month_expense, fx, bucket_states, fx_rates, expenses_currency,
        )

        if available_expenses <= 0:
            continue

        sell_expenses = min(needed, available_expenses)
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

        cash_pool.amount += net_in_expenses
        needed -= net_in_expenses


def _cover_expenses_from_buckets(
    remaining_expense: float,
    bucket_states: list[BucketState],
    month_expense: float,
    fx_rates: dict[str, float],
    config: SimConfig,
) -> float:
    """Cover expenses by selling from buckets in spending priority order.

    Returns the remaining uncovered expense amount.
    """
    expenses_currency = config.expenses_currency
    capital_gain_tax_pct = config.capital_gain_tax_pct
    spending_order = sorted(bucket_states, key=lambda b: b.spending_priority)

    for b in spending_order:
        if remaining_expense <= 0:
            break

        fx = get_fx_rate(b.currency, expenses_currency, fx_rates)
        if fx <= 0:
            continue

        bucket_value_expenses = b.amount * fx
        floor_amount_expenses = b.cash_floor_months * month_expense
        available_expenses = max(0, bucket_value_expenses - floor_amount_expenses)

        if available_expenses <= 0:
            continue

        sell_expenses = min(remaining_expense, available_expenses)
        sell_bucket_currency = sell_expenses / fx

        net_proceeds, fee = compute_sell(sell_bucket_currency, b.buy_sell_fee_pct)

        cost_basis = _compute_cost_basis(b, sell_bucket_currency)
        gain = net_proceeds - cost_basis
        tax = max(0, gain * capital_gain_tax_pct / 100.0)
        after_tax = net_proceeds - tax

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

    return remaining_expense


def execute_rebalance(
    bucket_states: list[BucketState],
    month_expense: float,
    fx_rates: dict[str, float],
    config: SimConfig,
    month_idx: int,
    cash_pool: CashPoolState | None = None,
) -> float:
    """Execute full rebalancing pass for one month.

    Returns the total amount covered toward expenses (in expenses currency).
    """
    expenses_currency = config.expenses_currency

    # Reset monthly tracking
    for b in bucket_states:
        b.amount_sold = 0.0
        b.amount_bought = 0.0
        b.fees_paid = 0.0
        b.tax_paid = 0.0
        b.net_spent = 0.0

    if cash_pool is not None:
        cash_pool.net_spent = 0.0

    # --- Phase 1: Execute sell triggers ---
    for b in bucket_states:
        for trigger in b.triggers:
            if trigger.trigger_type != TriggerType.SELL:
                continue
            if trigger.period_months > 1 and month_idx % trigger.period_months != 0:
                continue
            _execute_sell_trigger(trigger, b, bucket_states, month_expense, fx_rates, config)

    # --- Phase 2: Cover expenses ---
    if cash_pool is not None:
        # If cash pool is insufficient, refill it first
        if cash_pool.amount < month_expense:
            _refill_cash_pool(cash_pool, bucket_states, month_expense, fx_rates, config)

        # Draw expenses from cash pool
        drawn = min(cash_pool.amount, month_expense)
        cash_pool.amount -= drawn
        cash_pool.net_spent = drawn
        remaining_expense = month_expense - drawn

        # If cash pool still couldn't cover, fall through to direct bucket selling
        if remaining_expense > 0:
            remaining_expense = _cover_expenses_from_buckets(
                remaining_expense, bucket_states, month_expense, fx_rates, config,
            )

        total_covered = month_expense - max(0, remaining_expense)
    else:
        remaining_expense = _cover_expenses_from_buckets(
            month_expense, bucket_states, month_expense, fx_rates, config,
        )
        total_covered = month_expense - max(0, remaining_expense)

    # --- Phase 3: Refill cash pool (post-expenses, if still below trigger) ---
    if cash_pool is not None:
        _refill_cash_pool(cash_pool, bucket_states, month_expense, fx_rates, config)

    # --- Phase 4: Execute buy triggers ---
    for b in bucket_states:
        for trigger in b.triggers:
            if trigger.trigger_type != TriggerType.BUY:
                continue
            if trigger.period_months > 1 and month_idx % trigger.period_months != 0:
                continue
            _execute_buy_trigger(trigger, b, bucket_states, month_expense, fx_rates, config)

    return total_covered
