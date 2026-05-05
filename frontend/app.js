const startButton = document.querySelector("#startButton");
const stopButton = document.querySelector("#stopButton");
const statusText = document.querySelector("#statusText");
const statusDot = document.querySelector("#statusDot");
const subtitleStack = document.querySelector("#subtitleStack");
const azureSubtitleBox = document.querySelector("#azureSubtitleBox");
const monitorTitle = document.querySelector("#monitorTitle");
const monitorSubtitle = document.querySelector("#monitorSubtitle");
const monitorBadge = document.querySelector("#monitorBadge");
const audioSource = document.querySelector("#audioSource");
const modelSize = document.querySelector("#modelSize");
const deviceType = document.querySelector("#deviceType");
const chunkSeconds = document.querySelector("#chunkSeconds");
const localLatencyPreset = document.querySelector("#localLatencyPreset");
const translationEngine = document.querySelector("#translationEngine");
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
const uiThemeStorageKey = "subtitleStudioUiThemeCompact20260502";

function applySavedUiTheme() {
  let theme;
  try {
    theme = JSON.parse(localStorage.getItem(uiThemeStorageKey) || "{}");
  } catch (error) {
    theme = {};
  }

  const allowedProperties = [
    "--bg",
    "--bg-soft",
    "--bg-low",
    "--text",
    "--muted",
    "--accent",
    "--accent-strong",
    "--accent-soft",
    "--subtitle-font-size",
    "--source-font-size",
    "--panel-width",
    "--ui-radius",
    "--background-art",
  ];

  allowedProperties.forEach((property) => {
    if (theme[property]) {
      document.documentElement.style.setProperty(property, theme[property]);
    }
  });
}

function setStatus(status, detail = "") {
  statusText.textContent = status;
  logText.textContent = detail || status;
  statusDot.classList.toggle(
    "active",
    ["Connecting", "Listening", "Transcribing", "Translating", "Loading models", "Connecting cloud"].includes(status),
  );
  statusDot.classList.toggle("error", status === "Error");
}

