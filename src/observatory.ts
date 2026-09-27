export type LiveCapsule = { scope: string; capsule: string }

/**
 * Fetches the live capsule from the Hermes Observatory.
 *
 * Scope guard: the Observatory serves the capsule of the *current Hermes
 * session* and does not filter by `?scope=`. A capsule whose scope differs from
 * the OpenCode project is rejected, otherwise another conversation's goal would
 * leak into this agent (context poisoning).
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
    const url = `${baseUrl}/api/context/live?scope=${encodeURIComponent(scope)}`
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
