# Release Notes

## 0.1.0 - Working Prototype Closeout

Date: 2026-04-29

### Product

- Completed a usable local browser subtitle studio.
- Main workflow supports microphone or system audio, Azure streaming translation, and bilingual subtitle display.
- Added optional MiniMax domain polishing for engineering, pharmaceutical facility, cleanroom, HVAC, utilities, validation, commissioning, and modular construction meetings.

### Backend

- Added Azure Speech Translation streaming route.
- Kept local fallback route with faster-whisper and local translation engines.
- Added asynchronous MiniMax polish queue for final subtitle replacement.
- Added lightweight paragraph turn detection.
- Added performance payloads for subtitle events.

### Frontend

- Redesigned into a compact SaaS-style Subtitle Studio.
- Added fixed subtitle monitor.
- Added internal subtitle history scrolling.
- Added bottom auto-follow behavior that pauses when the user scrolls upward.
- Added minute-second timestamp formatting.

### Verification

- Python backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed.
- Full live audio verification still depends on local microphone/system audio and active Azure credentials.

### Known Limitations

- System audio depends on Windows exposing a usable monitor input or Stereo Mix.
- Azure credentials and MiniMax credentials must be provided through environment variables.
- MiniMax polishing can fail or be delayed; Azure translation remains the fallback.
- Current paragraph detection is pause-based, not true speaker diarization.
- Local MarianMT still uses Transformers, not CTranslate2 int8.

