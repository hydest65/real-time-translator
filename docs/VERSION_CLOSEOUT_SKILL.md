# Real-Time Translator Version Closeout Skill

Use this local project skill whenever closing a version of `real_time_translator`.

## Core Continuation Docs

Read these three files early when continuing product, architecture, or UI work:

- `docs/PRODUCT_REQUIREMENTS.md`: product goal, target users, MVP scope, fast-only mode, and out-of-scope items.
- `docs/TECHNICAL_ARCHITECTURE.md`: Azure cloud route, local fallback route, backend modules, and environment variables.
- `docs/UI_STYLE.md`: compact Subtitle Studio layout, subtitle monitor behavior, scrolling rules, and visual direction.

## Closeout Steps

1. Inspect current implementation:
   - `docs/PRODUCT_REQUIREMENTS.md`
   - `docs/TECHNICAL_ARCHITECTURE.md`
   - `docs/UI_STYLE.md`
   - `backend/config.py`
   - `backend/main.py`
   - `backend/cloud_speech.py`
   - `backend/audio_capture.py`
   - `backend/asr.py`
   - `backend/translator.py`
   - `frontend/index.html`
   - `frontend/style.css`
   - `frontend/app.js`
   - `frontend/ui-editor.html`
   - `frontend/ui-editor.css`
   - `frontend/ui-editor.js`
   - `README.md`

2. Confirm the active architecture:
   - Azure Cloud is the primary low-latency path.
   - Local ASR/translation remains a fallback path.
   - MiniMax polishing is removed unless the user explicitly asks to reintroduce it.
   - Fast/direct translation is the only active mode.
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
- Do not reintroduce MiniMax, Balanced, or Quality modes unless explicitly requested.
- Do not split long Azure final subtitles purely by time.
- Preserve the internal subtitle monitor scrollbar and scroll-review behavior.
- Preserve the Azure subtitle monitor scrollbar and scroll-review behavior.
- Preserve the local two-level reading model: English live transcript above and polished Chinese translation below.
- Keep true speaker diarization as a future feature unless explicitly implemented.
