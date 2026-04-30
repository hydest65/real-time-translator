# Product Requirements

## Product Goal

Build a Windows real-time subtitle translator for meetings. The first usable version listens to microphone or system audio, recognizes speech, translates it into Simplified Chinese, and displays bilingual subtitles in a local browser window.

## Target Users

- Engineering project meetings
- Pharmaceutical facility and cleanroom design meetings
- Chemical process, utilities, HVAC, MEP, BIM, validation, and commissioning reviews
- Teams meetings where the user needs low-latency Chinese subtitles

## Current MVP Scope

- Local browser subtitle window served by FastAPI.
- Audio input from microphone, with experimental system audio input when Windows exposes a monitor or Stereo Mix device.
- Azure Speech Translation as the main low-latency route.
- Local fallback engines for offline/private testing:
  - faster-whisper `base.en` / `small.en`
  - Argos Translate
  - MarianMT
  - NLLB
- MiniMax optional final-subtitle polishing for domain terminology.
- Fixed subtitle monitor with internal scrolling history.
- Real-time live row plus final subtitle history.
- Lightweight paragraph turn detection by pause interval.

## Quality Modes

- `Fast`: Azure translation only. Lowest latency.
- `Balanced`: Azure translation appears immediately, then MiniMax can polish final lines if configured.
- `Quality`: final Chinese can wait for MiniMax, higher quality but higher risk of delay.

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
- Azure mode should feel close to real time during normal speech.
- Balanced mode should improve engineering/pharma terminology without blocking live subtitles.
- User can scroll subtitle history inside the subtitle monitor while new subtitles continue to arrive.

