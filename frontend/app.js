const startButton = document.querySelector("#startButton");
const stopButton = document.querySelector("#stopButton");
const endMeetingButton = document.querySelector("#endMeetingButton");
const statusText = document.querySelector("#statusText");
const statusDot = document.querySelector("#statusDot");
const subtitleStack = document.querySelector("#subtitleStack");
const azureSubtitleBox = document.querySelector("#azureSubtitleBox");
const localSubtitleLayout = document.querySelector("#localSubtitleLayout");
const englishContextStack = document.querySelector("#englishContextStack");
const englishDraftStack = document.querySelector("#englishDraftStack");
const chineseSubtitleStack = document.querySelector("#chineseSubtitleStack");
const audioSource = document.querySelector("#audioSource");
const sourceLanguage = document.querySelector("#sourceLanguage");
const localAsrPreset = document.querySelector("#localAsrPreset");
const modelSize = document.querySelector("#modelSize");
const deviceType = document.querySelector("#deviceType");
const chunkSeconds = document.querySelector("#chunkSeconds");
const localLatencyPreset = document.querySelector("#localLatencyPreset");
const translationEngine = document.querySelector("#translationEngine");
const downloadTranscriptButton = document.querySelector("#downloadTranscriptButton");
const downloadMinutesButton = document.querySelector("#downloadMinutesButton");
const processMeetingButton = document.querySelector("#processMeetingButton");
const openMinutesButton = document.querySelector("#openMinutesButton");
const refreshRecordingsButton = document.querySelector("#refreshRecordingsButton");
const recordingList = document.querySelector("#recordingList");
const localControls = document.querySelectorAll(".local-control");
const cloudControls = document.querySelectorAll(".cloud-control");
const logText = document.querySelector("#logText");
const perfText = document.querySelector("#perfText");
const noticeText = document.querySelector("#noticeText");
const recordingStatusText = document.querySelector("#recordingStatusText");
const recordingFileText = document.querySelector("#recordingFileText");
const notesStatusText = document.querySelector("#notesStatusText");
const notesHintText = document.querySelector("#notesHintText");
const delayStatusText = document.querySelector("#delayStatusText");
const delayHintText = document.querySelector("#delayHintText");

let socket = null;
let finalSubtitleHistory = [];
let englishContextHistory = [];
let englishDraftById = new Map();
let chineseTranslationHistory = [];
let liveSubtitle = null;
let autoFollowSubtitles = true;
let autoFollowEnglishContext = true;
let sessionTranscript = [];
let transcriptById = new Map();
let currentTurnIndex = 0;
let meetingStartedAt = null;
let recordingStartedAt = null;
let recordingTimer = null;
let currentRecordingPath = "";
let azureConfigured = false;
let latestMinutesPath = "";
let isRecordingActive = false;
let isProcessingNotes = false;
let notesAbortController = null;
let notesTimeoutId = null;
let availableRecordings = [];
let selectedRecordingPaths = new Set();
let lastSubtitleReceivedAt = 0;
const maxDisplayHistory = 80;
const maxChineseFlowCharacters = 520;
const serverSubtitleWindow = 5;
const scrollBottomTolerance = 40;
const uiThemeStorageKey = "subtitleStudioUiThemeCompact20260502";

function applyDefaultInputMode() {
  audioSource.value = "system";
}

async function loadRuntimeConfig() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    azureConfigured = Boolean(payload.azure_configured);
    if (!azureConfigured && translationEngine.value === "azure") {
      noticeText.textContent = "Azure not configured";
      logText.textContent = "Azure Speech key/region are empty. Azure mode will wait for valid cloud configuration.";
      updateDelayHintFromStatus("Azure not configured", logText.textContent);
    }
    updateEngineControls();
    updateLanguageHints();
  } catch (error) {
    logText.textContent = "Could not load backend config.";
  }
}

async function refreshLatestMinutesState() {
  try {
    const response = await fetch("/api/latest-minutes");
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    latestMinutesPath = payload.minutes || "";
    updateMeetingActionButtons();
  } catch (error) {
    latestMinutesPath = "";
    updateMeetingActionButtons();
  }
}

async function refreshRecordings(preferredPath = "") {
  if (!recordingList) {
    return;
  }
  try {
    const response = await fetch("/api/recordings");
    if (!response.ok) {
      throw new Error(`Recordings list failed: ${response.status}`);
    }
    const payload = await response.json();
    availableRecordings = payload.recordings || [];
    if (preferredPath) {
      selectedRecordingPaths.add(preferredPath);
    }
    if (!selectedRecordingPaths.size && availableRecordings[0]) {
      selectedRecordingPaths.add(availableRecordings[0].path);
    }
    renderRecordingList();
  } catch (error) {
    recordingList.textContent = "Could not load recordings.";
  }
  updateMeetingActionButtons();
}

