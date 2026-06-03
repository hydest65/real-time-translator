# Release Notes

## 0.3.1-notes-quality-compressed-upload - Richer Meeting Notes and Lossless Upload Compression

Date: 2026-06-04

### Product

- Improved post-meeting notes so important topics are expanded with concrete discussion points, examples, numbers, risks, decisions, open questions, and next steps supported by the transcript.
- Preserved the original WAV as the local recording archive while allowing smaller lossless FLAC uploads for cloud meeting-notes processing.
- Added optional meeting context fields in the Notes panel for title, people, keywords, and background so the notes model can resolve ambiguous references more reliably.

### Technical

- Added `backend/notes_quality.py` for a second-pass Ollama notes rewrite over generated minutes plus the full transcript.
- Wired topic-level refinement into both Aliyun Tingwu cloud notes and local post-meeting notes before Markdown/DOCX output is written.
- Saved accepted pre-rewrite drafts as `*.minutes.raw.md` for review and rollback.
- Added Tingwu upload FLAC compression, cached `recordings/*.upload.flac` reuse, ffmpeg diagnostics, and fallback to original WAV when compression is unavailable or not beneficial.
- Added `.env.example` controls for notes rewrite and Tingwu upload compression.

### UI

- Added compact Notes panel context inputs without changing the Start/End Meeting flow.
- Added `compressing` and `refining` progress stages so long note builds show what the backend is doing.

### Verification

- Python syntax checks passed for `backend/notes_quality.py`, `backend/main.py`, and `backend/aliyun_tingwu.py`.
- Frontend JavaScript syntax check passed for `frontend/app.js` with the bundled Codex Node runtime.
- Prompt smoke test passed for the topic-level rewrite instructions.
- Tail-whitespace scan passed for the changed code and documentation files.
- `git diff --check` passed with GitHub Desktop's bundled Git.

## 0.3.0-funasr-streaming-live-window - Local Chinese FunASR Streaming Subtitles

Date: 2026-06-03

### Product

- Added a dedicated local Chinese realtime subtitle path based on FunASR Paraformer streaming.
- Kept the realtime goal focused on low-latency Chinese ASR instead of post-meeting translation quality.
- Changed End Meeting behavior so ending a live session saves/stops recording only; meeting notes are built manually from the notes tools.
- Preserved System audio as the default test path for local Chinese meeting/video audio.

### UI

- Added explicit startup feedback in the Chinese subtitle pane while FunASR connects, loads the model, and starts listening.
- Reworked realtime Chinese display into a recent live subtitle window instead of showing the entire accumulated transcript as one machine-like paragraph.
- Added live subtitle line wrapping and status styling for FunASR so short streaming updates feel closer to natural captions.
- Updated frontend asset versioning to `funasr-live-window-20260603`.

### Technical

- Added `asr/funasr_streaming.py`, `asr/audio_capture.py`, and `asr/subtitle_state.py` for PCM16 16 kHz mono chunk streaming, queue-limited capture, streaming cache reuse, partial/final subtitle state, and low-latency WebSocket events.
- Added FastAPI WebSocket `/ws/asr/funasr` for FunASR streaming messages with `partial`, `final`, `status`, and `error` event types.
- Added FunASR/model download dependencies through `funasr`, `modelscope`, and `huggingface-hub`.
- Improved partial subtitle merging so FunASR's short incremental fragments accumulate without replacing the full current caption.
- Tuned CPU fallback for stability with 800 ms chunks, `[5, 10, 5]` chunk size, queue size 3, and short-phrase partial updates.
- Added runtime logging for chunk inference time, latency, RTF, model/device load, and dropped stale chunks.

### Verification

- Frontend JavaScript syntax check passed for `frontend/app.js` with the bundled Codex Node runtime.
- Python syntax checks passed for `backend/main.py`, `asr/subtitle_state.py`, and the FunASR streaming modules.
- `git diff --check` passed for the candidate code and docs.
- Runtime smoke test passed for `GET /` on port `8000`.
- FunASR route registration was verified for `/ws/asr/funasr`.
- Current local limitation: the active virtual environment still has CPU-only Torch, so FunASR does not use the NVIDIA GPU until CUDA PyTorch is installed.

## 0.2.1-compact-diagnostics-draft-tape - Compact UI, Diagnostics, and Stable Draft Captions

Date: 2026-05-30

### Product

- Simplified the main UI into a more compact, icon-forward operating surface while preserving the large subtitle workspace.
- Added a diagnostics monitor page for backend health, cloud/local notes readiness, meeting-notes progress, quick checks, and recent recordings.
- Kept tester-facing meeting-notes controls provider-neutral: notes engine is shown as `Cloud` / `Local`, and upload routing is controlled by configuration instead of a visible upload-path selector.
- Preserved Tencent Relay as the default private upload bridge for cloud meeting notes.

