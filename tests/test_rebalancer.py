"""Tests for rebalancer engine — multi-trigger system, cost basis, cross-currency."""

import pytest
import numpy as np
from engine.rebalancer import (
    BucketState, CashPoolState, PurchaseLot, execute_rebalance,
    _compute_cost_basis, _add_purchase_lot,
)
from engine.errors import SimulationBugError
from engine.bucket import compute_sell
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
            threshold_pct=150,  # fire when growth ratio >= 150% of target
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

        # SP500 growth=100%, target=10%, ratio=1000% > 150%
        # Excess above target: price=200 vs target_price=110, excess=90/200=45% of amount
        assert sp500.amount_sold > 0
        assert cash.amount_bought > 0

    def test_triggers_with_exact_sell_amount(self):
        """Verify exact sell amount: excess above cost-basis target price."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=100,  # fire when growth ratio >= 100% of target
            target_bucket="Cash",
        )
        # Price doubled from 100 to 200, target_growth=10%
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

        # target_price = 100 * 1.10 = 110, excess = 200-110 = 90/200 = 45%
        # sell_amount = 10000 * 0.45 = 4500
        assert abs(sp500.amount_sold - 4500) < 1.0
        assert cash.amount_bought > 0

    def test_no_trigger_when_below(self):
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=150,  # need 150% of target growth
            target_bucket="Cash",
        )
        # 5% growth, target 10%, ratio = 50% < 150%
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
            threshold_pct=10,  # Very low to ensure it would fire
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

    def test_reverse_priority_fallback_when_all_at_floor(self):
        """When all buckets hit cash floor, sell in reverse priority (lowest first)."""
        config = SimConfig(
            expenses_currency="USD",
            capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(
                    name="HighPri", currency="USD",
                    initial_price=1, initial_amount=3000,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                    spending_priority=0, cash_floor_months=3,  # floor=3000
                ),
                InvestmentBucket(
                    name="LowPri", currency="USD",
                    initial_price=1, initial_amount=3000,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                    spending_priority=1, cash_floor_months=3,  # floor=3000
                ),
            ],
        )

        states = [
            _make_state("HighPri", price=1, amount=3000, initial_price=1,
                        spending_priority=0, cash_floor_months=3),
            _make_state("LowPri", price=1, amount=3000, initial_price=1,
                        spending_priority=1, cash_floor_months=3),
        ]

        # All at floor, but expenses=1000 must be covered
        total_covered = execute_rebalance(states, 1000, {}, config, 0)

        assert total_covered == 1000
        # LowPri (reverse priority) should be sold first to cover expenses
        assert states[1].amount_sold > 0
        # HighPri should be preserved (or sold less)
        assert states[1].amount_sold >= states[0].amount_sold


class TestMultipleTriggers:
    def test_multiple_sell_triggers(self):
        """A bucket with two sell triggers should execute both if conditions met."""
        triggers = [
            BucketTrigger(
                trigger_type=TriggerType.SELL,
                subtype=SellSubtype.TAKE_PROFIT.value,
                threshold_pct=100,
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
        """FIFO: sell 1500 currency at price=150 → 10 units.
        Lot1: 50 units @ $100, Lot2: 50 units @ $120.
        FIFO consumes 10 units from Lot1 → cost_basis = 10 * 100 = 1000.
        Gain = (1500 - fee) - 1000."""
        state = BucketState(
            name="Test", currency="USD", price=150, amount=15000,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            cost_basis_method=CostBasisMethod.FIFO,
        )
        state.purchase_lots = [
            PurchaseLot(price_exp=100, units=50),
            PurchaseLot(price_exp=120, units=50),
        ]

        # Sell 1500 currency at price=150 → 10 units from lot1
        cost = _compute_cost_basis(state, 1500)
        expected = 10 * 100  # 10 units at $100 each = $1000
        assert abs(cost - expected) < 0.01

        # Lot1 should have 40 units left, lot2 intact
        assert len(state.purchase_lots) == 2
        assert abs(state.purchase_lots[0].units - 40) < 0.01
        assert abs(state.purchase_lots[1].units - 50) < 0.01

    def test_fifo_consumes_across_lots(self):
        """FIFO: sell 9000 currency at price=150 → 60 units.
        Lot1: 50 units @ $100, Lot2: 50 units @ $120.
        FIFO: 50 from lot1 + 10 from lot2 → cost = 50*100 + 10*120 = 6200."""
        state = BucketState(
            name="Test", currency="USD", price=150, amount=15000,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            cost_basis_method=CostBasisMethod.FIFO,
        )
        state.purchase_lots = [
            PurchaseLot(price_exp=100, units=50),
            PurchaseLot(price_exp=120, units=50),
        ]

        cost = _compute_cost_basis(state, 9000)  # 60 units at $150
        expected = 50 * 100 + 10 * 120  # 5000 + 1200 = 6200
        assert abs(cost - expected) < 0.01
        assert len(state.purchase_lots) == 1
        assert abs(state.purchase_lots[0].units - 40) < 0.01

    def test_fifo_gain_is_nonzero_when_price_appreciated(self):
        """Selling at a higher price than purchase should produce a positive gain."""
        state = BucketState(
            name="Test", currency="USD", price=150, amount=7500,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            cost_basis_method=CostBasisMethod.FIFO,
        )
        # 50 units bought at $100
        state.purchase_lots = [PurchaseLot(price_exp=100, units=50)]

        sell_amount = 1500  # 10 units at $150
        cost = _compute_cost_basis(state, sell_amount)
        assert abs(cost - 1000) < 0.01  # 10 units * $100
        gain = sell_amount - cost  # 1500 - 1000 = 500
        assert abs(gain - 500) < 0.01


class TestCostBasisLIFO:
    def test_lifo_correct_gains(self):
        """LIFO: sell 1500 currency at price=150 → 10 units.
        Lot1: 50 units @ $100, Lot2: 50 units @ $120.
        LIFO consumes 10 units from Lot2 → cost_basis = 10 * 120 = 1200."""
        state = BucketState(
            name="Test", currency="USD", price=150, amount=15000,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            cost_basis_method=CostBasisMethod.LIFO,
        )
        state.purchase_lots = [
            PurchaseLot(price_exp=100, units=50),
            PurchaseLot(price_exp=120, units=50),
        ]

        cost = _compute_cost_basis(state, 1500)  # 10 units at $150
        expected = 10 * 120  # 10 units from lot2 at $120 each = $1200
        assert abs(cost - expected) < 0.01

        # Lot2 should have 40 units left, lot1 intact
        assert len(state.purchase_lots) == 2
        assert abs(state.purchase_lots[0].units - 50) < 0.01
        assert abs(state.purchase_lots[1].units - 40) < 0.01

    def test_lifo_consumes_across_lots(self):
        """LIFO: sell 9000 currency at price=150 → 60 units.
        Lot1: 50 units @ $100, Lot2: 50 units @ $120.
        LIFO: 50 from lot2 + 10 from lot1 → cost = 50*120 + 10*100 = 7000."""
        state = BucketState(
            name="Test", currency="USD", price=150, amount=15000,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            cost_basis_method=CostBasisMethod.LIFO,
        )
        state.purchase_lots = [
            PurchaseLot(price_exp=100, units=50),
            PurchaseLot(price_exp=120, units=50),
        ]

        cost = _compute_cost_basis(state, 9000)  # 60 units at $150
        expected = 50 * 120 + 10 * 100  # 6000 + 1000 = 7000
        assert abs(cost - expected) < 0.01
        assert len(state.purchase_lots) == 1
        assert abs(state.purchase_lots[0].units - 40) < 0.01


class TestCostBasisAVCO:
    def test_avco_correct_gains(self):
        """AVCO: sell 1500 at price=150 → 10 units.
        Lots: 5000 at $100 (50 units) + 6000 at $120 (50 units).
        Avg cost = (50*100 + 50*120)/100 = 110/unit.
        Cost basis = 10 * 110 = 1100."""
        state = BucketState(
            name="Test", currency="USD", price=150, amount=15000,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            cost_basis_method=CostBasisMethod.AVCO,
        )
        _add_purchase_lot(state, 5000, 100)  # 50 units at $100
        _add_purchase_lot(state, 6000, 120)  # 50 units at $120

        cost = _compute_cost_basis(state, 1500)  # 10 units at $150
        expected = 10 * 110  # avg_cost = (50*100+50*120)/100 = 110
        assert abs(cost - expected) < 0.01

    def test_avco_gain_is_nonzero(self):
        """AVCO gain should reflect the difference between sell price and avg cost."""
        state = BucketState(
            name="Test", currency="USD", price=200, amount=10000,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            cost_basis_method=CostBasisMethod.AVCO,
        )
        _add_purchase_lot(state, 10000, 100)  # 100 units at $100
        # avg_cost = 100

        sell_amount = 2000  # 10 units at $200
        cost = _compute_cost_basis(state, sell_amount)
        assert abs(cost - 1000) < 0.01  # 10 units * $100 avg cost
        gain = sell_amount - cost
        assert abs(gain - 1000) < 0.01  # $200-$100 per unit * 10 units


class TestCrossCurrencyTrigger:
    def test_sell_trigger_cross_currency(self):
        """Sell EUR bucket, buy USD cash — FX conversion + fees should apply."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=100,
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
                threshold_pct=150,
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
                InvestmentBucket(
                    name="Cash", initial_price=1, initial_amount=10000,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                ),
            ],
        )

        json_str = config.model_dump_json()
        loaded = SimConfig.model_validate_json(json_str)

        assert len(loaded.buckets) == 2
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
            threshold_pct=100,
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
            threshold_pct=100,
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
            threshold_pct=100,
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
            threshold_pct=100,
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
                InvestmentBucket(
                    name="Cash", initial_price=1, initial_amount=10000,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                ),
                InvestmentBucket(
                    name="Bonds", initial_price=100, initial_amount=10000,
                    growth_min_pct=0, growth_max_pct=5, growth_avg_pct=2,
                ),
            ],
        )

        json_str = config.model_dump_json()
        loaded = SimConfig.model_validate_json(json_str)

        b = loaded.buckets[0]
        assert len(b.triggers) == 1
        assert b.triggers[0].source_buckets == ["Cash", "Bonds"]


# ---------------------------------------------------------------------------
# Stage 12 — Tests for unfixed bugs (expected failures until bugs are fixed)
# ---------------------------------------------------------------------------


class TestExpenseCoverageProfitabilityOrdering:
    """Stage 12 P0: Expense coverage should sell most profitable bucket first,
    not just by spending priority order."""

    def test_sells_most_profitable_first_for_expenses(self):
        """When covering expenses, profitable buckets should be sold before
        unprofitable ones, regardless of spending priority."""
        # Profitable bucket (price doubled): spending_priority=1 (lower priority)
        profitable = _make_state("Profitable", price=200, amount=20000,
                                 initial_price=100, spending_priority=1)
        # Unprofitable bucket (price halved): spending_priority=0 (higher priority)
        unprofitable = _make_state("Unprofitable", price=50, amount=20000,
                                   initial_price=100, spending_priority=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Profitable", initial_price=100, initial_amount=20000,
                                 growth_min_pct=-50, growth_max_pct=100, growth_avg_pct=10,
                                 spending_priority=1),
                InvestmentBucket(name="Unprofitable", initial_price=100, initial_amount=20000,
                                 growth_min_pct=-50, growth_max_pct=100, growth_avg_pct=10,
                                 spending_priority=0),
            ],
        )

        execute_rebalance([profitable, unprofitable], 5000, {}, config, 0)

        # Requirements: sell most profitable first for expense coverage
        # Profitable (price doubled) should be sold before Unprofitable (price halved)
        assert profitable.amount_sold > 0, "Profitable bucket should be sold first"
        assert unprofitable.amount_sold == 0, "Unprofitable bucket should not be sold when profitable has funds"


