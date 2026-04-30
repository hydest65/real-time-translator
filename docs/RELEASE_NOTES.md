# Release Notes

## Unreleased - Spanish Source Language

Date: 2026-04-30

### Product

- Added Spanish-to-Chinese alongside the existing English-to-Chinese workflow.
- Added a source language selector on the main Subtitle Studio toolbar.

### Backend

- Allowed `spa_Latn` source language through runtime config instead of forcing English.
- Mapped Spanish local ASR to Whisper `es` and multilingual `base` / `small` models.
- Mapped Azure Spanish mode to `es-ES -> zh-Hans`.
- Added Argos, MarianMT, and NLLB routing for Spanish-to-Chinese local translation.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- Spanish config mapping check passed for `spa_Latn -> es-ES`, Whisper `es`, and multilingual ASR model selection.
- Runtime audio behavior still depends on local audio routing and valid Azure credentials.

## 0.1.2 - Visual UI Editor Closeout

Date: 2026-04-30

### Product

- Added a browser-based visual UI editor for quick local appearance tuning.
- Kept the main subtitle workflow unchanged: Azure Cloud remains the primary low-latency route and local engines remain fallback options.
- Preserved the fast/direct translation model with no MiniMax, Balanced, or Quality controls.

### Frontend

- Added `/static/ui-editor.html` with live preview controls for background color, panel color, accent/subtitle color, text color, subtitle font sizes, left panel width, corner radius, and background decoration.
- Added `frontend/ui-editor.css` and `frontend/ui-editor.js`.
- Main page now loads saved editor choices from browser `localStorage` using the `subtitleStudioUiTheme` key.
- Added a `UI Editor` entry button to the main toolbar.
- Removed the extra raised shell behind the topbar while preserving the individual brand and toolbar cards.
- Restored the main subtitle monitor outer shell after visual review because the page looked weaker without it.

### Documentation

- Updated README, product requirements, technical architecture, UI style notes, QA checklist, and the project-local closeout skill.

### Verification

- Frontend JavaScript syntax check passed for `frontend/app.js` and `frontend/ui-editor.js` with the bundled Node runtime.
- Backend compile and import checks passed.
- Local health endpoints responded on ports `8000` and `8001`.
- Full live audio behavior still depends on local audio device routing and valid Azure credentials.

### Known Limitations

- UI editor saves to the current browser only; it does not yet write accepted styles back into `frontend/style.css`.
- Browser cache may require `Ctrl + F5` after static asset changes.
- System audio still depends on Windows exposing a monitor input or Stereo Mix.

## 0.1.1 - Fast-Only Soft UI Closeout

Date: 2026-04-30

### Product

- Confirmed Azure Cloud as the primary live subtitle route and local engines as fallback options.
- Removed MiniMax polishing from the active product path.
- Removed Balanced and Quality modes so the app has one fast/direct translation behavior.

### Frontend

- Kept the selected Soft UI Evolution / Focus Display interface.
- Added a small red operating lamp in the logo block.
- The lamp remains dim red when stopped, pulses slowly when running or connecting, and stays red on error.
- Added static asset versioning for the lamp update so the browser does not keep stale CSS.

### Backend

- Removed MiniMax text polishing module, queue, payload fields, and HTTP dependency.
- Removed runtime handling for quality and latency mode switches.
- Kept Azure streaming and local fallback paths.

### Verification

- Python backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed.
- Live audio behavior still depends on local audio device routing and valid Azure credentials.

### Known Limitations

- System audio still depends on Windows exposing a monitor input or Stereo Mix.
- Azure cloud mode requires `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION`.
- Current paragraph detection is pause-based, not true speaker diarization.

## 0.1.0 - Working Prototype Closeout

Date: 2026-04-29

### Product

- Completed a usable local browser subtitle studio.
- Main workflow supports microphone or system audio, Azure streaming translation, and bilingual subtitle display.
- Removed MiniMax polishing from the active product path after live testing showed limited value for this workflow.
- Fixed the app to a single fast translation mode.

### Backend

- Added Azure Speech Translation streaming route.
- Kept local fallback route with faster-whisper and local translation engines.
- Removed the MiniMax polish queue, HTTP dependency, and text polishing module.
- Removed Balanced/Quality mode handling from the runtime path.
- Added lightweight paragraph turn detection.
- Added performance payloads for subtitle events.

### Frontend

- Redesigned into a compact SaaS-style Subtitle Studio.
- Updated the formal app UI to the selected Soft UI Evolution `Focus Display` direction with a larger subtitle monitor, recessed subtitle stream, raised controls, and light gray-blue palette.
- Added fixed subtitle monitor.
- Added internal subtitle history scrolling.
- Added bottom auto-follow behavior that pauses when the user scrolls upward.
- Added minute-second timestamp formatting.

### Verification

- Python backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed.
- Full live audio verification still depends on local microphone/system audio and active Azure credentials.
- GitHub Desktop is installed, but command-line `git` is not available in this shell.

### Known Limitations

- System audio depends on Windows exposing a usable monitor input or Stereo Mix.
- Azure credentials must be provided through environment variables for cloud mode.
- MiniMax is no longer part of this version.
- Current paragraph detection is pause-based, not true speaker diarization.
- Local MarianMT still uses Transformers, not CTranslate2 int8.
