"""Tests for rebalancer engine — multi-trigger system, cost basis, cross-currency."""

import numpy as np
from engine.rebalancer import (
    BucketState, CashPoolState, PurchaseLot, execute_rebalance,
    _compute_cost_basis, _add_purchase_lot,
)
from models.config import CashPool
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
                period_months=1,
            ),
            BucketTrigger(
                trigger_type=TriggerType.BUY,
                subtype=BuySubtype.DISCOUNT.value,
                threshold_pct=10.0,
                target_bucket="Cash",
                period_months=12,
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
        assert b.triggers[1].period_months == 12


class TestCashPoolExpenses:
    def test_expenses_drawn_from_cash_pool(self):
        """Expenses should be subtracted from cash pool, not from buckets."""
        sp500 = _make_state("SP500", price=100, amount=50000)
        cash_pool = CashPoolState(amount=10000, refill_trigger_months=0, refill_target_months=0, cash_floor_months=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            cash_pool=CashPool(initial_amount=10000, refill_trigger_months=0, refill_target_months=0, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5),
            ],
        )

        execute_rebalance([sp500], 1000, {}, config, 0, cash_pool=cash_pool)

        assert cash_pool.net_spent == 1000
        assert cash_pool.amount == 9000
        # Bucket should NOT have sold anything for expenses
        assert sp500.amount_sold == 0

    def test_fallthrough_when_cash_pool_insufficient(self):
        """When cash pool can't cover expenses, fall through to bucket selling."""
        sp500 = _make_state("SP500", price=100, amount=50000)
        cash_pool = CashPoolState(amount=500, refill_trigger_months=0, refill_target_months=0, cash_floor_months=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            cash_pool=CashPool(initial_amount=500, refill_trigger_months=0, refill_target_months=0, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5),
            ],
        )

        total_covered = execute_rebalance([sp500], 1000, {}, config, 0, cash_pool=cash_pool)

        assert cash_pool.net_spent == 500  # 500 drawn from cash pool
        assert cash_pool.amount == 0
        assert sp500.amount_sold > 0  # remainder covered by selling bucket
        assert total_covered == 1000  # fully covered


class TestCashPoolRefill:
    def test_refill_triggers_when_below_target(self):
        """Cash pool should be refilled when below target months."""
        sp500 = _make_state("SP500", price=200, amount=50000,
                            initial_price=100, buy_sell_fee_pct=0)
        cash_pool = CashPoolState(amount=2000, refill_trigger_months=6, refill_target_months=12, cash_floor_months=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            cash_pool=CashPool(initial_amount=2000, refill_trigger_months=6, refill_target_months=12, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                                 buy_sell_fee_pct=0),
            ],
        )

        execute_rebalance([sp500], 1000, {}, config, 0, cash_pool=cash_pool)

        # Target = 12 * 1000 = 12000. Started at 1000, drew 1000 expenses -> 0
        # Should have refilled from SP500
        assert cash_pool.amount > 0
        assert sp500.amount_sold > 0

    def test_refill_sells_most_profitable_first(self):
        """More profitable bucket should be sold first for refill."""
        # profitable bucket: price doubled (100 -> 200)
        profitable = _make_state("Profitable", price=200, amount=20000,
                                 initial_price=100, buy_sell_fee_pct=0,
                                 spending_priority=1)
        # unprofitable bucket: price halved (100 -> 50)
        unprofitable = _make_state("Unprofitable", price=50, amount=20000,
                                   initial_price=100, buy_sell_fee_pct=0,
                                   spending_priority=0)

        cash_pool = CashPoolState(amount=500, refill_trigger_months=3, refill_target_months=6, cash_floor_months=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            cash_pool=CashPool(initial_amount=500, refill_trigger_months=3, refill_target_months=6, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="Profitable", initial_price=100, initial_amount=20000,
                                 growth_min_pct=0, growth_max_pct=100, growth_avg_pct=10,
                                 buy_sell_fee_pct=0, spending_priority=1),
                InvestmentBucket(name="Unprofitable", initial_price=100, initial_amount=20000,
                                 growth_min_pct=-50, growth_max_pct=10, growth_avg_pct=0,
                                 buy_sell_fee_pct=0, spending_priority=0),
            ],
        )

        execute_rebalance([profitable, unprofitable], 500, {}, config, 0, cash_pool=cash_pool)

        # Profitable bucket should have been sold first
        assert profitable.amount_sold > 0

    def test_refill_respects_source_cash_floors(self):
        """Refill should not sell below a bucket's cash floor."""
        sp500 = _make_state("SP500", price=200, amount=5000,
                            initial_price=100, buy_sell_fee_pct=0,
                            cash_floor_months=4)

        cash_pool = CashPoolState(amount=0, refill_trigger_months=12, refill_target_months=24, cash_floor_months=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            cash_pool=CashPool(initial_amount=0, refill_trigger_months=12, refill_target_months=24, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=5000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                                 buy_sell_fee_pct=0, cash_floor_months=4),
            ],
        )

        execute_rebalance([sp500], 1000, {}, config, 0, cash_pool=cash_pool)

        # SP500 cash floor = 4 * 1000 = 4000. Should keep at least 4000.
        assert sp500.amount >= 3999  # small tolerance

    def test_refill_applies_fees(self):
        """Refill sells should apply fees."""
        sp500 = _make_state("SP500", price=200, amount=50000,
                            initial_price=100, buy_sell_fee_pct=1.0)

        cash_pool = CashPoolState(amount=1, refill_trigger_months=6, refill_target_months=12, cash_floor_months=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=25,
            cash_pool=CashPool(initial_amount=1, refill_trigger_months=6, refill_target_months=12, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=100, growth_avg_pct=10,
                                 buy_sell_fee_pct=1.0),
            ],
        )

        execute_rebalance([sp500], 1000, {}, config, 0, cash_pool=cash_pool)

        assert sp500.fees_paid > 0
        # Net proceeds to cash pool should be less than gross sell amount due to fees
        assert cash_pool.amount < sp500.amount_sold


