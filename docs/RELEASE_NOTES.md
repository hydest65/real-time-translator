# Release Notes

## Windows 桌面字幕 0.4.6 — 2026-10-03

- SET 中新增原文（SRC）与译文（TR）独立显示图标开关，默认两者都开启，可仅显示原文、仅显示译文、同时显示或同时隐藏。
- 修改立即应用到已有和后续字幕，不清空记录或重新建立翻译会话；`showSourceText` / `showTranslationText` 与显示设置一起保存，完整重开后恢复。
- RST 继续只恢复字号和颜色，不改变原文 / 译文显示选择。保留字体颜色、半透明背景和声波状态图标。
- 保留 0.4.5 的 MSIX 保存配置恢复及不覆盖有效配置 / 部分冲突保护。升级先关闭旧版再打开最新版，无需重新填写 API 密钥。
- 修正窄窗口设置网格及 CFG 面板内部滚动，420 × 240 的完整界面和字幕模式均可操作 SRC / TR；全部隐藏提示不增加字幕布局行。
- 全新便携包原生验收 37 项、完整重开后 39 项及单元测试 30/30 通过。四种显示组合应用于已有与新字幕且保留节点，不改变会话状态；无效字符串 / 数字不能覆盖原生布尔设置，RST 保留显示选择；完整重开恢复为原文隐藏、译文显示。
- 语法及 `git diff --check` 通过；ZIP 971 个条目扫描未发现私有配置、录音或私钥。0.4.5 已迁移的实际普通 Windows 主云配置未被本轮显示设置改动，未进行实际音频或付费识别测试。

## Windows 桌面字幕 0.4.5 — 2026-10-02

- 通过文件标识确认普通 Roaming 主配置与 Codex MSIX `LocalCache\Roaming` 保存配置是不同的实际文件：前者密钥 / 区域为空，后者仍有已保存值。此前隔离启动读到了影子目录，未覆盖普通 Windows 桌面重开路径，这是继续出现未配置提示的根因。
- 新版启动时自动从指定的已知 Codex MSIX `Subtitle Studio\.env` 恢复默认主配置，仅在主配置不完整且与现有部分设置兼容时执行；不覆盖有效主配置或部分冲突，保留注释、无关设置和短语表。
- 恢复在同一台电脑上本地进行，原保存文件保留，密钥不进入便携包。升级后关闭旧版并重新打开最新版即可执行恢复，无需重填 API 密钥。
- 保留 0.4.4 配置等待 / 重试及声波状态图标、0.4.3 字体颜色和本机显示设置。CFG 密钥框留空仍表示保护并保留原密钥。
- 已通过应用实际恢复函数补全普通 Windows 启动实际读取的主配置；访问使用同一台电脑的本地机器路径，没有向外部网络传送密钥。原影子目录配置 SHA 未变，第二次恢复不再改写主文件。两个全新冻结后端进程读取同一实际主文件，均为 `cloud_configured=true`，读前读后文件未改动。
- 完整 ZIP 全新解压后的隔离原生窗口验收 33 项通过，完整重开后 34 项通过；单元测试 30/30 通过；971 个条目包扫描未发现私有配置、录音或私钥。
- 实际存储路径 / 全新后端验证与隔离界面验收分别记录。此后从 Codex 环境重新打开 0.4.5，配置接口确认已配置，但启动仍受 MSIX 路径重定向，不能当作普通 Explorer 界面路径验证；真实音频与付费云识别不在该轮范围内。以下旧版原生数量保留，但隔离检查不能证明普通 Windows 桌面启动读取了正确的实际文件。

## Windows 桌面字幕 0.4.4 — 2026-10-02

- 修复首次配置请求未完成或失败时误报密钥未配置的问题。此前 `azureConfigured` 初始为 false，配置请求等待期间被当成确定缺失；首次请求失败后，播放入口也不会重新检查。
- 播放入口等待未完成的配置读取并按需重新检查，读取失败与确定缺配置分别提示；本机配置已存在而后台未加载时提示重新启动应用，无需重填密钥。等待或检查失败时保留字幕历史，不启动字幕会话。
- CFG 密钥框始终留空以保护已有密钥，留空保存会保留原密钥。各桌面版本共用 `%APPDATA%\Subtitle Studio`；仅在确认本机缺配置时首次填写，不因升级而重新填写。
- 本次排查确认本机配置仍存在且未改动，既有运行日志包含识别事件，没有复制真实字幕。误报未配置不能据此认定本机密钥丢失。
- 修正源码目录启动入口的最新版本选择，并在应用名称悬停提示中显示当前版本。升级前先关闭旧版窗口，再打开新版；保留 0.4.3 独立颜色设置、持久化与淡色半透明界面。
- 字幕模式新增声波状态图标：连接中为蓝色，本机服务与字幕连接正常且正在监听、识别或翻译时绿色跳动，停止时淡色静止，出错或连接中断时红色。悬停可查看状态说明；系统开启减少动画时仅保留状态颜色。
- 本机桌面新增 `Subtitle Studio` 快捷方式，通过隐藏终端的稳定启动脚本选择语义版本最高的已构建应用，不覆盖已有配置。
- 完整 ZIP 全新解压后原生验收 33 项通过，完整退出重开后 34 项全部通过；单元测试 19/19，包含新增 9 项配置等待、重试、响应校验、超时、本机与后端状态差异及配额检查。
- 原生声波正常监听 / 翻译、连接中、停止、错误状态及减少动画检查通过；聚焦字幕区域后原生滚轮浏览、颜色设置恢复与既有界面回归通过。ZIP 972 个唯一条目扫描通过，未发现私有配置、录音或私钥。
- 本轮未启动实际音频或付费识别，既有运行日志中的识别事件来自此前运行；详细结果见 [QA 清单](QA_CHECKLIST.md)。

