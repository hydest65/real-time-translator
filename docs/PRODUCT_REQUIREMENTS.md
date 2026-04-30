# Product Requirements

## Product Goal

Build a Windows real-time subtitle translator for meetings. The first usable version listens to microphone or system audio, recognizes English or Spanish speech, translates it into Simplified Chinese, and displays bilingual subtitles in a local browser window.

## Target Users

- Engineering project meetings
- Pharmaceutical facility and cleanroom design meetings
- Chemical process, utilities, HVAC, MEP, BIM, validation, and commissioning reviews
- Teams meetings where the user needs low-latency Chinese subtitles

## Current MVP Scope

- Local browser subtitle window served by FastAPI.
- Audio input from microphone, with experimental system audio input when Windows exposes a monitor or Stereo Mix device.
- Azure Speech Translation as the main low-latency route.
- Source language selector for English or Spanish, with Simplified Chinese as the fixed target language.
- Local fallback engines for offline/private testing:
  - faster-whisper `base.en` / `small.en` for English
  - multilingual faster-whisper `base` / `small` automatically for Spanish
  - Argos Translate
  - MarianMT
  - NLLB
- Fixed subtitle monitor with internal scrolling history.
- Real-time live row plus final subtitle history.
- Top-left red status lamp that remains visible when stopped and pulses while running.
- Visual UI editor for local browser-side tuning of colors, subtitle size, panel width, corner radius, and background decoration.
- Lightweight paragraph turn detection by pause interval.

## Translation Mode

- `Fast` is the only active mode.
- Azure Cloud streams live bilingual subtitles directly from Azure Speech Translation.
- Local fallback translates each ASR result immediately without delayed polishing or quality-mode buffering.

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
- User can choose English or Spanish as the source language before starting.
- Azure mode should feel close to real time during normal speech.
- The interface should not show MiniMax, Balanced, or Quality mode controls.
- The status lamp should be visible when stopped and gently pulse after Start.
- User can scroll subtitle history inside the subtitle monitor while new subtitles continue to arrive.
- User can open `/static/ui-editor.html`, tune the visual style, save it locally, and see the saved style on the main subtitle page.
