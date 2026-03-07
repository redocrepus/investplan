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
        rates = simulate_monthly_inflation(settings, 24000, rng)
        avg_annual = np.mean(rates) * 12 * 100
        assert abs(avg_annual - 3.0) < 1.5  # within 1.5% of target

    def test_output_length(self):
        settings = InflationSettings(min_pct=1.0, max_pct=5.0, avg_pct=3.0)
        rng = np.random.default_rng(0)
        rates = simulate_monthly_inflation(settings, 60, rng)
        assert len(rates) == 60

    def test_mild_volatility_std_matches_sigma(self):
        """MILD profile (sigma=0.002) should produce meaningful monthly variation."""
        settings = InflationSettings(
            min_pct=0.0, max_pct=20.0, avg_pct=3.0,
            volatility=InflationVolatility.MILD,
        )
        rng = np.random.default_rng(42)
        rates = simulate_monthly_inflation(settings, 12000, rng)
        # Monthly std should be in the ballpark of sigma=0.002 (modulated by mean reversion)
        # With the old /12.0 bug, std was ~0.00016 — far too small
        monthly_std = np.std(rates)
        assert monthly_std > 0.0005, f"Volatility too low: std={monthly_std}"

    def test_crazy_volatility_has_more_variation_than_mild(self):
        """CRAZY profile should produce wider spread than MILD."""
        mild_settings = InflationSettings(
            min_pct=0.0, max_pct=20.0, avg_pct=3.0,
            volatility=InflationVolatility.MILD,
        )
        crazy_settings = InflationSettings(
            min_pct=0.0, max_pct=20.0, avg_pct=3.0,
            volatility=InflationVolatility.CRAZY,
        )
        rng1 = np.random.default_rng(42)
        rng2 = np.random.default_rng(42)
        mild_rates = simulate_monthly_inflation(mild_settings, 6000, rng1)
        crazy_rates = simulate_monthly_inflation(crazy_settings, 6000, rng2)
        assert np.std(crazy_rates) > np.std(mild_rates)
