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
const checkCloudNotesButton = document.querySelector("#checkCloudNotesButton");
const refreshRecordingsButton = document.querySelector("#refreshRecordingsButton");
const openRecordingsFolderButton = document.querySelector("#openRecordingsFolderButton");
const openNotesFolderButton = document.querySelector("#openNotesFolderButton");
const notesUtilityToggle = document.querySelector("#notesUtilityToggle");
const settingsUtilityToggle = document.querySelector("#settingsUtilityToggle");
const notesUtilityBody = document.querySelector("#notesUtilityBody");
const settingsUtilityBody = document.querySelector("#settingsUtilityBody");
const notesEngine = document.querySelector("#notesEngine");
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
const notesProgress = document.querySelector("#notesProgress");
const notesProgressStage = document.querySelector("#notesProgressStage");
const notesProgressPercent = document.querySelector("#notesProgressPercent");
const notesProgressFill = document.querySelector("#notesProgressFill");
const notesProgressDetail = document.querySelector("#notesProgressDetail");
const delayStatusText = document.querySelector("#delayStatusText");
const delayHintText = document.querySelector("#delayHintText");
const azureUsageStatusText = document.querySelector("#azureUsageStatusText");
const azureUsageSessionText = document.querySelector("#azureUsageSessionText");
const azureUsageTodayText = document.querySelector("#azureUsageTodayText");
const azureUsageMonthText = document.querySelector("#azureUsageMonthText");
const azureUsageDayLabel = document.querySelector("#azureUsageDayLabel");
const azureUsageMonthLabel = document.querySelector("#azureUsageMonthLabel");
const azureUsageSyncText = document.querySelector("#azureUsageSyncText");

let socket = null;
let finalSubtitleHistory = [];
let englishContextHistory = [];
let englishDraftById = new Map();
let englishLiveBuffer = [];
let englishDraftLineStartWord = 0;
let englishDraftLineEndWord = 0;
let englishDraftLastWordCount = 0;
let englishDraftActiveId = "";
let englishDraftActiveItem = null;
let englishDraftPendingAdvance = false;
let englishDraftTapeWords = [];
let englishDraftTapeTextsById = new Map();
let englishContextRenderedText = "";
let englishContextTypeTimer = null;
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
let azureBatchConfigured = false;
let aliyunTingwuConfigured = false;
let aliyunTingwuEnabled = false;
let aliyunTingwuMissing = [];
let aliyunTingwuUploadProvider = "oss";
let funasrConfigured = false;
let postMeetingAsrRequested = "azure-batch";
let postMeetingAsrEffective = "faster-whisper";
let latestMinutesPath = "";
let isRecordingActive = false;
let isLiveSessionActive = false;
let isProcessingNotes = false;
let notesAbortController = null;
let notesTimeoutId = null;
let notesProgressTimer = null;
let availableRecordings = [];
let selectedRecordingPaths = new Set();
let lastSubtitleReceivedAt = 0;
let azureUsageStartedAt = null;
let azureUsageTimer = null;
let azureUsageCloud = null;
let azureUsageSyncTimer = null;
const maxDisplayHistory = 80;
const maxChineseFlowCharacters = 520;
const localDraftPromoteWordCount = 26;
const localDraftTailWordCount = 16;
const englishContextTypeChunk = 3;
const englishContextTypeDelayMs = 28;
const serverSubtitleWindow = 5;
const scrollBottomTolerance = 40;
const uiThemeStorageKey = "subtitleStudioUiThemeCompact20260502";
const azureUsageStorageKey = "subtitleStudioAzureUsageEstimate20260525";

function providerNeutralText(value = "") {
  return String(value || "")
    .replace(/azure\.cognitiveservices\.speech/gi, "cloud speech SDK")
    .replace(/login\.microsoftonline\.com/gi, "cloud auth endpoint")
    .replace(/management\.azure\.com/gi, "cloud usage endpoint")
    .replace(/cognitive\.microsoft\.com/gi, "cloud speech endpoint")
    .replace(/Microsoft Cognitive Services/gi, "cloud speech service")
    .replace(/AZURE_[A-Z0-9_]+/g, "cloud setting")
    .replace(/Azure Monitor/gi, "Cloud usage")
    .replace(/Azure Speech Translation/gi, "cloud speech translation")
    .replace(/Azure Speech/gi, "cloud speech")
    .replace(/Azure Batch Transcription/gi, "cloud batch transcription")
    .replace(/Azure Batch/gi, "cloud transcription")
    .replace(/Azure Blob/gi, "cloud storage")
    .replace(/Azure Cloud/gi, "Cloud")
    .replace(/\bAzure\b/gi, "Cloud");
}

function cloudCheckStatusText(item) {
  if (item?.ok) {
    return "OK";
  }
  const message = String(item?.message || "");
  if (/UserDisable|overdue|security reasons|not currently available/i.test(message)) {
    return "Blocked";
  }
  return "Missing";
}

function applyDefaultInputMode() {
  audioSource.value = "system";
  translationEngine.value = "azure";
}

