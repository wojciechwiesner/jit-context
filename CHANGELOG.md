# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-09-08

### Added
- **3-Tier Cascade Distillation Engine (`src/context/cascade_distiller.py`)**:
  - LLM Semantic Classifier (Gemini Flash with `thinkingBudget: 0`) delivering sub-1.2s extraction.
  - Verbatim protection of critical contracts (file paths, ports, error messages, export identifiers).
  - Elastic capsule assembler automatically scaling from 750 tokens up to 3,500 tokens based on task complexity.
- **Automated Project Profiler & Ingestion (`/jit init` / `src/init.py`)**:
  - Automatic language, framework, database, and test suite inspection.
  - Bidirectional sync to Obsidian SSOT (`~/Documents/Wojciech/projects/<name>.md`) and `.planning/STATE.md`.
  - Context7 and Hugging Face resource gap detection.
- **Real-Time CLI Telemetry Badges (`src/hooks.py`)**:
  - Direct stderr streaming of active scope, L0/L1 latencies, compilation duration, and capsule character count.
- **Comprehensive Benchmark Suite (`benchmarks/`)**:
  - EXP-005 local model evaluation on Apple Silicon M2 Pro.
  - Clean 1:1 refactoring duel between local Qwen-7B and cloud models on `retro-plumber-run`.
  - Distillation quality and speed comparison across local and cloud engines.

## [0.1.1] - 2026-09-07

### Added
- **EXP-005 Benchmark**: Real-time evaluation of local LLMs on Apple Silicon (M2 Pro 16 GB).
- Script `benchmarks/run_local_model_benchmark.py` evaluating Invariants I1, I3, I5 across:
  - `Qwen2.5-Coder-7B` (Ollama / Metal acceleration)
  - `LFM-2.5-1.2B` (LM Studio / MLX 8-bit)
  - `Mem-Agent` (HuggingFace / MLX 4-bit)
- Verified 100% epistemic correctness (3/3 PASS) for `Qwen2.5-Coder-7B` under JIT Context OS vs 0% (0/3 FAIL) under Naive Haystack, with 2.0x-3.0x inference speedup and ~60% prompt token reduction.

## [0.1.0] - 2026-08-31

### Added
- Initial public release of Hermes JIT Context OS & Borg Broker.
- L0 Hot-Path SQLite WAL overlay engine.
- L1 Scope Hysteresis filter.
- L2 Bounded Deep-Path Broker client.
- Invariants I1–I10 test suite and initial benchmarks (EXP-001..EXP-004).
