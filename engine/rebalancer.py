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
    """A single purchase lot for FIFO/LIFO cost basis tracking.

    Cost basis is tracked in expenses currency (per requirements).
    price_exp stores the price per unit in expenses currency at purchase time,
    capturing both the bucket-currency price and the FX rate at that moment.
    """
    price_exp: float  # price per unit in expenses currency at purchase time
    units: float      # number of units purchased (= currency_amount / bucket_price)


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


def _add_purchase_lot(state: BucketState, currency_amount: float, price: float,
                      fx_rate: float = 1.0):
    """Record a purchase lot and update AVCO.

    Cost basis is tracked in expenses currency. The lot stores
    price_exp = price * fx_rate (price per unit in expenses currency).

    For AVCO buckets, uses incremental formula instead of storing individual lots:
    new_avg = (old_units * old_avg + new_units * price_exp) / (old_units + new_units)

    Args:
        state: The bucket state to add the lot to.
        currency_amount: Amount spent in bucket currency.
        price: Price per unit at purchase time (bucket currency).
        fx_rate: FX rate from bucket currency to expenses currency at purchase time.
    """
    if currency_amount <= 0 or price <= 0:
        return
    new_units = currency_amount / price
    price_exp = price * fx_rate

    if state.cost_basis_method == CostBasisMethod.AVCO:
        # Incremental AVCO: no individual lots needed
        old_units = sum(lot.units for lot in state.purchase_lots)
        if old_units > 0:
            state.avg_cost = (old_units * state.avg_cost + new_units * price_exp) / (old_units + new_units)
        else:
            state.avg_cost = price_exp
        # Store a single synthetic lot representing all units
        total_units = old_units + new_units
        state.purchase_lots = [PurchaseLot(price_exp=state.avg_cost, units=total_units)]
    else:
        # FIFO/LIFO: store individual lots
        state.purchase_lots.append(PurchaseLot(price_exp=price_exp, units=new_units))
        # Update avg_cost for reference (in expenses currency)
        total_units = sum(lot.units for lot in state.purchase_lots)
        if total_units > 0:
            total_cost = sum(lot.price_exp * lot.units for lot in state.purchase_lots)
            state.avg_cost = total_cost / total_units


def _compute_cost_basis(state: BucketState, sell_currency_amount: float,
                        current_fx_rate: float = 1.0) -> float:
    """Compute cost basis for a sell using the bucket's chosen method.

    Converts the sell amount (in bucket currency) to units using the current price,
    then computes cost basis from purchase lots.
    Returns total cost basis in expenses currency. Also consumes lots for FIFO/LIFO/AVCO.

    Args:
        state: Bucket state with purchase lots.
        sell_currency_amount: Amount being sold in bucket currency.
        current_fx_rate: Current FX rate (bucket→expenses), used as fallback
            when no lots exist (cost = current price * current FX).
    """
    if state.price <= 0:
        return sell_currency_amount * current_fx_rate  # safety fallback

    sell_units = sell_currency_amount / state.price

    if state.cost_basis_method == CostBasisMethod.AVCO:
        # Reduce the synthetic lot's units (avg_cost stays the same on sell)
        if state.purchase_lots:
            state.purchase_lots[0].units = max(0, state.purchase_lots[0].units - sell_units)
        return sell_units * state.avg_cost

    # FIFO or LIFO
    remaining_units = sell_units
    cost_basis = 0.0
    if state.cost_basis_method == CostBasisMethod.FIFO:
        lots = state.purchase_lots  # consume from front
        while remaining_units > 1e-10 and lots:
            lot = lots[0]
            take_units = min(remaining_units, lot.units)
            cost_basis += take_units * lot.price_exp
            lot.units -= take_units
            remaining_units -= take_units
            if lot.units <= 1e-10:
                lots.pop(0)
    else:  # LIFO
        lots = state.purchase_lots  # consume from back
        while remaining_units > 1e-10 and lots:
            lot = lots[-1]
            take_units = min(remaining_units, lot.units)
            cost_basis += take_units * lot.price_exp
            lot.units -= take_units
            remaining_units -= take_units
            if lot.units <= 1e-10:
                lots.pop()

    # If we ran out of lots, treat remaining as no-gain (cost = current price in expenses currency)
    if remaining_units > 1e-10:
        cost_basis += remaining_units * state.price * current_fx_rate

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
    cash_pool_amount: float = 0.0,
) -> float:
    """Compute total portfolio value in expenses currency (including cash pool)."""
    buckets_total = sum(
        _bucket_value_in_expenses_currency(b, get_fx_rate(b.currency, expenses_currency, fx_rates))
        for b in bucket_states
    )
    return buckets_total + cash_pool_amount


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
    cash_pool_amount: float = 0.0,
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
        portfolio_total = _portfolio_total_expenses_currency(bucket_states, fx_rates, expenses_currency, cash_pool_amount)
        share_floor = portfolio_total * share_floor_pct / 100.0
    effective_floor = max(cash_floor, share_floor)
    return max(0.0, bucket_value - effective_floor)


