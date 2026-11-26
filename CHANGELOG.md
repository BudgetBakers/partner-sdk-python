# Changelog

All notable changes to this SDK are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
SDK adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Earlier versions were distributed only as downloads from the documentation
site.

## [Unreleased]

### Added

- The `refreshState` key of `connections.get`: the state of the newest data
  fetch (`running`, `succeeded` or `failed`), None when none has been recorded.

## [0.3.0] - 2026-11-13

### Added

- The `lastRefreshedAt` and `nextRefreshPossibleAt` keys of `connections.get`:
  the last successful data fetch (create, reconnect or refresh) and the
  earliest time a manual refresh is accepted.
- The `connectionId` key of `connections.refresh`: the connection being
  refreshed.

### Changed

- `connections.create`, `refresh` and `reconnect`, `connect_sessions.create`
  and `get`, and `partner.get_config` read the `{"data": ...}` envelope the
  partner API now answers on `/v2`, and still accept the bare body, so this
  version works before and after the API change. Return types are unchanged.
- `nextRefreshPossibleAt` of `connections.refresh` is `None` after a refresh
  is accepted: the cooldown is known only once the refresh finishes. Read the
  connection after `ConnectionRefreshSuccess`.
- The connection lifecycle actions (`connections.create`, `delete`, `refresh`,
  `reconnect`, `revoke`) call their `/v2` paths. Request bodies are unchanged.

## [0.2.1] - 2026-10-08

### Added

- Published on PyPI as `budgetbakers-partner-sdk`: `pip install
  budgetbakers-partner-sdk` replaces installing the downloaded artifact.
  Your code does not change, and the downloads stay available.
- Registry package metadata: project URLs, classifiers, and the `Apache-2.0`
  license expression with `LICENSE` and `NOTICE` in the wheel.

### Changed

- README rewritten for partners: install, a worked example, webhook
  verification, runtime behavior and links to the documentation site.
- Documentation comments no longer refer to internal design notes.

The client API, webhook verification and error types are unchanged since
0.2.0.
