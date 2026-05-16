const storageKey = "subtitleStudioUiThemeCompact20260502";
const controls = [...document.querySelectorAll("[data-theme-key]")];
const previewFrame = document.querySelector("#previewFrame");
const saveButton = document.querySelector("#saveTheme");
const copyCssButton = document.querySelector("#copyCss");
const exportThemeButton = document.querySelector("#exportTheme");
const importThemeButton = document.querySelector("#importTheme");
const importThemeInput = document.querySelector("#importThemeInput");
const resetButton = document.querySelector("#resetTheme");
const cssOutput = document.querySelector("#cssOutput");
const statusMessage = document.querySelector("#statusMessage");

const defaults = Object.fromEntries(
  controls.map((control) => {
    const unit = control.dataset.unit || "";
    return [control.dataset.themeKey, `${control.value}${unit}`];
  }),
);
const themeKeys = new Set(Object.keys(defaults));

let theme = loadTheme();

function normalizeTheme(candidate) {
  const nextTheme = { ...defaults };
  Object.entries(candidate || {}).forEach(([key, value]) => {
    if (themeKeys.has(key) && typeof value === "string" && value.trim()) {
      nextTheme[key] = value;
    }
  });
  return nextTheme;
}

function loadTheme() {
  try {
    return normalizeTheme(JSON.parse(localStorage.getItem(storageKey) || "{}"));
  } catch (error) {
    return { ...defaults };
  }
}

function setControlValues() {
  controls.forEach((control) => {
    const key = control.dataset.themeKey;
    const unit = control.dataset.unit || "";
    control.value = String(theme[key] || defaults[key]).replace(unit, "");
    updateOutputLabel(key, theme[key] || defaults[key]);
  });
}

function updateThemeFromControl(control) {
  const key = control.dataset.themeKey;
  const unit = control.dataset.unit || "";
  theme[key] = `${control.value}${unit}`;
  updateOutputLabel(key, theme[key]);
  applyThemeToPreview();
  renderCssOutput();
}

function updateOutputLabel(key, value) {
  const output = document.querySelector(`[data-output-for="${key}"]`);
  if (output) {
    output.textContent = value;
  }
}

function applyThemeToDocument(documentTarget) {
  if (!documentTarget?.documentElement) {
    return;
  }
  Object.entries(theme).forEach(([key, value]) => {
    documentTarget.documentElement.style.setProperty(key, value);
  });
}

function applyThemeToPreview() {
  applyThemeToDocument(document);
  applyThemeToDocument(previewFrame.contentDocument);
}

function renderCssOutput() {
  cssOutput.value = `:root {\n${Object.entries(theme)
    .map(([key, value]) => `  ${key}: ${value};`)
    .join("\n")}\n}`;
}

function setStatusMessage(message) {
  statusMessage.textContent = message;
}

function saveTheme() {
  localStorage.setItem(storageKey, JSON.stringify(theme));
  applyThemeToPreview();
  setStatusMessage("Theme saved in this browser.");
}

function resetTheme() {
  theme = { ...defaults };
  localStorage.removeItem(storageKey);
  setControlValues();
  applyThemeToPreview();
  renderCssOutput();
  setStatusMessage("Theme reset to defaults.");
}

async function copyCss() {
  try {
    await navigator.clipboard.writeText(cssOutput.value);
    setStatusMessage("CSS copied to clipboard.");
  } catch (error) {
    cssOutput.focus();
    cssOutput.select();
    document.execCommand("copy");
    setStatusMessage("CSS copied with fallback selection.");
  }
}

function exportTheme() {
  const payload = JSON.stringify(theme, null, 2);
  const blob = new Blob([payload], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "subtitle-studio-theme.json";
  link.click();
  URL.revokeObjectURL(url);
  setStatusMessage("Theme JSON exported.");
}

function requestThemeImport() {
  importThemeInput.click();
}

async function importThemeFile(event) {
  const [file] = event.target.files || [];
  if (!file) {
    return;
  }

  try {
    const rawText = await file.text();
    theme = normalizeTheme(JSON.parse(rawText));
    localStorage.setItem(storageKey, JSON.stringify(theme));
    setControlValues();
    applyThemeToPreview();
    renderCssOutput();
    setStatusMessage(`Imported theme from ${file.name}.`);
  } catch (error) {
    setStatusMessage("Theme import failed. Use a valid JSON export file.");
  } finally {
    importThemeInput.value = "";
  }
}

controls.forEach((control) => {
  control.addEventListener("input", () => updateThemeFromControl(control));
});

saveButton.addEventListener("click", saveTheme);
copyCssButton.addEventListener("click", copyCss);
exportThemeButton.addEventListener("click", exportTheme);
importThemeButton.addEventListener("click", requestThemeImport);
importThemeInput.addEventListener("change", importThemeFile);
resetButton.addEventListener("click", resetTheme);
previewFrame.addEventListener("load", applyThemeToPreview);

setControlValues();
applyThemeToPreview();
renderCssOutput();
setStatusMessage(localStorage.getItem(storageKey) ? "Loaded saved browser theme." : "Using default theme values.");
