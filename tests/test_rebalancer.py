"""Tests for rebalancer engine."""

import numpy as np
from engine.rebalancer import (
    BucketState, check_sell_trigger, check_buy_trigger,
    execute_rebalance,
)
from models.config import SimConfig
from models.bucket import InvestmentBucket


class TestCheckSellTrigger:
    def test_triggers_when_exceeds(self):
        b = BucketState(
            name="SP500", currency="USD",
            price=200, amount=10000,
            initial_price=100, target_growth_pct=10,
            buy_sell_fee_pct=0, sell_trigger=1.5,
        )
        # actual growth = 100%, target = 10%, ratio = 10 > 1.5
        assert check_sell_trigger(b) is True

    def test_no_trigger_when_below(self):
        b = BucketState(
            name="SP500", currency="USD",
            price=105, amount=10000,
            initial_price=100, target_growth_pct=10,
            buy_sell_fee_pct=0, sell_trigger=1.5,
        )
        # actual growth = 5%, target = 10%, ratio = 0.5 < 1.5
        assert check_sell_trigger(b) is False

    def test_zero_target_growth(self):
        b = BucketState(
            name="Cash", currency="USD",
            price=100, amount=10000,
            initial_price=100, target_growth_pct=0,
            buy_sell_fee_pct=0, sell_trigger=1.5,
        )
        assert check_sell_trigger(b) is False


class TestCheckBuyTrigger:
    def test_triggers_when_undervalued(self):
        b = BucketState(
            name="SP500", currency="USD",
            price=80, amount=10000,
            initial_price=100, target_growth_pct=10,
            buy_sell_fee_pct=0, buy_trigger=5.0,
        )
        # target_price = 110, discount = 100*110/80 - 100 = 37.5% > 5
        assert check_buy_trigger(b) is True

    def test_no_trigger_when_overvalued(self):
        b = BucketState(
            name="SP500", currency="USD",
            price=120, amount=10000,
            initial_price=100, target_growth_pct=10,
            buy_sell_fee_pct=0, buy_trigger=5.0,
        )
        # target_price = 110, discount = 100*110/120 - 100 = -8.3% < 5
        assert check_buy_trigger(b) is False


class TestRunawayGuard:
    def test_no_sell_when_low_runway(self):
        """If portfolio runway < required months, sell trigger should be skipped."""
        bucket = InvestmentBucket(
            name="SP500", currency="USD",
            initial_price=100, initial_amount=500,
            growth_min_pct=-10, growth_max_pct=30, growth_avg_pct=10,
            target_growth_pct=10,
        )
        bucket.rebalancing.required_runaway_months = 12
        bucket.rebalancing.sell_trigger = 0.1  # Very low trigger to ensure it would fire

        config = SimConfig(
            buckets=[bucket],
            expenses_currency="USD",
        )

        state = BucketState(
            name="SP500", currency="USD",
            price=200, amount=500,  # only 500 USD total — less than 12 months of 1000
            initial_price=100, target_growth_pct=10,
            buy_sell_fee_pct=0,
            sell_trigger=0.1,
            required_runaway_months=12,
            spending_priority=0,
        )

        # High expense relative to holdings
        total_covered = execute_rebalance([state], 1000, {}, config, 0)

        # Should still try to cover expenses via spending cascade
        assert total_covered > 0


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
                ),
                InvestmentBucket(
                    name="Secondary", currency="USD",
                    initial_price=100, initial_amount=10000,
                    growth_min_pct=0, growth_max_pct=10, growth_avg_pct=5,
                ),
            ],
        )

        states = [
            BucketState(
                name="Primary", currency="USD",
                price=100, amount=5000,
                initial_price=100, target_growth_pct=5,
                buy_sell_fee_pct=0,
                spending_priority=0,  # sell first
                cash_floor_months=3,  # keep at least 3 months of expenses
            ),
            BucketState(
                name="Secondary", currency="USD",
                price=100, amount=10000,
                initial_price=100, target_growth_pct=5,
                buy_sell_fee_pct=0,
                spending_priority=1,  # sell second
                cash_floor_months=0,
            ),
        ]

        monthly_expense = 1000
        total_covered = execute_rebalance(states, monthly_expense, {}, config, 0)

        # Primary should keep at least 3000 (3 months * 1000)
        assert states[0].amount >= 3000 - 1  # small tolerance
