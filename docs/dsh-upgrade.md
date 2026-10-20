# DSH Upgrade: 0.2.1-rc.2

## Scope

This branch updates the standalone application, not the paper's implementation
or frozen experimental artifacts. The starting published application was
`c3e5caabae3763aee9f641045f822efaa2076e9a`. The upgrade also includes the
application's already implemented Chinese data mapping, solution explorer, and
examples, which were absent from that published snapshot.

The core is a snapshot of the installed application runtime. Its file hashes
are recorded in the release manifest. It is not taken from a dirty research
checkout and is not a claim about reproducing research results under a new model.

## Adaptations

| Area | Updated behavior |
|---|---|
| Host | Official DSH 0.2.1-rc.2 with a full frozen lockfile. |
| Lifecycle | Prompt registration is effect-owned. |
| Settings | Read current locale descriptors, not retired `settings.get()`. |
| Credentials | Read/write version-1 `refs` while preserving other records. |
| Conversation | Read the current chat view from conversation projections. |
| HTTP | Same-origin uploads/results behind official DSH pairing and origin checks. |
| Assets | Include explorer HTML/JS/CSS and license notices in installed wheels. |
| Model | Use the current official `deepseek-flash` route, with Pro disabled. |
| Desktop | Accept official launch links and package a remote client. |
| Installation | One launcher, pinned dependencies, isolated home and service. |

An actual fresh-profile startup, authenticated upload, installed explorer assets,
browser render, and mocked DSH-to-MCP tool call are checked locally. Python and
Node suites cover state, exports, mapping, locale refresh, bridge authentication,
and desktop URL policy. Windows/macOS builds and real-model task quality require
their corresponding environments; no paid API call is part of the offline suite.

## Production rollout

1. Install into a new `MAPLE_HOME` and use unused frontend/backend ports.
2. Pair a browser and enter a key in Settings. Test an initial task, an update,
   plan selection, and a downloaded artifact before switching users.
3. Test a backup copy of existing state separately if historical sessions are
   needed. Never let old and new sidecars write the same state concurrently.
4. Stop the old service only after the new deployment has passed acceptance.
   Keep the old runtime and backup available for rollback.

This migration does not perform the production cutover automatically.

## Local verification

The migration's local regression run passed **75 Python tests** and **15 Node
tests**, including language assembly through the installed official DSH service.
A fresh-profile web smoke covered pairing, cross-origin rejection, Chinese CSV
upload, and the explorer assets installed from a wheel. A local Messages mock
completed a DSH-to-MCP tool call. These checks do not call a paid model.

The packaged Linux client was opened under a virtual display and paired with
the upgraded host. Its logo loaded, connection settings retained only the origin,
and the remote renderer had neither Node integration nor the launcher's IPC
bridge. Linux AppImage and tar.gz packages were built locally. Windows/macOS
native packages remain CI targets, not locally verified downloads.

The intranet launcher also passed an HTTPS check on separate test ports. The
client verified the private CA, paired through the official launch link, loaded
settings and explorer assets through the proxy, and rejected an untrusted Origin.
The production service was left running on its original port throughout testing.
