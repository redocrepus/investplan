"""Tests for Monte Carlo engine."""

import numpy as np
from models.config import SimConfig
from models.bucket import InvestmentBucket
from models.expense import ExpensePeriod
from models.inflation import InflationSettings
from engine.montecarlo import run_monte_carlo, MonteCarloResult
from utils.volatility import VolatilityProfile, ExpenseVolatility, InflationVolatility


def _make_config() -> SimConfig:
    return SimConfig(
        period_years=1,
        expenses_currency="USD",
        capital_gain_tax_pct=0,
        inflation=InflationSettings(
            min_pct=0, max_pct=0, avg_pct=0,
            volatility=InflationVolatility.CONSTANT,
        ),
        expense_periods=[
            ExpensePeriod(
                start_month=1, start_year=1,
                amount_min=100, amount_max=100, amount_avg=100,
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


class TestRunMonteCarlo:
    def test_result_structure(self):
        config = _make_config()
        result = run_monte_carlo(config, n_simulations=5, seed=42)
        assert isinstance(result, MonteCarloResult)
        assert result.n_simulations == 5
        assert 0.0 <= result.success_rate <= 1.0
        assert len(result.percentile_10) == 12
        assert len(result.percentile_50) == 12
        assert len(result.percentile_90) == 12

    def test_high_success_rate_with_plenty_of_cash(self):
        config = _make_config()
        result = run_monte_carlo(config, n_simulations=10, seed=42)
        # With 50000 cash and only 100/month expense, should always succeed
        assert result.success_rate == 1.0

    def test_progress_callback(self):
        config = _make_config()
        calls = []
        result = run_monte_carlo(
            config, n_simulations=3, seed=42,
            progress_callback=lambda cur, total: calls.append((cur, total)),
        )
        assert len(calls) == 3
        assert calls[-1] == (3, 3)

    def test_deterministic_with_seed(self):
        config = _make_config()
        r1 = run_monte_carlo(config, n_simulations=5, seed=123)
        r2 = run_monte_carlo(config, n_simulations=5, seed=123)
        assert r1.success_rate == r2.success_rate
        np.testing.assert_array_equal(
            r1.percentile_50["total_net_spent"].values,
            r2.percentile_50["total_net_spent"].values,
        )
