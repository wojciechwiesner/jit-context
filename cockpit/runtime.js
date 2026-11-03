// The runtime secret stays outside repositories; only private, ignored HTML embeds it.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
function chatRuntime(root) {
  try {
    const config = JSON.parse(fs.readFileSync(path.join(os.homedir(), '.hermes/state/project-cockpit/runtime.json'), 'utf8'));
    const entry = Object.entries(config.projects).find(([, value]) => path.resolve(value) === path.resolve(root));
    if (!entry) return null;
    return { url: config.url, model: config.model, token: config.token, page: config.url + entry[0] };
  } catch { return null; }
}
module.exports = { chatRuntime };
