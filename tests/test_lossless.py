from decimal import Decimal

from budgetbakers_partner_sdk._lossless import parse_body, quantize2


def test_money_keys_become_2dp_decimals() -> None:
    parsed = parse_body(
        '{"limit":2,"data":[{"id":"t1","amount":0.10},'
        '{"id":"t2","amount":90071992547409.93}],"balance":1490.1}'
    )
    assert parsed["limit"] == 2
    assert parsed["data"][0]["amount"] == Decimal("0.10")
    assert parsed["data"][1]["amount"] == Decimal("90071992547409.93")
    assert str(parsed["data"][1]["amount"]) == "90071992547409.93"
    assert parsed["balance"] == Decimal("1490.10")


def test_integral_money_is_normalized() -> None:
    parsed = parse_body('{"amount":5,"balance":-2500}')
    assert str(parsed["amount"]) == "5.00"
    assert str(parsed["balance"]) == "-2500.00"


def test_null_money_stays_none_and_sum_is_exact() -> None:
    parsed = parse_body('{"amount":null}')
    assert parsed["amount"] is None
    assert Decimal("0.10") + Decimal("0.20") == Decimal("0.30")


def test_non_money_numbers_stay_plain() -> None:
    parsed = parse_body('{"limit":10,"ratio":1.5,"note":"pay 12.34"}')
    assert parsed["limit"] == 10
    assert parsed["ratio"] == 1.5
    assert parsed["note"] == "pay 12.34"


def test_quantize2() -> None:
    assert str(quantize2("816")) == "816.00"
    assert str(quantize2(Decimal("1490.1"))) == "1490.10"
