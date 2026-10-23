# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), [SemVer](https://semver.org/).

## [0.2.0] - 2026-10-24

### Added
- OpenCode V2 entry `dist/v2.js` (package export `./v2`). Its `{ id, setup }` default export matches the V2 loader contract. Tools are registered via `ctx.tool.transform` with JSON Schema inputs, so nothing from `@opencode/plugin` or `effect` is needed at runtime. The capsule is injected via `ctx.session.hook("context")` and the edit trail via `ctx.tool.hook("execute.after")`. Verified on OpenCode 2.1.4 with a real `opencode run` that called `get_project_state` (status `completed`).
- `touchedFiles` reads the V2 `FileDiff.file` metadata (including `file://` URIs) and the `input.path` fallback.
- 9 tests for the V2 entry, run against a fake host.

### Changed
- `@opencode-ai/plugin` peer dependency is now optional. The V2 entry does not use it.

### Fixed
- OpenCode 2.x refused to load the V1 module ("Plugin must export a default definition with an id and an effect or setup function"). Plugin activation never finished and every server request failed with 503.

## [0.1.0] - 2026-09-28

### Added
- OpenCode plugin (`PluginModule`, id `jit-context`) with tools `get_jit_context`, `record_jit_observation`, `get_project_state`.
- System-prompt capsule injection via `experimental.chat.system.transform`. Injects nothing when the project has no data.
- Edit trail via `tool.execute.after`, covering the `apply_patch` metadata shape and `write`/`edit` args.
- L0 SQLite WAL store compatible with the jit-context MCP `session_overlay` schema. Scoped reads, idempotent writes.
- Observatory client queried with `?project=`, with 300 ms fail-open and cross-scope capsule rejection.
- Unit tests (15) and a single-file Bun bundle build.
- `bench/`: reproducible A/B harness (plugin vs `opencode run --pure`), with results in the README.
