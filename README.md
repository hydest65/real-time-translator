# Real Time Translator MVP

## Windows 桌面应用

桌面版 0.4.6 使用雾白半透明背景，隐藏滚动条并保留滚轮、PageUp / End 历史浏览。窗口可置顶，拖动四边或四角调整大小；完整界面和字幕模式都可在「SET」中按需打开设置，独立选择显示原文、译文，调整字号（10–160 px）、字体颜色及背景不透明度（15%–100%），设置自动保存。字体颜色可点击色块选择，也可直接输入 HEX 色值，修改后立即应用；「RST」恢复默认字号和颜色。功能按键尽可能使用细线图标，悬停显示中文功能及英文缩写提示。完整解压便携包后双击 `Subtitle Studio.exe`，无需安装 Python；本机桌面快捷方式 `Subtitle Studio` 或源码工作目录的 `启动桌面字幕.cmd` 可打开已构建的最新版本，悬停应用名称可查看版本。

构建方法、云服务配置及验证范围见 [桌面应用说明](docs/DESKTOP_APP.md)。便携包使用 Cloud 实时翻译，不包含私有配置、录音或离线模型。

0.4.6 在 SET 中新增原文（`SRC`）和译文（`TR`）独立显示开关，默认两者都显示；可仅显示原文、仅显示译文、同时显示或同时隐藏。修改立即作用于已有及新字幕并记住重启后的选择，不清空字幕记录或重启翻译；RST 只恢复字号和颜色，不改变显示选择。全新便携包原生验收 37 项、完整重开后 39 项及单元测试 30/30 通过，已确认两种最小窗口模式下开关可达与显示选择恢复；未进行实际音频或付费识别测试。

0.4.5 修复 Codex 的 Windows MSIX 目录重定向导致普通桌面启动找不到已保存云配置的问题：已保存密钥仍在本机 Codex 的影子目录中，普通 Windows 启动读取的主配置为空。新版在主配置缺失且兼容时，从指定的 Codex 保存位置自动恢复；已有有效配置或部分设置冲突时不会覆盖。升级后只需关闭旧版并重新打开最新版，无需重新输入 API 密钥。CFG 密钥框留空仍表示保留原密钥。

0.4.4 的配置等待 / 重试、读取错误与缺配置区分继续保留。此前隔离启动检查读到了 MSIX 影子目录，不能作为普通 Windows 桌面重开已恢复配置的证明；0.4.5 将普通启动路径纳入独立验收。

字幕模式左上角的声波图标显示连接与翻译状态：连接中为蓝色，连接正常且正在监听、识别或翻译时为绿色并缓慢跳动，停止时静止，出错时为红色。系统开启减少动画时保留状态颜色并停止跳动；悬停可查看状态说明。

0.4.5 已恢复普通 Windows 启动实际读取的本机配置，两个全新后端进程均读取同一实际文件并确认已配置；原保存文件未改动，重复恢复不会再次改写。隔离窗口验收和 30 项单元测试通过，便携包未含私有配置。此后从 Codex 环境重新打开 0.4.5 时配置检查正常，但该启动仍受 MSIX 路径重定向，不能视为普通 Explorer 界面路径已验证；实际音频和付费识别未在该轮测试。升级需先关闭旧版再打开最新版。此前版本检查的范围详见 [QA 清单](docs/QA_CHECKLIST.md)。

0.4.3 的颜色功能及验证记录保留：原文、译文独立颜色设置保存到本机 `display.json`，完整关闭并重开后恢复。默认原文颜色为 `#68788C`、译文颜色为 `#283445`。完整 ZIP 全新解压后原生验收 28 项、完整重开后 29 项及单元测试 10/10 通过，涵盖颜色即时应用、输入校验、默认值恢复和两种最小窗口模式下控件可达；颜色功能测试没有进行实际音频或付费识别。详细结果见 [QA 清单](docs/QA_CHECKLIST.md)。

0.4.2 配置修复的历史验证记录保留：缺少配置时播放按钮打开云配置表单并保留字幕历史；完整 ZIP 全新解压后原生验收 21 项、完整重开后 22 项及单元测试 10/10 通过。此前配置读取与界面验证不代表真实云识别及音频授权已验证。

Windows real-time subtitle translator. It supports English, Spanish, Japanese, and Chinese meeting speech with Simplified Chinese subtitles through two routes:

- `Cloud`: lowest-latency streaming speech translation, shown with provider-neutral labels for testers.
- `Local`: private offline ASR + translation. English/Spanish fallback uses faster-whisper plus local translators; local Chinese realtime mode uses FunASR streaming.

## Realtime-only edition

The app now focuses on live translation, caption history, custom font sizes, connection status, and audio recording. Notes controls, background queries, generation APIs, and notes-specific cloud installation dependencies have been removed. Existing recordings and generated documents are not deleted. Older notes scripts and historical documentation are retained as legacy source; they are not part of the supported application workflow.

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
- Focused realtime edition (2026-09-29): meeting-note generation, summarization, and Word export have been removed from the application and API.
- Audio archive: each session saves a local WAV file under `recordings/` as an audio archive
- UI editor: visual theme editor at `/static/ui-editor.html` for color, subtitle size, panel width, corner radius, and background-art toggles
- Diagnostics: monitor panel remains available at `/static/diagnostics.html`, but the main toolbar no longer shows a diagnostics shortcut
- Cloud usage panel: shows current-session cloud time, account-level sync when configured, and the centrally enforced monthly quota
- Status lamp: small red indicator stays visible when stopped and slowly pulses while translation is running
- Source language: English, Spanish, Japanese, or Chinese meeting speech, translated or transcribed into Simplified Chinese
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