class TestTriggerPeriodMonths:
    def test_monthly_trigger_fires_every_month(self):
        """period_months=1 should fire every month."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=1.0,
            target_bucket="Cash",
            period_months=1,
        )
        sp500 = _make_state("SP500", price=200, amount=10000,
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

        # Should fire at month 0, 1, 5, etc.
        for month_idx in [0, 1, 5]:
            sp500.amount = 10000
            sp500.price = 200
            execute_rebalance([sp500, cash], 0, {}, config, month_idx)
            assert sp500.amount_sold > 0, f"Trigger should fire at month {month_idx}"

    def test_quarterly_trigger_fires_correctly(self):
        """period_months=3 should fire at months 0, 3, 6, etc."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=1.0,
            target_bucket="Cash",
            period_months=3,
        )
        sp500 = _make_state("SP500", price=200, amount=10000,
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

        # Should fire at month 0, 3, 6
        for month_idx in [0, 3, 6]:
            sp500.amount = 10000
            sp500.price = 200
            execute_rebalance([sp500, cash], 0, {}, config, month_idx)
            assert sp500.amount_sold > 0, f"Trigger should fire at month {month_idx}"

        # Should NOT fire at month 1, 2, 4, 5
        for month_idx in [1, 2, 4, 5]:
            sp500.amount = 10000
            sp500.price = 200
            execute_rebalance([sp500, cash], 0, {}, config, month_idx)
            assert sp500.amount_sold == 0, f"Trigger should NOT fire at month {month_idx}"

    def test_yearly_trigger_fires_every_12_months(self):
        """period_months=12 should fire at months 0, 12, 24, etc."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=1.0,
            target_bucket="Cash",
            period_months=12,
        )
        sp500 = _make_state("SP500", price=200, amount=10000,
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

        # Should fire at month 0, 12, 24
        for month_idx in [0, 12, 24]:
            sp500.amount = 10000
            sp500.price = 200
            execute_rebalance([sp500, cash], 0, {}, config, month_idx)
            assert sp500.amount_sold > 0, f"Trigger should fire at month {month_idx}"

        # Should NOT fire at months 1-11
        for month_idx in [1, 6, 11]:
            sp500.amount = 10000
            sp500.price = 200
            execute_rebalance([sp500, cash], 0, {}, config, month_idx)
            assert sp500.amount_sold == 0, f"Trigger should NOT fire at month {month_idx}"


class TestMultiSourceBuyTrigger:
    def test_sells_from_most_profitable_first(self):
        """Buy trigger with 3 source buckets should sell from most profitable first."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=30.0,
            source_buckets=["Source1", "Source2", "Source3"],
        )
        # Buyer: 5% of portfolio, should buy up to 30%
        buyer = _make_state("Buyer", price=100, amount=5000, triggers=[trigger])
        # Source1: least profitable (price = initial)
        src1 = _make_state("Source1", price=100, amount=30000, initial_price=100)
        # Source2: most profitable (price doubled)
        src2 = _make_state("Source2", price=200, amount=30000, initial_price=100)
        # Source3: moderately profitable
        src3 = _make_state("Source3", price=150, amount=30000, initial_price=100)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Buyer", initial_price=100, initial_amount=5000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Source1", initial_price=100, initial_amount=30000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Source2", initial_price=100, initial_amount=30000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Source3", initial_price=100, initial_amount=30000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
            ],
        )

        execute_rebalance([buyer, src1, src2, src3], 0, {}, config, 0)

        assert buyer.amount_bought > 0
        # Source2 (most profitable) should have sold the most
        assert src2.amount_sold > 0
        # Source2 should sell more than Source1 (least profitable is sold last)
        assert src2.amount_sold >= src1.amount_sold

    def test_respects_cash_floors_on_each_source(self):
        """Each source's cash floor should be respected."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=50.0,
            source_buckets=["Source1", "Source2"],
        )
        buyer = _make_state("Buyer", price=100, amount=5000, triggers=[trigger])
        # Source1: 10000 with 9-month floor at 1000/month = 9000 floor -> only 1000 available
        src1 = _make_state("Source1", price=100, amount=10000, cash_floor_months=9)
        # Source2: 20000 with no floor
        src2 = _make_state("Source2", price=100, amount=20000, cash_floor_months=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Buyer", initial_price=100, initial_amount=5000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Source1", initial_price=100, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                                 cash_floor_months=9),
                InvestmentBucket(name="Source2", initial_price=100, initial_amount=20000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
            ],
        )

        execute_rebalance([buyer, src1, src2], 1000, {}, config, 0)

        # Source1 should keep at least 9000 (9 * 1000)
        assert src1.amount >= 8999

    def test_falls_back_to_priority_order_when_all_losing(self):
        """When all sources are losing, sell in user-defined priority order."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=20.0,
            source_buckets=["PriorityFirst", "PrioritySecond"],
        )
        buyer = _make_state("Buyer", price=100, amount=1000, triggers=[trigger])
        # Both sources are losing (price < initial)
        src1 = _make_state("PriorityFirst", price=80, amount=50000, initial_price=100)
        src2 = _make_state("PrioritySecond", price=50, amount=50000, initial_price=100)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Buyer", initial_price=100, initial_amount=1000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="PriorityFirst", initial_price=100, initial_amount=50000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="PrioritySecond", initial_price=100, initial_amount=50000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
            ],
        )

        execute_rebalance([buyer, src1, src2], 0, {}, config, 0)

        assert buyer.amount_bought > 0
        # PriorityFirst should sell before PrioritySecond (list order preserved)
        assert src1.amount_sold > 0

    def test_discount_sells_all_available_from_sources(self):
        """Discount trigger should sell all available from sources down to floors."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.DISCOUNT.value,
            threshold_pct=5.0,
            source_buckets=["Source"],
        )
        # Discounted: price=80, target=110, discount=37.5% > 5%
        buyer = _make_state("Buyer", price=80, amount=5000,
                            initial_price=100, target_growth_pct=10, triggers=[trigger])
        source = _make_state("Source", price=100, amount=20000, cash_floor_months=5)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Buyer", initial_price=100, initial_amount=5000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Source", initial_price=100, initial_amount=20000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                                 cash_floor_months=5),
            ],
        )

        execute_rebalance([buyer, source], 1000, {}, config, 0)

        assert buyer.amount_bought > 0
        # Source should be sold down to floor (5 * 1000 = 5000)
        assert source.amount >= 4999  # small tolerance
        assert source.amount_sold > 0


class TestImplicitShareFloors:
    def test_source_not_sold_below_share_floor(self):
        """Source with share_below 20% trigger should not be sold below 20% portfolio share."""
        # Source has a share_below 20% trigger (making 20% its implicit floor)
        source_trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=20.0,
            source_buckets=["Other"],
        )
        buy_trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=50.0,
            source_buckets=["Source"],
        )
        # Buyer: small amount, wants to reach 50%
        buyer = _make_state("Buyer", price=100, amount=5000, triggers=[buy_trigger])
        # Source: 25% of portfolio, has 20% floor
        source = _make_state("Source", price=100, amount=25000, triggers=[source_trigger])
        # Other: padding
        other = _make_state("Other", price=100, amount=70000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Buyer", initial_price=100, initial_amount=5000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Source", initial_price=100, initial_amount=25000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Other", initial_price=100, initial_amount=70000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
            ],
        )

        execute_rebalance([buyer, source, other], 0, {}, config, 0)

        # Source should not go below 20% of portfolio
        total = buyer.amount + source.amount + other.amount
        source_share = source.amount / total * 100 if total > 0 else 0
        assert source_share >= 19.5  # tolerance for fees

    def test_target_not_bought_above_share_ceiling(self):
        """Target with share_exceeds 60% trigger should not be bought above 60% portfolio share."""
        # Buyer has a share_exceeds 60% trigger (making 60% its implicit ceiling)
        sell_trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.SHARE_EXCEEDS.value,
            threshold_pct=60.0,
            target_bucket="Source",
        )
        buy_trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=80.0,
            source_buckets=["Source"],
        )
        # Buyer at 55%, wants to reach 80% but ceiling is 60%
        buyer = _make_state("Buyer", price=100, amount=55000,
                            triggers=[sell_trigger, buy_trigger])
        source = _make_state("Source", price=100, amount=45000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Buyer", initial_price=100, initial_amount=55000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Source", initial_price=100, initial_amount=45000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
            ],
        )

        execute_rebalance([buyer, source], 0, {}, config, 0)

        # Buyer should not exceed 60% of portfolio
        total = buyer.amount + source.amount
        buyer_share = buyer.amount / total * 100 if total > 0 else 0
        assert buyer_share <= 60.5  # small tolerance

    def test_share_floor_respected_in_cash_pool_refill(self):
        """Cash pool refill should respect source's implicit share% floor."""
        source_trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=40.0,
            source_buckets=["Other"],
        )
        # Source has 40% floor, starts at 50%
        source = _make_state("Source", price=200, amount=50000,
                             initial_price=100, buy_sell_fee_pct=0,
                             triggers=[source_trigger])
        other = _make_state("Other", price=100, amount=50000,
                            initial_price=100, buy_sell_fee_pct=0)

        cash_pool = CashPoolState(amount=0, refill_trigger_months=12, refill_target_months=24, cash_floor_months=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            cash_pool=CashPool(initial_amount=0, refill_trigger_months=12, refill_target_months=24, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="Source", initial_price=100, initial_amount=50000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
                InvestmentBucket(name="Other", initial_price=100, initial_amount=50000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
            ],
        )

        execute_rebalance([source, other], 1000, {}, config, 0, cash_pool=cash_pool)

        # Source should not go below 40% of portfolio
        total = source.amount + other.amount
        source_share = source.amount / total * 100 if total > 0 else 0
        assert source_share >= 39.0  # tolerance

    def test_share_ceiling_respected_in_sell_trigger_target(self):
        """Sell trigger proceeds should not push target above its ceiling."""
        sell_trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=1.0,
            target_bucket="Target",
        )
        # Target has share_exceeds 60% trigger (ceiling)
        target_ceiling_trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.SHARE_EXCEEDS.value,
            threshold_pct=60.0,
            target_bucket="Seller",
        )
        # Seller: price doubled, will trigger take profit
        seller = _make_state("Seller", price=200, amount=30000,
                             initial_price=100, target_growth_pct=10,
                             triggers=[sell_trigger])
        # Target: already at 55% (55000/100000)
        target = _make_state("Target", price=1, amount=55000,
                             initial_price=1, triggers=[target_ceiling_trigger])
        # Padding
        padding = _make_state("Padding", price=100, amount=15000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Seller", initial_price=100, initial_amount=30000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Target", initial_price=1, initial_amount=55000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
                InvestmentBucket(name="Padding", initial_price=100, initial_amount=15000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5),
            ],
        )

        execute_rebalance([seller, target, padding], 0, {}, config, 0)

        # Target should not exceed 60% of portfolio
        total = seller.amount + target.amount + padding.amount
        target_share = target.amount / total * 100 if total > 0 else 0
        assert target_share <= 60.5  # small tolerance