## Windows 桌面字幕 0.4.3 — 2026-10-02

- SET 中新增原文、译文独立字体颜色设置，可点击色块打开选择器，也可输入 `#RRGGBB` 格式的 HEX 色值，修改后立即应用到已有及后续字幕。
- 默认原文颜色为 `#68788C`、译文颜色为 `#283445`；RST 同时恢复默认字号与颜色。
- 颜色与现有显示设置一起保存在本机 `display.json`，完整退出并重开后恢复，不受随机服务端口影响。完整界面和字幕模式均保留图标 SET 入口。
- 保留 0.4.2 的配置修复与淡色半透明界面。升级时先关闭当前 0.4.2 窗口，再打开新版 EXE，避免已有实例继续显示旧版窗口。
- 完整 ZIP 全新解压后原生验收 28 项通过，完整退出重开后 29 项全部通过，涵盖独立选择器 / HEX 即时应用、无效颜色保留最后有效值、RST 默认值恢复及保存、新字幕和连续原文 / 译文配色、页面重载和完整重启恢复，以及两种 420 × 240 窗口模式下颜色控件可达。既有界面回归通过。
- 单元测试 10/10、JavaScript 语法、源码审查及 `git diff --check` 通过；ZIP 971 个条目和公开根证书白名单检查通过，未发现私有配置、录音或私钥。
- 本轮没有进行实际音频或付费识别测试，详细结果见 [QA 清单](QA_CHECKLIST.md)。0.4.2 / 0.4.1 的验证结果保留为历史。

## Windows 桌面字幕 0.4.2 — 2026-10-02

- 修复桌面版本机文件已有 Speech 密钥和区域，界面仍显示 `Cloud not configured` 的问题。已在隔离环境复现：继承空白 `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION` 时，文件配置存在而后端判定未配置。
- Electron 启动工作进程时，使用本机选定 `.env` 中的 Speech key / region / phrase 三项覆盖旧值或空白继承环境，并从启动时传入 `SUBTITLE_STUDIO_ENV_FILE` / `SUBTITLE_STUDIO_DATA_DIR`。
- CFG 与服务使用一致的配置解析，支持 UTF-8 BOM 和引号。缺配置时点击播放，直接打开云配置表单并显示中文提示，保留字幕历史，不建立字幕 WebSocket。
- 不修改用户现有 `.env`，密钥不进入便携包；保留 0.4.1 淡色界面、图标按键、半透明字幕及显示设置。
- 完整 ZIP 全新解压后，在继承空白 Speech key / region、文件使用非空测试值及 BOM / 引号的隔离环境中，原生验收 21 项通过；完整重开后 22 项全部通过。CFG 与后端 `cloud_configured` 状态一致；缺配置播放入口不建立字幕 WebSocket、不启动录音、保留历史，并打开 CFG 与中文提示。0.4.1 布局和浏览回归通过。
- 单元测试 10/10（配置 6 项、几何 4 项）、JavaScript 语法和 `git diff --check` 通过。使用用户现有 `.env` 只读启动新版隔离窗口，后端与桌面配置状态均为 true，界面 Ready；SHA 校验确认用户配置未改。
- 便携目录扫描及 ZIP 971 个条目复查通过，私有配置 / 录音 / 私钥为 0；仅保留 certifi 与 gRPC 两份白名单公开根证书，均无私钥，配置读取模块 `cloud-config.cjs` 已入包。
- 验证范围为配置读取与界面，未验证真实云识别、音频授权或付费识别；0.4.1 验证记录保留为历史。

## Windows 桌面字幕 0.4.1 — 2026-10-02

- 桌面界面改为雾白半透明背景（`rgba(248, 250, 253, alpha)`）、深灰正常字重字幕与轻量控件，PIN 激活状态使用淡蓝背景。
- 隐藏可见滚动条并保留历史浏览；字幕区域可用滚轮滚动，聚焦后可使用 PageUp / End。
- 功能按键尽可能改为细线图标：开始为播放、停止为方块、CAP / UI 为字幕窗 / 布局、SET 为调节、PIN 为图钉、CFG 为钥匙、LOG 为文件夹、RST / CHK 为刷新、SAV 为保存；悬停保留中文功能及英文缩写提示，并保留无障碍标签。
- SET 在完整界面和字幕模式都按需展开或收起，保留云配置入口。
- 保留拖动移动、八向窗口缩放、独立原文 / 译文 10–160 px 字号、15%–100% 背景不透明度及本机设置持久化。
- 完整 ZIP 全新解压后的原生验收 19 项通过；同一隔离配置完整退出重开后 20 项全部通过，恢复 420 × 240、原文 22 px、译文 48 px、背景 55% 和字幕模式。
- 原生滚轮 / PageUp / End、历史浏览与新字幕跟随、长连续英文无横向溢出、两种 420 × 240 模式的 SET / CFG 保存按钮可达、图标标签与缩写提示、错误提示增高后的设置位置均通过。窗口几何测试 4/4、JavaScript 语法、PowerShell 解析及 `git diff --check` 通过；公开证书白名单包扫描未发现 `.env`、密钥、录音或离线模型。
- 补充人工验收：真正的鼠标拖动、10 / 160 px 极限字号、15% / 100% 透明度及不同桌面底图可读性。真实音频和付费云识别本轮未实测。

## Windows 桌面字幕 0.4.0 — 2026-10-02

