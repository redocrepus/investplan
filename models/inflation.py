"""Inflation settings model."""

from pydantic import BaseModel, model_validator
from utils.volatility import InflationVolatility


class InflationSettings(BaseModel):
    """Inflation parameters for the simulation."""
    min_pct: float
    max_pct: float
    avg_pct: float
    volatility: InflationVolatility = InflationVolatility.MILD

    @model_validator(mode="after")
    def _check_bounds(self):
        if self.min_pct > self.max_pct:
            raise ValueError("min_pct must be <= max_pct")
        if not (self.min_pct <= self.avg_pct <= self.max_pct):
            raise ValueError("avg_pct must be between min_pct and max_pct")
        return self
