'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { parseCloudConfig, cloudEnvironment, cloudConfigMigration, updateCloudConfigText } = require('../cloud-config.cjs');

test('missing cloud settings have exactly the three fixed empty names', () => {
  assert.deepEqual(parseCloudConfig(''), {
    AZURE_SPEECH_KEY: '', AZURE_SPEECH_REGION: '', AZURE_PHRASE_LIST: '',
  });
});

test('BOM, Windows line endings, surrounding spaces and both quote styles are supported', () => {
  const text = '\uFEFF  AZURE_SPEECH_KEY = " example-key "  \r\n' +
    " AZURE_SPEECH_REGION = ' example-region ' \r\n" +
    'AZURE_PHRASE_LIST = "term one;term two=three"\r\n';
  assert.deepEqual(parseCloudConfig(text), {
    AZURE_SPEECH_KEY: 'example-key', AZURE_SPEECH_REGION: 'example-region',
    AZURE_PHRASE_LIST: 'term one;term two=three',
  });
});

test('the file replaces inherited stale or whitespace cloud values', () => {
  const inherited = {
    AZURE_SPEECH_KEY: ' ', AZURE_SPEECH_REGION: ' ', AZURE_PHRASE_LIST: 'stale phrase',
    PATH: 'example-path',
  };
  const original = { ...inherited };
  const merged = cloudEnvironment(inherited,
    'AZURE_SPEECH_KEY=example-key\nAZURE_SPEECH_REGION=example-region\nAZURE_PHRASE_LIST=updated phrase');
  assert.deepEqual(merged, {
    AZURE_SPEECH_KEY: 'example-key', AZURE_SPEECH_REGION: 'example-region',
    AZURE_PHRASE_LIST: 'updated phrase', PATH: 'example-path',
  });
  assert.deepEqual(inherited, original, 'Merging must not mutate the parent environment');
});

test('an empty or cleared file prevents inherited credentials from surviving', () => {
  const inherited = {
    AZURE_SPEECH_KEY: 'old-key', AZURE_SPEECH_REGION: 'old-region', AZURE_PHRASE_LIST: 'old phrases',
  };
  const cleared = { AZURE_SPEECH_KEY: '', AZURE_SPEECH_REGION: '', AZURE_PHRASE_LIST: '' };
  assert.deepEqual(cloudEnvironment(inherited, ''), cleared);
  assert.deepEqual(cloudEnvironment(inherited,
    'AZURE_SPEECH_KEY=""\nAZURE_SPEECH_REGION=  \nAZURE_PHRASE_LIST=\'\''), cleared);
});

test('unknown settings and aliases cannot overwrite or add process environment values', () => {
  const inherited = { NODE_OPTIONS: '--example-inherited-option', PATH: 'original-path' };
  const merged = cloudEnvironment(inherited,
    'NODE_OPTIONS=--example-file-option\nPATH=overridden-path\nPYTHONHOME=untrusted-home\n' +
    'azure_speech_key=alias-key\nSPEECH_KEY=alias-key\nexport AZURE_SPEECH_REGION=alias-region\n' +
    '__proto__=untrusted-prototype\nAZURE_SPEECH_KEY=example-key');
  assert.deepEqual(merged, {
    NODE_OPTIONS: '--example-inherited-option', PATH: 'original-path',
    AZURE_SPEECH_KEY: 'example-key', AZURE_SPEECH_REGION: '', AZURE_PHRASE_LIST: '',
  });
});

test('Windows case variants of inherited cloud names cannot retain conflicting values', () => {
  assert.deepEqual(cloudEnvironment({ azure_speech_key: 'old-key', Azure_Speech_Region: 'old-region',
    azure_phrase_list: 'old phrase', PATH: 'unchanged' }, 'AZURE_SPEECH_REGION=example-region'), {
    PATH: 'unchanged', AZURE_SPEECH_KEY: '', AZURE_SPEECH_REGION: 'example-region', AZURE_PHRASE_LIST: '',
  });
});

const legacyText = 'AZURE_SPEECH_KEY=example-legacy-key\nAZURE_SPEECH_REGION=example-region\nAZURE_PHRASE_LIST=legacy phrase\n';

