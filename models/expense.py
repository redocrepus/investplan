"""Expense period and one-time expense models."""

from pydantic import BaseModel, model_validator
from utils.volatility import ExpenseVolatility


class ExpensePeriod(BaseModel):
    """A recurring expense period that lasts until the next period or end of simulation."""
    start_month: int  # 1-12
    start_year: int   # 1-based year of the simulation
    amount_min: float
    amount_max: float
    amount_avg: float
    volatility: ExpenseVolatility = ExpenseVolatility.CONSTANT

    @model_validator(mode="after")
    def _check_bounds(self):
        if self.amount_min > self.amount_max:
            raise ValueError("amount_min must be <= amount_max")
        if not (self.amount_min <= self.amount_avg <= self.amount_max):
            raise ValueError("amount_avg must be between amount_min and amount_max")
        if not (1 <= self.start_month <= 12):
            raise ValueError("start_month must be between 1 and 12")
        if self.start_year < 1:
            raise ValueError("start_year must be >= 1")
        return self


class OneTimeExpense(BaseModel):
    """A one-time expense at a specific month."""
    month: int  # 1-12
    year: int   # 1-based year of the simulation
    amount: float

    @model_validator(mode="after")
    def _check_values(self):
        if not (1 <= self.month <= 12):
            raise ValueError("month must be between 1 and 12")
        if self.year < 1:
            raise ValueError("year must be >= 1")
        if self.amount < 0:
            raise ValueError("amount must be >= 0")
        return self
