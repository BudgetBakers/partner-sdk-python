# budgetbakers-partner-sdk

BudgetBakers Partner API server SDK (Python, WP4.2). Spec:
`spec/partner-api-v1.1.yaml` (single source of truth, D9). One runtime
dependency (httpx); Python ≥ 3.10; import name `budgetbakers_partner_sdk`.

```python
import os
from budgetbakers_partner_sdk import BudgetBakers

bb = BudgetBakers(api_key=os.environ["BB_API_KEY"])

# Capability discovery (mode = sandbox|live, decided by the key).
config = bb.partner.get_config()

# Clients upsert by externalId.
client = bb.clients.create(externalId="user-42")

# Client-scoped calls hide the X-Client-Id header.
scope = bb.client(client["id"])

# Hosted connect flow: hand hostedUrl to the browser / Link SDK, then poll.
session = scope.connect_sessions.create("https://app.example.com/bb-callback")
done = scope.connect_sessions.wait_for_terminal(session["sessionId"])

# Cursor pagination as generators.
for tx in scope.accounts.transactions(account_id):
    ...  # tx["amount"] is a 2-dp decimal.Decimal — money is never a float.

# Webhooks: constant-time verification against ALL active secrets (±300 s),
# typed events; unknown types pass through, never raise (respond 2xx).
from budgetbakers_partner_sdk import parse_event, verify
result = verify(secrets, request.headers["X-BB-Signature"], raw_body)
event = parse_event(raw_body)
```

Behavior guarantees (DESIGN.md §9.1), mirroring the TypeScript SDK:

- **Typed errors** — `PartnerApiError.code` is the stable machine code
  (`error.code`); never parse `errorDesc`. `request_id` carries the
  `X-Request-Id` correlation id.
- **Retries** — exponential backoff + jitter on 429/5xx honoring
  `Retry-After`; POST retries only under an `Idempotency-Key`
  (auto-UUID on creates, explicit `idempotency_key=` override).
- **Money** — `json.loads(parse_float=Decimal)` + 2-dp quantization at the
  money keys; amounts are exact `decimal.Decimal`, never float.
- **Nullability** — only `id` is guaranteed on Client/Connection/Account/
  Transaction payloads.

## Development (uv)

```sh
make venv    # uv sync → .venv
make test    # pytest: units + webhooksig/events vectors from contract-tests
make lint    # ruff + mypy --strict
```

Release gate: `make contract-matrix` at the repo root — the conformance
driver (`python -m budgetbakers_partner_sdk.conformance`,
`contract-tests/PROTOCOL.md`) must pass all 9 sandbox scenarios. Publishing to
PyPI is a manual handoff.
