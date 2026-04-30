# Real-Time Translator Version Closeout Skill

Use this local project skill whenever closing a version of `real_time_translator`.

## Closeout Steps

1. Inspect current implementation:
   - `backend/config.py`
   - `backend/main.py`
   - `backend/cloud_speech.py`
   - `backend/text_polisher.py`
   - `backend/audio_capture.py`
   - `backend/asr.py`
   - `backend/translator.py`
   - `frontend/index.html`
   - `frontend/style.css`
   - `frontend/app.js`
   - `README.md`

2. Confirm the active architecture:
   - Azure Cloud is the primary low-latency path.
   - Local ASR/translation remains a fallback path.
   - MiniMax polishing is optional and asynchronous.
   - The browser UI is the main operating surface.

3. Update documentation:
   - `README.md`
   - `docs/PRODUCT_REQUIREMENTS.md`
   - `docs/TECHNICAL_ARCHITECTURE.md`
   - `docs/UI_STYLE.md`
   - `docs/RELEASE_NOTES.md`
   - `docs/QA_CHECKLIST.md`

4. Run safe checks:
   - Python compile check for backend.
   - Backend import check.
   - JavaScript syntax check when Node is available.
   - Runtime smoke test when credentials and audio devices are available.

5. Report closeout:
   - product changes
   - technical changes
   - UI changes
   - verification result
   - known limitations
   - next recommended step

## Version Discipline

- Do not commit API keys.
- Do not treat MiniMax as required for live subtitles.
- Do not block Azure live output while waiting for polishing.
- Do not split long Azure final subtitles purely by time.
- Preserve the internal subtitle monitor scrollbar and scroll-review behavior.
- Keep true speaker diarization as a future feature unless explicitly implemented.

