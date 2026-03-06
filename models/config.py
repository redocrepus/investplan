"""Top-level simulation configuration model."""

from pydantic import BaseModel, Field, field_validator
from models.inflation import InflationSettings
from models.expense import ExpensePeriod, OneTimeExpense
from models.currency import CurrencySettings
from models.bucket import InvestmentBucket


class CashPool(BaseModel):
    """Cash reserve in expenses currency. Expenses are drawn from here;
    investment buckets auto-refill it when it drops below the target."""
    initial_amount: float = 0.0           # starting cash in expenses currency
    refill_target_months: float = 24.0    # auto-refill when below this many months of expenses
    cash_floor_months: float = 12.0       # hard floor for the cash pool itself

    @field_validator("initial_amount")
    @classmethod
    def _initial_amount_non_negative(cls, v):
        if v < 0:
            raise ValueError("initial_amount must be >= 0")
        return v

    @field_validator("refill_target_months")
    @classmethod
    def _refill_target_non_negative(cls, v):
        if v < 0:
            raise ValueError("refill_target_months must be >= 0")
        return v

    @field_validator("cash_floor_months")
    @classmethod
    def _cash_floor_non_negative(cls, v):
        if v < 0:
            raise ValueError("cash_floor_months must be >= 0")
        return v


class SimConfig(BaseModel):
    """Complete simulation configuration aggregating all parameters."""
    period_years: int = 10
    expenses_currency: str = "USD"
    hedge_amount: float = 0.0          # total hedge in expenses currency
    capital_gain_tax_pct: float = 25.0  # capital gains tax percentage

    inflation: InflationSettings = InflationSettings(
        min_pct=1.0, max_pct=5.0, avg_pct=2.5
    )

    cash_pool: CashPool = CashPool()

    expense_periods: list[ExpensePeriod] = Field(default_factory=list)
    one_time_expenses: list[OneTimeExpense] = Field(default_factory=list)

    buckets: list[InvestmentBucket] = Field(default_factory=list)
    currencies: list[CurrencySettings] = Field(default_factory=list)
