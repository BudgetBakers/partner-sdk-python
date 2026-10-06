"""Decimal-safe JSON parsing. Money is never a float.

v2 serves money as decimal strings ("816.00", or "1.005" when the third
digit carries value); v1 served bare numbers. Both are turned into
``decimal.Decimal`` at the money keys: ``json.loads(parse_float=Decimal)``
keeps fractional literals exact, strings are parsed directly. Amounts are
normalized to two decimal places unless a third one carries value.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

#: Money fields of the partner API (spec: "parse as decimal, never float").
MONEY_KEYS: frozenset[str] = frozenset({"amount", "balance"})

_TWO_DP = Decimal("0.01")


def quantize2(value: Decimal | int | str) -> Decimal:
    """Normalize to exactly two decimal places ("816" -> Decimal('816.00'))."""
    return Decimal(value).quantize(_TWO_DP)


def to_money(value: Decimal | int | str) -> Decimal:
    """Wire amount -> Decimal at 2 dp; a value-carrying third decimal is kept ("1.005")."""
    exact = Decimal(value)
    rounded = exact.quantize(_TWO_DP)
    return rounded if rounded == exact else exact


def _walk(value: Any, key: str | None) -> Any:
    if isinstance(value, Decimal | int) and not isinstance(value, bool):
        if key in MONEY_KEYS:
            return to_money(value)
        # Non-money numbers stay plain (ints stay ints; floats were parsed as
        # Decimal -- collapse them back for ergonomic non-money fields).
        return int(value) if value == int(value) else float(value)
    if isinstance(value, str) and key in MONEY_KEYS:
        return to_money(value)
    if isinstance(value, list):
        return [_walk(item, key) for item in value]
    if isinstance(value, dict):
        return {k: _walk(v, k) for k, v in value.items()}
    return value


def parse_body(text: str) -> Any:
    """Parse an API response body: money keys -> Decimal, rest untouched."""
    return _walk(json.loads(text, parse_float=Decimal), None)