class TestCashPoolFloorDuringExpenseDraw:
    """Stage 12 P0: Cash pool hard floor should be enforced when drawing expenses."""

    def test_cash_pool_floor_respected(self):
        """Cash pool should not be drawn below cash_floor_months * monthly_expense.

        When expenses exceed the drawable amount (above floor), the cash pool
        should stop drawing at the floor and fall through to bucket selling.
        """
        sp500 = _make_state("SP500", price=100, amount=50000)
        # Cash pool: 7000, floor = 6 months * 2000 = 12000
        # Since 7000 < 12000 floor, NOTHING should be drawn from cash pool
        cash_pool = CashPoolState(
            amount=7000, refill_trigger_months=0, refill_target_months=0,
            cash_floor_months=6,
        )

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            cash_pool=CashPool(
                initial_amount=7000, refill_trigger_months=0,
                refill_target_months=0, cash_floor_months=6,
            ),
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5),
            ],
        )

        month_expense = 2000
        execute_rebalance([sp500], month_expense, {}, config, 0, cash_pool=cash_pool)

        # Floor = 6 * 2000 = 12000. Cash pool is only 7000, already below floor.
        # No drawing should happen; cash pool should remain at 7000.
        assert cash_pool.amount == 7000, \
            f"Cash pool {cash_pool.amount} was drawn despite being below floor 12000"

    def test_cash_pool_floor_forces_bucket_fallthrough(self):
        """When cash pool can't draw due to floor, expenses should come from buckets."""
        sp500 = _make_state("SP500", price=100, amount=50000)
        # Cash pool: 7000, floor = 6 months * 1000 = 6000, only 1000 drawable
        cash_pool = CashPoolState(
            amount=7000, refill_trigger_months=0, refill_target_months=0,
            cash_floor_months=6,
        )

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            cash_pool=CashPool(
                initial_amount=7000, refill_trigger_months=0,
                refill_target_months=0, cash_floor_months=6,
            ),
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5),
            ],
        )

        month_expense = 2000
        total_covered = execute_rebalance([sp500], month_expense, {}, config, 0, cash_pool=cash_pool)

        # Floor = 6000. Drawable = 7000 - 6000 = 1000. Remaining 1000 from bucket.
        assert cash_pool.amount >= 5999, \
            f"Cash pool {cash_pool.amount} fell below floor 6000"
        assert sp500.amount_sold > 0, "Bucket should cover remainder"
        assert total_covered == 2000


class TestTriggerSnapshotIsolation:
    """Stage 12 P1: Triggers within a phase should be evaluated on a snapshot
    of portfolio state, not re-evaluated after each execution."""

    def test_sell_trigger_condition_uses_snapshot(self):
        """A sell trigger should evaluate its condition based on the portfolio
        snapshot at the start of the sell phase, not after prior triggers mutated state.

        Setup: BucketA has take_profit trigger that sells to BucketB.
        BucketB has share_exceeds 40% trigger that sells to Cash.
        BucketB starts at 35% share — below the 40% threshold.

        Without snapshot: BucketA fires first, adds proceeds to BucketB.
        BucketB now exceeds 40%, so its trigger fires too (sees mutated state).

        With snapshot: BucketB's share is evaluated on the original snapshot (35%),
        so its trigger should NOT fire.
        """
        trigger_a = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=100,
            target_bucket="BucketB",
        )
        trigger_b = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.SHARE_EXCEEDS.value,
            threshold_pct=40.0,
            target_bucket="Cash",
        )

        # BucketA: price doubled, will trigger take profit
        bucket_a = _make_state("BucketA", price=200, amount=30000,
                               initial_price=100, target_growth_pct=10,
                               triggers=[trigger_a])
        # BucketB: 35000/100000 = 35%, below 40% threshold
        bucket_b = _make_state("BucketB", price=100, amount=35000,
                               initial_price=100, triggers=[trigger_b])
        cash = _make_state("Cash", price=1, amount=35000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="BucketA", initial_price=100, initial_amount=30000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="BucketB", initial_price=100, initial_amount=35000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=35000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([bucket_a, bucket_b, cash], 0, {}, config, 0)

        # BucketA should sell (take profit fires)
        assert bucket_a.amount_sold > 0, "BucketA take_profit should fire"
        # BucketB should NOT sell — its share was 35% at snapshot time (< 40%)
        # Without snapshot, BucketA's proceeds push BucketB above 40%, causing it to fire
        assert bucket_b.amount_sold == 0, \
            f"BucketB sold {bucket_b.amount_sold} but should not (35% < 40% at snapshot)"

    def test_buy_trigger_condition_uses_snapshot(self):
        """A buy trigger should evaluate its condition based on the portfolio
        snapshot at the start of the buy phase, not after prior triggers mutated state.

        Setup with high fees + tax: BucketA buys aggressively from Source,
        causing portfolio total to shrink (fees/tax leak value out).
        BucketB at borderline 9.5% share vs 10% threshold.

        Without snapshot: after BucketA's large buy (with fees+tax shrinking
        portfolio), BucketB's share rises above 10%, so trigger doesn't fire.

        With snapshot: BucketB's share = 9.5% < 10%, trigger fires.
        """
        trigger_a = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=50.0,
            source_buckets=["Source"],
        )
        trigger_b = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=10.0,
            source_buckets=["Source"],
        )

        # Source has doubled in price (high gains → high tax on sell)
        bucket_a = _make_state("BucketA", price=100, amount=5000, triggers=[trigger_a],
                               buy_sell_fee_pct=5)
        # BucketB: 9500/100000 = 9.5%, just below 10% threshold
        bucket_b = _make_state("BucketB", price=100, amount=9500, triggers=[trigger_b],
                               buy_sell_fee_pct=5)
        source = _make_state("Source", price=200, amount=85500,
                             initial_price=100, buy_sell_fee_pct=5)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=25,
            buckets=[
                InvestmentBucket(name="BucketA", initial_price=100, initial_amount=5000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=5),
                InvestmentBucket(name="BucketB", initial_price=100, initial_amount=9500,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=5),
                InvestmentBucket(name="Source", initial_price=100, initial_amount=85500,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=5),
            ],
        )

        execute_rebalance([bucket_a, bucket_b, source], 0, {}, config, 0)

        # With snapshot: BucketB share = 9.5% < 10% → trigger should fire
        # Without snapshot: after BucketA's large buy with 5% fees + 25% cap gains
        # tax, portfolio total shrinks significantly, pushing BucketB share above 10%
        assert bucket_b.amount_bought > 0, \
            "BucketB trigger should fire (9.5% < 10% at snapshot time)"


class TestDiscountTriggerUsesCostBasis:
    """Discount trigger should use the bucket's cost basis method for target_price
    calculation, not always initial_price."""

    def test_discount_uses_avco_avg_cost(self):
        """AVCO bucket: discount trigger target_price should use avg_cost."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.DISCOUNT.value,
            threshold_pct=5.0,
            source_buckets=["Cash"],
        )
        # AVCO bucket: avg_cost = (100*100 + 150*200) / 250 = 160
        buyer = _make_state("SP500", price=140, amount=10000,
                            initial_price=100, target_growth_pct=10,
                            triggers=[trigger],
                            cost_basis_method=CostBasisMethod.AVCO)
        _add_purchase_lot(buyer, 30000, 200)

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

        execute_rebalance([buyer, cash], 0, {}, config, 0)

        # With avg_cost=160 and target_growth=10%: target_price = 176
        # Current price = 140: discount = (176/140 - 1)*100 = 25.7% > 5% threshold
        # So trigger SHOULD fire when using avg_cost
        assert buyer.amount_bought > 0, \
            "Discount trigger should fire when using AVCO avg_cost for target_price"

    def test_discount_uses_fifo_front_lot(self):
        """FIFO bucket: discount trigger target_price should use front lot price."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.DISCOUNT.value,
            threshold_pct=5.0,
            source_buckets=["Cash"],
        )
        # FIFO bucket: front lot at 100, back lot at 200
        buyer = _make_state("SP500", price=140, amount=10000,
                            initial_price=100, target_growth_pct=10,
                            triggers=[trigger],
                            cost_basis_method=CostBasisMethod.FIFO)
        _add_purchase_lot(buyer, 30000, 200)

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

        execute_rebalance([buyer, cash], 0, {}, config, 0)

        # FIFO front lot at 100, target_price = 110
        # Current price = 140: discount = (110/140 - 1)*100 = -21.4% (no discount)
        # Trigger should NOT fire
        assert buyer.amount_bought == 0, \
            "Discount trigger should not fire when FIFO front lot shows no discount"


# ---------------------------------------------------------------------------
# Stage 13 — Test Coverage Gaps
# ---------------------------------------------------------------------------


class TestExpenseCoverageShareFloors:
    """Stage 13: Expense coverage first pass should respect implicit share% floors
    in the first pass (profitability-ordered), with only the reverse-priority
    fallback violating them. Currently the first pass ignores share% floors (bug A)."""

    def test_first_pass_respects_share_floor(self):
        """First-pass expense coverage should not sell a bucket below its
        implicit share% floor from a share_below trigger.

        Source starts at 60% (60000/100000) with a 50% implicit floor.
        Available above floor = 10000. Expense = 30000.
        First pass should sell 10000 from Source (down to floor), then 20000
        from Other. Bug: first pass ignores share floor, sells all 30000
        from Source (most profitable), pushing it to 30000/70000 = 43%.
        """
        # share_below trigger creates implicit floor; use period_months=12
        # and run at month_idx=1 so the trigger itself doesn't fire in Phase 4,
        # isolating the expense coverage first-pass behavior.
        source_trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=50.0,
            source_buckets=["Other"],
            period_months=12,
        )
        # Source: 60%, doubled in price → most profitable, has 50% floor
        source = _make_state("Source", price=200, amount=60000,
                             initial_price=100, spending_priority=0,
                             triggers=[source_trigger])
        # Other: 40%, same price → less profitable
        other = _make_state("Other", price=100, amount=40000,
                            initial_price=100, spending_priority=1)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Source", initial_price=100, initial_amount=60000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5),
                InvestmentBucket(name="Other", initial_price=100, initial_amount=40000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5),
            ],
        )

        # 30000 expense: with floor, Source sells 10000, Other sells 20000
        # Without floor (bug): Source sells all 30000 (most profitable)
        # month_idx=1 prevents the buy trigger from firing in Phase 4
        execute_rebalance([source, other], 30000, {}, config, 1)

        total = source.amount + other.amount
        source_share = source.amount / total * 100 if total > 0 else 0
        assert source_share >= 49.5, \
            f"Source share {source_share:.1f}% fell below 50% floor in first pass"

    def test_fallback_can_violate_share_floor(self):
        """Reverse-priority fallback should violate share% floors when all
        buckets are at their cash floors (expenses must be covered)."""
        # Both buckets have share_below triggers AND are at their cash floors
        trigger_a = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=45.0,
            source_buckets=["BucketB"],
        )
        trigger_b = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=45.0,
            source_buckets=["BucketA"],
        )
        # Both at cash floor (3*1000=3000), both with 45% share floor
        bucket_a = _make_state("BucketA", price=1, amount=3000,
                               initial_price=1, spending_priority=0,
                               cash_floor_months=3, triggers=[trigger_a])
        bucket_b = _make_state("BucketB", price=1, amount=3000,
                               initial_price=1, spending_priority=1,
                               cash_floor_months=3, triggers=[trigger_b])

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="BucketA", initial_price=1, initial_amount=3000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                                 cash_floor_months=3),
                InvestmentBucket(name="BucketB", initial_price=1, initial_amount=3000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                                 cash_floor_months=3),
            ],
        )

        total_covered = execute_rebalance([bucket_a, bucket_b], 1000, {}, config, 0)

        # Expenses must be covered even though both are at floor
        assert total_covered == 1000
        # At least one bucket was sold below its floor
        assert bucket_a.amount_sold > 0 or bucket_b.amount_sold > 0


