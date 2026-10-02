// Keep caption appearance independent from window size and the rest of the UI theme.
(() => {
  const storageKey = "subtitleStudioUiThemeCompact20260502";
  const root = document.documentElement;
  const isDesktop = Boolean(window.subtitleDesktop);
  const status = document.getElementById("captionSettingsStatus");
  const streams = [...document.querySelectorAll(".subtitle-stream")];
  const controls = [
    { property: "--source-font-size", fallback: 18, number: "sourceFontSize", slider: "sourceFontSlider" },
    { property: "--subtitle-font-size", fallback: 32, number: "translationFontSize", slider: "translationFontSlider" },
  ].map((control) => ({ ...control,
    number: document.getElementById(control.number),
    slider: document.getElementById(control.slider),
  }));
  const colorControls = [
    { property: "--source-font-color", key: "sourceFontColor", fallback: isDesktop ? "#68788c" : "#586577" },
    { property: "--translation-font-color", key: "translationFontColor", fallback: isDesktop ? "#283445" : "#3f54d2" },
  ].map((control) => ({ ...control,
    picker: document.getElementById(control.key),
    hex: document.getElementById(`${control.key}Hex`),
    current: control.fallback,
  }));
  const visibilityControls = [
    { key: "showSourceText", id: "toggleSourceText", className: "caption-source-hidden", label: "原文字幕", abbreviation: "SRC" },
    { key: "showTranslationText", id: "toggleTranslationText", className: "caption-translation-hidden", label: "译文字幕", abbreviation: "TR" },
  ].map((control) => ({ ...control, button: document.getElementById(control.id) }));
  const visibilityNotice = document.getElementById("captionVisibilityNotice");

  function normalizeColor(value) {
    return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value.trim()) ? value.trim().toLowerCase() : null;
  }

  function savedStatus() {
    status.textContent = isDesktop ? "字幕样式已自动保存" : "Caption appearance saved";
  }

  function storageUnavailableStatus() {
    status.textContent = isDesktop ? "已应用；当前无法保存设置" : "Applied. Browser storage is unavailable.";
  }

  function readTheme() {
    try {
      const theme = JSON.parse(localStorage.getItem(storageKey) || "{}");
      return theme && typeof theme === "object" && !Array.isArray(theme) ? theme : {};
    } catch {
      return {};
    }
  }

  function update(control, value, save = true) {
    const size = Math.min(160, Math.max(10, Math.round(value)));
    // A font change should keep live readers at the bottom without pulling
    // someone reviewing older captions away from their current scroll position.
    const positions = streams.map((stream) => ({ stream, top: stream.scrollTop,
      following: stream.scrollHeight - stream.scrollTop - stream.clientHeight < 40 }));
    root.style.setProperty(control.property, `${size}px`);
    control.slider.value = size;
    control.number.value = size;
    positions.forEach(({ stream, top, following }) => {
      stream.scrollTop = following ? stream.scrollHeight : top;
    });
    if (save) {
      try {
        const theme = readTheme();
        theme[control.property] = `${size}px`;
        localStorage.setItem(storageKey, JSON.stringify(theme));
        savedStatus();
      } catch {
        storageUnavailableStatus();
      }
    }
  }

  function defaultColor(control) {
    if (!isDesktop && control.key === "translationFontColor") {
      return normalizeColor(getComputedStyle(root).getPropertyValue("--accent-strong")) || control.fallback;
    }
    return control.fallback;
  }

  function updateColor(control, value, save = true, useDefault = false) {
    const color = normalizeColor(value);
    if (!color) return;
    // Web renderers retain their original individual colors until the user
    // chooses an override. Desktop renderers share the light palette defaults.
    if (useDefault && !isDesktop) root.style.removeProperty(control.property);
    else root.style.setProperty(control.property, color);
    control.current = color;
    control.picker.value = color;
    control.hex.value = color.toUpperCase();
    control.hex.removeAttribute("aria-invalid");
    if (save) {
      try {
        const theme = readTheme();
        if (useDefault && !isDesktop) delete theme[control.key];
        else theme[control.key] = color;
        localStorage.setItem(storageKey, JSON.stringify(theme));
        savedStatus();
      } catch {
        storageUnavailableStatus();
      }
    }
  }

  function restoreColors(theme) {
    colorControls.forEach((control) => {
      const stored = normalizeColor(theme[control.key]);
      updateColor(control, stored || defaultColor(control), false, !stored);
    });
  }

  function updateVisibility(control, visible, save = true) {
    control.button.setAttribute("aria-pressed", String(visible));
    control.button.title = `${visible ? "隐藏" : "显示"}${control.label}（${control.abbreviation}）`;
    document.body.classList.toggle(control.className, !visible);
    const allHidden = visibilityControls.every(({ button }) => button.getAttribute("aria-pressed") === "false");
    document.body.classList.toggle("caption-text-hidden", allHidden);
    visibilityNotice.hidden = !allHidden;
    if (save) {
      try {
        const theme = readTheme();
        theme[control.key] = visible;
        localStorage.setItem(storageKey, JSON.stringify(theme));
        savedStatus();
      } catch {
        storageUnavailableStatus();
      }
    }
  }

  function restoreVisibility(theme) {
    visibilityControls.forEach((control) => {
      updateVisibility(control, typeof theme[control.key] === "boolean" ? theme[control.key] : true, false);
    });
  }

  controls.forEach((control) => {
    const stored = readTheme()[control.property];
    const match = typeof stored === "string" && stored.match(/^(\d+(?:\.\d+)?)px$/);
    update(control, match ? Number(match[1]) : control.fallback, false);
    control.slider.addEventListener("input", () => update(control, Number(control.slider.value)));
    control.number.addEventListener("input", () => {
      const value = control.number.valueAsNumber;
      // Leave partial input intact so typing 32 does not first turn 3 into 10.
      if (Number.isInteger(value) && value >= 10 && value <= 160) update(control, value);
    });
    const commit = () => {
      const value = control.number.valueAsNumber;
      update(control, Number.isFinite(value) ? value : Number(control.slider.value));
    };
    control.number.addEventListener("change", commit);
    control.number.addEventListener("blur", commit);
    control.number.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { commit(); control.number.blur(); }
    });
  });
  restoreColors(readTheme());
  colorControls.forEach((control) => {
    const commitPicker = () => updateColor(control, control.picker.value);
    control.picker.addEventListener("input", commitPicker);
    control.picker.addEventListener("change", commitPicker);
    control.hex.addEventListener("input", () => {
      const color = normalizeColor(control.hex.value);
      if (color) updateColor(control, color);
      else control.hex.setAttribute("aria-invalid", "true");
    });
    const commitHex = () => updateColor(control, normalizeColor(control.hex.value) || control.current);
    control.hex.addEventListener("change", commitHex);
    control.hex.addEventListener("blur", commitHex);
    control.hex.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { commitHex(); control.hex.blur(); }
    });
  });
  restoreVisibility(readTheme());
  visibilityControls.forEach((control) => {
    control.button.addEventListener("click", () => updateVisibility(control, control.button.getAttribute("aria-pressed") !== "true"));
  });
  document.getElementById("resetCaptionFonts").addEventListener("click", () => {
    controls.forEach((control) => update(control, control.fallback));
    colorControls.forEach((control) => updateColor(control, defaultColor(control), true, true));
  });
  window.addEventListener("storage", (event) => {
    if (event.key !== storageKey && event.key !== null) return;
    const theme = readTheme();
    controls.forEach((control) => {
      const match = String(theme[control.property] || "").match(/^(\d+(?:\.\d+)?)px$/);
      update(control, match ? Number(match[1]) : control.fallback, false);
    });
    restoreColors(theme);
    restoreVisibility(theme);
  });
})();
