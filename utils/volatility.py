"""Volatility profile enums and their σ mappings."""

from enum import Enum
from typing import NamedTuple


class DistributionType(str, Enum):
    CONSTANT = "constant"
    LOGNORMAL = "lognormal"
    NORMAL = "normal"


class VolatilitySpec(NamedTuple):
    monthly_sigma: float
    distribution: DistributionType


# --- Investment / FX volatility profiles ---

class VolatilityProfile(str, Enum):
    CONSTANT = "constant"
    GOV_BONDS = "gov_bonds"
    SP500 = "sp500"
    GOLD = "gold"
    BITCOIN = "bitcoin"


VOLATILITY_PROFILE_MAP: dict[VolatilityProfile, VolatilitySpec] = {
    VolatilityProfile.CONSTANT: VolatilitySpec(0.0, DistributionType.CONSTANT),
    VolatilityProfile.GOV_BONDS: VolatilitySpec(0.005, DistributionType.LOGNORMAL),
    VolatilityProfile.SP500: VolatilitySpec(0.04, DistributionType.LOGNORMAL),
    VolatilityProfile.GOLD: VolatilitySpec(0.025, DistributionType.LOGNORMAL),
    VolatilityProfile.BITCOIN: VolatilitySpec(0.15, DistributionType.LOGNORMAL),
}


# --- Expense volatility ---

class ExpenseVolatility(str, Enum):
    CONSTANT = "constant"
    MODERATE = "moderate"
    CRAZY = "crazy"


EXPENSE_VOLATILITY_MAP: dict[ExpenseVolatility, VolatilitySpec] = {
    ExpenseVolatility.CONSTANT: VolatilitySpec(0.0, DistributionType.CONSTANT),
    ExpenseVolatility.MODERATE: VolatilitySpec(0.03, DistributionType.NORMAL),
    ExpenseVolatility.CRAZY: VolatilitySpec(0.08, DistributionType.NORMAL),
}


# --- Inflation volatility ---

class InflationVolatility(str, Enum):
    CONSTANT = "constant"
    MILD = "mild"
    CRAZY = "crazy"


INFLATION_VOLATILITY_MAP: dict[InflationVolatility, VolatilitySpec] = {
    InflationVolatility.CONSTANT: VolatilitySpec(0.0, DistributionType.CONSTANT),
    InflationVolatility.MILD: VolatilitySpec(0.002, DistributionType.NORMAL),
    InflationVolatility.CRAZY: VolatilitySpec(0.01, DistributionType.NORMAL),
}


def get_volatility_spec(profile: VolatilityProfile) -> VolatilitySpec:
    return VOLATILITY_PROFILE_MAP[profile]


def get_expense_volatility_spec(profile: ExpenseVolatility) -> VolatilitySpec:
    return EXPENSE_VOLATILITY_MAP[profile]


def get_inflation_volatility_spec(profile: InflationVolatility) -> VolatilitySpec:
    return INFLATION_VOLATILITY_MAP[profile]
