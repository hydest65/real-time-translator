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
- Audio input defaults to `System` for meeting audio, preferring loopback from the current default Windows playback device and falling back to Stereo Mix / monitor input when needed. `Mic` remains available for room or headset microphone audio.
- Provider-neutral Cloud speech translation as the main low-latency route in the tester-facing UI.
- Source language selector for English, Spanish, or Chinese meeting speech, with Simplified Chinese translation and bilingual meeting-notes output.
- Local fallback engines for offline/private testing:
  - faster-whisper `base.en` / `small.en` for English
  - multilingual faster-whisper `base` / `small` automatically for Spanish
  - FunASR Paraformer streaming for local Chinese realtime subtitles
  - Argos Translate as the recommended local realtime engine
  - MarianMT for local comparison / quality testing
  - NLLB for local comparison / non-realtime use
- Local low-latency preset that uses shorter audio chunks, keeps source ASR responsive, and translates Chinese after sentence completion.
- Fixed subtitle monitor with internal scrolling history for Azure.
- Two-mode subtitle workspace: Azure keeps one bilingual monitor; local mode uses source context and Chinese translation panes, while local Chinese FunASR uses a recent Chinese live caption window.
- Real-time live row plus final subtitle history.
- Full-session final transcript capture for post-meeting export.
- Bilingual Word meeting-minutes export with English professional minutes first and Chinese reading version second in the same document.
- Local WAV recording for optional post-meeting speaker diarization.
- Top-left red status lamp that remains visible when stopped and pulses while running.
- Cloud usage panel for current-session timing, browser-local day/month estimates, and optional account-level synchronization.
- Visual UI editor for local browser-side tuning of colors, subtitle size, panel width, corner radius, and background decoration.
- Diagnostics monitor page for backend health, cloud notes readiness, local notes readiness, meeting-notes progress, recent recordings, and quick connection checks.
- Lightweight paragraph turn detection by pause interval.

## Translation Mode

- `Fast` is the only active mode.
- Cloud mode streams live bilingual subtitles directly from the configured cloud speech route.
- Local fallback shows ASR drafts immediately, then translates complete ready utterances through a short contextual buffer rather than a slower polishing or quality-mode path.
- Local fallback shows stable source context as a continuous text pane that fills first and then scrolls, then sends complete Chinese sentence translations to a continuous Chinese pane.
- Local Chinese speech uses FunASR streaming partials in the Chinese monitor. The realtime pane favors quick readable captions; richer punctuation and polishing belong to later final/notes processing.

## Out Of Scope For This Version

- True speaker diarization or voiceprint recognition.
  - The current export may label pause-based turns, but it does not verify speaker identity.
  - Optional post-meeting diarization can create anonymous speaker clusters, but naming speakers remains manual.
- OBS transparent subtitle overlay.
- Electron desktop packaging.
- SRT/TXT export.
- TTS voice playback.
- Multi-user cloud workspace.
- Production account management.

## Success Criteria

- User can open `http://127.0.0.1:8000`, click Start, and see live bilingual subtitles.
- User can choose English or Spanish as the source language before starting.
- Cloud mode should feel close to real time during normal speech.
- Local Low latency mode should keep ASR responsive while stable source context and Chinese complete sentences stay readable as continuous text flows.
- Local Chinese FunASR mode should show startup progress, begin emitting partial captions without waiting for full sentences, and keep the visible live window readable instead of displaying the entire raw transcript as one paragraph.
- The interface should not show MiniMax, Balanced, or Quality mode controls.
- The status lamp should be visible when stopped and gently pulse after Start.
- In Cloud mode, user can scroll subtitle history inside the subtitle monitor while new subtitles continue to arrive.
- In local mode, user can scan English live transcript and Chinese translations separately.
- Local MarianMT and NLLB do not need to match Azure realtime behavior on this machine; they are comparison paths rather than the primary recommended route.
- User can open `/static/ui-editor.html`, tune the visual style, save it locally, and see the saved style on the main subtitle page.
- User can open `/static/diagnostics.html` from the compact monitor icon without stopping the main live translation page.
- User can end a meeting, build bilingual Word notes from the Notes tools, and open the generated document without manually looking for a Markdown file.
- User can see whether Cloud usage is only a browser-local estimate or backed by account-level sync.
- Tester-facing UI should avoid naming the underlying cloud provider.
