const startButton = document.querySelector("#startButton");
const stopButton = document.querySelector("#stopButton");
const statusText = document.querySelector("#statusText");
const statusDot = document.querySelector("#statusDot");
const subtitleStack = document.querySelector("#subtitleStack");
const audioSource = document.querySelector("#audioSource");
const modelSize = document.querySelector("#modelSize");
const deviceType = document.querySelector("#deviceType");
const chunkSeconds = document.querySelector("#chunkSeconds");
const latencyMode = document.querySelector("#latencyMode");
const translationEngine = document.querySelector("#translationEngine");
const translationQuality = document.querySelector("#translationQuality");
const localControls = document.querySelectorAll(".local-control");
const cloudControls = document.querySelectorAll(".cloud-control");
const logText = document.querySelector("#logText");
const perfText = document.querySelector("#perfText");
const noticeText = document.querySelector("#noticeText");

let socket = null;
let finalSubtitleHistory = [];
let liveSubtitle = null;
let autoFollowSubtitles = true;
const maxDisplayHistory = 80;
const serverSubtitleWindow = 5;
const scrollBottomTolerance = 40;

function setStatus(status, detail = "") {
  statusText.textContent = status;
  logText.textContent = detail || status;
  statusDot.classList.toggle(
    "active",
    ["Listening", "Transcribing", "Translating", "Loading models", "Connecting cloud"].includes(status),
  );
  statusDot.classList.toggle("error", status === "Error");
}

function renderSubtitle(item) {
  const wasFollowing = isSubtitleAtBottom();
  item.lengthClass = classifySubtitleLength(item);
  if (item.isFinal === false) {
    if (!item.sourceText || !item.sourceText.trim()) {
      return;
    }
    liveSubtitle = item;
  } else {
    const existingIndex = finalSubtitleHistory.findIndex(
      (entry) => entry.sequenceId && entry.sequenceId === item.sequenceId,
    );
    if (existingIndex >= 0) {
      finalSubtitleHistory[existingIndex] = {
        ...finalSubtitleHistory[existingIndex],
        ...item,
      };
    } else {
      finalSubtitleHistory.push(item);
    }
    finalSubtitleHistory = finalSubtitleHistory.slice(-maxDisplayHistory);
    liveSubtitle = null;
  }

  const displayItems = liveSubtitle
    ? [...finalSubtitleHistory, liveSubtitle]
    : finalSubtitleHistory;

  subtitleStack.innerHTML = "";
  for (const entry of displayItems) {
    const row = document.createElement("article");
    row.className = `subtitle-row ${entry.isFinal === false ? "live" : ""} ${entry.isNewTurn ? "new-turn" : ""} ${entry.isNoise ? "noise" : ""} ${entry.lengthClass || ""}`.trim();

    const source = document.createElement("p");
    source.className = "source";
    source.textContent = entry.sourceText;

    const translation = document.createElement("p");
    translation.className = "translation";
    translation.textContent = entry.translatedText || (entry.isPolishing ? "Polishing..." : "...");

    const timestamp = document.createElement("div");
    timestamp.className = "timestamp";
    const state = entry.isFinal === false
      ? " - live"
      : entry.isPolished
        ? " - polished"
        : entry.isFallback
          ? " - fallback"
          : "";
    timestamp.textContent = `${formatTimestamp(entry.start)} - ${formatTimestamp(entry.end)}${state}`;

    row.append(source, translation, timestamp);
    subtitleStack.append(row);
  }
  if (autoFollowSubtitles && wasFollowing) {
    subtitleStack.scrollTop = subtitleStack.scrollHeight;
  }

  if (item.perf) {
    perfText.textContent = `Perf: audio ${item.perf.audioSeconds}s | ASR ${item.perf.asrMs}ms | translate ${item.perf.translateMs}ms | total ${item.perf.totalLatencyMs}ms | ${item.perf.engine}`;
  }
}

function isSubtitleAtBottom() {
  return subtitleStack.scrollHeight - subtitleStack.scrollTop - subtitleStack.clientHeight < scrollBottomTolerance;
}

function formatTimestamp(value) {
  const totalSeconds = Math.max(0, Math.floor(Number(value) || 0));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function classifySubtitleLength(item) {
  const length = `${item.sourceText || ""} ${item.translatedText || ""}`.length;
  if (length > 420) {
    return "very-long";
  }
  if (length > 240) {
    return "long";
  }
  return "";
}

function updateEngineControls() {
  const isCloud = translationEngine.value === "azure";
  localControls.forEach((item) => {
    item.classList.toggle("hidden", isCloud);
  });
  cloudControls.forEach((item) => {
    item.classList.toggle("hidden", !isCloud);
  });
  perfText.textContent = isCloud
    ? "Azure mode: streaming live subtitles; Balanced can polish final lines."
    : "Local mode: waiting for first subtitle.";
}

function start() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    return;
  }

  subtitleStack.innerHTML = "";
  finalSubtitleHistory = [];
  liveSubtitle = null;
  autoFollowSubtitles = true;
  perfText.textContent = "Perf: waiting for first subtitle.";
  setStatus("Connecting");

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${window.location.host}/ws/subtitles`);

  socket.addEventListener("open", () => {
    startButton.disabled = true;
    stopButton.disabled = false;
    const isCloud = translationEngine.value === "azure";
    setStatus(
      isCloud ? "Connecting cloud" : "Loading models",
      isCloud ? "Connecting to Azure Speech Translation." : "Preparing low-latency local pipeline.",
    );
    socket.send(JSON.stringify({
      action: "start",
      config: {
        asr_model_size: modelSize.value,
        asr_device: deviceType.value,
        asr_compute_type: "int8",
        audio_source: audioSource.value,
        source_language: "eng_Latn",
        target_language: "zho_Hans",
        translation_engine: translationEngine.value,
        translation_quality: translationQuality.value,
        latency_mode: latencyMode.value,
        chunk_seconds: Number(chunkSeconds.value),
        overlap_seconds: 0.5,
        max_subtitles: serverSubtitleWindow,
        queue_max_size: 2,
        buffer_max_wait_seconds: 4,
        buffer_min_words: 8,
        buffer_max_words: 18,
      },
    }));
  });

  socket.addEventListener("message", (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (error) {
      setStatus("Error", "Received invalid server message");
      return;
    }
    if (payload.type === "status") {
      setStatus(payload.status, payload.detail);
      return;
    }
    if (payload.type === "notice") {
      noticeText.textContent = payload.label || "Notice";
      noticeText.title = payload.detail || "";
      return;
    }
    if (payload.type === "subtitle") {
      noticeText.textContent = payload.isFinal === false ? "Live" : "Final";
      renderSubtitle(payload);
    }
  });

  socket.addEventListener("close", () => {
    startButton.disabled = false;
    stopButton.disabled = true;
    if (!statusDot.classList.contains("error")) {
      setStatus("Stopped");
    }
  });

  socket.addEventListener("error", () => {
    setStatus("Error", "WebSocket failed. Check that the backend server is still running.");
  });
}

function stop() {
  if (!socket) {
    return;
  }
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ action: "stop" }));
  }
  socket.close();
  socket = null;
}

startButton.addEventListener("click", start);
stopButton.addEventListener("click", stop);
translationEngine.addEventListener("change", updateEngineControls);
subtitleStack.addEventListener("scroll", () => {
  autoFollowSubtitles = isSubtitleAtBottom();
});
updateEngineControls();
