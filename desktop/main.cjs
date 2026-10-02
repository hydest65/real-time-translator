'use strict';
const { app, BrowserWindow, dialog, ipcMain, screen, shell } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const { MIN_WIDTH, MIN_HEIGHT, EDGES, resizeBounds, visibleBounds } = require('./geometry.cjs');
const { parseCloudConfig, cloudEnvironment, cloudConfigMigration, updateCloudConfigText } = require('./cloud-config.cjs');

app.setName('Subtitle Studio');
app.setPath('userData', app.commandLine.hasSwitch('smoke-test-dir') ?
  path.resolve(app.commandLine.getSwitchValue('smoke-test-dir'), 'profile') :
  path.join(app.getPath('appData'), 'Subtitle Studio'));
let window;
let worker;
let baseURL;
let resizeTimer;
let saveTimer;
let quitting = false;
let shutdownComplete = false;
let preferences = {};
let configFile;
const projectRoot = path.resolve(__dirname, '..');
const packaged = fs.existsSync(path.join(process.resourcesPath, 'backend', 'subtitle-backend.exe'));
const dataDir = () => app.getPath('userData');
const stateFile = () => path.join(dataDir(), 'window.json');
const displayFile = () => path.join(dataDir(), 'display.json');
let displayPreferences = {};

function recoverSavedCloudConfig(envFile) {
  // A process launched by the MSIX Codex app may write to its redirected
  // Roaming folder. Explorer launches use the real Roaming folder instead.
  // Recover only this application's saved settings, preserving valid settings.
  if (!packaged || process.env.SUBTITLE_STUDIO_ENV_FILE || app.commandLine.hasSwitch('smoke-test-dir')) return;
  const currentText = fs.readFileSync(envFile, 'utf8');
  const current = parseCloudConfig(currentText);
  if (current.AZURE_SPEECH_KEY && current.AZURE_SPEECH_REGION) return;
  const legacyFile = path.join(path.dirname(app.getPath('appData')), 'Local', 'Packages',
    'OpenAI.Codex_2p2nqsd0c76g0', 'LocalCache', 'Roaming', 'Subtitle Studio', '.env');
  if (!fs.existsSync(legacyFile)) return;
  const recovered = cloudConfigMigration(currentText, fs.readFileSync(legacyFile, 'utf8'));
  if (!recovered) return;
  const pendingFile = `${envFile}.migration-${process.pid}`;
  try {
    fs.writeFileSync(pendingFile, updateCloudConfigText(currentText, recovered));
    fs.renameSync(pendingFile, envFile);
  } finally {
    if (fs.existsSync(pendingFile)) fs.unlinkSync(pendingFile);
  }
}

function saveState() {
  if (!window || window.isDestroyed()) return;
  preferences = { bounds: window.getBounds(), alwaysOnTop: window.isAlwaysOnTop() };
  fs.writeFileSync(stateFile(), JSON.stringify(preferences, null, 2));
}

function stopResize() { clearInterval(resizeTimer); resizeTimer = null; }

function trusted(event) {
  return window && !window.isDestroyed() && event.sender === window.webContents &&
    event.senderFrame === window.webContents.mainFrame && event.senderFrame.url === `${baseURL}/`;
}

function handle(channel, action) {
  ipcMain.handle(channel, (event, ...args) => {
    if (!trusted(event)) throw new Error('Untrusted desktop request');
    return action(...args);
  });
}

function availablePort() {
  return new Promise((resolve, reject) => {
    const listener = net.createServer();
    listener.once('error', reject);
    listener.listen(0, '127.0.0.1', () => {
      const port = listener.address().port;
      listener.close(() => resolve(port));
    });
  });
}

