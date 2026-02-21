"""Top-level simulation configuration model."""

from pydantic import BaseModel, Field
from models.inflation import InflationSettings
from models.expense import ExpensePeriod, OneTimeExpense
from models.currency import CurrencySettings
from models.bucket import InvestmentBucket


class SimConfig(BaseModel):
    """Complete simulation configuration aggregating all parameters."""
    period_years: int = 10
    expenses_currency: str = "USD"
    hedge_amount: float = 0.0          # total hedge in expenses currency
    capital_gain_tax_pct: float = 25.0  # capital gains tax percentage

    inflation: InflationSettings = InflationSettings(
        min_pct=1.0, max_pct=5.0, avg_pct=2.5
    )

    expense_periods: list[ExpensePeriod] = Field(default_factory=list)
    one_time_expenses: list[OneTimeExpense] = Field(default_factory=list)

    buckets: list[InvestmentBucket] = Field(default_factory=list)
    currencies: list[CurrencySettings] = Field(default_factory=list)
