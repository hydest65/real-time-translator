const backendStatus = document.querySelector("#backendStatus");
const liveCloudStatus = document.querySelector("#liveCloudStatus");
const recordingStatus = document.querySelector("#recordingStatus");
const configList = document.querySelector("#configList");
const recordingList = document.querySelector("#recordingList");
const testLog = document.querySelector("#testLog");
const refreshButton = document.querySelector("#refreshButton");
const socketTestButton = document.querySelector("#socketTestButton");

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

  configList.append(
    configRow("Live captions", yesNo(liveCloudReady), statusClass(liveCloudReady)),
  );

  setTextStatus(liveCloudStatus, liveCloudReady ? "Ready" : "Missing", statusClass(liveCloudReady));
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
    const [health, recordings] = await Promise.all([
      loadJson("/api/health"),
      loadJson("/api/recordings"),
    ]);
    setTextStatus(backendStatus, health.ok ? "Ready" : "Problem", statusClass(health.ok));
    renderConfig(health.config || {});
    renderRecordings(recordings.recordings || []);
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


refreshButton.addEventListener("click", refreshAll);
socketTestButton.addEventListener("click", testLiveSocket);

refreshAll();
window.setInterval(refreshAll, 15000);
