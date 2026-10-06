# budgetbakers-partner-sdk

Server SDK for the BudgetBakers Partner AISP API, for Python. One runtime
dependency (httpx); Python ≥ 3.10; fully typed; import name
`budgetbakers_partner_sdk`. Default base URL: `https://aisp-partner.bbapi.io`
(the API key selects sandbox vs live).

## Install

Until the package is on PyPI, download the wheel from the
[downloads page](https://aisp-docs.bbapi.io/guide/downloads) and install it
locally:

```sh
pip install ./budgetbakers_partner_sdk-<version>-py3-none-any.whl
```

Once published, the package name is `budgetbakers-partner-sdk`; your code
does not change.

## Example

```python
import os
from budgetbakers_partner_sdk import BudgetBakers

bb = BudgetBakers(api_key=os.environ["BB_API_KEY"])

# Capability discovery (mode = sandbox|live, decided by the key).
config = bb.partner.get_config()

# Clients upsert by externalId.
client = bb.clients.create(externalId="user-42", email="u42@example.com", countryCode="CZ")

# Client-scoped calls hide the X-Client-Id header.
scope = bb.client(client["id"])

# Hosted connect flow: open hostedUrl in the user's browser, then poll.
session = scope.connect_sessions.create("https://app.example.com/bb-callback")
done = scope.connect_sessions.wait_for_terminal(session["sessionId"])

# Accounts: every page walked (Disabled, unselected accounts included).
accounts = scope.connections.list_accounts(done["connectionId"])

# Cursor pagination as generators; filters and delta sync as keyword arguments.
for tx in scope.accounts.transactions(accounts[0]["id"], since_seq=0):
    ...  # tx["amount"] is a decimal.Decimal - money is never a float.
```

## Webhook verification

```python
# Constant-time verification against ALL active secrets (±300 s),
# typed events; unknown types pass through, never raise (respond 2xx).
from budgetbakers_partner_sdk import parse_event, verify
result = verify(secrets, request.headers["X-BB-Signature"], raw_body)
event = parse_event(raw_body)
```

Verify over the raw request body bytes, before any JSON parsing.

## Behavior

- **Typed errors** - `PartnerApiError.code` is the stable machine code
  (`error.code`); branch on it, never on messages. `request_id` carries the
  `X-Request-Id` correlation id.
- **Retries** - exponential backoff + jitter on 429/5xx honoring
  `Retry-After`; POST retries only under an `Idempotency-Key`
  (auto-UUID on creates, explicit `idempotency_key=` override).
- **Money** - `json.loads(parse_float=Decimal)` + quantization at the
  money keys; amounts are exact `decimal.Decimal`, never float.
- **Nullability** - only `id` is guaranteed on Client/Connection/Account
  payloads (plus `subscriptionStatus` on accounts and `seq`/`createdSeq`/
  `recordDate` on transactions).
- **Paths** - reads and creates call `/v2` and unwrap the `{"data": ...}`
  envelope; the connection lifecycle actions (`connections.create/delete/
  refresh/reconnect/revoke`) call `/v1`, where they live today.
  `clients.get_by_external_id` returns `None` when nothing matches.

## Documentation

Guides and the API reference: <https://aisp-docs.bbapi.io>. Questions:
[integration@budgetbakers.com](mailto:integration@budgetbakers.com).

## Licence

Apache-2.0 (see `LICENSE` and `NOTICE`). Access to the Partner API itself is
governed by the BudgetBakers Partner Terms of Service.
