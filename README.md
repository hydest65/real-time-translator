# Real Time Translator MVP

Windows real-time subtitle translator. It supports English-to-Chinese and Spanish-to-Chinese subtitles through two routes:

- `Cloud`: lowest-latency streaming speech translation, shown with provider-neutral labels for testers.
- `Local`: private offline ASR + translation. English/Spanish fallback uses faster-whisper plus local translators; local Chinese realtime mode uses FunASR streaming.

## Current Low-Latency Defaults

- Engine: `Cloud` for lowest latency, or local engines when privacy/offline mode matters
- Input: `System` by default; it first tries the current default Windows output device through loopback capture, then falls back to Stereo Mix / speaker-monitor input. Use `Mic` when you want room or headset microphone audio.
- Local ASR: `faster-whisper` for English/Spanish fallback; `FunASR Paraformer streaming` for Chinese realtime subtitles
- Local ASR preset: `Balanced`
- Whisper model: `small.en`
- Speed option: `base.en`
- Accuracy experiment: `small.en + int8_float16`, or manual `medium.en + int8` if GPU memory allows
- Device: prefer `cuda + int8`, automatically falls back to `cpu + int8`
- Local ASR decoding: `Fast` uses beam 1, `Balanced` uses beam 2, and `Accurate` uses beam 3
- Local default chunk: `2s`
- Local low-latency preset: `2s` max audio chunk, `1s` adaptive minimum, `0.35s` silence flush, `0.3s` overlap, queue max size `2`
- Local steady preset: `3s` max audio chunk, `1.5s` adaptive minimum, `0.45s` silence flush, `0.5s` overlap, queue max size `2`
- VAD: skip low-RMS silence before ASR; `System` input uses a stricter default gate than `Mic` to avoid loopback silence/weak-noise hallucinations
- Local translation engine: `argos`
- Local English/Spanish subtitles use an English context pane and a Chinese complete-translation pane; local Chinese FunASR mode uses one Chinese live caption window
- Frontend: Cloud mode uses a fixed bilingual subtitle monitor; local mode uses separate English live and Chinese translation monitors
- Local Chinese FunASR subtitles use a recent live caption window instead of a separate draft pane
- Meeting notes: `End Meeting` closes the recording session; use the Notes tools to build one bilingual Word notes file with English minutes first and Chinese minutes second
- Audio archive: each session saves a local WAV file under `recordings/` for post-meeting speaker diarization
- UI editor: visual theme editor at `/static/ui-editor.html` for color, subtitle size, panel width, corner radius, and background-art toggles
- Diagnostics: monitor panel at `/static/diagnostics.html` opens separately so checking health does not stop the live translation page
- Cloud usage panel: shows current-session cloud time, local browser day/month estimates, and optional account-level sync
- Status lamp: small red indicator stays visible when stopped and slowly pulses while translation is running
- Source language: English or Spanish, both translated into Simplified Chinese
- Cloud subtitles: live partial results update the current row; final results enter the scrollable history
- Long subtitles stay continuous and wrap at the same fixed subtitle size as short subtitles
- Local English context and Chinese translation panes render as continuous text; the English pane fills first and then scrolls
- Paragraph turns: final subtitles after a pause start a new visual paragraph; short filler/noise is ignored
- Mode: fast/direct translation only.

## Translation Engines

- `azure`: internal cloud streaming speech translation route. Best for Teams meetings and low latency.
- `argos`: lowest latency local translation. Best offline/default local choice.
- `marianmt`: local neural translation through Helsinki-NLP MarianMT models. Better as a quality/comparison path than a real-time default on this machine.
- `nllb`: higher quality but slow; kept for comparison and non-real-time use.

First use of Argos may download and install the required language package. First use of MarianMT or NLLB may download Hugging Face models into `.cache/huggingface`.

Spanish mode notes:

