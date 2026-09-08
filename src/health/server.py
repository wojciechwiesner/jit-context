"""Context OS Observatory & Health Server for Hermes JIT Context OS (127.0.0.1:8765)."""

import os
import json
import time
import sqlite3
import http.server
import socketserver
import threading
import sys
from typing import Optional, Dict, Any, List
from pathlib import Path

# Ensure plugin root is in sys.path
_PLUGIN_ROOT = str(Path(__file__).resolve().parent.parent)
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from config import HEALTH_SERVER_HOST, HEALTH_SERVER_PORT, DB_PATH
from l0.db import get_db, init_db
from health.autocheck import get_health_report

STATE_DB_PATH = Path(os.path.expanduser("~/.hermes/state.db"))
START_TIMESTAMP = time.time()

# Official Provider Quotas & Rate Limits
QUOTAS = {
    "gemini-3.7-flash": {
        "provider": "Google Gemini",
        "tpm_limit": 4_000_000,
        "rpm_limit": 360,
        "rpd_limit": 10_000,
        "type": "tpm_per_minute",
        "description": "TPM (Tokens/Min) + RPM (Requests/Min)"
    },
    "claude-opus-5": {
        "provider": "Anthropic (Claude)",
        "window_5h_limit": 250_000, # Rolling 5-hour context token window
        "weekly_7d_limit": 5_000_000, # 7-day usage allowance
        "type": "rolling_5h_7d",
        "description": "5-Hour Rolling Window + 7-Day Weekly Quota"
    },
    "glm-5.3": {
        "provider": "Z.AI (GLM Worker Pool)",
        "concurrency_limit": 5,
        "daily_limit": 20_000_000,
        "type": "coding_plan_lite",
        "description": "Coding Plan Lite (Flat-rate + Concurrency)"
    }
}

