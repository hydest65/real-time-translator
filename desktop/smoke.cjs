// Opt-in integration verification against this application's actual native window.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { resizeBounds } = require('./geometry.cjs');

async function runSmoke(window, outputDir, baseURL, restoring = false) {
  fs.mkdirSync(outputDir, { recursive: true });
  const checks = [];
  const evaluate = (script) => window.webContents.executeJavaScript(script);
  const waitFrame = () => new Promise((resolve) => setTimeout(resolve, 400));
  try {
    await waitFrame();
    if (restoring) {
      assert.equal(await evaluate(`document.getElementById('translationFontSize').value`), '48');
      assert.equal(await evaluate(`document.getElementById('sourceFontSize').value`), '22');
      assert.equal(await evaluate(`document.getElementById('sourceFontColor').value`), '#345f93');
      assert.equal(await evaluate(`document.getElementById('translationFontColor').value`), '#7b3f69');
      assert.equal(await evaluate(`document.getElementById('desktopOpacity').value`), '55');
      assert.equal(await evaluate(`document.body.classList.contains('caption-only')`), true);
      assert.equal(window.getBounds().width, 420);
      assert.equal(window.getBounds().height, 240);
      checks.push('Window, font sizes and colors, opacity and view restored after a full process restart');
      assert.equal(await evaluate(`document.getElementById('toggleSourceText').getAttribute('aria-pressed')`), 'false');
      assert.equal(await evaluate(`document.getElementById('toggleTranslationText').getAttribute('aria-pressed')`), 'true');
      checks.push('Independent caption visibility restored after a full process restart');
      await evaluate(`document.getElementById('toggleSourceText').click()`);
      window.setBounds({ ...window.getBounds(), width: 1000, height: 620 });
    }
    assert.equal(await evaluate(`document.getElementById('toggleSourceText').getAttribute('aria-pressed')`), 'true');
    assert.equal(await evaluate(`document.getElementById('toggleTranslationText').getAttribute('aria-pressed')`), 'true');
    const response = await fetch(`${baseURL}/api/health`);
    const health = await response.json();
    assert.equal(health.ok, true);
    checks.push('Packaged backend health');
    const config = await evaluate('window.subtitleDesktop.getCloudConfig()');
    assert.equal(Object.hasOwn(config, 'key'), false);
    checks.push('Configuration does not expose the saved key');
    assert.equal(health.config?.cloud_configured, config.configured,
      'The packaged backend and desktop configuration must agree despite inherited cloud environment values');
    checks.push('Backend and desktop agree on the local cloud configuration');
    assert.equal(await evaluate('window.subtitleDesktop.setAlwaysOnTop(false)'), false);
    assert.equal(window.isAlwaysOnTop(), false);
    assert.equal(await evaluate('window.subtitleDesktop.setAlwaysOnTop(true)'), true);
    checks.push('Native always-on-top toggle via isolated bridge');
    await evaluate(`(() => {
      renderSubtitle({ sequenceId: 'desktop-smoke', sourceText: 'Live subtitles, sized just for you.',
        translatedText: '字幕窗口可以自由调整大小，半透明背景让会议画面保持可见。', start: 0, end: 5, isFinal: true });
      if (document.body.classList.contains('caption-only')) document.getElementById('exitCaptionView').click();
      const input = document.getElementById('translationFontSize');
      input.value = '48'; input.dispatchEvent(new Event('input', { bubbles: true }));
      document.getElementById('sourceFontSlider').value = '22';
      document.getElementById('sourceFontSlider').dispatchEvent(new Event('input', { bubbles: true }));
      document.getElementById('desktopOpacity').value = '55';
      document.getElementById('desktopOpacity').dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.translation')).fontSize`), '48px');
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.source')).fontSize`), '22px');
    assert.equal(await evaluate(`getComputedStyle(document.body, '::before').backgroundColor`), 'rgba(248, 250, 253, 0.55)');
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.translation')).opacity`), '1');
    checks.push('Independent font controls and background-only transparency');
    const titleColor = await evaluate(`getComputedStyle(document.querySelector('.desktop-drag-label')).color`);
    const applyTestColors = `(() => {
      const source = document.getElementById('sourceFontColor');
      source.value = '#345f93'; source.dispatchEvent(new Event('input', { bubbles: true }));
      const translation = document.getElementById('translationFontColorHex');
      translation.value = '#7B3F69'; translation.dispatchEvent(new Event('input', { bubbles: true }));
    })()`;
    await evaluate(applyTestColors);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.source')).color`), 'rgb(52, 95, 147)');
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.translation')).color`), 'rgb(123, 63, 105)');
    assert.equal(await evaluate(`document.getElementById('translationFontColor').value`), '#7b3f69');
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.desktop-drag-label')).color`), titleColor);
    assert.equal(await evaluate(`getComputedStyle(document.body, '::before').backgroundColor`), 'rgba(248, 250, 253, 0.55)');
    checks.push('Independent picker and HEX color changes affect captions without recoloring controls or background');
    await evaluate(`(() => {
      const hex = document.getElementById('translationFontColorHex');
      hex.value = '#12'; hex.dispatchEvent(new Event('input', { bubbles: true }));
      hex.dispatchEvent(new Event('blur'));
    })()`);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.translation')).color`), 'rgb(123, 63, 105)');
    assert.equal(await evaluate(`document.getElementById('translationFontColorHex').value.toLowerCase()`), '#7b3f69');
    await evaluate(`window.subtitleDesktop.saveDisplayPreferences({ sourceFontColor: 'transparent', translationFontColor: '#123' })`);
    const storedColors = await evaluate(`window.subtitleDesktop.getState()`);
    assert.equal(storedColors.display.sourceFontColor, '#345f93');
    assert.equal(storedColors.display.translationFontColor, '#7b3f69');
    checks.push('Incomplete HEX entry and invalid native color values preserve the last valid colors');
    await evaluate(`document.getElementById('resetCaptionFonts').click()`);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.source')).color`), 'rgb(104, 120, 140)');
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.translation')).color`), 'rgb(40, 52, 69)');
    const resetColors = await evaluate(`window.subtitleDesktop.getState()`);
    assert.equal(resetColors.display.sourceFontColor, '#68788c');
    assert.equal(resetColors.display.translationFontColor, '#283445');
    checks.push('Reset restores and persists default subtitle colors');
    await evaluate(`(() => {
      for (const [id, value] of [['sourceFontSlider', '22'], ['translationFontSlider', '48']]) {
        const input = document.getElementById(id); input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
    })()`);
    await evaluate(applyTestColors);
    await evaluate(`renderSubtitle({ sequenceId: 'desktop-smoke-colors', sourceText: 'New captions use your chosen colors.',
      translatedText: '新的字幕也会使用你选择的颜色。', start: 5, end: 8, isFinal: true })`);
    assert.ok(await evaluate(`[...document.querySelectorAll('.source')].every(item => getComputedStyle(item).color === 'rgb(52, 95, 147)')`));
    assert.ok(await evaluate(`[...document.querySelectorAll('.translation')].every(item => getComputedStyle(item).color === 'rgb(123, 63, 105)')`));
    checks.push('Newly rendered captions inherit both selected colors');
    await evaluate(`(() => {
      const entries = [{ sourceText: 'Original text also follows the chosen source color.', translatedText: '连续译文也使用选择的颜色。' }];
      renderTextFlow(englishContextStack, entries, 'sourceText', 760, 'context');
      renderTextFlow(chineseSubtitleStack, entries, 'translatedText', 760, 'translation');
    })()`);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('#englishContextStack .english-flow-text')).color`), 'rgb(52, 95, 147)');
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('#chineseSubtitleStack .translation-flow-text')).color`), 'rgb(123, 63, 105)');
    checks.push('English source and continuous translation renderers use their independent chosen colors');
    const visibility = () => evaluate(`(() => ({
      source: document.querySelector('#subtitleStack .source')?.getClientRects().length > 0,
      translation: document.querySelector('#subtitleStack .translation')?.getClientRects().length > 0,
      hint: !document.getElementById('captionVisibilityNotice').hidden &&
        document.getElementById('captionVisibilityNotice').getClientRects().length > 0,
      sourcePressed: document.getElementById('toggleSourceText').getAttribute('aria-pressed'),
      translationPressed: document.getElementById('toggleTranslationText').getAttribute('aria-pressed'),
      data: document.getElementById('subtitleStack').innerHTML,
      session: isLiveSessionActive,
    }))()`);
    await evaluate(`document.getElementById('toggleSourceText').click()`);
    let visible = await visibility();
    assert.equal(visible.source, false);
    assert.equal(visible.translation, true);
    await evaluate(`renderSubtitle({ sequenceId: 'desktop-visibility-new', sourceText: 'Hidden original remains in the transcript.',
      translatedText: '新译文继续显示。', start: 8, end: 9, isFinal: true })`);
    visible = await visibility();
    assert.equal(visible.source, false);
    assert.equal(visible.translation, true);
    assert.ok(visible.data.includes('Hidden original remains'));
    const dataBeforeHide = visible.data;
    const sessionBeforeHide = visible.session;
    await evaluate(`document.getElementById('toggleTranslationText').click()`);
    visible = await visibility();
    assert.equal(visible.source, false);
    assert.equal(visible.translation, false);
    assert.equal(visible.hint, true);
    assert.equal(visible.data, dataBeforeHide);
    assert.equal(visible.session, sessionBeforeHide);
    await evaluate(`document.getElementById('toggleSourceText').click()`);
    visible = await visibility();
    assert.equal(visible.source, true);
    assert.equal(visible.translation, false);
    assert.equal(visible.hint, false);
    assert.equal(visible.data, dataBeforeHide);
    checks.push('Source-only, translation-only and both-hidden choices preserve existing and incoming caption data');
    await waitFrame();
    let visibilityState = await evaluate(`window.subtitleDesktop.getState()`);
    assert.equal(visibilityState.display.showSourceText, true);
    assert.equal(visibilityState.display.showTranslationText, false);
    await evaluate(`window.subtitleDesktop.saveDisplayPreferences({showSourceText:'false',showTranslationText:1})`);
    visibilityState = await evaluate(`window.subtitleDesktop.getState()`);
    assert.equal(visibilityState.display.showSourceText, true);
    assert.equal(visibilityState.display.showTranslationText, false);
    await evaluate(`document.getElementById('toggleTranslationText').click()`);
    checks.push('Visibility preferences persist as validated native booleans without changing the caption session');
    const iconControls = await evaluate(`(() => {
      const controls = [
        ['desktopStart', 'ST'], ['desktopStop', 'SP'], ['desktopView', 'CAP'],
        ['desktopSettings', 'SET'], ['desktopPin', 'PIN'], ['desktopMinimize'], ['desktopClose'],
        ['desktopSettingsClose'], ['desktopCloudSettings', 'CFG'], ['desktopDataFolder', 'LOG'],
        ['resetCaptionFonts', 'RST'], ['retryConnectionCheck', 'CHK'],
        ['toggleSourceText', 'SRC'], ['toggleTranslationText', 'TR'],
      ].map(([id, abbreviation]) => ({ button: document.getElementById(id), id, abbreviation }));
      controls.push({ button: document.querySelector('.desktop-cloud-form button[type="submit"]'), id: 'cloudSave', abbreviation: 'SAV' });
      return controls.map(({ button, id, abbreviation }) => {
        const svg = button?.querySelector('svg');
        return { id, abbreviation, hasIcon: Boolean(svg?.firstElementChild),
          decorativeIcon: svg?.getAttribute('aria-hidden') === 'true' && svg?.getAttribute('focusable') === 'false',
          label: button?.getAttribute('aria-label') || '', title: button?.title || '' };
      });
    })()`);
    for (const control of iconControls) {
      assert.equal(control.hasIcon, true, `${control.id} must have a local SVG icon`);
      assert.equal(control.decorativeIcon, true, `${control.id} must use the button label for accessibility`);
      assert.ok(control.label.trim(), `${control.id} must have an accessible label`);
      assert.ok(control.title.trim(), `${control.id} must have a hover hint`);
      if (control.abbreviation) assert.ok(control.title.includes(`（${control.abbreviation}）`),
        `${control.id} must retain its abbreviation in the hover hint`);
    }
    checks.push('Main and settings icon buttons retain accessible labels and abbreviated hover hints');
    await waitFrame();
    fs.writeFileSync(path.join(outputDir, 'full-view.png'), (await window.webContents.capturePage()).toPNG());
    await evaluate(`document.getElementById('desktopView').click()`);
    const oldBounds = window.getBounds();
    window.setBounds(resizeBounds(oldBounds, 'se', 650 - oldBounds.width, 340 - oldBounds.height));
    assert.equal(window.getBounds().width, 650);
    assert.equal(window.getBounds().height, 340);
    await waitFrame();
    assert.equal(await evaluate(`document.body.classList.contains('caption-only')`), true);
    assert.ok(await evaluate(`document.getElementById('subtitleStack').getBoundingClientRect().height > 100`));
    assert.equal(await evaluate(`document.querySelectorAll('.desktop-resize').length`), 8);
    checks.push('Native window resized to 650 x 340 with visible captions');
    fs.writeFileSync(path.join(outputDir, 'caption-view.png'), (await window.webContents.capturePage()).toPNG());
    await evaluate(`(() => {
      const ids = ['backendConnection', 'streamConnection', 'statusText', 'noticeText'];
      window.__activitySmoke = { session: isLiveSessionActive, elements: ids.map(id => {
        const element = document.getElementById(id);
        return { id, text: element.textContent, state: element.dataset.state };
      }) };
    })()`);
    const activity = () => evaluate(`(() => {
      const icon = document.getElementById('desktopActivityIndicator');
      return { state: icon.dataset.state, label: icon.getAttribute('aria-label'), title: icon.title,
        animations: icon.getAnimations({ subtree: true }).filter(animation => animation.playState === 'running').length,
        bounds: (() => { const r = icon.getBoundingClientRect(); return r.width > 0 && r.height > 0 &&
          r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight; })() };
    })()`);
    window.webContents.debugger.attach('1.3');
    try {
      await window.webContents.debugger.sendCommand('Emulation.setEmulatedMedia',
        { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
      await evaluate(`(() => {
        document.getElementById('backendConnection').dataset.state = 'online';
        document.getElementById('streamConnection').dataset.state = 'idle';
        isLiveSessionActive = false; document.getElementById('statusText').textContent = 'Stopped';
        document.getElementById('noticeText').textContent = 'Ready';
      })()`);
      await waitFrame();
      assert.equal((await activity()).state, 'idle');
      assert.equal((await activity()).animations, 0);
      await evaluate(`(() => {
        document.getElementById('streamConnection').dataset.state = 'pending';
        isLiveSessionActive = true; document.getElementById('statusText').textContent = 'Connecting';
      })()`);
      await waitFrame();
      assert.equal((await activity()).state, 'pending');
      await evaluate(`(() => {
        document.getElementById('streamConnection').dataset.state = 'online';
        document.getElementById('statusText').textContent = 'Translating';
        document.getElementById('noticeText').textContent = 'Live';
      })()`);
      await waitFrame();
      const active = await activity();
      assert.equal(active.state, 'active');
      assert.ok(active.animations > 0);
      assert.ok(active.bounds && active.label && active.title);
      fs.writeFileSync(path.join(outputDir, 'caption-active-indicator.png'), (await window.webContents.capturePage()).toPNG());
      await window.webContents.debugger.sendCommand('Emulation.setEmulatedMedia',
        { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
      await waitFrame();
      assert.equal((await activity()).state, 'active');
      assert.equal((await activity()).animations, 0);
      checks.push('Active caption-mode status wave animates only with healthy connections and honors reduced-motion');
      await evaluate(`(() => {
        document.getElementById('streamConnection').dataset.state = 'error';
        document.getElementById('statusText').textContent = 'Error';
      })()`);
      await waitFrame();
      assert.equal((await activity()).state, 'error');
      assert.equal((await activity()).animations, 0);
      checks.push('Caption-mode connection, idle and error states never show a healthy translation animation');
    } finally {
      await window.webContents.debugger.sendCommand('Emulation.setEmulatedMedia', { features: [] });
      window.webContents.debugger.detach();
      await evaluate(`(() => {
        const previous = window.__activitySmoke;
        isLiveSessionActive = previous.session;
        previous.elements.forEach(({ id, text, state }) => {
          const element = document.getElementById(id); element.textContent = text;
          if (state === undefined) delete element.dataset.state; else element.dataset.state = state;
        });
        delete window.__activitySmoke;
      })()`);
      await waitFrame();
    }
    await evaluate(`document.getElementById('desktopSettings').click()`);
    await waitFrame();
    assert.notEqual(await evaluate(`getComputedStyle(document.querySelector('.caption-settings')).display`), 'none');
    checks.push('Caption-only settings remain accessible');
    fs.writeFileSync(path.join(outputDir, 'caption-settings.png'), (await window.webContents.capturePage()).toPNG());

    // Exercise the missing-configuration guard after the three primary images.
    // A constructor spy forbids real recognition, sockets or audio sessions.
    const cloudFile = path.join(outputDir, 'profile', '.env');
    const savedCloudFile = fs.readFileSync(cloudFile);
    fs.writeFileSync(cloudFile, 'AZURE_SPEECH_KEY=\nAZURE_SPEECH_REGION=\n');
    await evaluate(`(() => {
      if (document.body.classList.contains('desktop-settings-open')) document.getElementById('desktopSettingsClose').click();
      if (!document.querySelector('.desktop-cloud-form').hidden) document.getElementById('desktopCloudSettings').click();
      const guard = window.__desktopSmokeStartGuard = { originalWebSocket: window.WebSocket,
        originalFetch: window.fetch,
        originalConfigured: azureConfigured, captions: document.getElementById('subtitleStack').innerHTML,
        constructions: 0 };
      azureConfigured = false;
      window.fetch = (url, ...args) => String(url) === '/api/config' ?
        Promise.resolve({ ok: true, json: async () => ({ cloud_configured: false, funasr_configured: false }) }) :
        guard.originalFetch.call(window, url, ...args);
      window.WebSocket = new Proxy(guard.originalWebSocket, {
        construct() {
          guard.constructions++;
          throw new Error('Smoke verification forbids a socket when cloud configuration is missing');
        },
      });
      document.getElementById('desktopStart').click();
    })()`);
    try {
      await waitFrame();
      const missingConfiguration = await evaluate(`(() => {
        const guard = window.__desktopSmokeStartGuard;
        const panel = document.querySelector('.caption-settings');
        const form = document.querySelector('.desktop-cloud-form');
        const hint = document.querySelector('.desktop-status');
        const bounds = hint.getBoundingClientRect();
        return { constructions: guard.constructions, sessionActive: isLiveSessionActive,
          recordingActive: isRecordingActive, browserAudioActive: Boolean(browserAudioStream),
          captionsUnchanged: guard.captions === document.getElementById('subtitleStack').innerHTML,
          settingsOpen: document.body.classList.contains('desktop-settings-open') &&
            document.getElementById('desktopSettings').getAttribute('aria-expanded') === 'true' &&
            getComputedStyle(panel).display !== 'none',
          cloudFormOpen: !form.hidden && document.getElementById('desktopCloudSettings').getAttribute('aria-expanded') === 'true',
          chineseNotice: document.getElementById('noticeText').textContent === '云服务未配置',
          chineseHintVisible: !hint.hidden && getComputedStyle(hint).display !== 'none' &&
            hint.textContent.includes('填写区域和密钥') && bounds.width > 0 && bounds.height > 0 &&
            bounds.top >= 0 && bounds.bottom <= innerHeight + 1 };
      })()`);
      assert.equal(missingConfiguration.constructions, 0, 'Missing configuration must not construct a recognition socket');
      assert.equal(missingConfiguration.sessionActive, false, 'Missing configuration must not mark a session as active');
      assert.equal(missingConfiguration.recordingActive, false, 'Missing configuration must not start recording');
      assert.equal(missingConfiguration.browserAudioActive, false, 'Missing configuration must not capture browser audio');
      assert.equal(missingConfiguration.captionsUnchanged, true, 'Missing configuration must preserve existing captions');
      assert.equal(missingConfiguration.settingsOpen && missingConfiguration.cloudFormOpen, true,
        'The Start button must open settings and cloud configuration when configuration is missing');
      assert.equal(missingConfiguration.chineseNotice && missingConfiguration.chineseHintVisible, true,
        'The desktop must show a visible Chinese configuration hint');
      checks.push('Start without cloud configuration opens settings and preserves captions without a socket or audio session');
      fs.writeFileSync(path.join(outputDir, 'configuration-required.png'), (await window.webContents.capturePage()).toPNG());
    } finally {
      fs.writeFileSync(cloudFile, savedCloudFile);
      await evaluate(`(() => {
        const guard = window.__desktopSmokeStartGuard;
        if (!guard) return;
        window.WebSocket = guard.originalWebSocket;
        window.fetch = guard.originalFetch;
        azureConfigured = guard.originalConfigured;
        delete window.__desktopSmokeStartGuard;
      })()`);
    }
    await new Promise((resolve) => {
      window.webContents.once('did-finish-load', resolve);
      window.reload();
    });
    await waitFrame();
    assert.equal(await evaluate(`document.getElementById('translationFontSize').value`), '48');
    assert.equal(await evaluate(`document.getElementById('sourceFontSize').value`), '22');
    assert.equal(await evaluate(`document.getElementById('sourceFontColor').value`), '#345f93');
    assert.equal(await evaluate(`document.getElementById('translationFontColor').value`), '#7b3f69');
    assert.equal(await evaluate(`document.getElementById('desktopOpacity').value`), '55');
    assert.equal(await evaluate(`document.body.classList.contains('caption-only')`), true);
    checks.push('Font sizes and colors, transparency and view preferences survived reload');
    const retryChecks = await evaluate(`(async () => {
      const guard = { originalFetch: window.fetch, originalWebSocket: window.WebSocket,
        prompts: 0, constructions: 0, requests: 0, mode: 'failure', release: null };
      const prompt = () => guard.prompts++;
      window.addEventListener('subtitle-cloud-config-required', prompt);
      renderSubtitle({ sequenceId: 'config-retry-history', sourceText: 'Keep these captions while checking saved settings.',
        translatedText: '检查已保存的配置时，保留这段字幕。', start: 0, end: 2, isFinal: true });
      const beforeCaptions = document.getElementById('subtitleStack').innerHTML;
      window.fetch = (url, ...args) => {
        if (String(url) !== '/api/config') return guard.originalFetch.call(window, url, ...args);
        guard.requests++;
        if (guard.mode === 'failure') return Promise.reject(new Error('Synthetic temporary config read failure'));
        if (guard.mode === 'missing') return Promise.resolve({ ok: true,
          json: async () => ({ cloud_configured: false, funasr_configured: false }) });
        return new Promise(resolve => { guard.release = () => resolve({ ok: true,
          json: async () => ({ cloud_configured: true, funasr_configured: false }) }); });
      };
      window.WebSocket = class {
        static OPEN = 1; static CONNECTING = 0; static CLOSED = 3;
        constructor() { guard.constructions++; this.readyState = 0; }
        addEventListener() {} send() {} close() { this.readyState = 3; }
      };
      try {
        await start();
        const readFailure = { prompts: guard.prompts, sockets: guard.constructions,
          captionsKept: beforeCaptions === document.getElementById('subtitleStack').innerHTML,
          session: isLiveSessionActive, audio: Boolean(browserAudioStream),
          hint: document.getElementById('logText').textContent };
        guard.mode = 'missing';
        await start();
        const savedMismatch = { prompts: guard.prompts, sockets: guard.constructions,
          captionsKept: beforeCaptions === document.getElementById('subtitleStack').innerHTML,
          hint: document.getElementById('logText').textContent };
        guard.mode = 'delayed';
        const first = start();
        const second = start();
        await Promise.resolve();
        const pending = { prompts: guard.prompts, sockets: guard.constructions,
          captionsKept: beforeCaptions === document.getElementById('subtitleStack').innerHTML };
        guard.release();
        await Promise.all([first, second]);
        const recovered = { prompts: guard.prompts, sockets: guard.constructions,
          requests: guard.requests, configured: azureConfigured, pending: isStartPending,
          audio: Boolean(browserAudioStream) };
        return { readFailure, savedMismatch, pending, recovered };
      } finally {
        stop(); socket = null; isLiveSessionActive = false; isRecordingActive = false;
        window.fetch = guard.originalFetch; window.WebSocket = guard.originalWebSocket;
        window.removeEventListener('subtitle-cloud-config-required', prompt);
        updateMeetingActionButtons();
      }
    })()`);
    assert.equal(retryChecks.readFailure.prompts, 0);
    assert.equal(retryChecks.readFailure.sockets, 0);
    assert.equal(retryChecks.readFailure.captionsKept, true);
    assert.equal(retryChecks.readFailure.session || retryChecks.readFailure.audio, false);
    assert.ok(retryChecks.readFailure.hint.includes('读取'));
    checks.push('A temporary configuration read failure preserves captions and never requests API credentials or audio');
    assert.equal(retryChecks.savedMismatch.prompts, 0);
    assert.equal(retryChecks.savedMismatch.sockets, 0);
    assert.equal(retryChecks.savedMismatch.captionsKept, true);
    assert.ok(retryChecks.savedMismatch.hint.includes('已保存') && retryChecks.savedMismatch.hint.includes('无需重新填写'));
    checks.push('Saved native credentials with an unconfigured service show a reopen hint without requesting the key again');
    assert.equal(retryChecks.pending.prompts, 0);
    assert.equal(retryChecks.pending.sockets, 0);
    assert.equal(retryChecks.pending.captionsKept, true);
    assert.equal(retryChecks.recovered.prompts, 0);
    assert.equal(retryChecks.recovered.sockets, 1);
    assert.equal(retryChecks.recovered.requests, 3);
    assert.equal(retryChecks.recovered.configured, true);
    assert.equal(retryChecks.recovered.pending || retryChecks.recovered.audio, false);
    checks.push('Delayed config and double Start clicks recover to one simulated socket without repeated API prompts');
    window.setBounds({ ...window.getBounds(), width: 420, height: 240 });
    await waitFrame();
    assert.ok(await evaluate(`document.getElementById('subtitleStack').getBoundingClientRect().height > 40`));
    checks.push('Minimum-size caption window has positive usable space');

    // Keep the primary screenshots above limited to the single example caption.
    // This separate phase exercises actual overflowing history and native input.
    window.setBounds({ ...window.getBounds(), width: 650, height: 340 });
    await evaluate(`(() => {
      for (let index = 0; index < 24; index++) {
        renderSubtitle({ sequenceId: 'desktop-history-' + index,
          sourceText: 'History ' + (index + 1) + ': review earlier captions with a wheel or keyboard.',
          translatedText: '历史字幕 ' + (index + 1) + '：隐藏滚动条后，仍可使用滚轮和键盘查看之前的内容。',
          start: index * 5, end: index * 5 + 4, isFinal: true });
      }
    })()`);
    await waitFrame();
    const scrollStyle = await evaluate(`(() => {
      const stream = document.getElementById('subtitleStack');
      const style = getComputedStyle(stream);
      const scrollbar = getComputedStyle(stream, '::-webkit-scrollbar');
      return { tabIndex: stream.tabIndex, overflowY: style.overflowY,
        scrollbarWidth: style.scrollbarWidth, scrollbarGutter: style.scrollbarGutter,
        webkitScrollbarHidden: scrollbar.display === 'none' || scrollbar.width === '0px',
        scrollHeight: stream.scrollHeight, clientHeight: stream.clientHeight };
    })()`);
    assert.equal(scrollStyle.tabIndex, 0);
    assert.equal(scrollStyle.overflowY, 'auto');
    assert.equal(scrollStyle.scrollbarWidth, 'none');
    assert.equal(scrollStyle.scrollbarGutter, 'auto');
    assert.equal(scrollStyle.webkitScrollbarHidden, true);
    assert.ok(scrollStyle.scrollHeight > scrollStyle.clientHeight * 3);
    checks.push('History is focusable and scrollable without a native scrollbar or reserved gutter');

    const wheelTarget = await evaluate(`(() => {
      const stream = document.getElementById('subtitleStack');
      stream.scrollTop = (stream.scrollHeight - stream.clientHeight) / 2;
      const bounds = stream.getBoundingClientRect();
      return { x: Math.round(bounds.left + bounds.width / 2),
        y: Math.round(bounds.top + bounds.height / 2), top: stream.scrollTop,
        height: bounds.height, innerHeight, target: document.elementFromPoint(
          bounds.left + bounds.width / 2, bounds.top + bounds.height / 2)?.outerHTML.slice(0, 120) };
    })()`);
    window.focus();
    window.webContents.focus();
    window.webContents.sendInputEvent({ type: 'mouseMove', x: wheelTarget.x, y: wheelTarget.y });
    window.webContents.sendInputEvent({ type: 'mouseDown', x: wheelTarget.x, y: wheelTarget.y, button: 'left', clickCount: 1 });
    window.webContents.sendInputEvent({ type: 'mouseUp', x: wheelTarget.x, y: wheelTarget.y, button: 'left', clickCount: 1 });
    await waitFrame();
    window.webContents.sendInputEvent({ type: 'mouseWheel', x: wheelTarget.x, y: wheelTarget.y,
      deltaX: 0, deltaY: -180, canScroll: true, hasPreciseScrollingDeltas: true });
    await waitFrame();
    const afterWheel = await evaluate(`document.getElementById('subtitleStack').scrollTop`);
    if (Math.abs(afterWheel - wheelTarget.top) <= 1) {
      fs.writeFileSync(path.join(outputDir, 'wheel-diagnostic.png'), (await window.webContents.capturePage()).toPNG());
    }
    assert.ok(Math.abs(afterWheel - wheelTarget.top) > 1,
      'A native mouse wheel must move the history scroll position: ' + JSON.stringify({ ...wheelTarget, afterWheel }));
    checks.push('Native mouse wheel reviews history with hidden scrollbars');

    const beforePageUp = await evaluate(`(() => {
      const stream = document.getElementById('subtitleStack');
      stream.scrollTop = stream.scrollHeight;
      stream.focus({ preventScroll: true });
      return stream.scrollTop;
    })()`);
    assert.equal(await evaluate(`document.activeElement.id`), 'subtitleStack');
    window.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'PageUp' });
    window.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'PageUp' });
    await waitFrame();
    assert.ok(await evaluate(`document.getElementById('subtitleStack').scrollTop`) < beforePageUp - 1,
      'PageUp must review history in the focused caption stream');
    const reviewing = await evaluate(`(() => {
      const stream = document.getElementById('subtitleStack');
      return { top: stream.scrollTop, gap: stream.scrollHeight - stream.scrollTop - stream.clientHeight };
    })()`);
    assert.ok(reviewing.gap > 40);
    await evaluate(`renderSubtitle({ sequenceId: 'desktop-history-arrival',
      sourceText: 'An incoming caption must let you continue reviewing earlier history.',
      translatedText: '新字幕到达时，正在向上查看历史的窗口应继续保留历史阅读状态。',
      start: 125, end: 129, isFinal: true })`);
    await waitFrame();
    const afterArrival = await evaluate(`(() => {
      const stream = document.getElementById('subtitleStack');
      return { top: stream.scrollTop, gap: stream.scrollHeight - stream.scrollTop - stream.clientHeight };
    })()`);
    assert.ok(afterArrival.gap > 40 && afterArrival.top <= reviewing.top + 2,
      'A new caption must not jump a reader from earlier history to the live bottom');
    checks.push('Incoming captions do not jump history readers to the live bottom');
    window.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'End' });
    window.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'End' });
    await waitFrame();
    assert.ok(await evaluate(`(() => {
      const stream = document.getElementById('subtitleStack');
      return stream.scrollHeight - stream.scrollTop - stream.clientHeight < 2;
    })()`), 'End must return to the latest caption');
    checks.push('Native PageUp and End keys review history and return to live captions');
    const beforeFollowing = await evaluate(`document.getElementById('subtitleStack').scrollHeight`);
    await evaluate(`renderSubtitle({ sequenceId: 'desktop-history-follow',
      sourceText: 'LongUnbrokenCaptionToken'.repeat(12),
      translatedText: '返回最新字幕后，新到达的字幕应继续自动跟随，较长的原文和译文也应在窗口内自然换行。',
      start: 130, end: 134, isFinal: true })`);
    await waitFrame();
    const following = await evaluate(`(() => {
      const stream = document.getElementById('subtitleStack');
      return { height: stream.scrollHeight, gap: stream.scrollHeight - stream.scrollTop - stream.clientHeight,
        horizontalOverflow: stream.scrollWidth > stream.clientWidth + 1 ||
          document.body.scrollWidth > document.body.clientWidth + 1 ||
          document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 };
    })()`);
    assert.ok(following.height > beforeFollowing && following.gap < 2,
      'After End returns to live captions, a new caption must remain followed');
    assert.equal(following.horizontalOverflow, false, 'Long caption text must wrap without horizontal overflow');
    checks.push('Latest captions keep following after End, and long text wraps without horizontal overflow');
    fs.writeFileSync(path.join(outputDir, 'history-scroll.png'), (await window.webContents.capturePage()).toPNG());

    window.setBounds({ ...window.getBounds(), width: 420, height: 240 });
    await waitFrame();
    for (const compact of [false, true]) {
      await evaluate(`(() => {
        if (document.body.classList.contains('desktop-settings-open')) document.getElementById('desktopSettings').click();
        if (document.body.classList.contains('caption-only') !== ${compact}) document.getElementById('desktopView').click();
        document.getElementById('desktopSettings').click();
      })()`);
      await waitFrame();
      const toolbarLayout = await evaluate(`(() => {
        const header = document.querySelector('.desktop-titlebar').getBoundingClientRect();
        return [...document.querySelectorAll('.desktop-titlebar nav button')].map((button) => {
          const bounds = button.getBoundingClientRect();
          const icon = button.querySelector('svg').getBoundingClientRect();
          return { id: button.id, withinWindow: bounds.width > 0 && bounds.height > 0 &&
            bounds.left >= 0 && bounds.right <= innerWidth + 1 && bounds.top >= 0 && bounds.bottom <= innerHeight + 1,
            withinTitlebar: bounds.left >= header.left && bounds.right <= header.right + 1 &&
              bounds.top >= header.top && bounds.bottom <= header.bottom + 1,
            iconWithinButton: icon.left >= bounds.left - 1 && icon.right <= bounds.right + 1 &&
              icon.top >= bounds.top - 1 && icon.bottom <= bounds.bottom + 1,
            hitTarget: button.contains(document.elementFromPoint(bounds.left + bounds.width / 2, bounds.top + bounds.height / 2)) };
        });
      })()`);
      for (const button of toolbarLayout) {
        assert.equal(button.withinWindow && button.withinTitlebar && button.iconWithinButton && button.hitTarget, true,
          `${button.id} must remain unclipped and clickable in the minimum-size toolbar`);
      }
      const settingsLayout = await evaluate(`(() => {
        const panel = document.querySelector('.caption-settings');
        const bounds = panel.getBoundingClientRect();
        const control = document.getElementById('translationFontSize');
        control.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        const field = control.getBoundingClientRect();
        return { expanded: document.getElementById('desktopSettings').getAttribute('aria-expanded'),
          visible: getComputedStyle(panel).display !== 'none',
          withinWindow: bounds.left >= 0 && bounds.top >= 0 && bounds.right <= innerWidth + 1 && bounds.bottom <= innerHeight + 1,
          height: bounds.height,
          fontControlReachable: document.elementFromPoint(field.left + field.width / 2, field.top + field.height / 2) === control };
      })()`);
      assert.equal(settingsLayout.expanded, 'true');
      assert.equal(settingsLayout.visible, true);
      assert.equal(settingsLayout.withinWindow, true);
      assert.ok(settingsLayout.height > 40);
      assert.equal(settingsLayout.fontControlReachable, true,
        'The font size input must remain reachable in minimum-size settings');
      checks.push(`SET is accessible in minimum-size ${compact ? 'caption' : 'full'} view`);
      for (const id of ['sourceFontColor', 'translationFontColor', 'sourceFontColorHex', 'translationFontColorHex',
        'toggleSourceText', 'toggleTranslationText']) {
        assert.ok(await evaluate(`(() => {
          const control = document.getElementById(${JSON.stringify(id)});
          control.scrollIntoView({ block: 'nearest', inline: 'nearest' });
          const bounds = control.getBoundingClientRect();
          const panel = document.querySelector('.caption-settings').getBoundingClientRect();
          return bounds.left >= panel.left && bounds.right <= panel.right + 1 &&
            bounds.top >= panel.top && bounds.bottom <= panel.bottom + 1 &&
            control.contains(document.elementFromPoint(bounds.left + bounds.width / 2, bounds.top + bounds.height / 2));
        })()`), `${id} must remain reachable in minimum-size color settings`);
      }
      checks.push(`Color and visibility controls remain accessible in minimum-size ${compact ? 'caption' : 'full'} view`);
      await evaluate(`(() => {
        for (const id of ['toggleSourceText', 'toggleTranslationText']) {
          if (document.getElementById(id).getAttribute('aria-pressed') === 'true') document.getElementById(id).click();
        }
      })()`);
      const hiddenLayout = await evaluate(`(() => {
        const hint = document.getElementById('captionVisibilityNotice');
        const pane = document.getElementById('subtitleStack').closest('.subtitle-box');
        const h = hint.getBoundingClientRect(), p = pane.getBoundingClientRect();
        return { hintShown: !hint.hidden, paneHeight: p.height,
          overlaps: h.top >= p.top && h.bottom <= p.bottom + 1,
          insideWindow: h.top >= 0 && h.bottom <= innerHeight + 1 };
      })()`);
      assert.equal(hiddenLayout.hintShown, true);
      assert.ok(hiddenLayout.paneHeight > 0 && hiddenLayout.overlaps && hiddenLayout.insideWindow,
        'Both-hidden notice must overlay the caption pane without creating a second narrow-window grid row');
      checks.push(`Both-hidden notice stays inside the caption pane in minimum-size ${compact ? 'caption' : 'full'} view`);
      await evaluate(`(() => {
        document.getElementById('toggleSourceText').click();
        document.getElementById('toggleTranslationText').click();
      })()`);
      fs.writeFileSync(path.join(outputDir, compact ? 'minimum-caption-settings.png' : 'minimum-full-settings.png'),
        (await window.webContents.capturePage()).toPNG());

      await evaluate(`(async () => {
        const form = document.querySelector('.desktop-cloud-form');
        if (form.hidden) document.getElementById('desktopCloudSettings').click();
        await window.subtitleDesktop.getCloudConfig();
      })()`);
      await waitFrame();
      assert.equal(await evaluate(`document.querySelector('.desktop-cloud-form').hidden`), false);
      assert.equal(await evaluate(`document.getElementById('desktopCloudRegion').value`), config.region);
      assert.ok(await evaluate(`(() => {
        const text = document.getElementById('desktopCloudStatus').textContent;
        return text.includes('密钥已保存') || text.includes('首次使用');
      })()`), 'Cloud configuration must finish loading before checking its controls');
      for (const selector of ['#desktopCloudRegion', '.desktop-cloud-form button[type="submit"]']) {
        const cloudControl = await evaluate(`(() => {
          const control = document.querySelector(${JSON.stringify(selector)});
          control.scrollIntoView({ block: 'nearest', inline: 'nearest' });
          const bounds = control.getBoundingClientRect();
          const panel = document.querySelector('.caption-settings').getBoundingClientRect();
          return { withinPanel: bounds.width > 0 && bounds.height > 0 && bounds.left >= panel.left &&
              bounds.right <= panel.right + 1 && bounds.top >= panel.top && bounds.bottom <= panel.bottom + 1,
            hitTarget: control.contains(document.elementFromPoint(bounds.left + bounds.width / 2, bounds.top + bounds.height / 2)),
            enabled: !control.disabled };
        })()`);
        assert.equal(cloudControl.withinPanel && cloudControl.hitTarget && cloudControl.enabled, true,
          `${selector} must remain reachable in minimum-size cloud settings`);
      }
      assert.ok(await evaluate(`(() => {
        const panel = document.querySelector('.caption-settings');
        const stream = document.getElementById('subtitleStack');
        return panel.scrollWidth <= panel.clientWidth + 1 && stream.scrollWidth <= stream.clientWidth + 1 &&
          document.body.scrollWidth <= document.body.clientWidth + 1;
      })()`), 'Minimum-size settings and captions must not overflow horizontally');
      checks.push(`Minimum-size ${compact ? 'caption' : 'full'} toolbar and cloud region/save controls are reachable`);
      fs.writeFileSync(path.join(outputDir, compact ? 'minimum-caption-cloud-settings.png' : 'minimum-full-cloud-settings.png'),
        (await window.webContents.capturePage()).toPNG());
      // Never submit the configuration form or change its saved values.
      await evaluate(`document.getElementById('desktopCloudSettings').click()`);

      if (compact) {
        const oldErrorStatus = await evaluate(`(() => {
          const status = document.querySelector('.desktop-status');
          const previous = { hidden: status.hidden, text: status.textContent };
          status.textContent = 'Smoke test: captions disconnected. Please retry.';
          status.hidden = false;
          return previous;
        })()`);
        await waitFrame();
        const errorLayout = await evaluate(`(() => {
          const header = document.querySelector('.desktop-titlebar').getBoundingClientRect();
          const panel = document.querySelector('.caption-settings').getBoundingClientRect();
          return { headerBottom: header.bottom, panelTop: panel.top,
            panelBottom: panel.bottom, viewportHeight: innerHeight };
        })()`);
        assert.ok(errorLayout.panelTop >= errorLayout.headerBottom,
          'Visible errors must not let the taller titlebar overlap settings');
        assert.ok(errorLayout.panelBottom <= errorLayout.viewportHeight + 1,
          'Settings must stay inside the minimum-size window when an error is visible');
        checks.push('Minimum-size settings remain below the titlebar when an error makes it taller');
        fs.writeFileSync(path.join(outputDir, 'minimum-error-settings.png'), (await window.webContents.capturePage()).toPNG());
        await evaluate(`(() => {
          const status = document.querySelector('.desktop-status');
          status.textContent = ${JSON.stringify(oldErrorStatus.text)};
          status.hidden = ${oldErrorStatus.hidden};
        })()`);
        await waitFrame();
      }
      await evaluate(`document.getElementById('desktopSettings').click()`);
      assert.equal(await evaluate(`document.getElementById('desktopSettings').getAttribute('aria-expanded')`), 'false');
    }
    // These values are the contract consumed by the full-process restore run.
    assert.equal(await evaluate(`document.getElementById('translationFontSize').value`), '48');
    assert.equal(await evaluate(`document.getElementById('sourceFontSize').value`), '22');
    assert.equal(await evaluate(`document.getElementById('sourceFontColor').value`), '#345f93');
    assert.equal(await evaluate(`document.getElementById('translationFontColor').value`), '#7b3f69');
    assert.equal(await evaluate(`document.getElementById('desktopOpacity').value`), '55');
    assert.equal(await evaluate(`document.body.classList.contains('caption-only')`), true);
    assert.equal(window.getBounds().width, 420);
    assert.equal(window.getBounds().height, 240);
    await evaluate(`(() => {
      if (document.getElementById('toggleSourceText').getAttribute('aria-pressed') === 'true') document.getElementById('toggleSourceText').click();
      if (document.getElementById('toggleTranslationText').getAttribute('aria-pressed') !== 'true') document.getElementById('toggleTranslationText').click();
    })()`);
    await waitFrame();
    fs.writeFileSync(path.join(outputDir, 'result.json'), JSON.stringify({ ok: true, checks, baseURL }, null, 2));
  } catch (error) {
    try { fs.writeFileSync(path.join(outputDir, 'failure.png'), (await window.webContents.capturePage()).toPNG()); } catch { /* Preserve the original failure. */ }
    fs.writeFileSync(path.join(outputDir, 'result.json'), JSON.stringify({ ok: false, checks, error: String(error.stack) }, null, 2));
    throw error;
  }
}

module.exports = { runSmoke };