def _next_lot_cost_per_unit(b: BucketState) -> float:
    """Return cost per unit (in expenses currency) for the next lots to sell.

    FIFO: front lot price_exp, LIFO: back lot price_exp, AVCO: avg_cost.
    Falls back to initial_price if no lots exist (assumes FX=1 at init).
    """
    if b.cost_basis_method == CostBasisMethod.AVCO:
        return b.avg_cost if b.avg_cost > 0 else b.initial_price
    if not b.purchase_lots:
        return b.avg_cost if b.avg_cost > 0 else b.initial_price
    if b.cost_basis_method == CostBasisMethod.FIFO:
        return b.purchase_lots[0].price_exp
    # LIFO
    return b.purchase_lots[-1].price_exp


def _bucket_profitability(
    b: BucketState, fx_rate: float, fee_pct: float,
    conv_fee_pct: float, expenses_currency: str,
) -> float:
    """Compute profitability of selling from a bucket: gross gain after FX + fees.

    Uses the actual next-to-sell lot cost based on the bucket's cost basis method
    (FIFO front, LIFO back, AVCO average) for consistent profitability ordering.
    Cost per unit is in expenses currency; current price is converted to expenses
    currency via fx_rate for an apples-to-apples comparison.
    """
    value_exp = b.amount * fx_rate
    fee_cost = value_exp * fee_pct / 100.0
    conv_cost = 0.0
    if b.currency != expenses_currency:
        conv_cost = value_exp * conv_fee_pct / 100.0
    cost_per_unit_exp = _next_lot_cost_per_unit(b)  # in expenses currency
    current_price_exp = b.price * fx_rate  # current price in expenses currency
    if cost_per_unit_exp > 0:
        gain_ratio = (current_price_exp - cost_per_unit_exp) / cost_per_unit_exp
    else:
        gain_ratio = 0.0
    gross_gain = value_exp * gain_ratio - fee_cost - conv_cost
    return gross_gain


def _estimate_net_yield(
    b: BucketState,
    capital_gain_tax_pct: float,
    expenses_currency: str,
    config: SimConfig,
    fx_rate: float = 1.0,
) -> float | None:
    """Estimate fraction of gross sell value (in expenses currency) that becomes net proceeds.

    Used to gross up sell amounts so net proceeds cover the intended target.
    Returns None when yield <= 0 (extreme fee+tax scenarios make selling unviable).
    Callers should skip this source when None is returned.
    """
    fee_rate = b.buy_sell_fee_pct / 100.0
    cost_per_unit_exp = _next_lot_cost_per_unit(b)  # in expenses currency
    current_price_exp = b.price * fx_rate  # current price in expenses currency
    if current_price_exp > 0 and cost_per_unit_exp > 0:
        gain_fraction = max(0.0, (current_price_exp - cost_per_unit_exp) / current_price_exp)
    else:
        gain_fraction = 0.0
    tax_on_sell = capital_gain_tax_pct / 100.0 * gain_fraction * (1 - fee_rate)
    conv_fee_rate = 0.0
    if b.currency != expenses_currency:
        conv_fee_rate = get_conversion_fee_pct(b.currency, expenses_currency, config) / 100.0
    net_yield = (1 - fee_rate - tax_on_sell) * (1 - conv_fee_rate)
    if net_yield <= 0:
        return None
    return net_yield


def _snapshot_portfolio_total(
    bucket_states: list[BucketState],
    snapshot_amounts: dict[str, float],
    fx_rates: dict[str, float],
    expenses_currency: str,
    cash_pool_amount: float = 0.0,
) -> float:
    """Compute portfolio total using snapshot amounts for condition evaluation."""
    total = sum(
        snapshot_amounts.get(b.name, b.amount) * get_fx_rate(b.currency, expenses_currency, fx_rates)
        for b in bucket_states
    )
    return total + cash_pool_amount


