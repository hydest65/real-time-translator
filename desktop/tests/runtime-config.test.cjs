'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Exercise the shipped frontend functions, without any real socket, audio or cloud call.
const source = fs.readFileSync(path.join(__dirname, '../../frontend/app.js'), 'utf8');
function functionRange(begin, end) {
  const from = source.indexOf(begin);
  const to = source.indexOf(end, from);
  assert.ok(from >= 0 && to > from, `Frontend function range exists: ${begin}`);
  return source.slice(from, to);
}
const functions = functionRange('function loadRuntimeConfig()', 'function updateMeetingActionButtons()') +
  functionRange('function updateMeetingActionButtons()', 'function setDelayHint(') +
  functionRange('async function start()', 'function stop()');
const response = (configured) => ({ ok: true, json: async () => ({ cloud_configured: configured }) });
const flush = () => new Promise((resolve) => setImmediate(resolve));

function harness(fetchConfig, getCloudConfig = async () => ({ configured: true })) {
  const events = [];
  const statuses = [];
  const sockets = [];
  const requests = [];
  const timers = new Map();
  const panel = () => ({ innerHTML: 'existing captions' });
  class FakeWebSocket {
    static OPEN = 1;
    static CONNECTING = 0;
    constructor(url) { this.url = url; this.readyState = FakeWebSocket.CONNECTING; sockets.push(this); }
    addEventListener() {}
  }
  const context = {
    AbortController, Event, WebSocket: FakeWebSocket,
    socket: null, azureConfigured: false, funasrConfigured: false,
    runtimeConfigLoaded: false, runtimeConfigPromise: null, isStartPending: false,
    isLiveSessionActive: false, isRecordingActive: false, quotaBlocked: false,
    englishContextTypeTimer: null, currentRecordingPath: 'previous-recording.wav',
    subtitleStack: panel(), englishContextStack: panel(), englishDraftStack: panel(), chineseSubtitleStack: panel(),
    startButton: {}, stopButton: {}, endMeetingButton: {},
    translationEngine: { value: 'azure' }, statusText: { textContent: 'Stopped' },
    noticeText: { textContent: 'Ready' }, logText: { textContent: '' }, perfText: {},
    window: { subtitleDesktop: { getCloudConfig }, location: { protocol: 'http:', host: 'example.invalid' },
      dispatchEvent: (event) => events.push(event.type) },
    fetch: (url, options) => { requests.push({ url, options }); return fetchConfig(url, options); },
    setTimeout: (callback, delay) => { const id = {}; timers.set(id, { callback, delay }); return id; },
    clearTimeout: (id) => timers.delete(id),
    cloudQuotaExceeded: () => context.quotaBlocked,
    cloudQuotaMessage: () => 'Quota reached',
    renderAzureUsage() {}, updateDelayHintFromStatus() {}, updateEngineControls() {}, updateLanguageHints() {},
    updateRecordingPanel() {}, updateExportButtons() {}, useFunasrStreamingMode: () => false,
    setStatus: (status, detail = '') => {
      statuses.push({ status, detail }); context.logText.textContent = detail || status;
      context.statusText.textContent = status;
      context.updateMeetingActionButtons();
    },
  };
  vm.createContext(context);
  vm.runInContext(functions, context);
  return { context, events, statuses, sockets, requests, timers };
}

function assertPreserved(run) {
  assert.equal(run.sockets.length, 0);
  assert.equal(run.context.isLiveSessionActive, false);
  assert.equal(run.context.isRecordingActive, false);
  assert.equal(run.context.currentRecordingPath, 'previous-recording.wav');
  for (const name of ['subtitleStack', 'englishContextStack', 'englishDraftStack', 'chineseSubtitleStack']) {
    assert.equal(run.context[name].innerHTML, 'existing captions');
  }
  assert.equal(run.context.isStartPending, false);
  assert.equal(run.context.startButton.disabled, false);
}

test('an early and repeated Start waits for the pending initial config, then opens one socket without CFG', async () => {
  let resolve;
  const run = harness(() => new Promise((done) => { resolve = done; }));
  const initial = run.context.loadRuntimeConfig();
  const start = run.context.start();
  await run.context.start();
  assert.equal(run.requests.length, 1);
  assert.equal(run.context.startButton.disabled, true);
  assert.equal(run.context.subtitleStack.innerHTML, 'existing captions');
  assert.equal(run.sockets.length, 0);
  assert.deepEqual(run.events, []);
  resolve(response(true));
  assert.equal(await initial, true);
  await start;
  assert.equal(run.sockets.length, 1);
  assert.deepEqual(run.events, []);
  assert.equal(run.context.isLiveSessionActive, true);
  assert.equal(run.context.isRecordingActive, true);
  assert.equal(run.context.noticeText.textContent, 'Ready');
  assert.equal(run.statuses.at(-1).status, 'Connecting');
  assert.equal(run.context.runtimeConfigPromise, null);
  await run.context.start();
  assert.equal(run.requests.length, 1, 'A socket that is connecting cannot be started twice');
  assert.equal(run.sockets.length, 1);
});