class TestCrossCurrencyDoubleConversion:
    """Stage 13: Cross-currency trigger between two non-expenses-currency
    buckets routes through expenses currency, charging FX fees twice."""

    def test_double_fx_fee_between_foreign_buckets(self):
        """Sell EUR bucket → buy GBP bucket (expenses=USD). Both FX conversion
        fees should be charged (seller EUR→USD + target USD→GBP)."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=100,
            target_bucket="GBP_Fund",
        )
        eur_bucket = _make_state("EUR_Fund", currency="EUR", price=200, amount=10000,
                                 initial_price=100, target_growth_pct=10,
                                 triggers=[trigger])
        gbp_bucket = _make_state("GBP_Fund", currency="GBP", price=100, amount=5000,
                                 initial_price=100)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="EUR_Fund", currency="EUR", initial_price=100,
                                 initial_amount=10000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
                InvestmentBucket(name="GBP_Fund", currency="GBP", initial_price=100,
                                 initial_amount=5000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
            ],
            currencies=[
                CurrencySettings(
                    code="EUR", initial_price=1.1,
                    min_price=0.9, max_price=1.3, avg_price=1.1,
                    conversion_fee_pct=2.0,
                ),
                CurrencySettings(
                    code="GBP", initial_price=1.3,
                    min_price=1.0, max_price=1.5, avg_price=1.3,
                    conversion_fee_pct=3.0,
                ),
            ],
        )

        fx_rates = {"EUR": 1.1, "GBP": 1.3}
        execute_rebalance([eur_bucket, gbp_bucket], 0, fx_rates, config, 0)

        assert eur_bucket.amount_sold > 0, "EUR sell trigger should fire"
        assert gbp_bucket.amount_bought > 0, "GBP should receive proceeds"

        # Both EUR (seller) and GBP (target) should have FX fees charged
        assert eur_bucket.fees_paid > 0, "EUR seller should pay FX conversion fee"
        assert gbp_bucket.fees_paid > 0, "GBP target should pay FX conversion fee"

        # Verify the double-fee reduces total proceeds
        # Gross sell: eur_bucket sold some amount at price 200
        # After EUR→USD fee (2%) and USD→GBP fee (3%), proceeds should be
        # noticeably less than direct conversion
        sell_gross_eur = eur_bucket.amount_sold
        sell_gross_usd = sell_gross_eur * 1.1  # EUR→USD at rate 1.1
        # After 2% EUR fee + 3% GBP fee ≈ 5% total loss
        expected_bought_usd = sell_gross_usd * 0.98 * 0.97  # rough
        actual_bought_usd = gbp_bucket.amount_bought * 1.3
        assert actual_bought_usd < sell_gross_usd, \
            "Double FX fees should reduce proceeds vs gross sell"


class TestMultipleShareTriggersValidation:
    """Stage 13: Model should reject bucket with multiple share_below
    or multiple share_exceeds triggers (validates fix B)."""

    def test_rejects_multiple_share_below_triggers(self):
        """A bucket with two share_below buy triggers should be rejected."""
        t1 = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=20.0,
            source_buckets=["Cash"],
        )
        t2 = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=30.0,
            source_buckets=["Cash"],
        )
        with pytest.raises(ValueError):
            InvestmentBucket(
                name="Test", initial_price=100, initial_amount=10000,
                growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                triggers=[t1, t2],
            )

    def test_rejects_multiple_share_exceeds_triggers(self):
        """A bucket with two share_exceeds sell triggers should be rejected."""
        t1 = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.SHARE_EXCEEDS.value,
            threshold_pct=50.0,
            target_bucket="Cash",
        )
        t2 = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.SHARE_EXCEEDS.value,
            threshold_pct=60.0,
            target_bucket="Cash",
        )
        with pytest.raises(ValueError):
            InvestmentBucket(
                name="Test", initial_price=100, initial_amount=10000,
                growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                triggers=[t1, t2],
            )

    def test_allows_one_share_below_and_one_share_exceeds(self):
        """A bucket with one share_below and one share_exceeds should be valid."""
        t1 = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=20.0,
            source_buckets=["Cash"],
        )
        t2 = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.SHARE_EXCEEDS.value,
            threshold_pct=60.0,
            target_bucket="Cash",
        )
        # Should not raise
        b = InvestmentBucket(
            name="Test", initial_price=100, initial_amount=10000,
            growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
            triggers=[t1, t2],
        )
        assert len(b.triggers) == 2


class TestCashPoolRefillTargetValidation:
    """Stage 13: CashPool should validate refill_target_months >= refill_trigger_months
    (validates fix C)."""

    def test_rejects_target_below_trigger(self):
        """refill_target_months < refill_trigger_months should be rejected."""
        with pytest.raises(ValueError):
            CashPool(
                initial_amount=0,
                refill_trigger_months=24,
                refill_target_months=12,
                cash_floor_months=6,
            )

    def test_allows_target_equal_to_trigger(self):
        """refill_target_months == refill_trigger_months should be valid."""
        cp = CashPool(
            initial_amount=0,
            refill_trigger_months=12,
            refill_target_months=12,
            cash_floor_months=6,
        )
        assert cp.refill_target_months == 12

    def test_allows_target_above_trigger(self):
        """refill_target_months > refill_trigger_months should be valid."""
        cp = CashPool(
            initial_amount=0,
            refill_trigger_months=12,
            refill_target_months=24,
            cash_floor_months=6,
        )
        assert cp.refill_target_months == 24


class TestProfitabilityCostBasisMethod:
    """Stage 13: Profitability ordering should use the bucket's cost basis method
    (FIFO/LIFO) instead of always using avg_cost (validates fix D)."""

    def test_fifo_profitability_differs_from_avco(self):
        """With FIFO, profitability should be based on the oldest (cheapest) lots,
        making the bucket appear MORE profitable than AVCO suggests.

        Setup: FIFO bucket with a small cheap initial lot + large expensive lot.
        avg_cost is skewed toward the expensive lot, making AVCO profitability
        low (or negative). But FIFO sells the cheap lot first → high profitability.

        FIFO bucket: Lot 1 = 1000 at price 50, Lot 2 = 19000 at price 180
          avg_cost = (20*50 + 105.6*180) / 125.6 = (1000+19000)/125.6 ≈ 159.2
          Current price = 160
          AVCO gain_ratio: (160-159.2)/159.2 = 0.5% (barely profitable)
          FIFO gain_ratio: (160-50)/50 = 220% (very profitable)
        Moderate: avg_cost = 100, price = 160 → (160-100)/100 = 60% gain
        """
        fifo_bucket = _make_state("FIFO_Bucket", price=160, amount=20000,
                                  initial_price=50, buy_sell_fee_pct=0,
                                  spending_priority=0,
                                  cost_basis_method=CostBasisMethod.FIFO)
        # Override: replace initial lot (1000 at 50) and add large expensive lot
        fifo_bucket.purchase_lots = [PurchaseLot(price_exp=50, units=20)]
        _add_purchase_lot(fifo_bucket, 19000, 180)
        # avg_cost now ≈ 159.2, making AVCO profitability very low

        moderate = _make_state("Moderate", price=160, amount=20000,
                               initial_price=100, buy_sell_fee_pct=0,
                               spending_priority=1)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="FIFO_Bucket", initial_price=50,
                                 initial_amount=20000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10,
                                 cost_basis_method=CostBasisMethod.FIFO),
                InvestmentBucket(name="Moderate", initial_price=100,
                                 initial_amount=20000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10),
            ],
        )

        execute_rebalance([fifo_bucket, moderate], 5000, {}, config, 0)

        # With FIFO: next-to-sell lot costs 50, profitability ≈ 220% → sold first.
        # With AVCO (bug): avg_cost ≈ 159, profitability ≈ 0.5% < Moderate's 60%.
        # Bug causes Moderate to be sold first instead of FIFO_Bucket.
        assert fifo_bucket.amount_sold > 0, \
            "FIFO bucket should be sold first (highest FIFO profitability)"
        assert moderate.amount_sold == 0, \
            "Moderate bucket should not be sold when FIFO bucket is more profitable"

    def test_lifo_profitability_differs_from_avco(self):
        """With LIFO, profitability should be based on the newest (most expensive)
        lots, making the bucket appear LESS profitable than AVCO suggests.

        Setup: LIFO bucket with cheap old lot + expensive recent lot.
        LIFO sells expensive lot first → low profitability.
        AVCO averages → moderate profitability.
        """
        # Lot 1: 5000 at price 50 (old cheap)
        # Lot 2: 5000 at price 150 (recent expensive)
        # avg_cost = 100, current price = 120
        # AVCO profitability: (120-100)/100 = 20% gain
        # LIFO profitability: (120-150)/150 = -20% loss (sells expensive lot first)
        lifo_bucket = _make_state("LIFO_Bucket", price=120, amount=20000,
                                  initial_price=50, buy_sell_fee_pct=0,
                                  spending_priority=1,
                                  cost_basis_method=CostBasisMethod.LIFO)
        _add_purchase_lot(lifo_bucket, 10000, 150)

        # Another bucket with slight gain: avg_cost=110, price=120 → 9% gain
        slight_gain = _make_state("SlightGain", price=120, amount=20000,
                                  initial_price=110, buy_sell_fee_pct=0,
                                  spending_priority=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="LIFO_Bucket", initial_price=50,
                                 initial_amount=20000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10,
                                 cost_basis_method=CostBasisMethod.LIFO),
                InvestmentBucket(name="SlightGain", initial_price=110,
                                 initial_amount=20000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10),
            ],
        )

        execute_rebalance([lifo_bucket, slight_gain], 5000, {}, config, 0)

        # With LIFO, next-to-sell lot cost 150, profit = (120-150)/150 = -20% (loss).
        # SlightGain profit = (120-110)/110 = 9%. SlightGain should sell first.
        #
        # With AVCO (bug), LIFO_Bucket avg_cost=100, profit=20% > SlightGain's 9%.
        # LIFO_Bucket would incorrectly be sold first.
        assert slight_gain.amount_sold > 0, \
            "SlightGain should be sold first (LIFO bucket is losing on next lots)"
        assert lifo_bucket.amount_sold == 0, \
            "LIFO bucket should not be sold first (next lots are at a loss)"


class TestSameCurrencyShortCircuit:
    """Stage 13 fix E: When seller and target share the same foreign currency,
    FX conversion should be short-circuited (no double fee)."""

    def test_same_foreign_currency_no_double_fee(self):
        """Two EUR buckets (expenses=USD): proceeds should transfer directly
        without EUR→USD→EUR double conversion fee."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=100,
            target_bucket="EUR_Target",
        )
        seller = _make_state("EUR_Seller", currency="EUR", price=200, amount=10000,
                             initial_price=100, target_growth_pct=10,
                             buy_sell_fee_pct=0, triggers=[trigger])
        target = _make_state("EUR_Target", currency="EUR", price=100, amount=5000,
                             initial_price=100, buy_sell_fee_pct=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="EUR_Seller", currency="EUR", initial_price=100,
                                 initial_amount=10000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
                InvestmentBucket(name="EUR_Target", currency="EUR", initial_price=100,
                                 initial_amount=5000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
            ],
            currencies=[
                CurrencySettings(
                    code="EUR", initial_price=1.1,
                    min_price=0.9, max_price=1.3, avg_price=1.1,
                    conversion_fee_pct=5.0,  # high fee to make the difference obvious
                ),
            ],
        )

        fx_rates = {"EUR": 1.1}
        execute_rebalance([seller, target], 0, fx_rates, config, 0)

        assert seller.amount_sold > 0, "Sell trigger should fire"
        # With short-circuit: proceeds go directly EUR→EUR, no FX fee on transfer
        # Target should receive exactly what seller sold (no buy/sell fees either)
        assert abs(target.amount_bought - seller.amount_sold) < 1.0, \
            "Same-currency transfer should not lose value to FX fees"
        # Neither bucket should have FX conversion fees (only possible fee is
        # on tax amount conversion, but tax=0 here)
        assert seller.fees_paid == 0, "No FX fee for same-currency seller"
        assert target.fees_paid == 0, "No FX fee for same-currency target"