### UI

- Replaced oversized or inconsistent lower-panel buttons with the same soft capsule style used elsewhere.
- Converted dense Cloud Usage labels to icon-first counters with hover labels, reducing sidebar width pressure.
- Added a small monitor icon that opens diagnostics in a separate tab so checking health does not stop the active subtitle session.
- Reworked local English draft display into a one-line visual tape that fills to the end of the row before restarting from the left edge.

### Technical

- Added `frontend/diagnostics.html`, `frontend/diagnostics.css`, and `frontend/diagnostics.js`.
- The diagnostics live-socket test opens and closes a WebSocket without starting a caption session.
- Added `scripts/translation-quality-preview.py` for offline comparison of direct translation, stabilized English windows, and optional local `qwen3:14b` polishing.
- Versioned frontend assets with `draft-visual-tape-20260530` so browser refreshes load the draft subtitle changes.

### Verification

- Backend Python compile/import checks passed.
- Frontend JavaScript syntax checks passed for `frontend/app.js`, `frontend/ui-editor.js`, and `frontend/diagnostics.js`.
- `scripts/translation-quality-preview.py` syntax check passed.
- `git diff --check` passed.
- Runtime smoke test passed for `GET /api/health` and `GET /static/diagnostics.html` on port `8000`.
- Secret scan found placeholders only and no live Aliyun AccessKey, Tingwu AppKey, relay IP, or Azure secret in candidate committed paths.

## 0.2.0-aliyun-tingwu-qwen-notes - Aliyun Cloud Notes and Qwen Local Refinement

Date: 2026-05-30

### Product

- Added Aliyun Tingwu as the selected cloud meeting-notes path, with Tencent Relay supported as the default private upload bridge.
- Added compact UI controls for meeting-notes engine choice, progress display, diagnostics, and quick access to recordings / minutes folders.
- Kept tester-facing upload-path details out of the main UI; upload routing is controlled by local environment configuration.
- Set the local meeting-notes refinement model direction to Ollama `qwen3:14b` after Gemma and Phi test models were removed locally.

### Technical

- Added Aliyun Tingwu task submission, polling, transcript/minutes rendering, raw result capture, and temporary audio cleanup.
- Added Tencent Relay upload support with byte-level progress reporting and post-task deletion.
- Added `.env.example` settings for local Ollama notes refinement, Aliyun Tingwu, OSS, and relay cleanup.
- Added Aliyun SDK requirements and ignored backend runtime log files.

### Verification

- Python syntax checks passed for `backend/main.py`, `backend/aliyun_tingwu.py`, core backend modules, and `scripts/process-recording.py`.
- Backend import check passed.
- Frontend JavaScript syntax checks passed for `frontend/app.js` and `frontend/ui-editor.js` with the bundled Codex Node runtime.
- `git diff --check` passed.
- Secret scan found placeholders and environment-variable names only; live Aliyun, Azure, relay IP, and AppKey values were not present in committed paths.

## 0.1.12-cloud-branding-notes-fallback - Provider-Neutral UI and Stable Meeting Notes

Date: 2026-05-28

### Product

- Removed provider-specific wording from tester-facing UI. The app now presents the live route, usage panel, status messages, and settings as `Cloud` / `Cloud Usage` / `Cloud Sync`.
- Added Chinese meeting speech as a selectable input language while keeping meeting notes output bilingual, with English first and Chinese reading copy second.
- Reworked local hardware choices into three tester-friendly abbreviation tiers: `iGPU`, `dGPU`, and `HP`, assuming 16GB RAM and choosing the tier by graphics/compute class.
- Kept cloud usage remaining-time sync tied to the configured monthly quota, now set for a 5-hour free monthly allowance.

### Technical

- Added `/api/cloud-usage` as the provider-neutral usage endpoint while keeping `/api/azure-usage` as a compatibility alias.
- Reduced provider leakage in frontend status rendering with a display-layer neutralizer for backend and SDK errors.
- Changed public config payloads to expose `cloud_*` fields instead of returning the full runtime config to the browser.
- Fixed post-meeting local fallback on CUDA-incomplete machines by defaulting meeting-notes ASR to CPU unless `POST_MEETING_ASR_DEVICE` is explicitly set to `cuda` or `auto`.
- Kept generated recordings and notes under `recordings/`, which remains ignored by Git.

### UI

- Updated the top subtitle, speech selector, engine selector, usage panel, delay hints, and progress messages to use neutral cloud wording.
- Preserved the compact left-panel scroll behavior so Meeting Notes and Delay Hint remain reachable on shorter screens.
- Versioned frontend assets with `cloud-branding-20260528` so browser refresh picks up the new labels.

### Verification

