'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const helpers = require('../cloud-config.cjs');

const source = fs.readFileSync(path.join(__dirname, '../main.cjs'), 'utf8');
const start = source.indexOf('function recoverSavedCloudConfig(');
const end = source.indexOf('\nfunction saveState()', start);
assert.ok(start >= 0 && end > start);
const functionSource = source.slice(start, end);
const roaming = path.resolve('migration-fixture', 'AppData', 'Roaming');
const primary = path.join(roaming, 'Subtitle Studio', '.env');
const legacy = path.join(path.dirname(roaming), 'Local', 'Packages',
  'OpenAI.Codex_2p2nqsd0c76g0', 'LocalCache', 'Roaming', 'Subtitle Studio', '.env');

function harness(primaryText, options = {}) {
  const files = new Map([[primary, primaryText]]);
  if (options.legacyText !== undefined) files.set(legacy, options.legacyText);
  const reads = [];
  const writes = [];
  const mockFs = {
    existsSync: (file) => files.has(file),
    readFileSync: (file) => {
      reads.push(file);
      if (file === legacy && options.legacyUnreadable) throw new Error('Legacy access denied');
      if (!files.has(file)) throw new Error('Missing fixture file');
      return files.get(file);
    },
    writeFileSync: (file, text) => { writes.push(file); files.set(file, text); },
    renameSync: (from, to) => { files.set(to, files.get(from)); files.delete(from); },
    unlinkSync: (file) => files.delete(file),
  };
  const context = vm.createContext({fs:mockFs,path,...helpers,
    packaged:options.packaged ?? true,
    process:{pid:123,env:options.env ?? {}},
    app:{getPath:()=>roaming,commandLine:{hasSwitch:()=>options.smoke ?? false}}});
  vm.runInContext(functionSource, context);
  return {run:()=>context.recoverSavedCloudConfig(primary),files,reads,writes};
}

test('a configured normal profile starts without reading an unreadable redirected profile', () => {
  const text = 'AZURE_SPEECH_KEY=primary-key\nAZURE_SPEECH_REGION=primary-region\n';
  const fixture = harness(text, {legacyText:'',legacyUnreadable:true});
  fixture.run();
  assert.deepEqual(fixture.reads, [primary]);
  assert.equal(fixture.writes.length, 0);
  assert.equal(fixture.files.get(primary), text);
});

test('normal first-run startup recovers the fixed redirected profile once and preserves its source', () => {
  const legacyText = 'AZURE_SPEECH_KEY=saved-example-key\nAZURE_SPEECH_REGION=eastasia\n';
  const fixture = harness('# Keep user settings\nAZURE_SPEECH_KEY=\nAZURE_SPEECH_REGION=\nCUSTOM=keep\n', {legacyText});
  fixture.run();
  const saved = fixture.files.get(primary);
  assert.equal(helpers.parseCloudConfig(saved).AZURE_SPEECH_KEY, 'saved-example-key');
  assert.equal(helpers.parseCloudConfig(saved).AZURE_SPEECH_REGION, 'eastasia');
  assert.match(saved, /CUSTOM=keep/);
  assert.equal(fixture.files.get(legacy), legacyText);
  assert.equal(fixture.writes.length, 1);
  fixture.run();
  assert.equal(fixture.writes.length, 1);
  assert.equal(fixture.files.get(primary), saved);
});

test('development, explicit config overrides and isolated smoke runs never read or migrate another profile', () => {
  for (const options of [{packaged:false}, {env:{SUBTITLE_STUDIO_ENV_FILE:primary}}, {smoke:true}]) {
    const fixture = harness('', {...options,legacyText:'AZURE_SPEECH_KEY=saved-example-key\nAZURE_SPEECH_REGION=eastasia\n'});
    fixture.run();
    assert.equal(fixture.reads.length, 0);
    assert.equal(fixture.writes.length, 0);
  }
});
