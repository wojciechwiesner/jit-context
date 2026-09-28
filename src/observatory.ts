export type LiveCapsule = { scope: string; capsule: string }

/**
 * Fetches the live capsule from the Hermes Observatory.
 *
 * The Observatory selects by `?project=` and returns that project's newest
 * Hermes session (or `no_project_session`). Scope guard: a capsule whose scope
 * still differs from the OpenCode project is rejected (older Observatory builds
 * ignore the parameter and serve the active session), so another project's
 * context never leaks into this agent.
 *
 * Fail-open (Invariant I6): any error or timeout returns null, never throws.
 */
export async function fetchLiveCapsule(
  baseUrl: string,
  scope: string,
  timeoutMs: number,
  fetchImpl: typeof fetch = fetch,
): Promise<LiveCapsule | null> {
  try {
    const url = `${baseUrl}/api/context/live?project=${encodeURIComponent(scope)}`
    const res = await fetchImpl(url, { signal: AbortSignal.timeout(timeoutMs) })
    if (!res.ok) return null
    const data = (await res.json()) as Partial<LiveCapsule>
    if (typeof data.capsule !== "string" || !data.capsule.trim()) return null
    if (data.scope !== scope) return null
    return { scope: data.scope, capsule: data.capsule }
  } catch {
    return null
  }
}
