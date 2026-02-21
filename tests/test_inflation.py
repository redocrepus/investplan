"""Tests for inflation engine."""

import numpy as np
from models.inflation import InflationSettings
from engine.inflation import simulate_monthly_inflation
from utils.volatility import InflationVolatility


class TestSimulateMonthlyInflation:
    def test_constant_returns_average(self):
        settings = InflationSettings(
            min_pct=2.0, max_pct=4.0, avg_pct=3.0,
            volatility=InflationVolatility.CONSTANT,
        )
        rng = np.random.default_rng(42)
        rates = simulate_monthly_inflation(settings, 120, rng)
        expected = 3.0 / 100.0 / 12.0
        np.testing.assert_allclose(rates, expected)

    def test_bounds_respected(self):
        settings = InflationSettings(
            min_pct=1.0, max_pct=5.0, avg_pct=3.0,
            volatility=InflationVolatility.CRAZY,
        )
        rng = np.random.default_rng(42)
        rates = simulate_monthly_inflation(settings, 1200, rng)
        min_monthly = 1.0 / 100.0 / 12.0
        max_monthly = 5.0 / 100.0 / 12.0
        assert np.all(rates >= min_monthly - 1e-10)
        assert np.all(rates <= max_monthly + 1e-10)

    def test_mean_reversion(self):
        """After many steps, the average should be close to the target."""
        settings = InflationSettings(
            min_pct=0.0, max_pct=10.0, avg_pct=3.0,
            volatility=InflationVolatility.MILD,
        )
        rng = np.random.default_rng(123)
        rates = simulate_monthly_inflation(settings, 12000, rng)
        avg_annual = np.mean(rates) * 12 * 100
        assert abs(avg_annual - 3.0) < 1.0  # within 1% of target

    def test_output_length(self):
        settings = InflationSettings(min_pct=1.0, max_pct=5.0, avg_pct=3.0)
        rng = np.random.default_rng(0)
        rates = simulate_monthly_inflation(settings, 60, rng)
        assert len(rates) == 60