- 新增可直接运行的 Windows x64 便携应用，内置桌面窗口和 Cloud 后端运行组件。
- 半透明背景、置顶、拖动移动、八向调整窗口尺寸；字幕模式保留开始、停止和显示设置入口。
- 功能按钮统一采用 ST / SP / CAP / UI / SET / PIN / CFG / LOG / SAV / RST / CHK 英文缩写，保留中文悬停提示与无障碍标签。
- 原文、译文字号独立支持 10–160 px；背景不透明度支持 15%–100%，文字保持不透明。
- 桌面显示设置保存在本机配置文件，独立于每次启动的随机服务端口；完整重启后可恢复。
- 云服务配置仅保存在本机；退出时正常关闭自己创建的服务，完成录音清理。
- 实际桌面窗口、跨进程设置恢复、最终 ZIP 解压启动已验证；真实音频及付费云翻译未在此轮实测。

## Realtime-only UI — 2026-09-29

- Removed meeting-note controls, summary cards, generation, progress polling, and document export from the application.
- Removed the notes generation, cancellation, progress, diagnostics, and document-serving APIs. The realtime backend no longer imports Tingwu or notes-quality modules or probes notes configuration.
- Removed notes-only cloud SDKs from the default installation requirements.
- Retained live translation, caption history, independent font controls, connection status, recording, and usage tracking. Existing recordings and documents are untouched; historical notes source and documentation are legacy only.
- Verified backend import and route registration, removed APIs returning 404, diagnostics, no notes requests on page load, and start/caption/end with simulated speech events. Font and connection browser checks pass. Real microphone capture and paid speech translation were not exercised.

## 0.3.3-remote-quota-lightweight - Remote Tester Mode, Cloud Quota Guard, and Lightweight Handoff

Date: 2026-07-20

### Product

- Added a remote tester operating path: testers open a hosted Subtitle Studio page, while the speech key stays only on the center backend.
- Added Japanese source speech support for Cloud live translation into Simplified Chinese.
- Added a centrally enforced Cloud live-translation quota, defaulting to 5 hours per month and resetting at the first day of each UTC month.
- Changed the default install to a lightweight cloud-first dependency set so new testers do not download local Whisper, FunASR, Argos, MarianMT, NLLB, Torch, or Hugging Face model stacks unless they explicitly need offline/local mode.

### UI

- Removed the visible mode/settings panel and the Diag toolbar button from the main workspace.
- Kept a single compact Notes shortcut in the top-right utility area.
- Kept diagnostics available at `/static/diagnostics.html` for direct health checks without occupying the live subtitle surface.
- Preserved provider-neutral tester wording such as `Cloud`, `Cloud Usage`, and neutral cloud status labels.

### Technical

- Added browser-audio Cloud streaming for remote testers: the browser captures mic/system share audio, converts it to 16 kHz mono PCM, and sends it over the existing subtitle WebSocket to the center backend.
- Reused `AzureSpeechTranslationSession.write_audio(...)` so remote browser audio feeds the cloud stream without exposing credentials to the browser.
- Added backend monthly quota enforcement that combines Azure Monitor usage when configured, a local backend ledger at `sync-meta/cloud-usage-quota.json`, and active sessions.
- Added active-session quota guarding so Cloud sessions are rejected or stopped once the configured monthly limit is reached.
- Split dependencies into `backend/requirements.txt` for lightweight cloud-first use and `backend/requirements-local.txt` for optional offline/local models.
- Added `scripts/start-remote-server.ps1` for center-hosted testing and `scripts/cleanup-local-artifacts.ps1` for removing model/runtime caches before handoff.

### Verification

- Python syntax checks passed for the changed backend modules and recording-processing script.
- Frontend JavaScript syntax check passed for `frontend/app.js`, `frontend/ui-editor.js`, and `frontend/diagnostics.js` with the bundled Codex Node runtime.
- PowerShell parse checks passed for `scripts/start-server.ps1`, `scripts/start-remote-server.ps1`, `scripts/launch-app.ps1`, and `scripts/cleanup-local-artifacts.ps1`.
- Cloud quota smoke tests passed for limit reached, remaining seconds, active-session accounting, and ledger update after session finish.
- Runtime smoke test passed for `GET /api/health` and the main page on a temporary local port.
- Secret scan found placeholders/documented environment-variable names only; `.env`, recordings, generated notes, sync metadata, and model caches remain ignored.

### Known Limitations

- Remote browser microphone capture requires HTTPS unless the tester is on `localhost`.
- Remote browser system-audio sharing depends on browser and OS support; Mic is the safest remote-test input.
- The hosted center backend should sit behind tunnel access policy, VPN, or reverse-proxy authentication before wider external testing, because anyone who can reach it can spend the shared quota.

## 0.3.2-speaker-aware-notes-ui-trim - Speaker-Aware Meeting Notes and Subtitle Workspace Cleanup

Date: 2026-06-04

### Product

- Improved post-meeting notes so detailed discussion sections can preserve who raised, answered, challenged, confirmed, or owned an important point when speaker-separated transcript evidence is available.
- Kept speaker names conservative: use real names only when supplied by the transcript or meeting context; otherwise preserve anonymous labels such as `Speaker 1` / `Speaker 2` or Chinese `发言人 1` / `发言人 2`.
- Removed the visible Notes context input block (`Title`, `People`, `Keywords`, `Context`) from the main UI so the subtitle workspace stays focused and less crowded.

### UI

- Removed the left vertical panel's large background capsule and narrowed the panel from 160px to 136px, giving more horizontal space back to the subtitle monitors.
- Kept the individual left-side status cards for meeting state, recording state, Cloud usage, and notes status.
- Versioned frontend assets with `speaker-aware-notes-ui-trim-20260604` so browser refreshes load the UI cleanup.

### Technical

- Added speaker-attributed transcript evidence extraction in `backend/notes_quality.py` for the second-pass notes rewrite.
- Filtered short greetings, acknowledgements, and other low-information transcript snippets before sending speaker evidence to the local notes model.
- Strengthened the notes rewrite prompt so major topics prefer speaker-attributed bullets when diarized transcript evidence exists.
- Removed unused Notes context CSS after the UI inputs were removed; backend context payload handling remains compatible and simply receives empty context from the current UI.