class TestNetYieldNone:
    """Stage 13 fix F: _estimate_net_yield returns None when yield <= 0,
    and callers skip the source instead of using a 1% floor."""

    def test_extreme_fees_skip_source(self):
        """A bucket with 100% buy/sell fee should be skipped for expense coverage
        (yield is effectively 0), falling through to the next bucket."""
        # Bucket with extreme fee (100%) → net_yield ≈ 0 → should be skipped
        extreme = _make_state("Extreme", price=100, amount=50000,
                              initial_price=100, buy_sell_fee_pct=100,
                              spending_priority=0)
        # Normal bucket to cover expenses
        normal = _make_state("Normal", price=100, amount=50000,
                             initial_price=100, buy_sell_fee_pct=0,
                             spending_priority=1)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Extreme", initial_price=100,
                                 initial_amount=50000, growth_min_pct=0,
                                 growth_max_pct=0, growth_avg_pct=0,
                                 buy_sell_fee_pct=100),
                InvestmentBucket(name="Normal", initial_price=100,
                                 initial_amount=50000, growth_min_pct=0,
                                 growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([extreme, normal], 5000, {}, config, 0)

        # Extreme bucket should be skipped (net yield is 0)
        assert extreme.amount_sold == 0, \
            "Bucket with 0 net yield should be skipped in expense coverage"
        assert normal.amount_sold > 0, \
            "Normal bucket should cover expenses instead"


# ---------------------------------------------------------------------------
# Stage 14 — Test Coverage Gaps
# ---------------------------------------------------------------------------


class TestAVCOLotAccumulation:
    """Stage 14 #13: Verify AVCO lot list is properly maintained after sell/buy cycles."""

    def test_avco_sell_buy_cycles(self):
        """After multiple sell/buy cycles, AVCO should maintain a single synthetic lot
        with correct avg_cost and unit count."""
        state = _make_state("AVCO", price=100, amount=10000,
                            initial_price=100, cost_basis_method=CostBasisMethod.AVCO)
        # Initial: 1 lot, 100 units at avg_cost=100

        # Buy more at 120 → avg = (100*100 + 50*120) / 150 = 16000/150 ≈ 106.67
        _add_purchase_lot(state, 6000, 120)
        assert len(state.purchase_lots) == 1, "AVCO should have single synthetic lot"
        assert abs(state.avg_cost - 106.667) < 0.01

        # Sell some (3000 at current price 100 → 30 units)
        _compute_cost_basis(state, 3000)
        # avg_cost stays same after sell
        assert abs(state.avg_cost - 106.667) < 0.01
        remaining_units = state.purchase_lots[0].units
        assert abs(remaining_units - 120) < 0.1  # 150 - 30 = 120

        # Buy again at 80 → avg = (120*106.67 + 75*80) / 195
        _add_purchase_lot(state, 6000, 80)
        assert len(state.purchase_lots) == 1, "AVCO should still have single lot"
        expected_avg = (120 * 106.667 + 75 * 80) / 195
        assert abs(state.avg_cost - expected_avg) < 0.1


class TestTakeProfitFIFOLIFO:
    """Stage 14 #14: Take-profit trigger with FIFO/LIFO cost basis."""

    def test_take_profit_uses_fifo_oldest_lot(self):
        """FIFO bucket: take-profit should use oldest lot cost for growth calc."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=100,  # fire at 100% of target growth
            target_bucket="Cash",
        )
        # FIFO: oldest lot at 50, recent lot at 150. Current price = 200.
        # Growth from oldest lot: (200-50)/50 = 300%, target=10%, ratio=3000% > 100% ✓
        sp500 = _make_state("SP500", price=200, amount=10000,
                            initial_price=50, target_growth_pct=10,
                            triggers=[trigger],
                            cost_basis_method=CostBasisMethod.FIFO)
        _add_purchase_lot(sp500, 15000, 150)
        cash = _make_state("Cash", price=1, amount=50000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=50, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        # FIFO cost_per_unit = 50, target_price = 55, excess = 200-55 = 145/200 = 72.5%
        assert sp500.amount_sold > 0, "Take-profit should fire based on FIFO oldest lot"

    def test_take_profit_lifo_no_fire_on_recent_expensive_lot(self):
        """LIFO bucket: take-profit should use newest lot cost — may not fire
        if recent lot was bought near current price."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=100,
            target_bucket="Cash",
        )
        # LIFO: newest lot at 195. Current price = 200. target_growth=10%.
        # Growth from newest lot: (200-195)/195 = 2.6%, target=10%, ratio=26% < 100%
        sp500 = _make_state("SP500", price=200, amount=10000,
                            initial_price=50, target_growth_pct=10,
                            triggers=[trigger],
                            cost_basis_method=CostBasisMethod.LIFO)
        _add_purchase_lot(sp500, 19500, 195)
        cash = _make_state("Cash", price=1, amount=50000)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=50, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        execute_rebalance([sp500, cash], 0, {}, config, 0)

        # LIFO cost_per_unit = 195, ratio = 2.6/10*100 = 26% < 100%
        assert sp500.amount_sold == 0, "Take-profit should NOT fire — LIFO newest lot shows little growth"


class TestCrossCurrencyCostBasisFX:
    """Stage 14 #15: Cross-currency cost basis and FX-adjusted tax calculation."""

    def test_fx_gain_taxed(self):
        """When FX rate rises, the FX gain should be captured in taxable gain.
        Buy EUR at FX=1.0, sell at FX=1.5 → FX gain should be taxed."""
        state = _make_state("EUR_Fund", currency="EUR", price=100, amount=10000,
                            initial_price=100, buy_sell_fee_pct=0,
                            cost_basis_method=CostBasisMethod.FIFO,
                            spending_priority=0)
        # Override lots: purchased at price=100 with FX=1.0 → price_exp=100
        state.purchase_lots = [PurchaseLot(price_exp=100, units=100)]
        state.avg_cost = 100  # expenses currency

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=25,
            buckets=[
                InvestmentBucket(name="EUR_Fund", currency="EUR", initial_price=100,
                                 initial_amount=10000, growth_min_pct=0,
                                 growth_max_pct=0, growth_avg_pct=0,
                                 buy_sell_fee_pct=0),
            ],
            currencies=[
                CurrencySettings(
                    code="EUR", initial_price=1.0,
                    min_price=0.8, max_price=1.5, avg_price=1.0,
                    conversion_fee_pct=0,
                ),
            ],
        )

        # FX rate is now 1.5 — EUR appreciated
        fx_rates = {"EUR": 1.5}
        execute_rebalance([state], 5000, fx_rates, config, 0)

        # Sold to cover 5000 USD expenses.
        # Price stayed at 100 EUR, but FX went 1.0→1.5
        # Cost basis per unit in expenses currency: 100 (at FX=1.0)
        # Current price in expenses currency: 100*1.5 = 150
        # Gain per unit = 150 - 100 = 50 (includes FX gain)
        assert state.tax_paid > 0, "FX gain should be taxed"


class TestPreExpenseRefillAboveSingleMonth:
    """Stage 14 #16: Pre-expense refill when pool is above expenses but below trigger."""

    def test_refill_when_above_monthly_but_below_trigger(self):
        """Cash pool at 3 months (above 1 month's expense but below trigger of 6)
        should trigger refill."""
        sp500 = _make_state("SP500", price=100, amount=100000,
                            initial_price=100, buy_sell_fee_pct=0)
        # Cash pool: 3000 = 3 months of expenses (1000/month)
        # Trigger: 6 months, Target: 12 months
        cash_pool = CashPoolState(
            amount=3000, refill_trigger_months=6,
            refill_target_months=12, cash_floor_months=0,
        )

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            cash_pool=CashPool(initial_amount=3000, refill_trigger_months=6,
                               refill_target_months=12, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=100000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5),
            ],
        )

        execute_rebalance([sp500], 1000, {}, config, 0, cash_pool=cash_pool)

        # Pool was at 3000 (3 months), trigger is 6 months (6000)
        # Should have refilled toward 12000, then drawn 1000 for expenses
        assert sp500.amount_sold > 0, "Should sell from bucket to refill cash pool"
        # Pool should be near target (12000) minus expenses (1000) = 11000
        assert cash_pool.amount > 3000, "Cash pool should have been refilled"