function renderRecordingList() {
  if (!recordingList) {
    return;
  }
  recordingList.innerHTML = "";
  if (!availableRecordings.length) {
    const empty = document.createElement("p");
    empty.className = "panel-line";
    empty.textContent = "No recordings yet.";
    recordingList.append(empty);
    return;
  }
  availableRecordings.forEach((recording) => {
    const label = document.createElement("label");
    label.className = "recording-option";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = recording.path;
    checkbox.checked = selectedRecordingPaths.has(recording.path);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        selectedRecordingPaths.add(recording.path);
      } else {
        selectedRecordingPaths.delete(recording.path);
      }
      updateMeetingActionButtons();
    });
    const content = document.createElement("span");
    const title = document.createElement("span");
    title.className = "recording-title";
    title.textContent = recording.displayName || recordingFileName(recording.path || recording.name);
    const meta = document.createElement("div");
    meta.className = "recording-meta";
    meta.textContent = `${formatDuration((recording.durationSeconds || 0) * 1000)} · ${formatBytes(recording.sizeBytes || 0)}`;
    meta.textContent = `${formatDuration((recording.durationSeconds || 0) * 1000)} | ${formatBytes(recording.sizeBytes || 0)}`;
    content.append(title, meta);
    label.append(checkbox, content);
    recordingList.append(label);
  });
}

function selectedRecordings() {
  return availableRecordings
    .filter((recording) => selectedRecordingPaths.has(recording.path))
    .map((recording) => recording.path);
}

function updateMeetingActionButtons() {
  const isMeetingLive = Boolean(socket && socket.readyState === WebSocket.OPEN);
  const hasSelectedRecordings = selectedRecordings().length > 0;
  startButton.textContent = "Start Meeting";
  startButton.classList.remove("is-danger", "is-ready");
  startButton.disabled = isProcessingNotes || isMeetingLive || isRecordingActive;
  endMeetingButton.disabled = isProcessingNotes || (!isMeetingLive && !isRecordingActive);
  openMinutesButton.classList.toggle("hidden", !latestMinutesPath && !isProcessingNotes);

  if (isProcessingNotes) {
    processMeetingButton.textContent = "Cancel";
    openMinutesButton.textContent = "Creating Notes...";
    openMinutesButton.disabled = true;
    notesStatusText.textContent = "Creating";
    notesStatusText.classList.remove("muted");
    notesHintText.textContent = "Please wait. Selected recordings are being transcribed and summarized.";
  } else if (isMeetingLive || isRecordingActive) {
    processMeetingButton.textContent = "Build Notes";
    notesStatusText.textContent = "After meeting";
    notesStatusText.classList.add("muted");
    notesHintText.textContent = "End the meeting first, then choose recordings and build notes.";
  } else if (latestMinutesPath) {
    processMeetingButton.textContent = "Build Notes";
    openMinutesButton.textContent = "Open Notes";
    notesStatusText.textContent = "Ready";
    notesStatusText.classList.remove("muted");
    notesHintText.textContent = recordingFileName(latestMinutesPath);
  } else {
    processMeetingButton.textContent = "Build Notes";
    openMinutesButton.textContent = "Open Notes";
    notesStatusText.textContent = hasSelectedRecordings ? "Ready to build" : "Select recordings";
    notesStatusText.classList.add("muted");
    notesHintText.textContent = hasSelectedRecordings
      ? "Click Build Notes to create one bilingual document from selected recordings."
      : "Choose one or more recordings as the source files.";
  }

  stopButton.disabled = !isMeetingLive || isProcessingNotes;
  processMeetingButton.disabled = isRecordingActive || (!isProcessingNotes && !hasSelectedRecordings);
  openMinutesButton.disabled = isRecordingActive || isProcessingNotes || !latestMinutesPath;
}

function setDelayHint(label, detail, isWarning = false) {
  delayStatusText.textContent = label;
  delayStatusText.classList.toggle("muted", !isWarning);
  delayHintText.textContent = detail;
}

