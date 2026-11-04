// Test entry for `node --test cockpit/`: Node 22 resolves a directory argument as a module
// (package.json "main") instead of expanding it, so this file loads every *.test.js next to it.
const fs = require('node:fs');
const path = require('node:path');

const TEST_SUFFIX = '.test.js';

for (const name of fs.readdirSync(__dirname).filter(n => n.endsWith(TEST_SUFFIX)).sort()) {
  require(path.join(__dirname, name));
}
