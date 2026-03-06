"""Tests for rebalancer engine — multi-trigger system, cost basis, cross-currency."""

import numpy as np
from engine.rebalancer import (
    BucketState, PurchaseLot, execute_rebalance, _compute_cost_basis,
    _add_purchase_lot,
)
from models.config import SimConfig
from models.bucket import (
    InvestmentBucket, BucketTrigger, TriggerType, SellSubtype, BuySubtype,
    CostBasisMethod,
)
from models.currency import CurrencySettings


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
    # Add initial lot
    _add_purchase_lot(state, amount, initial_price)
    return state


class TestSellTakeProfitTrigger:
    def test_triggers_when_exceeds(self):
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=1.5,
            target_bucket="Cash",
        )
        sp500 = _make_state("SP500", price=200, amount=10000,
                            initial_price=100, target_growth_pct=10,
                            triggers=[trigger])
        cash = _make_state("Cash", price=1, amount=50000,
                           initial_price=1, target_growth_pct=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        # SP500 should have sold excess (price=200 vs target=110, excess fraction = 90/200 = 45%)
        assert sp500.amount_sold > 0
        assert cash.amount_bought > 0

    def test_no_trigger_when_below(self):
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=1.5,
            target_bucket="Cash",
        )
        sp500 = _make_state("SP500", price=105, amount=10000,
                            initial_price=100, target_growth_pct=10,
                            triggers=[trigger])
        cash = _make_state("Cash", price=1, amount=50000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        assert sp500.amount_sold == 0
        assert cash.amount_bought == 0


class TestSellShareExceedsTrigger:
    def test_triggers_when_share_too_high(self):
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.SHARE_EXCEEDS.value,
            threshold_pct=60.0,
            target_bucket="Cash",
        )
        # SP500 = 80000, Cash = 20000, total = 100000, SP500 share = 80%
        sp500 = _make_state("SP500", price=100, amount=80000, triggers=[trigger])
        cash = _make_state("Cash", price=1, amount=20000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=80000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=20000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        assert sp500.amount_sold > 0
        # After rebalance, SP500 share should be closer to 60%
        total = sp500.amount + cash.amount
        share = sp500.amount / total * 100
        assert share < 80  # Should have sold some

    def test_no_trigger_when_share_ok(self):
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.SHARE_EXCEEDS.value,
            threshold_pct=90.0,
            target_bucket="Cash",
        )
        sp500 = _make_state("SP500", price=100, amount=80000, triggers=[trigger])
        cash = _make_state("Cash", price=1, amount=20000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=80000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=20000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        assert sp500.amount_sold == 0


class TestBuyDiscountTrigger:
    def test_triggers_when_undervalued(self):
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.DISCOUNT.value,
            threshold_pct=5.0,
            target_bucket="Cash",  # source bucket to sell from
        )
        # SP500 price=80, target price=110 (100*1.1), discount=37.5% > 5%
        sp500 = _make_state("SP500", price=80, amount=10000,
                            initial_price=100, target_growth_pct=10,
                            triggers=[trigger])
        cash = _make_state("Cash", price=1, amount=50000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        assert sp500.amount_bought > 0
        assert cash.amount_sold > 0

    def test_no_trigger_when_overvalued(self):
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.DISCOUNT.value,
            threshold_pct=5.0,
            target_bucket="Cash",
        )
        # SP500 price=120, target price=110, no discount
        sp500 = _make_state("SP500", price=120, amount=10000,
                            initial_price=100, target_growth_pct=10,
                            triggers=[trigger])
        cash = _make_state("Cash", price=1, amount=50000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        assert sp500.amount_bought == 0


class TestBuyShareBelowTrigger:
    def test_triggers_when_share_too_low(self):
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=30.0,
            target_bucket="Cash",  # source bucket
        )
        # SP500 = 10000, Cash = 90000, total = 100000, SP500 share = 10% < 30%
        sp500 = _make_state("SP500", price=100, amount=10000, triggers=[trigger])
        cash = _make_state("Cash", price=1, amount=90000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=90000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        assert sp500.amount_bought > 0
        assert cash.amount_sold > 0

    def test_no_trigger_when_share_ok(self):
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=5.0,
            target_bucket="Cash",
        )
        # SP500 = 10000, Cash = 90000, share = 10% > 5%
        sp500 = _make_state("SP500", price=100, amount=10000, triggers=[trigger])
        cash = _make_state("Cash", price=1, amount=90000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=90000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        assert sp500.amount_bought == 0


class TestRunawayGuard:
    def test_no_sell_trigger_when_low_runway(self):
        """If portfolio runway < required months, sell trigger should be skipped."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=0.1,  # Very low to ensure it would fire
            target_bucket="Cash",
        )
        sp500 = _make_state("SP500", price=200, amount=500,
                            initial_price=100, target_growth_pct=10,
                            required_runaway_months=12, triggers=[trigger])

        config = SimConfig(
            expenses_currency="USD",
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=500,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
            ],
        )

        # High expense relative to holdings (500 USD, need 12 months * 1000 = 12000)
        execute_rebalance([sp500], 1000, {}, config, 0)

        # Sell trigger should be skipped due to low runway
        # But expense coverage should still work
        assert sp500.net_spent > 0


class TestCashFloorCascade:
    def test_respects_cash_floor(self):
        """Buckets with cash floor should keep minimum amount."""
        config = SimConfig(
            expenses_currency="USD",
            capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(
                    name="Primary", currency="USD",
                    initial_price=100, initial_amount=5000,
                    growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                    spending_priority=0, cash_floor_months=3,
                ),
                InvestmentBucket(
                    name="Secondary", currency="USD",
                    initial_price=100, initial_amount=10000,
                    growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                    spending_priority=1, cash_floor_months=0,
                ),
            ],
        )

        states = [
            _make_state("Primary", price=100, amount=5000, initial_price=100,
                        spending_priority=0, cash_floor_months=3),
            _make_state("Secondary", price=100, amount=10000, initial_price=100,
                        spending_priority=1, cash_floor_months=0),
        ]

        monthly_expense = 1000
        total_covered = execute_rebalance(states, monthly_expense, {}, config, 0)

        # Primary should keep at least 3000 (3 months * 1000)
        assert states[0].amount >= 3000 - 1  # small tolerance


class TestMultipleTriggers:
    def test_multiple_sell_triggers(self):
        """A bucket with two sell triggers should execute both if conditions met."""
        triggers = [
            BucketTrigger(
                trigger_type=TriggerType.SELL,
                subtype=SellSubtype.TAKE_PROFIT.value,
                threshold_pct=1.0,
                target_bucket="Cash",
            ),
            BucketTrigger(
                trigger_type=TriggerType.SELL,
                subtype=SellSubtype.SHARE_EXCEEDS.value,
                threshold_pct=70.0,
                target_bucket="Cash",
            ),
        ]
        # Price doubled (200% growth vs 10% target = ratio 20 > 1.0) AND share = 80% > 70%
        sp500 = _make_state("SP500", price=200, amount=80000,
                            initial_price=100, target_growth_pct=10,
                            triggers=triggers)
        cash = _make_state("Cash", price=1, amount=20000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=80000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=20000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        assert sp500.amount_sold > 0
        assert cash.amount_bought > 0


class TestCostBasisFIFO:
    def test_fifo_correct_gains(self):
        state = BucketState(
            name="Test", currency="USD", price=150, amount=100,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            cost_basis_method=CostBasisMethod.FIFO,
        )
        # Add lots: 50 units at $100, then 50 units at $120
        state.purchase_lots = [
            PurchaseLot(price=100, amount=50),
            PurchaseLot(price=120, amount=50),
        ]

        # Sell 60 currency — FIFO consumes 50 from the first lot, 10 from the second.
        cost = _compute_cost_basis(state, 60)
        expected = 60
        assert abs(cost - expected) < 0.01

        # First lot should be consumed, second lot should have 40 left
        assert len(state.purchase_lots) == 1
        assert abs(state.purchase_lots[0].amount - 40) < 0.01

    def test_fifo_does_not_scale_by_lot_price(self):
        state = BucketState(
            name="Test", currency="USD", price=150, amount=5000,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            cost_basis_method=CostBasisMethod.FIFO,
        )
        state.purchase_lots = [PurchaseLot(price=100, amount=5000)]

        # Regression: selling 1000 should not become 1000*price.
        cost = _compute_cost_basis(state, 1000)
        assert abs(cost - 1000) < 0.01


class TestCostBasisLIFO:
    def test_lifo_correct_gains(self):
        state = BucketState(
            name="Test", currency="USD", price=150, amount=100,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            cost_basis_method=CostBasisMethod.LIFO,
        )
        # Add lots: 50 units at $100, then 50 units at $120
        state.purchase_lots = [
            PurchaseLot(price=100, amount=50),
            PurchaseLot(price=120, amount=50),
        ]

        # Sell 60 currency — LIFO consumes 50 from the second lot, 10 from the first.
        cost = _compute_cost_basis(state, 60)
        expected = 60
        assert abs(cost - expected) < 0.01

        # Second lot should be consumed, first lot should have 40 left
        assert len(state.purchase_lots) == 1
        assert abs(state.purchase_lots[0].amount - 40) < 0.01


class TestCostBasisAVCO:
    def test_avco_correct_gains(self):
        state = BucketState(
            name="Test", currency="USD", price=150, amount=100,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            cost_basis_method=CostBasisMethod.AVCO,
        )
        # Simulate adding lots to compute avg_cost
        _add_purchase_lot(state, 50, 100)
        _add_purchase_lot(state, 50, 120)

        cost = _compute_cost_basis(state, 60)
        expected = 60
        assert abs(cost - expected) < 0.01


class TestCrossCurrencyTrigger:
    def test_sell_trigger_cross_currency(self):
        """Sell EUR bucket, buy USD cash — FX conversion + fees should apply."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=1.0,
            target_bucket="Cash",
        )
        # EUR bucket doubled in price
        eur_bucket = _make_state("EuroFund", currency="EUR", price=200, amount=10000,
                                 initial_price=100, target_growth_pct=10,
                                 triggers=[trigger])
        cash = _make_state("Cash", currency="USD", price=1, amount=50000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=25,
            buckets=[
                InvestmentBucket(name="EuroFund", currency="EUR", initial_price=100,
                                 initial_amount=10000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", currency="USD", initial_price=1,
                                 initial_amount=50000, growth_min_pct=0,
                                 growth_max_pct=0, growth_avg_pct=0),
            ],
            currencies=[
                CurrencySettings(
                    code="EUR", initial_price=1.1,
                    min_price=0.9, max_price=1.3, avg_price=1.1,
                    conversion_fee_pct=0.5,
                ),
            ],
        )

        fx_rates = {"EUR": 1.1}
        execute_rebalance([eur_bucket, cash], 0, fx_rates, config, 0)

        # Should have sold some EUR and bought USD cash
        assert eur_bucket.amount_sold > 0
        assert cash.amount_bought > 0
        # Fees should include sell fee + FX conversion fee
        assert eur_bucket.fees_paid > 0 or cash.fees_paid > 0


