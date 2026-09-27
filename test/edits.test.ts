import { describe, expect, test } from "bun:test"
import { touchedFiles } from "../src/edits"

const WT = "/repo"

describe("touchedFiles", () => {
  test("apply_patch: reads metadata.files (shape captured from OpenCode 1.17.8)", () => {
    const output = {
      metadata: {
        files: [
          { filePath: "/repo/api/webhooks.py", relativePath: "api/webhooks.py", type: "update" },
          { filePath: "/repo/notes.txt", relativePath: "notes.txt", type: "add" },
        ],
      },
    }
    expect(touchedFiles({ tool: "apply_patch", args: { patchText: "..." } }, output, WT)).toEqual([
      "api/webhooks.py",
      "notes.txt",
    ])
  })

  test("write/edit: absolute args.filePath becomes worktree-relative", () => {
    expect(touchedFiles({ tool: "edit", args: { filePath: "/repo/src/a.ts" } }, { metadata: {} }, WT)).toEqual([
      "src/a.ts",
    ])
  })

  test("unknown shapes yield nothing instead of throwing", () => {
    expect(touchedFiles({ tool: "write" }, {}, WT)).toEqual([])
    expect(touchedFiles({ tool: "apply_patch", args: null }, { metadata: { files: [null, 42] } }, WT)).toEqual([])
  })
})
