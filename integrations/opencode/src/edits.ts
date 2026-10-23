import { isAbsolute, relative } from "node:path"

type ToolCall = { tool: string; args?: any }
type ToolOutput = { metadata?: any }

/**
 * Extracts files touched by an OpenCode edit tool, as worktree-relative paths.
 * Verified against OpenCode 1.17.8 runtime:
 * - `apply_patch`: output.metadata.files[] = { filePath, relativePath, type }
 * - `write` / `edit`: args.filePath (absolute)
 * Verified against OpenCode 2.1.4 source (core/src/tool/plugin):
 * - `edit` / `write` / `patch`: result.metadata.files[] = FileDiff { file, ... }, input.path
 */
export function touchedFiles(call: ToolCall, output: ToolOutput, worktree: string): string[] {
  const files = output.metadata?.files
  const raw: unknown[] = Array.isArray(files)
    ? files.map((f: any) => f?.relativePath ?? f?.filePath ?? f?.file)
    : [call.args?.filePath ?? call.args?.path]

  const rel = raw
    .filter((p): p is string => typeof p === "string" && p.length > 0)
    .map((p) => p.replace(/^file:\/\//, ""))
    .map((p) => (isAbsolute(p) ? relative(worktree, p) : p))
  return [...new Set(rel)]
}
