# Project State: hermes-jit-context-os-v0.1

## Active Goal
Align published JIT Context guarantees with verified runtime behavior.

## Remediation Plan
- Plan: `docs/plans/2026-09-08-promise-to-proof-remediation.md`
- Baseline: v0.2.4 / `35181df`; pre-existing dirty `src/hooks.py` preserved.
- Implementation in progress (52/52 tests passing in sandbox, doctor 10/10 PASS).
- [x] G0: Label synthetic evidence (EXP-001..004), define invariant contracts, port hermetic fixtures.
- [x] G1: Repair provenance boundaries (T03), typed tool results & lifecycle (T04), literal fidelity & cleaner containment (T05), safe modes (T06).
- [x] G2: Scope persistence across turns, L2 fact retention, path traversal containment, hard capsule budget.
- [ ] G3: Verify packaging, CLI entrypoints, health server decoupling and CI.
- [x] G4: Deliver provenance-backed four-section coding capsule (Dev Runtime, Working Set, L0 Proofs, Active Invariants, Pointers; calibrated 800-1800 tok sweet spot).
- [ ] G5: Run and independently review equal-information paired benchmarks.
- [ ] G6: Evidence-linked release and separately approved canary.

## Historical Milestone (not verified as complete)
Hermes JIT Context OS v0.2 with Dynamic LLM Distillation and Multimodal Ingestion

## Tech Stack
- Languages: 
- Frameworks: 

## Tasks & Phases
- [x] Phase 0: Repository Profiling & JIT Context Initialization (`/jit init`)
- [ ] Phase 1: Core Implementation & Test Harness
- [ ] Phase 2: Runtime Verification & Deployment