### Verification

- Python syntax check passed for `backend/notes_quality.py`.
- Speaker-evidence smoke test on `recordings/rec-0603-220033.transcript.md` extracted substantive `Speaker 1` / `Speaker 2` discussion lines while filtering short greetings.
- `git diff --check` passed with GitHub Desktop's bundled Git.
- Backend health check passed for `GET /api/health` on the running local server.
- Known local limitation: regenerating the full speaker-aware notes preview with Ollama `qwen3:14b` failed when Ollama reported insufficient available memory (`6.3 GiB` required, `4.3 GiB` available). The prompt/code path is in place, but a full rewrite needs memory to be freed or a smaller notes model.

## 0.3.1-notes-quality-compressed-upload - Richer Meeting Notes and Lossless Upload Compression

Date: 2026-06-04

### Product

- Improved post-meeting notes so important topics are expanded with concrete discussion points, examples, numbers, risks, decisions, open questions, and next steps supported by the transcript.
- Preserved the original WAV as the local recording archive while allowing smaller lossless FLAC uploads for cloud meeting-notes processing.
- Added optional meeting context fields in the Notes panel for title, people, keywords, and background so the notes model can resolve ambiguous references more reliably.

### Technical

- Added `backend/notes_quality.py` for a second-pass Ollama notes rewrite over generated minutes plus the full transcript.
- Wired topic-level refinement into both Aliyun Tingwu cloud notes and local post-meeting notes before Markdown/DOCX output is written.
- Saved accepted pre-rewrite drafts as `*.minutes.raw.md` for review and rollback.
- Added Tingwu upload FLAC compression, cached `recordings/*.upload.flac` reuse, ffmpeg diagnostics, and fallback to original WAV when compression is unavailable or not beneficial.
- Added `.env.example` controls for notes rewrite and Tingwu upload compression.

### UI

- Added compact Notes panel context inputs without changing the Start/End Meeting flow.
- Added `compressing` and `refining` progress stages so long note builds show what the backend is doing.

### Verification

- Python syntax checks passed for `backend/notes_quality.py`, `backend/main.py`, and `backend/aliyun_tingwu.py`.
- Frontend JavaScript syntax check passed for `frontend/app.js` with the bundled Codex Node runtime.
- Prompt smoke test passed for the topic-level rewrite instructions.
- Tail-whitespace scan passed for the changed code and documentation files.
- `git diff --check` passed with GitHub Desktop's bundled Git.

## 0.3.0-funasr-streaming-live-window - Local Chinese FunASR Streaming Subtitles

Date: 2026-06-03

### Product

- Added a dedicated local Chinese realtime subtitle path based on FunASR Paraformer streaming.
- Kept the realtime goal focused on low-latency Chinese ASR instead of post-meeting translation quality.
- Changed End Meeting behavior so ending a live session saves/stops recording only; meeting notes are built manually from the notes tools.
- Preserved System audio as the default test path for local Chinese meeting/video audio.

### UI

- Added explicit startup feedback in the Chinese subtitle pane while FunASR connects, loads the model, and starts listening.
- Reworked realtime Chinese display into a recent live subtitle window instead of showing the entire accumulated transcript as one machine-like paragraph.
- Added live subtitle line wrapping and status styling for FunASR so short streaming updates feel closer to natural captions.
- Updated frontend asset versioning to `funasr-live-window-20260603`.

### Technical

- Added `asr/funasr_streaming.py`, `asr/audio_capture.py`, and `asr/subtitle_state.py` for PCM16 16 kHz mono chunk streaming, queue-limited capture, streaming cache reuse, partial/final subtitle state, and low-latency WebSocket events.
- Added FastAPI WebSocket `/ws/asr/funasr` for FunASR streaming messages with `partial`, `final`, `status`, and `error` event types.
- Added FunASR/model download dependencies through `funasr`, `modelscope`, and `huggingface-hub`.
- Improved partial subtitle merging so FunASR's short incremental fragments accumulate without replacing the full current caption.
- Tuned CPU fallback for stability with 800 ms chunks, `[5, 10, 5]` chunk size, queue size 3, and short-phrase partial updates.
- Added runtime logging for chunk inference time, latency, RTF, model/device load, and dropped stale chunks.

### Verification

- Frontend JavaScript syntax check passed for `frontend/app.js` with the bundled Codex Node runtime.
- Python syntax checks passed for `backend/main.py`, `asr/subtitle_state.py`, and the FunASR streaming modules.
- `git diff --check` passed for the candidate code and docs.
- Runtime smoke test passed for `GET /` on port `8000`.
- FunASR route registration was verified for `/ws/asr/funasr`.
- Current local limitation: the active virtual environment still has CPU-only Torch, so FunASR does not use the NVIDIA GPU until CUDA PyTorch is installed.

## 0.2.1-compact-diagnostics-draft-tape - Compact UI, Diagnostics, and Stable Draft Captions

Date: 2026-05-30

### Product

- Simplified the main UI into a more compact, icon-forward operating surface while preserving the large subtitle workspace.
- Added a diagnostics monitor page for backend health, cloud/local notes readiness, meeting-notes progress, quick checks, and recent recordings.
- Kept tester-facing meeting-notes controls provider-neutral: notes engine is shown as `Cloud` / `Local`, and upload routing is controlled by configuration instead of a visible upload-path selector.
- Preserved Tencent Relay as the default private upload bridge for cloud meeting notes.

### UI

- Replaced oversized or inconsistent lower-panel buttons with the same soft capsule style used elsewhere.
- Converted dense Cloud Usage labels to icon-first counters with hover labels, reducing sidebar width pressure.
- Added a small monitor icon that opens diagnostics in a separate tab so checking health does not stop the active subtitle session.
- Reworked local English draft display into a one-line visual tape that fills to the end of the row before restarting from the left edge.