async function loadRuntimeConfig() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    azureConfigured = Boolean(payload.cloud_configured ?? payload.azure_configured);
    azureBatchConfigured = Boolean(payload.cloud_batch_configured ?? payload.azure_batch_configured);
    aliyunTingwuConfigured = Boolean(payload.aliyun_tingwu_configured);
    aliyunTingwuEnabled = Boolean(payload.aliyun_tingwu_enabled);
    aliyunTingwuMissing = Array.isArray(payload.aliyun_tingwu_missing) ? payload.aliyun_tingwu_missing : [];
    aliyunTingwuUploadProvider = payload.aliyun_tingwu_upload_provider || "oss";
    funasrConfigured = Boolean(payload.funasr_configured);
    postMeetingAsrRequested = payload.post_meeting_asr_requested || "cloud-batch";
    postMeetingAsrEffective = payload.post_meeting_asr_effective || "faster-whisper";
    updateMeetingActionButtons();
    renderAzureUsage();
    if (!azureConfigured && translationEngine.value === "azure") {
      noticeText.textContent = "Cloud not configured";
      logText.textContent = "Cloud speech is not configured. Cloud mode will wait for valid cloud configuration.";
      updateDelayHintFromStatus("Cloud not configured", logText.textContent);
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

function setUtilityPanel(toggle, body, open) {
  if (!toggle || !body) {
    return;
  }
  body.classList.toggle("hidden", !open);
  toggle.classList.toggle("is-open", open);
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
}

function toggleUtilityPanel(target) {
  const openingNotes = target === "notes" && notesUtilityBody?.classList.contains("hidden");
  const openingSettings = target === "settings" && settingsUtilityBody?.classList.contains("hidden");
  setUtilityPanel(notesUtilityToggle, notesUtilityBody, openingNotes);
  setUtilityPanel(settingsUtilityToggle, settingsUtilityBody, openingSettings);
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
  startButton.innerHTML = '<span class="button-glyph start-glyph"></span><span>Start</span>';
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
      ? notesBuildHint()
      : "Choose one or more recordings as the source files.";
  }

  stopButton.disabled = !isMeetingLive || isProcessingNotes;
  processMeetingButton.disabled = isRecordingActive || (!isProcessingNotes && (!hasSelectedRecordings || !notesEngineReady()));
  openMinutesButton.disabled = isRecordingActive || isProcessingNotes || !latestMinutesPath;
  if (checkCloudNotesButton) {
    checkCloudNotesButton.disabled = isRecordingActive || isProcessingNotes || notesEngine?.value !== "aliyun-tingwu";
  }
}

function notesEngineReady() {
  if (!notesEngine) {
    return true;
  }
  if (notesEngine.value === "aliyun-tingwu") {
    return aliyunTingwuConfigured;
  }
  if (notesEngine.value === "azure-fast") {
    return azureConfigured;
  }
  if (notesEngine.value === "funasr") {
    return funasrConfigured;
  }
  return true;
}

function notesBuildHint() {
  if (notesEngine?.value === "aliyun-tingwu") {
    const uploadLabel = aliyunTingwuUploadProvider === "tencent-relay" ? "Tencent Relay" : "Aliyun OSS";
    if (!aliyunTingwuEnabled) {
      return "Aliyun Tingwu is selected. Enable ALIYUN_TINGWU_ENABLED in .env to use cloud meeting notes.";
    }
    if (!aliyunTingwuConfigured) {
      const missing = aliyunTingwuMissing.length ? ` Missing: ${aliyunTingwuMissing.join(", ")}.` : "";
      return `Aliyun Tingwu needs its cloud settings before notes can run. Upload path: ${uploadLabel}.${missing}`;
    }
    return `Build Notes will use Aliyun Tingwu for speaker-separated cloud transcription and meeting summary via ${uploadLabel}.`;
  }
  if (notesEngine?.value === "azure-fast") {
    if (!azureConfigured) {
      return "Cloud Speech is selected, but Azure Speech to Text is not configured yet.";
    }
    return "Build Notes will use Azure Speech to Text, then refine the transcript locally.";
  }
  if (notesEngine?.value === "funasr") {
    if (!funasrConfigured) {
      return "Local FunASR is selected, but FunASR is not installed yet.";
    }
    return "Build Notes will use local FunASR transcription, keeping recordings on this computer.";
  }
  return "Build Notes will generate English-Chinese meeting minutes from the selected recordings.";
}

function setNotesProgress(percent = 0, stage = "", message = "", visible = false) {
  if (!notesProgress || !notesProgressFill || !notesProgressPercent || !notesProgressStage) {
    return;
  }
  const normalizedPercent = Math.max(0, Math.min(100, Number(percent) || 0));
  const normalizedMessage = providerNeutralText(message);
  notesProgress.classList.toggle("hidden", !visible);
  notesProgressFill.style.width = `${normalizedPercent}%`;
  notesProgressPercent.textContent = `${Math.round(normalizedPercent)}%`;
  notesProgressStage.textContent = stage || "Preparing";
  if (notesProgressDetail) {
    notesProgressDetail.textContent = normalizedMessage || "Working on meeting notes.";
    notesProgressDetail.title = normalizedMessage || "";
  }
  notesProgress.querySelector(".notes-progress-track")?.setAttribute("aria-valuenow", String(Math.round(normalizedPercent)));
  if (message && !visible) {
    notesHintText.textContent = normalizedMessage;
  }
}

function stopNotesProgressPolling() {
  if (notesProgressTimer) {
    window.clearInterval(notesProgressTimer);
    notesProgressTimer = null;
  }
}

function startNotesProgressPolling() {
  stopNotesProgressPolling();
  setNotesProgress(2, "Queued", "Preparing selected recordings.", true);
  notesProgressTimer = window.setInterval(refreshNotesProgress, 1000);
  refreshNotesProgress();
}