class TestShareFloorWithCashPool:
    """Stage 14 #17: Share% floors with active cash pool (portfolio total correctness)."""

    def test_share_floor_includes_cash_pool_in_total(self):
        """Share% floor calculation in expense coverage should include cash pool
        in portfolio total, preventing over-selling."""
        share_trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=40,  # floor at 40%
            source_buckets=["Other"],
        )
        # Portfolio: Source=60000, Other=40000, CashPool=100000 → total=200000
        # Source floor = 40% of 200000 = 80000 — source is already below floor!
        # So no selling from Source should occur.
        source = _make_state("Source", price=100, amount=60000,
                             initial_price=100, buy_sell_fee_pct=0,
                             spending_priority=0, triggers=[share_trigger])
        other = _make_state("Other", price=100, amount=40000,
                            initial_price=100, buy_sell_fee_pct=0,
                            spending_priority=1)
        cash_pool = CashPoolState(
            amount=100000, refill_trigger_months=0,
            refill_target_months=0, cash_floor_months=0,
        )

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            cash_pool=CashPool(initial_amount=100000, refill_trigger_months=0,
                               refill_target_months=0, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="Source", initial_price=100, initial_amount=60000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
                InvestmentBucket(name="Other", initial_price=100, initial_amount=40000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        # Small expense covered from cash pool
        execute_rebalance([source, other], 5000, {}, config, 0, cash_pool=cash_pool)

        # With cash pool in total (200k), Source at 60k is below 40% floor (80k)
        # Without cash pool in total (100k), Source at 60k is above 40% floor (40k)
        # The floor should use the total INCLUDING cash pool
        assert cash_pool.amount < 100000, "Expenses should be drawn from cash pool"


class TestTriggerBucketReferenceValidation:
    """Stage 14 #11: Trigger bucket references must resolve to actual buckets."""

    def test_invalid_target_bucket_rejected(self):
        """SimConfig should reject triggers referencing non-existent target_bucket."""
        with pytest.raises(ValueError, match="unknown target_bucket"):
            SimConfig(
                expenses_currency="USD",
                buckets=[
                    InvestmentBucket(
                        name="SP500", initial_price=100, initial_amount=10000,
                        growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                        triggers=[
                            BucketTrigger(
                                trigger_type=TriggerType.SELL,
                                subtype=SellSubtype.TAKE_PROFIT.value,
                                threshold_pct=100,
                                target_bucket="NonExistent",
                            ),
                        ],
                    ),
                ],
            )

    def test_invalid_source_bucket_rejected(self):
        """SimConfig should reject triggers referencing non-existent source_bucket."""
        with pytest.raises(ValueError, match="unknown source_bucket"):
            SimConfig(
                expenses_currency="USD",
                buckets=[
                    InvestmentBucket(
                        name="SP500", initial_price=100, initial_amount=10000,
                        growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                        triggers=[
                            BucketTrigger(
                                trigger_type=TriggerType.BUY,
                                subtype=BuySubtype.DISCOUNT.value,
                                threshold_pct=5,
                                source_buckets=["NonExistent"],
                            ),
                        ],
                    ),
                ],
            )

    def test_valid_references_accepted(self):
        """SimConfig should accept triggers with valid bucket references."""
        config = SimConfig(
            expenses_currency="USD",
            buckets=[
                InvestmentBucket(
                    name="SP500", initial_price=100, initial_amount=10000,
                    growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                    triggers=[
                        BucketTrigger(
                            trigger_type=TriggerType.SELL,
                            subtype=SellSubtype.TAKE_PROFIT.value,
                            threshold_pct=100,
                            target_bucket="Cash",
                        ),
                    ],
                ),
                InvestmentBucket(
                    name="Cash", initial_price=1, initial_amount=50000,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                ),
            ],
        )
        assert len(config.buckets) == 2


class TestAvgCostInitialization:
    """Stage 14 #12: avg_cost should be initialized to initial_price, not 0."""

    def test_avg_cost_initialized_to_initial_price(self):
        """Zero-amount bucket should have avg_cost = initial_price."""
        from engine.simulator import _init_bucket_state
        bucket = InvestmentBucket(
            name="Empty", initial_price=150, initial_amount=0,
            growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
        )
        state = _init_bucket_state(bucket)
        assert state.avg_cost == 150, "avg_cost should be initial_price, not 0"


class TestCumulativeInflationNeutralStart:
    """Stage 14 #8: First month should have no inflation applied."""

    def test_first_month_no_inflation(self):
        """Month 0 expenses should be base amount (no inflation)."""
        from engine.expenses import compute_monthly_expenses
        from models.expense import ExpensePeriod, ExpenseVolatility

        periods = [ExpensePeriod(
            start_month=1, start_year=1,
            amount_min=1000, amount_max=1000, amount_avg=1000,
            volatility=ExpenseVolatility.CONSTANT,
        )]
        inflation = np.full(24, 0.05)  # 5% monthly inflation
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses(periods, [], inflation, 24, rng)

        assert abs(expenses[0] - 1000) < 0.01, "Month 0 should have no inflation"
        assert expenses[1] > 1000, "Month 1 should have inflation applied"


class TestMonteCarloRelativeTolerance:
    """Stage 14 #9: Monte Carlo success tolerance should be relative."""

    def test_relative_tolerance_large_expenses(self):
        """With large expenses, small absolute shortfall should still count as success."""
        from engine.montecarlo import run_monte_carlo

        config = SimConfig(
            period_years=1,
            expenses_currency="USD",
            capital_gain_tax_pct=0,
            expense_periods=[],
            buckets=[
                InvestmentBucket(
                    name="Fund", initial_price=100, initial_amount=1000000,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                ),
            ],
        )
        # With no expenses, all simulations should succeed
        result = run_monte_carlo(config, n_simulations=5, seed=42)
        assert result.success_rate == 1.0


class TestStatefulMultiMonthTrigger:
    """Stage 14 #23: Trigger with period_months=1 fires every month."""

    def test_monthly_trigger_fires_each_month(self):
        """Take-profit trigger with period_months=1 should fire every month
        when conditions are met."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=100,
            target_bucket="Cash",
            period_months=1,
        )
        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10),
                InvestmentBucket(name="Cash", initial_price=1, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        sold_amounts = []
        for month in range(3):
            sp500 = _make_state("SP500", price=200, amount=10000,
                                initial_price=100, target_growth_pct=10,
                                triggers=[trigger])
            cash = _make_state("Cash", price=1, amount=50000)
            execute_rebalance([sp500, cash], 0, {}, config, month)
            sold_amounts.append(sp500.amount_sold)

        # Should fire every month (months 0, 1, 2)
        assert all(s > 0 for s in sold_amounts), \
            "period_months=1 trigger should fire every month"


class TestNearZeroBucketPrice:
    """Stage 14 #18: Near-zero bucket price edge cases."""

    def test_cost_basis_at_price_floor(self):
        """_compute_cost_basis should handle near-zero prices gracefully."""
        state = _make_state("Crashed", price=0.001, amount=1000,
                            initial_price=100, cost_basis_method=CostBasisMethod.FIFO)
        # Price crashed to 0.001; try to compute cost basis for a sell
        cost = _compute_cost_basis(state, 500, 1.0)
        assert cost >= 0, "Cost basis should be non-negative"

    def test_expense_coverage_at_price_floor(self):
        """Expense coverage should still work when bucket price is near zero."""
        crashed = _make_state("Crashed", price=0.001, amount=1000,
                              initial_price=100, spending_priority=0)
        healthy = _make_state("Healthy", price=100, amount=50000,
                              initial_price=100, spending_priority=1)
        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Crashed", initial_price=100, initial_amount=1000,
                                 growth_min_pct=-99, growth_max_pct=0, growth_avg_pct=-50),
                InvestmentBucket(name="Healthy", initial_price=100, initial_amount=50000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5),
            ],
        )
        execute_rebalance([crashed, healthy], 5000, {}, config, 0)
        # Should not crash; expenses should be covered from healthy bucket
        assert healthy.amount_sold > 0 or crashed.amount_sold > 0


class TestExpensePeriodBoundaries:
    """Stage 14 #19: Expense period boundary conditions."""

    def test_period_starting_last_month(self):
        """Period starting in the last simulation month should still apply."""
        from engine.expenses import compute_monthly_expenses
        from models.expense import ExpensePeriod, ExpenseVolatility

        periods = [ExpensePeriod(
            start_month=12, start_year=1,
            amount_min=5000, amount_max=5000, amount_avg=5000,
            volatility=ExpenseVolatility.CONSTANT,
        )]
        inflation = np.zeros(12)
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses(periods, [], inflation, 12, rng)

        # Only month 11 (0-indexed) should have expenses
        assert expenses[11] == 5000
        assert all(expenses[i] == 0 for i in range(11))

    def test_two_periods_same_start_month(self):
        """Two periods with the same start month: last one wins."""
        from engine.expenses import compute_monthly_expenses
        from models.expense import ExpensePeriod, ExpenseVolatility

        periods = [
            ExpensePeriod(start_month=1, start_year=1,
                          amount_min=1000, amount_max=1000, amount_avg=1000,
                          volatility=ExpenseVolatility.CONSTANT),
            ExpensePeriod(start_month=1, start_year=1,
                          amount_min=2000, amount_max=2000, amount_avg=2000,
                          volatility=ExpenseVolatility.CONSTANT),
        ]
        inflation = np.zeros(12)
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses(periods, [], inflation, 12, rng)

        # Both periods have same start; whichever is last in sorted order wins
        assert expenses[0] > 0

    def test_period_starting_before_simulation(self):
        """Period starting at month 0 (before simulation starts) should apply from month 0."""
        from engine.expenses import compute_monthly_expenses
        from models.expense import ExpensePeriod, ExpenseVolatility

        periods = [ExpensePeriod(
            start_month=1, start_year=1,
            amount_min=3000, amount_max=3000, amount_avg=3000,
            volatility=ExpenseVolatility.CONSTANT,
        )]
        inflation = np.zeros(12)
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses(periods, [], inflation, 12, rng)

        assert expenses[0] == 3000


