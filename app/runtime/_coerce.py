"""Lenient scalar coercion for policy/config values (shared runtime helpers)."""

from __future__ import annotations


def as_float(value: object, default: float) -> float:
    """Coerce a policy value to float, falling back to ``default``."""
    if isinstance(value, bool | None):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default


def as_int(value: object, default: int) -> int:
    """Coerce a policy value to int, falling back to ``default``."""
    if isinstance(value, bool | None):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default
