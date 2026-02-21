"""Tests for the simulator orchestrator."""

import numpy as np
from models.config import SimConfig
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