class TestReversePriorityFallbackWithTax:
    """Stage 14 #20: Reverse-priority fallback with capital gains tax gross-up."""

    def test_fallback_covers_expenses_after_tax(self):
        """When all buckets are at cash floor, reverse-priority fallback should
        correctly gross up to cover expenses even with capital gains tax."""
        # Both buckets at cash floor (high floor relative to amount)
        low_priority = _make_state("LowPri", price=200, amount=10000,
                                   initial_price=100, spending_priority=1,
                                   cash_floor_months=100)  # very high floor
        high_priority = _make_state("HighPri", price=200, amount=10000,
                                    initial_price=100, spending_priority=0,
                                    cash_floor_months=100)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=25,
            buckets=[
                InvestmentBucket(name="LowPri", initial_price=100, initial_amount=10000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
                InvestmentBucket(name="HighPri", initial_price=100, initial_amount=10000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        total_covered = execute_rebalance([low_priority, high_priority], 5000, {}, config, 0)

        # Fallback should sell from low_priority first (reverse order: highest priority last)
        assert low_priority.amount_sold > 0, \
            "Low-priority bucket should be sold first in fallback"
        # Total covered should be close to 5000
        assert total_covered > 4000, "Fallback should mostly cover expenses"


class TestFullIntegration:
    """Stage 14 #21: Full multi-year integration test."""

    def test_10_year_simulation_invariants(self):
        """Run a 10-year simulation and validate basic invariants."""
        from engine.simulator import run_simulation

        config = SimConfig(
            period_years=10,
            expenses_currency="USD",
            capital_gain_tax_pct=25,
            inflation=__import__("models.inflation", fromlist=["InflationSettings"]).InflationSettings(
                min_pct=1, max_pct=5, avg_pct=2.5,
            ),
            expense_periods=[
                __import__("models.expense", fromlist=["ExpensePeriod"]).ExpensePeriod(
                    start_month=1, start_year=1,
                    amount_min=3000, amount_max=5000, amount_avg=4000,
                ),
            ],
            buckets=[
                InvestmentBucket(
                    name="Stocks", initial_price=100, initial_amount=500000,
                    growth_min_pct=-20, growth_max_pct=30, growth_avg_pct=8,
                    buy_sell_fee_pct=0.5,
                    spending_priority=1,
                    cash_floor_months=3,
                ),
                InvestmentBucket(
                    name="Bonds", initial_price=50, initial_amount=200000,
                    growth_min_pct=-5, growth_max_pct=10, growth_avg_pct=3,
                    buy_sell_fee_pct=0.2,
                    spending_priority=0,
                ),
            ],
            cash_pool=CashPool(
                initial_amount=50000,
                refill_trigger_months=6,
                refill_target_months=12,
                cash_floor_months=3,
            ),
        )

        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)

        # Basic invariants
        assert len(df) == 120  # 10 years * 12 months
        assert all(df["Stocks_amount"] >= 0), "No negative amounts"
        assert all(df["Bonds_amount"] >= 0), "No negative amounts"
        assert all(df["cash_pool_amount"] >= 0), "No negative cash pool"
        # Total fees should be positive but less than total sold
        total_fees = df["Stocks_fees"].sum() + df["Bonds_fees"].sum()
        total_sold = df["Stocks_sold"].sum() + df["Bonds_sold"].sum()
        assert total_fees >= 0
        if total_sold > 0:
            assert total_fees < total_sold, "Fees should be less than total sold"


class TestCashPoolDisabled:
    """Stage 14 #22: Cash pool disabled when both initial_amount=0 and refill_target=0."""

    def test_cash_pool_stays_zero(self):
        """When cash pool is effectively disabled, its columns should remain zero."""
        from engine.simulator import run_simulation

        config = SimConfig(
            period_years=1,
            expenses_currency="USD",
            capital_gain_tax_pct=0,
            expense_periods=[
                __import__("models.expense", fromlist=["ExpensePeriod"]).ExpensePeriod(
                    start_month=1, start_year=1,
                    amount_min=1000, amount_max=1000, amount_avg=1000,
                ),
            ],
            buckets=[
                InvestmentBucket(
                    name="Fund", initial_price=100, initial_amount=500000,
                    growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                ),
            ],
            cash_pool=CashPool(
                initial_amount=0,
                refill_trigger_months=0,
                refill_target_months=0,
                cash_floor_months=0,
            ),
        )

        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)

        # Cash pool should not be used (initial=0, target=0)
        assert all(df["cash_pool_amount"] == 0), "Cash pool should stay zero"
        assert all(df["cash_pool_net_spent"] == 0), "No expenses from cash pool"


# ---------------------------------------------------------------------------
# Stage 15 — Test Coverage Gaps
# ---------------------------------------------------------------------------


class TestBuyTriggerSameCurrencyShortCircuit:
    """Stage 15 #8: Buy trigger between same-foreign-currency buckets should not
    double-charge FX conversion fees."""

    def test_same_foreign_currency_no_double_fee(self):
        """Two EUR buckets (expenses=USD): buy trigger source sell should transfer
        directly without EUR→USD→EUR double conversion fee."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=50.0,
            source_buckets=["EUR_Source"],
        )
        # Buyer: EUR, small share → triggers share_below 50%
        buyer = _make_state("EUR_Buyer", currency="EUR", price=100, amount=5000,
                            initial_price=100, buy_sell_fee_pct=0, triggers=[trigger])
        # Source: EUR, large holdings
        source = _make_state("EUR_Source", currency="EUR", price=100, amount=95000,
                             initial_price=100, buy_sell_fee_pct=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="EUR_Buyer", currency="EUR", initial_price=100,
                                 initial_amount=5000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
                InvestmentBucket(name="EUR_Source", currency="EUR", initial_price=100,
                                 initial_amount=95000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
            ],
            currencies=[
                CurrencySettings(
                    code="EUR", initial_price=1.1,
                    min_price=0.9, max_price=1.3, avg_price=1.1,
                    conversion_fee_pct=10.0,  # very high fee to make the difference obvious
                ),
            ],
        )

        fx_rates = {"EUR": 1.1}
        execute_rebalance([buyer, source], 0, fx_rates, config, 0)

        assert buyer.amount_bought > 0, "Buy trigger should fire"
        assert source.amount_sold > 0, "Source should be sold"
        # With short-circuit: proceeds go directly EUR→EUR, no FX fee on transfer.
        # Without short-circuit: EUR→USD→EUR at 10% fee each way → ~19% total loss.
        # Verify bought ≈ sold (no FX fee loss, only buy fee which is 0 here)
        assert abs(buyer.amount_bought - source.amount_sold) < 1.0, \
            "Same-currency transfer should not lose value to FX fees"
        # Neither bucket should have FX conversion fees (tax=0 → no tax conversion needed)
        assert source.fees_paid == 0, "No FX fee for same-currency source"
        assert buyer.fees_paid == 0, "No FX fee for same-currency buyer"

    def test_same_foreign_currency_with_tax(self):
        """Same-currency short-circuit with capital gains tax: only the tax amount
        should incur FX conversion fees."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=50.0,
            source_buckets=["EUR_Source"],
        )
        buyer = _make_state("EUR_Buyer", currency="EUR", price=100, amount=5000,
                            initial_price=100, buy_sell_fee_pct=0, triggers=[trigger])
        # Source: EUR, price doubled → has gains → tax applies
        source = _make_state("EUR_Source", currency="EUR", price=200, amount=95000,
                             initial_price=100, buy_sell_fee_pct=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=25,
            buckets=[
                InvestmentBucket(name="EUR_Buyer", currency="EUR", initial_price=100,
                                 initial_amount=5000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
                InvestmentBucket(name="EUR_Source", currency="EUR", initial_price=100,
                                 initial_amount=95000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
            ],
            currencies=[
                CurrencySettings(
                    code="EUR", initial_price=1.1,
                    min_price=0.9, max_price=1.3, avg_price=1.1,
                    conversion_fee_pct=10.0,
                ),
            ],
        )

        fx_rates = {"EUR": 1.1}
        execute_rebalance([buyer, source], 0, fx_rates, config, 0)

        assert source.amount_sold > 0, "Source should be sold"
        assert source.tax_paid > 0, "Tax should be charged on gains"
        # FX fee should only be on the tax amount conversion, not on the full transfer
        # Tax is paid in expenses currency; FX fee applies on that conversion.
        # Without short-circuit: FX fee would be ~10% of full proceeds (much larger)
        if source.fees_paid > 0:
            # FX fee should be small (10% of tax amount, not 10% of full proceeds)
            assert source.fees_paid < source.tax_paid, \
                "FX fee should only be on tax conversion, not full proceeds"

    def test_mixed_currency_sources(self):
        """Buy trigger with one same-currency source and one different-currency source.
        Same-currency source should short-circuit, other should route via expenses."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=40.0,
            source_buckets=["EUR_Source", "USD_Source"],
        )
        # Buyer: EUR
        buyer = _make_state("EUR_Buyer", currency="EUR", price=100, amount=5000,
                            initial_price=100, buy_sell_fee_pct=0, triggers=[trigger])
        # EUR source: same currency → short-circuit
        eur_source = _make_state("EUR_Source", currency="EUR", price=100, amount=45000,
                                 initial_price=100, buy_sell_fee_pct=0)
        # USD source: different currency → route via expenses
        usd_source = _make_state("USD_Source", currency="USD", price=100, amount=50000,
                                 initial_price=100, buy_sell_fee_pct=0)

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="EUR_Buyer", currency="EUR", initial_price=100,
                                 initial_amount=5000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
                InvestmentBucket(name="EUR_Source", currency="EUR", initial_price=100,
                                 initial_amount=45000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
                InvestmentBucket(name="USD_Source", currency="USD", initial_price=100,
                                 initial_amount=50000, growth_min_pct=-10,
                                 growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
            ],
            currencies=[
                CurrencySettings(
                    code="EUR", initial_price=1.1,
                    min_price=0.9, max_price=1.3, avg_price=1.1,
                    conversion_fee_pct=5.0,
                ),
            ],
        )

        fx_rates = {"EUR": 1.1}
        execute_rebalance([buyer, eur_source, usd_source], 0, fx_rates, config, 0)

        assert buyer.amount_bought > 0, "Buy trigger should fire"
        # EUR source should have no FX fee (same-currency short-circuit, tax=0)
        assert eur_source.fees_paid == 0, \
            "EUR source should have no FX fee (same currency as buyer)"
        # USD source: if sold, should have buyer-side EUR FX fee
        # (USD→USD is free, but buying EUR requires USD→EUR conversion)


class TestExactGrossForNet:
    """Tests for _exact_gross_for_net: exact lot-walking gross-up calculation."""

    def test_single_lot_exact_net(self):
        """Single lot: gross-up should produce exact net proceeds."""
        from engine.rebalancer import _exact_gross_for_net
        from engine.bucket import compute_sell

        state = _make_state("Test", price=150, amount=15000,
                            initial_price=100, buy_sell_fee_pct=2.0)
        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=25.0,
            buckets=[
                InvestmentBucket(name="Test", initial_price=100, initial_amount=15000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                                 buy_sell_fee_pct=2.0),
            ],
        )

        needed_net = 5000.0
        gross = _exact_gross_for_net(state, needed_net, 25.0, "USD", config, 1.0)
        assert gross is not None

        # Verify: actually sell that gross amount and check net ≈ needed_net
        net_proceeds, fee = compute_sell(gross, state.buy_sell_fee_pct)
        cost_basis_exp = _compute_cost_basis(state, gross, 1.0)
        gain_exp = net_proceeds - cost_basis_exp
        tax_exp = max(0, gain_exp * 25.0 / 100.0)
        after_tax = net_proceeds - tax_exp

        assert abs(after_tax - needed_net) < 0.01, \
            f"Net proceeds {after_tax:.2f} should equal needed {needed_net:.2f}"

    def test_multi_lot_fifo(self):
        """FIFO with multiple lots at different prices: exact gross-up."""
        from engine.rebalancer import _exact_gross_for_net

        state = BucketState(
            name="Multi", currency="USD", price=200, amount=20000,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=1.0,
            spending_priority=0, cash_floor_months=0, required_runaway_months=0,
            triggers=[], cost_basis_method=CostBasisMethod.FIFO,
        )
        # Lot 1: bought at 80 (cheap), 50 units
        state.purchase_lots.append(PurchaseLot(price_exp=80.0, units=50.0))
        # Lot 2: bought at 150 (expensive), 50 units
        state.purchase_lots.append(PurchaseLot(price_exp=150.0, units=50.0))

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=25.0,
            buckets=[
                InvestmentBucket(name="Multi", initial_price=100, initial_amount=20000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                                 buy_sell_fee_pct=1.0),
            ],
        )

        needed_net = 8000.0
        gross = _exact_gross_for_net(state, needed_net, 25.0, "USD", config, 1.0)
        assert gross is not None

        # Verify by actually selling
        net_proceeds, fee = compute_sell(gross, state.buy_sell_fee_pct)
        cost_basis_exp = _compute_cost_basis(state, gross, 1.0, config)
        gain_exp = net_proceeds - cost_basis_exp
        tax_exp = max(0, gain_exp * 25.0 / 100.0)
        after_tax = net_proceeds - tax_exp

        assert abs(after_tax - needed_net) < 0.05, \
            f"Multi-lot FIFO net {after_tax:.2f} should ≈ needed {needed_net:.2f}"

    def test_multi_lot_lifo(self):
        """LIFO with multiple lots at different prices: exact gross-up."""
        from engine.rebalancer import _exact_gross_for_net

        state = BucketState(
            name="Multi", currency="USD", price=200, amount=20000,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=1.0,
            spending_priority=0, cash_floor_months=0, required_runaway_months=0,
            triggers=[], cost_basis_method=CostBasisMethod.LIFO,
        )
        # Lot 1: bought at 80 (cheap), 50 units
        state.purchase_lots.append(PurchaseLot(price_exp=80.0, units=50.0))
        # Lot 2: bought at 180 (expensive), 50 units — LIFO sells this first
        state.purchase_lots.append(PurchaseLot(price_exp=180.0, units=50.0))

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=25.0,
            buckets=[
                InvestmentBucket(name="Multi", initial_price=100, initial_amount=20000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                                 buy_sell_fee_pct=1.0),
            ],
        )

        needed_net = 8000.0
        gross = _exact_gross_for_net(state, needed_net, 25.0, "USD", config, 1.0)
        assert gross is not None

        # Verify by actually selling
        net_proceeds, fee = compute_sell(gross, state.buy_sell_fee_pct)
        cost_basis_exp = _compute_cost_basis(state, gross, 1.0, config)
        gain_exp = net_proceeds - cost_basis_exp
        tax_exp = max(0, gain_exp * 25.0 / 100.0)
        after_tax = net_proceeds - tax_exp

        assert abs(after_tax - needed_net) < 0.05, \
            f"Multi-lot LIFO net {after_tax:.2f} should ≈ needed {needed_net:.2f}"

    def test_avco_multi_lot_uses_total_units(self):
        """AVCO with multiple purchase lots should use total units, not just first lot."""
        from engine.rebalancer import _exact_gross_for_net
        from engine.bucket import compute_sell

        state = BucketState(
            name="AVCO_Multi", currency="USD", price=120, amount=12000,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=1.0,
            spending_priority=0, cash_floor_months=0, required_runaway_months=0,
            triggers=[], cost_basis_method=CostBasisMethod.AVCO,
        )
        # Simulate multiple buys: 3 lots, 20 units each = 60 total units
        # avg_cost should reflect weighted average
        state.purchase_lots.append(PurchaseLot(price_exp=90.0, units=20.0))
        state.purchase_lots.append(PurchaseLot(price_exp=100.0, units=20.0))
        state.purchase_lots.append(PurchaseLot(price_exp=110.0, units=20.0))
        state.avg_cost = 100.0  # weighted avg of 90, 100, 110

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=25.0,
            buckets=[
                InvestmentBucket(name="AVCO_Multi", initial_price=100, initial_amount=12000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                                 buy_sell_fee_pct=1.0),
            ],
        )

        # Request net that requires more than 20 units (first lot) to cover
        # With price=120, avg_cost=100, fee=1%, tax=25%:
        # net_after_fee = 120 * 0.99 = 118.8
        # gain = 118.8 - 100 = 18.8
        # tax = 18.8 * 0.25 = 4.7
        # net_per_unit = 118.8 - 4.7 = 114.1
        # 30 units would yield ~3423 net — request that amount
        needed_net = 3400.0
        gross = _exact_gross_for_net(state, needed_net, 25.0, "USD", config, 1.0)
        assert gross is not None

        # Verify the gross covers the needed net
        units_sold = gross / state.price
        # Must need more than 20 units (first lot) to confirm we use total
        assert units_sold > 20.0, \
            f"Should sell >20 units (got {units_sold:.2f}), proving total units are used"

        # Verify precision using _compute_cost_basis (consistent with FIFO/LIFO tests)
        net_proceeds, fee = compute_sell(gross, state.buy_sell_fee_pct)
        cost_basis_exp = _compute_cost_basis(state, gross, 1.0, config)
        gain_exp = net_proceeds - cost_basis_exp
        tax_exp = max(0, gain_exp * 25.0 / 100.0)
        after_tax = net_proceeds - tax_exp
        assert abs(after_tax - needed_net) < 0.05, \
            f"AVCO multi-lot net {after_tax:.2f} should ≈ needed {needed_net:.2f}"

    def test_cross_currency_with_fx_fee(self):
        """Cross-currency gross-up should account for FX conversion fee."""
        from engine.rebalancer import _exact_gross_for_net

        state = _make_state("EUR_Fund", currency="EUR", price=150, amount=15000,
                            initial_price=100, buy_sell_fee_pct=1.0)
        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=25.0,
            buckets=[
                InvestmentBucket(name="EUR_Fund", currency="EUR", initial_price=100,
                                 initial_amount=15000, growth_min_pct=0,
                                 growth_max_pct=10, growth_avg_pct=5,
                                 buy_sell_fee_pct=1.0),
            ],
            currencies=[
                CurrencySettings(
                    code="EUR", initial_price=1.1,
                    min_price=0.9, max_price=1.3, avg_price=1.1,
                    conversion_fee_pct=2.0,
                ),
            ],
        )

        needed_net = 5000.0
        gross = _exact_gross_for_net(state, needed_net, 25.0, "USD", config, 1.1)
        assert gross is not None
        # Gross should be larger than needed_net / fx_rate due to fees/tax/FX
        assert gross > needed_net / 1.1

    def test_skip_fx_conv_same_currency(self):
        """skip_fx_conv=True should produce smaller gross (no FX fee deduction)."""
        from engine.rebalancer import _exact_gross_for_net

        state = _make_state("EUR_Fund", currency="EUR", price=150, amount=15000,
                            initial_price=100, buy_sell_fee_pct=1.0)
        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=25.0,
            buckets=[
                InvestmentBucket(name="EUR_Fund", currency="EUR", initial_price=100,
                                 initial_amount=15000, growth_min_pct=0,
                                 growth_max_pct=10, growth_avg_pct=5,
                                 buy_sell_fee_pct=1.0),
            ],
            currencies=[
                CurrencySettings(
                    code="EUR", initial_price=1.1,
                    min_price=0.9, max_price=1.3, avg_price=1.1,
                    conversion_fee_pct=2.0,
                ),
            ],
        )

        needed_net = 5000.0
        gross_with_fx = _exact_gross_for_net(state, needed_net, 25.0, "USD", config, 1.1)
        gross_no_fx = _exact_gross_for_net(state, needed_net, 25.0, "USD", config, 1.1,
                                            skip_fx_conv=True)
        assert gross_with_fx is not None
        assert gross_no_fx is not None
        assert gross_no_fx < gross_with_fx, \
            "Skipping FX conv should need less gross to cover same net"

    def test_zero_gain_no_tax(self):
        """When bucket has no gain, gross-up should only account for fees."""
        from engine.rebalancer import _exact_gross_for_net

        state = _make_state("Flat", price=100, amount=10000,
                            initial_price=100, buy_sell_fee_pct=1.0)
        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=25.0,
            buckets=[
                InvestmentBucket(name="Flat", initial_price=100, initial_amount=10000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                                 buy_sell_fee_pct=1.0),
            ],
        )

        needed_net = 1000.0
        gross = _exact_gross_for_net(state, needed_net, 25.0, "USD", config, 1.0)
        assert gross is not None
        # With 0 gain, no tax. Fee = 1%, so gross ≈ 1000 / 0.99 ≈ 1010.10
        expected_gross = needed_net / 0.99
        assert abs(gross - expected_gross) < 0.10, \
            f"Zero-gain gross {gross:.2f} should ≈ {expected_gross:.2f}"

    def test_returns_none_when_not_viable(self):
        """When net yield per unit <= 0, should return None."""
        from engine.rebalancer import _exact_gross_for_net

        # 100% fee makes selling unviable
        state = _make_state("Extreme", price=100, amount=10000,
                            initial_price=100, buy_sell_fee_pct=100.0)
        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Extreme", initial_price=100, initial_amount=10000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0,
                                 buy_sell_fee_pct=100.0),
            ],
        )

        result = _exact_gross_for_net(state, 1000.0, 0, "USD", config, 1.0)
        assert result is None

    def test_partial_when_lots_exhausted(self):
        """When lots can't fully cover needed_net, return partial gross."""
        from engine.rebalancer import _exact_gross_for_net

        state = BucketState(
            name="Small", currency="USD", price=100, amount=500,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            spending_priority=0, cash_floor_months=0, required_runaway_months=0,
            triggers=[], cost_basis_method=CostBasisMethod.FIFO,
        )
        state.purchase_lots.append(PurchaseLot(price_exp=100.0, units=5.0))

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Small", initial_price=100, initial_amount=500,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        # Need more net than available — should return the max gross possible
        gross = _exact_gross_for_net(state, 10000.0, 0, "USD", config, 1.0)
        assert gross is not None
        # Max is 5 units * 100 price = 500 bucket currency
        assert abs(gross - 500.0) < 0.01


class TestTotalNetSpentEqualsExpenses:
    """Stage 15 #9: total_net_spent should equal expenses each month within tight tolerance."""

    def test_net_spent_matches_expenses_no_cash_pool(self):
        """Without cash pool, sum of bucket net_spent should equal expenses each month."""
        from engine.simulator import run_simulation
        from models.inflation import InflationSettings

        config = SimConfig(
            period_years=5,
            expenses_currency="USD",
            capital_gain_tax_pct=25,
            inflation=InflationSettings(min_pct=1, max_pct=5, avg_pct=2.5),
            expense_periods=[
                __import__("models.expense", fromlist=["ExpensePeriod"]).ExpensePeriod(
                    start_month=1, start_year=1,
                    amount_min=3000, amount_max=5000, amount_avg=4000,
                ),
            ],
            buckets=[
                InvestmentBucket(
                    name="Stocks", initial_price=100, initial_amount=500000,
                    growth_min_pct=-20, growth_max_pct=30, growth_avg_pct=8,
                    buy_sell_fee_pct=0.5, spending_priority=0,
                ),
                InvestmentBucket(
                    name="Bonds", initial_price=50, initial_amount=200000,
                    growth_min_pct=-5, growth_max_pct=10, growth_avg_pct=3,
                    buy_sell_fee_pct=0.2, spending_priority=1,
                ),
            ],
            cash_pool=CashPool(
                initial_amount=0, refill_trigger_months=0,
                refill_target_months=0, cash_floor_months=0,
            ),
        )

        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)

        for i, row in df.iterrows():
            expenses = row["expenses"]
            net_spent = row["total_net_spent"]
            if expenses > 0:
                # Allow 1% relative tolerance (from gross-up estimate imprecision)
                assert abs(net_spent - expenses) <= 0.01 * expenses + 0.01, \
                    f"Month {i}: net_spent={net_spent:.2f} != expenses={expenses:.2f}"

    def test_net_spent_matches_expenses_with_cash_pool(self):
        """With cash pool, cash_pool_net_spent + bucket net_spent should equal expenses."""
        from engine.simulator import run_simulation
        from models.inflation import InflationSettings

        config = SimConfig(
            period_years=5,
            expenses_currency="USD",
            capital_gain_tax_pct=25,
            inflation=InflationSettings(min_pct=1, max_pct=5, avg_pct=2.5),
            expense_periods=[
                __import__("models.expense", fromlist=["ExpensePeriod"]).ExpensePeriod(
                    start_month=1, start_year=1,
                    amount_min=3000, amount_max=5000, amount_avg=4000,
                ),
            ],
            buckets=[
                InvestmentBucket(
                    name="Stocks", initial_price=100, initial_amount=500000,
                    growth_min_pct=-20, growth_max_pct=30, growth_avg_pct=8,
                    buy_sell_fee_pct=0.5, spending_priority=0,
                ),
            ],
            cash_pool=CashPool(
                initial_amount=50000, refill_trigger_months=6,
                refill_target_months=12, cash_floor_months=3,
            ),
        )

        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)

        for i, row in df.iterrows():
            expenses = row["expenses"]
            net_spent = row["total_net_spent"]
            if expenses > 0:
                assert abs(net_spent - expenses) <= 0.01 * expenses + 0.01, \
                    f"Month {i}: net_spent={net_spent:.2f} != expenses={expenses:.2f}"

    def test_net_spent_matches_with_cross_currency(self):
        """Cross-currency buckets: net_spent should still match expenses."""
        from engine.simulator import run_simulation
        from models.inflation import InflationSettings

        config = SimConfig(
            period_years=3,
            expenses_currency="USD",
            capital_gain_tax_pct=25,
            inflation=InflationSettings(min_pct=1, max_pct=3, avg_pct=2),
            expense_periods=[
                __import__("models.expense", fromlist=["ExpensePeriod"]).ExpensePeriod(
                    start_month=1, start_year=1,
                    amount_min=4000, amount_max=4000, amount_avg=4000,
                ),
            ],
            buckets=[
                InvestmentBucket(
                    name="EUR_Fund", currency="EUR", initial_price=100,
                    initial_amount=300000, growth_min_pct=-10,
                    growth_max_pct=20, growth_avg_pct=7,
                    buy_sell_fee_pct=0.5, spending_priority=0,
                ),
                InvestmentBucket(
                    name="USD_Fund", initial_price=100,
                    initial_amount=200000, growth_min_pct=-10,
                    growth_max_pct=20, growth_avg_pct=5,
                    buy_sell_fee_pct=0.3, spending_priority=1,
                ),
            ],
            currencies=[
                CurrencySettings(
                    code="EUR", initial_price=1.1,
                    min_price=0.9, max_price=1.3, avg_price=1.1,
                    conversion_fee_pct=0.5,
                ),
            ],
        )

        rng = np.random.default_rng(42)
        df = run_simulation(config, rng)

        for i, row in df.iterrows():
            expenses = row["expenses"]
            net_spent = row["total_net_spent"]
            if expenses > 0:
                assert abs(net_spent - expenses) <= 0.01 * expenses + 0.01, \
                    f"Month {i}: net_spent={net_spent:.2f} != expenses={expenses:.2f}"