### Technical

- Added `frontend/diagnostics.html`, `frontend/diagnostics.css`, and `frontend/diagnostics.js`.
- The diagnostics live-socket test opens and closes a WebSocket without starting a caption session.
- Added `scripts/translation-quality-preview.py` for offline comparison of direct translation, stabilized English windows, and optional local `qwen3:14b` polishing.
- Versioned frontend assets with `draft-visual-tape-20260530` so browser refreshes load the draft subtitle changes.

### Verification

- Backend Python compile/import checks passed.
- Frontend JavaScript syntax checks passed for `frontend/app.js`, `frontend/ui-editor.js`, and `frontend/diagnostics.js`.
- `scripts/translation-quality-preview.py` syntax check passed.
- `git diff --check` passed.
- Runtime smoke test passed for `GET /api/health` and `GET /static/diagnostics.html` on port `8000`.
- Secret scan found placeholders only and no live Aliyun AccessKey, Tingwu AppKey, relay IP, or Azure secret in candidate committed paths.

## 0.2.0-aliyun-tingwu-qwen-notes - Aliyun Cloud Notes and Qwen Local Refinement

Date: 2026-05-30

### Product

- Added Aliyun Tingwu as the selected cloud meeting-notes path, with Tencent Relay supported as the default private upload bridge.
- Added compact UI controls for meeting-notes engine choice, progress display, diagnostics, and quick access to recordings / minutes folders.
- Kept tester-facing upload-path details out of the main UI; upload routing is controlled by local environment configuration.
- Set the local meeting-notes refinement model direction to Ollama `qwen3:14b` after Gemma and Phi test models were removed locally.

### Technical

- Added Aliyun Tingwu task submission, polling, transcript/minutes rendering, raw result capture, and temporary audio cleanup.
- Added Tencent Relay upload support with byte-level progress reporting and post-task deletion.
- Added `.env.example` settings for local Ollama notes refinement, Aliyun Tingwu, OSS, and relay cleanup.
- Added Aliyun SDK requirements and ignored backend runtime log files.

### Verification

- Python syntax checks passed for `backend/main.py`, `backend/aliyun_tingwu.py`, core backend modules, and `scripts/process-recording.py`.
- Backend import check passed.
- Frontend JavaScript syntax checks passed for `frontend/app.js` and `frontend/ui-editor.js` with the bundled Codex Node runtime.
- `git diff --check` passed.
- Secret scan found placeholders and environment-variable names only; live Aliyun, Azure, relay IP, and AppKey values were not present in committed paths.

## 0.1.12-cloud-branding-notes-fallback - Provider-Neutral UI and Stable Meeting Notes

Date: 2026-05-28

### Product

- Removed provider-specific wording from tester-facing UI. The app now presents the live route, usage panel, status messages, and settings as `Cloud` / `Cloud Usage` / `Cloud Sync`.
- Added Chinese meeting speech as a selectable input language while keeping meeting notes output bilingual, with English first and Chinese reading copy second.
- Reworked local hardware choices into three tester-friendly abbreviation tiers: `iGPU`, `dGPU`, and `HP`, assuming 16GB RAM and choosing the tier by graphics/compute class.
- Kept cloud usage remaining-time sync tied to the configured monthly quota, now set for a 5-hour free monthly allowance.

### Technical

- Added `/api/cloud-usage` as the provider-neutral usage endpoint while keeping `/api/azure-usage` as a compatibility alias.
- Reduced provider leakage in frontend status rendering with a display-layer neutralizer for backend and SDK errors.
- Changed public config payloads to expose `cloud_*` fields instead of returning the full runtime config to the browser.
- Fixed post-meeting local fallback on CUDA-incomplete machines by defaulting meeting-notes ASR to CPU unless `POST_MEETING_ASR_DEVICE` is explicitly set to `cuda` or `auto`.
- Kept generated recordings and notes under `recordings/`, which remains ignored by Git.

### UI

- Updated the top subtitle, speech selector, engine selector, usage panel, delay hints, and progress messages to use neutral cloud wording.
- Preserved the compact left-panel scroll behavior so Meeting Notes and Delay Hint remain reachable on shorter screens.
- Versioned frontend assets with `cloud-branding-20260528` so browser refresh picks up the new labels.

### Verification

- Python syntax checks passed for `backend/main.py`, `backend/cloud_speech.py`, and `scripts/process-recording.py`.
- Frontend JavaScript syntax check passed for `frontend/app.js` with the bundled Node runtime.
- Local runtime smoke test passed for `GET /` on port `8000`.
- `GET /api/cloud-usage` returned a configured account-level usage payload with neutral `source` and `metric` fields.
- `GET /api/config` now returns provider-neutral public config fields.
- A real recording, `rec-0528-131932.wav`, successfully generated `rec-0528-131932.minutes.docx` after the CPU fallback fix, and `/api/open-latest-minutes` opened the Word file.

### Known Limitations

- The internal environment variable names and some internal code identifiers still use the cloud provider's original naming so existing local configuration keeps working.
- Cloud batch speaker separation still requires a configured Blob/SAS batch-storage path; otherwise notes fall back to local transcription without verified speaker separation.
- CPU meeting-notes fallback is slower than CUDA, but avoids the `cublas64_12.dll` failure on tester machines without a complete CUDA runtime.

## 0.1.11-local-t600 - Azure Usage Sync Panel

Date: 2026-05-25

### Product

- Added an Azure Usage panel to the left runtime sidebar.
- The panel shows current-session Azure time and local browser day/month estimates.
- The UI clearly labels local-only estimates so users do not confuse one machine's browser storage with account-wide Azure usage.

### Technical

