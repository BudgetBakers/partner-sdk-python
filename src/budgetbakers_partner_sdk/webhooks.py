"""Webhook signature verification + typed event parsing.

Signature (spec/webhooks-v2.yaml, pinned by contract-tests/fixtures/
webhooksig.json)::

    X-BB-Signature: t=<unix-ts>,v1=<hex HMAC_SHA256(secret, "{t}." + raw_body)>

Constant-time comparison against every active secret (two during rotation),
±300 s timestamp window, collect every v1 entry, ignore unknown scheme keys.
No home-grown deviations (CLAUDE.md rule 6).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any, Literal

SIGNATURE_HEADER = "X-BB-Signature"
TOLERANCE_SECONDS = 300

VerifyResult = Literal[
    "valid", "invalid_signature", "timestamp_out_of_tolerance", "malformed_header"
]

_HEX_32_BYTES = re.compile(r"^[0-9a-fA-F]{64}$")
_DIGITS = re.compile(r"^[0-9]+$")

EVENT_TYPES: frozenset[str] = frozenset(
    {
        "AuthenticationStarted",
        "AuthenticationSuccess",
        "AuthenticationFailed",
        "AuthenticationCanceled",
        "AccountsFetchingStarted",
        "AccountsFetchingSuccess",
        "AccountsFetchingFailed",
        "TransactionsFetchingStarted",
        "TransactionsFetchingSuccess",
        "TransactionsFetchingFailed",
        "ConnectionCreateSuccess",
        "ConnectionCreateFailed",
        "ConnectionRefreshSuccess",
        "ConnectionRefreshFailed",
        "ConnectionDeleted",
        "ConnectionConsentRevoked",
        "ConnectionConsentExpired",
    }
)

_KNOWN_FIELDS = frozenset({"eventId", "type", "clientId", "connectionId", "createdAt", "reason"})


def _digest(secret: str, ts: str, raw_body: bytes) -> bytes:
    return hmac.new(secret.encode(), f"{ts}.".encode() + raw_body, hashlib.sha256).digest()


def sign(secret: str, ts: int, raw_body: bytes | str) -> str:
    """Sign raw_body at unix time ts; returns the full header value (tooling use)."""
    body = raw_body.encode() if isinstance(raw_body, str) else raw_body
    t = str(int(ts))
    return f"t={t},v1={_digest(secret, t, body).hex()}"


def _parse_header(header: str) -> tuple[str, list[bytes]] | None:
    if header == "":
        return None
    ts = ""
    sigs: list[bytes] = []
    for element in header.split(","):
        eq = element.find("=")
        if eq <= 0:
            return None
        key, value = element[:eq], element[eq + 1 :]
        if value == "":
            return None
        if key == "t":
            if ts != "" or not _DIGITS.match(value):
                return None
            ts = value
        elif key == "v1":
            if not _HEX_32_BYTES.match(value):
                return None
            sigs.append(bytes.fromhex(value))
        # Unknown scheme keys are ignored (forward compatibility).
    if ts == "" or not sigs:
        return None
    return ts, sigs


def verify(
    secrets: list[str],
    header: str,
    raw_body: bytes | str,
    now: float | None = None,
) -> VerifyResult:
    """Verify a delivery against ALL active secrets (two during rotation)."""
    parsed = _parse_header(header)
    if parsed is None:
        return "malformed_header"
    ts, sigs = parsed
    now_unix = int(now if now is not None else time.time())
    if abs(now_unix - int(ts)) > TOLERANCE_SECONDS:
        return "timestamp_out_of_tolerance"
    body = raw_body.encode() if isinstance(raw_body, str) else raw_body
    for secret in secrets:
        expected = _digest(secret, ts, body)
        for sig in sigs:
            if hmac.compare_digest(sig, expected):
                return "valid"
    return "invalid_signature"


def parse_event(raw_body: bytes | str) -> dict[str, Any]:
    """Parse a delivery body into a typed event. NEVER raises.

    Returns one of::

        {"kind": "event", "type", "eventId", "clientId", "connectionId",
         "createdAt", "reason", "extra"}
        {"kind": "unknown", "type", "raw"}      # respond 2xx and ignore (D11)
        {"kind": "parse_error", "message"}
    """
    text = raw_body.decode("utf-8", errors="replace") if isinstance(raw_body, bytes) else raw_body
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as err:
        return {"kind": "parse_error", "message": str(err)}
    if not isinstance(raw, dict):
        return {"kind": "parse_error", "message": "webhook body is not a JSON object"}
    event_type = raw.get("type") if isinstance(raw.get("type"), str) else ""
    if event_type not in EVENT_TYPES:
        return {"kind": "unknown", "type": event_type, "raw": raw}
    return {
        "kind": "event",
        "type": event_type,
        "eventId": str(raw.get("eventId", "")),
        "clientId": str(raw.get("clientId", "")),
        "connectionId": str(raw.get("connectionId", "")),
        "createdAt": str(raw.get("createdAt", "")),
        "reason": raw.get("reason"),
        "extra": {k: v for k, v in raw.items() if k not in _KNOWN_FIELDS},
    }
