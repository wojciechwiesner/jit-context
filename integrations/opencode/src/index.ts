import type { Hooks, Plugin, PluginModule } from "@opencode-ai/plugin"
import { tool } from "@opencode-ai/plugin"
import { buildCapsule, readProjectState } from "./capsule"
import { resolveConfig, scopeFromWorktree } from "./config"
import { touchedFiles } from "./edits"
import { L0Store } from "./l0"

/**
 * IMPORTANT: this entry module must only export the plugin. OpenCode's legacy
 * loader iterates every export and throws if one is not a plugin function.
 */
const server: Plugin = async (input, options) => {
  const cfg = resolveConfig(options)
  const store = new L0Store(cfg.dbPath)
  const worktree = input.worktree || input.directory
  const defaultScope = scopeFromWorktree(worktree)

  const hooks: Hooks = {
    tool: {
      get_jit_context: tool({
        description:
          "Get the lean JIT context capsule for this project (recorded observations, .planning/STATE.md, " +
          "live Hermes capsule when in scope). Call this BEFORE exploring the codebase blind.",
        args: {
          scope: tool.schema.string().optional().describe("Project scope. Defaults to the worktree folder name."),
        },
        async execute({ scope }, ctx) {
          const capsule = await buildCapsule(cfg, store, scope || defaultScope, ctx.worktree || worktree)
          ctx.metadata({ title: `JIT capsule (${capsule.source}, ${capsule.chars} chars)` })
          return capsule.text || `[jit-context] No observations or .planning/STATE.md for scope '${scope || defaultScope}' yet.`
        },
      }),

      record_jit_observation: tool({
        description:
          "Persist a verified technical fact or architecture decision for this project, so future sessions " +
          "and other agents (Hermes, Claude Code) see it. Only record facts backed by tool output.",
        args: {
          fact: tool.schema.string().min(8).describe("One self-contained, verified fact."),
          scope: tool.schema.string().optional().describe("Project scope. Defaults to the worktree folder name."),
        },
        async execute({ fact, scope }, ctx) {
          const key = store.record(fact.trim(), scope || defaultScope, ctx.sessionID, `opencode:${ctx.agent}`)
          return `Recorded under scope '${scope || defaultScope}' [key: ${key}].`
        },
      }),

      get_project_state: tool({
        description: "Read .planning/STATE.md (canonical project progress) without searching the filesystem.",
        args: {},
        async execute(_args, ctx) {
          return readProjectState(ctx.worktree || worktree, cfg.maxStateChars) ?? "[jit-context] No .planning/STATE.md in this worktree."
        },
      }),
    },
  }

  if (cfg.injectSystemCapsule) {
    hooks["experimental.chat.system.transform"] = async (_input, output) => {
      try {
        const capsule = await buildCapsule(cfg, store, defaultScope, worktree)
        if (capsule.text) output.system.push(capsule.text)
      } catch {
        // Fail-open: never block the prompt loop.
      }
    }
  }

  hooks["tool.execute.after"] = async (call, output) => {
    if (!cfg.autoRecordTools.includes(call.tool)) return
    try {
      for (const file of touchedFiles(call, output, worktree)) {
        store.record(`File modified via ${call.tool}: ${file}`, defaultScope, call.sessionID, "opencode:auto")
      }
    } catch {
      // Fail-open.
    }
  }

  return hooks
}

const plugin: PluginModule = { id: "jit-context", server }
export default plugin
