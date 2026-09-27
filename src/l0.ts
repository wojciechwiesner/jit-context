import { Database } from "bun:sqlite"
import { createHash } from "node:crypto"
import { existsSync, mkdirSync } from "node:fs"
import { dirname } from "node:path"

/**
 * L0 SQLite WAL store. Schema is identical to jit-context mcp_server.py
 * (`session_overlay`), so observations are shared between Hermes, Claude Code
 * (MCP) and OpenCode (this plugin).
 */
const SCHEMA = `
CREATE TABLE IF NOT EXISTS session_overlay (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  epistemic_weight REAL DEFAULT 1.0,
  source TEXT NOT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)`

export type Observation = { key: string; value: string; source: string; updatedAt: string }

export class L0Store {
  constructor(private readonly dbPath: string) {}

  private open(readonly: boolean): Database | null {
    if (readonly && !existsSync(this.dbPath)) return null
    if (!readonly) mkdirSync(dirname(this.dbPath), { recursive: true })
    const db = new Database(this.dbPath, readonly ? { readonly: true } : { create: true })
    db.exec("PRAGMA busy_timeout = 200")
    return db
  }

  /** Returns observations for exactly this scope. Never mixes other projects in. */
  read(scope: string, limit = 15): Observation[] {
    const db = this.open(true)
    if (!db) return []
    try {
      const hasTable = db
        .query("SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_overlay'")
        .get()
      if (!hasTable) return []
      return db
        .query(
          `SELECT key, value, source, updated_at AS updatedAt FROM session_overlay
           WHERE scope = ?1 ORDER BY updated_at DESC, id DESC LIMIT ?2`,
        )
        .all(scope, limit) as Observation[]
    } finally {
      db.close()
    }
  }

  /** Idempotent per (scope, fact): re-recording the same fact refreshes its timestamp. */
  record(fact: string, scope: string, sessionId: string, source: string): string {
    const key = `obs_${createHash("sha256").update(fact).digest("hex").slice(0, 12)}`
    const db = this.open(false)!
    try {
      db.exec("PRAGMA journal_mode = WAL")
      db.exec(SCHEMA)
      const existing = db
        .query("SELECT id FROM session_overlay WHERE scope = ?1 AND key = ?2")
        .get(scope, key) as { id: number } | null
      if (existing) {
        db.query("UPDATE session_overlay SET updated_at = CURRENT_TIMESTAMP WHERE id = ?1").run(existing.id)
      } else {
        db.query(
          `INSERT INTO session_overlay (session_id, scope, key, value, epistemic_weight, source)
           VALUES (?1, ?2, ?3, ?4, 1.0, ?5)`,
        ).run(sessionId, scope, key, fact, source)
      }
      return key
    } finally {
      db.close()
    }
  }
}
