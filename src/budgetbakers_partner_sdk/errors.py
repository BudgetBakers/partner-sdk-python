"""Error model (spec/partner-api-v1.1.yaml).

Every error response carries a stable machine-readable ``error.code``.
Branch on the code only -- never parse ``errorDesc`` strings.
"""

from __future__ import annotations

import json

KNOWN_CODES: frozenset[str] = frozenset(
    {
        "validation_error",
        "unauthorized",
        "capability_disabled",
        "operation_temporarily_unavailable",
        "connection_not_recoverable",
        "consent_inactive",
        "not_found",
        "refresh_in_progress",
        "refresh_cooldown",
        "refresh_quota_exceeded",
        "background_refresh_not_allowed",
        "rate_limited",
        "internal_error",
    }
)


class PartnerApiError(Exception):
    """A typed partner API error (non-2xx with the v1.1 error envelope)."""

    def __init__(
        self,
        code: str,
        http_status: int,
        request_id: str | None,
        message: str,
        next_refresh_possible_at: str | None = None,
    ) -> None:
        super().__init__(f"{code} (HTTP {http_status}): {message}")
        #: Stable machine code -- the only thing to branch on.
        self.code = code
        self.http_status = http_status
        #: Correlation id (X-Request-Id header / body requestId), for support.
        self.request_id = request_id
        #: Present on refresh_cooldown / refresh_quota_exceeded.
        self.next_refresh_possible_at = next_refresh_possible_at


class PartnerApiUnreachable(Exception):
    """Network-level failure -- the API endpoint was not reachable at all."""


def _status_fallback(status: int) -> str:
    """Fallbacks for gateway-shaped errors without the envelope (Kong 401/429)."""
    if status == 401:
        return "unauthorized"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    return "internal_error"


def parse_error_envelope(
    status: int, body_text: str, header_request_id: str | None
) -> PartnerApiError:
    """Build a typed error from a non-2xx response body + headers."""
    code = _status_fallback(status)
    message = f"HTTP {status}"
    request_id = header_request_id
    next_refresh: str | None = None
    try:
        body = json.loads(body_text)
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            raw_code = error.get("code")
            if isinstance(raw_code, str) and raw_code in KNOWN_CODES:
                code = raw_code
            if isinstance(error.get("message"), str):
                message = error["message"]
            if isinstance(error.get("nextRefreshPossibleAt"), str):
                next_refresh = error["nextRefreshPossibleAt"]
        if request_id is None and isinstance(body, dict) and isinstance(body.get("requestId"), str):
            request_id = body["requestId"]
    except (json.JSONDecodeError, ValueError):
        pass  # Non-JSON error body (gateway) -- keep the status-derived fallback.
    return PartnerApiError(code, status, request_id, message, next_refresh)
