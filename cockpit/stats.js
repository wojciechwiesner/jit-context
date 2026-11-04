// Stats for the "Statystyki" tab: <hub dir>/stats/<slug>.json, written by the hub refresher (src/hub/stats.py).
// Returns { path, data, missing, error }: `missing` says exactly which input is absent, `error` is a read failure.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const STATS_DIR = 'stats';

function hubDir(env = process.env) {
  return env.JIT_HUB_DIR || path.join(env.HERMES_HOME || path.join(os.homedir(), '.hermes'), 'state', 'jit-hub');
}

function collectStats(hubSlug, env = process.env) {
  if (!hubSlug) {
    return { path: null, data: null, error: null,
      missing: 'Projekt nie jest w rejestrze hubu (jit init albo jit hub scan), więc refresher nie zapisuje dla niego statystyk.' };
  }
  const file = path.join(hubDir(env), STATS_DIR, `${hubSlug}.json`);
  let raw;
  try {
    raw = fs.readFileSync(file, 'utf-8');
  } catch (e) {
    if (e.code === 'ENOENT') {
      return { path: file, data: null, error: null,
        missing: `Brak pliku ${file}. Zapisuje go refresher hubu (jit hub refresh) przed budową kokpitu.` };
    }
    return { path: file, data: null, missing: null, error: `Nie można odczytać ${file}: ${e.message}` };
  }
  try {
    const data = JSON.parse(raw);
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('oczekiwano obiektu JSON');
    return { path: file, data, missing: null, error: null };
  } catch (e) {
    return { path: file, data: null, missing: null, error: `Niepoprawny plik statystyk ${file}: ${e.message}` };
  }
}

module.exports = { collectStats, hubDir, STATS_DIR };
