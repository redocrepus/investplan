"""Investment bucket and rebalancing parameters models."""

from typing import Optional
from pydantic import BaseModel, model_validator
from utils.volatility import VolatilityProfile


class RebalancingParams(BaseModel):
    """Target-trajectory rebalancing configuration for a bucket."""
    frequency: str = "monthly"  # "monthly" or "yearly"
    sell_trigger: float = 1.5   # sell if actual_growth/target_growth > X
    standby_bucket: Optional[str] = None  # name of the standby bucket to buy
    buy_trigger: float = 5.0    # buy if 100*target_price/current_price - 100 > X%
    buying_priority: int = 0    # lower = buy first
    required_runaway_months: float = 6.0  # months of expenses required before selling
    spending_priority: int = 0  # lower = sell first for expenses
    cash_floor_months: float = 0.0  # keep at least this many months of expenses

    @model_validator(mode="after")
    def _check_values(self):
        if self.frequency not in ("monthly", "yearly"):
            raise ValueError("frequency must be 'monthly' or 'yearly'")
        if self.sell_trigger <= 0:
            raise ValueError("sell_trigger must be > 0")
        if self.required_runaway_months < 0:
            raise ValueError("required_runaway_months must be >= 0")
        if self.cash_floor_months < 0:
            raise ValueError("cash_floor_months must be >= 0")
        return self


class InvestmentBucket(BaseModel):
    """An investment bucket (asset class) in the portfolio."""
    name: str
    currency: str = "USD"
    initial_price: float
    initial_amount: float
    growth_min_pct: float
    growth_max_pct: float
    growth_avg_pct: float
    volatility: VolatilityProfile = VolatilityProfile.SP500
    buy_sell_fee_pct: float = 0.0
    target_growth_pct: float = 7.0
    rebalancing: RebalancingParams = RebalancingParams()

    @model_validator(mode="after")
    def _check_bounds(self):
        if self.growth_min_pct > self.growth_max_pct:
            raise ValueError("growth_min_pct must be <= growth_max_pct")
        if not (self.growth_min_pct <= self.growth_avg_pct <= self.growth_max_pct):
            raise ValueError("growth_avg_pct must be between growth_min_pct and growth_max_pct")
        if self.initial_price <= 0:
            raise ValueError("initial_price must be > 0")
        if self.initial_amount < 0:
            raise ValueError("initial_amount must be >= 0")
        if self.buy_sell_fee_pct < 0:
            raise ValueError("buy_sell_fee_pct must be >= 0")
        return self