test('an initial transient read failure is retried on Start and recovers without requesting credentials', async () => {
  let calls = 0;
  const run = harness(async () => {
    if (++calls === 1) throw new Error('Temporary local service failure');
    return response(true);
  });
  assert.equal(await run.context.loadRuntimeConfig(), false);
  await run.context.start();
  assert.equal(run.requests.length, 2);
  assert.equal(run.sockets.length, 1);
  assert.deepEqual(run.events, []);
  assert.equal(run.statuses.at(-1).status, 'Connecting');
});

test('Start rechecks a previously successful config instead of relying on stale frontend state', async () => {
  let calls = 0;
  const run = harness(async () => response(++calls === 1), async () => ({ configured: true }));
  assert.equal(await run.context.loadRuntimeConfig(), true);
  await run.context.start();
  assert.equal(run.requests.length, 2);
  assertPreserved(run);
  assert.deepEqual(run.events, []);
  assert.match(run.statuses.at(-1).detail, /云配置已保存/);
  assert.match(run.statuses.at(-1).detail, /无需重新填写密钥/);
});

test('request, response and schema failures preserve captions and never open the credentials form', async () => {
  const failures = [
    async () => { throw new Error('Temporary failure'); },
    async () => ({ ok: false }),
    async () => ({ ok: true, json: async () => { throw new Error('Invalid JSON'); } }),
    async () => response('false'),
    async () => response(null),
    async () => ({ ok: true, json: async () => ({}) }),
  ];
  for (const fetchConfig of failures) {
    const run = harness(fetchConfig);
    await run.context.start();
    assertPreserved(run);
    assert.deepEqual(run.events, []);
    assert.equal(run.context.runtimeConfigLoaded, false);
    assert.equal(run.statuses.at(-1).status, 'Error');
    assert.match(run.statuses.at(-1).detail, /无需重新填写密钥/);
  }
});

test('a bounded config timeout cancels the read and preserves captions without a configuration prompt', async () => {
  const run = harness((_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new Error('Aborted')));
  }));
  const pending = run.context.start();
  const timer = [...run.timers.values()][0];
  assert.equal(timer.delay, 5000);
  assert.equal(run.requests[0].options.cache, 'no-store');
  timer.callback();
  await pending;
  assert.equal(run.requests[0].options.signal.aborted, true);
  assertPreserved(run);
  assert.deepEqual(run.events, []);
  assert.equal(run.timers.size, 0);
});

test('only confirmed missing backend and saved credentials open CFG, without clearing old captions', async () => {
  const run = harness(async () => response(false), async () => ({ configured: false }));
  await run.context.start();
  assertPreserved(run);
  assert.deepEqual(run.events, ['subtitle-cloud-config-required']);
  assert.equal(run.context.runtimeConfigLoaded, true);
  assert.match(run.statuses.at(-1).detail, /填写区域和密钥/);
});

test('saved configuration read failures do not imply missing credentials', async () => {
  for (const getSaved of [
    async () => { throw new Error('Local read failed'); },
    async () => ({ configured: 'false' }),
  ]) {
    const run = harness(async () => response(false), getSaved);
    await run.context.start();
    assertPreserved(run);
    assert.deepEqual(run.events, []);
    assert.match(run.statuses.at(-1).detail, /无法读取本机云配置/);
  }
});

test('quota updates received during preflight still prevent socket and recording startup', async () => {
  let resolve;
  const run = harness(() => new Promise((done) => { resolve = done; }));
  const pending = run.context.start();
  run.context.quotaBlocked = true;
  resolve(response(true));
  await pending;
  assert.equal(run.sockets.length, 0);
  assert.equal(run.context.isLiveSessionActive, false);
  assert.equal(run.context.isRecordingActive, false);
  assert.equal(run.context.subtitleStack.innerHTML, 'existing captions');
  assert.deepEqual(run.events, []);
  assert.equal(run.statuses.at(-1).detail, 'Quota reached');
  assert.equal(run.context.startButton.disabled, true);
});

test('separate failed Start attempts recheck the service instead of retaining a failed promise', async () => {
  const run = harness(async () => { throw new Error('Temporary failure'); });
  await run.context.start();
  await flush();
  await run.context.start();
  assert.equal(run.requests.length, 2);
  assertPreserved(run);
  assert.deepEqual(run.events, []);
});
