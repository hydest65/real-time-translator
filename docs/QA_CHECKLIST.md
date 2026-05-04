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
- Argos remains the recommended local real-time engine on this environment.

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

- Source: English, Input: Mic, Engine: Azure Cloud.
- Source: Spanish, Input: Mic, Engine: Azure Cloud.
- Input: System, Engine: Azure Cloud, if Windows supports system capture.
- Source: English, Engine: Argos, Latency: Low, Chunk: 1s.
- Source: Spanish, Engine: Argos or NLLB, if offline/local fallback is needed.

## Manual UX Checks

- Start button connects and changes status.
- Stop button stops streaming and returns to stopped state.
- Red status lamp is dim but visible when stopped.
- Red status lamp pulses slowly while running or connecting.
- Live subtitles appear without waiting for full paragraphs.
- In local Low latency mode, the English upper area keeps continuous readable context and begins scrolling only after the pane fills.
- In local Low latency mode, the lower English draft pane updates live while ASR is still forming the utterance.
- In local Low latency mode, the Chinese monitor appends complete translated sentences as a continuous text flow.
- Azure mode keeps one bilingual subtitle monitor.
- Azure mode still uses subtitle rows, internal scroll history, and bottom auto-follow.
- Local mode shows English context, English draft, and Chinese complete translations as separate panes.
- `Input: System` can capture the current active Windows playback device when loopback is available.
- Switching Source to Spanish updates the subtitle direction and still starts the stream.
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