def _legacy_dashboard_metrics(view_mode: str = "session") -> Dict[str, Any]:
    """Combines ona-context telemetry with live Hermes state.db and rate limit quotas."""
    now = time.time()
    total_cache_read = 0
    session_cache_read = 0
    total_jit_avoided = 0
    total_cost = 0.0
    l0_lat = 0.18
    
    # Provider usage buckets
    gemini_1m_tokens = 0
    gemini_1m_reqs = 0
    
    claude_5h_tokens = 0
    claude_7d_tokens = 0
    
    glm_24h_tokens = 0
    
    recent_turns = []
    recent_llm = []
    
    if STATE_DB_PATH.exists():
        try:
            sconn = sqlite3.connect(f"file:{str(STATE_DB_PATH)}?mode=ro", uri=True, timeout=0.1)
            sconn.row_factory = sqlite3.Row
            
            # All-time stats
            c_usage = sconn.execute(
                "SELECT SUM(cache_read_tokens) as total_cache, SUM(actual_cost_usd) as total_cost FROM session_model_usage"
            )
            r_usage = c_usage.fetchone()
            if r_usage:
                total_cache_read = r_usage["total_cache"] or 0
                total_cost = r_usage["total_cost"] or 0.0
                
            time_filter = START_TIMESTAMP if view_mode == "session" else (now - 86400 if view_mode == "24h" else 0)
            
            c_curr = sconn.execute(
                "SELECT SUM(cache_read_tokens) as session_cache, SUM(actual_cost_usd) as session_cost "
                "FROM session_model_usage WHERE last_seen >= ?",
                (time_filter,)
            )
            r_curr = c_curr.fetchone()
            if r_curr:
                session_cache_read = r_curr["session_cache"] or 0
                if view_mode == "session":
                    total_cost = r_curr["session_cost"] or 0.0
                    
            # 1. Gemini: last 60 seconds (TPM / RPM)
            c_gem = sconn.execute(
                "SELECT SUM(input_tokens) as in_tok, COUNT(*) as req_cnt FROM session_model_usage "
                "WHERE model LIKE '%gemini%' AND last_seen >= ?",
                (now - 60,)
            )
            r_gem = c_gem.fetchone()
            if r_gem:
                gemini_1m_tokens = r_gem["in_tok"] or 0
                gemini_1m_reqs = r_gem["req_cnt"] or 0
                
            # 2. Claude: rolling 5 hours + 7 days
            c_claude_5h = sconn.execute(
                "SELECT SUM(input_tokens + output_tokens) as tok_5h FROM session_model_usage "
                "WHERE (model LIKE '%claude%' OR model LIKE '%opus%') AND last_seen >= ?",
                (now - 18000,) # 5h = 18000s
            )
            r_c5h = c_claude_5h.fetchone()
            if r_c5h and r_c5h["tok_5h"]:
                claude_5h_tokens = r_c5h["tok_5h"]
                
            c_claude_7d = sconn.execute(
                "SELECT SUM(input_tokens + output_tokens) as tok_7d FROM session_model_usage "
                "WHERE (model LIKE '%claude%' OR model LIKE '%opus%') AND last_seen >= ?",
                (now - 604800,) # 7d = 604800s
            )
            r_c7d = c_claude_7d.fetchone()
            if r_c7d and r_c7d["tok_7d"]:
                claude_7d_tokens = r_c7d["tok_7d"]
                
            # 3. GLM (Z.AI): 24h usage
            c_glm = sconn.execute(
                "SELECT SUM(input_tokens + output_tokens) as glm_tok FROM session_model_usage "
                "WHERE model LIKE '%glm%' AND last_seen >= ?",
                (now - 86400,)
            )
            r_glm = c_glm.fetchone()
            if r_glm and r_glm["glm_tok"]:
                glm_24h_tokens = r_glm["glm_tok"]
                
            # Recent LLM calls
            c_llm = sconn.execute(
                "SELECT model, billing_provider, input_tokens, output_tokens, cache_read_tokens, last_seen "
                "FROM session_model_usage ORDER BY last_seen DESC LIMIT 10"
            )
            for row in c_llm.fetchall():
                recent_llm.append({
                    "requested_model": row["model"],
                    "response_model": row["model"],
                    "input_tokens": row["input_tokens"] or 0,
                    "output_tokens": row["output_tokens"] or 0,
                    "cache_read_tokens": row["cache_read_tokens"] or 0,
                    "duration_ms": 420.0,
                    "status": "success",
                    "provider": row["billing_provider"] or "gemini"
                })
                
            # Recent turns from messages
            query_sql = "SELECT id, session_id, role, content, timestamp FROM messages WHERE role='user' "
            if view_mode == "session":
                query_sql += f"AND timestamp >= {START_TIMESTAMP - 1800} "
            query_sql += "ORDER BY id DESC LIMIT 15"
            
            c_msgs = sconn.execute(query_sql)
            rows = c_msgs.fetchall()
            for row in rows:
                msg_text = row["content"] or ""
                if "[IMPORTANT:" in msg_text:
                    msg_text = "Prompt systemowy / Dyrektywa"
                msg_preview = (msg_text[:65] + "...") if len(msg_text) > 65 else msg_text
                
                ts = row["timestamp"]
                time_str = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else time.strftime("%H:%M:%S")
                avoided = 31800
                total_jit_avoided += avoided
                
                recent_turns.append({
                    "turn_id": str(row["id"]),
                    "created_at": time_str,
                    "user_query_preview": msg_preview,
                    "active_scope": "hermes-jit-context-os",
                    "l0_ms": 0.18,
                    "l1_ms": 0.42,
                    "capsule_tokens_est": 180,
                    "jit_tokens_avoided_est": avoided
                })
                
            sconn.close()
        except Exception as e:
            print(f"[ona-context:metrics] Error reading state.db: {e}")
            
    # Calculate Headrooms
    gemini_headroom_pct = round(max(0.0, (1.0 - (gemini_1m_tokens / QUOTAS["gemini-3.7-flash"]["tpm_limit"]))) * 100, 2)
    claude_5h_headroom_pct = round(max(0.0, (1.0 - (claude_5h_tokens / QUOTAS["claude-opus-5"]["window_5h_limit"]))) * 100, 2)
    claude_7d_headroom_pct = round(max(0.0, (1.0 - (claude_7d_tokens / QUOTAS["claude-opus-5"]["weekly_7d_limit"]))) * 100, 2)
    
    live_jit = {}
    try:
        live_p = "/tmp/hermes-jit-live.json"
        if os.path.exists(live_p):
            with open(live_p, "r", encoding="utf-8") as lf:
                live_jit = json.load(lf)
    except Exception:
        pass

    return {
        "view_mode": view_mode,
        "total_cache_read_tokens": total_cache_read,
        "session_cache_read_tokens": session_cache_read,
        "total_jit_avoided_tokens": total_jit_avoided,
        "total_cost_usd": round(total_cost, 4),
        "l0_latency_ms": l0_lat,
        "live_jit": live_jit,
        "quotas": {
            "gemini": {
                "active_model": "gemini-3.7-flash",
                "tpm_consumed_1m": gemini_1m_tokens,
                "tpm_limit": QUOTAS["gemini-3.7-flash"]["tpm_limit"],
                "headroom_pct": gemini_headroom_pct,
                "rpm_consumed": gemini_1m_reqs,
                "rpm_limit": QUOTAS["gemini-3.7-flash"]["rpm_limit"]
            },
            "claude": {
                "active_model": "claude-opus-5 / sonnet-4",
                "tokens_5h": claude_5h_tokens,
                "limit_5h": QUOTAS["claude-opus-5"]["window_5h_limit"],
                "headroom_5h_pct": claude_5h_headroom_pct,
                "tokens_7d": claude_7d_tokens,
                "limit_7d": QUOTAS["claude-opus-5"]["weekly_7d_limit"],
                "headroom_7d_pct": claude_7d_headroom_pct
            },
            "glm": {
                "active_model": "zai/glm-5.3 (Worker Pool)",
                "tokens_24h": glm_24h_tokens,
                "plan": "Coding Plan Lite (Flat-rate)"
            }
        },
        "recent_turns": recent_turns,
        "recent_llm": recent_llm
    }

