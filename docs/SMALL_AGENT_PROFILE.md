# Small-agent profile: local 2-9B workers on JIT/JEV Context OS

One Hermes profile (`small`) plus a JIT capsule mode that lets a local model (LFM 2.5 2.6B,
qwen2.5-coder 7B, Qwen 9B on Ollama, Metal) do bounded coding work with project memory.

## Wiring

```
hermes -p small  (model lfm2.5:2.6b-64k @ 127.0.0.1:11434, ctx 64k)
 ├─ system prompt   ~9.9k chars: SOUL (8 rules) + AGENTS.md; no MEMORY/USER dump, no skills index
 ├─ tools (6)       read_file, search_files, patch, write_file, terminal, skill_view
 │                  + mcp mem-agent.use_memory_agent  (Obsidian vault, Borg LLM gateway)
 │                  + mcp jit-context.get_project_state / record_jit_observation
 │                  tool_search bridge OFF (small models loop on tool_describe)
 └─ ona-context plugin (pre_llm_call, every turn)
     ├─ L0 overlay: session cwd -> project scope (falls back to profile state.db cwd)
     ├─ JEV facts / invariants / verified proofs (same as large models)
     └─ small_model profile (model= from hook): + CONTEXT_SMALL.md brief
                                                + 6 ranked skill pointers, cap 4.8k chars
```

Project setup: `jit init . --profile small` writes `.planning/CONTEXT_SMALL.md` (<=2k chars)
and `.planning/jit.json`. Delegation fallback chain ends at `ollama/lfm2.5:2.6b-64k`.

## Tool choice (data, 30 days, 142k tool calls)

| tool | share | cumulative |
|---|---|---|
| terminal | 60.4% | 60.4% |
| read_file | 19.3% | 79.7% |
| search_files | 6.3% | 86.0% |
| patch | 4.6% | 90.6% |
| write_file | 3.0% | 93.5% |

Five tools cover 93.5% of real usage; `skill_view` and two MCP tools add memory access.

## Measured (Mac mini M2 Pro, lfm2.5:2.6b-64k)

| run | default profile | small profile |
|---|---|---|
| fixed system prompt | 92k chars, 39 tools / 72 KB schemas | 9.9k chars, 6 tools / 12 KB |
| read file + answer | 158 s, 21.8k input tok | 28 s, 13.9k input tok, JIT scope jit-context |
| Obsidian lookup (mem-agent) | n/a | 57 s, correct (gateway); free-tier Gemini was 429 |
| patch + pytest + report (worktree) | timed out at 252 s | 50 s, correct diff, 7 passed |

## Where small workers fit

Good: single-file edits with a test command, grep/read/explain, mechanical refactors,
STATE.md / CHANGELOG upkeep, log triage, cockpit regen, 429/offline fallback, private code
that must not leave the machine, high-volume cheap loops (lint fix, rename, docstring).

Not good: multi-file design, ambiguous specs, security review, UI work needing vision,
anything that needs >8 tool turns of planning. Route those to Gemini / Opus tiers.

## Gotchas

- A worktree run must set `TERMINAL_CWD=<worktree>`; otherwise relative paths resolve to
  the parent shell's repo (observed: edit landed in the main checkout).
- Profiles read plugins from their own home; `jit install` now links `ona-context` into every
  profile listing it in `plugins.enabled`.
- mem-agent auto-discovers `GOOGLE_API_KEY` and pins the Gemini free tier (20 req/day);
  `MEM_AGENT_LLM_BASE_URL` / `MEM_AGENT_LLM_API_KEY` override it (set in the profile).
- Ollama tags can disappear (`lfm2.5:2.6b-128k`, `8b-a1b` were removed 2026-10-08 23:52);
  the profile and fallback chain pin `lfm2.5:2.6b-64k`, which exists.
