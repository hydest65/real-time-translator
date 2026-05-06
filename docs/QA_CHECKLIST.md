# QA Checklist

## Static Checks

Run from:

```powershell
cd path\to\real-time-translator
```

```powershell
.\.venv\Scripts\python.exe -m compileall backend
.\.venv\Scripts\python.exe -c "import backend.main; print('backend import ok')"
```

If Node is available:

```powershell
node --check frontend\app.js
node --check frontend\ui-editor.js
```

Current closeout result on 2026-05-04:

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- UI editor JavaScript syntax check passed with the bundled Node runtime.
- GitHub sync completed on branch `codex/realtime-translator-closeout`.
- Local runtime smoke test passed for `GET /` and `GET /api/health` on port `8000`.
- Azure startup path now works without importing `faster-whisper` until a local engine is selected.
- `Input: System` now prefers current-default-device loopback before Stereo Mix fallback.
- Local realtime defaults were tightened to `1s` / `1.5s` chunk behavior depending on latency preset.
- MarianMT is the recommended local engine when Chinese wording quality matters; Argos remains the fastest fallback.

High-end local upgrade result on 2026-05-05:

- CUDA PyTorch `2.11.0+cu128` installed in `.venv`.
- `torch.cuda.is_available()` returned `true` on NVIDIA GeForce RTX 5070 Ti.
- `WhisperASR` loaded on `cuda`.
- `medium.en` warm ASR average was `494.1ms` for a `13.3s` sample, RTF `0.037`.
- Frontend now defaults to `MarianMT`, `medium.en`, `cuda`, and English-only source.
- Input now defaults to `System`, with `Mic` available as the manual fallback.

Continuation check on 2026-05-06:

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed for `frontend/app.js`.
- UI editor JavaScript syntax check passed for `frontend/ui-editor.js`.
- Local runtime smoke test passed for `GET /` and `GET /api/health` on port `8765`.
- Project-local closeout skill now matches the high-end local-first architecture.

Glossary upgrade result on 2026-05-06:

- Added editable `backend/glossary.csv` professional term table.
- Added `docs/GLOSSARY_GUIDE.md` with step-by-step glossary editing instructions.
- Glossary post-edit smoke test corrected sample outputs for `commissioning`, `FAT`, `developer`, and `land reclamation`.

Pipeline optimization result on 2026-05-06:

- Added `/metrics` rolling pipeline metrics endpoint.
- Added VAD front gate, low-volume notices, stale chunk dropping, and latest-chunk audio queue behavior.
- Added ASR de-duplication for overlap-driven repeated fragments.
- Added short-fragment buffering with sentence, pause, and 2s max-buffer finalization.
- Added protected-term handling for abbreviations, equipment IDs, rooms, levels, numbers, and units.
- Added websocket support for `subtitle_update` replacement of the same segment within one second.

Version 0.2.1 closeout result on 2026-05-06:

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed for `frontend/app.js`.
- UI editor JavaScript syntax check passed for `frontend/ui-editor.js`.
- Local runtime smoke test passed for `GET /api/health` on port `8000`.
- `/metrics` returned successfully on port `8000`.
- Azure live Chinese rendering now uses live translated partials in the lower Chinese pane when Azure emits them.

## Runtime Smoke Test

```powershell
cd path\to\real-time-translator
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Test matrix:

- Input: System, Engine: Azure Cloud.
- Input: Mic, Engine: Azure Cloud, if microphone capture is needed.
- Engine: MarianMT, ASR: medium.en, Device: cuda, Latency: Low, Chunk: 1.5s.
- Engine: Argos, ASR: small.en, Device: cuda, Latency: Low, Chunk: 1.5s.

## Manual UX Checks

- Start button connects and changes status.
- Stop button stops streaming and returns to stopped state.
- Red status lamp is dim but visible when stopped.
- Red status lamp pulses slowly while running or connecting.
- Live subtitles appear without waiting for full paragraphs.
- In local Low latency mode, the upper English pane updates while ASR is still forming the utterance.
- In local Low latency mode, the lower Chinese pane only receives fuller translated utterances.
- English and Chinese should render as continuous long text flows, not one card per utterance.
- Short fragments such as `and`, `in Vietnam`, or `the General Director of the` should not become standalone Chinese rows.
- Repeated loopback phrases should not be appended many times to either subtitle pane.
- Azure mode uses the same two-pane workspace: live English above and live Chinese below.
- Azure and local mode both use internal scroll history and bottom auto-follow.
- Local mode shows English transcript above and polished Chinese translation below.
- `Input: System` can capture the current active Windows playback device when loopback is available.
- No Source selector is shown in the high-end English-only build.
- Final subtitles enter history.
- No MiniMax, Balanced, or Quality mode controls are visible.
- Azure subtitle monitor has its own right-side scrollbar.
- In Azure mode, scrolling upward does not prevent new subtitles from arriving.
- In Azure mode, returning to the bottom resumes auto-follow.
- Long subtitles do not overflow the monitor.
- Short and long subtitles use the same fixed source/translation font sizes.
- Subtitle row padding and spacing stay compact enough to show more history.
- UI Editor opens at `/static/ui-editor.html`.
- UI Editor changes update the preview immediately.
- Clicking "save" stores the theme and the main page applies it after reload.
- Background decoration can be shown or removed through the editor.
