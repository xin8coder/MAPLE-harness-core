# Desktop and Language Support

## Host compatibility

This application targets official DSH **0.2.1-rc.2**, upstream commit
`687f282e8625c6b8d11ff58211a90524be2e4317`:
[release](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.1-rc.2).
The host is installed from its official npm distribution with a committed pnpm
lockfile. MAPLE uses public plugin, MCP, settings, conversation, and web-server
interfaces. It does not patch installed upstream JavaScript files.

The official DSH Desktop bundles its own host. Its plugin compatibility must be
checked against that host's version rather than inferred from an Electron version.
The client here is a separate **remote MAPLE client**, not a build of the official
desktop application and not a self-contained local optimizer.

## MAPLE remote desktop

The `desktop/` package uses Electron **44.7.0** and electron-builder **26.17.0**.
Chat, uploads, progress, solution selection, downloads, and state live on the
connected MAPLE server. Closing the window does not stop optimization on that
server. A running server with a configured API key is required.

Build on the target platform with Node.js 22.19+ or 24+:

```bash
cd desktop
npm ci
npm test
npm start
npm run dist
```

Linux targets are AppImage and tar.gz, Windows uses NSIS, and macOS uses DMG and
ZIP. `.github/workflows/desktop.yml` builds each on its native runner. Producing a
local Linux package does not establish Windows/macOS test coverage or signing.
Signing certificates and automatic updates are not bundled in this release.

The connection window accepts an HTTPS server origin or the private launch link
printed by DSH. HTTP is allowed only for loopback development. Only the origin is
saved in `connection.json`; launch tokens are not written there. The official
browser session persists in the client's isolated Electron partition.

For a private CA, verify the displayed certificate fingerprint with the server
administrator or install the verified CA certificate. A one-launch trust decision
is restricted to the selected origin. There is no global certificate bypass.

Remote pages use sandboxing and context isolation, with no Node integration or
launcher IPC bridge. Only the local connection window can change its settings.
Navigation remains on the connected origin, external links are HTTPS-only, and
artifact downloads use the native save dialog.

## Language and data mapping

English and Simplified Chinese are supported. The MAPLE settings control shares
official DSH's durable locale preference. The language instruction is read anew
for each model step: the latest user message determines response language, with
the UI preference used for language-neutral messages. Chinese input therefore
does not require an extra instruction asking for Chinese output.

The UI translates its own labels and charts, not historical chat, code, raw data,
or entity identifiers. `liveopt_map_data` uses the LLM for reversible schema
aliases and validates that field mapping does not change values or units.
Localized exports retain the original names and an explicit mapping dictionary.
The desktop launcher's language affects its native connection page and menus;
it does not silently overwrite the server's application preference.

## Upgrade boundary

The new application uses a separate `MAPLE_HOME` and service name. Existing
production profiles, paper code, and experiment caches remain unchanged. Offline
verification covers API compatibility and data/result behavior. It does not
claim that a mock response proves the paid model's task accuracy.