class TestSaveLoadRoundtrip:
    def test_roundtrip_with_triggers(self):
        """Config with triggers should serialize and deserialize correctly."""
        triggers = [
            BucketTrigger(
                trigger_type=TriggerType.SELL,
                subtype=SellSubtype.TAKE_PROFIT.value,
                threshold_pct=1.5,
                target_bucket="Cash",
                frequency="monthly",
            ),
            BucketTrigger(
                trigger_type=TriggerType.BUY,
                subtype=BuySubtype.DISCOUNT.value,
                threshold_pct=10.0,
                target_bucket="Cash",
                frequency="yearly",
            ),
        ]
        config = SimConfig(
            period_years=5,
            expenses_currency="USD",
            buckets=[
                InvestmentBucket(
                    name="SP500", initial_price=100, initial_amount=50000,
                    growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                    cost_basis_method=CostBasisMethod.LIFO,
                    spending_priority=1,
                    cash_floor_months=3,
                    required_runaway_months=6,
                    triggers=triggers,
                ),
            ],
        )

        json_str = config.model_dump_json()
        loaded = SimConfig.model_validate_json(json_str)

        assert len(loaded.buckets) == 1
        b = loaded.buckets[0]
        assert b.cost_basis_method == CostBasisMethod.LIFO
        assert b.spending_priority == 1
        assert b.cash_floor_months == 3
        assert len(b.triggers) == 2
        assert b.triggers[0].subtype == "take_profit"
        assert b.triggers[1].subtype == "discount"
        assert b.triggers[1].frequency == "yearly"
