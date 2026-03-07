"""Tests for the simulator orchestrator."""

import pytest
import numpy as np
from models.config import SimConfig, CashPool
from models.bucket import InvestmentBucket
from models.expense import ExpensePeriod
from models.inflation import InflationSettings
from engine.simulator import run_simulation
from utils.volatility import VolatilityProfile, ExpenseVolatility, InflationVolatility


def _make_config() -> SimConfig:
    """Create a simple test config with one bucket and expenses."""
    return SimConfig(
        period_years=2,
        expenses_currency="USD",
        capital_gain_tax_pct=0,
        inflation=InflationSettings(
            min_pct=0, max_pct=0, avg_pct=0,
            volatility=InflationVolatility.CONSTANT,
        ),
        expense_periods=[
            ExpensePeriod(
                start_month=1, start_year=1,
                amount_min=500, amount_max=500, amount_avg=500,
                volatility=ExpenseVolatility.CONSTANT,
            ),
        ],
        buckets=[
            InvestmentBucket(
                name="Cash", currency="USD",
                initial_price=1, initial_amount=50000,
                growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                volatility=VolatilityProfile.CONSTANT,
                buy_sell_fee_pct=0,
                target_growth_pct=0,
            ),
        ],
    )


class TestRunSimulation:
    def test_output_shape(self):
        config = _make_config()
        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)
        assert len(df) == 24  # 2 years * 12 months
        assert "year" in df.columns
        assert "month" in df.columns
        assert "inflation" in df.columns
        assert "expenses" in df.columns
        assert "total_net_spent" in df.columns
        assert "cash_pool_amount" in df.columns
        assert "cash_pool_net_spent" in df.columns

    def test_bucket_columns_present(self):
        config = _make_config()
        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)
        for col in ["Cash_price", "Cash_amount", "Cash_net_spent"]:
            assert col in df.columns

    def test_expenses_covered(self):
        """With plenty of cash and no fees, net_spent should match expenses."""
        config = _make_config()
        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)
        # total_net_spent should closely match expenses each month
        diff = np.abs(df["expenses"].values - df["total_net_spent"].values)
        assert np.all(diff < 1.0)  # within $1 tolerance

    def test_deterministic_with_seed(self):
        config = _make_config()
        df1 = run_simulation(config, np.random.default_rng(99))
        df2 = run_simulation(config, np.random.default_rng(99))
        np.testing.assert_array_equal(df1.values, df2.values)

    def test_no_expenses_no_selling(self):
        config = SimConfig(
            period_years=1,
            expenses_currency="USD",
            inflation=InflationSettings(
                min_pct=0, max_pct=0, avg_pct=0,
                volatility=InflationVolatility.CONSTANT,
            ),
            buckets=[
                InvestmentBucket(
                    name="SP500", currency="USD",
                    initial_price=100, initial_amount=10000,
                    growth_min_pct=5, growth_max_pct=15, growth_avg_pct=10,
                    volatility=VolatilityProfile.CONSTANT,
                    buy_sell_fee_pct=0,
                    target_growth_pct=10,
                ),
            ],
        )
        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)
        # No expenses => no selling
        assert np.all(df["SP500_sold"].values == 0)
        assert np.all(df["total_net_spent"].values == 0)

    def test_cash_pool_covers_expenses(self):
        """With cash pool active, expenses should come from cash pool."""
        config = SimConfig(
            period_years=1,
            expenses_currency="USD",
            capital_gain_tax_pct=0,
            inflation=InflationSettings(
                min_pct=0, max_pct=0, avg_pct=0,
                volatility=InflationVolatility.CONSTANT,
            ),
            cash_pool=CashPool(
                initial_amount=100000,
                refill_trigger_months=6,
                refill_target_months=12,
                cash_floor_months=0,
            ),
            expense_periods=[
                ExpensePeriod(
                    start_month=1, start_year=1,
                    amount_min=500, amount_max=500, amount_avg=500,
                    volatility=ExpenseVolatility.CONSTANT,
                ),
            ],
            buckets=[
                InvestmentBucket(
                    name="SP500", currency="USD",
                    initial_price=100, initial_amount=50000,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                    volatility=VolatilityProfile.CONSTANT,
                    buy_sell_fee_pct=0,
                    target_growth_pct=0,
                ),
            ],
        )
        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)
        # Cash pool should decrease as expenses are drawn
        assert df["cash_pool_amount"].iloc[0] < 100000
        assert df["cash_pool_net_spent"].iloc[0] == 500
        # total_net_spent should match expenses (drawn from cash pool)
        diff = np.abs(df["expenses"].values - df["total_net_spent"].values)
        assert np.all(diff < 1.0)

    def test_cash_pool_activated_with_zero_initial_and_refill_target(self):
        """Cash pool should be active when initial_amount=0 but refill_target>0.

        Validates Stage 9 P1 fix for use_cash_pool condition.
        """
        config = SimConfig(
            period_years=1,
            expenses_currency="USD",
            capital_gain_tax_pct=0,
            inflation=InflationSettings(
                min_pct=0, max_pct=0, avg_pct=0,
                volatility=InflationVolatility.CONSTANT,
            ),
            cash_pool=CashPool(
                initial_amount=0,
                refill_trigger_months=6,
                refill_target_months=12,
                cash_floor_months=0,
            ),
            expense_periods=[
                ExpensePeriod(
                    start_month=1, start_year=1,
                    amount_min=500, amount_max=500, amount_avg=500,
                    volatility=ExpenseVolatility.CONSTANT,
                ),
            ],
            buckets=[
                InvestmentBucket(
                    name="SP500", currency="USD",
                    initial_price=100, initial_amount=50000,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                    volatility=VolatilityProfile.CONSTANT,
                    buy_sell_fee_pct=0,
                    target_growth_pct=0,
                ),
            ],
        )
        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)
        # Cash pool should be refilled from bucket and used for expenses
        # At month 1: cash pool starts at 0, refill triggered (0 < 6*500=3000),
        # should refill to 12*500=6000 from SP500
        assert df["cash_pool_amount"].iloc[0] > 0, \
            "Cash pool should be active and refilled even with initial_amount=0"
        assert df["cash_pool_net_spent"].iloc[0] > 0, \
            "Expenses should be drawn from the cash pool"

    @pytest.mark.xfail(reason="Stage 12 P0: bucket amount not revalued with price changes")
    def test_bucket_amount_reflects_price_growth(self):
        """Bucket amount should change as price changes (market value tracking).

        Currently bucket amount only changes from buy/sell operations,
        not from price appreciation/depreciation.
        """
        config = SimConfig(
            period_years=1,
            expenses_currency="USD",
            capital_gain_tax_pct=0,
            inflation=InflationSettings(
                min_pct=0, max_pct=0, avg_pct=0,
                volatility=InflationVolatility.CONSTANT,
            ),
            buckets=[
                InvestmentBucket(
                    name="SP500", currency="USD",
                    initial_price=100, initial_amount=10000,
                    growth_min_pct=10, growth_max_pct=10, growth_avg_pct=10,
                    volatility=VolatilityProfile.CONSTANT,
                    buy_sell_fee_pct=0,
                    target_growth_pct=10,
                ),
            ],
        )
        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)

        # With 10% annual growth (constant), price after 12 months ≈ 110.
        # Amount should grow proportionally: 10000 * (110/100) = 11000
        # (100 units * new_price = market value)
        final_price = df["SP500_price"].iloc[-1]
        final_amount = df["SP500_amount"].iloc[-1]

        # Amount should reflect price growth, not remain at initial 10000
        expected_amount = 10000 * (final_price / 100.0)
        assert abs(final_amount - expected_amount) < 50, \
            f"Amount {final_amount} should track price growth to ~{expected_amount}"
        assert final_amount > 10000, \
            f"Amount {final_amount} should be > 10000 after price appreciation"
