"""Tests for Pydantic data models."""

import pytest
from models.inflation import InflationSettings
from models.expense import ExpensePeriod, OneTimeExpense
from models.currency import CurrencySettings
from models.bucket import InvestmentBucket, RebalancingParams
from models.config import SimConfig
from utils.volatility import InflationVolatility, ExpenseVolatility, VolatilityProfile


class TestInflationSettings:
    def test_valid(self):
        s = InflationSettings(min_pct=1.0, max_pct=5.0, avg_pct=3.0)
        assert s.avg_pct == 3.0

    def test_min_greater_than_max(self):
        with pytest.raises(ValueError):
            InflationSettings(min_pct=5.0, max_pct=1.0, avg_pct=3.0)

    def test_avg_out_of_bounds(self):
        with pytest.raises(ValueError):
            InflationSettings(min_pct=1.0, max_pct=5.0, avg_pct=6.0)

    def test_volatility_default(self):
        s = InflationSettings(min_pct=0, max_pct=10, avg_pct=3)
        assert s.volatility == InflationVolatility.MILD


class TestExpensePeriod:
    def test_valid(self):
        p = ExpensePeriod(
            start_month=1, start_year=1,
            amount_min=1000, amount_max=2000, amount_avg=1500,
        )
        assert p.amount_avg == 1500

    def test_min_greater_than_max(self):
        with pytest.raises(ValueError):
            ExpensePeriod(
                start_month=1, start_year=1,
                amount_min=2000, amount_max=1000, amount_avg=1500,
            )

    def test_invalid_month(self):
        with pytest.raises(ValueError):
            ExpensePeriod(
                start_month=13, start_year=1,
                amount_min=1000, amount_max=2000, amount_avg=1500,
            )

    def test_invalid_year(self):
        with pytest.raises(ValueError):
            ExpensePeriod(
                start_month=1, start_year=0,
                amount_min=1000, amount_max=2000, amount_avg=1500,
            )


class TestOneTimeExpense:
    def test_valid(self):
        o = OneTimeExpense(month=6, year=2, amount=5000)
        assert o.amount == 5000

    def test_negative_amount(self):
        with pytest.raises(ValueError):
            OneTimeExpense(month=6, year=2, amount=-100)

    def test_invalid_month(self):
        with pytest.raises(ValueError):
            OneTimeExpense(month=0, year=1, amount=100)


class TestCurrencySettings:
    def test_valid(self):
        c = CurrencySettings(
            code="EUR", initial_price=1.1,
            min_price=0.8, max_price=1.5, avg_price=1.1,
        )
        assert c.code == "EUR"

    def test_min_greater_than_max(self):
        with pytest.raises(ValueError):
            CurrencySettings(
                code="EUR", initial_price=1.1,
                min_price=1.5, max_price=0.8, avg_price=1.1,
            )

    def test_negative_initial_price(self):
        with pytest.raises(ValueError):
            CurrencySettings(
                code="EUR", initial_price=-1,
                min_price=0.8, max_price=1.5, avg_price=1.0,
            )

    def test_negative_fee(self):
        with pytest.raises(ValueError):
            CurrencySettings(
                code="EUR", initial_price=1.0,
                min_price=0.8, max_price=1.5, avg_price=1.0,
                conversion_fee_pct=-1,
            )


class TestInvestmentBucket:
    def test_valid(self):
        b = InvestmentBucket(
            name="SP500", initial_price=100, initial_amount=10000,
            growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
        )
        assert b.name == "SP500"

    def test_growth_bounds(self):
        with pytest.raises(ValueError):
            InvestmentBucket(
                name="X", initial_price=100, initial_amount=10000,
                growth_min_pct=30, growth_max_pct=-10, growth_avg_pct=10,
            )

    def test_negative_initial_price(self):
        with pytest.raises(ValueError):
            InvestmentBucket(
                name="X", initial_price=-1, initial_amount=10000,
                growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
            )

    def test_rebalancing_defaults(self):
        b = InvestmentBucket(
            name="X", initial_price=100, initial_amount=10000,
            growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
        )
        assert b.rebalancing.frequency == "monthly"
        assert b.rebalancing.sell_trigger == 1.5


class TestRebalancingParams:
    def test_invalid_frequency(self):
        with pytest.raises(ValueError):
            RebalancingParams(frequency="weekly")

    def test_negative_sell_trigger(self):
        with pytest.raises(ValueError):
            RebalancingParams(sell_trigger=-1)


class TestSimConfig:
    def test_default(self):
        c = SimConfig()
        assert c.period_years == 10
        assert c.expenses_currency == "USD"
        assert len(c.buckets) == 0

    def test_with_buckets(self):
        c = SimConfig(
            buckets=[
                InvestmentBucket(
                    name="SP500", initial_price=100, initial_amount=50000,
                    growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                ),
            ],
        )
        assert len(c.buckets) == 1