async function startBackend() {
  const port = await availablePort();
  baseURL = `http://127.0.0.1:${port}`;
  const executable = packaged ? path.join(process.resourcesPath, 'backend', 'subtitle-backend.exe') :
    path.join(projectRoot, '.venv', 'Scripts', 'python.exe');
  if (!fs.existsSync(executable)) throw new Error('未找到应用运行组件，请重新解压完整应用包。');
  const envFile = path.resolve(process.env.SUBTITLE_STUDIO_ENV_FILE ||
    (packaged ? path.join(dataDir(), '.env') : path.join(projectRoot, '.env')));
  configFile = envFile;
  if (!fs.existsSync(envFile)) {
    fs.writeFileSync(envFile, '# 云翻译配置：填入自己的 Azure Speech 密钥和区域，再重新启动应用。\nAZURE_SPEECH_KEY=\nAZURE_SPEECH_REGION=\n');
  }
  recoverSavedCloudConfig(envFile);
  const args = packaged ? [] : [path.join(__dirname, 'backend_worker.py')];
  args.push('--port', String(port), '--data-dir', dataDir(), '--env-file', envFile, '--managed');
  const logFile = fs.openSync(path.join(dataDir(), 'service-launch.log'), 'a');
  const workerEnv = cloudEnvironment(process.env, fs.readFileSync(envFile, 'utf8'));
  worker = spawn(executable, args, { cwd: packaged ? dataDir() : projectRoot,
    windowsHide: true, stdio: ['pipe', logFile, logFile],
    env: { ...workerEnv, SUBTITLE_STUDIO_ENV_FILE: envFile, SUBTITLE_STUDIO_DATA_DIR: dataDir(),
      PYTHONPATH: packaged ? '' : projectRoot, PYTHONUNBUFFERED: '1' } });
  fs.closeSync(logFile);
  let launchError;
  worker.once('error', (error) => { launchError = error; });
  worker.stdin.on('error', () => { /* Worker already exited; shutdown fallback handles it. */ });
  worker.once('exit', (code) => {
    if (!quitting && window && !window.isDestroyed()) {
      if (!app.commandLine.hasSwitch('smoke-test')) {
        dialog.showErrorBox('字幕服务已退出', `请重新打开应用。详情见数据目录中的 backend.log。退出码：${code}`);
      }
      app.quit();
    }
  });
  for (let attempt = 0; attempt < 150; attempt++) {
    if (launchError) throw launchError;
    if (worker.exitCode !== null) throw new Error('字幕服务启动失败，请查看 service-launch.log。');
    try {
      const response = await fetch(`${baseURL}/api/health`, { signal: AbortSignal.timeout(500) });
      if (response.ok && (await response.json()).ok === true) return;
    } catch { /* Wait for this application's own worker. */ }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error('字幕服务启动超时，请查看数据目录中的日志。');
}

async function createWindow() {
  fs.mkdirSync(dataDir(), { recursive: true });
  try { preferences = JSON.parse(fs.readFileSync(stateFile(), 'utf8')); } catch { /* First launch. */ }
  try { displayPreferences = JSON.parse(fs.readFileSync(displayFile(), 'utf8')); } catch { /* First launch. */ }
  await startBackend();
  const display = preferences.bounds ? screen.getDisplayMatching(preferences.bounds) : screen.getPrimaryDisplay();
  window = new BrowserWindow({ ...visibleBounds(preferences.bounds, display.workArea),
    minWidth: MIN_WIDTH, minHeight: MIN_HEIGHT, frame: false, transparent: true,
    // Native resize can break Windows transparency. Our eight edge handles use setBounds.
    resizable: false, maximizable: false, backgroundColor: '#00000000', hasShadow: false,
    alwaysOnTop: preferences.alwaysOnTop !== false, show: false, title: 'Subtitle Studio',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true,
      nodeIntegration: false, sandbox: true, webSecurity: true, backgroundThrottling: false } });
  window.setMenu(null);
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event, url) => { if (url !== `${baseURL}/`) event.preventDefault(); });
  window.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  handle('desktop:state', () => ({ alwaysOnTop: window.isAlwaysOnTop(), packaged, version: app.getVersion(), display: displayPreferences }));
  handle('desktop:display-save', (values) => {
    if (!values || typeof values !== 'object') return;
    for (const [name, minimum, maximum] of [['sourceFontSize', 10, 160], ['translationFontSize', 10, 160], ['backgroundOpacity', 15, 100]]) {
      if (Number.isInteger(values[name]) && values[name] >= minimum && values[name] <= maximum) displayPreferences[name] = values[name];
    }
    for (const name of ['sourceFontColor', 'translationFontColor']) {
      if (typeof values[name] === 'string' && /^#[0-9a-f]{6}$/i.test(values[name])) {
        displayPreferences[name] = values[name].toLowerCase();
      }
    }
    for (const name of ['captionOnly', 'showSourceText', 'showTranslationText']) {
      if (typeof values[name] === 'boolean') displayPreferences[name] = values[name];
    }
    fs.writeFileSync(displayFile(), JSON.stringify(displayPreferences, null, 2));
  });
  handle('desktop:pin', (value) => { window.setAlwaysOnTop(value === true); saveState(); return window.isAlwaysOnTop(); });
  handle('desktop:minimize', () => { stopResize(); window.minimize(); });
  handle('desktop:close', () => window.close());
  handle('desktop:data-folder', () => shell.openPath(dataDir()));
  handle('desktop:cloud-config', () => {
    const values = parseCloudConfig(fs.readFileSync(configFile, 'utf8'));
    return { region: values.AZURE_SPEECH_REGION,
      configured: Boolean(values.AZURE_SPEECH_KEY && values.AZURE_SPEECH_REGION) };
  });
  handle('desktop:cloud-save', (config) => {
    if (!config || typeof config.region !== 'string' || typeof config.key !== 'string') throw new Error('配置格式无效');
    const region = config.region.trim();
    const key = config.key.trim();
    if (!/^[a-z0-9-]{2,40}$/.test(region)) throw new Error('请填写有效的云服务区域，例如 eastasia。');
    if (key && (!/^[a-zA-Z0-9_+/=-]{8,256}$/.test(key))) throw new Error('密钥格式无效。');
    const values = { AZURE_SPEECH_REGION: region };
    if (key) values.AZURE_SPEECH_KEY = key; // An empty masked field preserves the key.
    fs.writeFileSync(configFile, updateCloudConfigText(fs.readFileSync(configFile, 'utf8'), values));
    setTimeout(() => { app.relaunch(); app.quit(); }, 300);
    return true;
  });
  handle('desktop:resize-stop', stopResize);
  handle('desktop:resize-start', (edge) => {
    if (!EDGES.has(edge)) return;
    stopResize();
    const start = screen.getCursorScreenPoint();
    const bounds = window.getBounds();
    const deadline = Date.now() + 15000;
    resizeTimer = setInterval(() => {
      if (Date.now() > deadline || !window || window.isDestroyed()) return stopResize();
      const current = screen.getCursorScreenPoint();
      window.setBounds(resizeBounds(bounds, edge, current.x - start.x, current.y - start.y));
    }, 16);
  });
  window.on('blur', stopResize);
  const scheduleSave = () => { clearTimeout(saveTimer); saveTimer = setTimeout(saveState, 250); };
  window.on('move', scheduleSave);
  window.on('resize', scheduleSave);
  window.on('close', () => { stopResize(); clearTimeout(saveTimer); saveState(); });
  window.on('closed', () => { window = null; });
  await window.loadURL(`${baseURL}/`);
  window.show();
  if (app.commandLine.hasSwitch('smoke-test')) {
    const { runSmoke } = require('./smoke.cjs');
    await runSmoke(window, path.resolve(app.commandLine.getSwitchValue('smoke-test-dir')), baseURL,
      app.commandLine.hasSwitch('smoke-restore'));
    app.quit();
  }
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (window) { window.restore(); window.show(); window.focus(); } });
  app.whenReady().then(createWindow).catch((error) => {
    if (app.commandLine.hasSwitch('smoke-test')) {
      const outputDir = path.resolve(app.commandLine.getSwitchValue('smoke-test-dir'));
      fs.mkdirSync(outputDir, { recursive: true });
      const resultPath = path.join(outputDir, 'result.json');
      if (!fs.existsSync(resultPath)) fs.writeFileSync(resultPath, JSON.stringify({ ok: false, error: String(error.stack) }, null, 2));
    } else dialog.showErrorBox('无法启动 Subtitle Studio', String(error.message));
    app.quit();
  });
}
app.on('before-quit', (event) => {
  stopResize();
  if (shutdownComplete || !worker || worker.exitCode !== null) { quitting = true; return; }
  event.preventDefault();
  if (quitting) return;
  quitting = true;
  // Let ASR/WebSocket cleanup finalize WAV headers before stopping our service.
  const timeout = setTimeout(() => { worker.kill(); shutdownComplete = true; app.quit(); }, 6000);
  worker.once('exit', () => { clearTimeout(timeout); shutdownComplete = true; app.quit(); });
  worker.stdin.end('shutdown\n');
});
app.on('window-all-closed', () => app.quit());
