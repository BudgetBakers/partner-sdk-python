"""Conformance driver (contract-tests/PROTOCOL.md v1).

Every step goes through the SDK's PUBLIC surface — the driver never issues
HTTP itself. Subcommands: probe | scenario | webhooksig | events.
Invoked as: python -m budgetbakers_partner_sdk.conformance <subcommand>
"""

from __future__ import annotations

import json
import os
import re
import sys
from decimal import Decimal
from typing import Any

from .. import __version__, parse_event, verify
from ..client import BudgetBakers, ClientScope
from ..errors import PartnerApiError

IDENTITY = {"lang": "python", "sdk": "budgetbakers-partner-sdk", "version": __version__}

_VAR_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


class UnresolvedVar(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"unresolved var {name}")
        self.name = name


def _interpolate(args: dict[str, Any], variables: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):

            def _sub(match: re.Match[str]) -> str:
                name = match.group(1)
                if name not in variables:
                    raise UnresolvedVar(name)
                return variables[name]

            out[key] = _VAR_RE.sub(_sub, value)
        else:
            out[key] = value
    return out


def _extract(value: Any, path: str) -> Any:
    current = value
    for token in re.findall(r"[A-Za-z0-9_]+|\[\d+\]", path):
        if token.startswith("["):
            if not isinstance(current, list):
                return None
            index = int(token[1:-1])
            current = current[index] if index < len(current) else None
        elif isinstance(current, dict):
            current = current.get(token)
        else:
            return None
    return current


def _money(value: Any) -> str | None:
    return str(value) if isinstance(value, Decimal) else None


def _account_view(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": account.get("id"),
        "type": account.get("type"),
        "balance": _money(account.get("balance")),
        "currencyCode": account.get("currencyCode"),
        "iban": account.get("iban"),
    }


def _sum(amounts: list[str | None]) -> str:
    total = sum((Decimal(a) for a in amounts if a is not None), Decimal("0"))
    return str(total.quantize(Decimal("0.01")))


def _run_op(  # noqa: C901 — one dispatch table, mirrors PROTOCOL.md 1:1
    bb: BudgetBakers, op: str, args: dict[str, Any], config: dict[str, Any]
) -> Any:
    def scope() -> ClientScope:
        return bb.client(str(args["clientId"]))

    if op == "partner.getConfig":
        return bb.partner.get_config()
    if op == "providers.listAll":
        ids: list[Any] = []
        pages = 0
        for page in bb.providers.pages(country=args.get("country"), limit=args.get("limit")):
            pages += 1
            ids.extend(p.get("id") for p in page.get("data", []))
        return {"count": len(ids), "pages": pages, "ids": ids}
    if op == "clients.create":
        return bb.clients.create(**args)
    if op == "clients.get":
        return bb.clients.get(str(args["clientId"]))
    if op == "clients.getByExternalId":
        return bb.clients.get_by_external_id(str(args["externalId"]))
    if op == "clients.delete":
        scope().delete()
        return {"deleted": True}
    if op == "connectSessions.create":
        return scope().connect_sessions.create(
            str(args["returnUrl"]),
            provider_id=args.get("providerId"),
            connection_id=args.get("connectionId"),
            idempotency_key=args.get("idempotencyKey"),
        )
    if op == "connectSessions.get":
        return scope().connect_sessions.get(str(args["sessionId"]))
    if op == "connectSessions.waitForTerminal":
        states: list[Any] = []
        session = scope().connect_sessions.wait_for_terminal(
            str(args["sessionId"]),
            poll_interval_ms=int(config["pollIntervalMs"]),
            max_polls=int(config["maxPolls"]),
            on_poll=lambda polled: states.append(polled.get("state")),
        )
        return {
            "states": states,
            "state": session.get("state"),
            "connectionId": session.get("connectionId"),
            "resultCode": session.get("resultCode"),
            "error": session.get("error"),
        }
    if op == "connections.create":
        return scope().connections.create(
            str(args["providerId"]), idempotency_key=args.get("idempotencyKey")
        )
    if op == "connections.get":
        return scope().connections.get(str(args["connectionId"]))
    if op == "connections.delete":
        scope().connections.delete(str(args["connectionId"]))
        return {"deleted": True}
    if op == "connections.refresh":
        res = scope().connections.refresh(str(args["connectionId"]))
        return {
            "status": res.get("status"),
            "nextRefreshPossibleAt": res.get("nextRefreshPossibleAt"),
        }
    if op == "connections.reconnect":
        return scope().connections.reconnect(
            str(args["connectionId"]), idempotency_key=args.get("idempotencyKey")
        )
    if op == "connections.revoke":
        scope().connections.revoke(str(args["connectionId"]))
        return {"revoked": True}
    if op == "accounts.list":
        accounts = scope().connections.list_accounts(str(args["connectionId"]))
        return {"count": len(accounts), "accounts": [_account_view(a) for a in accounts]}
    if op == "transactions.listAll":
        amounts: list[str | None] = []
        count = 0
        pages = 0
        for page in scope().accounts.transaction_pages(
            str(args["accountId"]), limit=args.get("limit")
        ):
            pages += 1
            data = page.get("data", [])
            count += len(data)
            amounts.extend(_money(t.get("amount")) for t in data)
        return {"count": count, "pages": pages, "amounts": amounts, "sumAmount": _sum(amounts)}
    raise LookupError(op)