function updateDelayHintFromStatus(status, detail = "") {
  const normalized = String(status || "").toLowerCase();
  const isCloud = translationEngine.value === "azure";

  if (isProcessingNotes) {
    setDelayHint(
      "Notes running",
      "Post-meeting notes generation is using the computer. Live captions should stay paused.",
      true,
    );
    return;
  }

  if (isCloud && !azureConfigured) {
    setDelayHint(
      "Cloud not ready",
      "Azure Speech is not configured. Captions may wait until the cloud key and region are available.",
      true,
    );
    return;
  }

  if (normalized.includes("connecting cloud")) {
    setDelayHint("Cloud connection", "Waiting for Azure Speech. If this lasts, check network or Azure settings.", true);
    return;
  }

  if (normalized.includes("loading models")) {
    setDelayHint("Model loading", "Local speech or translation models are loading. The first run can be slower.", true);
    return;
  }

  if (normalized.includes("transcribing")) {
    setDelayHint("ASR busy", "The app is converting speech to English text. Delay is usually local CPU/GPU work.");
    return;
  }

  if (normalized.includes("translating")) {
    setDelayHint("Translating", "The app is translating completed English text into Chinese.");
    return;
  }

  if (normalized.includes("listening")) {
    setDelayHint("Listening", "Audio capture is active. If text is slow, check input volume or system audio source.");
    return;
  }

  if (normalized.includes("error")) {
    setDelayHint("Needs attention", detail || "An error interrupted the caption flow.", true);
    return;
  }

  setDelayHint("Ready", "No delay detected.");
}

function updateDelayHintFromSubtitle(item) {
  lastSubtitleReceivedAt = Date.now();
  const perf = item?.perf || {};
  const totalLatency = Number(perf.totalLatencyMs);
  if (Number.isFinite(totalLatency) && totalLatency > 2500) {
    setDelayHint(
      "Live but delayed",
      `Captions are arriving, but total latency is about ${Math.round(totalLatency)} ms.`,
      true,
    );
    return;
  }
  setDelayHint(
    "Live captions active",
    item?.isFinal === false
      ? "Realtime subtitles are arriving. The current line is still updating."
      : "Final subtitle received. The live path is working.",
  );
}

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
      let value = theme[property];
      if (property === "--subtitle-font-size") {
        value = clampPixelValue(value, 12, 16);
      }
      if (property === "--source-font-size") {
        value = clampPixelValue(value, 10, 12);
      }
      document.documentElement.style.setProperty(property, value);
    }
  });
}

function clampPixelValue(value, min, max) {
  const match = String(value).match(/^(\d+(?:\.\d+)?)px$/);
  if (!match) {
    return value;
  }
  return `${Math.min(max, Math.max(min, Number(match[1])))}px`;
}

function setStatus(status, detail = "") {
  statusText.textContent = status;
  logText.textContent = detail || status;
  updateDelayHintFromStatus(status, detail);
  statusDot.classList.toggle(
    "active",
    ["Connecting", "Listening", "Transcribing", "Translating", "Loading models", "Connecting cloud"].includes(status),
  );
  statusDot.classList.toggle("error", status === "Error");
  updateMeetingActionButtons();
}

function formatDuration(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${seconds}`;
  }
  return `${minutes}:${seconds}`;
}

function formatBytes(bytes) {
  if (!bytes) {
    return "0 KB";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(unitIndex ? 1 : 0)} ${units[unitIndex]}`;
}

