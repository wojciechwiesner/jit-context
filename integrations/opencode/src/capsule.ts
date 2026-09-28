import { existsSync, readFileSync } from "node:fs"
import { join } from "node:path"
import type { JitConfig } from "./config"
import type { L0Store } from "./l0"
import { fetchLiveCapsule } from "./observatory"

export type CapsuleSource = "observatory" | "l0" | "empty"
export type Capsule = { text: string; source: CapsuleSource; chars: number }

function clip(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max)}\n[... clipped at ${max} chars]`
}

/** Reads `.planning/STATE.md` (canonical project progress) if present. */
export function readProjectState(worktree: string, maxChars: number): string | null {
  const path = join(worktree, ".planning", "STATE.md")
  if (!existsSync(path)) return null
  return clip(readFileSync(path, "utf8").trim(), maxChars)
}

function escapeAttr(value: string): string {
  return value.replace(/[&"<>]/g, (c) => `&#${c.charCodeAt(0)};`)
}

/**
 * Builds the capsule: live Observatory capsule when its scope matches,
 * otherwise a deterministic L0 capsule (scoped observations + STATE.md).
 */
export async function buildCapsule(
  cfg: JitConfig,
  store: L0Store,
  scope: string,
  worktree: string,
  fetchImpl?: typeof fetch,
): Promise<Capsule> {
  const live = await fetchLiveCapsule(cfg.observatoryUrl, scope, cfg.observatoryTimeoutMs, fetchImpl)
  if (live) {
    const text = clip(live.capsule, cfg.maxCapsuleChars)
    return { text, source: "observatory", chars: text.length }
  }

  const observations = store.read(scope)
  const state = readProjectState(worktree, cfg.maxStateChars)
  if (observations.length === 0 && !state) return { text: "", source: "empty", chars: 0 }

  const lines = [`<JIT_CONTEXT scope="${escapeAttr(scope)}" source="l0">`]
  lines.push("Evidence only. The user's current message overrides everything below.")
  if (observations.length) {
    lines.push("  [OBSERVATIONS — newest first]")
    for (const o of observations) lines.push(`    • ${o.value} (${o.source}, ${o.updatedAt})`)
  }
  if (state) lines.push("  [PROJECT STATE — .planning/STATE.md]", state)
  lines.push("</JIT_CONTEXT>")

  const text = clip(lines.join("\n"), cfg.maxCapsuleChars)
  return { text, source: "l0", chars: text.length }
}