- Added `GET /api/azure-usage` for optional Azure Monitor synchronization.
- The backend queries Azure Monitor `AudioSecondsTranslated` with a service principal when `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and `AZURE_SPEECH_RESOURCE_ID` are configured.
- Azure Monitor usage responses are cached for 60 seconds.
- `.env.example` now documents Azure Monitor usage-sync variables and optional monthly seconds budget.

### UI

- Reduced usage-card label sizing and shortened labels to prevent two-line wrapping in the compact sidebar.
- The panel switches between local estimate labels and Cloud Day / Cloud Month labels depending on whether Azure Monitor sync is configured.

### Verification

- Backend Python syntax check passed for `backend/main.py`.
- Frontend JavaScript syntax check passed for `frontend/app.js`.
- Local runtime smoke test passed for `GET /` on port `8001`.
- `GET /api/azure-usage` safely returned `configured=false` before Azure Monitor credentials were added.

### Known Limitations

- Azure Speech API keys can run live translation, but cannot read Azure Monitor metrics.
- Account-level cloud usage sync requires a service principal with `Monitoring Reader` access to the Speech resource.
- Until those Azure Monitor variables are configured, day/month numbers remain browser-local estimates.

## 0.1.10-local-t600 - Guided Meeting Flow and Bilingual Word Notes

Date: 2026-05-17

Local-only note: this version is intended for the NVIDIA T600 Laptop GPU machine. Keep it on a dedicated T600 branch unless the project is intentionally converted into a multi-machine profile system.

### Beginner Meeting Flow

- Reworked the main Subtitle Studio controls around a clearer meeting lifecycle: `Start Meeting`, `End Meeting`, then `Open Bilingual Notes`.
- Kept the UI labels in English while simplifying the visible control surface for first-time users.
- Moved lower-frequency tuning controls into `Advanced Settings` so the main workflow stays focused on the next obvious action.
- Kept `End Meeting` visible during live use, because ending the meeting is the moment that triggers post-meeting note generation.

### Realtime Status

- Added a delay hint panel so the user can distinguish cloud setup problems from live caption delay.
- Fixed the misleading state where subtitles were moving but the side panel could still imply that captions were unavailable.
- Updated live subtitle receipt tracking so active captions can report a healthy live state instead of a stale warning.
- Added adaptive local audio chunking: continuous speech still uses the selected max chunk window, while speech followed by a short quiet tail flushes earlier for faster local ASR feedback.
- Added a shared terminology hotword loader for Azure phrase lists, local faster-whisper prompts/hotwords, and post-meeting faster-whisper processing.
- Added a contextual translation buffer that briefly holds short or dependent local utterances, merges nearby context when possible, and flushes quickly when no follow-up arrives.
- Added a stricter default RMS noise gate for `System` input so loopback silence and weak residual audio are less likely to reach local Whisper ASR.
- Switched live local `System` defaults back toward stability: fixed chunks instead of adaptive short flushes, contextual translation merging disabled by default, and local ASR prompt/hotword bias disabled by default.

### Meeting Notes

- Changed post-meeting output from Markdown-first to Word-first for normal use.
- Generated notes now use one `.docx` file with the English professional minutes first and the Chinese reading version second.
- Added a transcript cleanup step for post-meeting processing so raw ASR markup such as language and emotion tags does not leak into the minutes.
- Added a content-quality guard: when the captured transcript is too short or noisy, the minutes clearly say that decisions, actions, and risks cannot be inferred safely instead of inventing them.
- Added topic segmentation to meeting notes. The notes now include a Topic Timeline that creates new topic sections when the transcript changes subject, moves to a new agenda item, or has a meaningful time gap.
- Added a visible meeting-notes progress bar backed by `GET /api/process-recording-progress`, so long post-meeting processing shows upload, transcription, summary, and completion stages.
- Added Azure Batch Transcription as the cloud meeting-notes path. When the live engine is Azure and Blob SAS storage is configured, post-meeting notes use Azure cloud transcription with speaker separation; local engines continue to use local faster-whisper without speaker separation.
- Added a safe fallback when Azure Batch storage is not configured: cloud mode explains the missing Blob SAS setup and uses local notes instead of failing.
- Added chunked faster-whisper transcription for long recordings, with a guard against very short chunks that degrade ASR context and increase repetition.

### Verification

- Frontend JavaScript syntax check passed.
- Backend and recording-processing Python compile checks passed.
- Latest minutes lookup was verified to prefer `.docx` files over `.md` files.
- A sample `.docx` minutes file was rendered successfully, with English on the first page and Chinese on the second page.
- Azure Fast Transcription was tested but rejected diarization on the current endpoint, so Azure Batch remains the selected cloud diarization path.
- Local fallback routing was verified: Azure without `AZURE_BATCH_CONTAINER_SAS_URL` falls back to `faster-whisper`, while local engines always stay local.
- Git diff whitespace check passed before publish.

## 0.1.9-local-t600 - Local ASR Presets for 4GB GPU

Date: 2026-05-08

Local-only note: this tuning is for the NVIDIA T600 Laptop GPU machine. Keep it separate from the GitHub/5070Ti baseline unless the project is intentionally changed to support multiple machine profiles.

### Local ASR

- Added an `ASR Preset` control for local mode.
- `Fast` selects `base.en + int8`.
- `Balanced` selects `small.en + int8` and remains the recommended default for the NVIDIA T600 Laptop GPU with 4GB VRAM.
- `Accurate` selects `small.en + int8_float16` for a higher-quality local experiment when enough GPU memory is free.
- Added `medium.en` to the manual ASR model dropdown for experiments, without making it a default preset.
- Allowed the frontend to send `asr_compute_type` instead of hardcoding local ASR to `int8`.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- CTranslate2 detects one CUDA device and supports `int8`, `int8_float16`, `float16`, and `float32`.
- Torch remains CPU-only in this environment, so Transformers-based MarianMT/NLLB GPU acceleration is still not the recommended optimization path.

## 0.1.8 - Local ASR Quality Tuning

Date: 2026-05-08

### Local ASR

- Changed the default local ASR model from `base.en` to `small.en` for better English meeting transcription.
- Kept `base.en` as the faster manual option in the UI.
- Retuned faster-whisper decoding from single-candidate fastest mode to `beam_size=3` / `best_of=3`.
- Enabled previous-text conditioning inside the ASR call and added a meeting-domain prompt / hotwords list for common technical terms.
- Made VAD slightly less aggressive so speech is less likely to be clipped at short pauses.
- Added light repetition controls to reduce repeated phrases from overlapping chunks.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- Runtime live-audio quality still needs a fresh local test after restarting Subtitle Studio.

## 0.1.7 - Local Sentence Aggregation Tuning

Date: 2026-05-08

### Local Subtitles

- Retuned local Low mode from very short ASR fragments toward fuller sentence aggregation.
- Changed Low mode to use a `2s` chunk, `0.3s` overlap, queue size `2`, `0.9s` sentence pause, and a longer word/time threshold before Chinese translation.
- Changed Steady mode to use a `3s` chunk, `0.5s` overlap, queue size `2`, `1.2s` sentence pause, and a more conservative sentence threshold.
- Added backend protection so very short idle fragments are held briefly instead of being translated immediately.
- Raised the punctuation-based sentence completion threshold so unreliable local ASR punctuation does not split tiny fragments too early.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- Aggregator simulation confirmed a short fragment such as `goes up.` is held and merged with following text before translation.

## 0.1.6 - Local Secret Hygiene Closeout

Date: 2026-05-08

### Security

- Removed an accidental local text dump containing account/session data from the project workspace.
- Added the accidental dump filename to `.gitignore` so it is less likely to be synced or committed later.
- Reconfirmed that `.env` files remain ignored while `.env.example` stays shareable.

### Documentation

- Updated the project closeout pointer in `README.md`.
- Reinforced the closeout skill with a reminder not to keep copied browser session dumps, access tokens, or account exports in the repository.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- Git CLI sync/status check could not run in this shell because `git` is not available in `PATH`.

## 0.1.5 - System Loopback and Local Realtime Tuning Closeout

Date: 2026-05-04

### Frontend

- Restored the local English upper area to a continuous reading flow instead of separate stable-row cards.
- Kept the lower local English draft pane for fast draft visibility while ASR is still forming the utterance.
- Tightened the local latency presets so `Low` now drives a `1s` chunk and `Steady` now targets `1.5s`.
- Sent additional local realtime tuning values from the browser to the backend so chunk overlap, queue pressure, and utterance segmentation all match the selected latency preset.

### Backend

- Updated system-audio capture to prefer loopback from the current default Windows playback device when available, with Stereo Mix / speaker-monitor fallback.
- Added `soundcard` as the preferred Windows loopback path for `Input: System`.
- Tuned local chunking, overlap, queue size, and utterance segmentation for earlier subtitle emission.
- Added local English cleanup for noisy punctuation sequences such as repeated `///` and excessive ellipses.
- Completed the local dependency set for `faster-whisper`, Argos, MarianMT, and NLLB startup.

