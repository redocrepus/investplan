"""Zero and edge-case tests for all engine modules.

Covers scenarios where financial parameters are zero or at extreme boundaries.
Each test is deterministic (uses rng seeds) and independent.
"""

import numpy as np
import pytest
from engine.bucket import simulate_bucket_prices, compute_sell, compute_buy
from engine.rebalancer import (
    BucketState, CashPoolState, PurchaseLot, execute_rebalance,
    _compute_cost_basis, _add_purchase_lot, _portfolio_total_expenses_currency,
    _available_to_sell, get_fx_rate,
)
from engine.inflation import simulate_monthly_inflation
from engine.currency import simulate_fx_rates
from engine.expenses import compute_monthly_expenses
from engine.simulator import run_simulation
from engine.montecarlo import run_monte_carlo
from models.config import SimConfig, CashPool
from models.bucket import (
    InvestmentBucket, BucketTrigger, TriggerType, SellSubtype, BuySubtype,
    CostBasisMethod,
)
from models.currency import CurrencySettings
from models.expense import ExpensePeriod, OneTimeExpense
from models.inflation import InflationSettings
from utils.volatility import (
    VolatilityProfile, ExpenseVolatility, InflationVolatility,
)


# ---------------------------------------------------------------------------
# Helper: create a BucketState with initial purchase lot
# ---------------------------------------------------------------------------

def _make_state(name="SP500", currency="USD", price=100, amount=10000,
                initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
                spending_priority=0, cash_floor_months=0,
                required_runaway_months=0, triggers=None,
                cost_basis_method=CostBasisMethod.FIFO) -> BucketState:
    state = BucketState(
        name=name, currency=currency,
        price=price, amount=amount,
        initial_price=initial_price, target_growth_pct=target_growth_pct,
        buy_sell_fee_pct=buy_sell_fee_pct,
        spending_priority=spending_priority,
        cash_floor_months=cash_floor_months,
        required_runaway_months=required_runaway_months,
        triggers=triggers or [],
        cost_basis_method=cost_basis_method,
    )
    if amount > 0 and initial_price > 0:
        _add_purchase_lot(state, amount, initial_price)
    return state


def _zero_inflation_config(**overrides):
    """Base config with zero inflation, zero tax, and zero fees."""
    defaults = dict(
        period_years=1,
        expenses_currency="USD",
        capital_gain_tax_pct=0,
        inflation=InflationSettings(
            min_pct=0, max_pct=0, avg_pct=0,
            volatility=InflationVolatility.CONSTANT,
        ),
    )
    defaults.update(overrides)
    return SimConfig(**defaults)


# ============================================================================
# 1. ZERO FEES — buy_sell_fee_pct=0, conversion_fee_pct=0
# ============================================================================

