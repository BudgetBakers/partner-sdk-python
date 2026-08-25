"""Pinned by the language-neutral vectors in contract-tests/fixtures
(webhooksig.json — sign AND verify; events.json — parsing)."""

import json
from pathlib import Path

import pytest

from budgetbakers_partner_sdk import parse_event, sign, verify

FIXTURES = Path(__file__).resolve().parents[3] / "contract-tests" / "fixtures"

SIG = json.loads((FIXTURES / "webhooksig.json").read_text())
EVENTS = json.loads((FIXTURES / "events.json").read_text())


@pytest.mark.parametrize("vector", SIG["signVectors"], ids=lambda v: v["name"])
def test_sign_vectors(vector: dict) -> None:
    assert sign(vector["secret"], vector["timestamp"], vector["body"]) == vector["expectedHeader"]


@pytest.mark.parametrize("vector", SIG["verifyVectors"], ids=lambda v: v["name"])
def test_verify_vectors(vector: dict) -> None:
    result = verify(vector["secrets"], vector["header"], vector["body"].encode(), vector["now"])
    assert result == vector["expect"]


@pytest.mark.parametrize("vector", EVENTS["vectors"], ids=lambda v: v["name"])
def test_event_vectors(vector: dict) -> None:
    parsed = parse_event(vector["body"])
    expect = vector["expect"]
    assert parsed["kind"] == expect["kind"]
    if parsed["kind"] == "event":
        if "type" in expect:
            assert parsed["type"] == expect["type"]
        if "reasonCode" in expect:
            reason = parsed.get("reason")
            code = reason.get("code") if isinstance(reason, dict) else None
            assert code == expect["reasonCode"]
        if "extra" in expect:
            for key, value in expect["extra"].items():
                assert parsed["extra"][key] == value
    if parsed["kind"] == "unknown" and "type" in expect:
        assert parsed["type"] == expect["type"]


def test_parse_event_never_raises() -> None:
    assert parse_event("")["kind"] == "parse_error"
    assert parse_event("[1,2]")["kind"] == "parse_error"
    assert parse_event('{"type":123}')["kind"] == "unknown"
