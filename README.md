# Real Time Translator MVP

Windows real-time subtitle translator tuned for a high-end local English-to-Chinese workflow. It supports two routes:

- `Local`: private offline ASR + translation with faster-whisper on CUDA and local translators.
- `Azure Cloud`: optional cloud streaming speech translation for comparison or fallback.

## Current Low-Latency Defaults

- Engine: `Argos` local by default for private high-end local use; `Azure Cloud` remains optional
- Input: `System` by default; it first tries the current default Windows output device through loopback capture, then falls back to Stereo Mix / speaker-monitor input
- Local ASR: `faster-whisper`
- Whisper model: `medium.en`
- Faster options: `small.en` and `base.en`
- Device: prefer `cuda + int8`, automatically falls back to `cpu + int8`
- GPU target: NVIDIA RTX 5070 Ti 16GB class hardware
- Local default chunk: `1.5s`
- Local low-latency preset: `1s` audio chunk, `0.1s` overlap, queue max size `1`
- Local steady preset: `1.5s` audio chunk, `0.2s` overlap, queue max size `1`
- VAD: skip low-RMS silence before ASR
- Local translation engine: `argos`
- Local subtitles use an English context pane, an English live draft pane, and a Chinese complete-translation pane
- Frontend: Azure uses a fixed bilingual subtitle monitor; local mode uses separate English live and Chinese translation monitors
- UI editor: visual theme editor at `/static/ui-editor.html` for color, subtitle size, panel width, corner radius, background-art toggles, and theme import/export
- Status lamp: small red indicator stays visible when stopped and slowly pulses while translation is running
- Source language: English only, translated into Simplified Chinese
- Azure subtitles: live partial results update the current row; final results enter the scrollable history
- Long subtitles stay continuous and wrap at the same fixed subtitle size as short subtitles
- Local English context and Chinese translation panes render as continuous text; the English pane fills first and then scrolls
- Paragraph turns: final subtitles after a pause start a new visual paragraph; short filler/noise is ignored
- Mode: fast/direct translation only.

## Translation Engines

- `azure`: cloud streaming speech translation through Azure Speech Translation. Best for Teams meetings and low latency.
- `argos`: lowest latency local translation. Best offline/default local choice.
- `marianmt`: local neural translation through Helsinki-NLP MarianMT models. Better as a quality/comparison path than a real-time default on this machine.
- `nllb`: higher quality but slow; kept for comparison and non-real-time use.

First use of Argos may download and install the required language package. First use of MarianMT or NLLB may download Hugging Face models into `.cache/huggingface`.

High-end local notes:

- The dedicated local default is `medium.en + cuda + int8 + Argos`.
- The project environment is pinned to CUDA PyTorch through `torch==2.11.0+cu128`.
- On RTX 5070 Ti 16GB, measured warm ASR speed for `medium.en` is about `0.037 RTF` on a 13.3s English sample, roughly 27x realtime.
- `small.en` remains available when startup time or extra latency margin matters; `base.en` remains available as the fastest low-accuracy option.

## Project Structure

```text
real_time_translator/
  backend/
    main.py
    audio_capture.py
    asr.py
    cloud_speech.py
    translator.py
    config.py
    requirements.txt
  frontend/
    index.html
    style.css
    app.js
    ui-editor.html
    ui-editor.css
    ui-editor.js
  README.md
```

## Version Closeout Docs

- Current closeout: `0.2.0 - High-End Local English Edition`.
- `docs/PRODUCT_REQUIREMENTS.md`: product scope and success criteria.
- `docs/TECHNICAL_ARCHITECTURE.md`: Azure and local fallback architecture.
- `docs/UI_STYLE.md`: Subtitle Studio layout and interaction rules.
- `docs/RELEASE_NOTES.md`: current milestone release notes.
- `docs/QA_CHECKLIST.md`: static checks and runtime smoke test checklist.
- `docs/VERSION_CLOSEOUT_SKILL.md`: project-local version closeout workflow.

## Install

Use Python 3.11 on Windows.

```powershell
cd path\to\real-time-translator
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
```

The high-end local edition installs CUDA PyTorch from the PyTorch CUDA 12.8 wheel index. The first install downloads a large GPU package.

If your pip source says it cannot find `argostranslate`, install it from PyPI directly:

```powershell
python -m pip install argostranslate==1.9.6 -i https://pypi.org/simple
python -m pip install sacremoses==0.0.53 -i https://pypi.org/simple
```

If Windows cannot install the local `faster-whisper` stack immediately, you can still start and use the Azure Cloud route first. The backend now delays loading `faster-whisper` until a local engine is actually selected.

If you already have the virtual environment, just run:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

## Azure Cloud Setup

Create an Azure Speech resource, then set these environment variables in the same PowerShell window before starting the backend:

```powershell
$env:AZURE_SPEECH_KEY="your_speech_key"
$env:AZURE_SPEECH_REGION="your_region"
```

For a local test package, copy `.env.example` to `.env` and fill in your own Azure Speech values. Do not share your real `.env` file.

Optional phrase list for better names and technical terms:

```powershell
$env:AZURE_PHRASE_LIST="Teams,Codex,faster-whisper,MarianMT,Azure Speech"
```

MiniMax polishing and Balanced/Quality modes have been removed. The app now keeps a single fast/direct live-subtitle path.

Example region values look like `eastus`, `westus`, or the region shown in your Azure resource page.

When the web page opens, choose:

```text
Engine: Azure Cloud
```

In Azure mode, the app streams microphone audio to Azure Speech Translation and receives live source-language and Chinese subtitle results. It does not load Whisper, Argos, MarianMT, or NLLB for that run.

Azure can sometimes return very long final segments. The app keeps them as one semantic subtitle with fixed subtitle sizing instead of forcing time-based cuts.

The paragraph detector is intentionally lightweight. It uses the pause between final subtitles plus a short noise list such as `uh`, `um`, `ok`, and `yeah`. This is not true speaker diarization; it avoids noise-triggered paragraph breaks while keeping latency low.

For Teams meetings, keep `Input: System`. The app now prefers the current default Windows playback device through loopback capture when available. If loopback is unavailable, it falls back to Stereo Mix / speaker-monitor input. If the app still reports that system audio input was not found, enable Stereo Mix in Windows sound settings or use `Input: Mic`.

## Run

Easiest local-app style start:

```text
Double-click: Subtitle Studio.bat
```

This starts the local backend and opens Subtitle Studio automatically. The first run creates `.venv` if needed and installs missing dependencies, so it can take a while. When you are done, close the app/browser window and the launcher will stop the local server it started.

Backup manual controls:

```text
Double-click: Start Subtitle Studio.bat
Double-click: Stop Subtitle Studio.bat
```

PowerShell start:

```powershell
cd path\to\real-time-translator
.\scripts\start-server.ps1
```

You can also double-click `start-server.bat` in the project folder. These options use the project's `.venv` automatically, so you do not need to activate the virtual environment every time.

Manual developer start:

```powershell
cd path\to\real-time-translator
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Visual UI editor:

```text
http://127.0.0.1:8000/static/ui-editor.html
```

The UI editor previews the main page in a browser frame. Changes are stored in the browser's `localStorage` and applied by the main page on load. You can also copy the generated CSS or export/import a theme JSON file for reuse across browsers before deciding whether a style should be written permanently into `frontend/style.css`.

Recommended first test:

```text
ASR: medium.en
Device: cuda
Latency: Low
Chunk: 1s
Engine: Argos
Input: System, if available for Teams audio
```

Recommended faster local test:

```text
ASR: small.en
Device: cuda
Latency: Low
Chunk: 1s
Engine: Argos
```

Recommended cloud comparison:

```text
Engine: Azure Cloud
Input: System, if available for Teams audio
```

Local benchmark on RTX 5070 Ti 16GB:

```text
base.en warm ASR: 191.8ms for 13.3s audio, RTF 0.014
small.en warm ASR: 301.3ms for 13.3s audio, RTF 0.023
medium.en warm ASR: 494.1ms for 13.3s audio, RTF 0.037
```

## Runtime Pipeline

Local mode runs four async workers:

```text
audio_capture_worker
  -> asr_worker
  -> LocalUtteranceAggregator
  -> translate_worker
  -> websocket_push_worker
```

In the Low latency preset, the audio queue uses max size `1`. When it is full, the oldest audio item is dropped so the app stays close to real time instead of processing stale audio. The translation queue preserves ready utterances so completed sentences are not lost.

For local mode, the frontend receives fast English draft updates first. When an utterance is ready, the stable English text is appended to a continuous context pane and the Chinese translation is appended to a continuous translation pane. The English context and Chinese panes do not behave like scrolling subtitle history rows; they keep a continuous readable text flow, with the English context pane filling first and then scrolling. Azure mode keeps the original single bilingual scrolling monitor.

Azure mode uses a shorter cloud-streaming route:

```text
microphone frames
  -> Azure Speech Translation streaming session
  -> websocket_push_worker
```

Azure returns live partial subtitles and final subtitles. The frontend updates the latest live line instead of waiting for a full local chunk to finish.

## Performance Logs

Every subtitle includes:

- audio duration
- ASR time
- translation time
- total latency
- translation engine

The browser shows this in the Perf line. If you see an `argos-asr` or similar engine name, that is the English-first local ASR row before Chinese translation completes. PowerShell also prints lines like:

```text
[perf] {'audioSeconds': 3.0, 'asrMs': 420.5, 'translateMs': 35.2, 'totalLatencyMs': 620.1, 'engine': 'argos'}
```

## Notes

- `argos` is the best default for this high-end local English edition.
- `azure` remains useful when you want a cloud comparison or do not want to load local models.
- `marianmt` may be better when you can accept a bit more delay.
- `nllb` is not recommended for real-time use on this machine.
- English local mode now defaults to `medium.en`; use `small.en` for a lighter realtime profile and `base.en` for the fastest low-accuracy profile.
- Current MarianMT runs through Transformers, not CTranslate2 int8 yet.