def _execute_sell_trigger(
    trigger: BucketTrigger,
    seller: BucketState,
    bucket_states: list[BucketState],
    month_expense: float,
    fx_rates: dict[str, float],
    config: SimConfig,
    cash_pool_amount: float = 0.0,
    snapshot_amounts: dict[str, float] | None = None,
) -> None:
    """Execute a single sell trigger if conditions are met.

    When snapshot_amounts is provided, conditions are evaluated against the
    snapshot (portfolio state at phase start) while mutations apply to live state.
    """
    expenses_currency = config.expenses_currency
    capital_gain_tax_pct = config.capital_gain_tax_pct
    name_to_state = {b.name: b for b in bucket_states}

    # Runaway guard (uses live state — this is a safety guard, not a trigger condition)
    runway = _cash_runway_months(bucket_states, month_expense, fx_rates, expenses_currency)
    if runway < seller.required_runaway_months:
        return

    sell_amount = 0.0

    if trigger.subtype == SellSubtype.TAKE_PROFIT.value:
        # Sell if actual_growth% / target_growth% * 100 >= threshold_pct
        # Use cost basis per unit based on bucket's cost basis method (per requirements).
        # Both values in expenses currency for correct cross-currency comparison.
        seller_fx = get_fx_rate(seller.currency, expenses_currency, fx_rates)
        cost_per_unit_exp = _next_lot_cost_per_unit(seller)  # expenses currency
        current_price_exp = seller.price * seller_fx  # expenses currency
        if seller.target_growth_pct == 0 or cost_per_unit_exp <= 0:
            return
        actual_growth = (current_price_exp - cost_per_unit_exp) / cost_per_unit_exp * 100.0
        ratio_pct = actual_growth / seller.target_growth_pct * 100.0
        if ratio_pct < trigger.threshold_pct:
            return
        # Sell the excess above target (in expenses currency, then convert to fraction)
        target_price_exp = cost_per_unit_exp * (1 + seller.target_growth_pct / 100.0)
        excess_per_unit_exp = current_price_exp - target_price_exp
        if excess_per_unit_exp <= 0:
            return
        fraction_excess = excess_per_unit_exp / current_price_exp
        sell_amount = seller.amount * fraction_excess

    elif trigger.subtype == SellSubtype.SHARE_EXCEEDS.value:
        # Evaluate condition on snapshot if available
        if snapshot_amounts is not None:
            snap_total = _snapshot_portfolio_total(bucket_states, snapshot_amounts, fx_rates, expenses_currency, cash_pool_amount)
            seller_fx = get_fx_rate(seller.currency, expenses_currency, fx_rates)
            snap_value = snapshot_amounts.get(seller.name, seller.amount) * seller_fx
            if snap_total <= 0:
                return
            share_pct = snap_value / snap_total * 100.0
            if share_pct <= trigger.threshold_pct:
                return
        # Compute sell amount from live state
        portfolio_total = _portfolio_total_expenses_currency(bucket_states, fx_rates, expenses_currency, cash_pool_amount)
        if portfolio_total <= 0:
            return
        seller_fx = get_fx_rate(seller.currency, expenses_currency, fx_rates)
        seller_value = seller.amount * seller_fx
        if snapshot_amounts is None:
            share_pct = seller_value / portfolio_total * 100.0
            if share_pct <= trigger.threshold_pct:
                return
        # Sell excess to bring share down to threshold.
        # Note: single-pass approximation — doesn't account for portfolio
        # shrinkage from the sell itself, causing systematic under-sell.
        # Acceptable for simulation accuracy.
        target_value = portfolio_total * trigger.threshold_pct / 100.0
        excess_value = seller_value - target_value
        if excess_value <= 0:
            return
        sell_amount = excess_value / seller_fx if seller_fx > 0 else 0

    if sell_amount <= 0:
        return

    seller_fx = get_fx_rate(seller.currency, expenses_currency, fx_rates)

    # Pre-limit sell_amount based on target's share ceiling so we don't sell
    # more than the target can receive.
    if trigger.target_bucket and trigger.target_bucket in name_to_state:
        target_state = name_to_state[trigger.target_bucket]
        target_ceiling_pct = _get_share_ceiling(target_state)
        if target_ceiling_pct is not None:
            target_fx = get_fx_rate(target_state.currency, expenses_currency, fx_rates)
            portfolio_total = _portfolio_total_expenses_currency(
                bucket_states, fx_rates, expenses_currency, cash_pool_amount,
            )
            target_value = target_state.amount * target_fx
            ceiling_value = portfolio_total * target_ceiling_pct / 100.0
            headroom = max(0.0, ceiling_value - target_value)
            if headroom <= 0:
                return
            # Estimate max sell_amount that produces headroom worth of net proceeds
            net_yield = _estimate_net_yield(seller, capital_gain_tax_pct, expenses_currency, config, seller_fx)
            if net_yield is None:
                return
            buy_yield = 1.0 - target_state.buy_sell_fee_pct / 100.0
            max_sell = headroom / (seller_fx * net_yield * max(buy_yield, 0.01))
            sell_amount = min(sell_amount, max_sell)
            if sell_amount <= 0:
                return

    # Execute the sell
    seller_fx = get_fx_rate(seller.currency, expenses_currency, fx_rates)
    net_proceeds, fee = compute_sell(sell_amount, seller.buy_sell_fee_pct)

    # Capital gains tax using cost basis (both in expenses currency).
    # Fees are deducted before gain (Israeli tax law: brokerage fees are allowable deduction).
    cost_basis_exp = _compute_cost_basis(seller, sell_amount, seller_fx)
    net_proceeds_exp = net_proceeds * seller_fx  # convert to expenses currency
    gain_exp = net_proceeds_exp - cost_basis_exp  # gain in expenses currency
    tax_exp = max(0, gain_exp * capital_gain_tax_pct / 100.0)
    # Convert tax back to bucket currency for deduction from proceeds
    tax_bucket = tax_exp / seller_fx if seller_fx > 0 else 0
    after_tax = net_proceeds - tax_bucket

    seller.amount -= sell_amount
    seller.amount_sold += sell_amount
    seller.fees_paid += fee * seller_fx
    seller.tax_paid += tax_exp

    # Buy into target bucket if configured
    if trigger.target_bucket and trigger.target_bucket in name_to_state:
        target = name_to_state[trigger.target_bucket]
        target_fx = get_fx_rate(target.currency, expenses_currency, fx_rates)

        if seller.currency == target.currency and seller.currency != expenses_currency:
            # Short-circuit: same foreign currency — only convert tax amount
            # to expenses currency, transfer the rest directly (no double FX fee).
            conv_fee_pct = get_conversion_fee_pct(seller.currency, expenses_currency, config)
            # Tax is already in expenses currency; pay FX fee on the conversion
            if conv_fee_pct > 0 and tax_exp > 0:
                fx_fee_on_tax = tax_exp * conv_fee_pct / 100.0
                seller.fees_paid += fx_fee_on_tax
            # Remaining proceeds stay in seller currency (= target currency)
            buy_amount_target = after_tax
            if buy_amount_target <= 0:
                return
            invested, buy_fee = compute_buy(buy_amount_target, target.buy_sell_fee_pct)
            target.amount += invested
            target.amount_bought += invested
            target.fees_paid += buy_fee * target_fx
            _add_purchase_lot(target, invested, target.price, target_fx)
        else:
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

            if proceeds_expenses <= 0:
                return

            buy_amount_target = proceeds_expenses / target_fx if target_fx > 0 else 0
            invested, buy_fee = compute_buy(buy_amount_target, target.buy_sell_fee_pct)
            target.amount += invested
            target.amount_bought += invested
            target.fees_paid += buy_fee * target_fx
            _add_purchase_lot(target, invested, target.price, target_fx)


