# Product Requirements

## Product Goal

Build a Windows real-time subtitle translator for meetings. The first usable version listens to microphone, browser audio, or system audio, recognizes English, Spanish, Japanese, or Chinese speech, translates or transcribes it into Simplified Chinese, and displays subtitles in a local or hosted browser window.

## Target Users

- Engineering project meetings
- Pharmaceutical facility and cleanroom design meetings
- Chemical process, utilities, HVAC, MEP, BIM, validation, and commissioning reviews
- Teams meetings where the user needs low-latency Chinese subtitles

## Current MVP Scope

- Local or center-hosted browser subtitle window served by FastAPI.
- Local single-user runs can still capture server-machine `System` or `Mic` audio. Remote tester runs use the tester's browser audio capture and stream 16 kHz PCM audio back to the center backend so the cloud key stays private.
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
- Cloud usage panel for current-session timing, account-level synchronization, and a centrally enforced monthly cloud quota.
- Default cloud live-translation quota is 5 hours per month, reset on the first day of each UTC month.
- Visual UI editor for local browser-side tuning of colors, subtitle size, panel width, corner radius, and background decoration.
- Diagnostics monitor page remains available by URL for backend health, cloud notes readiness, local notes readiness, meeting-notes progress, recent recordings, and quick connection checks, but it is no longer surfaced as a main-toolbar button.
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
- User can choose English, Spanish, Japanese, or Chinese as the source language before starting.
- Cloud mode should feel close to real time during normal speech.
- Local Low latency mode should keep ASR responsive while stable source context and Chinese complete sentences stay readable as continuous text flows.
- Local Chinese FunASR mode should show startup progress, begin emitting partial captions without waiting for full sentences, and keep the visible live window readable instead of displaying the entire raw transcript as one paragraph.
- The interface should not show MiniMax, Balanced, or Quality mode controls.
- The status lamp should be visible when stopped and gently pulse after Start.
- In Cloud mode, user can scroll subtitle history inside the subtitle monitor while new subtitles continue to arrive.
- In local mode, user can scan English live transcript and Chinese translations separately.
- Local MarianMT and NLLB do not need to match Azure realtime behavior on this machine; they are comparison paths rather than the primary recommended route.
- User can open `/static/ui-editor.html`, tune the visual style, save it locally, and see the saved style on the main subtitle page.
- User can open `/static/diagnostics.html` directly when backend diagnostics are needed.
- User can end a meeting, build bilingual Word notes from the Notes tools, and open the generated document without manually looking for a Markdown file.
- User can see Cloud monthly quota usage and is blocked from starting new Cloud sessions when the center backend reaches the configured limit.
- Tester-facing UI should avoid naming the underlying cloud provider.