- Cloud mode uses `es-ES` speech recognition and `zh-Hans` translation.
- Local ASR automatically maps `base.en` to multilingual `base`, and `small.en` to multilingual `small`, because `.en` Whisper models cannot recognize Spanish.
- Argos first tries a direct `es -> zh` package, then falls back to `es -> en -> zh` if the direct package is unavailable.
- MarianMT uses a separate Spanish-to-Chinese model setting: `Helsinki-NLP/opus-mt-es-zh`.
- NLLB uses `spa_Latn -> zho_Hans`.

## Project Structure

```text
real_time_translator/
  asr/
    funasr_streaming.py
    audio_capture.py
    subtitle_state.py
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
    diagnostics.html
    diagnostics.css
    diagnostics.js
  README.md
```

## Version Closeout Docs

- Current closeout: `0.3.2-speaker-aware-notes-ui-trim - Speaker-aware meeting notes and subtitle workspace cleanup`.
- Local-only profile: `docs/LOCAL_T600_PROFILE.md`. Do not treat this as the GitHub/5070Ti baseline unless a separate multi-machine profile feature is intentionally added.
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

Optional Azure Monitor usage sync:

```powershell
$env:AZURE_TENANT_ID="your_tenant_id"
$env:AZURE_CLIENT_ID="your_app_registration_client_id"
$env:AZURE_CLIENT_SECRET="your_client_secret"
$env:AZURE_SPEECH_RESOURCE_ID="/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.CognitiveServices/accounts/<speech-resource-name>"
$env:AZURE_SPEECH_MONTHLY_SECONDS_LIMIT="360000"
```

The Speech key is enough for live translation, but it cannot read account-level usage. The usage panel calls `/api/azure-usage`, which uses Azure Monitor `AudioSecondsTranslated` through a service principal with `Monitoring Reader` access on the Speech resource. If these Azure Monitor variables are missing, the UI safely falls back to browser-local estimates and labels them as local-only.

Optional phrase list for better names and technical terms:

```powershell
$env:AZURE_PHRASE_LIST="Teams,Codex,faster-whisper,MarianMT,Azure Speech"
$env:ASR_PROMPT_TERMS="AHU,BMS,EMS,HVAC,WFI,CIP,SIP,P&ID"
```

The terminology hotword system is shared by Azure Cloud subtitles, local faster-whisper subtitles, and post-meeting processing. For a larger private glossary, copy `backend/glossary.example.csv` to `backend/glossary.csv` and add rows with:

```csv
source,target,aliases,notes
AHU,空气处理机组,Air Handling Unit,HVAC equipment
```

`source` and `aliases` are used as recognition hotwords. `target` is kept for human-readable translation terminology and future glossary-assisted translation. `backend/glossary.csv` is ignored by Git so private project terms stay local. Set `TERMINOLOGY_GLOSSARY_PATH` if you want to keep the glossary elsewhere.

## Azure Batch Meeting Notes

For post-meeting notes with cloud speaker separation, set:

```powershell
$env:POST_MEETING_ASR_ENGINE="azure-batch"
$env:AZURE_BATCH_CONTAINER_SAS_URL="https://<storage>.blob.core.windows.net/<container>?<sas>"
```

The SAS URL should point to a private Blob container and allow create/write/read/list for the processing window. The app uploads the original WAV, submits Azure Batch Transcription with diarization enabled, polls the job, downloads the transcript, and then builds the notes locally. If the SAS URL is missing, the app falls back to local transcription without speaker separation.

Post-meeting notes follow the selected live engine: Azure Cloud mode attempts Azure Batch meeting notes, while Argos, MarianMT, and NLLB modes use local post-meeting transcription without speaker separation.

