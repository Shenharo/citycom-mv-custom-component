"""Estimate the cost of the water used in a month."""

from __future__ import annotations


def compute_cost(  # noqa: PLR0913
    consumption: float,
    *,
    regular: float,
    over: float | None = None,
    drain: float = 0.0,
    fixed: float = 0.0,
    allowance_per_person: float = 0.0,
    persons: int = 0,
) -> float:
    """Return the cost of `consumption` m³.

    Water up to `allowance_per_person` x `persons` is charged at the regular
    price and the rest at the over-usage price (the regular price if unset).
    With no allowance everything is regular. The drain price applies to all
    water, and the fixed fee is added once.
    """
    allowance = allowance_per_person * persons
    regular_m3 = min(consumption, allowance) if allowance > 0 else consumption
    over_m3 = consumption - regular_m3
    over_price = regular if over is None else over
    return regular_m3 * regular + over_m3 * over_price + consumption * drain + fixed