function recordingFileName(path) {
  const fileName = String(path || "").split(/[\\/]/).pop() || "";
  const match = fileName.match(/(?:session-)?(\d{4})?(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/);
  if (match) {
    return `${match[2]}/${match[3]} ${match[4]}:${match[5]}`;
  }
  return fileName || "Recording file pending.";
}

function updateRecordingPanel(state, path = currentRecordingPath) {
  currentRecordingPath = path || currentRecordingPath;
  if (recordingTimer) {
    clearInterval(recordingTimer);
    recordingTimer = null;
  }

  if (state === "recording") {
    isRecordingActive = true;
    recordingStartedAt = recordingStartedAt || new Date();
    const render = () => {
      recordingStatusText.textContent = `ON ${formatDuration(Date.now() - recordingStartedAt.getTime())}`;
    };
    recordingStatusText.classList.remove("muted");
    recordingFileText.textContent = recordingFileName(currentRecordingPath);
    render();
    recordingTimer = setInterval(render, 1000);
    updateMeetingActionButtons();
    return;
  }

  if (state === "paused") {
    isRecordingActive = false;
    recordingStatusText.textContent = "Paused";
    recordingStatusText.classList.add("muted");
    recordingFileText.textContent = currentRecordingPath ? recordingFileName(currentRecordingPath) : "Recording paused.";
    updateMeetingActionButtons();
    return;
  }

  if (state === "ended") {
    isRecordingActive = false;
    recordingStartedAt = null;
    recordingStatusText.textContent = "Ended";
    recordingStatusText.classList.add("muted");
    recordingFileText.textContent = currentRecordingPath ? recordingFileName(currentRecordingPath) : "Meeting ended.";
    updateMeetingActionButtons();
    return;
  }

  isRecordingActive = false;
  recordingStartedAt = null;
  currentRecordingPath = "";
  recordingStatusText.textContent = "Off";
  recordingStatusText.classList.add("muted");
  recordingFileText.textContent = "No recording yet.";
  updateMeetingActionButtons();
}

function renderSubtitle(item) {
  if (translationEngine.value !== "azure") {
    renderLocalSubtitle(item);
    return;
  }

  const wasFollowing = isSubtitleAtBottom();
  const isCloudLiveRow = item.isFinal === false && item.sequenceId === "azure-live";
  if (isCloudLiveRow) {
    if (!item.sourceText || !item.sourceText.trim()) {
      return;
    }
    liveSubtitle = item;
  } else {
    recordTranscriptEntry(item, "azure");
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
    row.className = `subtitle-row ${entry.isFinal === false ? "live" : ""} ${entry.isNewTurn ? "new-turn" : ""} ${entry.isNoise ? "noise" : ""}`.trim();

    const source = document.createElement("p");
    source.className = "source";
    source.textContent = entry.sourceText;

    const translation = document.createElement("p");
    translation.className = "translation";
    translation.textContent = entry.translatedText || "翻译中...";

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

function renderLocalSubtitle(item) {
  if (item.sourceText && item.sourceText.trim()) {
    const draftId = item.sequenceId || "local-current-draft";
    if (item.isFinal === false) {
      englishDraftById.set(draftId, {
        ...(englishDraftById.get(draftId) || {}),
        ...item,
        translatedText: "",
        sequenceId: draftId,
        isFinal: false,
      });
      renderEnglishDraft();
    } else {
      recordTranscriptEntry(item, "local");
      upsertHistory(englishContextHistory, {
        ...item,
        translatedText: "",
        sequenceId: draftId,
        isFinal: true,
      });
      englishContextHistory = englishContextHistory.slice(-24);
      englishDraftById.delete(draftId);
      renderEnglishContext();
      renderEnglishDraft();
    }
  }

  if (item.isFinal !== false && item.translatedText && item.translatedText.trim()) {
    recordTranscriptEntry(item, "local");
    upsertHistory(chineseTranslationHistory, item);
    chineseTranslationHistory = chineseTranslationHistory.slice(-maxDisplayHistory);
    renderTextFlow(chineseSubtitleStack, chineseTranslationHistory, "translatedText", maxChineseFlowCharacters, "translation");
  }

  if (item.perf) {
    perfText.textContent = `Perf: audio ${item.perf.audioSeconds}s | ASR ${item.perf.asrMs}ms | translate ${item.perf.translateMs}ms | total ${item.perf.totalLatencyMs}ms | ${item.perf.engine}`;
  }
}

function renderEnglishContext() {
  const wasFollowing = isAtBottom(englishContextStack);
  renderTextFlow(englishContextStack, englishContextHistory, "sourceText", null, "context");
  if (autoFollowEnglishContext && wasFollowing) {
    englishContextStack.scrollTop = englishContextStack.scrollHeight;
  }
}

function renderEnglishDraft() {
  const drafts = Array.from(englishDraftById.values()).slice(-2);
  renderSubtitleList(englishDraftStack, drafts, "draft");
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

function renderSubtitleList(target, entries, mode) {
  target.innerHTML = "";
  for (const entry of entries) {
    const row = document.createElement("article");
    row.className = `subtitle-row ${entry.isFinal === false ? "live" : ""} ${entry.isNewTurn ? "new-turn" : ""} ${entry.isNoise ? "noise" : ""}`.trim();

    const source = document.createElement("p");
    source.className = "source";
    source.textContent = entry.sourceText;

    const translation = document.createElement("p");
    translation.className = "translation";
    translation.textContent = entry.translatedText || "";

    const timestamp = document.createElement("div");
    timestamp.className = "timestamp";
    const state = mode === "draft" ? " - draft" : "";
    timestamp.textContent = `${formatTimestamp(entry.start)} - ${formatTimestamp(entry.end)}${state}`;

    row.append(source, translation, timestamp);
    target.append(row);
  }
}

function renderTextFlow(target, entries, field, maxCharacters, mode) {
  const joinedText = entries
    .map((entry) => entry[field])
    .filter(Boolean)
    .join(" ");
  const text = typeof maxCharacters === "number"
    ? trimFlowText(joinedText, maxCharacters)
    : joinedText.replace(/\s+/g, " ").trim();

  target.innerHTML = "";
  const paragraph = document.createElement("p");
  paragraph.className = `flow-text ${mode === "translation" ? "translation-flow-text" : ""} ${mode === "context" ? "english-flow-text" : ""}`.trim();
  paragraph.textContent = text;
  target.append(paragraph);
}

function trimFlowText(text, maxCharacters) {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxCharacters) {
    return normalized;
  }
  const clipped = normalized.slice(-maxCharacters);
  const firstSentenceBreak = clipped.search(/[.!?\u3002\uff01\uff1f]\s+/);
  if (firstSentenceBreak > 0 && firstSentenceBreak < Math.floor(maxCharacters * 0.35)) {
    return clipped.slice(firstSentenceBreak + 1).trim();
  }
  return clipped.trimStart();
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
    item.classList.toggle("hidden", isCloud || item.classList.contains("internal-control"));
  });
  cloudControls.forEach((item) => {
    item.classList.toggle("hidden", !isCloud);
  });
  perfText.textContent = isCloud
    ? "Azure mode: streaming live subtitles."
    : "Local mode: English live transcript above, Chinese sentence translation below.";
  azureSubtitleBox.classList.toggle("hidden", !isCloud);
  localSubtitleLayout.classList.toggle("hidden", isCloud);
  if (!isCloud) {
    applyLocalAsrPreset();
    applyLocalLatencyPreset();
  }
}

function recordTranscriptEntry(item, mode) {
  if (item.isFinal === false || !item.sourceText?.trim()) {
    return;
  }

  if (item.isNewTurn || currentTurnIndex === 0) {
    currentTurnIndex += 1;
  }

  const id = item.sequenceId || `${mode}-${sessionTranscript.length + 1}`;
  const existingIndex = transcriptById.get(id);
  const entry = {
    id,
    mode,
    turnLabel: mode === "azure" ? `Turn ${currentTurnIndex}` : "Local",
    start: Number(item.start) || 0,
    end: Number(item.end) || 0,
    sourceText: item.sourceText.trim(),
    translatedText: (item.translatedText || "").trim(),
    isNoise: Boolean(item.isNoise),
  };

  if (existingIndex === undefined) {
    transcriptById.set(id, sessionTranscript.length);
    sessionTranscript.push(entry);
  } else {
    sessionTranscript[existingIndex] = {
      ...sessionTranscript[existingIndex],
      ...entry,
      translatedText: entry.translatedText || sessionTranscript[existingIndex].translatedText,
    };
  }
  updateExportButtons();
}

function updateExportButtons() {
  const hasTranscript = sessionTranscript.length > 0;
  downloadTranscriptButton.disabled = !hasTranscript;
  downloadMinutesButton.disabled = !hasTranscript;
}

function meetingMetadata() {
  const sourceLabel = sourceLanguage.value === "spa_Latn" ? "Spanish" : "English";
  const engineLabel = translationEngine.options[translationEngine.selectedIndex]?.textContent || translationEngine.value;
  const inputLabel = audioSource.options[audioSource.selectedIndex]?.textContent || audioSource.value;
  return {
    sourceLabel,
    engineLabel,
    inputLabel,
    startedAt: meetingStartedAt || new Date(),
    exportedAt: new Date(),
  };
}

function transcriptMarkdown() {
  const meta = meetingMetadata();
  const lines = [
    "# Meeting Transcript",
    "",
    `- Started: ${formatDateTime(meta.startedAt)}`,
    `- Exported: ${formatDateTime(meta.exportedAt)}`,
    `- Input: ${meta.inputLabel}`,
    `- Source: ${meta.sourceLabel}`,
    `- Engine: ${meta.engineLabel}`,
    "",
    "Speaker labels are pause-based turns, not verified voiceprints.",
    "",
    "## Full Transcript",
    "",
  ];

  for (const entry of sessionTranscript) {
    lines.push(`### ${entry.turnLabel} · ${formatTimestamp(entry.start)}-${formatTimestamp(entry.end)}`);
    lines.push("");
    lines.push(`Source: ${entry.sourceText}`);
    if (entry.translatedText) {
      lines.push("");
      lines.push(`中文: ${entry.translatedText}`);
    }
    lines.push("");
  }
  return lines.join("\n");
}

function minutesMarkdown() {
  const meta = meetingMetadata();
  const usableEntries = sessionTranscript.filter((entry) => !entry.isNoise && (entry.sourceText || entry.translatedText));
  const highlights = usableEntries
    .filter((entry) => (entry.translatedText || entry.sourceText).length >= 16)
    .slice(0, 10);
  const actionCandidates = usableEntries.filter((entry) =>
    /\b(need|should|must|follow up|action|todo|next|confirm|decide|owner|deadline)\b/i.test(entry.sourceText)
    || /需要|应该|必须|跟进|确认|决定|负责人|截止|下一步/.test(entry.translatedText),
  );

  const lines = [
    "# Meeting Minutes",
    "",
    `- Started: ${formatDateTime(meta.startedAt)}`,
    `- Exported: ${formatDateTime(meta.exportedAt)}`,
    `- Input: ${meta.inputLabel}`,
    `- Source: ${meta.sourceLabel}`,
    `- Engine: ${meta.engineLabel}`,
    "",
    "Speaker labels are pause-based turns, not verified voiceprints.",
    "",
    "## Summary Draft",
    "",
  ];

  if (highlights.length) {
    for (const entry of highlights) {
      lines.push(`- ${entry.translatedText || entry.sourceText}`);
    }
  } else {
    lines.push("- No final transcript text was captured yet.");
  }

  lines.push("", "## Action Candidates", "");
  if (actionCandidates.length) {
    for (const entry of actionCandidates.slice(0, 12)) {
      lines.push(`- [${entry.turnLabel} ${formatTimestamp(entry.start)}] ${entry.translatedText || entry.sourceText}`);
    }
  } else {
    lines.push("- No obvious action items detected automatically.");
  }

  lines.push("", "## Full Transcript", "");
  for (const entry of sessionTranscript) {
    lines.push(`### ${entry.turnLabel} · ${formatTimestamp(entry.start)}-${formatTimestamp(entry.end)}`);
    lines.push("");
    lines.push(`Source: ${entry.sourceText}`);
    if (entry.translatedText) {
      lines.push("");
      lines.push(`中文: ${entry.translatedText}`);
    }
    lines.push("");
  }
  return lines.join("\n");
}

function downloadMarkdown(filenamePrefix, content) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${filenamePrefix}-${timestamp}.md`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function formatDateTime(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(value);
}

function localAsrProfile() {
  const preset = localAsrPreset?.value || "balanced";
  if (preset === "fast") {
    return {
      model: "base.en",
      computeType: "int8",
      beamSize: 1,
      bestOf: 1,
      patience: 1.0,
      conditionOnPreviousText: false,
      label: "Fast ASR: base.en / int8 / beam 1",
    };
  }
  if (preset === "accurate") {
    return {
      model: "small.en",
      computeType: "int8_float16",
      beamSize: 3,
      bestOf: 3,
      patience: 1.2,
      conditionOnPreviousText: true,
      label: "Accurate ASR: small.en / int8_float16 / beam 3",
    };
  }
  return {
    model: "small.en",
    computeType: "int8",
    beamSize: 2,
    bestOf: 2,
    patience: 1.0,
    conditionOnPreviousText: false,
    label: "Balanced ASR: small.en / int8 / beam 2",
  };
}

function applyLocalAsrPreset() {
  if (!localAsrPreset || translationEngine.value === "azure") {
    return;
  }
  const profile = localAsrProfile();
  deviceType.value = "cuda";
  localLatencyPreset.value = localAsrPreset.value === "accurate" ? "steady" : "low";
  modelSize.value = profile.model;
  perfText.textContent = profile.label;
  applyLocalLatencyPreset();
}

function applyLocalLatencyPreset() {
  if (!localLatencyPreset) {
    return;
  }
  if (localLatencyPreset.value === "low") {
    chunkSeconds.value = "2";
  } else {
    chunkSeconds.value = "3";
  }
}

function effectiveLocalChunkSeconds(isLowLatencyLocal) {
  const selectedChunk = Number(chunkSeconds.value);
  if (!isLowLatencyLocal) {
    return Math.min(Math.max(selectedChunk || 3, 2), 3);
  }
  const cappedChunk = Math.min(Math.max(selectedChunk || 2, 1.5), 2);
  chunkSeconds.value = String(cappedChunk);
  return cappedChunk;
}

function localRealtimeTuning() {
  const isLowLatencyLocal = localLatencyPreset?.value === "low";
  if (isLowLatencyLocal) {
    return {
      overlap_seconds: 0.3,
      queue_max_size: 2,
      segmenter_pause_seconds: 0.9,
      segmenter_max_words: 28,
      segmenter_max_seconds: 8,
    };
  }
  return {
    overlap_seconds: 0.5,
    queue_max_size: 2,
    segmenter_pause_seconds: 1.2,
    segmenter_max_words: 36,
    segmenter_max_seconds: 12,
  };
}

function updateLanguageHints() {
  const isSpanish = sourceLanguage.value === "spa_Latn";
  const isCloud = translationEngine.value === "azure";
  const subtitle = document.querySelector("#brandSubtitle");
  if (subtitle) {
    subtitle.textContent = isSpanish
      ? "Spanish to Chinese - Local or Azure cloud"
      : "English to Chinese - Local or Azure cloud";
  }
  if (isCloud) {
    perfText.textContent = isSpanish
      ? "Azure Spanish: es-ES -> zh-Hans live translation."
      : "Azure English: en-US -> zh-Hans live translation.";
    return;
  }
  perfText.textContent = isSpanish
    ? "Local Spanish: multilingual Whisper is selected automatically."
    : "Local English: optimized English ASR is available.";
}

function start() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    return;
  }
  if (translationEngine.value === "azure" && !azureConfigured) {
    noticeText.textContent = "Azure not configured";
    logText.textContent = "Azure Speech key/region are empty. Start may fail until Azure cloud settings are available.";
    updateDelayHintFromStatus("Azure not configured", logText.textContent);
  }

  subtitleStack.innerHTML = "";
  englishContextStack.innerHTML = "";
  englishDraftStack.innerHTML = "";
  chineseSubtitleStack.innerHTML = "";
  finalSubtitleHistory = [];
  englishContextHistory = [];
  englishDraftById = new Map();
  chineseTranslationHistory = [];
  sessionTranscript = [];
  transcriptById = new Map();
  currentTurnIndex = 0;
  meetingStartedAt = new Date();
  recordingStartedAt = null;
  currentRecordingPath = "";
  latestMinutesPath = "";
  isRecordingActive = true;
  liveSubtitle = null;
  autoFollowSubtitles = true;
  updateRecordingPanel("off");
  updateExportButtons();
  updateMeetingActionButtons();
  perfText.textContent = "Perf: waiting for first subtitle.";
  setStatus("Connecting");

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${window.location.host}/ws/subtitles`);

  socket.addEventListener("open", () => {
    startButton.disabled = false;
    stopButton.disabled = false;
    const isCloud = translationEngine.value === "azure";
    const isLowLatencyLocal = !isCloud && localLatencyPreset?.value === "low";
    const effectiveChunk = effectiveLocalChunkSeconds(isLowLatencyLocal);
    const realtimeTuning = isCloud ? null : localRealtimeTuning();
    const asrProfile = isCloud ? null : localAsrProfile();
    setStatus(
      isCloud ? "Connecting cloud" : "Loading models",
      isCloud ? "Connecting to Azure Speech Translation." : "Preparing low-latency local pipeline.",
    );
    updateMeetingActionButtons();
    socket.send(JSON.stringify({
      action: "start",
      config: {
        asr_model_size: modelSize.value,
        asr_device: deviceType.value,
        asr_compute_type: asrProfile?.computeType ?? "int8",
        asr_beam_size: asrProfile?.beamSize ?? 3,
        asr_best_of: asrProfile?.bestOf ?? 3,
        asr_patience: asrProfile?.patience ?? 1.2,
        asr_condition_on_previous_text: asrProfile?.conditionOnPreviousText ?? true,
        audio_source: audioSource.value,
        source_language: sourceLanguage.value,
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
      if (payload.detail) {
        logText.textContent = payload.detail;
      }
      if ((payload.label || "").toLowerCase() === "recording") {
        updateRecordingPanel("recording", payload.detail || "");
      }
      if (Date.now() - lastSubtitleReceivedAt > 5000) {
        updateDelayHintFromStatus(payload.label || "Notice", payload.detail || "");
      }
      return;
    }
    if (payload.type === "subtitle") {
      noticeText.textContent = payload.isFinal === false ? "Live" : "Final";
      updateDelayHintFromSubtitle(payload);
      renderSubtitle(payload);
    }
  });

  socket.addEventListener("close", () => {
    stopButton.disabled = true;
    if (!statusDot.classList.contains("error")) {
      setStatus("Stopped");
    }
    if (currentRecordingPath) {
      updateRecordingPanel("paused");
    }
    updateMeetingActionButtons();
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
  if (currentRecordingPath) {
    updateRecordingPanel("paused");
  }
}

async function endMeeting() {
  stop();
  try {
    const response = await fetch("/api/end-meeting", { method: "POST" });
    if (!response.ok) {
      throw new Error(`End meeting failed: ${response.status}`);
    }
    noticeText.textContent = "Meeting ended";
    const payload = await response.json().catch(() => ({}));
    const endedRecording = payload.endedRecording || currentRecordingPath;
    if (endedRecording) {
      currentRecordingPath = endedRecording;
      selectedRecordingPaths.add(endedRecording);
    }
    logText.textContent = "Recording session closed. Choose recordings and click Build Notes when ready.";
    updateRecordingPanel("ended");
    setStatus("Stopped", "Meeting ended. Notes can be built later from selected recordings.");
    await refreshRecordings(endedRecording);
  } catch (error) {
    setStatus("Error", error.message || "Could not end meeting.");
  }
}

async function processMeetingRecording() {
  if (isProcessingNotes) {
    await cancelMeetingNotes();
    return;
  }
  if (isRecordingActive) {
    return;
  }
  isProcessingNotes = true;
  latestMinutesPath = "";
  notesAbortController = new AbortController();
  notesTimeoutId = window.setTimeout(() => {
    cancelMeetingNotes("Meeting notes timed out. Try a shorter recording.");
  }, 8 * 60 * 1000);
  updateMeetingActionButtons();
  noticeText.textContent = "Processing meeting notes";
  const recordings = selectedRecordings();
  logText.textContent = `Building notes from ${recordings.length} selected recording(s). You can cancel this if it takes too long.`;
  updateDelayHintFromStatus("Creating notes", logText.textContent);
  try {
    const response = await fetch("/api/process-recording", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recordings }),
      signal: notesAbortController.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || "Post-meeting processing failed.");
    }

    const minutesPreview = (payload.minutesText || "").slice(0, 1600).trim();
    latestMinutesPath = payload.minutes || "";
    noticeText.textContent = "Meeting notes ready";
    logText.textContent = [
      "Post-meeting files generated.",
      `ASR engine: ${payload.asrEngine || "auto"}`,
      `Recording: ${payload.recording}`,
      `Transcript: ${payload.transcript}`,
      `Minutes: ${payload.minutes}`,
      "",
      minutesPreview || payload.log || "No preview text returned.",
    ].join("\n");
    setStatus("Stopped", "Meeting notes ready.");
  } catch (error) {
    if (error.name === "AbortError") {
      noticeText.textContent = "Meeting notes cancelled";
      setStatus("Stopped", "Meeting notes generation was cancelled.");
      logText.textContent = "Post-meeting notes generation was cancelled. Choose recordings and build again when ready.";
    } else {
      noticeText.textContent = "Meeting notes failed";
      setStatus("Error", error.message || "Post-meeting processing failed.");
      logText.textContent = error.message || "Post-meeting processing failed.";
    }
  } finally {
    if (notesTimeoutId) {
      window.clearTimeout(notesTimeoutId);
      notesTimeoutId = null;
    }
    notesAbortController = null;
    isProcessingNotes = false;
    updateMeetingActionButtons();
  }
}

async function cancelMeetingNotes(message = "Meeting notes generation was cancelled.") {
  try {
    await fetch("/api/cancel-process-recording", { method: "POST" });
  } catch (error) {
    // The local abort below still releases the UI.
  }
  if (notesAbortController) {
    notesAbortController.abort();
  }
  noticeText.textContent = "Meeting notes cancelled";
  logText.textContent = message;
}

async function openLatestMinutes() {
  if (isRecordingActive || isProcessingNotes || !latestMinutesPath) {
    return;
  }
  openMinutesButton.disabled = true;
  try {
    const response = await fetch("/api/latest-minutes");
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.available) {
      throw new Error(payload.detail || "No meeting notes file found.");
    }
    latestMinutesPath = payload.minutes || latestMinutesPath;
    window.open("/api/latest-minutes-file", "_blank", "noopener");
    noticeText.textContent = "Meeting notes opened";
    logText.textContent = `Opened: ${latestMinutesPath}`;
  } catch (error) {
    noticeText.textContent = "Open notes failed";
    logText.textContent = error.message || "Could not open meeting notes.";
  } finally {
    updateMeetingActionButtons();
  }
}

