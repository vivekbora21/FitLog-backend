"""Rounding helper for the plan engine (spec section 4.9).

Python's built-in ``round`` uses banker's rounding (round-half-to-even),
which is wrong for calories and macros: ``round(2.5) == 2``. This module
provides an explicit "round half up" (ties rounded away from zero)
implementation, matching spec worked case M exactly.
"""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up(x: float, step: int = 1) -> int:
    """Round ``x`` to the nearest multiple of ``step``, rounding ties away
    from zero (never Python's banker's rounding).

    >>> round_half_up(2.5)
    3
    >>> round_half_up(1704.5)
    1705
    >>> round_half_up(2645, step=10)
    2650
    """
    if step <= 0:
        raise ValueError("step must be a positive integer")

    # Convert via str() to use the float's shortest round-tripping decimal
    # representation (what a human would see), avoiding surprises from the
    # binary floating point representation of e.g. 2.675.
    scaled = Decimal(str(x)) / Decimal(step)
    rounded_units = scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rounded_units) * step
