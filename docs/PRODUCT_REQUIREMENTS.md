# Product Requirements

## Product Goal

Build a Windows real-time subtitle translator for meetings. The high-end local edition listens to microphone or system audio, recognizes English speech, translates it into Simplified Chinese, and displays bilingual subtitles in a local browser window.

## Target Users

- Engineering project meetings
- Pharmaceutical facility and cleanroom design meetings
- Chemical process, utilities, HVAC, MEP, BIM, validation, and commissioning reviews
- Teams meetings where the user needs low-latency Chinese subtitles

## Current MVP Scope

- Local browser subtitle window served by FastAPI.
- Audio input defaults to `System`, which prefers loopback from the current default Windows playback device and falls back to Stereo Mix / monitor input when needed. `Mic` remains available.
- High-end local English-to-Chinese as the main route.
- Azure Speech Translation as an optional comparison/fallback route.
- English source speech with Simplified Chinese as the fixed target language.
- Local fallback engines for offline/private testing:
  - faster-whisper `medium.en` by default on CUDA
  - `small.en` and `base.en` as lighter English-only options
  - Argos Translate as the recommended local realtime engine
  - MarianMT for local comparison / quality testing
  - NLLB for local comparison / non-realtime use
- Local low-latency preset that uses shorter audio chunks, shows live English ASR draft immediately, and translates Chinese after sentence completion.
- Two-level local subtitle workspace: continuous English live transcript above, continuous polished Chinese translation below.
- Local drafts update inline in the upper English text flow immediately; fuller translated utterances append to the lower Chinese text flow after sentence completion.
- Real-time live row plus final subtitle history.
- Top-left red status lamp that remains visible when stopped and pulses while running.
- Visual UI editor for local browser-side tuning of colors, subtitle size, panel width, corner radius, and background decoration.
- Lightweight paragraph turn detection by pause interval.

## Translation Mode

- `Fast` is the only active mode.
- Azure Cloud streams live bilingual subtitles directly from Azure Speech Translation.
- Local fallback translates each ASR result immediately without delayed polishing or quality-mode buffering.
- Local fallback shows English ASR drafts continuously in the upper pane, then translates fuller utterances into polished Chinese text in the lower pane.

## Out Of Scope For This Version

- True speaker diarization or voiceprint recognition.
- OBS transparent subtitle overlay.
- Electron desktop packaging.
- SRT/TXT export.
- TTS voice playback.
- Multi-user cloud workspace.
- Production account management.

## Success Criteria

- User can open `http://127.0.0.1:8000`, click Start, and see live bilingual subtitles.
- User can run the dedicated English-to-Chinese workflow without choosing a source language.
- Azure mode should feel close to real time during normal speech.
- Local Low latency mode should keep the upper English transcript responsive while lower Chinese output waits for fuller, less-fragmented utterances.
- The interface should not show MiniMax, Balanced, or Quality mode controls.
- The status lamp should be visible when stopped and gently pulse after Start.
- In Azure mode, user can scroll subtitle history inside the subtitle monitor while new subtitles continue to arrive.
- In local mode, user can scan continuous English live transcript above and continuous polished Chinese translation below.
- Local MarianMT and NLLB do not need to match Azure realtime behavior on this machine; they are comparison paths rather than the primary recommended route.
- User can open `/static/ui-editor.html`, tune the visual style, save it locally, and see the saved style on the main subtitle page.
