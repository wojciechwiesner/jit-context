#!/usr/bin/env node
// Project cockpit generator: node build_state_template.js <project_dir>
// Writes <project_dir>/.planning/state.html (and refreshes ./state.html if the project keeps one).
// Core logic lives next to this file (vendored from sota-starter); a project can add domain panels via
// .planning/cockpit.module.js and deploy targets via .planning/cockpit.json.
const fs = require("fs");
const path = require("path");
const { collect } = require("./collect");
const { render } = require("./render");

const root = path.resolve(process.argv[2] || process.cwd());
const planning = path.join(root, ".planning");
fs.mkdirSync(planning, { recursive: true });

const data = collect(root);
const html = render(data);
const target = path.join(planning, "state.html");
fs.writeFileSync(target, html, "utf-8");
const rootCopy = path.join(root, "state.html");
if (fs.existsSync(rootCopy)) fs.writeFileSync(rootCopy, html, "utf-8");
if (data.chatRuntime || (data.credentials && data.credentials.entries.length)) {
  fs.chmodSync(target, 0o600);
  if (fs.existsSync(rootCopy)) fs.chmodSync(rootCopy, 0o600);
}
console.log(`cockpit: ${target} (${Math.round(html.length / 1024)} KB)`);