- Python syntax checks passed for `backend/main.py`, `backend/cloud_speech.py`, and `scripts/process-recording.py`.
- Frontend JavaScript syntax check passed for `frontend/app.js` with the bundled Node runtime.
- Local runtime smoke test passed for `GET /` on port `8000`.
- `GET /api/cloud-usage` returned a configured account-level usage payload with neutral `source` and `metric` fields.
- `GET /api/config` now returns provider-neutral public config fields.
- A real recording, `rec-0528-131932.wav`, successfully generated `rec-0528-131932.minutes.docx` after the CPU fallback fix, and `/api/open-latest-minutes` opened the Word file.

### Known Limitations

- The internal environment variable names and some internal code identifiers still use the cloud provider's original naming so existing local configuration keeps working.
- Cloud batch speaker separation still requires a configured Blob/SAS batch-storage path; otherwise notes fall back to local transcription without verified speaker separation.
- CPU meeting-notes fallback is slower than CUDA, but avoids the `cublas64_12.dll` failure on tester machines without a complete CUDA runtime.

## 0.1.11-local-t600 - Azure Usage Sync Panel

Date: 2026-05-25

### Product

- Added an Azure Usage panel to the left runtime sidebar.
- The panel shows current-session Azure time and local browser day/month estimates.
- The UI clearly labels local-only estimates so users do not confuse one machine's browser storage with account-wide Azure usage.

### Technical