test('an empty first-run template migrates the complete legacy credentials together', () => {
  const template = '# Cloud settings\r\nAZURE_SPEECH_KEY=\r\nAZURE_SPEECH_REGION=\r\n';
  const migration = cloudConfigMigration(template, legacyText);
  assert.deepEqual(migration, {
    AZURE_SPEECH_KEY: 'example-legacy-key', AZURE_SPEECH_REGION: 'example-region', AZURE_PHRASE_LIST: 'legacy phrase',
  });
  const updated = updateCloudConfigText(template, migration);
  assert.deepEqual(parseCloudConfig(updated), migration);
  assert.ok(updated.startsWith('# Cloud settings\r\n'));
  assert.ok(updated.endsWith('AZURE_PHRASE_LIST=legacy phrase\r\n'));
});

test('a complete primary configuration is never overwritten, including a deliberately different API', () => {
  assert.equal(cloudConfigMigration(legacyText, legacyText), null);
  assert.equal(cloudConfigMigration('AZURE_SPEECH_KEY=chosen-key\nAZURE_SPEECH_REGION=chosen-region\n', legacyText), null);
});

test('a partial primary configuration that disagrees with legacy values is left untouched', () => {
  assert.equal(cloudConfigMigration('AZURE_SPEECH_KEY=chosen-key\n', legacyText), null);
  assert.equal(cloudConfigMigration('AZURE_SPEECH_REGION=chosen-region\n', legacyText), null);
});

test('compatible partial primary settings fill the missing value and preserve chosen phrases', () => {
  for (const primary of [
    'AZURE_SPEECH_KEY="example-legacy-key"\nAZURE_PHRASE_LIST=chosen phrase\n',
    "AZURE_SPEECH_REGION='example-region'\nAZURE_PHRASE_LIST=chosen phrase\n",
  ]) {
    const migration = cloudConfigMigration(primary, '\uFEFF' + legacyText);
    assert.deepEqual(migration, {
      AZURE_SPEECH_KEY: 'example-legacy-key', AZURE_SPEECH_REGION: 'example-region', AZURE_PHRASE_LIST: 'chosen phrase',
    });
    assert.deepEqual(parseCloudConfig(updateCloudConfigText(primary, migration)), migration);
  }
});

test('incomplete or empty legacy settings cannot cause a partial credentials migration', () => {
  for (const legacy of ['', 'AZURE_SPEECH_KEY=example-key\n', 'AZURE_SPEECH_REGION=example-region\n']) {
    assert.equal(cloudConfigMigration('', legacy), null);
  }
});

test('upserts normalize BOM, quoted and duplicate managed rows while preserving unrelated lines', () => {
  const original = '\uFEFF# Keep this comment\r\nUNRELATED="keep=exactly"\r\n' +
    ' AZURE_SPEECH_KEY = "old-key"\r\nAZURE_SPEECH_KEY=duplicate-key\r\n' +
    "AZURE_SPEECH_REGION='old-region'\r\n# AZURE_SPEECH_KEY=comment only\r\n";
  const migration = cloudConfigMigration('', legacyText);
  const updated = updateCloudConfigText(original, { ...migration, NODE_OPTIONS: '--ignored' });
  assert.deepEqual(parseCloudConfig(updated), migration);
  assert.equal((updated.match(/^AZURE_SPEECH_KEY=/gm) || []).length, 1);
  assert.equal(updated.includes('\uFEFF'), false);
  assert.ok(updated.includes('UNRELATED="keep=exactly"\r\n'));
  assert.ok(updated.includes('# AZURE_SPEECH_KEY=comment only\r\n'));
  assert.equal(updated.includes('NODE_OPTIONS'), false);
});

test('a partial upsert keeps other managed values and can explicitly clear a selected field', () => {
  const updated = updateCloudConfigText(legacyText, { AZURE_PHRASE_LIST: '' });
  assert.deepEqual(parseCloudConfig(updated), {
    AZURE_SPEECH_KEY: 'example-legacy-key', AZURE_SPEECH_REGION: 'example-region', AZURE_PHRASE_LIST: '',
  });
});

test('serialization prevents multiline settings from adding arbitrary environment rows', () => {
  assert.throws(() => updateCloudConfigText('', { AZURE_PHRASE_LIST: 'phrase\nNODE_OPTIONS=untrusted' }), /single line/);
  assert.throws(() => updateCloudConfigText('', { AZURE_SPEECH_KEY: 'example\0key' }), /single line/);
});
