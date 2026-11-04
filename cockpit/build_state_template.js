#!/usr/bin/env node
// Project cockpit generator: node build_state_template.js <project_dir> [--out <file>] [--hub-slug <slug>]
// Writes <project_dir>/.planning/state.html (and refreshes ./state.html if the project keeps one).
// With --out it writes only <file> (atomically) and leaves the project tree untouched: the Project Hub
// uses this for repos that track state.html in git.
// Core logic lives next to this file (vendored from sota-starter); a project can add domain panels via
// .planning/cockpit.module.js and deploy targets via .planning/cockpit.json.
const fs = require("fs");
const path = require("path");
const { collect } = require("./collect");
const { render } = require("./render");
const { resolveHubSlug } = require("./freshness");
const { collectStats } = require("./stats");

const RESTRICTED_MODE = 0o600;
const DEFAULT_MODE = 0o644;

const args = process.argv.slice(2);
const outIndex = args.indexOf("--out");
if (outIndex >= 0 && !args[outIndex + 1]) {
  console.error("build_state_template: --out needs a file path");
  process.exit(2);
}
const outFile = outIndex >= 0 ? path.resolve(args.splice(outIndex, 2)[1]) : null;
const hubSlugIndex = args.indexOf("--hub-slug");
const hubSlugArg = hubSlugIndex >= 0 ? args.splice(hubSlugIndex, 2)[1] : null;
const root = path.resolve(args[0] || process.cwd());
const planning = path.join(root, ".planning");
if (!outFile) fs.mkdirSync(planning, { recursive: true });

const data = collect(root);
data.hubSlug = resolveHubSlug(root, data.worktrees, hubSlugArg);
data.stats = collectStats(data.hubSlug);
const html = render(data);
const restricted = Boolean(data.credentials && data.credentials.entries.length);

function writeOut(file) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp-${process.pid}`;
  fs.writeFileSync(tmp, html, { encoding: "utf-8", mode: restricted ? RESTRICTED_MODE : DEFAULT_MODE });
  fs.renameSync(tmp, file);
  return file;
}

function writeInPlace() {
  const target = path.join(planning, "state.html");
  fs.writeFileSync(target, html, "utf-8");
  const rootCopy = path.join(root, "state.html");
  if (fs.existsSync(rootCopy)) fs.writeFileSync(rootCopy, html, "utf-8");
  if (restricted) {
    fs.chmodSync(target, RESTRICTED_MODE);
    if (fs.existsSync(rootCopy)) fs.chmodSync(rootCopy, RESTRICTED_MODE);
  }
  return target;
}

const written = outFile ? writeOut(outFile) : writeInPlace();
console.log(`cockpit: ${written} (${Math.round(html.length / 1024)} KB)`);