class TestZeroFees:
    """Verify that zero fees result in no fee deductions anywhere."""

    def test_sell_trigger_zero_fee_no_deduction(self):
        """Take profit sell with fee=0 should transfer full amount to target."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=100,
            target_bucket="Cash",
        )
        # Price doubled: 100 -> 200, target_growth=10%, so target_price=110
        # excess = (200-110)/200 = 45%, sell_amount = 10000 * 0.45 = 4500
        sp500 = _make_state("SP500", price=200, amount=10000,
                            initial_price=100, target_growth_pct=10,
                            buy_sell_fee_pct=0, triggers=[trigger])
        cash = _make_state("Cash", price=1, amount=50000,
                           initial_price=1, target_growth_pct=0,
                           buy_sell_fee_pct=0)

        config = _zero_inflation_config(buckets=[
            InvestmentBucket(name="SP500", initial_price=100, initial_amount=10000,
                             growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                             buy_sell_fee_pct=0),
            InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                             buy_sell_fee_pct=0),
        ])

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        assert sp500.fees_paid == 0, "Zero fee should produce zero fees_paid on seller"
        assert cash.fees_paid == 0, "Zero fee should produce zero fees_paid on buyer"
        # Sold 4500, zero tax, zero fee => cash gets exactly 4500
        assert abs(sp500.amount_sold - 4500) < 1.0
        assert abs(cash.amount_bought - 4500) < 1.0

    def test_expense_coverage_zero_fee_full_net_proceeds(self):
        """Expense coverage with zero fees: net_spent should equal expenses exactly."""
        bucket = _make_state("Cash", price=1, amount=50000,
                             initial_price=1, buy_sell_fee_pct=0)

        config = _zero_inflation_config(buckets=[
            InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                             buy_sell_fee_pct=0),
        ])

        total_covered = execute_rebalance([bucket], 1000, {}, config, 0)

        assert total_covered == 1000
        assert bucket.fees_paid == 0
        assert bucket.tax_paid == 0
        assert abs(bucket.net_spent - 1000) < 0.01

    def test_cross_currency_zero_conversion_fee(self):
        """Cross-currency sell with conversion_fee_pct=0 should have no FX fee."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=100,
            target_bucket="Cash",
        )
        eur_bucket = _make_state("EuroFund", currency="EUR", price=200, amount=10000,
                                 initial_price=100, target_growth_pct=10,
                                 buy_sell_fee_pct=0, triggers=[trigger])
        cash = _make_state("Cash", currency="USD", price=1, amount=50000,
                           buy_sell_fee_pct=0)

        config = _zero_inflation_config(
            buckets=[
                InvestmentBucket(name="EuroFund", currency="EUR", initial_price=100,
                                 initial_amount=10000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10, buy_sell_fee_pct=0),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                                 buy_sell_fee_pct=0),
            ],
            currencies=[
                CurrencySettings(
                    code="EUR", initial_price=1.1,
                    min_price=0.9, max_price=1.3, avg_price=1.1,
                    conversion_fee_pct=0.0,
                ),
            ],
        )

        fx_rates = {"EUR": 1.1}
        execute_rebalance([eur_bucket, cash], 0, fx_rates, config, 0)

        # Total fees should be zero (no sell fee, no buy fee, no conversion fee)
        total_fees = eur_bucket.fees_paid + cash.fees_paid
        assert total_fees == 0, f"Expected 0 total fees with zero fees everywhere, got {total_fees}"


# ============================================================================
# 2. ZERO TAX — capital_gain_tax_pct=0
# ============================================================================

