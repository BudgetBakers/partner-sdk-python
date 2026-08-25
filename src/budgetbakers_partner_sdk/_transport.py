"""HTTP transport: auth headers, lossless body parsing, typed errors, and
retries with exponential backoff + jitter on 429/5xx honoring Retry-After.
POST is retried only when an Idempotency-Key makes the replay safe."""

from __future__ import annotations

import random
import time
from typing import Any

import httpx

from ._lossless import parse_body
from .errors import PartnerApiUnreachable, parse_error_envelope

_RETRYABLE_METHODS = frozenset({"GET", "DELETE", "PATCH", "PUT"})


class Transport:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        retry_base_ms: int,
        max_retries: int,
        http: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._retry_base_ms = retry_base_ms
        self._max_retries = max_retries
        self._http = http if http is not None else httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        client_id: str | None = None,
        query: dict[str, Any] | None = None,
        body: Any | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers: dict[str, str] = {"Accept": "application/json", "X-Api-Key": self._api_key}
        if client_id is not None:
            headers["X-Client-Id"] = client_id
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        params = {k: v for k, v in (query or {}).items() if v is not None}
        can_retry = method in _RETRYABLE_METHODS or idempotency_key is not None

        attempt = 0
        while True:
            try:
                res = self._http.request(
                    method,
                    self._base_url + path,
                    params=params,
                    json=body,
                    headers=headers,
                )
            except httpx.HTTPError as cause:
                raise PartnerApiUnreachable(str(cause)) from cause

            if res.is_success:
                return parse_body(res.text) if res.text != "" else None

            retryable = res.status_code == 429 or res.status_code >= 500
            if retryable and can_retry and attempt < self._max_retries:
                retry_after = res.headers.get("Retry-After")
                if retry_after is not None and retry_after.isdigit():
                    delay = float(retry_after)
                else:
                    # Exponential backoff with ±25% jitter.
                    delay = (
                        self._retry_base_ms
                        * (2**attempt)
                        * (0.75 + random.random() * 0.5)  # noqa: S311 — jitter, not crypto
                        / 1000.0
                    )
                attempt += 1
                time.sleep(delay)
                continue

            raise parse_error_envelope(res.status_code, res.text, res.headers.get("X-Request-Id"))

    def request_dict(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """request() with the object-body shape asserted (mypy-strict friendly)."""
        result = self.request(method, path, **kwargs)
        return result if isinstance(result, dict) else {}

    def request_list(self, method: str, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        """request() with the raw-array shape asserted (accounts list)."""
        result = self.request(method, path, **kwargs)
        return result if isinstance(result, list) else []