function handlePrimaryMeetingAction() {
  start();
}

startButton.addEventListener("click", handlePrimaryMeetingAction);
stopButton.addEventListener("click", stop);
endMeetingButton.addEventListener("click", endMeeting);
processMeetingButton.addEventListener("click", processMeetingRecording);
openMinutesButton.addEventListener("click", openLatestMinutes);
refreshRecordingsButton?.addEventListener("click", () => refreshRecordings(currentRecordingPath));
downloadTranscriptButton.addEventListener("click", () => {
  downloadMarkdown("meeting-transcript", transcriptMarkdown());
});
downloadMinutesButton.addEventListener("click", () => {
  downloadMarkdown("meeting-minutes", minutesMarkdown());
});
translationEngine.addEventListener("change", updateEngineControls);
translationEngine.addEventListener("change", updateLanguageHints);
localAsrPreset.addEventListener("change", applyLocalAsrPreset);
localLatencyPreset.addEventListener("change", applyLocalLatencyPreset);
sourceLanguage.addEventListener("change", updateLanguageHints);
subtitleStack.addEventListener("scroll", () => {
  autoFollowSubtitles = isSubtitleAtBottom();
});
englishContextStack.addEventListener("scroll", () => {
  autoFollowEnglishContext = isAtBottom(englishContextStack);
});
applySavedUiTheme();
applyDefaultInputMode();
updateExportButtons();
updateEngineControls();
updateLanguageHints();
loadRuntimeConfig();
refreshLatestMinutesState();
refreshRecordings();
