"""Tests for bucket engine — price simulation and buy/sell math."""

import numpy as np
from models.bucket import InvestmentBucket
from engine.bucket import simulate_bucket_prices, compute_sell, compute_buy
from utils.volatility import VolatilityProfile


class TestSimulateBucketPrices:
    def test_constant_growth(self):
        bucket = InvestmentBucket(
            name="Bonds", initial_price=100, initial_amount=10000,
            growth_min_pct=5, growth_max_pct=5, growth_avg_pct=5,
            volatility=VolatilityProfile.CONSTANT,
        )
        rng = np.random.default_rng(42)
        prices = simulate_bucket_prices(bucket, 12, rng)
        # After 12 months at 5% annual, price should be ~105
        assert abs(prices[-1] - 105) < 0.5

    def test_output_length(self):
        bucket = InvestmentBucket(
            name="SP500", initial_price=100, initial_amount=10000,
            growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
        )
        rng = np.random.default_rng(0)
        prices = simulate_bucket_prices(bucket, 60, rng)
        assert len(prices) == 60

    def test_prices_positive(self):
        bucket = InvestmentBucket(
            name="BTC", initial_price=50000, initial_amount=1000,
            growth_min_pct=-50, growth_max_pct=200, growth_avg_pct=20,
            volatility=VolatilityProfile.BITCOIN,
        )
        rng = np.random.default_rng(42)
        prices = simulate_bucket_prices(bucket, 120, rng)
        assert np.all(prices > 0)


class TestComputeSell:
    def test_no_fee(self):
        net, fee = compute_sell(1000, 0)
        assert net == 1000
        assert fee == 0

    def test_with_fee(self):
        net, fee = compute_sell(1000, 1.0)
        assert fee == 10
        assert net == 990


class TestComputeBuy:
    def test_no_fee(self):
        invested, fee = compute_buy(1000, 0)
        assert invested == 1000
        assert fee == 0

    def test_with_fee(self):
        invested, fee = compute_buy(1000, 2.0)
        assert fee == 20
        assert invested == 980
