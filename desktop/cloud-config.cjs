'use strict';

const CLOUD_NAMES = Object.freeze([
  'AZURE_SPEECH_KEY',
  'AZURE_SPEECH_REGION',
  'AZURE_PHRASE_LIST',
]);
const CLOUD_NAME_SET = new Set(CLOUD_NAMES);

// Parse only the desktop application's fixed cloud settings, never arbitrary env.
function parseCloudConfig(text = '') {
  const values = Object.fromEntries(CLOUD_NAMES.map((name) => [name, '']));
  for (const line of String(text ?? '').replace(/^\uFEFF/, '').split(/\r\n|\n|\r/)) {
    const separator = line.indexOf('=');
    if (separator < 0) continue;
    const name = line.slice(0, separator).trim();
    if (!CLOUD_NAME_SET.has(name)) continue;
    let value = line.slice(separator + 1).trim();
    const quote = value[0];
    if (value.length >= 2 && (quote === '"' || quote === "'") && value.at(-1) === quote) {
      value = value.slice(1, -1).trim();
    }
    values[name] = value;
  }
  return values;
}

function cloudEnvironment(inherited = {}, text = '') {
  const environment = { ...inherited };
  // Windows treats names as case-insensitive. Remove alternate casing before
  // adding the canonical names so Node cannot spawn with duplicate cloud keys.
  for (const name of Object.keys(environment)) {
    if (CLOUD_NAME_SET.has(name.toUpperCase())) delete environment[name];
  }
  return Object.assign(environment, parseCloudConfig(text));
}

// A legacy file may fill missing settings, but can never replace a complete
// primary configuration or disagree with settings the user has already chosen.
function cloudConfigMigration(primaryText = '', legacyText = '') {
  const primary = parseCloudConfig(primaryText);
  const legacy = parseCloudConfig(legacyText);
  if (primary.AZURE_SPEECH_KEY && primary.AZURE_SPEECH_REGION) return null;
  if (!legacy.AZURE_SPEECH_KEY || !legacy.AZURE_SPEECH_REGION) return null;
  for (const name of ['AZURE_SPEECH_KEY', 'AZURE_SPEECH_REGION']) {
    if (primary[name] && primary[name] !== legacy[name]) return null;
  }
  return {
    AZURE_SPEECH_KEY: legacy.AZURE_SPEECH_KEY,
    AZURE_SPEECH_REGION: legacy.AZURE_SPEECH_REGION,
    AZURE_PHRASE_LIST: primary.AZURE_PHRASE_LIST || legacy.AZURE_PHRASE_LIST,
  };
}

function updateCloudConfigText(text = '', values = {}) {
  const source = String(text ?? '').replace(/^\uFEFF/, '');
  const updates = new Map();
  for (const name of CLOUD_NAMES) {
    if (!Object.hasOwn(values, name) || typeof values[name] !== 'string') continue;
    const value = values[name].trim();
    if (/[\r\n\u0000]/.test(value)) throw new Error('Cloud settings must contain a single line');
    updates.set(name, value);
  }
  if (!updates.size) return source;
  const newline = source.includes('\r\n') ? '\r\n' : source.includes('\r') ? '\r' : '\n';
  const seen = new Set();
  const lines = [];
  for (const line of source.split(/\r\n|\n|\r/)) {
    const separator = line.indexOf('=');
    const name = separator < 0 ? '' : line.slice(0, separator).trim();
    if (!updates.has(name)) { lines.push(line); continue; }
    if (!seen.has(name)) {
      lines.push(`${name}=${updates.get(name)}`);
      seen.add(name);
    }
  }
  // A final split item represents the existing line ending, not an extra row.
  if (lines.at(-1) === '') lines.pop();
  for (const [name, value] of updates) {
    if (!seen.has(name)) lines.push(`${name}=${value}`);
  }
  return `${lines.join(newline)}${newline}`;
}

module.exports = { parseCloudConfig, cloudEnvironment, cloudConfigMigration, updateCloudConfigText };
