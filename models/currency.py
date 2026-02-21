"""Currency exchange settings model."""

from pydantic import BaseModel, model_validator
from utils.volatility import VolatilityProfile


class CurrencySettings(BaseModel):
    """FX settings for a non-expenses currency."""
    code: str
    initial_price: float            # price in expenses currency
    min_price: float
    max_price: float
    avg_price: float
    volatility: VolatilityProfile = VolatilityProfile.SP500
    conversion_fee_pct: float = 0.0  # fee percentage on conversion

    @model_validator(mode="after")
    def _check_bounds(self):
        if self.min_price > self.max_price:
            raise ValueError("min_price must be <= max_price")
        if not (self.min_price <= self.avg_price <= self.max_price):
            raise ValueError("avg_price must be between min_price and max_price")
        if self.initial_price <= 0:
            raise ValueError("initial_price must be > 0")
        if self.conversion_fee_pct < 0:
            raise ValueError("conversion_fee_pct must be >= 0")
        return self
