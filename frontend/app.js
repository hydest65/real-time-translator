const startButton = document.querySelector("#startButton");
const stopButton = document.querySelector("#stopButton");
const statusText = document.querySelector("#statusText");
const statusDot = document.querySelector("#statusDot");
const subtitleWorkspace = document.querySelector("#subtitleWorkspace");
const englishSubtitleStack = document.querySelector("#englishSubtitleStack");
const chineseSubtitleStack = document.querySelector("#chineseSubtitleStack");
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
let englishSubtitleHistory = [];
let chineseSubtitleHistory = [];
let liveEnglishSubtitle = null;
let autoFollowEnglish = true;
let autoFollowChinese = true;
const maxEnglishCharacters = 1800;
const maxChineseCharacters = 1600;
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
  const wasFollowingEnglish = isAtBottom(englishSubtitleStack);
  const wasFollowingChinese = isAtBottom(chineseSubtitleStack);
  const isLiveRow = item.isFinal === false;
  if (isLiveRow) {
    if (!item.sourceText || !item.sourceText.trim()) {
      return;
    }
    liveEnglishSubtitle = {
      ...item,
      translatedText: item.translatedText || "",
    };
  } else {
    upsertHistory(englishSubtitleHistory, {
      ...item,
      translatedText: "",
    });
    englishSubtitleHistory = trimHistoryByCharacters(
      englishSubtitleHistory,
      "sourceText",
      maxEnglishCharacters,
    );
    if (item.translatedText && item.translatedText.trim()) {
      upsertHistory(chineseSubtitleHistory, item);
      chineseSubtitleHistory = trimHistoryByCharacters(
        chineseSubtitleHistory,
        "translatedText",
        maxChineseCharacters,
      );
    }
    const shouldClearLiveRow =
      !liveEnglishSubtitle?.sequenceId ||
      liveEnglishSubtitle.sequenceId === item.sequenceId ||
      liveEnglishSubtitle.sequenceId === "azure-live" ||
      translationEngine.value === "azure";
    if (shouldClearLiveRow) {
      liveEnglishSubtitle = null;
    }
  }

  const englishItems = liveEnglishSubtitle
    ? [...englishSubtitleHistory, liveEnglishSubtitle]
    : englishSubtitleHistory;

  renderTextFlow(englishSubtitleStack, englishItems, "sourceText", maxEnglishCharacters, {
    className: "english-flow-text",
    liveText: liveEnglishSubtitle?.sourceText,
  });
  renderTextFlow(chineseSubtitleStack, chineseSubtitleHistory, "translatedText", maxChineseCharacters, {
    className: "chinese-flow-text",
  });

  if (autoFollowEnglish && wasFollowingEnglish) {
    englishSubtitleStack.scrollTop = englishSubtitleStack.scrollHeight;
  }
  if (autoFollowChinese && wasFollowingChinese) {
    chineseSubtitleStack.scrollTop = chineseSubtitleStack.scrollHeight;
  }

  if (item.perf) {
    perfText.textContent = `Perf: audio ${item.perf.audioSeconds}s | ASR ${item.perf.asrMs}ms | translate ${item.perf.translateMs}ms | total ${item.perf.totalLatencyMs}ms | ${item.perf.engine}`;
  }
}

function renderTextFlow(target, entries, field, maxCharacters, options = {}) {
  const text = trimFlowText(
    entries
      .map((entry) => entry[field])
      .filter(Boolean)
      .join(" "),
    maxCharacters,
  );

  target.innerHTML = "";
  const paragraph = document.createElement("p");
  paragraph.className = `subtitle-flow-text ${options.className || ""}`.trim();
  paragraph.textContent = text || "Waiting for speech...";
  if (options.liveText) {
    paragraph.dataset.live = "true";
  }
  target.append(paragraph);
}

function trimFlowText(text, maxCharacters) {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized || normalized.length <= maxCharacters) {
    return normalized;
  }
  const clipped = normalized.slice(-maxCharacters);
  const firstBreak = clipped.search(/[.!?\u3002\uff01\uff1f]\s+/);
  if (firstBreak > 0 && firstBreak < Math.floor(maxCharacters * 0.25)) {
    return clipped.slice(firstBreak + 1).trim();
  }
  return clipped.trimStart();
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

function trimHistoryByCharacters(history, field, maxCharacters) {
  let total = 0;
  const kept = [];
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const entry = history[index];
    total += (entry[field] || "").length + 1;
    kept.unshift(entry);
    if (total >= maxCharacters) {
      break;
    }
  }
  return kept;
}

function isAtBottom(target) {
  return target.scrollHeight - target.scrollTop - target.clientHeight < scrollBottomTolerance;
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
    : "Local mode: English live above, Chinese polished below.";
  subtitleWorkspace.classList.remove("hidden");
  if (monitorTitle) {
    monitorTitle.textContent = isCloud ? "English Cloud Transcript" : "English Live Transcript";
  }
  if (monitorSubtitle) {
    monitorSubtitle.textContent = isCloud
      ? "Azure source text above - translated Chinese below"
      : "Continuous ASR above - current sentence updates live";
  }
  if (monitorBadge) {
    monitorBadge.textContent = isCloud ? "CLOUD" : "EN";
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

  englishSubtitleStack.innerHTML = "";
  chineseSubtitleStack.innerHTML = "";
  englishSubtitleHistory = [];
  chineseSubtitleHistory = [];
  liveEnglishSubtitle = null;
  autoFollowEnglish = true;
  autoFollowChinese = true;
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
englishSubtitleStack.addEventListener("scroll", () => {
  autoFollowEnglish = isAtBottom(englishSubtitleStack);
});
chineseSubtitleStack.addEventListener("scroll", () => {
  autoFollowChinese = isAtBottom(chineseSubtitleStack);
});
applySavedUiTheme();
updateEngineControls();
updateLanguageHints();
