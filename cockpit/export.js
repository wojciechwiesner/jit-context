#!/usr/bin/env node
// Cockpit data export for other tools (Mission Control): node export.js <project_dir>
// Prints collect() as JSON. Drops git.tracked (file list, large) and serialises dates.
const path = require("path");
const { collect } = require("./collect");

const root = path.resolve(process.argv[2] || process.cwd());
const data = collect(root);
const { tracked, ...git } = data.git;
const output = { ...data, git: { ...git, trackedCount: tracked.length } };
process.stdout.write(JSON.stringify(output, (key, value) => (value instanceof Date ? value.toISOString() : value)));