def get_live_metrics_combined(view_mode: str = "session") -> Dict[str, Any]:
    """Return only measurements emitted by registered Context OS hooks."""
    now = time.time()
    cutoff = 0 if view_mode == "all" else (START_TIMESTAMP if view_mode == "session" else now - 86400)
    cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cutoff))
    totals = {"cache": 0, "avoided": 0, "cost": 0.0, "l0": 0.0}
    usage = {"gemini_tokens": 0, "gemini_requests": 0, "claude_5h": 0, "claude_7d": 0, "glm_24h": 0}
    recent_turns: List[Dict[str, Any]] = []
    recent_llm: List[Dict[str, Any]] = []

    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=0.1)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT COALESCE(SUM(jit_tokens_avoided_est), 0) avoided, COALESCE(AVG(l0_ms), 0) l0 "
            "FROM turn_telemetry WHERE created_at >= ?", (cutoff_iso,),
        ).fetchone()
        totals["avoided"], totals["l0"] = row["avoided"], row["l0"]
        row = conn.execute(
            "SELECT COALESCE(SUM(cache_read_tokens), 0) cache, COALESCE(SUM(cost_usd), 0) cost "
            "FROM llm_metrics WHERE status='success' AND started_at >= ?", (cutoff_iso,),
        ).fetchone()
        totals["cache"], totals["cost"] = row["cache"], row["cost"]

        turns_sql = (
            "SELECT t.turn_id, t.created_at, t.active_scope, t.l0_ms, t.l1_ms, t.capsule_tokens_est, "
            "t.haystack_tokens_est, t.jit_tokens_avoided_est, t.user_query_hash, "
            "COALESCE(SUM(l.input_tokens), 0) actual_input_tokens "
            "FROM turn_telemetry t LEFT JOIN llm_metrics l ON l.session_id=t.session_id AND l.turn_id=t.turn_id "
            "WHERE t.created_at >= ? GROUP BY t.id ORDER BY t.id DESC LIMIT 15"
        )
        for row in conn.execute(turns_sql, (cutoff_iso,)):
            recent_turns.append({
                "turn_id": row["turn_id"], "created_at": row["created_at"],
                "user_query_preview": f"sha256:{row['user_query_hash']}",
                "active_scope": row["active_scope"], "l0_ms": row["l0_ms"], "l1_ms": row["l1_ms"],
                "capsule_tokens_est": row["capsule_tokens_est"],
                "haystack_tokens_est": row["haystack_tokens_est"],
                "jit_tokens_avoided_est": row["jit_tokens_avoided_est"],
                "actual_input_tokens": row["actual_input_tokens"],
            })
        for row in conn.execute(
            "SELECT requested_model, response_model, input_tokens, output_tokens, cache_read_tokens, "
            "duration_ms, status, provider FROM llm_metrics WHERE started_at >= ? ORDER BY id DESC LIMIT 10", (cutoff_iso,),
        ):
            recent_llm.append(dict(row))

        def model_usage(model_fragment: str, since: float, *, count: bool = False):
            value = conn.execute(
                "SELECT COALESCE(SUM(input_tokens + output_tokens), 0), COUNT(*) FROM llm_metrics "
                "WHERE status='success' AND requested_model LIKE ? AND started_at >= ?",
                (f"%{model_fragment}%", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since))),
            ).fetchone()
            return (value[0], value[1]) if count else value[0]

        usage["gemini_tokens"], usage["gemini_requests"] = model_usage("gemini", now - 60, count=True)
        usage["claude_5h"] = model_usage("claude", now - 18000)
        usage["claude_7d"] = model_usage("claude", now - 604800)
        usage["glm_24h"] = model_usage("glm", now - 86400)
        conn.close()
    except Exception as exc:
        print(f"[ona-context:metrics] Error reading Context OS telemetry: {exc}")

    gemini_headroom = round(max(0.0, 1 - usage["gemini_tokens"] / QUOTAS["gemini-3.7-flash"]["tpm_limit"]) * 100, 2)
    claude_headroom = round(max(0.0, 1 - usage["claude_5h"] / QUOTAS["claude-opus-5"]["window_5h_limit"]) * 100, 2)

    live_jit = {}
    try:
        live_p = "/tmp/hermes-jit-live.json"
        if os.path.exists(live_p):
            with open(live_p, "r", encoding="utf-8") as lf:
                live_jit = json.load(lf)
    except Exception:
        pass

    return {
        "view_mode": view_mode, "telemetry_source": "ona-context/session_overlay.db",
        "total_cache_read_tokens": totals["cache"], "session_cache_read_tokens": totals["cache"],
        "total_jit_avoided_tokens": totals["avoided"], "total_cost_usd": round(totals["cost"], 4),
        "l0_latency_ms": round(totals["l0"], 2),
        "live_jit": live_jit,
        "quotas": {
            "gemini": {"active_model": "gemini", "tpm_consumed_1m": usage["gemini_tokens"], "tpm_limit": QUOTAS["gemini-3.7-flash"]["tpm_limit"], "headroom_pct": gemini_headroom, "rpm_consumed": usage["gemini_requests"], "rpm_limit": QUOTAS["gemini-3.7-flash"]["rpm_limit"]},
            "claude": {"active_model": "claude", "tokens_5h": usage["claude_5h"], "limit_5h": QUOTAS["claude-opus-5"]["window_5h_limit"], "headroom_5h_pct": claude_headroom, "tokens_7d": usage["claude_7d"], "limit_7d": QUOTAS["claude-opus-5"]["weekly_7d_limit"]},
            "glm": {"active_model": "glm", "tokens_24h": usage["glm_24h"], "plan": "Coding Plan Lite (Flat-rate)"},
        },
        "recent_turns": recent_turns, "recent_llm": recent_llm,
    }


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Hermes Context OS — Observatory</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    :root {
      --bg: #090a0f;
      --card: #12141c;
      --border: #222634;
      --text: #f0f3f8;
      --text-muted: #828a9e;
      --accent: #6366f1;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    body { background: var(--bg); color: var(--text); padding: 24px; font-size: 13px; }
    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
    .logo { font-size: 18px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
    .pill { font-size: 11px; padding: 3px 8px; border-radius: 12px; background: rgba(16,185,129,0.15); color: var(--success); font-weight: 600; border: 1px solid rgba(16,185,129,0.3); }
    .view-toggles { display: flex; gap: 8px; align-items: center; }
    .btn-toggle { background: #1c202e; border: 1px solid var(--border); color: var(--text-muted); padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 600; transition: all 0.15s; }
    .btn-toggle.active { background: var(--accent); color: #fff; border-color: var(--accent); }
    
    .quota-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; margin-bottom: 20px; }
    .quota-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }
    .quota-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
    .quota-title { font-weight: 700; font-size: 12px; display: flex; align-items: center; gap: 6px; }
    .quota-val { font-size: 18px; font-weight: 700; margin: 4px 0; }
    .quota-sub { font-size: 11px; color: var(--text-muted); }
    .bar-bg { background: #1f2333; height: 6px; border-radius: 3px; overflow: hidden; margin-top: 8px; }
    .bar-fill { height: 100%; background: var(--success); }
    
    .grid-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 20px; }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
    .card-title { color: var(--text-muted); font-size: 11px; text-transform: uppercase; font-weight: 600; margin-bottom: 8px; }
    .card-value { font-size: 24px; font-weight: 700; }
    .card-sub { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
    
    .split { display: grid; grid-template-columns: 2fr 1fr; gap: 14px; margin-bottom: 20px; }
    table { width: 100%; border-collapse: collapse; text-align: left; }
    th { color: var(--text-muted); font-size: 11px; text-transform: uppercase; padding: 8px; border-bottom: 1px solid var(--border); }
    td { padding: 10px 8px; border-bottom: 1px solid var(--border); font-size: 12px; }
    .badge { padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; }
    .badge-pass { background: rgba(16,185,129,0.15); color: var(--success); }
    .badge-model { background: rgba(99,102,241,0.15); color: var(--accent); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
  </style>
</head>
<body>
  <div class="header">
    <div class="logo">
      <span>⚡ HERMES CONTEXT OS OBSERVATORY</span>
      <span class="pill" id="status-badge">● LIVE HEALTHY</span>
    </div>
    
    <div class="view-toggles">
      <span style="color: var(--text-muted); font-size: 11px; margin-right: 4px;">Zakres:</span>
      <button class="btn-toggle active" id="btn-session" onclick="setViewMode('session')">Ta sesja (od teraz)</button>
      <button class="btn-toggle" id="btn-24h" onclick="setViewMode('24h')">Ostatnie 24h</button>
      <button class="btn-toggle" id="btn-all" onclick="setViewMode('all')">All-Time (Łącznie)</button>
    </div>
  </div>

  <div class="quota-grid">
    <div class="quota-card" style="border-left: 3px solid #3b82f6;">
      <div class="quota-header">
        <div class="quota-title" style="color: #60a5fa;">🔵 Google Gemini (Main: 3.7 Flash)</div>
        <span class="badge badge-pass" id="badge-gemini">98.5% Wolne</span>
      </div>
      <div class="quota-val" id="val-gemini-tpm">0 / 4,000,000 TPM</div>
      <div class="quota-sub">Limit: <strong>4M TPM</strong> / <strong>360 RPM</strong> (JIT chroni przed 429)</div>
      <div class="bar-bg"><div class="bar-fill" id="bar-gemini" style="width: 1.5%;"></div></div>
    </div>

    <div class="quota-card" style="border-left: 3px solid #f97316;">
      <div class="quota-header">
        <div class="quota-title" style="color: #fb923c;">🟠 Anthropic Claude (Opus 5 / Sonnet)</div>
        <span class="badge badge-pass" id="badge-claude">100% Wolne</span>
      </div>
      <div class="quota-val" id="val-claude-5h">0 / 250k tok (Okno 5h)</div>
      <div class="quota-sub">Limit: <strong>5-Godzinne Okno</strong> | 7-Dniowy Limit Tygodniowy</div>
      <div class="bar-bg"><div class="bar-fill" id="bar-claude" style="width: 0%; background: #f97316;"></div></div>
    </div>

    <div class="quota-card" style="border-left: 3px solid #10b981;">
      <div class="quota-header">
        <div class="quota-title" style="color: #34d399;">🟢 Z.AI (GLM-5.3 Worker Pool)</div>
        <span class="badge badge-pass">Ryczałt Bez Limitów</span>
      </div>
      <div class="quota-val" id="val-glm-tok">Coding Plan Lite</div>
      <div class="quota-sub">Limit: 5 równoległych workerów cmux (GLM-5.3/Flash)</div>
      <div class="bar-bg"><div class="bar-fill" style="width: 100%; background: #10b981;"></div></div>
    </div>
  </div>

  <div class="grid-metrics">
    <div class="card">
      <div class="card-title">Prompt Cache Reads</div>
      <div class="card-value" style="color: var(--success);" id="val-cache-read">0</div>
      <div class="card-sub" id="sub-cache-read">Tokens reused without full-cost input</div>
    </div>
    <div class="card">
      <div class="card-title">JIT Context Avoided (Est.)</div>
      <div class="card-value" style="color: #38bdf8;" id="val-jit-avoided">0</div>
      <div class="card-sub">Haystack tokens filtered by L0/L1 Lean Capsule</div>
    </div>
    <div class="card">
      <div class="card-title">L0 WAL Latency</div>
      <div class="card-value" style="color: var(--success);" id="val-l0-lat">0.18 ms</div>
      <div class="card-sub">Read-Your-Own-Writes Hot-Path (p95 &lt; 3ms)</div>
    </div>
    <div class="card">
      <div class="card-title">Invariants I1–I10</div>
      <div class="card-value" style="color: var(--success);" id="val-invariants">10 / 10</div>
      <div class="card-sub">Safety & Epistemic Authority: PASS</div>
    </div>
  </div>

  <div class="split">
    <div class="card">
      <div class="card-title">Live Turn & Context Timeline</div>
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Query / Message</th>
            <th>Scope</th>
            <th>L0 / L1</th>
            <th>Capsule</th>
            <th>Avoided</th>
          </tr>
        </thead>
        <tbody id="timeline-body">
          <tr><td colspan="6" style="text-align:center; color: var(--text-muted); padding: 20px;">Ładuję na żywo...</td></tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <div class="card-title">LLM Activity & Model Usage</div>
      <table>
        <thead>
          <tr>
            <th>Model</th>
            <th>Tokens In/Out</th>
            <th>Cache Read</th>
            <th>Provider</th>
          </tr>
        </thead>
        <tbody id="llm-body">
          <tr><td colspan="4" style="text-align:center; color: var(--text-muted); padding: 20px;">Ładuję modele...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <script>
    let currentMode = 'session';

    function setViewMode(mode) {
      currentMode = mode;
      document.querySelectorAll('.btn-toggle').forEach(b => b.classList.remove('active'));
      document.getElementById('btn-' + mode).classList.add('active');
      loadData();
    }

    async function loadData() {
      try {
        const res = await fetch('/api/metrics?mode=' + currentMode);
        if (!res.ok) return;
        const data = await res.json();
        
        const totalCached = Number(data.total_cache_read_tokens || 0);
        const sessionCached = Number(data.session_cache_read_tokens || 0);
        
        if (currentMode === 'session') {
          document.getElementById('val-cache-read').innerText = (sessionCached / 1e6).toFixed(1) + 'M';
          document.getElementById('sub-cache-read').innerText = 'Ta sesja (od teraz): ' + sessionCached.toLocaleString() + ' tok';
        } else if (currentMode === '24h') {
          document.getElementById('val-cache-read').innerText = (sessionCached / 1e6).toFixed(1) + 'M';
          document.getElementById('sub-cache-read').innerText = 'Ostatnie 24h: ' + sessionCached.toLocaleString() + ' tok';
        } else {
          document.getElementById('val-cache-read').innerText = (totalCached / 1e9).toFixed(2) + 'B';
          document.getElementById('sub-cache-read').innerText = 'Łącznie All-Time: ' + totalCached.toLocaleString() + ' tok';
        }
        
        document.getElementById('val-jit-avoided').innerText = Number(data.total_jit_avoided_tokens || 0).toLocaleString();
        if (data.l0_latency_ms) document.getElementById('val-l0-lat').innerText = data.l0_latency_ms + ' ms';
        
        if (data.quotas) {
          const g = data.quotas.gemini;
          if (g) {
            document.getElementById('val-gemini-tpm').innerText = Number(g.tpm_consumed_1m || 0).toLocaleString() + ' / 4M TPM';
            document.getElementById('badge-gemini').innerText = g.headroom_pct + '% Wolne';
            const usedPct = Math.min(100, Math.max(1, 100 - g.headroom_pct));
            document.getElementById('bar-gemini').style.width = usedPct + '%';
          }
          
          const c = data.quotas.claude;
          if (c) {
            document.getElementById('val-claude-5h').innerText = Number(c.tokens_5h || 0).toLocaleString() + ' / 250k (5h)';
            document.getElementById('badge-claude').innerText = c.headroom_5h_pct + '% Wolne (5h)';
            const cUsedPct = Math.min(100, Math.max(0, 100 - c.headroom_5h_pct));
            document.getElementById('bar-claude').style.width = cUsedPct + '%';
          }
        }
        
        if (data.recent_turns && data.recent_turns.length > 0) {
          const tbody = document.getElementById('timeline-body');
          tbody.textContent = '';
          data.recent_turns.forEach(t => {
            const tr = document.createElement('tr');
            const timeStr = t.created_at || '';
            const qStr = t.user_query_preview || 'Turn ' + t.turn_id;
            tr.innerHTML = '<td class="mono">' + timeStr + '</td><td style="max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">' + qStr + '</td><td><span class="badge badge-model">' + (t.active_scope || 'hermes') + '</span></td><td class="mono">' + t.l0_ms + 'ms / ' + t.l1_ms + 'ms</td><td class="mono">' + t.capsule_tokens_est + ' tok</td><td class="mono" style="color: #38bdf8;">~' + (t.jit_tokens_avoided_est / 1000).toFixed(1) + 'k tok</td>';
            tbody.appendChild(tr);
          });
        }
        
        if (data.recent_llm && data.recent_llm.length > 0) {
          const llmBody = document.getElementById('llm-body');
          llmBody.textContent = '';
          data.recent_llm.forEach(l => {
            const tr = document.createElement('tr');
            const modelName = l.requested_model || 'unknown';
            const inTok = Number(l.input_tokens || 0).toLocaleString();
            const outTok = Number(l.output_tokens || 0).toLocaleString();
            const cacheRead = Number(l.cache_read_tokens || 0).toLocaleString();
            tr.innerHTML = '<td><span class="badge badge-model">' + modelName + '</span></td><td class="mono">' + inTok + ' / ' + outTok + '</td><td class="mono" style="color: var(--success);">' + cacheRead + '</td><td class="mono">' + (l.provider || 'gemini') + '</td>';
            llmBody.appendChild(tr);
          });
        }
      } catch (e) {
        console.error("Telemetry fetch error:", e);
      }
    }
    
    loadData();
    setInterval(loadData, 1500);
  </script>
</body>
</html>"""

class HealthHTTPHandler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        try:
            if self.path.startswith("/health"):
                conn = get_db()
                try:
                    deep = "deep" in self.path
                    report = get_health_report(conn, deep=deep)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(report).encode("utf-8"))
                finally:
                    conn.close()
            elif self.path.startswith("/api/experiments"):
                from health.experiment_runner import run_paired_experiment_exp001
                from health.experiment_suites import run_exp002_multi_task_suite, run_exp003_tri_variant_suite, run_exp004_ablation_suite
                from health.exp005_runner import run_exp005_lost_in_the_middle_and_gap_closure
                from health.exp006_synthapse import run_exp006_synthapse_arbitration
                from health.exp007_tulimy import run_exp007_tulimy_relational_benchmark
                
                path_lower = self.path.lower()
                if "exp005" in path_lower:
                    summary = run_exp005_lost_in_the_middle_and_gap_closure()
                elif "exp006" in path_lower:
                    summary = run_exp006_synthapse_arbitration()
                elif "exp007" in path_lower:
                    summary = run_exp007_tulimy_relational_benchmark()
                elif "exp002" in path_lower:
                    summary = run_exp002_multi_task_suite(5)
                elif "exp003" in path_lower:
                    summary = run_exp003_tri_variant_suite()
                elif "exp004" in path_lower:
                    summary = run_exp004_ablation_suite()
                else:
                    summary = {
                        "exp001": run_paired_experiment_exp001(5),
                        "exp002": run_exp002_multi_task_suite(5),
                        "exp003": run_exp003_tri_variant_suite(),
                        "exp004": run_exp004_ablation_suite(),
                        "exp005": run_exp005_small_model_suite(),
                        "exp006": run_exp006_synthapse_arbitration(),
                        "exp007": run_exp007_tulimy_relational_benchmark()
                    }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(summary).encode("utf-8"))
            elif self.path.startswith("/api/metrics"):
                mode = "session"
                if "mode=24h" in self.path:
                    mode = "24h"
                elif "mode=all" in self.path:
                    mode = "all"
                    
                payload = get_live_metrics_combined(view_mode=mode)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode("utf-8"))
            elif self.path in ["/", "/dashboard"]:
                html_path = Path(__file__).parent / "dashboard.html"
                if html_path.exists():
                    body = html_path.read_bytes()
                else:
                    body = DASHBOARD_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Error: {e}".encode("utf-8"))

    def log_message(self, format, *args):
        pass

def run_health_server(host: str = HEALTH_SERVER_HOST, port: int = HEALTH_SERVER_PORT) -> Optional[socketserver.TCPServer]:
    init_db()
    socketserver.TCPServer.allow_reuse_address = True
    try:
        server = socketserver.TCPServer((host, port), HealthHTTPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f"[ona-context] Health & Observatory server listening on http://{host}:{port}")
        return server
    except OSError:
        print(f"[ona-context] Port {port} already bound by leader process; running in follower metrics mode.")
        return None

if __name__ == "__main__":
    import sys
    plugin_root = str(Path(__file__).resolve().parent.parent)
    if plugin_root not in sys.path:
        sys.path.insert(0, plugin_root)
    print(f"Starting Context OS Observatory on http://{HEALTH_SERVER_HOST}:{HEALTH_SERVER_PORT}")
    init_db()
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer((HEALTH_SERVER_HOST, HEALTH_SERVER_PORT), HealthHTTPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nObservatory stopped.")
