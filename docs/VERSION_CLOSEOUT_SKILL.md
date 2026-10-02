# Real-Time Translator Version Closeout Skill

Use this local project skill whenever closing a version of `real_time_translator`.

## Core Continuation Docs

Read these files early when continuing product, architecture, UI, meeting-notes, or closeout work:

- `docs/PRODUCT_REQUIREMENTS.md`: product goal, target users, MVP scope, fast-only mode, and out-of-scope items.
- `docs/TECHNICAL_ARCHITECTURE.md`: Cloud route, local fallback route, meeting-notes routes, backend modules, and environment variables.
- `docs/UI_STYLE.md`: compact Subtitle Studio layout, subtitle monitor behavior, scrolling rules, and visual direction.
- `docs/RELEASE_NOTES.md`: current released baseline and verification notes.
- `README.md`: user-facing setup, run, and operations notes.

## Closeout Steps

1. Inspect current implementation:
   - `docs/PRODUCT_REQUIREMENTS.md`
   - `docs/TECHNICAL_ARCHITECTURE.md`
   - `docs/UI_STYLE.md`
   - `docs/RELEASE_NOTES.md`
   - `docs/QA_CHECKLIST.md`
   - `backend/config.py`
   - `backend/main.py`
   - `backend/cloud_speech.py`
   - `backend/audio_capture.py`
   - `backend/asr.py`
   - `backend/translator.py`
   - `scripts/process-recording.py`
   - `scripts/translation-quality-preview.py`
   - `frontend/index.html`
   - `frontend/style.css`
   - `frontend/app.js`
   - `frontend/ui-editor.html`
   - `frontend/ui-editor.css`
   - `frontend/ui-editor.js`
   - `frontend/diagnostics.html`
   - `frontend/diagnostics.css`
   - `frontend/diagnostics.js`
   - `README.md`

2. Confirm the active architecture:
   - Cloud mode is the primary low-latency path in tester-facing UI.
   - Remote tester Cloud mode captures audio in the tester browser and streams 16 kHz PCM over WebSocket to the center backend; the backend keeps the speech key private.
   - The center backend enforces the configured monthly Cloud quota, currently 5 hours by default.
   - Tester-facing labels remain provider-neutral: use `Cloud`, `Cloud Usage`, and neutral status/error text.
   - The main toolbar no longer exposes mode/settings/diagnostics controls; keep it focused on input, language, Start, End, and Notes.
   - Local ASR/translation remains a fallback path.
   - Local Chinese realtime subtitles can use FunASR streaming through `/ws/asr/funasr`.
   - MiniMax polishing is removed unless the user explicitly asks to reintroduce it.
   - Fast/direct translation is the only active mode.
   - The browser UI is the main operating surface.
   - Diagnostics opens separately and must not replace or stop the active subtitle page.
   - Cloud usage shows current-session timing, browser-local estimates, and optional account-level sync.
   - English/Spanish local subtitles keep the split reading model: stable source context and complete Chinese translation.
   - Meeting notes are Word-first: English professional minutes first, Chinese reading version second, in one `.docx`.
   - Cloud meeting notes can use Aliyun Tingwu/Tencent Relay/OSS or Azure Batch when configured; local engines use local post-meeting processing.
   - Ollama `qwen3:14b` is a post-meeting refinement model only, not a realtime subtitle model.

3. Update documentation:
   - `README.md`
   - `docs/PRODUCT_REQUIREMENTS.md`
   - `docs/TECHNICAL_ARCHITECTURE.md`
   - `docs/UI_STYLE.md`
   - `docs/RELEASE_NOTES.md`
   - `docs/QA_CHECKLIST.md`
   - `docs/VERSION_CLOSEOUT_SKILL.md`

4. Run safe checks:
   - Python compile check for backend.
   - Backend import check.
   - JavaScript syntax check for `frontend/app.js`, `frontend/ui-editor.js`, and `frontend/diagnostics.js` when Node is available.
   - `scripts/translation-quality-preview.py` syntax check when that script changed.
   - `git diff --check` when Git is available.
   - Secret scan candidate committed paths for real API keys, service-principal secrets, relay IPs, SAS URLs, and app keys.
   - Runtime smoke test when credentials and audio devices are available.

5. Report closeout:
   - product changes
   - technical changes
   - UI changes
   - verification result
   - GitHub sync result or blocker
   - known limitations
   - next recommended step

## Version Discipline

- Do not commit API keys, service-principal secrets, relay endpoints with credentials, SAS URLs, AppKeys, copied browser sessions, account exports, access tokens, or temporary login dumps.
- Do not reintroduce MiniMax, Balanced, or Quality modes unless explicitly requested.
- Do not split long Cloud final subtitles purely by time.
- Preserve the internal subtitle monitor scrollbar and scroll-review behavior.
- Preserve the Cloud subtitle monitor scrollbar and scroll-review behavior.
- Preserve the English/Spanish local split reading model: stable source context and complete Chinese translation.
- Preserve local Chinese FunASR live-window behavior: visible realtime text should be recent and readable, while full transcript accumulation remains internal.
- Preserve the guided meeting flow: `Start Meeting`, `End Meeting`, then manual notes building through the Notes tools.
- Preserve Word-first bilingual notes: English minutes first, Chinese reading version second, in one `.docx` file.
- Preserve provider-neutral UI wording for testers: use `Cloud` in visible labels, status messages, usage panel text, and common errors.
- Preserve remote tester key hygiene: never distribute `.env` or speech keys; use a hosted center backend plus HTTPS access.
- Preserve lightweight default installs: keep local model packages in `backend/requirements-local.txt`, not in the default `backend/requirements.txt`.
- Keep private `.env`, `backend/glossary.csv`, recordings, generated notes, model caches, browser session exports, and temporary auth dumps out of Git.
- Keep true speaker diarization as a future feature unless explicitly implemented.