async function refreshNotesProgress() {
  try {
    const response = await fetch("/api/process-recording-progress", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const progress = await response.json();
    const stage = progress.stage ? readableNotesStage(progress.stage) : "Processing";
    const current = progress.total ? ` (${progress.current || 0}/${progress.total})` : "";
    setNotesProgress(progress.percent || 0, `${stage}${current}`, progress.message || "", isProcessingNotes || progress.running);
    if (!progress.running && progress.stage === "complete") {
      setNotesProgress(100, "Complete", progress.message || "Meeting notes are ready.", true);
    }
  } catch (error) {
    // Progress is best-effort; the main request still controls success/failure.
  }
}

function setDelayHint(label, detail, isWarning = false) {
  const normalizedDetail = providerNeutralText(detail);
  delayStatusText.textContent = label;
  delayStatusText.classList.toggle("muted", !isWarning);
  delayStatusText.title = normalizedDetail || label;
  delayStatusText.setAttribute("aria-label", `${label}. ${normalizedDetail || ""}`.trim());
  delayHintText.textContent = normalizedDetail;
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
      "Cloud speech is not configured. Captions may wait until cloud settings are available.",
      true,
    );
    return;
  }

  if (normalized.includes("connecting cloud")) {
    setDelayHint("Cloud connection", "Waiting for cloud speech. If this lasts, check network or cloud settings.", true);
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
  logText.textContent = providerNeutralText(detail || status);
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

function localDateKey(date = new Date()) {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

function localMonthKey(date = new Date()) {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
  ].join("-");
}

function readAzureUsageEstimate() {
  try {
    const raw = window.localStorage.getItem(azureUsageStorageKey);
    const parsed = raw ? JSON.parse(raw) : {};
    return {
      dayKey: parsed.dayKey || localDateKey(),
      monthKey: parsed.monthKey || localMonthKey(),
      daySeconds: Number(parsed.daySeconds) || 0,
      monthSeconds: Number(parsed.monthSeconds) || 0,
    };
  } catch (error) {
    return {
      dayKey: localDateKey(),
      monthKey: localMonthKey(),
      daySeconds: 0,
      monthSeconds: 0,
    };
  }
}

function readableNotesStage(stage = "") {
  const normalized = String(stage || "").toLowerCase();
  const labels = {
    queued: "Queued",
    uploading: "Uploading",
    submitting: "Submitting",
    waiting: "Waiting",
    downloading: "Downloading",
    transcribing: "Transcribing",
    model: "Model",
    model_loading: "Model",
    model_ready: "Model Ready",
    refining: "Refining",
    writing: "Writing",
    processed: "Processed",
    combining: "Combining",
    complete: "Complete",
    failed: "Failed",
    cancelled: "Cancelled",
  };
  return labels[normalized] || normalized.replace(/_/g, " ").replace(/^\w/, (char) => char.toUpperCase());
}

function normalizedAzureUsageEstimate() {
  const usage = readAzureUsageEstimate();
  const today = localDateKey();
  const month = localMonthKey();
  if (usage.dayKey !== today) {
    usage.dayKey = today;
    usage.daySeconds = 0;
  }
  if (usage.monthKey !== month) {
    usage.monthKey = month;
    usage.monthSeconds = 0;
  }
  return usage;
}

function saveAzureUsageEstimate(usage) {
  window.localStorage.setItem(azureUsageStorageKey, JSON.stringify(usage));
}

function formatUsageMinutes(seconds) {
  if (seconds < 60) {
    return `${Math.floor(seconds)} sec`;
  }
  const minutes = seconds / 60;
  if (minutes < 90) {
    return `${Math.round(minutes)} min`;
  }
  return `${(minutes / 60).toFixed(1)} hr`;
}

function formatUsageCount(value) {
  const count = Math.round(Number(value) || 0);
  return count >= 1000 ? `${(count / 1000).toFixed(1)}k` : String(count);
}

function formatSyncTime(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function currentAzureSessionSeconds() {
  if (!azureUsageStartedAt) {
    return 0;
  }
  return Math.max(0, Math.floor((Date.now() - azureUsageStartedAt.getTime()) / 1000));
}

function setUsageIconLabel(element, label) {
  if (!element) {
    return;
  }
  element.title = label;
  element.setAttribute("aria-label", label);
}

function renderAzureUsage() {
  if (!azureUsageSessionText) {
    return;
  }
  const usage = normalizedAzureUsageEstimate();
  const sessionSeconds = currentAzureSessionSeconds();
  azureUsageSessionText.textContent = formatDuration(sessionSeconds * 1000);
  if (azureUsageCloud?.configured && azureUsageCloud?.ok && azureUsageCloud.usageMode === "calls") {
    setUsageIconLabel(azureUsageDayLabel, "Calls in last 24 hours");
    setUsageIconLabel(azureUsageMonthLabel, "Calls this month");
    azureUsageTodayText.textContent = formatUsageCount(azureUsageCloud.dayCallCount);
    azureUsageMonthText.textContent = formatUsageCount(azureUsageCloud.monthCallCount);
  } else if (azureUsageCloud?.configured && azureUsageCloud?.ok) {
    setUsageIconLabel(azureUsageDayLabel, "Cloud usage today");
    setUsageIconLabel(azureUsageMonthLabel, "Cloud usage this month");
    azureUsageTodayText.textContent = formatUsageMinutes((azureUsageCloud.daySeconds || 0) + sessionSeconds);
    azureUsageMonthText.textContent = formatUsageMinutes((azureUsageCloud.monthSeconds || 0) + sessionSeconds);
  } else {
    setUsageIconLabel(azureUsageDayLabel, "Local estimate today");
    setUsageIconLabel(azureUsageMonthLabel, "Local estimate this month");
    azureUsageTodayText.textContent = formatUsageMinutes(usage.daySeconds + sessionSeconds);
    azureUsageMonthText.textContent = formatUsageMinutes(usage.monthSeconds + sessionSeconds);
  }
  if (azureUsageStartedAt) {
    azureUsageStatusText.textContent = "Tracking";
    azureUsageStatusText.classList.remove("muted");
  } else if (azureUsageCloud?.configured && azureUsageCloud?.ok) {
    azureUsageStatusText.textContent = "Cloud Sync";
    azureUsageStatusText.classList.remove("muted");
  } else if (translationEngine.value === "azure" && azureConfigured) {
    azureUsageStatusText.textContent = "Ready";
    azureUsageStatusText.classList.remove("muted");
  } else {
    azureUsageStatusText.textContent = "Estimate";
    azureUsageStatusText.classList.add("muted");
  }
  if (azureUsageCloud?.configured && azureUsageCloud?.ok) {
    const syncedAt = formatSyncTime(azureUsageCloud.syncedAt);
    const remaining = azureUsageCloud.remainingSeconds == null
      ? ""
      : ` / ${formatUsageMinutes(azureUsageCloud.remainingSeconds)} left`;
    azureUsageSyncText.textContent = azureUsageCloud.message
      ? `${providerNeutralText(azureUsageCloud.message)}${syncedAt ? ` / ${syncedAt}` : ""}`
      : `Synced${syncedAt ? ` ${syncedAt}` : ""}${remaining}`;
  } else if (azureUsageCloud?.message) {
    azureUsageSyncText.textContent = providerNeutralText(azureUsageCloud.message);
  } else {
    azureUsageSyncText.textContent = "Local estimate";
  }
}

function startAzureUsageSession() {
  if (translationEngine.value !== "azure" || !azureConfigured || azureUsageStartedAt) {
    renderAzureUsage();
    return;
  }
  azureUsageStartedAt = new Date();
  if (azureUsageTimer) {
    clearInterval(azureUsageTimer);
  }
  azureUsageTimer = setInterval(renderAzureUsage, 1000);
  renderAzureUsage();
}

function stopAzureUsageSession() {
  if (azureUsageTimer) {
    clearInterval(azureUsageTimer);
    azureUsageTimer = null;
  }
  if (!azureUsageStartedAt) {
    renderAzureUsage();
    return;
  }
  const usage = normalizedAzureUsageEstimate();
  const sessionSeconds = currentAzureSessionSeconds();
  usage.daySeconds += sessionSeconds;
  usage.monthSeconds += sessionSeconds;
  saveAzureUsageEstimate(usage);
  azureUsageStartedAt = null;
  renderAzureUsage();
}

async function refreshAzureUsageCloud() {
  try {
    const response = await fetch("/api/cloud-usage", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Cloud usage sync failed: ${response.status}`);
    }
    azureUsageCloud = await response.json();
  } catch (error) {
    azureUsageCloud = {
      ok: false,
      configured: false,
      message: "Cloud sync unavailable. Showing local browser estimate.",
    };
  }
  renderAzureUsage();
}

function startAzureUsageCloudPolling() {
  refreshAzureUsageCloud();
  if (azureUsageSyncTimer) {
    clearInterval(azureUsageSyncTimer);
  }
  azureUsageSyncTimer = setInterval(refreshAzureUsageCloud, 60 * 1000);
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
    updateEnglishDraftTape(item, draftId);
    englishDraftActiveItem = item;
    if (item.isFinal === false) {
      if (englishDraftActiveId !== draftId) {
        englishDraftActiveId = draftId;
      }
      upsertEnglishLiveBuffer(item, draftId, false);
      englishDraftById.set(draftId, {
        ...(englishDraftById.get(draftId) || {}),
        ...item,
        sourceText: item.sourceText,
        originalSourceText: item.sourceText,
        translatedText: "",
        sequenceId: draftId,
        isFinal: false,
      });
      renderEnglishDraft();
      renderEnglishContext();
    } else {
      recordTranscriptEntry(item, "local");
      removeProvisionalContext(draftId);
      const draftIds = Array.isArray(item.draftSequenceIds) && item.draftSequenceIds.length
        ? item.draftSequenceIds
        : [draftId];
      for (const id of draftIds) {
        removeProvisionalContext(id);
        removeEnglishLiveBuffer(id);
      }
      upsertHistory(englishContextHistory, {
        ...item,
        translatedText: "",
        sequenceId: draftId,
        isFinal: true,
      });
      englishContextHistory = englishContextHistory.slice(-24);
      for (const id of draftIds) {
        englishDraftById.delete(id);
      }
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
  const draftWindow = buildEnglishDraftWindow();
  renderSubtitleList(englishDraftStack, draftWindow ? [draftWindow] : [], "draft");
}

function resetEnglishDraftPaging(activeId = englishDraftActiveId) {
  englishDraftActiveId = activeId;
  englishDraftActiveItem = null;
  englishDraftLineStartWord = 0;
  englishDraftLineEndWord = 0;
  englishDraftLastWordCount = 0;
  englishDraftPendingAdvance = false;
}

function updateEnglishDraftTape(item, draftId) {
  const text = String(item.sourceText || "").replace(/\s+/g, " ").trim();
  if (!text) {
    return;
  }
  const previous = englishDraftTapeTextsById.get(draftId) || "";
  const previousWords = previous.split(/\s+/).filter(Boolean);
  const nextWords = text.split(/\s+/).filter(Boolean);
  const commonCount = commonWordPrefixCount(previousWords, nextWords);
  const appendedWords = nextWords.slice(commonCount);
  if (appendedWords.length) {
    englishDraftTapeWords.push(...appendedWords);
  }
  englishDraftTapeTextsById.set(draftId, text);
  trimEnglishDraftTape();
}

function commonWordPrefixCount(leftWords, rightWords) {
  const limit = Math.min(leftWords.length, rightWords.length);
  let index = 0;
  while (index < limit && leftWords[index].toLowerCase() === rightWords[index].toLowerCase()) {
    index += 1;
  }
  return index;
}

function trimEnglishDraftTape() {
  const maxWords = 180;
  if (englishDraftTapeWords.length <= maxWords) {
    return;
  }
  const removed = englishDraftTapeWords.length - maxWords;
  englishDraftTapeWords = englishDraftTapeWords.slice(-maxWords);
  englishDraftLineStartWord = Math.max(0, englishDraftLineStartWord - removed);
  englishDraftLineEndWord = Math.max(0, englishDraftLineEndWord - removed);
}

function promoteDraftLeadToContext(item, draftId) {
  const text = String(item.sourceText || "").trim();
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length < localDraftPromoteWordCount) {
    removeProvisionalContext(draftId);
    return;
  }

  const leadText = words.slice(0, -localDraftTailWordCount).join(" ").trim();
  if (!leadText) {
    removeProvisionalContext(draftId);
    return;
  }

  upsertHistory(englishContextHistory, {
    ...item,
    sequenceId: `${draftId}-provisional-context`,
    sourceText: leadText,
    translatedText: "",
    isFinal: true,
    isProvisional: true,
  });
  englishContextHistory = englishContextHistory.slice(-24);
}

function removeProvisionalContext(draftId) {
  englishContextHistory = englishContextHistory.filter(
    (entry) =>
      entry.sequenceId !== `${draftId}-provisional-context`
      && !String(entry.sequenceId || "").startsWith(`${draftId}-draft-page-`),
  );
}

function draftDisplayText(text) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  const words = normalized.split(/\s+/).filter(Boolean);
  if (words.length <= localDraftPromoteWordCount) {
    return normalized;
  }
  return words.slice(-localDraftTailWordCount).join(" ");
}

function upsertEnglishLiveBuffer(item, sequenceId, isFinal) {
  const text = String(item.sourceText || "").replace(/\s+/g, " ").trim();
  if (!text || isFinal) {
    return;
  }
  const existingIndex = englishLiveBuffer.findIndex((entry) => entry.sequenceId === sequenceId);
  const entry = {
    ...item,
    sequenceId,
    sourceText: text,
    translatedText: "",
    isFinal,
    updatedAt: Date.now(),
  };
  if (existingIndex >= 0) {
    englishLiveBuffer[existingIndex] = {
      ...englishLiveBuffer[existingIndex],
      ...entry,
    };
  } else {
    englishLiveBuffer.push(entry);
  }
  englishLiveBuffer = englishLiveBuffer.slice(-10);
}

function removeEnglishLiveBuffer(sequenceId) {
  englishLiveBuffer = englishLiveBuffer.filter((entry) => entry.sequenceId !== sequenceId);
}

function buildEnglishDraftWindow() {
  const words = englishDraftTapeWords;
  if (!words.length) {
    englishDraftLineStartWord = 0;
    englishDraftLineEndWord = 0;
    englishDraftLastWordCount = 0;
    return null;
  }
  if (words.length < englishDraftLastWordCount || englishDraftLineStartWord >= words.length) {
    englishDraftLineStartWord = 0;
    englishDraftLineEndWord = 0;
    englishDraftPendingAdvance = false;
  }
  if (
    englishDraftPendingAdvance
    && englishDraftLineEndWord > englishDraftLineStartWord
    && englishDraftLineEndWord < words.length
  ) {
    const completedPage = {
      startWord: englishDraftLineStartWord,
      endWord: englishDraftLineEndWord,
      text: words.slice(englishDraftLineStartWord, englishDraftLineEndWord).join(" "),
    };
    promoteDraftPageToContext(completedPage, englishDraftActiveItem, englishDraftActiveItem);
    englishDraftLineStartWord = englishDraftLineEndWord;
    englishDraftPendingAdvance = false;
  }
  const draftWindow = longestFittingDraftPage(words, englishDraftLineStartWord);
  englishDraftLineStartWord = draftWindow.startWord;
  englishDraftLineEndWord = draftWindow.endWord;
  englishDraftPendingAdvance = draftWindow.text && draftWindow.endWord < words.length;
  englishDraftLastWordCount = words.length;
  return {
    sequenceId: "local-live-window",
    sourceText: draftWindow.text,
    translatedText: "",
    start: englishDraftActiveItem?.start || 0,
    end: englishDraftActiveItem?.end || 0,
    isFinal: false,
  };
}

function promoteDraftPageToContext(page, firstEntry, lastEntry) {
  const text = String(page.text || "").trim();
  if (!text || !englishDraftActiveId) {
    return;
  }
  const sequenceId = `${englishDraftActiveId}-draft-page-${page.startWord}-${page.endWord}`;
  upsertHistory(englishContextHistory, {
    ...(englishDraftActiveItem || firstEntry || {}),
    sequenceId,
    sourceText: text,
    translatedText: "",
    start: firstEntry?.start,
    end: lastEntry?.end,
    isFinal: true,
    isProvisional: true,
  });
  englishContextHistory = englishContextHistory.slice(-24);
}

function longestFittingDraftPage(words, startWord = 0) {
  if (!words.length) {
    return { startWord: 0, endWord: 0, text: "" };
  }
  const safeStart = Math.max(0, Math.min(startWord, words.length - 1));
  for (let endWord = words.length; endWord > safeStart; endWord -= 1) {
    const text = words.slice(safeStart, endWord).join(" ");
    if (!draftTextWouldOverflow(text)) {
      return { startWord: safeStart, endWord, text };
    }
  }
  return { startWord: safeStart, endWord: safeStart + 1, text: words[safeStart] };
}

function draftTextWouldOverflow(text) {
  if (!englishDraftStack || !text) {
    return false;
  }
  const probe = document.createElement("span");
  probe.className = "draft-measure-probe";
  probe.textContent = text;
  englishDraftStack.append(probe);
  const availableWidth = Math.max(40, englishDraftStack.clientWidth - 44);
  const wouldOverflow = probe.scrollWidth > availableWidth;
  probe.remove();
  return wouldOverflow;
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
    const state = entry.isProvisional ? " - context" : mode === "draft" ? " - draft" : "";
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

  if (mode === "context") {
    renderEnglishContextTypewriter(target, text);
    return;
  }

  target.innerHTML = "";
  const paragraph = document.createElement("p");
  paragraph.className = `flow-text ${mode === "translation" ? "translation-flow-text" : ""} ${mode === "context" ? "english-flow-text" : ""}`.trim();
  paragraph.textContent = text;
  target.append(paragraph);
}

function renderEnglishContextTypewriter(target, nextText) {
  let paragraph = target.querySelector(".english-flow-text");
  if (!paragraph) {
    target.innerHTML = "";
    paragraph = document.createElement("p");
    paragraph.className = "flow-text english-flow-text";
    target.append(paragraph);
    englishContextRenderedText = "";
  }

  const currentText = paragraph.textContent || "";
  if (englishContextTypeTimer) {
    clearTimeout(englishContextTypeTimer);
    englishContextTypeTimer = null;
  }

  if (nextText.length < currentText.length || !nextText.startsWith(currentText)) {
    const commonPrefix = commonTextPrefix(currentText, nextText);
    if (commonPrefix.length >= Math.min(24, Math.floor(currentText.length * 0.6))) {
      englishContextRenderedText = commonPrefix;
      paragraph.textContent = commonPrefix;
    } else {
      englishContextRenderedText = nextText;
      paragraph.textContent = nextText;
      paragraph.classList.toggle("typing", Boolean(nextText));
      return;
    }
  } else {
    englishContextRenderedText = currentText;
  }

  paragraph.classList.toggle("typing", englishContextRenderedText.length < nextText.length);

  const tick = () => {
    if (englishContextRenderedText.length >= nextText.length) {
      paragraph.classList.toggle("typing", Boolean(nextText));
      englishContextTypeTimer = null;
      return;
    }
    englishContextRenderedText = nextText.slice(
      0,
      Math.min(nextText.length, englishContextRenderedText.length + englishContextTypeChunk),
    );
    paragraph.textContent = englishContextRenderedText;
    if (autoFollowEnglishContext) {
      target.scrollTop = target.scrollHeight;
    }
    englishContextTypeTimer = window.setTimeout(tick, englishContextTypeDelayMs);
  };

  tick();
}

function commonTextPrefix(left, right) {
  const maxLength = Math.min(left.length, right.length);
  let index = 0;
  while (index < maxLength && left[index] === right[index]) {
    index += 1;
  }
  return left.slice(0, index).replace(/\s+\S*$/, "").trimEnd();
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
    ? "Cloud mode: streaming live subtitles."
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
  const sourceLabel = sourceLanguage.value === "spa_Latn" ? "Spanish" : sourceLanguage.value === "zho_Hans" ? "Chinese" : "English";
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
  const preset = localAsrPreset?.value || "igpu";
  const isSystemAudio = audioSource?.value === "system";
  if (preset === "igpu" || preset === "fast") {
    return {
      model: "base.en",
      computeType: "int8",
      device: "cpu",
      beamSize: 1,
      bestOf: 1,
      patience: 1.0,
      conditionOnPreviousText: false,
      noSpeechThreshold: isSystemAudio ? 0.72 : 0.62,
      logProbThreshold: isSystemAudio ? -0.75 : -1.0,
      compressionRatioThreshold: 2.35,
      hallucinationSilenceThreshold: isSystemAudio ? 0.7 : 1.0,
      repetitionPenalty: 1.1,
      noRepeatNgramSize: 3,
      label: "iGPU: 16GB RAM assumed - base / int8 / beam 1",
    };
  }
  if (preset === "hp" || preset === "t600" || preset === "accurate") {
    return {
      model: "small.en",
      computeType: "int8_float16",
      device: "cuda",
      beamSize: 3,
      bestOf: 3,
      patience: 1.2,
      conditionOnPreviousText: false,
      noSpeechThreshold: isSystemAudio ? 0.66 : 0.55,
      logProbThreshold: isSystemAudio ? -0.9 : -1.2,
      compressionRatioThreshold: 2.4,
      hallucinationSilenceThreshold: isSystemAudio ? 0.9 : 1.5,
      repetitionPenalty: 1.06,
      noRepeatNgramSize: 3,
      label: "HP: 16GB RAM assumed - small / int8_float16 / beam 3",
    };
  }
  return {
    model: "small.en",
    computeType: "int8",
    device: "auto",
    beamSize: 2,
    bestOf: 2,
    patience: 1.0,
    conditionOnPreviousText: false,
    noSpeechThreshold: isSystemAudio ? 0.68 : 0.58,
    logProbThreshold: isSystemAudio ? -0.85 : -1.1,
    compressionRatioThreshold: 2.4,
    hallucinationSilenceThreshold: isSystemAudio ? 0.8 : 1.2,
    repetitionPenalty: 1.08,
    noRepeatNgramSize: 3,
    label: "dGPU: 16GB RAM assumed - small / int8 / beam 2",
  };
}

function applyLocalAsrPreset() {
  if (!localAsrPreset || translationEngine.value === "azure") {
    return;
  }
  const profile = localAsrProfile();
  deviceType.value = profile.device;
  localLatencyPreset.value = profile.device === "cuda" ? "steady" : "low";
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
  const isSystemAudio = audioSource?.value === "system";
  if (isLowLatencyLocal) {
    return {
      overlap_seconds: isSystemAudio ? 0.15 : 0.3,
      adaptive_chunking_enabled: !isSystemAudio,
      min_chunk_seconds: isSystemAudio ? 2 : 1,
      chunk_flush_silence_seconds: isSystemAudio ? 0 : 0.35,
      queue_max_size: 2,
      segmenter_pause_seconds: isSystemAudio ? 1.1 : 0.9,
      segmenter_max_words: isSystemAudio ? 22 : 28,
      segmenter_max_seconds: isSystemAudio ? 6 : 8,
      context_buffer_enabled: false,
      context_buffer_min_words: 10,
      context_buffer_max_words: 42,
      context_buffer_max_wait_seconds: 0.8,
    };
  }
  return {
    overlap_seconds: isSystemAudio ? 0.2 : 0.5,
    adaptive_chunking_enabled: !isSystemAudio,
    min_chunk_seconds: isSystemAudio ? 3 : 1.5,
    chunk_flush_silence_seconds: isSystemAudio ? 0 : 0.45,
    queue_max_size: 2,
    segmenter_pause_seconds: 1.2,
    segmenter_max_words: isSystemAudio ? 30 : 36,
    segmenter_max_seconds: isSystemAudio ? 9 : 12,
    context_buffer_enabled: false,
    context_buffer_min_words: 14,
    context_buffer_max_words: 52,
    context_buffer_max_wait_seconds: 1.1,
  };
}

function updateLanguageHints() {
  const isSpanish = sourceLanguage.value === "spa_Latn";
  const isChinese = sourceLanguage.value === "zho_Hans";
  const isCloud = translationEngine.value === "azure";
  const subtitle = document.querySelector("#brandSubtitle");
  if (subtitle) {
    subtitle.textContent = isChinese
      ? "Chinese meeting notes - English-Chinese output"
      : isSpanish
      ? "Spanish to Chinese - Local or Cloud"
      : "English to Chinese - Local or Cloud";
  }
  if (isCloud) {
    perfText.textContent = isChinese
      ? "Cloud Chinese: zh-CN transcription for bilingual notes."
      : isSpanish
      ? "Cloud Spanish: es-ES -> zh-Hans live translation."
      : "Cloud English: en-US -> zh-Hans live translation.";
    return;
  }
  perfText.textContent = isSpanish
    ? "Local Spanish: multilingual Whisper is selected automatically."
    : isChinese
    ? "Local Chinese: multilingual Whisper is selected automatically."
    : "Local English: optimized English ASR is available.";
}

function notesRecordingLanguage() {
  if (sourceLanguage.value === "spa_Latn") {
    return "es-ES";
  }
  if (sourceLanguage.value === "zho_Hans") {
    return "zh-CN";
  }
  return "en";
}

function start() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    return;
  }
  isLiveSessionActive = true;
  if (translationEngine.value === "azure" && !azureConfigured) {
    noticeText.textContent = "Cloud not configured";
    logText.textContent = "Cloud speech is not configured. Start may fail until cloud settings are available.";
    updateDelayHintFromStatus("Cloud not configured", logText.textContent);
  }

  subtitleStack.innerHTML = "";
  englishContextStack.innerHTML = "";
  englishDraftStack.innerHTML = "";
  chineseSubtitleStack.innerHTML = "";
  finalSubtitleHistory = [];
  englishContextHistory = [];
  englishDraftById = new Map();
  englishLiveBuffer = [];
  englishDraftLineStartWord = 0;
  englishDraftLineEndWord = 0;
  englishDraftLastWordCount = 0;
  englishDraftActiveId = "";
  englishDraftActiveItem = null;
  englishDraftPendingAdvance = false;
  englishDraftTapeWords = [];
  englishDraftTapeTextsById = new Map();
  englishContextRenderedText = "";
  if (englishContextTypeTimer) {
    clearTimeout(englishContextTypeTimer);
    englishContextTypeTimer = null;
  }
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
      isCloud ? "Connecting to cloud speech translation." : "Preparing low-latency local pipeline.",
    );
    startAzureUsageSession();
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
        asr_condition_on_previous_text: asrProfile?.conditionOnPreviousText ?? false,
        asr_no_speech_threshold: asrProfile?.noSpeechThreshold ?? 0.58,
        asr_log_prob_threshold: asrProfile?.logProbThreshold ?? -1.1,
        asr_compression_ratio_threshold: asrProfile?.compressionRatioThreshold ?? 2.4,
        asr_hallucination_silence_threshold: asrProfile?.hallucinationSilenceThreshold ?? 1.2,
        asr_repetition_penalty: asrProfile?.repetitionPenalty ?? 1.08,
        asr_no_repeat_ngram_size: asrProfile?.noRepeatNgramSize ?? 3,
        asr_hotwords_enabled: false,
        asr_use_default_hotwords: false,
        audio_source: audioSource.value,
        source_language: sourceLanguage.value,
        target_language: "zho_Hans",
        translation_engine: translationEngine.value,
        system_vad_rms_threshold: 0.016,
        chunk_seconds: effectiveChunk,
        overlap_seconds: realtimeTuning?.overlap_seconds ?? 0.5,
        adaptive_chunking_enabled: realtimeTuning?.adaptive_chunking_enabled ?? true,
        min_chunk_seconds: realtimeTuning?.min_chunk_seconds ?? 1,
        chunk_flush_silence_seconds: realtimeTuning?.chunk_flush_silence_seconds ?? 0.35,
        max_subtitles: serverSubtitleWindow,
        queue_max_size: realtimeTuning?.queue_max_size ?? 2,
        segmenter_pause_seconds: realtimeTuning?.segmenter_pause_seconds,
        segmenter_max_words: realtimeTuning?.segmenter_max_words,
        segmenter_max_seconds: realtimeTuning?.segmenter_max_seconds,
        context_buffer_enabled: realtimeTuning?.context_buffer_enabled ?? true,
        context_buffer_min_words: realtimeTuning?.context_buffer_min_words,
        context_buffer_max_words: realtimeTuning?.context_buffer_max_words,
        context_buffer_max_wait_seconds: realtimeTuning?.context_buffer_max_wait_seconds,
      },
    }));
  });

  socket.addEventListener("message", (event) => {
    if (!isLiveSessionActive) {
      return;
    }
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (error) {
      setStatus("Error", "Received invalid server message");
      return;
    }
    if (payload.type === "status") {
      setStatus(payload.status, providerNeutralText(payload.detail));
      return;
    }
    if (payload.type === "notice") {
      noticeText.textContent = payload.label || "Notice";
      noticeText.title = providerNeutralText(payload.detail || "");
      if (payload.detail) {
        logText.textContent = providerNeutralText(payload.detail);
      }
      if ((payload.label || "").toLowerCase() === "recording") {
        updateRecordingPanel("recording", payload.detail || "");
      }
      if (Date.now() - lastSubtitleReceivedAt > 5000) {
        updateDelayHintFromStatus(payload.label || "Notice", providerNeutralText(payload.detail || ""));
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
    stopAzureUsageSession();
    stopButton.disabled = true;
    isLiveSessionActive = false;
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
  isLiveSessionActive = false;
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
  isLiveSessionActive = false;
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
  }, 30 * 60 * 1000);
  startNotesProgressPolling();
  updateMeetingActionButtons();
  noticeText.textContent = "Processing meeting notes";
  const recordings = selectedRecordings();
  logText.textContent = `Building notes from ${recordings.length} selected recording(s). You can cancel this if it takes too long.`;
  updateDelayHintFromStatus("Creating notes", logText.textContent);
  try {
    const response = await fetch("/api/process-recording", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        recordings,
        engine: translationEngine.value,
        notesEngine: notesEngine?.value || "aliyun-tingwu",
        tingwuUploadProvider: aliyunTingwuUploadProvider || "oss",
        notesLanguage: notesRecordingLanguage(),
      }),
      signal: notesAbortController.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(providerNeutralText(payload.detail || "Post-meeting processing failed."));
    }

    const minutesPreview = (payload.minutesText || "").slice(0, 1600).trim();
    latestMinutesPath = payload.minutes || "";
    noticeText.textContent = "Meeting notes ready";
    setNotesProgress(100, "Complete", "Meeting notes are ready.", true);
    logText.textContent = providerNeutralText([
      "Post-meeting files generated.",
      payload.notesMode || notesBuildHint(),
      `ASR engine: ${payload.asrEngine || "auto"}`,
      `Recording: ${payload.recording}`,
      `Transcript: ${payload.transcript}`,
      `Minutes: ${payload.minutes}`,
      "",
      minutesPreview || payload.log || "No preview text returned.",
    ].join("\n"));
    setStatus("Stopped", "Meeting notes ready.");
  } catch (error) {
    if (error.name === "AbortError") {
      noticeText.textContent = "Meeting notes cancelled";
      setNotesProgress(0, "Cancelled", "Meeting notes generation was cancelled.", false);
      setStatus("Stopped", "Meeting notes generation was cancelled.");
      logText.textContent = "Post-meeting notes generation was cancelled. Choose recordings and build again when ready.";
    } else {
      noticeText.textContent = "Meeting notes failed";
      const message = providerNeutralText(error.message || "Post-meeting processing failed.");
      setNotesProgress(0, "Failed", message, false);
      setStatus("Error", message);
      logText.textContent = message;
    }
  } finally {
    if (notesTimeoutId) {
      window.clearTimeout(notesTimeoutId);
      notesTimeoutId = null;
    }
    notesAbortController = null;
    stopNotesProgressPolling();
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
  stopNotesProgressPolling();
  setNotesProgress(0, "Cancelled", message, false);
  noticeText.textContent = "Meeting notes cancelled";
  logText.textContent = message;
}

async function checkCloudNotesSetup() {
  if (notesEngine?.value !== "aliyun-tingwu") {
    return;
  }
  if (checkCloudNotesButton) {
    checkCloudNotesButton.disabled = true;
    checkCloudNotesButton.textContent = "Checking";
  }
  notesStatusText.textContent = "Checking";
  notesStatusText.classList.add("muted");
  notesHintText.textContent = "Checking Aliyun Tingwu cloud notes setup.";
  try {
    const uploadProvider = aliyunTingwuUploadProvider || "oss";
    const response = await fetch(`/api/aliyun-tingwu-diagnostics?uploadProvider=${encodeURIComponent(uploadProvider)}`);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || "Cloud notes setup check failed.");
    }
    const checks = Array.isArray(payload.checks) ? payload.checks : [];
    const failed = checks.filter((item) => !item.ok);
    aliyunTingwuConfigured = Boolean(payload.ok);
    aliyunTingwuEnabled = checks.some((item) => item.name === "Tingwu Enabled" && item.ok) || aliyunTingwuEnabled;
    aliyunTingwuMissing = failed
      .filter((item) => ["Tingwu AppKey", "OSS Bucket", "Tencent Relay URL"].includes(item.name))
      .map((item) => item.name);
    notesStatusText.textContent = payload.ok ? "Cloud ready" : "Cloud setup";
    notesStatusText.classList.toggle("muted", !payload.ok);
    notesHintText.textContent = payload.ok
      ? "Aliyun Tingwu is ready for cloud meeting notes."
      : failed.map((item) => item.message).join(" ");
    logText.textContent = checks
      .map((item) => `${cloudCheckStatusText(item)} - ${item.name}: ${item.message}`)
      .join("\n");
    noticeText.textContent = payload.ok ? "Cloud notes ready" : "Cloud setup incomplete";
  } catch (error) {
    const message = providerNeutralText(error.message || "Could not check Aliyun Tingwu setup.");
    notesStatusText.textContent = "Check failed";
    notesStatusText.classList.add("muted");
    notesHintText.textContent = message;
    logText.textContent = message;
  } finally {
    if (checkCloudNotesButton) {
      checkCloudNotesButton.disabled = false;
      checkCloudNotesButton.textContent = "Cloud Check";
    }
    updateMeetingActionButtons();
  }
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
      throw new Error(providerNeutralText(payload.detail || "No meeting notes file found."));
    }
    latestMinutesPath = payload.minutes || latestMinutesPath;
    window.open("/api/latest-minutes-file", "_blank", "noopener");
    noticeText.textContent = "Meeting notes opened";
    logText.textContent = `Opened: ${latestMinutesPath}`;
  } catch (error) {
    noticeText.textContent = "Open notes failed";
    logText.textContent = providerNeutralText(error.message || "Could not open meeting notes.");
  } finally {
    updateMeetingActionButtons();
  }
}

async function openProjectFolder(kind) {
  const label = kind === "notes" ? "notes folder" : "recordings folder";
  try {
    const response = await fetch(`/api/open-folder/${kind}`, { method: "POST" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(providerNeutralText(payload.detail || `Could not open ${label}.`));
    }
    noticeText.textContent = kind === "notes" ? "Notes folder opened" : "Recordings folder opened";
    logText.textContent = `Opened: ${payload.path || label}`;
  } catch (error) {
    noticeText.textContent = "Open folder failed";
    logText.textContent = providerNeutralText(error.message || `Could not open ${label}.`);
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
checkCloudNotesButton?.addEventListener("click", checkCloudNotesSetup);
refreshRecordingsButton?.addEventListener("click", () => refreshRecordings(currentRecordingPath));
openRecordingsFolderButton?.addEventListener("click", () => openProjectFolder("recordings"));
openNotesFolderButton?.addEventListener("click", () => openProjectFolder("notes"));
notesUtilityToggle?.addEventListener("click", () => toggleUtilityPanel("notes"));
settingsUtilityToggle?.addEventListener("click", () => toggleUtilityPanel("settings"));
downloadTranscriptButton.addEventListener("click", () => {
  downloadMarkdown("meeting-transcript", transcriptMarkdown());
});
downloadMinutesButton.addEventListener("click", () => {
  downloadMarkdown("meeting-minutes", minutesMarkdown());
});
translationEngine.addEventListener("change", updateEngineControls);
translationEngine.addEventListener("change", updateLanguageHints);
translationEngine.addEventListener("change", renderAzureUsage);
notesEngine?.addEventListener("change", updateMeetingActionButtons);
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
renderAzureUsage();
startAzureUsageCloudPolling();
loadRuntimeConfig();
refreshLatestMinutesState();
refreshRecordings();