function renderSubtitle(item) {
  const wasFollowing = isSubtitleAtBottom();
  const isLiveRow = item.isFinal === false;
  if (isLiveRow) {
    if (!item.sourceText || !item.sourceText.trim()) {
      return;
    }
    liveSubtitle = {
      ...item,
      translatedText: item.translatedText || "",
    };
  } else {
    upsertHistory(finalSubtitleHistory, item);
    if (finalSubtitleHistory.length > maxDisplayHistory) {
      finalSubtitleHistory = finalSubtitleHistory.slice(-maxDisplayHistory);
    }
    const shouldClearLiveRow =
      !liveSubtitle?.sequenceId ||
      liveSubtitle.sequenceId === item.sequenceId ||
      liveSubtitle.sequenceId === "azure-live" ||
      translationEngine.value === "azure";
    if (shouldClearLiveRow) {
      liveSubtitle = null;
    }
  }

  const displayItems = liveSubtitle
    ? [...finalSubtitleHistory, liveSubtitle]
    : finalSubtitleHistory;

  subtitleStack.innerHTML = "";
  for (const entry of displayItems) {
    const row = document.createElement("article");
    row.className = `subtitle-row ${entry.isFinal === false ? "live" : ""} ${entry.isNewTurn ? "new-turn" : ""} ${entry.isNoise ? "noise" : ""}`.trim();

    const source = document.createElement("p");
    source.className = "source";
    source.textContent = entry.sourceText;

    const translation = document.createElement("p");
    translation.className = "translation";
    translation.textContent = entry.translatedText || "Translating...";

    const timestamp = document.createElement("div");
    timestamp.className = "timestamp";
    const state = entry.isFinal === false ? " - live" : "";
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

function upsertHistory(history, item) {
  const existingIndex = history.findIndex(
    (entry) => entry.sequenceId && entry.sequenceId === item.sequenceId,
  );
  if (existingIndex >= 0) {
    history[existingIndex] = {
      ...history[existingIndex],
      ...item,
    };
  } else {
    history.push(item);
  }
}

function isSubtitleAtBottom() {
  return isAtBottom(subtitleStack);
}

function isAtBottom(target) {
  return target.scrollHeight - target.scrollTop - target.clientHeight < scrollBottomTolerance;
}

function formatTimestamp(value) {
  const totalSeconds = Math.max(0, Math.floor(Number(value) || 0));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
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
    ? "Azure mode: streaming live subtitles."
    : "Local mode: Azure-style live subtitle monitor.";
  azureSubtitleBox.classList.remove("hidden");
  if (monitorTitle) {
    monitorTitle.textContent = "Subtitle Monitor";
  }
  if (monitorSubtitle) {
    monitorSubtitle.textContent = isCloud
      ? "Azure live history - scroll to review"
      : "Local draft and final history - scroll to review";
  }
  if (monitorBadge) {
    monitorBadge.textContent = isCloud ? "LIVE" : "LOCAL";
  }
  if (!isCloud) {
    applyLocalLatencyPreset();
  }
}

function applyLocalLatencyPreset() {
  if (!localLatencyPreset) {
    return;
  }
  if (localLatencyPreset.value === "low") {
    chunkSeconds.value = "1.5";
  } else {
    chunkSeconds.value = "2";
  }
}

function effectiveLocalChunkSeconds(isLowLatencyLocal) {
  const selectedChunk = Number(chunkSeconds.value);
  if (!isLowLatencyLocal) {
    return Math.min(selectedChunk || 2, 2);
  }
  const cappedChunk = Math.min(selectedChunk || 1.5, 1.5);
  chunkSeconds.value = String(cappedChunk);
  return cappedChunk;
}

function localRealtimeTuning() {
  const isLowLatencyLocal = localLatencyPreset?.value === "low";
  if (isLowLatencyLocal) {
    return {
      overlap_seconds: 0.25,
      queue_max_size: 1,
      segmenter_pause_seconds: 0.8,
      segmenter_max_words: 24,
      segmenter_max_seconds: 6.0,
    };
  }
  return {
    overlap_seconds: 0.3,
    queue_max_size: 1,
    segmenter_pause_seconds: 1.1,
    segmenter_max_words: 32,
    segmenter_max_seconds: 8.0,
  };
}

function updateLanguageHints() {
  const subtitle = document.querySelector("#brandSubtitle");
  if (subtitle) {
    subtitle.textContent = translationEngine.value === "azure"
      ? "English to Chinese - Azure cloud"
      : "English to Chinese - High-end local mode";
  }
  perfText.textContent = translationEngine.value === "azure"
    ? "Azure mode: streaming live subtitles."
    : `${modelSize.value} on ${deviceType.value}: optimized English ASR is available.`;
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
    const isLowLatencyLocal = !isCloud && localLatencyPreset?.value === "low";
    const effectiveChunk = effectiveLocalChunkSeconds(isLowLatencyLocal);
    const realtimeTuning = isCloud ? null : localRealtimeTuning();
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
        chunk_seconds: effectiveChunk,
        overlap_seconds: realtimeTuning?.overlap_seconds ?? 0.5,
        max_subtitles: serverSubtitleWindow,
        queue_max_size: realtimeTuning?.queue_max_size ?? 2,
        segmenter_pause_seconds: realtimeTuning?.segmenter_pause_seconds,
        segmenter_max_words: realtimeTuning?.segmenter_max_words,
        segmenter_max_seconds: realtimeTuning?.segmenter_max_seconds,
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
translationEngine.addEventListener("change", updateLanguageHints);
modelSize.addEventListener("change", updateLanguageHints);
deviceType.addEventListener("change", updateLanguageHints);
localLatencyPreset.addEventListener("change", applyLocalLatencyPreset);
subtitleStack.addEventListener("scroll", () => {
  autoFollowSubtitles = isSubtitleAtBottom();
});
applySavedUiTheme();
updateEngineControls();
updateLanguageHints();
