# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), [SemVer](https://semver.org/).

## [0.1.0] - 2026-09-27

### Added
- OpenCode plugin (`PluginModule`, id `jit-context`) with tools `get_jit_context`, `record_jit_observation`, `get_project_state`.
- System-prompt capsule injection via `experimental.chat.system.transform`. Injects nothing when the project has no data.
- Edit trail via `tool.execute.after`, covering the `apply_patch` metadata shape and `write`/`edit` args.
- L0 SQLite WAL store compatible with the jit-context MCP `session_overlay` schema. Scoped reads, idempotent writes.
- Observatory client with 300 ms fail-open and cross-scope capsule rejection.
- Unit tests (14) and a single-file Bun bundle build.
