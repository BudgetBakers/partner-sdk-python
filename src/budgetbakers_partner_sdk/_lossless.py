"""Decimal-safe JSON parsing. Money is never a float.

``json.loads(parse_float=Decimal)`` keeps fractional amounts exact; integral
amounts arrive as ``int`` and are normalized at the money keys. Every money
value is quantized to exactly two decimal places.
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


def _walk(value: Any, key: str | None) -> Any:
    if isinstance(value, Decimal | int) and not isinstance(value, bool):
        if key in MONEY_KEYS:
            return quantize2(value)
        # Non-money numbers stay plain (ints stay ints; floats were parsed as
        # Decimal -- collapse them back for ergonomic non-money fields).
        return int(value) if value == int(value) else float(value)
    if isinstance(value, list):
        return [_walk(item, key) for item in value]
    if isinstance(value, dict):
        return {k: _walk(v, k) for k, v in value.items()}
    return value


def parse_body(text: str) -> Any:
    """Parse an API response body: money keys -> 2-dp Decimal, rest untouched."""
    return _walk(json.loads(text, parse_float=Decimal), None)
