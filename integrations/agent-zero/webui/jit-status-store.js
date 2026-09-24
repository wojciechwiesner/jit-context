import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

const API = "/plugins/jit_context/jit_status";
const POLL_MS = 30000;

function fmtTokens(n) {
  if (n == null) return "—";
  return `\u2212${Number(n).toLocaleString("en-US")}`;
}

export const store = createStore("jitStatusStore", {
    status: null,
    loading: false,
    error: "",
    expanded: false,
    _timer: null,

    init() {},

    onOpen() {
        this.refresh();
        if (!this._timer) {
            this._timer = setInterval(() => this.refresh(), POLL_MS);
        }
    },

    cleanup() {
        if (this._timer) {
            clearInterval(this._timer);
            this._timer = null;
        }
    },

    toggle() {
        this.expanded = !this.expanded;
    },

    async refresh() {
        if (this.loading) return;
        this.loading = true;
        try {
            const res = await callJsonApi(API, {});
            if (res && res.ok) {
                this.status = res;
                this.error = "";
            } else {
                this.error = "no-data";
            }
        } catch (e) {
            this.error = String(e && e.message ? e.message : e);
        } finally {
            this.loading = false;
        }
    },

    // ---- derived helpers (safe on null) ----

    helpful() {
        return this.status?.jev?.verdicts?.HELPFUL ?? 0;
    },
    verdictsTotal() {
        return this.status?.counts?.verdicts_total ?? 0;
    },
    lastCompileMs() {
        const ms = this.status?.jit?.last_compile_ms;
        return ms != null ? `${ms}ms` : "—";
    },
    tokensSaved() {
        return fmtTokens(this.status?.jit?.tokens_avoided);
    },
    issueCount() {
        return (this.status?.issues || []).length;
    },
    errorCount() {
        return (this.status?.issues || []).filter((i) => i.level === "error").length;
    },
    tierClass(tier) {
        const t = this.status?.tiers?.[tier];
        if (t === true) return "jit-tier-on";
        if (t === false || t === "off") return "jit-tier-off";
        return "jit-tier-shadow";
    },
    jitActive() {
        return this.status?.jit?.mode === "active";
    },
    jevActive() {
        return !!this.status?.jev?.enabled;
    },
});
