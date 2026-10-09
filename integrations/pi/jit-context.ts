import { execFile } from "node:child_process"
import { existsSync } from "node:fs"
import { homedir } from "node:os"
import { basename, join } from "node:path"
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"
import { Type } from "typebox"

const CALL_TIMEOUT_MS = 4000
const MAX_CAPSULE_CHARS = 6000
const EDIT_TOOLS = new Set(["edit", "write"])
const SOURCE = "pi:agent"
const PY_BRIDGE =
  "import sys,json;sys.path.insert(0,sys.argv[1]);import mcp_server as m;a=json.loads(sys.argv[2]);print(getattr(m,a['fn'])(**a['kw']))"

function resolveSrc(): string | null {
  const candidates = [
    process.env.JIT_SRC,
    join(homedir(), ".claude", "jit-context-runtime", "current"),
    join(homedir(), ".jit-context", "src"),
  ]
  return candidates.find((p) => p && existsSync(join(p, "mcp_server.py"))) ?? null
}

/** Calls a tool_* function of the jit-context Python runtime. Fail-open: returns "" on any error. */
function callJit(fn: string, kw: Record<string, string>): Promise<string> {
  const src = resolveSrc()
  if (!src) return Promise.resolve("")
  return new Promise((resolve) => {
    execFile("python3", ["-c", PY_BRIDGE, src, JSON.stringify({ fn, kw })], { timeout: CALL_TIMEOUT_MS }, (err, out) =>
      resolve(err ? "" : out.trim()),
    )
  })
}

const scopeOf = (cwd: string) => basename(cwd)
const clip = (text: string) => (text.length <= MAX_CAPSULE_CHARS ? text : `${text.slice(0, MAX_CAPSULE_CHARS)}\n[... clipped]`)
const textResult = (text: string) => ({ content: [{ type: "text" as const, text }], details: {} })

export default function jitContext(pi: ExtensionAPI) {
  if (process.env.JIT_INJECT === "0") return

  pi.on("before_agent_start", async (event, ctx) => {
    const capsule = await callJit("tool_get_jit_context", { scope: scopeOf(ctx.cwd), task_intent: event.prompt.slice(0, 500) })
    if (!capsule) return
    const opts = event.systemPromptOptions
    opts.appendSystemPrompt = [opts.appendSystemPrompt, clip(capsule)].filter(Boolean).join("\n\n")
  })

  pi.on("tool_result", (event, ctx) => {
    if (event.isError || !EDIT_TOOLS.has(event.toolName)) return
    const path = (event.input as { path?: string; file_path?: string }).path ?? (event.input as { file_path?: string }).file_path
    if (!path) return
    void callJit("tool_record_jit_observation", {
      fact: `File modified via ${event.toolName}: ${path}`,
      scope: scopeOf(ctx.cwd),
      source: "pi:auto",
    })
  })

  pi.registerTool({
    name: "get_jit_context",
    label: "JIT context",
    description: "Get the lean JIT context capsule for this project. Call BEFORE exploring the codebase blind.",
    parameters: Type.Object({ scope: Type.Optional(Type.String({ description: "Project scope. Defaults to the cwd folder name." })) }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      const text = await callJit("tool_get_jit_context", { scope: params.scope ?? scopeOf(ctx.cwd) })
      return textResult(text ? clip(text) : "[jit-context] runtime unavailable or no context yet.")
    },
  })

  pi.registerTool({
    name: "record_jit_observation",
    label: "JIT record",
    description: "Persist a verified technical fact or decision so future sessions and other agents (Hermes, Claude Code) see it. Only facts backed by tool output.",
    parameters: Type.Object({ fact: Type.String({ minLength: 8 }), scope: Type.Optional(Type.String()) }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      const text = await callJit("tool_record_jit_observation", { fact: params.fact, scope: params.scope ?? scopeOf(ctx.cwd), source: SOURCE })
      return textResult(text || "[jit-context] runtime unavailable, observation not recorded.")
    },
  })

  pi.registerTool({
    name: "get_project_state",
    label: "Project state",
    description: "Read .planning/STATE.md (canonical project progress) without searching the filesystem.",
    parameters: Type.Object({}),
    async execute(_id, _params, _signal, _onUpdate, ctx) {
      return textResult((await callJit("tool_get_project_state", { project_path: ctx.cwd })) || "[jit-context] no state.")
    },
  })
}
