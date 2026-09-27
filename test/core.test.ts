import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { buildCapsule } from "../src/capsule"
import { resolveConfig, scopeFromWorktree } from "../src/config"
import { L0Store } from "../src/l0"
import { fetchLiveCapsule } from "../src/observatory"

let dir: string
let store: L0Store

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "jit-plugin-"))
  store = new L0Store(join(dir, "overlay.db"))
})
afterEach(() => rmSync(dir, { recursive: true, force: true }))

const jsonFetch = (body: unknown, status = 200) =>
  (async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch

describe("L0Store", () => {
  test("read on missing DB returns empty, never throws", () => {
    expect(store.read("any")).toEqual([])
  })

  test("records and reads back only the requested scope", () => {
    store.record("API uses FastAPI 0.120", "proj-a", "s1", "test")
    store.record("Frontend is Next.js 16", "proj-b", "s1", "test")
    const a = store.read("proj-a")
    expect(a.map((o) => o.value)).toEqual(["API uses FastAPI 0.120"])
  })

  test("same fact twice is idempotent", () => {
    const k1 = store.record("dup fact here", "p", "s1", "t")
    const k2 = store.record("dup fact here", "p", "s2", "t")
    expect(k1).toBe(k2)
    expect(store.read("p")).toHaveLength(1)
  })
})

describe("fetchLiveCapsule", () => {
  test("accepts capsule with matching scope", async () => {
    const r = await fetchLiveCapsule("http://x", "boocco", 100, jsonFetch({ scope: "boocco", capsule: "<C/>" }))
    expect(r?.capsule).toBe("<C/>")
  })

  test("rejects capsule from another scope (anti-poisoning)", async () => {
    const r = await fetchLiveCapsule("http://x", "boocco", 100, jsonFetch({ scope: "thesaiver", capsule: "<C/>" }))
    expect(r).toBeNull()
  })

  test("fails open on network error and on timeout", async () => {
    const boom = (async () => {
      throw new Error("ECONNREFUSED")
    }) as unknown as typeof fetch
    expect(await fetchLiveCapsule("http://x", "p", 100, boom)).toBeNull()
    // Real timeout path against a non-routable address.
    const t0 = performance.now()
    expect(await fetchLiveCapsule("http://10.255.255.1:9", "p", 150)).toBeNull()
    expect(performance.now() - t0).toBeLessThan(1500)
  })
})

describe("buildCapsule", () => {
  const cfg = resolveConfig({ observatoryUrl: "http://x" }, {})

  test("falls back to L0 observations + STATE.md", async () => {
    mkdirSync(join(dir, ".planning"))
    writeFileSync(join(dir, ".planning", "STATE.md"), "Phase 2: auth")
    store.record("DB is Postgres 17", "p", "s", "t")
    const c = await buildCapsule(cfg, store, "p", dir, jsonFetch({}, 503))
    expect(c.source).toBe("l0")
    expect(c.text).toContain("DB is Postgres 17")
    expect(c.text).toContain("Phase 2: auth")
  })

  test("empty project yields empty capsule (nothing injected)", async () => {
    const c = await buildCapsule(cfg, store, "p", dir, jsonFetch({}, 503))
    expect(c).toEqual({ text: "", source: "empty", chars: 0 })
  })

  test("clips oversized capsules", async () => {
    const small = resolveConfig({ observatoryUrl: "http://x", maxCapsuleChars: 50 }, {})
    const c = await buildCapsule(small, store, "p", dir, jsonFetch({ scope: "p", capsule: "x".repeat(500) }))
    expect(c.source).toBe("observatory")
    expect(c.text.length).toBeLessThan(100)
  })
})

describe("config", () => {
  test("options override env override defaults", () => {
    const env = { JIT_OBSERVATORY_URL: "http://env:1/", JIT_INJECT: "0" }
    expect(resolveConfig({}, env).observatoryUrl).toBe("http://env:1")
    expect(resolveConfig({}, env).injectSystemCapsule).toBe(false)
    expect(resolveConfig({ observatoryUrl: "http://opt:2" }, env).observatoryUrl).toBe("http://opt:2")
  })

  test("scope is worktree folder name", () => {
    expect(scopeFromWorktree("/Users/x/Projects/active/boocco/")).toBe("boocco")
  })
})
