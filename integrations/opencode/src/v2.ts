import { buildCapsule, readProjectState } from "./capsule"
import { resolveConfig, scopeFromWorktree } from "./config"
import { touchedFiles } from "./edits"
import { L0Store } from "./l0"

/**
 * OpenCode V2 entry (`opencode >= 2.0`). The V1 entry stays in `index.ts`.
 *
 * Only the subset of the `@opencode/plugin` Promise API used here is typed
 * locally, verified against @opencode/plugin 2.1.4 d.ts. Tool inputs are plain
 * JSON Schema, so the plugin needs neither `@opencode/plugin` nor `effect` at runtime.
 */
type JsonSchema = Record<string, unknown>
type ToolResult = { content?: string; metadata?: Record<string, unknown> }
type ToolContext = { readonly sessionID: string; readonly agent: string }
type ToolInfo = {
  name: string
  description: string
  input: JsonSchema
  options?: { codemode: boolean }
  execute: (input: any, ctx: ToolContext) => Promise<ToolResult>
}
type SessionContextEvent = { system: Array<{ type: "text"; text: string }> }
type ToolAfterEvent = {
  readonly tool: string
  readonly sessionID: string
  readonly input: unknown
  readonly status: "completed" | "error"
  result?: { metadata?: Record<string, unknown> }
}
export type V2Context = {
  readonly location: { readonly directory: string; readonly project?: { readonly directory: string } }
  readonly options: Readonly<Record<string, any>>
  readonly tool: {
    transform: (callback: (editor: { add: (tool: ToolInfo) => void }) => void) => Promise<unknown>
    hook: (name: "execute.after", callback: (event: ToolAfterEvent) => Promise<void> | void) => Promise<unknown>
  }
  readonly session: {
    hook: (name: "context", callback: (event: SessionContextEvent) => Promise<void> | void) => Promise<unknown>
  }
}

const SCOPE_ARG = { type: "string", description: "Project scope. Defaults to the worktree folder name." }
const MIN_FACT_CHARS = 8

async function setup(ctx: V2Context): Promise<void> {
  const cfg = resolveConfig(ctx.options)
  const store = new L0Store(cfg.dbPath)
  const worktree = ctx.location.project?.directory || ctx.location.directory
  const defaultScope = scopeFromWorktree(worktree)

  await ctx.tool.transform((tools) => {
    tools.add({
      name: "get_jit_context",
      description:
        "Get the lean JIT context capsule for this project (recorded observations, .planning/STATE.md, " +
        "live Hermes capsule when in scope). Call this BEFORE exploring the codebase blind.",
      input: { type: "object", properties: { scope: SCOPE_ARG } },
      options: { codemode: false },
      execute: async ({ scope }: { scope?: string }) => {
        const capsule = await buildCapsule(cfg, store, scope || defaultScope, worktree)
        return {
          content: capsule.text || `[jit-context] No observations or .planning/STATE.md for scope '${scope || defaultScope}' yet.`,
          metadata: { title: `JIT capsule (${capsule.source}, ${capsule.chars} chars)` },
        }
      },
    })

    tools.add({
      name: "record_jit_observation",
      description:
        "Persist a verified technical fact or architecture decision for this project, so future sessions " +
        "and other agents (Hermes, Claude Code) see it. Only record facts backed by tool output.",
      input: {
        type: "object",
        properties: {
          fact: { type: "string", minLength: MIN_FACT_CHARS, description: "One self-contained, verified fact." },
          scope: SCOPE_ARG,
        },
        required: ["fact"],
      },
      options: { codemode: false },
      execute: async ({ fact, scope }: { fact: string; scope?: string }, tctx) => {
        const key = store.record(fact.trim(), scope || defaultScope, tctx.sessionID, `opencode:${tctx.agent}`)
        return { content: `Recorded under scope '${scope || defaultScope}' [key: ${key}].` }
      },
    })

    tools.add({
      name: "get_project_state",
      description: "Read .planning/STATE.md (canonical project progress) without searching the filesystem.",
      input: { type: "object", properties: {} },
      options: { codemode: false },
      execute: async () => ({
        content: readProjectState(worktree, cfg.maxStateChars) ?? "[jit-context] No .planning/STATE.md in this worktree.",
      }),
    })
  })

  if (cfg.injectSystemCapsule) {
    await ctx.session.hook("context", async (event) => {
      try {
        const capsule = await buildCapsule(cfg, store, defaultScope, worktree)
        if (capsule.text) event.system.push({ type: "text", text: capsule.text })
      } catch {
        // Fail-open: never block the prompt loop.
      }
    })
  }

  await ctx.tool.hook("execute.after", (event) => {
    if (event.status !== "completed" || !cfg.autoRecordTools.includes(event.tool)) return
    try {
      const call = { tool: event.tool, args: event.input }
      for (const file of touchedFiles(call, { metadata: event.result?.metadata }, worktree)) {
        store.record(`File modified via ${event.tool}: ${file}`, defaultScope, event.sessionID, "opencode:auto")
      }
    } catch {
      // Fail-open.
    }
  })
}

const plugin = { id: "jit-context", setup }
export default plugin
