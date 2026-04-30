# Real Time Translator MVP

Windows real-time subtitle translator. It supports English-to-Chinese and Spanish-to-Chinese subtitles through two routes:

- `Azure Cloud`: lowest-latency streaming speech translation, similar to commercial meeting subtitle apps.
- `Local`: private offline ASR + translation with faster-whisper and local translators.

## Current Low-Latency Defaults

- Engine: `Azure Cloud` for lowest latency, or local engines when privacy/offline mode matters
- Input: `Mic` by default; `System` tries to capture Stereo Mix / speaker-monitor input on Windows
- Local ASR: `faster-whisper`
- Whisper model: `base.en`
- Accuracy option: `small.en`
- Device: prefer `cuda + int8`, automatically falls back to `cpu + int8`
- Audio chunk: `3s`
- Overlap: `0.5s`
- VAD: skip low-RMS silence before ASR
- Local translation engine: `argos`
- Queue max size: `2`; old chunks are dropped when work piles up
- Frontend: Subtitle Studio layout with a fixed subtitle monitor and scrollable bilingual history
- UI editor: visual theme editor at `/static/ui-editor.html` for color, subtitle size, panel width, corner radius, and background-art toggles
- Status lamp: small red indicator stays visible when stopped and slowly pulses while translation is running
- Source language: English or Spanish, both translated into Simplified Chinese
- Azure subtitles: live partial results update the current row; final results enter the scrollable history
- Long subtitles stay continuous; the UI adapts font size instead of cutting by time
- Paragraph turns: final subtitles after a pause start a new visual paragraph; short filler/noise is ignored
- Mode: fast/direct translation only.

## Translation Engines

- `azure`: cloud streaming speech translation through Azure Speech Translation. Best for Teams meetings and low latency.
- `argos`: lowest latency local translation. Best offline/default local choice.
- `marianmt`: local neural translation through Helsinki-NLP MarianMT models.
- `nllb`: higher quality but slow; kept for comparison and non-real-time use.

First use of Argos may download and install the required language package. First use of MarianMT or NLLB may download Hugging Face models into `.cache/huggingface`.

Spanish mode notes:

- Azure mode uses `es-ES` speech recognition and `zh-Hans` translation.
- Local ASR automatically maps `base.en` to multilingual `base`, and `small.en` to multilingual `small`, because `.en` Whisper models cannot recognize Spanish.
- Argos first tries a direct `es -> zh` package, then falls back to `es -> en -> zh` if the direct package is unavailable.
- MarianMT uses a separate Spanish-to-Chinese model setting: `Helsinki-NLP/opus-mt-es-zh`.
- NLLB uses `spa_Latn -> zho_Hans`.

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

- `docs/PRODUCT_REQUIREMENTS.md`: product scope and success criteria.
- `docs/TECHNICAL_ARCHITECTURE.md`: Azure and local fallback architecture.
- `docs/UI_STYLE.md`: Subtitle Studio layout and interaction rules.
- `docs/RELEASE_NOTES.md`: current milestone release notes.
- `docs/QA_CHECKLIST.md`: static checks and runtime smoke test checklist.
- `docs/VERSION_CLOSEOUT_SKILL.md`: project-local version closeout workflow.

## Install

Use Python 3.11 on Windows.

```powershell
cd "C:\Users\lixin11190\Documents\New project 3\real_time_translator"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
```

If your pip source says it cannot find `argostranslate`, install it from PyPI directly:

```powershell
python -m pip install argostranslate==1.9.6 -i https://pypi.org/simple
python -m pip install sacremoses==0.0.53 -i https://pypi.org/simple
```

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

Azure can sometimes return very long final segments. The app keeps them as one semantic subtitle and adapts the display size instead of forcing time-based cuts.

The paragraph detector is intentionally lightweight. It uses the pause between final subtitles plus a short noise list such as `uh`, `um`, `ok`, and `yeah`. This is not true speaker diarization; it avoids noise-triggered paragraph breaks while keeping latency low.

For Teams meetings, choose `Input: System` if your Windows audio device exposes Stereo Mix or speaker-monitor input. If the app reports that system audio input was not found, enable Stereo Mix in Windows sound settings or use `Input: Mic`.

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
cd "C:\Users\lixin11190\Documents\New project 3\real_time_translator"
.\scripts\start-server.ps1
```

You can also double-click `start-server.bat` in the project folder. These options use the project's `.venv` automatically, so you do not need to activate the virtual environment every time.

Manual developer start:

```powershell
cd "C:\Users\lixin11190\Documents\New project 3\real_time_translator"
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

The UI editor previews the main page in a browser frame. Changes are stored in the browser's `localStorage` and applied by the main page on load. Use it for fast personal UI tuning before deciding whether a style should be written permanently into `frontend/style.css`.

Recommended first test:

```text
Source: English
ASR: base.en
Device: cuda
Chunk: 3s
Engine: Azure Cloud
Input: System, if available for Teams audio
```

Recommended Spanish test:

```text
Source: Spanish
ASR: base.en
Device: cuda
Chunk: 3s
Engine: Azure Cloud
```

Recommended private/offline test:

```text
ASR: base.en
Device: cuda
Chunk: 3s
Engine: Argos
```

For better recognition accuracy:

```text
ASR: small.en
```

## Runtime Pipeline

Local mode runs four async workers:

```text
audio_capture_worker
  -> asr_worker
  -> translate_worker
  -> websocket_push_worker
```

Each queue has max size `2`. When a queue is full, the oldest item is dropped so the app stays close to real time instead of translating stale audio.

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

The browser shows this in the Perf line. PowerShell also prints lines like:

```text
[perf] {'audioSeconds': 3.0, 'asrMs': 420.5, 'translateMs': 35.2, 'totalLatencyMs': 620.1, 'engine': 'argos'}
```

## Notes

- `azure` is the best choice when you want the lowest latency and can use a cloud service.
- `argos` is the best local default for low latency.
- `marianmt` may be better when you can accept a bit more delay.
- `nllb` is not recommended for real-time use on this machine.
- English local mode can use `base.en` for speed and `small.en` for better accuracy. Spanish local mode automatically uses the matching multilingual Whisper model.
- Current MarianMT runs through Transformers, not CTranslate2 int8 yet.
