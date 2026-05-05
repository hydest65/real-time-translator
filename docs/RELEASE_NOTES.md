# Release Notes

## 0.2.0 - High-End Local English Edition

Date: 2026-05-05

### Product

- Repositioned the project as a dedicated high-end local English-to-Chinese subtitle workflow.
- Removed Spanish from the active product surface so local mode can stay on English-only Whisper `.en` models.
- Made `Argos` the default engine and kept Azure Cloud as an optional comparison/fallback route.
- Made `System` the default input for meeting/system-audio capture, with `Mic` as the manual fallback.
- Promoted `medium.en` as the default local ASR model for RTX 5070 Ti 16GB class hardware.

### Frontend

- Removed the Source selector and fixed the runtime payload to `eng_Latn -> zho_Hans`.
- Reordered the ASR selector to `medium.en`, `small.en`, then `base.en`.
- Updated static asset versions for the high-end local build.
- Reworked local mode into a two-level subtitle workspace: English live transcript above and polished Chinese translation below.
- Changed both local subtitle panes from per-utterance cards to continuous long-text flows.
- Tightened local utterance readiness so short fragments such as `and`, `in Vietnam`, or dangling phrases ending with `of the` do not become standalone Chinese subtitles.
- Kept the UI editor import/export/CSS-copy tools added during this upgrade window.

### Backend

- Changed the default app config to `medium.en + cuda + int8 + argos`.
- Pinned PyTorch to `torch==2.11.0+cu128` in `backend/requirements.txt`.
- Simplified runtime language mapping to English-only local and Azure paths.
- Simplified local translation setup by removing the Spanish MarianMT model setting and Argos pivot path.
- Retuned the high-end local Low preset to `1.5s` chunks with longer utterance boundaries to reduce fragmented drafts.
- Added local repeated-phrase filtering so repeated loopback fragments do not become repeated Chinese translation flow.

### Verification

- CUDA is active in the project virtual environment with `torch 2.11.0+cu128`.
- `torch.cuda.is_available()` returned `true`.
- `WhisperASR('base.en', 'cuda', 'int8')` loaded on `cuda`.
- RTX 5070 Ti benchmark on a 13.3s English sample:
- `base.en` warm ASR average: `191.8ms`, RTF `0.014`.
- `small.en` warm ASR average: `301.3ms`, RTF `0.023`.
- `medium.en` warm ASR average: `494.1ms`, RTF `0.037`.

## 0.1.5 - System Loopback and Local Realtime Tuning Closeout

Date: 2026-05-04

### Frontend

- Restored the local English upper area to a continuous reading flow instead of separate stable-row cards.
- Kept the lower local English draft pane for fast draft visibility while ASR is still forming the utterance.
- Tightened the local latency presets so `Low` now drives a `1s` chunk and `Steady` now targets `1.5s`.
- Sent additional local realtime tuning values from the browser to the backend so chunk overlap, queue pressure, and utterance segmentation all match the selected latency preset.

### Backend

- Updated system-audio capture to prefer loopback from the current default Windows playback device when available, with Stereo Mix / speaker-monitor fallback.
- Added `soundcard` as the preferred Windows loopback path for `Input: System`.
- Tuned local chunking, overlap, queue size, and utterance segmentation for earlier subtitle emission.
- Added local English cleanup for noisy punctuation sequences such as repeated `///` and excessive ellipses.
- Completed the local dependency set for `faster-whisper`, Argos, MarianMT, and NLLB startup.

### Product

- Azure Cloud remains the recommended production route for real-time use.
- Argos is now the recommended local engine when realtime behavior matters.
- MarianMT and NLLB remain available for local quality comparison, but on this machine they are not the recommended real-time choice.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- Azure `System` mode was manually verified after the loopback change.
- Local Argos route was verified after dependency completion.
- MarianMT and NLLB import/model startup paths were verified, but their practical real-time usability remains limited on this environment.

## 0.1.4 - Local Split Transcript Closeout

Date: 2026-05-04

### Frontend

- Kept Azure mode on the original single bilingual subtitle monitor and scroll-history strategy.
- Reworked local mode into three reading zones: stable English context, live English draft, and complete Chinese translation.
- Changed the local English context and Chinese translation panes from scrolling subtitle rows to continuous forward text blocks.
- Kept the local English draft pane separate so ASR updates can remain responsive while Chinese waits for a fuller utterance.
- Versioned the main static assets so browser refresh picks up the local split transcript update.

### Backend

- Kept `LocalUtteranceAggregator` as the local sentence/utterance boundary layer.
- Made local translation jobs run through a background queue that does not block the English draft path.
- Added safer translation-worker exception handling and task cleanup on stop/disconnect.

### Product

- Local mode now optimizes for watchability: immediate English draft, readable English context, and slightly delayed complete Chinese.
- Azure remains the recommended lowest-latency mode and keeps its existing UI behavior.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- GitHub sync passed on branch `codex/realtime-translator-closeout`.
- Runtime audio behavior still depends on selecting the correct input source (`System` for computer audio, `Mic` for microphone) and valid Azure credentials for cloud mode.

## 0.1.3 - Spanish Source Language and Compact Local Layout

Date: 2026-05-04

### Frontend

- Reduced subtitle row padding and stream spacing so more subtitle history fits in the monitor.
- Changed subtitle text to fixed source/translation sizes; short and long subtitles no longer use different length-based font sizes.
- Increased the compact English source subtitle default from 12px to 13px for readability.
- Updated the UI editor subtitle-size defaults for the compact subtitle layout.
- Added a Local Latency control with Low and Steady presets; Low selects a 2s local chunk.
- Split subtitle rendering by engine: Azure keeps the existing single bilingual monitor, while local engines use separate English live transcript and Chinese translation monitors.
- Local English monitor now keeps recent stable English context and one current draft row instead of showing only the latest draft.

### Backend

- Reworked local mode around a `LocalUtteranceAggregator`: ASR chunks update a continuous English utterance row, and only ready utterances are translated into Chinese.
- Low latency local runs with shorter overlap and smaller audio queues while preserving ready translation jobs so completed sentences are not dropped.

### Product

- Added Spanish-to-Chinese alongside the existing English-to-Chinese workflow.
- Added a source language selector on the main Subtitle Studio toolbar.
- Kept Azure Cloud usable as the primary route even when local `faster-whisper` dependencies are not ready on Windows.

### Backend

- Allowed `spa_Latn` source language through runtime config instead of forcing English.
- Mapped Spanish local ASR to Whisper `es` and multilingual `base` / `small` models.
- Mapped Azure Spanish mode to `es-ES -> zh-Hans`.
- Added Argos, MarianMT, and NLLB routing for Spanish-to-Chinese local translation.
- Delayed importing `faster-whisper` until local ASR is selected, so Azure-first startup no longer hard-fails on missing local ASR packages.

### Documentation

- Updated README and architecture notes to explain the Azure-first startup path and the lazy local-ASR dependency load.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- Spanish config mapping check passed for `spa_Latn -> es-ES`, Whisper `es`, and multilingual ASR model selection.
- Local runtime smoke test passed for `GET /` and `GET /api/health` on `http://127.0.0.1:8000`.
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
- Main page now loads saved editor choices from browser `localStorage` using the `subtitleStudioUiThemeCompact20260502` key.
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
