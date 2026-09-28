import { isAbsolute, relative } from "node:path"

type ToolCall = { tool: string; args?: any }
type ToolOutput = { metadata?: any }

/**
 * Extracts files touched by an OpenCode edit tool, as worktree-relative paths.
 * Verified against OpenCode 1.17.8 runtime:
 * - `apply_patch`: output.metadata.files[] = { filePath, relativePath, type }
 * - `write` / `edit`: args.filePath (absolute)
 */
export function touchedFiles(call: ToolCall, output: ToolOutput, worktree: string): string[] {
  const files = output.metadata?.files
  const raw: unknown[] = Array.isArray(files)
    ? files.map((f: any) => f?.relativePath ?? f?.filePath)
    : [call.args?.filePath ?? call.args?.path]

  const rel = raw
    .filter((p): p is string => typeof p === "string" && p.length > 0)
    .map((p) => (isAbsolute(p) ? relative(worktree, p) : p))
  return [...new Set(rel)]
}
