# QA Checklist

## Static Checks

Run from:

```powershell
cd "C:\Users\lixin11190\Documents\New project 3"
```

```powershell
real_time_translator\.venv\Scripts\python.exe -m compileall real_time_translator\backend
real_time_translator\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'real_time_translator'); import backend.main; print('backend import ok')"
```

If Node is available:

```powershell
node --check real_time_translator\frontend\app.js
```

Current closeout result on 2026-04-30:

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- Command-line `git` was not available in this shell; use GitHub Desktop for sync if needed.

## Runtime Smoke Test

```powershell
cd "C:\Users\lixin11190\Documents\New project 3\real_time_translator"
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Test matrix:

- Input: Mic, Engine: Azure Cloud.
- Input: System, Engine: Azure Cloud, if Windows supports system capture.
- Engine: Argos, if offline/local fallback is needed.

## Manual UX Checks

- Start button connects and changes status.
- Stop button stops streaming and returns to stopped state.
- Red status lamp is dim but visible when stopped.
- Red status lamp pulses slowly while running or connecting.
- Live subtitles appear without waiting for full paragraphs.
- Final subtitles enter history.
- No MiniMax, Balanced, or Quality mode controls are visible.
- Subtitle monitor has its own right-side scrollbar.
- Scrolling upward does not prevent new subtitles from arriving.
- Returning to the bottom resumes auto-follow.
- Long subtitles do not overflow the monitor.