class TestZeroTax:
    """Verify zero capital gains tax means no tax deduction on sells with gains."""

    def test_sell_with_gains_zero_tax_no_deduction(self):
        """Sell at a gain with 0% capital gains tax: tax_paid should be 0."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=100,
            target_bucket="Cash",
        )
        # Price doubled: 100% gain, but tax=0%
        sp500 = _make_state("SP500", price=200, amount=10000,
                            initial_price=100, target_growth_pct=10,
                            buy_sell_fee_pct=0, triggers=[trigger])
        cash = _make_state("Cash", price=1, amount=50000,
                           buy_sell_fee_pct=0)

        config = _zero_inflation_config(
            capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                                 buy_sell_fee_pct=0),
            ],
        )

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        assert sp500.tax_paid == 0
        assert sp500.amount_sold > 0, "Trigger should still fire"
        # With zero fee and zero tax, cash receives full sell amount
        assert abs(cash.amount_bought - sp500.amount_sold) < 0.01

    def test_expense_coverage_with_gains_zero_tax(self):
        """Expense coverage from a profitable bucket with 0% tax: no tax deducted."""
        # Price doubled, selling at a gain
        bucket = _make_state("SP500", price=200, amount=50000,
                             initial_price=100, buy_sell_fee_pct=0)

        config = _zero_inflation_config(
            capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=50000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
            ],
        )

        execute_rebalance([bucket], 5000, {}, config, 0)

        assert bucket.tax_paid == 0
        assert bucket.amount_sold > 0


# ============================================================================
# 3. ZERO GROWTH — growth_min/max/avg all 0
# ============================================================================

class TestZeroGrowth:
    """Verify zero growth means prices stay constant."""

    def test_zero_growth_constant_volatility_prices_unchanged(self):
        """With 0% growth and constant volatility, price should remain at initial."""
        bucket = InvestmentBucket(
            name="ZeroGrowth", initial_price=100, initial_amount=10000,
            growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
            volatility=VolatilityProfile.CONSTANT,
        )
        rng = np.random.default_rng(42)
        prices = simulate_bucket_prices(bucket, 120, rng)

        # With constant 0% growth, all prices should be exactly 100
        np.testing.assert_allclose(prices, 100.0, atol=0.001)

    def test_zero_growth_lognormal_volatility_stays_bounded(self):
        """With 0% growth and non-constant volatility (SP500), prices stay at 100.

        The min/max are both 0, so log_return is clamped to 0 each month.
        """
        bucket = InvestmentBucket(
            name="ZeroGrowth", initial_price=100, initial_amount=10000,
            growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
            volatility=VolatilityProfile.SP500,
        )
        rng = np.random.default_rng(42)
        prices = simulate_bucket_prices(bucket, 120, rng)

        # min/max both 0 means log-return clamped to 0 => price stays at 100
        np.testing.assert_allclose(prices, 100.0, atol=0.001)

    def test_zero_growth_simulator_amount_unchanged(self):
        """Full simulation: zero growth bucket should keep same amount (no expenses)."""
        config = _zero_inflation_config(
            buckets=[
                InvestmentBucket(
                    name="ZG", initial_price=100, initial_amount=10000,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                    volatility=VolatilityProfile.CONSTANT,
                    buy_sell_fee_pct=0, target_growth_pct=0,
                ),
            ],
        )
        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)

        # No expenses, no growth => amount stays at 10000 every month
        np.testing.assert_allclose(df["ZG_amount"].values, 10000.0, atol=0.01)


# ============================================================================
# 4. ZERO AMOUNT — initial_amount=0 for buckets
# ============================================================================

class TestZeroAmount:
    """Verify buckets with initial_amount=0 do not break the simulation."""

    def test_zero_amount_bucket_no_selling(self):
        """Bucket with amount=0 should not sell anything for expenses."""
        empty_bucket = _make_state("Empty", price=100, amount=0, initial_price=100)
        funded_bucket = _make_state("Funded", price=100, amount=50000, initial_price=100)

        config = _zero_inflation_config(buckets=[
            InvestmentBucket(name="Empty", initial_price=100, initial_amount=0,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            InvestmentBucket(name="Funded", initial_price=100, initial_amount=50000,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
        ])

        execute_rebalance([empty_bucket, funded_bucket], 1000, {}, config, 0)

        assert empty_bucket.amount_sold == 0
        assert funded_bucket.amount_sold > 0

    def test_zero_amount_bucket_full_simulation(self):
        """Full simulation with one zero-amount bucket should not crash."""
        config = _zero_inflation_config(
            expense_periods=[
                ExpensePeriod(start_month=1, start_year=1,
                              amount_min=100, amount_max=100, amount_avg=100,
                              volatility=ExpenseVolatility.CONSTANT),
            ],
            buckets=[
                InvestmentBucket(
                    name="Empty", initial_price=100, initial_amount=0,
                    growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                    volatility=VolatilityProfile.CONSTANT,
                    buy_sell_fee_pct=0,
                ),
                InvestmentBucket(
                    name="Funded", initial_price=1, initial_amount=50000,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                    volatility=VolatilityProfile.CONSTANT,
                    buy_sell_fee_pct=0,
                ),
            ],
        )
        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)

        assert len(df) == 12
        # Empty bucket should stay at 0 (no income, no buying)
        np.testing.assert_allclose(df["Empty_amount"].values, 0.0, atol=0.01)

    def test_zero_amount_buy_trigger_target(self):
        """A buy trigger should be able to buy into a zero-amount bucket."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=20.0,
            source_buckets=["Source"],
        )
        buyer = _make_state("Buyer", price=100, amount=0, initial_price=100,
                            triggers=[trigger])
        source = _make_state("Source", price=100, amount=100000, initial_price=100)

        config = _zero_inflation_config(buckets=[
            InvestmentBucket(name="Buyer", initial_price=100, initial_amount=0,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            InvestmentBucket(name="Source", initial_price=100, initial_amount=100000,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
        ])

        execute_rebalance([buyer, source], 0, {}, config, 0)

        # Buyer at 0% < 20% threshold, trigger should fire
        assert buyer.amount_bought > 0, "Should buy into zero-amount bucket"
        assert source.amount_sold > 0


# ============================================================================
# 5. ZERO PRICE — edge case where price=0 (cost basis safety)
# ============================================================================

class TestZeroPrice:
    """Verify _compute_cost_basis safety fallback when price=0."""

    def test_cost_basis_zero_price_returns_sell_amount(self):
        """When bucket price=0, cost basis should equal sell amount (safety fallback)."""
        state = BucketState(
            name="Test", currency="USD", price=0, amount=0,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            cost_basis_method=CostBasisMethod.FIFO,
        )
        state.purchase_lots = [PurchaseLot(price=100, units=50)]

        cost = _compute_cost_basis(state, 1000)
        # Safety fallback: when price <= 0, return sell_currency_amount
        assert cost == 1000

    def test_cost_basis_zero_price_avco(self):
        """AVCO with price=0 should also use safety fallback."""
        state = BucketState(
            name="Test", currency="USD", price=0, amount=0,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            cost_basis_method=CostBasisMethod.AVCO,
        )
        state.avg_cost = 100

        cost = _compute_cost_basis(state, 500)
        assert cost == 500


# ============================================================================
# 6. ZERO EXPENSES — no expense periods or expense=0
# ============================================================================

class TestZeroExpenses:
    """Verify zero expenses produce no selling."""

    def test_no_expense_periods_no_selling(self):
        """Rebalancer with month_expense=0 should not sell for expenses."""
        bucket = _make_state("SP500", price=100, amount=50000, initial_price=100)

        config = _zero_inflation_config(buckets=[
            InvestmentBucket(name="SP500", initial_price=100, initial_amount=50000,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
        ])

        total_covered = execute_rebalance([bucket], 0, {}, config, 0)

        assert total_covered == 0
        assert bucket.amount_sold == 0
        assert bucket.net_spent == 0
        assert bucket.amount == 50000

    def test_zero_amount_expense_period(self):
        """Expense period with amount=0 should produce zero expenses."""
        periods = [
            ExpensePeriod(
                start_month=1, start_year=1,
                amount_min=0, amount_max=0, amount_avg=0,
                volatility=ExpenseVolatility.CONSTANT,
            ),
        ]
        inflation = np.zeros(12)
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses(periods, [], inflation, 12, rng)

        np.testing.assert_allclose(expenses, 0.0)

    def test_zero_expenses_cash_pool_no_refill(self):
        """With zero expenses, cash pool should not trigger refill (month_expense=0)."""
        bucket = _make_state("SP500", price=200, amount=50000,
                             initial_price=100, buy_sell_fee_pct=0)
        cash_pool = CashPoolState(
            amount=0, refill_trigger_months=6,
            refill_target_months=12, cash_floor_months=0,
        )

        config = _zero_inflation_config(
            cash_pool=CashPool(initial_amount=0, refill_trigger_months=6,
                               refill_target_months=12, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                                 buy_sell_fee_pct=0),
            ],
        )

        execute_rebalance([bucket], 0, {}, config, 0, cash_pool=cash_pool)

        # _refill_cash_pool returns early when month_expense <= 0
        assert bucket.amount_sold == 0
        assert cash_pool.amount == 0


# ============================================================================
# 7. ZERO INFLATION — all inflation params=0
# ============================================================================

class TestZeroInflation:
    """Verify zero inflation keeps cumulative factor at 1.0."""

    def test_zero_inflation_constant_rates(self):
        """Constant zero inflation should produce all-zero monthly rates."""
        settings = InflationSettings(
            min_pct=0, max_pct=0, avg_pct=0,
            volatility=InflationVolatility.CONSTANT,
        )
        rng = np.random.default_rng(42)
        rates = simulate_monthly_inflation(settings, 120, rng)

        np.testing.assert_allclose(rates, 0.0)

    def test_zero_inflation_expenses_unchanged(self):
        """With zero inflation, expenses should stay at base amount every month."""
        periods = [
            ExpensePeriod(
                start_month=1, start_year=1,
                amount_min=1000, amount_max=1000, amount_avg=1000,
                volatility=ExpenseVolatility.CONSTANT,
            ),
        ]
        inflation = np.zeros(24)
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses(periods, [], inflation, 24, rng)

        # Cumulative inflation at each month = product of (1+0) = 1.0
        np.testing.assert_allclose(expenses, 1000.0)

    def test_zero_inflation_one_time_expense_unchanged(self):
        """With zero inflation, one-time expense amount should be exact."""
        one_time = [OneTimeExpense(month=6, year=1, amount=5000)]
        inflation = np.zeros(12)
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses([], one_time, inflation, 12, rng)

        # Month index 5 (month=6, year=1)
        assert expenses[5] == 5000.0


# ============================================================================
# 8. ZERO CASH POOL — cash pool with initial_amount=0 and all params=0
# ============================================================================

class TestZeroCashPool:
    """Verify fully-zero cash pool configuration."""

    def test_zero_cash_pool_all_params_expenses_from_buckets(self):
        """Cash pool with all params=0 should not interfere; expenses from buckets."""
        bucket = _make_state("Cash", price=1, amount=50000, initial_price=1)
        cash_pool = CashPoolState(
            amount=0, refill_trigger_months=0,
            refill_target_months=0, cash_floor_months=0,
        )

        config = _zero_inflation_config(
            cash_pool=CashPool(initial_amount=0, refill_trigger_months=0,
                               refill_target_months=0, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        total_covered = execute_rebalance(
            [bucket], 1000, {}, config, 0, cash_pool=cash_pool,
        )

        # Cash pool at 0 with 0 floor => draws 0, falls through to bucket
        assert cash_pool.net_spent == 0
        assert bucket.amount_sold > 0
        assert total_covered == 1000

    def test_zero_cash_pool_not_activated_in_simulator(self):
        """When cash pool initial=0 and refill_target=0, use_cash_pool should be False."""
        config = _zero_inflation_config(
            cash_pool=CashPool(initial_amount=0, refill_trigger_months=0,
                               refill_target_months=0, cash_floor_months=0),
            expense_periods=[
                ExpensePeriod(start_month=1, start_year=1,
                              amount_min=100, amount_max=100, amount_avg=100,
                              volatility=ExpenseVolatility.CONSTANT),
            ],
            buckets=[
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                                 volatility=VolatilityProfile.CONSTANT,
                                 buy_sell_fee_pct=0),
            ],
        )
        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)

        # use_cash_pool = initial_amount > 0 or refill_target_months > 0 => False
        # cash_pool_net_spent should be 0 (no cash pool drawing)
        # But total_net_spent should equal expenses (from bucket selling)
        diff = np.abs(df["expenses"].values - df["total_net_spent"].values)
        assert np.all(diff < 1.0)


# ============================================================================
# 9. ZERO CASH FLOOR — cash_floor_months=0
# ============================================================================

class TestZeroCashFloor:
    """Verify cash_floor_months=0 allows selling entire bucket."""

    def test_bucket_zero_cash_floor_allows_full_sell(self):
        """With cash_floor=0, entire bucket should be sellable for expenses."""
        bucket = _make_state("Cash", price=1, amount=1000, initial_price=1,
                             cash_floor_months=0)

        config = _zero_inflation_config(buckets=[
            InvestmentBucket(name="Cash", initial_price=1, initial_amount=1000,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                             cash_floor_months=0),
        ])

        total_covered = execute_rebalance([bucket], 1000, {}, config, 0)

        assert total_covered == 1000
        assert abs(bucket.amount) < 0.01, "Bucket should be fully depleted"

    def test_cash_pool_zero_floor_allows_full_draw(self):
        """Cash pool with floor=0 should allow drawing entire balance."""
        bucket = _make_state("SP500", price=100, amount=50000)
        cash_pool = CashPoolState(
            amount=1000, refill_trigger_months=0,
            refill_target_months=0, cash_floor_months=0,
        )

        config = _zero_inflation_config(
            cash_pool=CashPool(initial_amount=1000, refill_trigger_months=0,
                               refill_target_months=0, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([bucket], 1000, {}, config, 0, cash_pool=cash_pool)

        # Floor=0, drawable=1000-0=1000, expenses=1000 => fully drawn
        assert cash_pool.net_spent == 1000
        assert abs(cash_pool.amount) < 0.01
        assert bucket.amount_sold == 0, "Bucket should not be sold"

    def test_available_to_sell_zero_cash_floor_returns_full_value(self):
        """_available_to_sell with cash_floor=0 should return full bucket value."""
        bucket = _make_state("SP500", price=100, amount=10000, cash_floor_months=0)
        fx_rate = 1.0
        available = _available_to_sell(
            bucket, 1000, fx_rate, [bucket], {}, "USD",
        )
        assert abs(available - 10000) < 0.01


# ============================================================================
# 10. ZERO THRESHOLD — trigger threshold_pct=0
# ============================================================================

class TestZeroThreshold:
    """Verify triggers with threshold_pct=0."""

    def test_share_exceeds_zero_threshold_always_fires(self):
        """share_exceeds with threshold=0 should fire whenever bucket has any amount.

        Any non-zero share > 0% should trigger a sell.
        """
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.SHARE_EXCEEDS.value,
            threshold_pct=0.0,
            target_bucket="Cash",
        )
        sp500 = _make_state("SP500", price=100, amount=10000, triggers=[trigger])
        cash = _make_state("Cash", price=1, amount=90000)

        config = _zero_inflation_config(buckets=[
            InvestmentBucket(name="SP500", initial_price=100, initial_amount=10000,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            InvestmentBucket(name="Cash", initial_price=1, initial_amount=90000,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
        ])

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        # SP500 share = 10% > 0%, should sell to bring down to 0%
        assert sp500.amount_sold > 0

    def test_share_below_zero_threshold_never_fires(self):
        """share_below with threshold=0 should never fire (no share < 0%)."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=0.0,
            source_buckets=["Source"],
        )
        buyer = _make_state("Buyer", price=100, amount=0, initial_price=100,
                            triggers=[trigger])
        source = _make_state("Source", price=100, amount=100000)

        config = _zero_inflation_config(buckets=[
            InvestmentBucket(name="Buyer", initial_price=100, initial_amount=0,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            InvestmentBucket(name="Source", initial_price=100, initial_amount=100000,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
        ])

        execute_rebalance([buyer, source], 0, {}, config, 0)

        # Buyer share = 0% which is >= 0% threshold, so trigger should NOT fire
        assert buyer.amount_bought == 0

    def test_discount_zero_threshold_fires_at_any_discount(self):
        """discount with threshold=0 should fire when there is any discount > 0%."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.DISCOUNT.value,
            threshold_pct=0.0,
            source_buckets=["Source"],
        )
        # target_price = 100 * 1.1 = 110, current_price = 109
        # discount = 100 * 110/109 - 100 = 0.917% > 0%
        buyer = _make_state("Buyer", price=109, amount=10000,
                            initial_price=100, target_growth_pct=10,
                            triggers=[trigger])
        source = _make_state("Source", price=100, amount=50000)

        config = _zero_inflation_config(buckets=[
            InvestmentBucket(name="Buyer", initial_price=100, initial_amount=10000,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            InvestmentBucket(name="Source", initial_price=100, initial_amount=50000,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
        ])

        execute_rebalance([buyer, source], 0, {}, config, 0)

        assert buyer.amount_bought > 0, "Discount trigger with 0% threshold should fire"


# ============================================================================
# 11. ZERO PERIOD — period_years=0 or very short
# ============================================================================

class TestZeroPeriod:
    """Verify edge cases with very short simulation periods."""

    def test_zero_months_bucket_prices(self):
        """simulate_bucket_prices with n_months=0 should return empty array."""
        bucket = InvestmentBucket(
            name="Test", initial_price=100, initial_amount=10000,
            growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
            volatility=VolatilityProfile.CONSTANT,
        )
        rng = np.random.default_rng(42)
        prices = simulate_bucket_prices(bucket, 0, rng)

        assert len(prices) == 0

    def test_zero_months_inflation(self):
        """simulate_monthly_inflation with n_months=0 should return empty array."""
        settings = InflationSettings(min_pct=0, max_pct=5, avg_pct=2.5)
        rng = np.random.default_rng(42)
        rates = simulate_monthly_inflation(settings, 0, rng)

        assert len(rates) == 0

    def test_zero_months_fx_rates(self):
        """simulate_fx_rates with n_months=0 should return empty array."""
        settings = CurrencySettings(
            code="EUR", initial_price=1.1,
            min_price=0.8, max_price=1.5, avg_price=1.1,
        )
        rng = np.random.default_rng(42)
        prices = simulate_fx_rates(settings, 0, rng)

        assert len(prices) == 0

    def test_zero_months_expenses(self):
        """compute_monthly_expenses with n_months=0 should return empty array."""
        periods = [
            ExpensePeriod(start_month=1, start_year=1,
                          amount_min=1000, amount_max=1000, amount_avg=1000,
                          volatility=ExpenseVolatility.CONSTANT),
        ]
        inflation = np.zeros(0)
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses(periods, [], inflation, 0, rng)

        assert len(expenses) == 0


# ============================================================================
# 12. SINGLE MONTH — period_years where only 1 month runs
# ============================================================================

class TestSingleMonth:
    """Verify simulation works correctly with a minimal single-month run."""

    def test_single_month_simulation(self):
        """A 1-month simulation should produce one row in the output."""
        config = SimConfig(
            period_years=1,  # Will be modified to run 1 month manually
            expenses_currency="USD",
            capital_gain_tax_pct=0,
            inflation=InflationSettings(
                min_pct=0, max_pct=0, avg_pct=0,
                volatility=InflationVolatility.CONSTANT,
            ),
            expense_periods=[
                ExpensePeriod(start_month=1, start_year=1,
                              amount_min=500, amount_max=500, amount_avg=500,
                              volatility=ExpenseVolatility.CONSTANT),
            ],
            buckets=[
                InvestmentBucket(
                    name="Cash", initial_price=1, initial_amount=50000,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                    volatility=VolatilityProfile.CONSTANT,
                    buy_sell_fee_pct=0,
                ),
            ],
        )
        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)

        # 1 year = 12 months but check first month is correct
        assert df["year"].iloc[0] == 1
        assert df["month"].iloc[0] == 1
        assert abs(df["expenses"].iloc[0] - 500) < 1
        assert abs(df["total_net_spent"].iloc[0] - 500) < 1

    def test_single_month_expense_coverage(self):
        """In month 0 of rebalancer, expenses should be fully covered."""
        bucket = _make_state("Cash", price=1, amount=50000, initial_price=1)

        config = _zero_inflation_config(buckets=[
            InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
        ])

        total_covered = execute_rebalance([bucket], 500, {}, config, 0)

        assert total_covered == 500
        assert abs(bucket.net_spent - 500) < 0.01

    def test_single_month_monte_carlo(self):
        """Monte Carlo with 1-year period should work."""
        config = _zero_inflation_config(
            period_years=1,
            expense_periods=[
                ExpensePeriod(start_month=1, start_year=1,
                              amount_min=100, amount_max=100, amount_avg=100,
                              volatility=ExpenseVolatility.CONSTANT),
            ],
            buckets=[
                InvestmentBucket(
                    name="Cash", initial_price=1, initial_amount=50000,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                    volatility=VolatilityProfile.CONSTANT,
                    buy_sell_fee_pct=0,
                ),
            ],
        )

        result = run_monte_carlo(config, n_simulations=3, seed=42)

        assert result.n_simulations == 3
        assert result.success_rate == 1.0
        assert len(result.percentile_50) == 12


# ============================================================================
# 13. ZERO PORTFOLIO TOTAL — all buckets empty
# ============================================================================

class TestZeroPortfolioTotal:
    """Verify behavior when all buckets are empty (zero total portfolio value)."""

    def test_portfolio_total_zero_all_empty(self):
        """_portfolio_total_expenses_currency should return 0 when all empty."""
        b1 = _make_state("A", price=100, amount=0)
        b2 = _make_state("B", price=100, amount=0)

        total = _portfolio_total_expenses_currency([b1, b2], {}, "USD")
        assert total == 0.0

    def test_share_exceeds_trigger_skipped_zero_portfolio(self):
        """share_exceeds trigger should not fire when portfolio total is 0."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.SHARE_EXCEEDS.value,
            threshold_pct=50.0,
            target_bucket="B",
        )
        a = _make_state("A", price=100, amount=0, triggers=[trigger])
        b = _make_state("B", price=100, amount=0)

        config = _zero_inflation_config(buckets=[
            InvestmentBucket(name="A", initial_price=100, initial_amount=0,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            InvestmentBucket(name="B", initial_price=100, initial_amount=0,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
        ])

        # Should not crash; no division by zero
        execute_rebalance([a, b], 0, {}, config, 0)

        assert a.amount_sold == 0
        assert b.amount_bought == 0

    def test_share_below_trigger_skipped_zero_portfolio(self):
        """share_below trigger should not fire when portfolio total is 0."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=30.0,
            source_buckets=["B"],
        )
        a = _make_state("A", price=100, amount=0, triggers=[trigger])
        b = _make_state("B", price=100, amount=0)

        config = _zero_inflation_config(buckets=[
            InvestmentBucket(name="A", initial_price=100, initial_amount=0,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            InvestmentBucket(name="B", initial_price=100, initial_amount=0,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
        ])

        execute_rebalance([a, b], 0, {}, config, 0)

        assert a.amount_bought == 0

    def test_expense_coverage_empty_portfolio_shortfall(self):
        """When all buckets are empty, expenses cannot be covered."""
        a = _make_state("A", price=100, amount=0)
        b = _make_state("B", price=100, amount=0)

        config = _zero_inflation_config(buckets=[
            InvestmentBucket(name="A", initial_price=100, initial_amount=0,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            InvestmentBucket(name="B", initial_price=100, initial_amount=0,
                             growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
        ])

        total_covered = execute_rebalance([a, b], 1000, {}, config, 0)

        assert total_covered == 0
        assert a.amount_sold == 0
        assert b.amount_sold == 0

    def test_cash_pool_refill_empty_portfolio(self):
        """Cash pool refill with all-empty buckets should not crash."""
        a = _make_state("A", price=100, amount=0)
        cash_pool = CashPoolState(
            amount=0, refill_trigger_months=6,
            refill_target_months=12, cash_floor_months=0,
        )

        config = _zero_inflation_config(
            cash_pool=CashPool(initial_amount=0, refill_trigger_months=6,
                               refill_target_months=12, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="A", initial_price=100, initial_amount=0,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([a], 1000, {}, config, 0, cash_pool=cash_pool)

        assert cash_pool.amount == 0
        assert a.amount_sold == 0

    def test_full_simulation_all_empty_buckets_with_expenses(self):
        """Full simulation with empty buckets and expenses should not crash."""
        config = _zero_inflation_config(
            period_years=1,
            expense_periods=[
                ExpensePeriod(start_month=1, start_year=1,
                              amount_min=100, amount_max=100, amount_avg=100,
                              volatility=ExpenseVolatility.CONSTANT),
            ],
            buckets=[
                InvestmentBucket(
                    name="Empty", initial_price=100, initial_amount=0,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                    volatility=VolatilityProfile.CONSTANT,
                    buy_sell_fee_pct=0,
                ),
            ],
        )
        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)

        assert len(df) == 12
        # Expenses cannot be covered; total_net_spent should be 0
        np.testing.assert_allclose(df["total_net_spent"].values, 0.0, atol=0.01)
        # Expenses should still be 100
        np.testing.assert_allclose(df["expenses"].values, 100.0, atol=0.01)


# ============================================================================
# Additional edge case: add_purchase_lot with zero/negative amounts
# ============================================================================

class TestAddPurchaseLotEdgeCases:
    """Verify _add_purchase_lot handles edge cases."""

    def test_zero_amount_lot_not_added(self):
        """Lot with currency_amount=0 should not be added."""
        state = BucketState(
            name="Test", currency="USD", price=100, amount=0,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
        )
        _add_purchase_lot(state, 0, 100)
        assert len(state.purchase_lots) == 0

    def test_zero_price_lot_not_added(self):
        """Lot with price=0 should not be added."""
        state = BucketState(
            name="Test", currency="USD", price=100, amount=0,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
        )
        _add_purchase_lot(state, 1000, 0)
        assert len(state.purchase_lots) == 0

    def test_negative_amount_lot_not_added(self):
        """Lot with negative currency_amount should not be added."""
        state = BucketState(
            name="Test", currency="USD", price=100, amount=0,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
        )
        _add_purchase_lot(state, -500, 100)
        assert len(state.purchase_lots) == 0


# ============================================================================
# Additional: compute_sell / compute_buy with zero amount
# ============================================================================

class TestComputeSellBuyZeroAmount:
    """Verify sell/buy computations with zero amounts."""

    def test_sell_zero_amount(self):
        """Selling 0 should produce 0 net and 0 fee."""
        net, fee = compute_sell(0, 1.0)
        assert net == 0
        assert fee == 0

    def test_buy_zero_amount(self):
        """Buying with 0 should produce 0 invested and 0 fee."""
        invested, fee = compute_buy(0, 1.0)
        assert invested == 0
        assert fee == 0


# ============================================================================
# Additional: FX rate helpers edge case
# ============================================================================

class TestFxRateEdgeCases:
    """Verify get_fx_rate edge cases."""

    def test_same_currency_returns_one(self):
        """When bucket currency equals expenses currency, rate should be 1.0."""
        rate = get_fx_rate("USD", "USD", {"EUR": 1.1})
        assert rate == 1.0

    def test_missing_currency_returns_one(self):
        """When currency not in fx_rates dict, should default to 1.0."""
        rate = get_fx_rate("GBP", "USD", {"EUR": 1.1})
        assert rate == 1.0