For Aliyun Tingwu notes, the local archive stays as the original WAV. Before upload, the backend can create a lossless FLAC file with `ffmpeg` and upload that smaller file instead. This is enabled by default with `ALIYUN_TINGWU_AUDIO_COMPRESSION=flac`; set it to `off` to upload the original WAV. The compressed upload file is cached as `recordings/*.upload.flac` when `ALIYUN_TINGWU_CACHE_COMPRESSED_AUDIO=1`, so rebuilding notes for the same WAV does not recompress audio. If `ffmpeg` is not found or the FLAC is not meaningfully smaller, the app automatically falls back to the original WAV.

Meeting notes can run a second-pass topic rewrite after cloud or local transcription. With `POST_MEETING_NOTES_REWRITE_ENABLED=1`, the backend sends the generated minutes plus the full transcript to the configured Ollama notes model and asks it to expand each important topic with concrete discussion points, examples, numbers, risks, decisions, and next steps that are supported by the transcript. The original generated draft is saved beside the recording as `*.minutes.raw.md` whenever the rewrite is accepted.

MiniMax polishing and Balanced/Quality modes have been removed. The app now keeps a single fast/direct live-subtitle path.

Example region values look like `eastus`, `westus`, or the region shown in your Azure resource page.

When the web page opens, choose:

```text
Engine: Azure Cloud
```

In Azure mode, the app streams microphone audio to Azure Speech Translation and receives live source-language and Chinese subtitle results. It does not load Whisper, Argos, MarianMT, or NLLB for that run.

Azure can sometimes return very long final segments. The app keeps them as one semantic subtitle with fixed subtitle sizing instead of forcing time-based cuts.

The paragraph detector is intentionally lightweight. It uses the pause between final subtitles plus a short noise list such as `uh`, `um`, `ok`, and `yeah`. This is not true speaker diarization; it avoids noise-triggered paragraph breaks while keeping latency low.

Meeting export uses the final subtitle stream rather than the visible history window, so the downloaded transcript can keep the full meeting text even though the on-screen monitor only keeps a compact rolling display. Speaker labels in the export are pause-based `Turn` labels, not verified voiceprints.

Each started session also writes a WAV file to `recordings/session-YYYYMMDD-HHMMSS.wav`. The folder is ignored by Git because meeting audio may contain private information.

If you accidentally press Stop and then Start again within 5 minutes, the app continues appending to the same WAV file instead of creating a new meeting recording. After a longer break, it creates a new session file.

Use `End Meeting` when the meeting is truly over. It closes the current recording session, so the next `Start` creates a new WAV even if it happens within 5 minutes.

Optional post-meeting speaker diarization can be run against that WAV file in a separate Python environment with `pyannote.audio` installed:

```powershell
$env:HF_TOKEN="your_huggingface_token"
python scripts\diarize-recording.py recordings\session-YYYYMMDD-HHMMSS.wav
```

This writes `.speakers.rttm` and `.speakers.md` files with anonymous speaker clusters such as `SPEAKER_00`. Those labels are not real names and still need human review.

To turn a recording into post-meeting transcript and minutes files, run:

```powershell
python scripts\process-recording.py recordings\session-YYYYMMDD-HHMMSS.wav
```

This writes `.transcript.md` and `.minutes.md`. Add `--diarize` when `pyannote.audio` and `HF_TOKEN` are ready:

`End Meeting` only stops the live session and closes the current recording. To build notes, open the Notes tool, choose the recording, and click `Build Notes`. The app writes a readable bilingual Word document with English professional meeting minutes first, then a Chinese reading version in the same file. Without diarization it falls back to pause-based turn labels; with diarization it uses anonymous speaker clusters.

Quality presets for this T600 4GB GPU machine:

```powershell
python scripts\process-recording.py recordings\session-YYYYMMDD-HHMMSS.wav --quality fast
python scripts\process-recording.py recordings\session-YYYYMMDD-HHMMSS.wav --quality balanced
python scripts\process-recording.py recordings\session-YYYYMMDD-HHMMSS.wav --quality high
```

`balanced` uses `small.en + int8 + beam 2` and is the default. `high` uses `medium.en + int8 + beam 3`; use it only for post-meeting processing because it can be slow or may fall back if GPU memory is tight.

