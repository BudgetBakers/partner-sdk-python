from decimal import Decimal

import httpx
import pytest

from budgetbakers_partner_sdk import BudgetBakers, PartnerApiError, PartnerApiUnreachable

ENVELOPE = '{"errorDesc":"x","error":{"code":"internal_error","message":"m"},"requestId":"req_1"}'


def make_bb(handler: httpx.MockTransport, max_retries: int = 3) -> BudgetBakers:
    return BudgetBakers(
        "sk_test_x",
        base_url="https://partner.test.local",
        retry_base_ms=1,
        max_retries=max_retries,
        http=httpx.Client(transport=handler),
    )


def test_retries_5xx_then_succeeds() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(500, text=ENVELOPE)
        return httpx.Response(200, json={"ok": 1})

    bb = make_bb(httpx.MockTransport(handler))
    assert bb.partner.get_config() == {"ok": 1}
    assert len(calls) == 3


def test_exhausts_retries_into_typed_error() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500, text=ENVELOPE)

    bb = make_bb(httpx.MockTransport(handler))
    with pytest.raises(PartnerApiError) as err:
        bb.partner.get_config()
    assert err.value.code == "internal_error"
    assert err.value.http_status == 500
    assert err.value.request_id == "req_1"
    assert len(calls) == 4  # initial + 3 retries


def test_non_429_4xx_is_never_retried() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            406,
            text='{"error":{"code":"background_refresh_not_allowed","message":"m"},'
            '"requestId":"r"}',
        )

    bb = make_bb(httpx.MockTransport(handler))
    with pytest.raises(PartnerApiError) as err:
        bb.client("c1").connections.refresh("conn1")
    assert err.value.code == "background_refresh_not_allowed"
    assert len(calls) == 1


def test_post_without_idempotency_key_is_not_retried() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500, text=ENVELOPE)

    bb = make_bb(httpx.MockTransport(handler))
    with pytest.raises(PartnerApiError):
        bb.clients.create(externalId="u1")  # upsert create — no Idempotency-Key
    assert len(calls) == 1


def test_headers_and_lossless_money() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text='{"amount":0.10}')

    bb = make_bb(httpx.MockTransport(handler))
    result = bb.client("c1").connections.create("prov1", idempotency_key="k1")
    assert result["amount"] == Decimal("0.10")
    request = seen[0]
    assert request.headers["X-Api-Key"] == "sk_test_x"
    assert request.headers["X-Client-Id"] == "c1"
    assert request.headers["Idempotency-Key"] == "k1"


def test_auto_idempotency_key_is_uuid() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"sessionId": "s", "hostedUrl": "h", "expiresAt": "e"})

    bb = make_bb(httpx.MockTransport(handler))
    bb.client("c1").connect_sessions.create("https://x.test/cb")
    key = seen[0].headers["Idempotency-Key"]
    assert len(key) == 36 and key.count("-") == 4


def test_pagination_until_null_cursor() -> None:
    pages = [
        '{"limit":2,"nextCursor":"c2","data":[{"id":"t1","amount":0.10},'
        '{"id":"t2","amount":0.20}]}',
        '{"limit":2,"nextCursor":null,"data":[{"id":"t3","amount":90071992547409.93}]}',
    ]
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, text=pages[len(urls) - 1])

    bb = make_bb(httpx.MockTransport(handler))
    amounts = [t["amount"] for t in bb.client("c1").accounts.transactions("a1", limit=2)]
    assert [str(a) for a in amounts] == ["0.10", "0.20", "90071992547409.93"]
    assert "nextCursor=c2" in urls[1]


def test_unreachable_wraps_network_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    bb = make_bb(httpx.MockTransport(handler), max_retries=0)
    with pytest.raises(PartnerApiUnreachable):
        bb.partner.get_config()


def test_wait_for_terminal_polls_and_reports() -> None:
    states = ["AwaitingBankSelection", "Fetching", "Completed"]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        state = states[min(len(calls) - 1, len(states) - 1)]
        body: dict = {"sessionId": "s1", "state": state}
        if state == "Completed":
            body.update(connectionId="conn1", resultCode="Ok")
        return httpx.Response(200, json=body)

    bb = make_bb(httpx.MockTransport(handler))
    seen: list[str] = []
    final = bb.client("c1").connect_sessions.wait_for_terminal(
        "s1", poll_interval_ms=1, max_polls=10, on_poll=lambda s: seen.append(s["state"])
    )
    assert seen == states
    assert final["connectionId"] == "conn1"
