// Worktree activity: every `git worktree list --porcelain` entry with its last commit and dirty file count.
const { execFileSync } = require("child_process");

const GIT_TIMEOUT_MS = 8000;
const BRANCH_PREFIX = "refs/heads/";

function git(cwd, args) {
  try {
    return { ok: true, out: execFileSync("git", args, { cwd, encoding: "utf-8", timeout: GIT_TIMEOUT_MS, stdio: ["ignore", "pipe", "pipe"] }) };
  } catch (e) {
    const stderr = e.stderr ? String(e.stderr).trim() : "";
    return { ok: false, error: stderr || e.message };
  }
}

// Porcelain blocks are separated by blank lines; each starts with "worktree <path>".
function parsePorcelain(text) {
  const entries = [];
  let current = null;
  for (const line of text.split("\n")) {
    if (line.startsWith("worktree ")) {
      current = { path: line.slice("worktree ".length), head: null, branch: null, detached: false, bare: false, prunable: false };
      entries.push(current);
    } else if (!current) {
      continue;
    } else if (line.startsWith("HEAD ")) {
      current.head = line.slice("HEAD ".length);
    } else if (line.startsWith("branch ")) {
      const ref = line.slice("branch ".length);
      current.branch = ref.startsWith(BRANCH_PREFIX) ? ref.slice(BRANCH_PREFIX.length) : ref;
    } else if (line === "detached") {
      current.detached = true;
    } else if (line === "bare") {
      current.bare = true;
    } else if (line.startsWith("prunable")) {
      current.prunable = true;
    }
  }
  return entries;
}

// Missing values stay null and the git error is kept; nothing is guessed.
function describeWorktree(entry) {
  const item = { ...entry, last_commit_at: null, last_commit_subject: null, dirty_count: null, error: null };
  if (entry.bare) return item;
  const log = git(entry.path, ["log", "-1", "--format=%cI%x00%s"]);
  if (log.ok && log.out.trim()) {
    const [at, subject] = log.out.replace(/\n$/, "").split("\u0000");
    item.last_commit_at = at || null;
    item.last_commit_subject = subject ?? null;
  } else if (!log.ok) {
    item.error = log.error;
  }
  const status = git(entry.path, ["status", "--porcelain"]);
  if (status.ok) item.dirty_count = status.out.split("\n").filter(Boolean).length;
  else item.error = item.error || status.error;
  return item;
}

function commitTime(item) {
  const ms = item.last_commit_at ? Date.parse(item.last_commit_at) : NaN;
  return Number.isNaN(ms) ? -Infinity : ms;
}

function collectWorktrees(root) {
  const listed = git(root, ["worktree", "list", "--porcelain"]);
  if (!listed.ok) return { worktrees: [], newestActivity: null, error: listed.error };
  const worktrees = parsePorcelain(listed.out).map(describeWorktree).sort((a, b) => commitTime(b) - commitTime(a));
  const newest = worktrees.find(w => w.last_commit_at) || null;
  return { worktrees, newestActivity: newest, error: null };
}

module.exports = { collectWorktrees, parsePorcelain };