def _execute_buy_trigger(
    trigger: BucketTrigger,
    buyer: BucketState,
    bucket_states: list[BucketState],
    month_expense: float,
    fx_rates: dict[str, float],
    config: SimConfig,
    cash_pool_amount: float = 0.0,
    snapshot_amounts: dict[str, float] | None = None,
) -> None:
    """Execute a single buy trigger if conditions are met.

    Sells from source_buckets in profitability order (profitable first, then
    user-defined priority order for losing sources). Each source is sold down
    to its floors (cash floor + implicit share% floor).

    When snapshot_amounts is provided, conditions are evaluated against the
    snapshot (portfolio state at phase start) while mutations apply to live state.
    """
    expenses_currency = config.expenses_currency
    capital_gain_tax_pct = config.capital_gain_tax_pct
    name_to_state = {b.name: b for b in bucket_states}

    should_buy = False
    buy_value_expenses = 0.0  # how much to buy in expenses currency (0 = unlimited/all available)
    unlimited_buy = False

    if trigger.subtype == BuySubtype.DISCOUNT.value:
        # Buy if 100 * target_price / current_price - 100 > threshold%
        # Both in expenses currency for correct cross-currency comparison.
        buyer_fx = get_fx_rate(buyer.currency, expenses_currency, fx_rates)
        cost_per_unit_exp = _next_lot_cost_per_unit(buyer)  # expenses currency
        target_price_exp = cost_per_unit_exp * (1 + buyer.target_growth_pct / 100.0)
        current_price_exp = buyer.price * buyer_fx
        if current_price_exp <= 0:
            return
        discount_pct = 100.0 * target_price_exp / current_price_exp - 100.0
        if discount_pct <= trigger.threshold_pct:
            return
        should_buy = True
        unlimited_buy = True  # sell all available from sources down to floors

    elif trigger.subtype == BuySubtype.SHARE_BELOW.value:
        buyer_fx = get_fx_rate(buyer.currency, expenses_currency, fx_rates)
        if snapshot_amounts is not None:
            # Evaluate condition and compute buy amount from snapshot
            snap_total = _snapshot_portfolio_total(bucket_states, snapshot_amounts, fx_rates, expenses_currency, cash_pool_amount)
            snap_value = snapshot_amounts.get(buyer.name, buyer.amount) * buyer_fx
            if snap_total <= 0:
                return
            snap_share = snap_value / snap_total * 100.0
            if snap_share >= trigger.threshold_pct:
                return
            should_buy = True
            target_value = snap_total * trigger.threshold_pct / 100.0
            buy_value_expenses = target_value - snap_value
        else:
            portfolio_total = _portfolio_total_expenses_currency(bucket_states, fx_rates, expenses_currency, cash_pool_amount)
            if portfolio_total <= 0:
                return
            buyer_value = buyer.amount * buyer_fx
            share_pct = buyer_value / portfolio_total * 100.0
            if share_pct >= trigger.threshold_pct:
                return
            should_buy = True
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
        portfolio_total = _portfolio_total_expenses_currency(bucket_states, fx_rates, expenses_currency, cash_pool_amount)
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
        avail = _available_to_sell(s, month_expense, s_fx, bucket_states, fx_rates, expenses_currency, cash_pool_amount)
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
            # Gross up to account for fee/tax/FX shrinkage
            net_yield = _estimate_net_yield(source, capital_gain_tax_pct, expenses_currency, config, source_fx)
            if net_yield is None:
                continue
            gross_needed = remaining_need / net_yield
            sell_expenses = min(gross_needed, available)

        sell_bucket_currency = sell_expenses / source_fx

        net_proceeds, sell_fee = compute_sell(sell_bucket_currency, source.buy_sell_fee_pct)

        # Capital gains tax on source sell (gain in expenses currency).
        # Fees deducted before gain (Israeli tax law: fees are allowable deduction).
        cost_basis_exp = _compute_cost_basis(source, sell_bucket_currency, source_fx)
        net_proceeds_exp = net_proceeds * source_fx
        gain_exp = net_proceeds_exp - cost_basis_exp  # net_proceeds is after sell fee
        tax_exp = max(0, gain_exp * capital_gain_tax_pct / 100.0)
        tax_bucket = tax_exp / source_fx if source_fx > 0 else 0
        after_tax = net_proceeds - tax_bucket

        source.amount -= sell_bucket_currency
        source.amount_sold += sell_bucket_currency
        source.fees_paid += sell_fee * source_fx
        source.tax_paid += tax_exp

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
    _add_purchase_lot(buyer, invested, buyer.price, buyer_fx)


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
            cash_pool.amount,
        )

        if available_expenses <= 0:
            continue

        # Gross up sell amount to account for fee/tax/FX shrinkage
        net_yield = _estimate_net_yield(b, capital_gain_tax_pct, expenses_currency, config, fx)
        if net_yield is None:
            continue
        gross_needed = needed / net_yield
        sell_expenses = min(gross_needed, available_expenses)
        sell_bucket_currency = sell_expenses / fx

        net_proceeds, fee = compute_sell(sell_bucket_currency, b.buy_sell_fee_pct)

        # Tax on gains using cost basis (gain in expenses currency).
        # Fees deducted before gain (Israeli tax law: fees are allowable deduction).
        cost_basis_exp = _compute_cost_basis(b, sell_bucket_currency, fx)
        net_proceeds_exp = net_proceeds * fx
        gain_exp = net_proceeds_exp - cost_basis_exp  # net_proceeds is after sell fee
        tax_exp = max(0, gain_exp * capital_gain_tax_pct / 100.0)
        tax_bucket = tax_exp / fx if fx > 0 else 0
        after_tax = net_proceeds - tax_bucket

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
        b.tax_paid += tax_exp

        cash_pool.amount += net_in_expenses
        needed -= net_in_expenses


