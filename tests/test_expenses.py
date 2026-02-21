"""Tests for expense computation engine."""

import numpy as np
from models.expense import ExpensePeriod, OneTimeExpense
from engine.expenses import compute_monthly_expenses
from utils.volatility import ExpenseVolatility


class TestComputeMonthlyExpenses:
    def test_single_constant_period(self):
        periods = [
            ExpensePeriod(
                start_month=1, start_year=1,
                amount_min=2000, amount_max=2000, amount_avg=2000,
                volatility=ExpenseVolatility.CONSTANT,
            ),
        ]
        # Zero inflation
        inflation = np.zeros(24)
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses(periods, [], inflation, 24, rng)
        # With zero inflation, cumulative factor is 1.0 for all months
        np.testing.assert_allclose(expenses, 2000.0)

    def test_period_switching(self):
        periods = [
            ExpensePeriod(
                start_month=1, start_year=1,
                amount_min=1000, amount_max=1000, amount_avg=1000,
                volatility=ExpenseVolatility.CONSTANT,
            ),
            ExpensePeriod(
                start_month=7, start_year=1,
                amount_min=2000, amount_max=2000, amount_avg=2000,
                volatility=ExpenseVolatility.CONSTANT,
            ),
        ]
        inflation = np.zeros(12)
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses(periods, [], inflation, 12, rng)
        # First 6 months: 1000, next 6 months: 2000
        np.testing.assert_allclose(expenses[:6], 1000.0)
        np.testing.assert_allclose(expenses[6:], 2000.0)

    def test_one_time_expense(self):
        one_time = [OneTimeExpense(month=3, year=1, amount=5000)]
        inflation = np.zeros(12)
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses([], one_time, inflation, 12, rng)
        # Only month index 2 (month=3, year=1) should have the expense
        assert expenses[2] == 5000.0
        assert expenses[0] == 0.0
        assert expenses[5] == 0.0

    def test_inflation_adjustment(self):
        periods = [
            ExpensePeriod(
                start_month=1, start_year=1,
                amount_min=1000, amount_max=1000, amount_avg=1000,
                volatility=ExpenseVolatility.CONSTANT,
            ),
        ]
        # 1% monthly inflation
        inflation = np.full(12, 0.01)
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses(periods, [], inflation, 12, rng)
        # Each month should be higher than the last
        for i in range(1, 12):
            assert expenses[i] > expenses[i - 1]
        # First month: 1000 * 1.01 = 1010
        assert abs(expenses[0] - 1010) < 1

    def test_no_periods_no_expenses(self):
        inflation = np.zeros(12)
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses([], [], inflation, 12, rng)
        np.testing.assert_allclose(expenses, 0.0)

    def test_moderate_volatility_respects_bounds(self):
        periods = [
            ExpensePeriod(
                start_month=1, start_year=1,
                amount_min=800, amount_max=1200, amount_avg=1000,
                volatility=ExpenseVolatility.MODERATE,
            ),
        ]
        inflation = np.zeros(120)
        rng = np.random.default_rng(42)
        expenses = compute_monthly_expenses(periods, [], inflation, 120, rng)
        assert np.all(expenses >= 800)
        assert np.all(expenses <= 1200)
