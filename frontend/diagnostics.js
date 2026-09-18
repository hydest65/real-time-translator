const backendStatus = document.querySelector("#backendStatus");
const liveCloudStatus = document.querySelector("#liveCloudStatus");
const cloudNotesStatus = document.querySelector("#cloudNotesStatus");
const localNotesStatus = document.querySelector("#localNotesStatus");
const recordingStatus = document.querySelector("#recordingStatus");
const latestMinutesStatus = document.querySelector("#latestMinutesStatus");
const configList = document.querySelector("#configList");
const progressStage = document.querySelector("#progressStage");
const progressPercent = document.querySelector("#progressPercent");
const progressFill = document.querySelector("#progressFill");
const progressMessage = document.querySelector("#progressMessage");
const recordingList = document.querySelector("#recordingList");
const testLog = document.querySelector("#testLog");
const refreshButton = document.querySelector("#refreshButton");
const socketTestButton = document.querySelector("#socketTestButton");
const tingwuTestButton = document.querySelector("#tingwuTestButton");

function statusClass(ok, warning = false) {
  if (ok) {
    return "ok";
  }
  return warning ? "warn" : "bad";
}

function setTextStatus(element, text, className) {
  element.textContent = text;
  element.classList.remove("ok", "warn", "bad");
  if (className) {
    element.classList.add(className);
  }
}

function yesNo(value) {
  return value ? "Ready" : "Missing";
}

function configRow(label, value, className = "") {
  const row = document.createElement("div");
  row.className = "kv-row";
  const term = document.createElement("dt");
  term.textContent = label;
  const detail = document.createElement("dd");
  detail.textContent = String(value ?? "");
  if (className) {
    detail.classList.add(className);
  }
  row.append(term, detail);
  return row;
}

function renderConfig(config = {}) {
  configList.innerHTML = "";
  const liveCloudReady = Boolean(config.cloud_configured ?? config.azure_configured);
  const cloudNotesReady = Boolean(config.aliyun_tingwu_configured);
  const localNotesReady = Boolean(config.funasr_configured);
  const notesModel = config.post_meeting_llm_model || "Not reported";
  const uploadProvider = config.aliyun_tingwu_upload_provider || "Not reported";

  configList.append(
    configRow("Live captions", yesNo(liveCloudReady), statusClass(liveCloudReady)),
    configRow("Cloud notes", yesNo(cloudNotesReady), statusClass(cloudNotesReady)),
    configRow("Local notes", yesNo(localNotesReady), statusClass(localNotesReady, true)),
    configRow("Notes model", notesModel),
    configRow("Upload path", uploadProvider),
  );

  setTextStatus(liveCloudStatus, liveCloudReady ? "Ready" : "Missing", statusClass(liveCloudReady));
  setTextStatus(cloudNotesStatus, cloudNotesReady ? "Ready" : "Missing", statusClass(cloudNotesReady));
  setTextStatus(localNotesStatus, localNotesReady ? "Ready" : "Missing", statusClass(localNotesReady, true));
}

function renderProgress(progress = {}) {
  const percent = Number(progress.percent || 0);
  progressStage.textContent = progress.stage || (progress.running ? "Running" : "Idle");
  progressPercent.textContent = `${Math.max(0, Math.min(100, percent))}%`;
  progressFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  progressMessage.textContent = progress.message || "No meeting notes task is running.";
  progressMessage.classList.toggle("warn", Boolean(progress.running));
}

function renderLatestMinutes(payload = {}) {
  const available = Boolean(payload.available);
  setTextStatus(latestMinutesStatus, available ? "Ready" : "None", statusClass(available, true));
  if (available && payload.minutes) {
    latestMinutesStatus.title = payload.minutes;
  } else {
    latestMinutesStatus.removeAttribute("title");
  }
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value > 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  if (value > 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${value} B`;
}

function renderRecordings(recordings = []) {
  recordingList.innerHTML = "";
  if (!recordings.length) {
    recordingList.textContent = "No recordings found.";
    setTextStatus(recordingStatus, "None", "warn");
    return;
  }
  setTextStatus(recordingStatus, `${recordings.length} found`, "ok");
  recordings.slice(0, 5).forEach((recording) => {
    const item = document.createElement("div");
    item.className = "recording-item";
    const title = document.createElement("strong");
    title.textContent = recording.displayName || recording.name || "Recording";
    const meta = document.createElement("span");
    meta.textContent = `${recording.name || ""} / ${formatBytes(recording.sizeBytes)} / ${recording.durationSeconds || 0}s`;
    item.append(title, meta);
    recordingList.append(item);
  });
}

async function loadJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `${url} failed with ${response.status}`);
  }
  return payload;
}

async function refreshAll() {
  setTextStatus(backendStatus, "Checking", "warn");
  try {
    const [health, progress, recordings, latestMinutes] = await Promise.all([
      loadJson("/api/health"),
      loadJson("/api/process-recording-progress"),
      loadJson("/api/recordings"),
      loadJson("/api/latest-minutes"),
    ]);
    setTextStatus(backendStatus, health.ok ? "Ready" : "Problem", statusClass(health.ok));
    renderConfig(health.config || {});
    renderProgress(progress);
    renderRecordings(recordings.recordings || []);
    renderLatestMinutes(latestMinutes);
    testLog.textContent = `Refreshed ${new Date().toLocaleTimeString()}.`;
  } catch (error) {
    setTextStatus(backendStatus, "Problem", "bad");
    testLog.textContent = error.message || "Refresh failed.";
  }
}

function testLiveSocket() {
  testLog.textContent = "Testing live websocket...";
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/subtitles`);
  const timer = window.setTimeout(() => {
    socket.close();
    testLog.textContent = "Live websocket timed out.";
  }, 5000);

  socket.addEventListener("open", () => {
    window.clearTimeout(timer);
    testLog.textContent = "Live websocket opens successfully. No caption session was started.";
    socket.close();
  });

  socket.addEventListener("error", () => {
    window.clearTimeout(timer);
    testLog.textContent = "Live websocket failed. Backend may be blocked or stopped.";
  });
}

async function testCloudNotes() {
  testLog.textContent = "Checking cloud notes setup...";
  try {
    const payload = await loadJson("/api/aliyun-tingwu-diagnostics?uploadProvider=tencent-relay");
    const checks = Array.isArray(payload.checks) ? payload.checks : [];
    const failed = checks.filter((item) => !item.ok);
    testLog.textContent = failed.length
      ? `Cloud notes has ${failed.length} issue(s): ${failed.map((item) => item.name || item.message).join(", ")}`
      : "Cloud notes setup looks ready.";
  } catch (error) {
    testLog.textContent = error.message || "Cloud notes check failed.";
  }
}

refreshButton.addEventListener("click", refreshAll);
socketTestButton.addEventListener("click", testLiveSocket);
tingwuTestButton.addEventListener("click", testCloudNotes);

refreshAll();
window.setInterval(refreshAll, 15000);
