"""Tests for Pydantic data models."""

import pytest
from models.inflation import InflationSettings
from models.expense import ExpensePeriod, OneTimeExpense
from models.currency import CurrencySettings
from models.bucket import (
    InvestmentBucket, BucketTrigger, TriggerType, SellSubtype, BuySubtype,
    CostBasisMethod,
)
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

    def test_defaults(self):
        b = InvestmentBucket(
            name="X", initial_price=100, initial_amount=10000,
            growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
        )
        assert b.spending_priority == 0
        assert b.cash_floor_months == 0.0
        assert b.required_runaway_months == 6.0
        assert b.cost_basis_method == CostBasisMethod.FIFO
        assert b.triggers == []

    def test_with_triggers(self):
        t = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=1.5,
            target_bucket="Cash",
        )
        b = InvestmentBucket(
            name="SP500", initial_price=100, initial_amount=10000,
            growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
            triggers=[t],
        )
        assert len(b.triggers) == 1
        assert b.triggers[0].subtype == "take_profit"


class TestBucketTrigger:
    def test_valid_sell_take_profit(self):
        t = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=1.5,
        )
        assert t.trigger_type == TriggerType.SELL

    def test_valid_sell_share_exceeds(self):
        t = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.SHARE_EXCEEDS.value,
            threshold_pct=60.0,
        )
        assert t.subtype == "share_exceeds"

    def test_valid_buy_discount(self):
        t = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.DISCOUNT.value,
            threshold_pct=5.0,
            target_bucket="Cash",
        )
        assert t.subtype == "discount"

    def test_valid_buy_share_below(self):
        t = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=20.0,
            target_bucket="Cash",
        )
        assert t.subtype == "share_below"

    def test_invalid_sell_subtype(self):
        with pytest.raises(ValueError):
            BucketTrigger(
                trigger_type=TriggerType.SELL,
                subtype="discount",
                threshold_pct=1.5,
            )

    def test_invalid_buy_subtype(self):
        with pytest.raises(ValueError):
            BucketTrigger(
                trigger_type=TriggerType.BUY,
                subtype="take_profit",
                threshold_pct=1.5,
            )

    def test_invalid_period_months(self):
        with pytest.raises(ValueError):
            BucketTrigger(
                trigger_type=TriggerType.SELL,
                subtype=SellSubtype.TAKE_PROFIT.value,
                threshold_pct=1.5,
                period_months=0,
            )

    def test_valid_period_months(self):
        t = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=1.5,
            period_months=6,
        )
        assert t.period_months == 6

    def test_buy_trigger_requires_source_buckets(self):
        with pytest.raises(ValueError, match="source bucket"):
            BucketTrigger(
                trigger_type=TriggerType.BUY,
                subtype=BuySubtype.DISCOUNT.value,
                threshold_pct=5.0,
            )

    def test_buy_trigger_auto_migrates_target_bucket(self):
        t = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.DISCOUNT.value,
            threshold_pct=5.0,
            target_bucket="Cash",
        )
        assert t.source_buckets == ["Cash"]

    def test_buy_trigger_with_source_buckets(self):
        t = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=20.0,
            source_buckets=["Cash", "Bonds"],
        )
        assert t.source_buckets == ["Cash", "Bonds"]

    def test_buy_trigger_source_buckets_not_overwritten(self):
        t = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.DISCOUNT.value,
            threshold_pct=5.0,
            target_bucket="Cash",
            source_buckets=["Bonds"],
        )
        assert t.source_buckets == ["Bonds"]


class TestCashPool:
    def test_default(self):
        from models.config import CashPool
        cp = CashPool()
        assert cp.initial_amount == 0.0
        assert cp.refill_trigger_months == 12.0
        assert cp.refill_target_months == 24.0
        assert cp.cash_floor_months == 6.0

    def test_valid(self):
        from models.config import CashPool
        cp = CashPool(initial_amount=50000, refill_trigger_months=6, refill_target_months=12, cash_floor_months=6)
        assert cp.initial_amount == 50000

    def test_negative_initial_amount(self):
        from models.config import CashPool
        with pytest.raises(ValueError):
            CashPool(initial_amount=-1)

    def test_negative_refill_trigger(self):
        from models.config import CashPool
        with pytest.raises(ValueError):
            CashPool(refill_trigger_months=-1)

    def test_negative_refill_target(self):
        from models.config import CashPool
        with pytest.raises(ValueError):
            CashPool(refill_target_months=-1)

    def test_negative_cash_floor(self):
        from models.config import CashPool
        with pytest.raises(ValueError):
            CashPool(cash_floor_months=-1)


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