Argos, MarianMT, NLLB, faster-whisper, and FunASR are optional local-model features. They are not installed by the default lightweight dependency set. If you install the optional local stack, first use of Argos may download and install the required language package, and first use of MarianMT or NLLB may download Hugging Face models into `.cache/huggingface`.

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
    requirements-local.txt
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

- Current closeout: `0.4.6 - Windows desktop caption visibility and saved configuration recovery`.
- [当前需求](docs/requirements.md)、[当前架构](docs/architecture.md)、[迭代与待验收](docs/roadmap.md)、[技术交接](docs/technical-memory.md)：中文短入口，以桌面 0.4.6 和实时字幕版为当前基线。
- Local-only profile: `docs/LOCAL_T600_PROFILE.md`. Do not treat this as the GitHub/5070Ti baseline unless a separate multi-machine profile feature is intentionally added.
- `docs/PRODUCT_REQUIREMENTS.md`: current product baseline and historical scope.
- `docs/TECHNICAL_ARCHITECTURE.md`: current desktop architecture and historical route details.
- `docs/UI_STYLE.md`: current desktop interaction rules and historical browser styling.
- `docs/RELEASE_NOTES.md`: current milestone release notes.
- `docs/QA_CHECKLIST.md`: static checks and runtime smoke test checklist.
- `docs/VERSION_CLOSEOUT_SKILL.md`: project-local version closeout workflow.

## Install

The default install is cloud-first and lightweight. It supports the browser UI, Azure live translation, audio capture, and local recording. It does not install local realtime/offline model packages such as Whisper, FunASR, Argos, MarianMT, NLLB, Torch, or Hugging Face Transformers.

Use Python 3.11 on Windows.

```powershell
cd path\to\real-time-translator
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
```

Only install the optional local-model stack when you specifically need offline/local ASR or offline/local translation:

```powershell
python -m pip install -r backend\requirements-local.txt
```

If your pip source says it cannot find `argostranslate`, install the optional stack from PyPI directly:

```powershell
python -m pip install -r backend\requirements-local.txt -i https://pypi.org/simple
```

If Windows cannot install the local `faster-whisper` or FunASR stack immediately, you can still start and use the Azure Cloud route first. The backend delays loading local model libraries until a local engine is actually selected.

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
$env:AZURE_SPEECH_MONTHLY_SECONDS_LIMIT="18000"
```

The Speech key is enough for live translation, but it cannot read account-level usage. The usage panel calls `/api/cloud-usage`, which uses Azure Monitor `AudioSecondsTranslated` through a service principal with `Monitoring Reader` access on the Speech resource. If these Azure Monitor variables are missing, the app still enforces the local backend quota ledger, but the panel labels the cloud sync as unavailable.

Cloud live translation has a default monthly quota of `18000` seconds, or 5 hours. The quota window resets at 00:00 UTC on the first day of each month, which is 08:00 in China Standard Time. When the combined Azure Monitor usage, local backend quota ledger, and currently active cloud sessions reach the limit, the backend rejects new cloud subtitle sessions and stops active cloud sessions at the quota boundary.

## Remote Testing Mode

For small external tests, keep the Azure Speech key only on your own center backend. Testers should open your hosted Subtitle Studio page instead of receiving `.env` or Azure keys.

Start the center backend on all network interfaces:

```powershell
.\scripts\start-remote-server.ps1
```

For browser microphone capture, testers must access the app through HTTPS unless they are on `localhost`. A Cloudflare Tunnel, ngrok tunnel, VPN-hosted HTTPS reverse proxy, or normal HTTPS deployment works. Plain `http://public-ip:8000` may open the page, but Chrome/Edge can block microphone capture.

In remote cloud mode, the browser captures the tester's audio, sends 16 kHz PCM audio over WebSocket to the center backend, and the center backend streams it to Azure. The Azure key never leaves the backend. The 5-hour monthly quota is enforced centrally across all testers.

Do not expose the center backend publicly without a tunnel access policy, VPN, or reverse-proxy authentication. Anyone who can reach the page can spend the shared cloud quota.

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

## Run

Easiest local-app style start:

```text
Double-click: Subtitle Studio.bat
```

This starts the local backend and opens Subtitle Studio automatically. The first run creates `.venv` if needed and installs missing dependencies, so it can take a while. When you are done, close the app/browser window and the launcher will stop the local server it started.

By default the launcher installs only the lightweight cloud-first dependency set. To include optional offline/local models on your own machine, start from PowerShell with `-InstallLocalModels`.

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

Optional local-model start:

```powershell
.\scripts\start-server.ps1 -InstallLocalModels
```

You can also double-click `start-server.bat` in the project folder. These options use the project's `.venv` automatically, so you do not need to activate the virtual environment every time.

## Keep the Project Lightweight

Model downloads, Python environments, recordings, generated previews, runtime caches, and logs should not be shared with other users or pushed to GitHub. The repo already ignores these paths, and the helper below can clean local artifacts before packaging or handing off the project.

Preview what would be removed:

```powershell
.\scripts\cleanup-local-artifacts.ps1 -WhatIf
```

Remove model/runtime caches and logs, while keeping `.venv` and `recordings`:

```powershell
.\scripts\cleanup-local-artifacts.ps1
```

Full cleanup for a transfer package, including `.venv`, recordings, and design previews:

```powershell
.\scripts\cleanup-local-artifacts.ps1 -All
```

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

The diagnostics page shows backend health, live cloud readiness, recent recordings, and connection checks. Open it directly by URL when needed.

Recommended first test:

```text
Source: English
ASR: small.en
Device: cuda
Chunk: 2s
Engine: Azure Cloud
Input: System, if available for Teams audio
```

Recommended Japanese test:

```text
Source: Japanese
Input: Mic or System
Engine: Azure Cloud
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
