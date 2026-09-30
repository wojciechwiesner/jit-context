# Changelog

## Unreleased
- chore: `jit-context-os` becomes an automatic read-only mirror of `jit-context/integrations/agent-zero/` (workflow `agent-zero-mirror.yml`); edit the plugin in `jit-context`
- docs: README merges the features, configuration table (real `default_config.yaml` keys) and benchmark snapshot from the previous `jit-context-os` README; `CHANGELOG.md`, `CITATION.cff`, `docs/plans/` and `.planning/` ported from `jit-context-os`

## 0.4.1 — 2026-09-28
- fix: `jev_bridge/judge.py` `tokens()` folds diacritics before tokenizing (Polish text: `połączenie` -> `polaczenie`), fixing judge, rerank and distill
- docs: README names `jit-context` as the source of truth and lists three install paths
- feat: `a0-v<version>` tags in `jit-context` publish `jit_context-<version>.zip`

## 0.4.0 — 2026-09-23
- feat: JEV Bridge merged into jit_context (single plugin; standalone jev_bridge plugin removed)
  - shadow judge (`message_loop_end/_10_shadow_judge.py`) with L2 promotion gate (>=10 evals, 0 harmful, >=30% helpful)
  - eviction advisor (`_20_eviction_advisor.py`) and JEV prefetch (`message_loop_start/_05_jev_prefetch.py`)
  - remote JEV model support (`jev_bridge/jev_remote.py`, TTL cache, I6 safe fallback)
- feat: `/api/plugins/jit_context/jit_status` endpoint (telemetry + issue rules engine)
- feat: live JIT/JEV status bar above chat input (`webui/jit-status-store.js`, `chat-input-progress-start` extension)
- feat: JEV config keys merged into `default_config.yaml` and config UI
- docs: model references updated to Claude latest / Sonnet latest
- docs: live benchmark hub, architecture deep-dive, and JEV System 1 telemetry
- docs: add CITATION.cff (concept DOI 10.5281/zenodo.22649541) + DOI badge
- fix: test_runtime_loader now resolves local repository root dynamically

## 0.3.1 — 2026-09-21
- feat: optional fact_reranker hook in _read_vault_facts_sync (backward-compatible, pool 40, I6 file-order fallback)
