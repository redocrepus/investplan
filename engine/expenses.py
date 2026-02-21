"""Monthly expense computation with inflation adjustment."""

import numpy as np
from models.expense import ExpensePeriod, OneTimeExpense
from utils.volatility import get_expense_volatility_spec, DistributionType


def compute_monthly_expenses(
    expense_periods: list[ExpensePeriod],
    one_time_expenses: list[OneTimeExpense],
    inflation_rates: np.ndarray,
    n_months: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Compute monthly expenses array, inflation-adjusted.

    Months are 0-indexed internally. ExpensePeriod start is converted from
    (year, month) to a 0-based month index: (start_year - 1) * 12 + (start_month - 1).
    """
    expenses = np.zeros(n_months)

    # Sort expense periods by their start month index
    sorted_periods = sorted(
        expense_periods,
        key=lambda p: (p.start_year - 1) * 12 + (p.start_month - 1),
    )

    # Build a mapping: for each month, which period is active
    period_for_month: list[ExpensePeriod | None] = [None] * n_months
    for idx, period in enumerate(sorted_periods):
        start_idx = (period.start_year - 1) * 12 + (period.start_month - 1)
        # End is the start of next period, or end of simulation
        if idx + 1 < len(sorted_periods):
            next_period = sorted_periods[idx + 1]
            end_idx = (next_period.start_year - 1) * 12 + (next_period.start_month - 1)
        else:
            end_idx = n_months
        for m in range(max(0, start_idx), min(n_months, end_idx)):
            period_for_month[m] = period

    # Cumulative inflation factor
    cum_inflation = np.ones(n_months)
    for i in range(n_months):
        if i == 0:
            cum_inflation[i] = 1.0 + inflation_rates[i]
        else:
            cum_inflation[i] = cum_inflation[i - 1] * (1.0 + inflation_rates[i])

    # Generate base expenses for each month
    for m in range(n_months):
        period = period_for_month[m]
        if period is None:
            continue

        spec = get_expense_volatility_spec(period.volatility)

        if spec.distribution == DistributionType.CONSTANT:
            base = period.amount_avg
        else:
            base = rng.normal(period.amount_avg, spec.monthly_sigma * period.amount_avg)
            base = np.clip(base, period.amount_min, period.amount_max)

        # Apply cumulative inflation
        expenses[m] = base * cum_inflation[m]

    # Add one-time expenses
    for ote in one_time_expenses:
        m_idx = (ote.year - 1) * 12 + (ote.month - 1)
        if 0 <= m_idx < n_months:
            expenses[m_idx] += ote.amount * cum_inflation[m_idx]

    return expenses
