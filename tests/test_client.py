"""Every operation on /v2, with the {data} envelope unwrapped on reads and
creates; sessions, partner config and the connection lifecycle actions take
both the {data} body and the bare one older API versions answered."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest

from budgetbakers_partner_sdk import BudgetBakers

ANY_OK = {
    "data": {"id": "any", "subscriptionStatus": "Active"},
    "limit": 1,
    "nextCursor": None,
    "sessionId": "s",
    "state": "Completed",
}


def make_bb(handler: Callable[[httpx.Request], httpx.Response]) -> BudgetBakers:
    return BudgetBakers(
        "sk_test_x",
        base_url="https://partner.test.local",
        retry_base_ms=1,
        max_retries=0,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def recording(responses: list[httpx.Response]) -> tuple[list[httpx.Request], Any]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses.pop(0) if responses else httpx.Response(200, json=ANY_OK)

    return seen, handler


@pytest.mark.parametrize(
    ("name", "method", "path", "call"),
    [
        ("partner.get_config", "GET", "/v2/partner/config", lambda bb: bb.partner.get_config()),
        ("providers.pages", "GET", "/v2/providers", lambda bb: next(bb.providers.pages())),
        (
            "clients.create",
            "POST",
            "/v2/clients",
            lambda bb: bb.clients.create(email="u@x.test", countryCode="CZ"),
        ),
        ("clients.get", "GET", "/v2/clients/c1", lambda bb: bb.clients.get("c1")),
        (
            "clients.get_by_external_id",
            "GET",
            "/v2/clients",
            lambda bb: bb.clients.get_by_external_id("u"),
        ),
        ("client.delete", "DELETE", "/v2/clients/c1", lambda bb: bb.client("c1").delete()),
        (
            "connections.get",
            "GET",
            "/v2/connections/x1",
            lambda bb: bb.client("c1").connections.get("x1"),
        ),
        (
            "connections.account_pages",
            "GET",
            "/v2/connections/x1/accounts",
            lambda bb: next(bb.client("c1").connections.account_pages("x1")),
        ),
        ("accounts.get", "GET", "/v2/accounts/a1", lambda bb: bb.client("c1").accounts.get("a1")),
        (
            "accounts.transaction_pages",
            "GET",
            "/v2/accounts/a1/transactions",
            lambda bb: next(bb.client("c1").accounts.transaction_pages("a1")),
        ),
        (
            "connect_sessions.create",
            "POST",
            "/v2/connect-sessions",
            lambda bb: bb.client("c1").connect_sessions.create("https://x.test/cb"),
        ),
        (
            "connect_sessions.get",
            "GET",
            "/v2/connect-sessions/s1",
            lambda bb: bb.client("c1").connect_sessions.get("s1"),
        ),
        (
            "connections.create",
            "POST",
            "/v2/connections",
            lambda bb: bb.client("c1").connections.create("p"),
        ),
        (
            "connections.delete",
            "DELETE",
            "/v2/connections/x1",
            lambda bb: bb.client("c1").connections.delete("x1"),
        ),
        (
            "connections.refresh",
            "POST",
            "/v2/connections/x1/refresh",
            lambda bb: bb.client("c1").connections.refresh("x1"),
        ),
        (
            "connections.reconnect",
            "POST",
            "/v2/connections/x1/reconnect",
            lambda bb: bb.client("c1").connections.reconnect("x1"),
        ),
        (
            "connections.revoke",
            "PATCH",
            "/v2/connections/x1/revoke",
            lambda bb: bb.client("c1").connections.revoke("x1"),
        ),
    ],
)
def test_operation_paths(
    name: str, method: str, path: str, call: Callable[[BudgetBakers], Any]
) -> None:
    seen, handler = recording([])
    call(make_bb(handler))
    assert seen[0].method == method, name
    assert seen[0].url.path == path, name


def test_unwraps_the_data_envelope() -> None:
    seen, handler = recording(
        [
            httpx.Response(201, json={"data": {"id": "c1", "externalId": "u"}}),
            httpx.Response(200, json={"data": {"id": "c1"}}),
            httpx.Response(
                200,
                json={
                    "data": {
                        "id": "x1",
                        "state": "Active",
                        "consentExpiresAt": "2026-10-27T00:00:00Z",
                        "consentRevokedAt": None,
                    }
                },
            ),
            httpx.Response(
                200, text='{"data":{"id":"a1","balance":"0.10","subscriptionStatus":"Active"}}'
            ),
        ]
    )
    bb = make_bb(handler)
    assert bb.clients.create(email="u@x.test", countryCode="CZ", externalId="u")["id"] == "c1"
    assert bb.clients.get("c1")["id"] == "c1"
    assert seen[1].headers["X-Client-Id"] == "c1"
    conn = bb.client("c1").connections.get("x1")
    assert conn == {
        "id": "x1",
        "state": "Active",
        "consentExpiresAt": "2026-10-27T00:00:00Z",
        "consentRevokedAt": None,
    }
    account = bb.client("c1").accounts.get("a1")
    assert account["balance"] == Decimal("0.10")
    assert account["subscriptionStatus"] == "Active"


def test_bare_body_where_the_envelope_is_required_raises() -> None:
    _seen, handler = recording([httpx.Response(201, json={"id": "c1"})])
    with pytest.raises(TypeError, match="envelope"):
        make_bb(handler).clients.create(email="u@x.test", countryCode="CZ")


def test_get_by_external_id_returns_item_or_none() -> None:
    seen, handler = recording(
        [
            httpx.Response(
                200,
                json={"limit": 100, "nextCursor": None, "data": [{"id": "c1", "externalId": "u"}]},
            ),
            httpx.Response(200, json={"limit": 100, "nextCursor": None, "data": []}),
        ]
    )
    bb = make_bb(handler)
    assert bb.clients.get_by_external_id("u") == {"id": "c1", "externalId": "u"}
    assert bb.clients.get_by_external_id("nobody") is None
    assert seen[0].url.params["externalId"] == "u"


def test_list_accounts_walks_every_page() -> None:
    seen, handler = recording(
        [
            httpx.Response(
                200,
                text='{"limit":2,"nextCursor":"acc2","data":[{"id":"a1","balance":"1490.10",'
                '"subscriptionStatus":"Active"},{"id":"a2","balance":"1.005",'
                '"subscriptionStatus":"Disabled"}]}',
            ),
            httpx.Response(
                200,
                text='{"limit":2,"nextCursor":null,"data":[{"id":"a3","balance":null,'
                '"subscriptionStatus":"Active"}]}',
            ),
        ]
    )
    accounts = make_bb(handler).client("c1").connections.list_accounts("x1")
    assert [a["id"] for a in accounts] == ["a1", "a2", "a3"]
    assert [a["balance"] for a in accounts] == [Decimal("1490.10"), Decimal("1.005"), None]
    assert seen[1].url.params["nextCursor"] == "acc2"


def test_transaction_filters_are_encoded_and_variable_symbol_repeats() -> None:
    seen, handler = recording(
        [httpx.Response(200, json={"limit": 1, "nextCursor": None, "data": []})]
    )
    next(
        make_bb(handler)
        .client("c1")
        .accounts.transaction_pages(
            "a1",
            limit=5,
            sort="amount",
            order="asc",
            date_from="2026-07-01",
            record_state="Cleared",
            variable_symbol=["888", "456"],
            since_seq=9002,
        )
    )
    params = seen[0].url.params
    assert params.get_list("variableSymbol") == ["888", "456"]
    assert params["sort"] == "amount"
    assert params["order"] == "asc"
    assert params["dateFrom"] == "2026-07-01"
    assert params["recordState"] == "Cleared"
    assert params["sinceSeq"] == "9002"
    assert params["limit"] == "5"


# The API wraps every single resource in {data}. The methods that used to read a
# bare body take both shapes, so an SDK on either side of the deploy works.
WRAPPED_CONFIG = {
    "partnerId": "p1",
    "name": "Acme",
    "mode": "sandbox",
    "capabilities": {"refresh": True, "reconnect": True},
    "consentDuration": None,
    "countries": ["CZ"],
    "webhook": {"signatureVersion": "v1"},
}
WRAPPED_CREATED = {
    "connectionId": "conn1",
    "redirectUrl": "https://bank.test/auth",
    "expiresAt": "2026-10-01T10:00:00Z",
}
WRAPPED_SESSION = {
    "sessionId": "s1",
    "hostedUrl": "https://connect.test/s1",
    "expiresAt": "2026-10-01T10:00:00Z",
}
WRAPPED_POLLED = {
    "sessionId": "s1",
    "state": "Failed",
    "connectionId": None,
    "resultCode": "Error",
    "error": "provider_unavailable",
}
WRAPPED_REFRESHED = {"connectionId": "conn1", "status": "Accepted", "nextRefreshPossibleAt": None}

WRAPPED_CASES = [
    ("partner.get_config", 200, WRAPPED_CONFIG, lambda bb: bb.partner.get_config()),
    (
        "connect_sessions.create",
        201,
        WRAPPED_SESSION,
        lambda bb: bb.client("c1").connect_sessions.create("https://x.test/cb"),
    ),
    (
        "connect_sessions.get",
        200,
        WRAPPED_POLLED,
        lambda bb: bb.client("c1").connect_sessions.get("s1"),
    ),
    (
        "connections.create",
        200,
        WRAPPED_CREATED,
        lambda bb: bb.client("c1").connections.create("p"),
    ),
    (
        "connections.reconnect",
        200,
        WRAPPED_CREATED,
        lambda bb: bb.client("c1").connections.reconnect("conn1"),
    ),
    (
        "connections.refresh",
        202,
        WRAPPED_REFRESHED,
        lambda bb: bb.client("c1").connections.refresh("conn1"),
    ),
]


@pytest.mark.parametrize(("name", "status", "resource", "call"), WRAPPED_CASES)
def test_envelope_wrapped_body_returns_the_resource(
    name: str, status: int, resource: dict[str, Any], call: Callable[[BudgetBakers], Any]
) -> None:
    _seen, handler = recording([httpx.Response(status, json={"data": resource})])
    assert call(make_bb(handler)) == resource, name


@pytest.mark.parametrize(("name", "status", "resource", "call"), WRAPPED_CASES)
def test_envelope_bare_body_is_returned_as_is(
    name: str, status: int, resource: dict[str, Any], call: Callable[[BudgetBakers], Any]
) -> None:
    _seen, handler = recording([httpx.Response(status, json=resource)])
    assert call(make_bb(handler)) == resource, name


def test_wait_for_terminal_reads_wrapped_sessions() -> None:
    _seen, handler = recording(
        [
            httpx.Response(200, json={"data": {"sessionId": "s1", "state": "Fetching"}}),
            httpx.Response(
                200,
                json={
                    "data": {
                        "sessionId": "s1",
                        "state": "Completed",
                        "connectionId": "conn1",
                        "resultCode": "Ok",
                    }
                },
            ),
        ]
    )
    finished = (
        make_bb(handler)
        .client("c1")
        .connect_sessions.wait_for_terminal("s1", poll_interval_ms=1, max_polls=5)
    )
    assert finished["state"] == "Completed"
    assert finished["connectionId"] == "conn1"
