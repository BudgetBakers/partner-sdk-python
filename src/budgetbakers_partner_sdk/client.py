"""The SDK surface, mirroring @budgetbakers/partner-sdk:
client-scoped ergonomics hiding X-Client-Id, generator-based cursor
pagination, automatic Idempotency-Key on creates (explicit override), and a
connect-session polling helper. Reads and creates live on /v2; the
connection lifecycle actions live on /v1.
Amounts are decimal.Decimal — never float."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import quote

import httpx

from ._transport import Transport

# The production partner edge; sandbox vs live is selected by the key.
DEFAULT_BASE_URL = "https://aisp-partner.bbapi.io"

_TERMINAL_STATES = frozenset({"Completed", "Failed", "Cancelled", "Expired"})

JsonDict = dict[str, Any]


def _q(value: str) -> str:
    return quote(value, safe="")


def _pages(fetch_page: Callable[[str | None], JsonDict]) -> Iterator[JsonDict]:
    cursor: str | None = None
    while True:
        page = fetch_page(cursor)
        yield page
        next_cursor = page.get("nextCursor")
        if not isinstance(next_cursor, str):
            return
        cursor = next_cursor


class _Connections:
    def __init__(self, transport: Transport, client_id: str) -> None:
        self._t = transport
        self._cid = client_id

    # Lifecycle actions (create, delete, refresh, reconnect, revoke) live on /v1.
    def create(self, provider_id: str, *, idempotency_key: str | None = None) -> JsonDict:
        return self._t.request_dict(
            "POST",
            "/v1/connections",
            client_id=self._cid,
            body={"providerId": provider_id},
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )

    def get(self, connection_id: str) -> JsonDict:
        """The stored connection record: state, provider, consent expiry."""
        return self._t.request_data(
            "GET", f"/v2/connections/{_q(connection_id)}", client_id=self._cid
        )

    def delete(self, connection_id: str) -> None:
        self._t.request_dict("DELETE", f"/v1/connections/{_q(connection_id)}", client_id=self._cid)

    def refresh(self, connection_id: str) -> JsonDict:
        return self._t.request_dict(
            "POST", f"/v1/connections/{_q(connection_id)}/refresh", client_id=self._cid
        )

    def reconnect(self, connection_id: str, *, idempotency_key: str | None = None) -> JsonDict:
        return self._t.request_dict(
            "POST",
            f"/v1/connections/{_q(connection_id)}/reconnect",
            client_id=self._cid,
            body={},
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )

    def revoke(self, connection_id: str) -> None:
        """Idempotent: revoking an already-Inactive connection is a no-op 200."""
        self._t.request_dict(
            "PATCH", f"/v1/connections/{_q(connection_id)}/revoke", client_id=self._cid
        )

    def account_pages(self, connection_id: str, *, limit: int | None = None) -> Iterator[JsonDict]:
        """Page-level iteration when you need cursors/limits."""
        return _pages(
            lambda cursor: self._t.request_dict(
                "GET",
                f"/v2/connections/{_q(connection_id)}/accounts",
                client_id=self._cid,
                query={"limit": limit, "nextCursor": cursor},
            )
        )

    def list_accounts(self, connection_id: str) -> list[JsonDict]:
        """Every account of the connection, all pages walked; Disabled ones included."""
        accounts: list[JsonDict] = []
        for page in self.account_pages(connection_id):
            accounts.extend(page.get("data", []))
        return accounts


class _Accounts:
    def __init__(self, transport: Transport, client_id: str) -> None:
        self._t = transport
        self._cid = client_id

    def get(self, account_id: str) -> JsonDict:
        return self._t.request_data("GET", f"/v2/accounts/{_q(account_id)}", client_id=self._cid)

    def transaction_pages(
        self,
        account_id: str,
        *,
        limit: int | None = None,
        sort: str | None = None,
        order: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        record_state: str | None = None,
        variable_symbol: list[str] | None = None,
        since_seq: int | None = None,
        since_created_seq: int | None = None,
    ) -> Iterator[JsonDict]:
        """Page-level iteration (keyset cursor until nextCursor is null).

        ``sort`` is ``recordDate`` (default) or ``amount``; ``order`` ``desc`` or
        ``asc``; ``date_from``/``date_to`` are inclusive ``YYYY-MM-DD`` bounds on
        recordDate; ``variable_symbol`` filters on details.variableSymbol (up to
        20 values); ``since_seq``/``since_created_seq`` are the delta feeds and
        combine only with ``limit``."""
        return _pages(
            lambda cursor: self._t.request_dict(
                "GET",
                f"/v2/accounts/{_q(account_id)}/transactions",
                client_id=self._cid,
                query={
                    "limit": limit,
                    "sort": sort,
                    "order": order,
                    "dateFrom": date_from,
                    "dateTo": date_to,
                    "recordState": record_state,
                    "variableSymbol": variable_symbol,
                    "sinceSeq": since_seq,
                    "sinceCreatedSeq": since_created_seq,
                    "nextCursor": cursor,
                },
            )
        )

    def transactions(self, account_id: str, **params: Any) -> Iterator[JsonDict]:
        """Iterate every transaction across pages (same keyword filters as transaction_pages)."""
        for page in self.transaction_pages(account_id, **params):
            yield from page.get("data", [])


class _ConnectSessions:
    def __init__(self, transport: Transport, client_id: str) -> None:
        self._t = transport
        self._cid = client_id

    def create(
        self,
        return_url: str,
        *,
        provider_id: str | None = None,
        connection_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> JsonDict:
        """`connection_id` reconnects that connection instead of creating one; the
        bank picker is then skipped, so do not also pass `provider_id`."""
        body: JsonDict = {"returnUrl": return_url}
        if provider_id is not None:
            body["providerId"] = provider_id
        if connection_id is not None:
            body["connectionId"] = connection_id
        return self._t.request_dict(
            "POST",
            "/v2/connect-sessions",
            client_id=self._cid,
            body=body,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )

    def get(self, session_id: str) -> JsonDict:
        return self._t.request_dict(
            "GET", f"/v2/connect-sessions/{_q(session_id)}", client_id=self._cid
        )

    def wait_for_terminal(
        self,
        session_id: str,
        *,
        poll_interval_ms: int = 2000,
        max_polls: int = 150,
        on_poll: Callable[[JsonDict], None] | None = None,
    ) -> JsonDict:
        """Poll until the session reaches a terminal state (or max_polls)."""
        session: JsonDict = {}
        for poll in range(max_polls):
            if poll > 0:
                time.sleep(poll_interval_ms / 1000.0)
            session = self.get(session_id)
            if on_poll is not None:
                on_poll(session)
            if session.get("state") in _TERMINAL_STATES:
                return session
        return session


class ClientScope:
    """Everything scoped to one end user (X-Client-Id header)."""

    def __init__(self, transport: Transport, client_id: str) -> None:
        self.client_id = client_id
        self._t = transport
        self.connections = _Connections(transport, client_id)
        self.accounts = _Accounts(transport, client_id)
        self.connect_sessions = _ConnectSessions(transport, client_id)

    def delete(self) -> None:
        """Delete this client and cascade to their connections, accounts and transactions."""
        self._t.request_dict(
            "DELETE", f"/v2/clients/{_q(self.client_id)}", client_id=self.client_id
        )


class _Clients:
    def __init__(self, transport: Transport) -> None:
        self._t = transport

    def create(self, **fields: Any) -> JsonDict:
        """Create ``email=``, ``countryCode=`` and optionally ``externalId=``; upserts by
        externalId, so an existing externalId returns the existing client."""
        return self._t.request_data("POST", "/v2/clients", body=fields)

    def get(self, client_id: str) -> JsonDict:
        return self._t.request_data("GET", f"/v2/clients/{_q(client_id)}", client_id=client_id)

    def get_by_external_id(self, external_id: str) -> JsonDict | None:
        """Exact match on your externalId; None when no client carries it."""
        page = self._t.request_dict("GET", "/v2/clients", query={"externalId": external_id})
        data = page.get("data", [])
        return data[0] if isinstance(data, list) and data else None


class _Providers:
    def __init__(self, transport: Transport) -> None:
        self._t = transport

    def pages(
        self,
        *,
        country: str | None = None,
        search: str | None = None,
        limit: int | None = None,
    ) -> Iterator[JsonDict]:
        return _pages(
            lambda cursor: self._t.request_dict(
                "GET",
                "/v2/providers",
                query={"country": country, "search": search, "limit": limit, "nextCursor": cursor},
            )
        )

    def list(
        self,
        *,
        country: str | None = None,
        search: str | None = None,
        limit: int | None = None,
    ) -> Iterator[JsonDict]:
        """Iterate every provider across pages."""
        for page in self.pages(country=country, search=search, limit=limit):
            yield from page.get("data", [])


class _Partner:
    def __init__(self, transport: Transport) -> None:
        self._t = transport

    def get_config(self) -> JsonDict:
        """Capability discovery — self-description of the calling partner + key mode."""
        return self._t.request_dict("GET", "/v2/partner/config")


class BudgetBakers:
    """BudgetBakers Partner API client.

    Example::

        bb = BudgetBakers(api_key=os.environ["BB_API_KEY"])
        client = bb.clients.create(email="user@example.com", countryCode="CZ", externalId="user-42")
        scope = bb.client(client["id"])
        session = scope.connect_sessions.create("https://app.example.com/bb-callback")
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        retry_base_ms: int = 500,
        max_retries: int = 3,
        http: httpx.Client | None = None,
    ) -> None:
        self._transport = Transport(base_url, api_key, retry_base_ms, max_retries, http)
        self.clients = _Clients(self._transport)
        self.providers = _Providers(self._transport)
        self.partner = _Partner(self._transport)

    def client(self, client_id: str) -> ClientScope:
        """Scope every client-bound call to one end user."""
        return ClientScope(self._transport, client_id)

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> BudgetBakers:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