Optional Alibaba/FunASR post-meeting ASR:

```powershell
python -m pip install funasr
python scripts\process-recording.py recordings\session-YYYYMMDD-HHMMSS.wav --asr-engine funasr
```

The FunASR path defaults to `iic/SenseVoiceSmall` with VAD and punctuation. It is intended for post-meeting experiments, not the realtime subtitle path.

```powershell
$env:HF_TOKEN="your_huggingface_token"
python scripts\process-recording.py recordings\session-YYYYMMDD-HHMMSS.wav --diarize
```

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

The UI editor previews the main page in a browser frame. Changes are stored in the browser's `localStorage` and applied by the main page on load. Use it for fast personal UI tuning before deciding whether a style should be written permanently into `frontend/style.css`.

Diagnostics panel:

```text
http://127.0.0.1:8000/static/diagnostics.html
```

The diagnostics page shows backend health, cloud/local notes readiness, meeting-notes progress, recent recordings, and quick connection checks. Open it from the small monitor icon in the main UI; it uses a separate tab so the active subtitle session keeps running.

Recommended first test:

```text
Source: English
ASR: small.en
Device: cuda
Chunk: 2s
Engine: Azure Cloud
Input: System, if available for Teams audio
```

Recommended Spanish test:

```text
Source: Spanish
ASR: small.en
Device: cuda
Chunk: 2s
Engine: Azure Cloud
```

Recommended private/offline test:

```text
ASR Preset: Balanced
ASR: small.en
Device: cuda
Latency: Low
Chunk: 2s
Engine: Argos
```

Local ASR presets:

- `Fast`: `base.en + int8 + beam 1`, for lower latency when wording does not need to be perfect.
- `Balanced`: `small.en + int8 + beam 2`, recommended default for the NVIDIA T600 Laptop GPU with 4GB VRAM.
- `Accurate`: `small.en + int8_float16 + beam 3`, for a quality test when enough GPU memory is free.

The local ASR presets also tune decoding behavior. `Fast` and `Balanced` do not condition on previous chunk text, which reduces repeated or drifting phrases during short streaming chunks. `Accurate` keeps previous-text conditioning for experiments where wording quality matters more than latency.

Manual model note: `medium.en` is available in the ASR dropdown for experiments, but it is not the default on a 4GB GPU because it can load slowly or run out of memory during meetings.

For better recognition accuracy:

```text
ASR: small.en
```

## Runtime Pipeline

Local mode runs four async workers:

```text
audio_capture_worker
  -> asr_worker
  -> LocalUtteranceAggregator
  -> ContextualTranslationBuffer
  -> translate_worker
  -> websocket_push_worker
```

In the Low latency preset, the audio queue uses max size `2`. The local segmenter waits for fuller utterances before Chinese translation so short ASR fragments do not become broken Chinese sentences. A contextual translation buffer can briefly hold short or dependent utterances, merge them with the next ready utterance, and then translate the combined text. The translation queue preserves ready utterances so completed sentences are not lost.

For English/Spanish local mode, the frontend receives fast ASR updates first. When an utterance is ready, stable source text is appended to a continuous context pane and the Chinese translation is appended to a continuous translation pane. For Chinese local mode, FunASR streaming feeds a recent live caption window directly and keeps the full transcript buffer internally. Azure mode keeps the original single bilingual scrolling monitor.

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

- `azure` is the best choice when you want the lowest latency and can use a cloud service.
- `argos` is the best local default for low latency.
- `marianmt` may be better when you can accept a bit more delay.
- `nllb` is not recommended for real-time use on this machine.
- English local mode can use `base.en` for speed, `small.en` for the recommended default, and `medium.en` for manual experiments. Spanish local mode automatically uses the matching multilingual Whisper model.
- Current MarianMT runs through Transformers, not CTranslate2 int8 yet.