### Product

- Azure Cloud remains the recommended production route for real-time use.
- Argos is now the recommended local engine when realtime behavior matters.
- MarianMT and NLLB remain available for local quality comparison, but on this machine they are not the recommended real-time choice.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- Azure `System` mode was manually verified after the loopback change.
- Local Argos route was verified after dependency completion.
- MarianMT and NLLB import/model startup paths were verified, but their practical real-time usability remains limited on this environment.

## 0.1.4 - Local Split Transcript Closeout

Date: 2026-05-04

### Frontend

- Kept Azure mode on the original single bilingual subtitle monitor and scroll-history strategy.
- Reworked local mode into three reading zones: stable English context, live English draft, and complete Chinese translation.
- Changed the local English context and Chinese translation panes from scrolling subtitle rows to continuous forward text blocks.
- Kept the local English draft pane separate so ASR updates can remain responsive while Chinese waits for a fuller utterance.
- Versioned the main static assets so browser refresh picks up the local split transcript update.

### Backend

- Kept `LocalUtteranceAggregator` as the local sentence/utterance boundary layer.
- Made local translation jobs run through a background queue that does not block the English draft path.
- Added safer translation-worker exception handling and task cleanup on stop/disconnect.

### Product

- Local mode now optimizes for watchability: immediate English draft, readable English context, and slightly delayed complete Chinese.
- Azure remains the recommended lowest-latency mode and keeps its existing UI behavior.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- GitHub sync passed on branch `codex/realtime-translator-closeout`.
- Runtime audio behavior still depends on selecting the correct input source (`System` for computer audio, `Mic` for microphone) and valid Azure credentials for cloud mode.

## 0.1.3 - Spanish Source Language and Compact Local Layout

Date: 2026-05-04

### Frontend

- Reduced subtitle row padding and stream spacing so more subtitle history fits in the monitor.
- Changed subtitle text to fixed source/translation sizes; short and long subtitles no longer use different length-based font sizes.
- Increased the compact English source subtitle default from 12px to 13px for readability.
- Updated the UI editor subtitle-size defaults for the compact subtitle layout.
- Added a Local Latency control with Low and Steady presets; Low selects a 2s local chunk.
- Split subtitle rendering by engine: Azure keeps the existing single bilingual monitor, while local engines use separate English live transcript and Chinese translation monitors.
- Local English monitor now keeps recent stable English context and one current draft row instead of showing only the latest draft.

### Backend