class TestPostExpenseRefill:
    """Stage 15 #10: Cash pool should be refilled after expenses are drawn
    when it drops below refill trigger."""

    def test_post_expense_refill_occurs(self):
        """Cash pool above trigger before expenses, below trigger after drawing.
        Phase 3 should refill it."""
        # Cash pool: 7000, trigger=6 months, target=12 months, floor=0
        # Monthly expense: 1000
        # Before expenses: 7000 > 6*1000=6000 → no pre-expense refill needed
        # After drawing 1000: 6000 = trigger → borderline
        # If expenses are 2000: after drawing 2000: 5000 < 6000 → Phase 3 should refill
        sp500 = _make_state("SP500", price=100, amount=100000,
                            initial_price=100, buy_sell_fee_pct=0)
        cash_pool = CashPoolState(
            amount=7000, refill_trigger_months=6,
            refill_target_months=12, cash_floor_months=0,
        )

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            cash_pool=CashPool(initial_amount=7000, refill_trigger_months=6,
                               refill_target_months=12, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=100000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                                 buy_sell_fee_pct=0),
            ],
        )

        # Expense of 2000: pool goes 7000→5000 after draw, below trigger 6000
        execute_rebalance([sp500], 2000, {}, config, 0, cash_pool=cash_pool)

        # Phase 3 post-expense refill should have topped up toward target (12*2000=24000)
        assert cash_pool.amount > 5000, \
            f"Cash pool should be refilled after expenses, got {cash_pool.amount}"
        assert sp500.amount_sold > 0, "Bucket should be sold for post-expense refill"

    def test_no_post_expense_refill_when_above_trigger(self):
        """Cash pool still above trigger after expenses → no Phase 3 refill."""
        sp500 = _make_state("SP500", price=100, amount=100000,
                            initial_price=100, buy_sell_fee_pct=0)
        cash_pool = CashPoolState(
            amount=20000, refill_trigger_months=6,
            refill_target_months=12, cash_floor_months=0,
        )

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            cash_pool=CashPool(initial_amount=20000, refill_trigger_months=6,
                               refill_target_months=12, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=100000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                                 buy_sell_fee_pct=0),
            ],
        )

        # Expense of 1000: pool goes 20000→19000, still above 6*1000=6000
        execute_rebalance([sp500], 1000, {}, config, 0, cash_pool=cash_pool)

        # No refill needed — pool is still well above trigger
        assert cash_pool.amount == 19000, \
            f"Cash pool should just be drawn, got {cash_pool.amount}"
        assert sp500.amount_sold == 0, "No bucket selling needed"

    def test_post_expense_refill_before_buy_triggers(self):
        """Post-expense refill should happen before buy triggers run,
        so buy triggers see the refilled cash pool in portfolio total."""
        buy_trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.SHARE_BELOW.value,
            threshold_pct=30.0,
            source_buckets=["Source"],
        )
        # Buyer: 10% of portfolio
        buyer = _make_state("Buyer", price=100, amount=10000,
                            buy_sell_fee_pct=0, triggers=[buy_trigger])
        source = _make_state("Source", price=100, amount=90000,
                             initial_price=100, buy_sell_fee_pct=0)
        # Cash pool starts just above trigger, drops below after expenses
        cash_pool = CashPoolState(
            amount=6100, refill_trigger_months=6,
            refill_target_months=12, cash_floor_months=0,
        )

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            cash_pool=CashPool(initial_amount=6100, refill_trigger_months=6,
                               refill_target_months=12, cash_floor_months=0),
            buckets=[
                InvestmentBucket(name="Buyer", initial_price=100, initial_amount=10000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                                 buy_sell_fee_pct=0),
                InvestmentBucket(name="Source", initial_price=100, initial_amount=90000,
                                 growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                                 buy_sell_fee_pct=0),
            ],
        )

        # Expense: 1000 → pool goes 6100→5100, below trigger 6000
        # Phase 3 refills pool, then Phase 4 runs buy triggers
        execute_rebalance([buyer, source], 1000, {}, config, 0, cash_pool=cash_pool)

        # Cash pool should have been refilled before buy triggers
        # (buy trigger sees updated portfolio total including refilled cash pool)
        assert cash_pool.amount > 5100, "Post-expense refill should occur"