- Added `GET /api/azure-usage` for optional Azure Monitor synchronization.
- The backend queries Azure Monitor `AudioSecondsTranslated` with a service principal when `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and `AZURE_SPEECH_RESOURCE_ID` are configured.
- Azure Monitor usage responses are cached for 60 seconds.
- `.env.example` now documents Azure Monitor usage-sync variables and optional monthly seconds budget.

### UI

- Reduced usage-card label sizing and shortened labels to prevent two-line wrapping in the compact sidebar.
- The panel switches between local estimate labels and Cloud Day / Cloud Month labels depending on whether Azure Monitor sync is configured.

### Verification

- Backend Python syntax check passed for `backend/main.py`.
- Frontend JavaScript syntax check passed for `frontend/app.js`.
- Local runtime smoke test passed for `GET /` on port `8001`.
- `GET /api/azure-usage` safely returned `configured=false` before Azure Monitor credentials were added.

### Known Limitations

- Azure Speech API keys can run live translation, but cannot read Azure Monitor metrics.
- Account-level cloud usage sync requires a service principal with `Monitoring Reader` access to the Speech resource.
- Until those Azure Monitor variables are configured, day/month numbers remain browser-local estimates.

## 0.1.10-local-t600 - Guided Meeting Flow and Bilingual Word Notes

Date: 2026-05-17

Local-only note: this version is intended for the NVIDIA T600 Laptop GPU machine. Keep it on a dedicated T600 branch unless the project is intentionally converted into a multi-machine profile system.

### Beginner Meeting Flow

- Reworked the main Subtitle Studio controls around a clearer meeting lifecycle: `Start Meeting`, `End Meeting`, then `Open Bilingual Notes`.
- Kept the UI labels in English while simplifying the visible control surface for first-time users.
- Moved lower-frequency tuning controls into `Advanced Settings` so the main workflow stays focused on the next obvious action.
- Kept `End Meeting` visible during live use, because ending the meeting is the moment that triggers post-meeting note generation.

### Realtime Status

- Added a delay hint panel so the user can distinguish cloud setup problems from live caption delay.
- Fixed the misleading state where subtitles were moving but the side panel could still imply that captions were unavailable.
- Updated live subtitle receipt tracking so active captions can report a healthy live state instead of a stale warning.
- Added adaptive local audio chunking: continuous speech still uses the selected max chunk window, while speech followed by a short quiet tail flushes earlier for faster local ASR feedback.
- Added a shared terminology hotword loader for Azure phrase lists, local faster-whisper prompts/hotwords, and post-meeting faster-whisper processing.
- Added a contextual translation buffer that briefly holds short or dependent local utterances, merges nearby context when possible, and flushes quickly when no follow-up arrives.
- Added a stricter default RMS noise gate for `System` input so loopback silence and weak residual audio are less likely to reach local Whisper ASR.
- Switched live local `System` defaults back toward stability: fixed chunks instead of adaptive short flushes, contextual translation merging disabled by default, and local ASR prompt/hotword bias disabled by default.

### Meeting Notes

- Changed post-meeting output from Markdown-first to Word-first for normal use.
- Generated notes now use one `.docx` file with the English professional minutes first and the Chinese reading version second.
- Added a transcript cleanup step for post-meeting processing so raw ASR markup such as language and emotion tags does not leak into the minutes.
- Added a content-quality guard: when the captured transcript is too short or noisy, the minutes clearly say that decisions, actions, and risks cannot be inferred safely instead of inventing them.
- Added topic segmentation to meeting notes. The notes now include a Topic Timeline that creates new topic sections when the transcript changes subject, moves to a new agenda item, or has a meaningful time gap.
- Added a visible meeting-notes progress bar backed by `GET /api/process-recording-progress`, so long post-meeting processing shows upload, transcription, summary, and completion stages.
- Added Azure Batch Transcription as the cloud meeting-notes path. When the live engine is Azure and Blob SAS storage is configured, post-meeting notes use Azure cloud transcription with speaker separation; local engines continue to use local faster-whisper without speaker separation.
- Added a safe fallback when Azure Batch storage is not configured: cloud mode explains the missing Blob SAS setup and uses local notes instead of failing.
- Added chunked faster-whisper transcription for long recordings, with a guard against very short chunks that degrade ASR context and increase repetition.

### Verification

- Frontend JavaScript syntax check passed.
- Backend and recording-processing Python compile checks passed.
- Latest minutes lookup was verified to prefer `.docx` files over `.md` files.
- A sample `.docx` minutes file was rendered successfully, with English on the first page and Chinese on the second page.
- Azure Fast Transcription was tested but rejected diarization on the current endpoint, so Azure Batch remains the selected cloud diarization path.
- Local fallback routing was verified: Azure without `AZURE_BATCH_CONTAINER_SAS_URL` falls back to `faster-whisper`, while local engines always stay local.
- Git diff whitespace check passed before publish.

## 0.1.9-local-t600 - Local ASR Presets for 4GB GPU

Date: 2026-05-08

Local-only note: this tuning is for the NVIDIA T600 Laptop GPU machine. Keep it separate from the GitHub/5070Ti baseline unless the project is intentionally changed to support multiple machine profiles.

### Local ASR

- Added an `ASR Preset` control for local mode.
- `Fast` selects `base.en + int8`.
- `Balanced` selects `small.en + int8` and remains the recommended default for the NVIDIA T600 Laptop GPU with 4GB VRAM.
- `Accurate` selects `small.en + int8_float16` for a higher-quality local experiment when enough GPU memory is free.
- Added `medium.en` to the manual ASR model dropdown for experiments, without making it a default preset.
- Allowed the frontend to send `asr_compute_type` instead of hardcoding local ASR to `int8`.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- CTranslate2 detects one CUDA device and supports `int8`, `int8_float16`, `float16`, and `float32`.
- Torch remains CPU-only in this environment, so Transformers-based MarianMT/NLLB GPU acceleration is still not the recommended optimization path.

## 0.1.8 - Local ASR Quality Tuning

Date: 2026-05-08

### Local ASR

- Changed the default local ASR model from `base.en` to `small.en` for better English meeting transcription.
- Kept `base.en` as the faster manual option in the UI.
- Retuned faster-whisper decoding from single-candidate fastest mode to `beam_size=3` / `best_of=3`.
- Enabled previous-text conditioning inside the ASR call and added a meeting-domain prompt / hotwords list for common technical terms.
- Made VAD slightly less aggressive so speech is less likely to be clipped at short pauses.
- Added light repetition controls to reduce repeated phrases from overlapping chunks.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- Runtime live-audio quality still needs a fresh local test after restarting Subtitle Studio.

## 0.1.7 - Local Sentence Aggregation Tuning

Date: 2026-05-08

### Local Subtitles

- Retuned local Low mode from very short ASR fragments toward fuller sentence aggregation.
- Changed Low mode to use a `2s` chunk, `0.3s` overlap, queue size `2`, `0.9s` sentence pause, and a longer word/time threshold before Chinese translation.
- Changed Steady mode to use a `3s` chunk, `0.5s` overlap, queue size `2`, `1.2s` sentence pause, and a more conservative sentence threshold.
- Added backend protection so very short idle fragments are held briefly instead of being translated immediately.
- Raised the punctuation-based sentence completion threshold so unreliable local ASR punctuation does not split tiny fragments too early.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- Aggregator simulation confirmed a short fragment such as `goes up.` is held and merged with following text before translation.

## 0.1.6 - Local Secret Hygiene Closeout

Date: 2026-05-08

### Security

- Removed an accidental local text dump containing account/session data from the project workspace.
- Added the accidental dump filename to `.gitignore` so it is less likely to be synced or committed later.
- Reconfirmed that `.env` files remain ignored while `.env.example` stays shareable.

### Documentation

- Updated the project closeout pointer in `README.md`.
- Reinforced the closeout skill with a reminder not to keep copied browser session dumps, access tokens, or account exports in the repository.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- Git CLI sync/status check could not run in this shell because `git` is not available in `PATH`.

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