def _scenario_mode() -> int:
    file = os.environ.get("CT_SCENARIO_FILE")
    base_url = os.environ.get("CT_BASE_URL")
    api_key = os.environ.get("CT_API_KEY")
    if file is None or base_url is None or api_key is None:
        print("CT_SCENARIO_FILE, CT_BASE_URL and CT_API_KEY are required", file=sys.stderr)
        return 1
    with open(file, encoding="utf-8") as fh:
        fixture = json.load(fh)
    if fixture.get("protocolVersion") != 1:
        print(json.dumps({"unsupported": f"protocolVersion {fixture.get('protocolVersion')}"}))
        return 3
    config = fixture["driver"]["config"]
    variables: dict[str, str] = dict(fixture.get("vars", {}))
    bb = BudgetBakers(
        api_key,
        base_url=base_url,
        retry_base_ms=int(config["retryBaseMs"]),
        max_retries=int(config["maxRetries"]),
    )

    steps: list[dict[str, Any]] = []
    for step in fixture["driver"]["steps"]:
        entry: dict[str, Any] = {"id": step["id"], "op": step["op"]}
        try:
            args = _interpolate(step.get("args", {}), variables)
            ok = _run_op(bb, step["op"], args, config)
            entry["ok"] = ok
            for name, path in step.get("save", {}).items():
                extracted = _extract(ok, path)
                if extracted is not None:
                    variables[name] = str(extracted)
        except UnresolvedVar as err:
            entry["skipped"] = f"unresolved var {err.name}"
        except PartnerApiError as err:
            entry["error"] = {
                "code": err.code,
                "httpStatus": err.http_status,
                "requestId": err.request_id,
            }
        except LookupError as err:
            print(json.dumps({"unsupported": str(err)}))
            return 3
        except Exception as err:  # noqa: BLE001 — crash entries are the contract
            entry["crash"] = str(err)
        steps.append(entry)

    print(
        json.dumps(
            {
                "protocolVersion": 1,
                "driver": IDENTITY,
                "scenario": fixture["name"],
                "steps": steps,
            }
        )
    )
    return 0


def _webhooksig_mode() -> int:
    file = os.environ.get("CT_FIXTURE_FILE")
    if file is None:
        print("CT_FIXTURE_FILE is required", file=sys.stderr)
        return 1
    with open(file, encoding="utf-8") as fh:
        fixture = json.load(fh)
    results = [
        {
            "name": v["name"],
            "result": verify(v["secrets"], v["header"], v["body"].encode(), v["now"]),
        }
        for v in fixture["verifyVectors"]
    ]
    print(
        json.dumps(
            {"protocolVersion": 1, "driver": IDENTITY, "mode": "webhooksig", "results": results}
        )
    )
    return 0


def _events_mode() -> int:
    file = os.environ.get("CT_FIXTURE_FILE")
    if file is None:
        print("CT_FIXTURE_FILE is required", file=sys.stderr)
        return 1
    with open(file, encoding="utf-8") as fh:
        fixture = json.load(fh)
    results = []
    for vector in fixture["vectors"]:
        parsed = parse_event(vector["body"])
        if parsed["kind"] == "event":
            reason = parsed.get("reason")
            results.append(
                {
                    "name": vector["name"],
                    "kind": "event",
                    "type": parsed["type"],
                    "eventId": parsed["eventId"],
                    "clientId": parsed["clientId"],
                    "connectionId": parsed["connectionId"],
                    "reasonCode": reason.get("code") if isinstance(reason, dict) else None,
                    "extra": parsed["extra"],
                }
            )
        elif parsed["kind"] == "unknown":
            results.append({"name": vector["name"], "kind": "unknown", "type": parsed["type"]})
        else:
            results.append({"name": vector["name"], "kind": "parse_error"})
    print(
        json.dumps({"protocolVersion": 1, "driver": IDENTITY, "mode": "events", "results": results})
    )
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "probe":
        print(json.dumps({"protocolVersion": 1, **IDENTITY}))
        return 0
    if mode == "scenario":
        return _scenario_mode()
    if mode == "webhooksig":
        return _webhooksig_mode()
    if mode == "events":
        return _events_mode()
    print(json.dumps({"unsupported": f"mode {mode}"}))
    return 3


if __name__ == "__main__":
    sys.exit(main())