class TestMultiSourceBackwardCompat:
    def test_target_bucket_auto_migrates_to_source_buckets(self):
        """Buy trigger with target_bucket and empty source_buckets should auto-migrate."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.DISCOUNT.value,
            threshold_pct=5.0,
            target_bucket="Cash",
        )
        assert trigger.source_buckets == ["Cash"]

    def test_source_buckets_not_overwritten_when_set(self):
        """If source_buckets is explicitly set, target_bucket should not overwrite it."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.DISCOUNT.value,
            threshold_pct=5.0,
            target_bucket="Cash",
            source_buckets=["Bonds", "Gold"],
        )
        assert trigger.source_buckets == ["Bonds", "Gold"]

    def test_roundtrip_with_source_buckets(self):
        """Config with source_buckets should serialize and deserialize correctly."""
        triggers = [
            BucketTrigger(
                trigger_type=TriggerType.BUY,
                subtype=BuySubtype.DISCOUNT.value,
                threshold_pct=10.0,
                source_buckets=["Cash", "Bonds"],
                period_months=12,
            ),
        ]
        config = SimConfig(
            period_years=5,
            expenses_currency="USD",
            buckets=[
                InvestmentBucket(
                    name="SP500", initial_price=100, initial_amount=50000,
                    growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                    triggers=triggers,
                ),
            ],
        )

        json_str = config.model_dump_json()
        loaded = SimConfig.model_validate_json(json_str)

        b = loaded.buckets[0]
        assert len(b.triggers) == 1
        assert b.triggers[0].source_buckets == ["Cash", "Bonds"]
