const storageKey = "subtitleStudioUiTheme";
const controls = [...document.querySelectorAll("[data-theme-key]")];
const previewFrame = document.querySelector("#previewFrame");
const saveButton = document.querySelector("#saveTheme");
const resetButton = document.querySelector("#resetTheme");
const cssOutput = document.querySelector("#cssOutput");

const defaults = Object.fromEntries(
  controls.map((control) => {
    const unit = control.dataset.unit || "";
    return [control.dataset.themeKey, `${control.value}${unit}`];
  }),
);

let theme = loadTheme();

function loadTheme() {
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem(storageKey) || "{}") };
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

function saveTheme() {
  localStorage.setItem(storageKey, JSON.stringify(theme));
  applyThemeToPreview();
}

function resetTheme() {
  theme = { ...defaults };
  localStorage.removeItem(storageKey);
  setControlValues();
  applyThemeToPreview();
  renderCssOutput();
}

controls.forEach((control) => {
  control.addEventListener("input", () => updateThemeFromControl(control));
});

saveButton.addEventListener("click", saveTheme);
resetButton.addEventListener("click", resetTheme);
previewFrame.addEventListener("load", applyThemeToPreview);

setControlValues();
applyThemeToPreview();
renderCssOutput();
