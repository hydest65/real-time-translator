// Keep caption sizing independent from window size and the rest of the UI theme.
(() => {
  const storageKey = "subtitleStudioUiThemeCompact20260502";
  const root = document.documentElement;
  const status = document.getElementById("captionSettingsStatus");
  const streams = [...document.querySelectorAll(".subtitle-stream")];
  const controls = [
    { property: "--source-font-size", fallback: 18, number: "sourceFontSize", slider: "sourceFontSlider" },
    { property: "--subtitle-font-size", fallback: 32, number: "translationFontSize", slider: "translationFontSlider" },
  ].map((control) => ({ ...control,
    number: document.getElementById(control.number),
    slider: document.getElementById(control.slider),
  }));

  function readTheme() {
    try {
      const theme = JSON.parse(localStorage.getItem(storageKey) || "{}");
      return theme && typeof theme === "object" && !Array.isArray(theme) ? theme : {};
    } catch {
      return {};
    }
  }

  function update(control, value, save = true) {
    const size = Math.min(96, Math.max(12, Math.round(value)));
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
        status.textContent = "Font sizes saved";
      } catch {
        status.textContent = "Applied. Browser storage is unavailable.";
      }
    }
  }

  controls.forEach((control) => {
    const stored = readTheme()[control.property];
    const match = typeof stored === "string" && stored.match(/^(\d+(?:\.\d+)?)px$/);
    update(control, match ? Number(match[1]) : control.fallback, false);
    control.slider.addEventListener("input", () => update(control, Number(control.slider.value)));
    control.number.addEventListener("input", () => {
      const value = control.number.valueAsNumber;
      // Leave partial input intact so typing 32 does not first turn 3 into 12.
      if (Number.isInteger(value) && value >= 12 && value <= 96) update(control, value);
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
  document.getElementById("resetCaptionFonts").addEventListener("click", () => {
    controls.forEach((control) => update(control, control.fallback));
  });
  window.addEventListener("storage", (event) => {
    if (event.key !== storageKey && event.key !== null) return;
    const theme = readTheme();
    controls.forEach((control) => {
      const match = String(theme[control.property] || "").match(/^(\d+(?:\.\d+)?)px$/);
      update(control, match ? Number(match[1]) : control.fallback, false);
    });
  });
})();
