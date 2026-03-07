"""Investment bucket, triggers, and rebalancing models."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, model_validator
from utils.volatility import VolatilityProfile


class TriggerType(str, Enum):
    SELL = "sell"
    BUY = "buy"


class SellSubtype(str, Enum):
    TAKE_PROFIT = "take_profit"
    SHARE_EXCEEDS = "share_exceeds"


class BuySubtype(str, Enum):
    DISCOUNT = "discount"
    SHARE_BELOW = "share_below"


class CostBasisMethod(str, Enum):
    FIFO = "fifo"
    LIFO = "lifo"
    AVCO = "avco"


class BucketTrigger(BaseModel):
    """A single trigger (sell or buy) attached to an investment bucket.

    Sell triggers use ``target_bucket`` to specify where proceeds are invested.
    Buy triggers use ``source_buckets`` (ordered list) to specify funding sources.
    For backward compatibility, if a buy trigger has ``target_bucket`` set but
    ``source_buckets`` is empty, ``source_buckets`` is auto-populated from
    ``target_bucket``.
    """
    trigger_type: TriggerType
    subtype: str  # SellSubtype or BuySubtype value
    threshold_pct: float  # percentage: take_profit=100 means "fire at 100% of target growth"
    target_bucket: Optional[str] = None      # sell triggers: where to invest proceeds
    source_buckets: list[str] = []            # buy triggers: ordered list of funding sources
    period_months: int = 1  # check every N months (1=monthly, 12=yearly)

    @model_validator(mode="after")
    def _check_values(self):
        if self.period_months < 1:
            raise ValueError("period_months must be >= 1")
        if self.trigger_type == TriggerType.SELL:
            if self.subtype not in (SellSubtype.TAKE_PROFIT.value, SellSubtype.SHARE_EXCEEDS.value):
                raise ValueError(f"Invalid sell subtype: {self.subtype}")
        elif self.trigger_type == TriggerType.BUY:
            if self.subtype not in (BuySubtype.DISCOUNT.value, BuySubtype.SHARE_BELOW.value):
                raise ValueError(f"Invalid buy subtype: {self.subtype}")
            # Backward compat: migrate target_bucket to source_buckets
            if not self.source_buckets and self.target_bucket:
                self.source_buckets = [self.target_bucket]
            if not self.source_buckets:
                raise ValueError("Buy triggers must have at least one source bucket")
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
    cost_basis_method: CostBasisMethod = CostBasisMethod.FIFO

    # Rebalancing — bucket-level fields
    spending_priority: int = 0       # lower = sell first for expenses
    cash_floor_months: float = 0.0   # keep at least this many months of expenses
    required_runaway_months: float = 6.0  # months of expenses required before trigger-based selling

    # Multi-trigger list
    triggers: list[BucketTrigger] = []

    @model_validator(mode="after")
    def _check_bounds(self):
        # Validate at most one share_below and one share_exceeds trigger
        share_below_count = sum(
            1 for t in self.triggers
            if t.trigger_type == TriggerType.BUY and t.subtype == BuySubtype.SHARE_BELOW.value
        )
        share_exceeds_count = sum(
            1 for t in self.triggers
            if t.trigger_type == TriggerType.SELL and t.subtype == SellSubtype.SHARE_EXCEEDS.value
        )
        if share_below_count > 1:
            raise ValueError("At most one share_below buy trigger is allowed per bucket")
        if share_exceeds_count > 1:
            raise ValueError("At most one share_exceeds sell trigger is allowed per bucket")
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
        if self.cash_floor_months < 0:
            raise ValueError("cash_floor_months must be >= 0")
        if self.required_runaway_months < 0:
            raise ValueError("required_runaway_months must be >= 0")
        return self
