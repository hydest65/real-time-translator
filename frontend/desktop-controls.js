(() => {
  const desktop = window.subtitleDesktop;
  if (!desktop) return;
  let hydrating = true;
  function persistDisplay() {
    if (hydrating) return;
    desktop.saveDisplayPreferences({
      sourceFontSize: Number(document.getElementById('sourceFontSlider').value),
      translationFontSize: Number(document.getElementById('translationFontSlider').value),
      sourceFontColor: document.getElementById('sourceFontColor').value,
      translationFontColor: document.getElementById('translationFontColor').value,
      showSourceText: document.getElementById('toggleSourceText').getAttribute('aria-pressed') === 'true',
      showTranslationText: document.getElementById('toggleTranslationText').getAttribute('aria-pressed') === 'true',
      backgroundOpacity: Number(document.getElementById('desktopOpacity').value),
      captionOnly: document.body.classList.contains('caption-only'),
    }).catch(() => { /* Closing the window can end the bridge. */ });
  }
  document.documentElement.classList.add('desktop-surface');
  document.body.classList.add('desktop-app');
  const iconPaths = {
    play: '<path d="m9 5 11 7-11 7Z"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    captions: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 12h4m2 0h4M7 16h10"/>',
    layout: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18M9 9v11"/>',
    settings: '<path d="M4 7h7m4 0h5M4 17h3m4 0h9"/><circle cx="13" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    pin: '<path d="m9 3 6 0-1 6 4 4v2H6v-2l4-4Z M12 15v6"/>',
    minimize: '<path d="M5 12h14"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
    key: '<circle cx="8" cy="9" r="4"/><path d="m11 12 9 9m-5-5 3-3m0 6 3-3"/>',
    folder: '<path d="M3 8V6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    reset: '<path d="M3 10a9 9 0 1 1 2 8M3 4v6h6"/>',
    save: '<path d="M5 3h12l4 4v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2ZM7 3v6h10V3M7 21v-7h10v7"/>',
    microphone: '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-3 0h6"/>',
    chart: '<path d="M5 17v-4m7 4V8m7 9V3"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 11h18"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"/>',
    audio: '<path d="M3 14v-4a9 9 0 0 1 18 0v4M3 10h3v8H3Zm15 0h3v8h-3Z"/>',
    speech: '<path d="M21 11a8 8 0 0 1-8 8H5l-3 3V11a9 9 0 0 1 19 0Z"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    eyeOff: '<path d="m3 3 18 18M10 5a12 12 0 0 1 2 0c6 0 10 7 10 7a19 19 0 0 1-3 4M6 6a22 22 0 0 0-4 6s4 7 10 7a12 12 0 0 0 5-1M10 10a3 3 0 0 0 4 4"/>',
  };
  function iconMarkup(name) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${iconPaths[name]}</svg>`;
  }
  function paintIcon(button, name, label, abbreviation) {
    button.innerHTML = iconMarkup(name);
    button.setAttribute('aria-label', label);
    button.title = abbreviation ? `${label}（${abbreviation}）` : label;
  }
  const header = document.createElement('header');
  header.className = 'desktop-titlebar';
  header.innerHTML = `
    <span class="desktop-drag-label" title="拖动移动窗口"><span id="desktopActivityIndicator" class="desktop-brand-mark desktop-activity-indicator" role="img" aria-label="字幕未启动（IDLE）" data-state="idle" title="字幕未启动（IDLE）"><i aria-hidden="true"></i><i aria-hidden="true"></i><i aria-hidden="true"></i></span>Subtitle Studio</span>
    <nav aria-label="桌面窗口控制">
      <span class="desktop-control-group">
      <button id="desktopStart" type="button" title="开始翻译" aria-label="开始翻译">ST</button>
      <button id="desktopStop" type="button" title="停止翻译并保存录音" aria-label="停止翻译并保存录音" disabled>SP</button>
      </span><span class="desktop-control-group">
      <button id="desktopView" type="button" title="切换到字幕模式">CAP</button>
      <button id="desktopSettings" type="button" title="显示设置：字号、颜色和背景透明度" aria-label="显示设置" aria-controls="desktopDisplaySettings" aria-expanded="false">SET</button>
      <button id="desktopPin" type="button" aria-label="切换窗口置顶" aria-pressed="true" title="让字幕显示在其他窗口上方">PIN</button>
      </span><span class="desktop-control-group desktop-window-controls">
      <button id="desktopMinimize" type="button" aria-label="最小化">—</button>
      <button id="desktopClose" type="button" aria-label="关闭应用">×</button>
      </span>
    </nav>`;
  document.body.prepend(header);
  for (const [selector, name] of [
    ['.recording-panel-icon', 'microphone'], ['.usage-panel-icon', 'chart'],
    ['.usage-session', 'clock'], ['.usage-day', 'sun'], ['.usage-month', 'calendar'],
    ['.audio-icon', 'audio'], ['.speech-icon', 'speech'],
  ]) {
    const element = document.querySelector(selector);
    element.classList.add('desktop-line-icon');
    element.innerHTML = iconMarkup(name);
  }
  const usageNote = document.getElementById('azureUsageSyncText');
  function simplifyUsageNote() {
    if (/Cloud usage sync needs/i.test(usageNote.textContent)) {
      usageNote.title = usageNote.textContent;
      usageNote.textContent = '用量记录保存在本机';
    }
  }
  const usageNoteObserver = new MutationObserver(simplifyUsageNote);
  usageNoteObserver.observe(usageNote, { childList: true, characterData: true, subtree: true });
  simplifyUsageNote();
  // Error messages can make the title bar taller. Keep the settings below it.
  const headerSizeObserver = new ResizeObserver(() => {
    document.documentElement.style.setProperty('--desktop-titlebar-height', `${header.getBoundingClientRect().height}px`);
  });
  headerSizeObserver.observe(header);
  for (const [id, name, label, abbreviation] of [
    ['desktopStart', 'play', '开始翻译', 'ST'], ['desktopStop', 'stop', '停止翻译并保存录音', 'SP'],
    ['desktopSettings', 'settings', '显示设置：字号、颜色和背景透明度', 'SET'],
    ['desktopMinimize', 'minimize', '最小化'], ['desktopClose', 'close', '关闭应用'],
  ]) paintIcon(document.getElementById(id), name, label, abbreviation);
  const errorStatus = document.createElement('span');
  errorStatus.className = 'desktop-status';
  errorStatus.setAttribute('role', 'status');
  header.append(errorStatus);
  function showError() {
    const element = ['backendConnection', 'streamConnection', 'liveConnectionActivity']
      .map((id) => document.getElementById(id)).find((item) => item?.dataset.state === 'error');
    errorStatus.textContent = element?.textContent || '';
    errorStatus.hidden = !element;
  }
  const statusObserver = new MutationObserver(showError);
  for (const id of ['backendConnection', 'streamConnection', 'liveConnectionActivity']) {
    statusObserver.observe(document.getElementById(id), { attributes: true, childList: true, characterData: true, subtree: true });
  }
  showError();
  const activityIndicator = document.getElementById('desktopActivityIndicator');
  function updateActivityIndicator() {
    const server = document.getElementById('backendConnection').dataset.state;
    const captions = document.getElementById('streamConnection').dataset.state;
    const activity = document.getElementById('liveConnectionActivity').dataset.state;
    const stage = document.getElementById('statusText').textContent.trim().toLowerCase();
    const notice = document.getElementById('noticeText').textContent.trim().toLowerCase();
    const live = typeof isLiveSessionActive !== 'undefined' && isLiveSessionActive;
    const connecting = ['checking config', 'connecting', 'connecting cloud', 'loading models'].includes(stage);
    const working = ['listening', 'transcribing', 'translating', 'recording'].includes(stage) ||
      (!connecting && !['stopped', 'error'].includes(stage) && ['live', 'final'].includes(notice));
    let state = 'idle';
    let label = '字幕未启动（IDLE）';
    // A reachable server alone never proves that speech recognition is active.
    if (server === 'error' || captions === 'error' || activity === 'error' || stage === 'error') {
      state = 'error';
      label = '连接或翻译异常，请检查状态（ERR）';
    } else if (server === 'online' && captions === 'online' && live && working) {
      state = 'active';
      label = '连接正常，正在监听并翻译（LIVE）';
    } else if (connecting || captions === 'pending' || server === 'pending' || (live && captions === 'online')) {
      state = 'pending';
      label = '正在连接或准备字幕服务（CONN）';
    }
    activityIndicator.dataset.state = state;
    activityIndicator.setAttribute('aria-label', label);
    activityIndicator.title = label;
  }
  const activityObserver = new MutationObserver(updateActivityIndicator);
  for (const id of ['backendConnection', 'streamConnection', 'liveConnectionActivity', 'statusText', 'noticeText']) {
    activityObserver.observe(document.getElementById(id), {
      attributes: true, attributeFilter: ['data-state'], childList: true, characterData: true, subtree: true,
    });
  }
  updateActivityIndicator();
  const settings = document.querySelector('.caption-settings');
  settings.id = 'desktopDisplaySettings';
  settings.setAttribute('aria-labelledby', 'desktopSettingsTitle');
  const settingsHeading = document.createElement('div');
  settingsHeading.className = 'desktop-settings-heading';
  settingsHeading.innerHTML = '<h2 id="desktopSettingsTitle">显示设置</h2><button id="desktopSettingsClose" type="button" title="关闭设置" aria-label="关闭设置">×</button>';
  settings.prepend(settingsHeading);
  paintIcon(document.getElementById('desktopSettingsClose'), 'close', '关闭设置');
  const visibilityButtons = [['toggleSourceText', 'SRC'], ['toggleTranslationText', 'TR']];
  function paintVisibilityButtons() {
    for (const [id, abbreviation] of visibilityButtons) {
      const button = document.getElementById(id);
      const visible = button.getAttribute('aria-pressed') === 'true';
      button.innerHTML = `${iconMarkup(visible ? 'eye' : 'eyeOff')}<span aria-hidden="true">${abbreviation}</span>`;
    }
  }
  const visibilityObserver = new MutationObserver(paintVisibilityButtons);
  for (const [id] of visibilityButtons) {
    const button = document.getElementById(id);
    visibilityObserver.observe(button, { attributes: true, attributeFilter: ['aria-pressed'] });
    button.addEventListener('click', persistDisplay);
  }
  paintVisibilityButtons();
  settings.querySelector('label[for="sourceFontSize"]').textContent = '原文字号';
  settings.querySelector('label[for="translationFontSize"]').textContent = '译文字号';
  document.getElementById('captionSettingsStatus').textContent = '修改会自动保存';
  for (const [id, label] of [['subtitleStack', '字幕历史'], ['englishContextStack', '原文历史'], ['chineseSubtitleStack', '译文历史']]) {
    const stream = document.getElementById(id);
    stream.tabIndex = 0;
    stream.setAttribute('role', 'region');
    stream.setAttribute('aria-label', `${label}，可使用滚轮或 PageUp、PageDown、Home、End 浏览`);
  }
  const background = document.createElement('div');
  background.className = 'caption-size-control desktop-background-control';
  background.innerHTML = `<label for="desktopOpacity">背景不透明度</label>
    <input id="desktopOpacity" type="range" min="15" max="100" step="1" value="72" aria-label="背景不透明度" />
    <output id="desktopOpacityValue" for="desktopOpacity">72%</output>`;
  settings.append(background);
  const actions = document.createElement('div');
  actions.className = 'desktop-settings-actions';
  actions.innerHTML = `
    <button id="desktopCloudSettings" type="button" title="云服务设置" aria-label="云服务设置">CFG</button>
    <button id="desktopDataFolder" type="button" title="打开录音与日志目录" aria-label="打开录音与日志目录">LOG</button>`;
  actions.append(document.getElementById('resetCaptionFonts'));
  settings.append(actions, document.getElementById('captionSettingsStatus'));
  for (const [id, name, label, abbreviation] of [
    ['desktopCloudSettings', 'key', '云服务配置', 'CFG'], ['desktopDataFolder', 'folder', '打开录音与日志', 'LOG'],
    ['resetCaptionFonts', 'reset', '恢复默认字号和颜色', 'RST'], ['retryConnectionCheck', 'reset', '检查连接状态', 'CHK'],
  ]) paintIcon(document.getElementById(id), name, label, abbreviation);
  const cloudForm = document.createElement('form');
  cloudForm.className = 'desktop-cloud-form';
  cloudForm.hidden = true;
  cloudForm.innerHTML = `<label>区域 <input id="desktopCloudRegion" placeholder="eastasia" autocomplete="off" required /></label>
    <label>密钥 <input id="desktopCloudKey" type="password" placeholder="留空保留现有密钥" autocomplete="off" /></label>
    <button type="submit" title="保存云服务配置并重新启动" aria-label="保存云服务配置并重新启动">SAV</button><p id="desktopCloudStatus" role="status">密钥仅保存在这台电脑上。</p>`;
  settings.append(cloudForm);
  paintIcon(cloudForm.querySelector('button'), 'save', '保存云服务配置并重新启动', 'SAV');
  const cloudButton = document.getElementById('desktopCloudSettings');
  cloudButton.setAttribute('aria-expanded', 'false');
  async function setCloudFormOpen(open) {
    cloudForm.hidden = !open;
    cloudButton.setAttribute('aria-expanded', String(open));
    if (!cloudForm.hidden) {
      try {
        const config = await desktop.getCloudConfig();
        document.getElementById('desktopCloudRegion').value = config.region;
        document.getElementById('desktopCloudStatus').textContent = config.configured ? '密钥已保存，无需重复填写。密钥框留空会保留现有配置。' : '首次使用请填写 Azure Speech 区域和密钥，保存后会自动沿用。';
        // Scroll only the settings pane. scrollIntoView can also move the
        // transparent outer window and push its error banner off screen.
        const panelBounds = settings.getBoundingClientRect();
        const formBounds = cloudForm.getBoundingClientRect();
        if (formBounds.top < panelBounds.top + 16 || formBounds.bottom > panelBounds.bottom - 16) {
          settings.scrollTop += formBounds.top - panelBounds.top - 16;
        }
      } catch (error) {
        document.getElementById('desktopCloudStatus').textContent = error.message;
      }
    }
  }
  cloudButton.addEventListener('click', () => setCloudFormOpen(cloudForm.hidden));
  window.addEventListener('subtitle-cloud-config-required', () => {
    setSettingsOpen(true);
    setCloudFormOpen(true);
  });
  cloudForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = cloudForm.querySelector('button');
    submit.disabled = true;
    try {
      await desktop.saveCloudConfig(document.getElementById('desktopCloudRegion').value, document.getElementById('desktopCloudKey').value);
      document.getElementById('desktopCloudKey').value = '';
      document.getElementById('desktopCloudStatus').textContent = '已保存，正在重新启动…';
    } catch (error) {
      document.getElementById('desktopCloudStatus').textContent = error.message;
      submit.disabled = false;
    }
  });
  const opacity = document.getElementById('desktopOpacity');
  const opacityValue = document.getElementById('desktopOpacityValue');
  function setOpacity(value) {
    const percent = Math.min(100, Math.max(15, Number(value) || 72));
    // Only the background receives alpha. Text and controls stay fully opaque.
    document.documentElement.style.setProperty('--desktop-background-alpha', String(percent / 100));
    opacity.value = percent;
    opacityValue.textContent = `${percent}%`;
    try { localStorage.setItem('subtitleStudioDesktopOpacity', String(percent)); } catch { /* Session-only. */ }
    persistDisplay();
  }
  try { setOpacity(localStorage.getItem('subtitleStudioDesktopOpacity') || 72); } catch { setOpacity(72); }
  opacity.addEventListener('input', () => setOpacity(opacity.value));
  const start = document.getElementById('startButton');
  const stop = document.getElementById('endMeetingButton');
  const desktopStart = document.getElementById('desktopStart');
  const desktopStop = document.getElementById('desktopStop');
  const view = document.getElementById('desktopView');
  const toggleSettings = document.getElementById('desktopSettings');
  const pin = document.getElementById('desktopPin');
  desktopStart.addEventListener('click', () => start.click());
  desktopStop.addEventListener('click', () => stop.click());
  view.addEventListener('click', () => {
    document.getElementById(document.body.classList.contains('caption-only') ? 'exitCaptionView' : 'enterCaptionView').click();
  });
  function setSettingsOpen(open, focus = false) {
    document.body.classList.toggle('desktop-settings-open', open);
    toggleSettings.setAttribute('aria-expanded', String(open));
    if (open) settings.scrollTop = 0;
    if (focus) document.getElementById(open ? 'desktopSettingsClose' : 'desktopSettings').focus({ preventScroll: true });
  }
  toggleSettings.addEventListener('click', () => {
    setSettingsOpen(!document.body.classList.contains('desktop-settings-open'), true);
  });
  document.getElementById('desktopSettingsClose').addEventListener('click', () => setSettingsOpen(false, true));
  document.addEventListener('pointerdown', (event) => {
    if (!settings.contains(event.target) && !toggleSettings.contains(event.target)) setSettingsOpen(false);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && document.body.classList.contains('desktop-settings-open')) {
      event.stopImmediatePropagation();
      event.preventDefault();
      setSettingsOpen(false, true);
    }
  }, true);
  const sync = () => {
    desktopStart.disabled = start.disabled;
    desktopStop.disabled = stop.disabled;
    const compact = document.body.classList.contains('caption-only');
    paintIcon(view, compact ? 'layout' : 'captions', compact ? '返回完整界面' : '切换到字幕模式', compact ? 'UI' : 'CAP');
    if (!start.title) start.title = '开始翻译';
    updateActivityIndicator();
    persistDisplay();
  };
  const observer = new MutationObserver(sync);
  observer.observe(start, { attributes: true, attributeFilter: ['disabled'] });
  observer.observe(stop, { attributes: true, attributeFilter: ['disabled'] });
  observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  sync();
  function paintPin(enabled) {
    pin.setAttribute('aria-pressed', String(enabled));
    paintIcon(pin, 'pin', enabled ? '已置顶；点击取消置顶' : '让字幕显示在其他窗口上方', 'PIN');
  }
  // The service uses a fresh port on every launch, so origin-bound localStorage
  // alone cannot persist desktop settings across launches. Restore the native file.
  desktop.getState().then((state) => {
    paintPin(state.alwaysOnTop);
    header.querySelector('.desktop-drag-label').title = `Subtitle Studio ${state.version || ''} · 拖动移动窗口`;
    const saved = state.display || {};
    for (const [id, key] of [['toggleSourceText', 'showSourceText'], ['toggleTranslationText', 'showTranslationText']]) {
      const visible = typeof saved[key] === 'boolean' ? saved[key] : true;
      const button = document.getElementById(id);
      if (visible !== (button.getAttribute('aria-pressed') === 'true')) button.click();
    }
    for (const [id, value] of [['sourceFontSlider', saved.sourceFontSize], ['translationFontSlider', saved.translationFontSize]]) {
      if (Number.isInteger(value) && value >= 10 && value <= 160) {
        const input = document.getElementById(id);
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }
    for (const id of ['sourceFontColor', 'translationFontColor']) {
      if (typeof saved[id] === 'string' && /^#[0-9a-f]{6}$/i.test(saved[id])) {
        const input = document.getElementById(id);
        input.value = saved[id].toLowerCase();
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }
    if (Number.isInteger(saved.backgroundOpacity)) setOpacity(saved.backgroundOpacity);
    if (typeof saved.captionOnly === 'boolean' && saved.captionOnly !== document.body.classList.contains('caption-only')) {
      document.getElementById(saved.captionOnly ? 'enterCaptionView' : 'exitCaptionView').click();
    }
    hydrating = false;
    persistDisplay();
  });
  for (const id of ['sourceFontSlider', 'sourceFontSize', 'translationFontSlider', 'translationFontSize',
    'sourceFontColor', 'translationFontColor', 'sourceFontColorHex', 'translationFontColorHex']) {
    for (const event of ['input', 'change', 'blur']) document.getElementById(id).addEventListener(event, persistDisplay);
  }
  document.getElementById('resetCaptionFonts').addEventListener('click', persistDisplay);
  pin.addEventListener('click', async () => paintPin(await desktop.setAlwaysOnTop(pin.getAttribute('aria-pressed') !== 'true')));
  document.getElementById('desktopMinimize').addEventListener('click', () => desktop.minimize());
  document.getElementById('desktopClose').addEventListener('click', () => desktop.close());
  document.getElementById('desktopDataFolder').addEventListener('click', () => desktop.openDataFolder());
  for (const edge of ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']) {
    const handle = document.createElement('div');
    handle.className = `desktop-resize desktop-resize-${edge}`;
    handle.dataset.edge = edge;
    handle.title = '拖动调整字幕窗口大小';
    handle.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
      desktop.beginResize(edge);
    });
    for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) {
      handle.addEventListener(name, () => desktop.endResize());
    }
    document.body.append(handle);
  }
  document.addEventListener('pointerup', () => desktop.endResize());
  window.addEventListener('blur', () => desktop.endResize());
})();
