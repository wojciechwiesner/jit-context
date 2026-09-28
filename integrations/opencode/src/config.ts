import { homedir } from "node:os"
import { basename, join } from "node:path"

export type JitConfig = {
  observatoryUrl: string
  observatoryTimeoutMs: number
  dbPath: string
  injectSystemCapsule: boolean
  autoRecordTools: string[]
  maxCapsuleChars: number
  maxStateChars: number
}

const DEFAULTS: JitConfig = {
  observatoryUrl: "http://127.0.0.1:8765",
  observatoryTimeoutMs: 300,
  dbPath: join(homedir(), ".hermes/state/ona-context/session_overlay.db"),
  injectSystemCapsule: true,
  autoRecordTools: ["edit", "write", "patch", "multiedit", "apply_patch"],
  maxCapsuleChars: 6000,
  maxStateChars: 2500,
}

function expandHome(p: string): string {
  return p.startsWith("~/") ? join(homedir(), p.slice(2)) : p
}

/** Precedence: plugin options (opencode.json) > env vars > defaults. */
export function resolveConfig(
  options: Record<string, unknown> = {},
  env: Record<string, string | undefined> = process.env,
): JitConfig {
  const pick = <K extends keyof JitConfig>(key: K, envValue?: JitConfig[K]): JitConfig[K] =>
    (options[key] as JitConfig[K] | undefined) ?? envValue ?? DEFAULTS[key]

  return {
    observatoryUrl: pick("observatoryUrl", env.JIT_OBSERVATORY_URL).replace(/\/$/, ""),
    observatoryTimeoutMs: pick("observatoryTimeoutMs"),
    dbPath: expandHome(pick("dbPath", env.JIT_L0_DB_PATH)),
    injectSystemCapsule: pick(
      "injectSystemCapsule",
      env.JIT_INJECT === undefined ? undefined : env.JIT_INJECT !== "0",
    ),
    autoRecordTools: pick("autoRecordTools"),
    maxCapsuleChars: pick("maxCapsuleChars"),
    maxStateChars: pick("maxStateChars"),
  }
}

/** Project scope = worktree folder name (matches Hermes scope naming). */
export function scopeFromWorktree(worktree: string): string {
  return basename(worktree.replace(/\/+$/, "")) || "general"
}