def _cover_expenses_from_buckets(
    remaining_expense: float,
    bucket_states: list[BucketState],
    month_expense: float,
    fx_rates: dict[str, float],
    config: SimConfig,
    cash_pool_amount: float = 0.0,
) -> float:
    """Cover expenses by selling from buckets in spending priority order.

    Returns the remaining uncovered expense amount.
    """
    expenses_currency = config.expenses_currency
    capital_gain_tax_pct = config.capital_gain_tax_pct

    # Sort by profitability: profitable buckets first (descending),
    # then unprofitable in spending priority order (ascending).
    bucket_profit = []
    for b in bucket_states:
        fx = get_fx_rate(b.currency, expenses_currency, fx_rates)
        conv_fee_pct = get_conversion_fee_pct(b.currency, expenses_currency, config)
        profit = _bucket_profitability(b, fx, b.buy_sell_fee_pct, conv_fee_pct, expenses_currency)
        bucket_profit.append((b, profit))

    profitable = [(b, p) for b, p in bucket_profit if p > 0]
    unprofitable = [(b, p) for b, p in bucket_profit if p <= 0]
    profitable.sort(key=lambda x: x[1], reverse=True)
    unprofitable.sort(key=lambda x: x[0].spending_priority)
    spending_order = [b for b, _p in profitable + unprofitable]

    for b in spending_order:
        if remaining_expense <= 0:
            break

        fx = get_fx_rate(b.currency, expenses_currency, fx_rates)
        if fx <= 0:
            continue

        available_expenses = _available_to_sell(
            b, month_expense, fx, bucket_states, fx_rates, expenses_currency,
            cash_pool_amount,
        )

        if available_expenses <= 0:
            continue

        # Gross up sell amount to account for fee/tax/FX shrinkage
        net_yield = _estimate_net_yield(b, capital_gain_tax_pct, expenses_currency, config, fx)
        if net_yield is None:
            continue
        gross_needed = remaining_expense / net_yield
        sell_expenses = min(gross_needed, available_expenses)
        sell_bucket_currency = sell_expenses / fx

        net_proceeds, fee = compute_sell(sell_bucket_currency, b.buy_sell_fee_pct)

        # Fees deducted before gain (Israeli tax law: fees are allowable deduction).
        # Gain computed in expenses currency to capture FX gains.
        cost_basis_exp = _compute_cost_basis(b, sell_bucket_currency, fx)
        net_proceeds_exp = net_proceeds * fx
        gain_exp = net_proceeds_exp - cost_basis_exp  # net_proceeds is after sell fee
        tax_exp = max(0, gain_exp * capital_gain_tax_pct / 100.0)
        tax_bucket = tax_exp / fx if fx > 0 else 0
        after_tax = net_proceeds - tax_bucket

        conv_fee_pct = get_conversion_fee_pct(b.currency, expenses_currency, config)
        net_in_expenses = after_tax * fx
        if b.currency != expenses_currency:
            fx_fee = net_in_expenses * conv_fee_pct / 100.0
            net_in_expenses -= fx_fee
            b.fees_paid += fx_fee

        b.amount -= sell_bucket_currency
        b.amount_sold += sell_bucket_currency
        b.fees_paid += fee * fx
        b.tax_paid += tax_exp
        b.net_spent += min(net_in_expenses, remaining_expense)

        remaining_expense -= net_in_expenses

    # Fallback: if all buckets hit their cash floors, sell in reverse spending
    # priority order (lowest priority first), violating cash floors. This
    # preserves the most stable assets (highest priority) during distress.
    if remaining_expense > 0:
        reverse_order = sorted(bucket_states, key=lambda b: b.spending_priority, reverse=True)
        for b in reverse_order:
            if remaining_expense <= 0:
                break

            fx = get_fx_rate(b.currency, expenses_currency, fx_rates)
            if fx <= 0:
                continue

            bucket_value_expenses = b.amount * fx
            if bucket_value_expenses <= 0:
                continue

            # Gross up for shrinkage (fallback still applies fees/tax)
            net_yield = _estimate_net_yield(b, capital_gain_tax_pct, expenses_currency, config, fx)
            if net_yield is None:
                # Yield is non-positive; sell everything available as last resort
                sell_expenses = bucket_value_expenses
            else:
                gross_needed = remaining_expense / net_yield
                sell_expenses = min(gross_needed, bucket_value_expenses)
            sell_bucket_currency = sell_expenses / fx

            net_proceeds, fee = compute_sell(sell_bucket_currency, b.buy_sell_fee_pct)

            # Fees deducted before gain (Israeli tax law: fees are allowable deduction).
            # Gain computed in expenses currency to capture FX gains.
            cost_basis_exp = _compute_cost_basis(b, sell_bucket_currency, fx)
            net_proceeds_exp = net_proceeds * fx
            gain_exp = net_proceeds_exp - cost_basis_exp  # net_proceeds is after sell fee
            tax_exp = max(0, gain_exp * capital_gain_tax_pct / 100.0)
            tax_bucket = tax_exp / fx if fx > 0 else 0
            after_tax = net_proceeds - tax_bucket

            conv_fee_pct = get_conversion_fee_pct(b.currency, expenses_currency, config)
            net_in_expenses = after_tax * fx
            if b.currency != expenses_currency:
                fx_fee = net_in_expenses * conv_fee_pct / 100.0
                net_in_expenses -= fx_fee
                b.fees_paid += fx_fee

            b.amount -= sell_bucket_currency
            b.amount_sold += sell_bucket_currency
            b.fees_paid += fee * fx
            b.tax_paid += tax_exp
            b.net_spent += min(net_in_expenses, remaining_expense)

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
    # Triggers fire at month_idx 0 (first month), then every period_months.
    # E.g. period_months=12 fires at months 0, 12, 24, ...
    # Snapshot: conditions evaluated on phase-start state, mutations on live state.
    # Refresh cp_amount before each phase that uses it.
    cp_amount = cash_pool.amount if cash_pool is not None else 0.0
    sell_snapshot = {b.name: b.amount for b in bucket_states}
    for b in bucket_states:
        for trigger in b.triggers:
            if trigger.trigger_type != TriggerType.SELL:
                continue
            if trigger.period_months > 1 and month_idx % trigger.period_months != 0:
                continue
            _execute_sell_trigger(trigger, b, bucket_states, month_expense, fx_rates, config, cp_amount, sell_snapshot)

    # --- Phase 2: Cover expenses ---
    if cash_pool is not None:
        # If cash pool is below refill trigger, refill it first
        if cash_pool.amount < cash_pool.refill_trigger_months * month_expense:
            _refill_cash_pool(cash_pool, bucket_states, month_expense, fx_rates, config)

        # Draw expenses from cash pool (respect cash floor)
        cash_floor = cash_pool.cash_floor_months * month_expense
        drawable = max(0.0, cash_pool.amount - cash_floor)
        drawn = min(drawable, month_expense)
        cash_pool.amount -= drawn
        cash_pool.net_spent = drawn
        remaining_expense = month_expense - drawn

        # If cash pool still couldn't cover, fall through to direct bucket selling
        if remaining_expense > 0:
            remaining_expense = _cover_expenses_from_buckets(
                remaining_expense, bucket_states, month_expense, fx_rates, config,
                cash_pool.amount,
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
    # Snapshot: conditions evaluated on phase-start state, mutations on live state.
    buy_snapshot = {b.name: b.amount for b in bucket_states}
    for b in bucket_states:
        for trigger in b.triggers:
            if trigger.trigger_type != TriggerType.BUY:
                continue
            if trigger.period_months > 1 and month_idx % trigger.period_months != 0:
                continue
            cp_amount = cash_pool.amount if cash_pool is not None else 0.0
            _execute_buy_trigger(trigger, b, bucket_states, month_expense, fx_rates, config, cp_amount, buy_snapshot)

    return total_covered
