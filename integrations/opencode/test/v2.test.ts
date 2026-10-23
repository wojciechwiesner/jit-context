import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { touchedFiles } from "../src/edits"
import { L0Store } from "../src/l0"
import plugin, { type V2Context } from "../src/v2"

let dir: string
let worktree: string
let dbPath: string

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "jit-v2-"))
  worktree = join(dir, "my-proj")
  mkdirSync(join(worktree, ".planning"), { recursive: true })
  writeFileSync(join(worktree, ".planning/STATE.md"), "# State\nPhase 2 in progress")
  dbPath = join(dir, "overlay.db")
})
afterEach(() => rmSync(dir, { recursive: true, force: true }))

/** Fake V2 host that captures what the plugin registers. */
async function load(options: Record<string, unknown> = {}) {
  const tools = new Map<string, any>()
  const sessionHooks = new Map<string, (e: any) => any>()
  const toolHooks = new Map<string, (e: any) => any>()
  const ctx: V2Context = {
    location: { directory: worktree, project: { directory: worktree } },
    options: { dbPath, observatoryUrl: "http://127.0.0.1:1", observatoryTimeoutMs: 50, ...options },
    tool: {
      transform: async (cb) => cb({ add: (t) => void tools.set(t.name, t) }),
      hook: async (name, cb) => void toolHooks.set(name, cb),
    },
    session: { hook: async (name, cb) => void sessionHooks.set(name, cb) },
  }
  await plugin.setup(ctx)
  return { tools, sessionHooks, toolHooks }
}

const TOOL_CTX = { sessionID: "ses_1", agent: "build" }

describe("V2 plugin module", () => {
  test("default export matches the V2 loader contract (id + setup)", () => {
    expect(plugin.id).toBe("jit-context")
    expect(typeof plugin.setup).toBe("function")
  })

  test("registers the three tools as direct (non-codemode) tools with JSON Schema input", async () => {
    const { tools } = await load()
    expect([...tools.keys()].sort()).toEqual(["get_jit_context", "get_project_state", "record_jit_observation"])
    for (const t of tools.values()) {
      expect(t.options).toEqual({ codemode: false })
      expect(t.input.type).toBe("object")
    }
  })

  test("record then get_jit_context round-trips through L0", async () => {
    const { tools } = await load()
    await tools.get("record_jit_observation").execute({ fact: "API runs on port 8002" }, TOOL_CTX)
    const res = await tools.get("get_jit_context").execute({}, TOOL_CTX)
    expect(res.content).toContain("API runs on port 8002")
  })

  test("get_project_state reads .planning/STATE.md of the location project", async () => {
    const { tools } = await load()
    const res = await tools.get("get_project_state").execute({}, TOOL_CTX)
    expect(res.content).toContain("Phase 2 in progress")
  })

  test("context hook pushes the capsule as a system text part", async () => {
    const { sessionHooks } = await load()
    const event = { system: [] as any[] }
    await sessionHooks.get("context")!(event)
    expect(event.system).toHaveLength(1)
    expect(event.system[0].type).toBe("text")
    expect(event.system[0].text).toContain("Phase 2 in progress")
  })

  test("injectSystemCapsule=false registers no context hook", async () => {
    const { sessionHooks } = await load({ injectSystemCapsule: false })
    expect(sessionHooks.has("context")).toBe(false)
  })

  test("execute.after records edits from V2 FileDiff metadata, ignores errors", async () => {
    const { toolHooks } = await load()
    const after = toolHooks.get("execute.after")!
    await after({
      tool: "edit",
      sessionID: "ses_1",
      input: { path: "src/a.ts" },
      status: "completed",
      result: { metadata: { files: [{ file: join(worktree, "src/a.ts"), status: "modified" }] } },
    })
    await after({ tool: "write", sessionID: "ses_1", input: { path: "b.ts" }, status: "error" })
    const values = new L0Store(dbPath).read("my-proj").map((o) => o.value)
    expect(values).toEqual(["File modified via edit: src/a.ts"])
  })
})

describe("touchedFiles V2 shapes", () => {
  test("FileDiff.file and file:// URIs become worktree-relative", () => {
    const output = { metadata: { files: [{ file: "file:///repo/x.ts" }, { file: "y.ts" }] } }
    expect(touchedFiles({ tool: "patch" }, output, "/repo")).toEqual(["x.ts", "y.ts"])
  })

  test("falls back to input.path when no metadata", () => {
    expect(touchedFiles({ tool: "write", args: { path: "/repo/z.ts" } }, {}, "/repo")).toEqual(["z.ts"])
  })
})