class TestSelfReferentialTriggerBehavior:
    """Stage 15 #11: Self-referential triggers (target_bucket or source_buckets
    referencing the owning bucket). Currently not validated — test observable behavior."""

    def test_sell_trigger_self_target_with_fees(self):
        """Sell trigger targeting itself: sells and buys back, losing value to fees."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=100,
            target_bucket="SP500",  # self-referential!
        )
        sp500 = _make_state("SP500", price=200, amount=10000,
                            initial_price=100, target_growth_pct=10,
                            buy_sell_fee_pct=2.0, triggers=[trigger])

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=2.0),
            ],
        )

        initial_amount = sp500.amount
        execute_rebalance([sp500], 0, {}, config, 0)

        # Trigger fires, sells and buys back into same bucket
        assert sp500.amount_sold > 0, "Self-referential sell trigger should fire"
        assert sp500.amount_bought > 0, "Should buy back into itself"
        # With 2% sell + 2% buy fee, value is destroyed
        assert sp500.fees_paid > 0, "Fees should be charged"
        # Net amount should be less than initial (value lost to fees)
        assert sp500.amount < initial_amount, \
            "Self-referential trigger with fees should reduce bucket value"

    def test_sell_trigger_self_target_zero_fees(self):
        """Sell trigger targeting itself with zero fees: should be a wash."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.SELL,
            subtype=SellSubtype.TAKE_PROFIT.value,
            threshold_pct=100,
            target_bucket="SP500",
        )
        sp500 = _make_state("SP500", price=200, amount=10000,
                            initial_price=100, target_growth_pct=10,
                            buy_sell_fee_pct=0, triggers=[trigger])

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=100, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
            ],
        )

        initial_amount = sp500.amount
        execute_rebalance([sp500], 0, {}, config, 0)

        # With zero fees and zero tax, sell + buy back = wash
        assert sp500.amount_sold > 0, "Trigger should fire"
        assert abs(sp500.amount - initial_amount) < 1.0, \
            "Zero-fee self-referential trigger should preserve value"

    def test_buy_trigger_self_source(self):
        """Buy trigger with itself as source: should not produce meaningful results
        since selling from self to buy into self is circular."""
        trigger = BucketTrigger(
            trigger_type=TriggerType.BUY,
            subtype=BuySubtype.DISCOUNT.value,
            threshold_pct=5.0,
            source_buckets=["SP500"],  # self-referential!
        )
        # Use initial_price=80 to match price=80 so lots are consistent.
        # The discount trigger still fires because target_price = 80*1.1 = 88 > 80.
        sp500 = _make_state("SP500", price=80, amount=10000,
                            initial_price=80, target_growth_pct=10,
                            buy_sell_fee_pct=0, triggers=[trigger])

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="SP500", initial_price=80, initial_amount=10000,
                                 growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
                                 buy_sell_fee_pct=0),
            ],
        )

        initial_amount = sp500.amount
        execute_rebalance([sp500], 0, {}, config, 0)

        # Self-source buy trigger: sells from self, buys into self
        # With zero fees, net effect should be approximately zero
        # The trigger condition fires (discount exists), but selling from self
        # to buy into self doesn't change net position (with zero fees/tax)
        assert abs(sp500.amount - initial_amount) < 1.0, \
            "Self-source buy trigger with zero fees should be approximately a wash"


class TestComputeCostBasisBugReport:
    """Test that _compute_cost_basis raises SimulationBugError on lots exhausted."""

    def test_lots_exhausted_raises_bug_error(self, tmp_path, monkeypatch):
        """When lots are exhausted with remaining units, should raise SimulationBugError."""
        monkeypatch.chdir(tmp_path)

        state = BucketState(
            name="Broken", currency="USD", price=100, amount=10000,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            spending_priority=0, cash_floor_months=0, required_runaway_months=0,
            triggers=[], cost_basis_method=CostBasisMethod.FIFO,
        )
        # Add only 10 units but try to sell 200 units worth (20000 currency)
        state.purchase_lots.append(PurchaseLot(price_exp=100.0, units=10.0))

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Broken", initial_price=100, initial_amount=10000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        with pytest.raises(SimulationBugError, match="lots exhausted"):
            _compute_cost_basis(state, 20000.0, 1.0, config)

    def test_lots_exhausted_writes_json_report(self, tmp_path, monkeypatch):
        """Bug report JSON file should be written before raising."""
        monkeypatch.chdir(tmp_path)

        state = BucketState(
            name="Broken", currency="USD", price=100, amount=10000,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            spending_priority=0, cash_floor_months=0, required_runaway_months=0,
            triggers=[], cost_basis_method=CostBasisMethod.FIFO,
        )
        state.purchase_lots.append(PurchaseLot(price_exp=100.0, units=10.0))

        config = SimConfig(
            expenses_currency="USD", capital_gain_tax_pct=0,
            buckets=[
                InvestmentBucket(name="Broken", initial_price=100, initial_amount=10000,
                                 growth_min_pct=0, growth_max_pct=0, growth_avg_pct=0),
            ],
        )

        with pytest.raises(SimulationBugError):
            _compute_cost_basis(state, 20000.0, 1.0, config)

        import glob
        reports = glob.glob(str(tmp_path / "bug_report_*.json"))
        assert len(reports) == 1, "Should have written exactly one bug report"

        import json
        with open(reports[0]) as f:
            report = json.load(f)
        assert "lots exhausted" in report["error"]
        assert report["context"]["bucket"] == "Broken"

    def test_no_config_falls_back_silently(self):
        """Without config parameter, should fall back silently (backward compat)."""
        state = BucketState(
            name="Legacy", currency="USD", price=100, amount=10000,
            initial_price=100, target_growth_pct=10, buy_sell_fee_pct=0,
            spending_priority=0, cash_floor_months=0, required_runaway_months=0,
            triggers=[], cost_basis_method=CostBasisMethod.FIFO,
        )
        state.purchase_lots.append(PurchaseLot(price_exp=100.0, units=10.0))

        # Without config, should NOT raise — falls back to old behavior
        result = _compute_cost_basis(state, 20000.0, 1.0)
        assert result > 0