- Reworked local mode around a `LocalUtteranceAggregator`: ASR chunks update a continuous English utterance row, and only ready utterances are translated into Chinese.
- Low latency local runs with shorter overlap and smaller audio queues while preserving ready translation jobs so completed sentences are not dropped.

### Product

- Added Spanish-to-Chinese alongside the existing English-to-Chinese workflow.
- Added a source language selector on the main Subtitle Studio toolbar.
- Kept Azure Cloud usable as the primary route even when local `faster-whisper` dependencies are not ready on Windows.

### Backend

- Allowed `spa_Latn` source language through runtime config instead of forcing English.
- Mapped Spanish local ASR to Whisper `es` and multilingual `base` / `small` models.
- Mapped Azure Spanish mode to `es-ES -> zh-Hans`.
- Added Argos, MarianMT, and NLLB routing for Spanish-to-Chinese local translation.
- Delayed importing `faster-whisper` until local ASR is selected, so Azure-first startup no longer hard-fails on missing local ASR packages.

### Documentation

- Updated README and architecture notes to explain the Azure-first startup path and the lazy local-ASR dependency load.

### Verification

- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- Spanish config mapping check passed for `spa_Latn -> es-ES`, Whisper `es`, and multilingual ASR model selection.
- Local runtime smoke test passed for `GET /` and `GET /api/health` on `http://127.0.0.1:8000`.
- Runtime audio behavior still depends on local audio routing and valid Azure credentials.

## 0.1.2 - Visual UI Editor Closeout

Date: 2026-04-30

### Product

- Added a browser-based visual UI editor for quick local appearance tuning.
- Kept the main subtitle workflow unchanged: Azure Cloud remains the primary low-latency route and local engines remain fallback options.
- Preserved the fast/direct translation model with no MiniMax, Balanced, or Quality controls.

### Frontend

- Added `/static/ui-editor.html` with live preview controls for background color, panel color, accent/subtitle color, text color, subtitle font sizes, left panel width, corner radius, and background decoration.
- Added `frontend/ui-editor.css` and `frontend/ui-editor.js`.
- Main page now loads saved editor choices from browser `localStorage` using the `subtitleStudioUiThemeCompact20260502` key.
- Added a `UI Editor` entry button to the main toolbar.
- Removed the extra raised shell behind the topbar while preserving the individual brand and toolbar cards.
- Restored the main subtitle monitor outer shell after visual review because the page looked weaker without it.

### Documentation

- Updated README, product requirements, technical architecture, UI style notes, QA checklist, and the project-local closeout skill.

### Verification

- Frontend JavaScript syntax check passed for `frontend/app.js` and `frontend/ui-editor.js` with the bundled Node runtime.
- Backend compile and import checks passed.
- Local health endpoints responded on ports `8000` and `8001`.
- Full live audio behavior still depends on local audio device routing and valid Azure credentials.

### Known Limitations

- UI editor saves to the current browser only; it does not yet write accepted styles back into `frontend/style.css`.
- Browser cache may require `Ctrl + F5` after static asset changes.
- System audio still depends on Windows exposing a monitor input or Stereo Mix.

## 0.1.1 - Fast-Only Soft UI Closeout

Date: 2026-04-30

### Product

- Confirmed Azure Cloud as the primary live subtitle route and local engines as fallback options.
- Removed MiniMax polishing from the active product path.
- Removed Balanced and Quality modes so the app has one fast/direct translation behavior.

### Frontend

- Kept the selected Soft UI Evolution / Focus Display interface.
- Added a small red operating lamp in the logo block.
- The lamp remains dim red when stopped, pulses slowly when running or connecting, and stays red on error.
- Added static asset versioning for the lamp update so the browser does not keep stale CSS.

### Backend

- Removed MiniMax text polishing module, queue, payload fields, and HTTP dependency.
- Removed runtime handling for quality and latency mode switches.
- Kept Azure streaming and local fallback paths.

### Verification

- Python backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed.
- Live audio behavior still depends on local audio device routing and valid Azure credentials.

### Known Limitations

- System audio still depends on Windows exposing a monitor input or Stereo Mix.
- Azure cloud mode requires `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION`.
- Current paragraph detection is pause-based, not true speaker diarization.

## 0.1.0 - Working Prototype Closeout

Date: 2026-04-29

### Product

- Completed a usable local browser subtitle studio.
- Main workflow supports microphone or system audio, Azure streaming translation, and bilingual subtitle display.
- Removed MiniMax polishing from the active product path after live testing showed limited value for this workflow.
- Fixed the app to a single fast translation mode.

### Backend

- Added Azure Speech Translation streaming route.
- Kept local fallback route with faster-whisper and local translation engines.
- Removed the MiniMax polish queue, HTTP dependency, and text polishing module.
- Removed Balanced/Quality mode handling from the runtime path.
- Added lightweight paragraph turn detection.
- Added performance payloads for subtitle events.

### Frontend

- Redesigned into a compact SaaS-style Subtitle Studio.
- Updated the formal app UI to the selected Soft UI Evolution `Focus Display` direction with a larger subtitle monitor, recessed subtitle stream, raised controls, and light gray-blue palette.
- Added fixed subtitle monitor.
- Added internal subtitle history scrolling.
- Added bottom auto-follow behavior that pauses when the user scrolls upward.
- Added minute-second timestamp formatting.

### Verification

- Python backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed.
- Full live audio verification still depends on local microphone/system audio and active Azure credentials.
- GitHub Desktop is installed, but command-line `git` is not available in this shell.

### Known Limitations

- System audio depends on Windows exposing a usable monitor input or Stereo Mix.
- Azure credentials must be provided through environment variables for cloud mode.
- MiniMax is no longer part of this version.
- Current paragraph detection is pause-based, not true speaker diarization.
- Local MarianMT still uses Transformers, not CTranslate2 int8.
