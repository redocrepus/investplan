"""Tests for currency/FX engine."""

import numpy as np
from models.currency import CurrencySettings
from engine.currency import simulate_fx_rates
from utils.volatility import VolatilityProfile


class TestSimulateFxRates:
    def test_constant_returns_average(self):
        settings = CurrencySettings(
            code="EUR", initial_price=1.1,
            min_price=0.8, max_price=1.5, avg_price=1.1,
            volatility=VolatilityProfile.CONSTANT,
        )
        rng = np.random.default_rng(42)
        prices = simulate_fx_rates(settings, 120, rng)
        np.testing.assert_allclose(prices, 1.1)

    def test_bounds_respected(self):
        settings = CurrencySettings(
            code="EUR", initial_price=1.1,
            min_price=0.8, max_price=1.5, avg_price=1.1,
            volatility=VolatilityProfile.SP500,
        )
        rng = np.random.default_rng(42)
        prices = simulate_fx_rates(settings, 1200, rng)
        assert np.all(prices >= 0.8 - 1e-10)
        assert np.all(prices <= 1.5 + 1e-10)

    def test_output_length(self):
        settings = CurrencySettings(
            code="EUR", initial_price=1.0,
            min_price=0.5, max_price=2.0, avg_price=1.0,
        )
        rng = np.random.default_rng(0)
        prices = simulate_fx_rates(settings, 60, rng)
        assert len(prices) == 60

    def test_starts_near_initial(self):
        settings = CurrencySettings(
            code="GBP", initial_price=1.3,
            min_price=1.0, max_price=2.0, avg_price=1.5,
            volatility=VolatilityProfile.GOV_BONDS,
        )
        rng = np.random.default_rng(42)
        prices = simulate_fx_rates(settings, 12, rng)
        # First price should be close to initial
        assert abs(prices[0] - 1.3) < 0.1
