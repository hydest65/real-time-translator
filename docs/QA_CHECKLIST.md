# QA Checklist

## Windows 原文／译文显示开关 0.4.6 — 2026-10-03

完整包的原生窗口验收 37 项通过，完整进程退出并重开后 39 项通过。窗口测试使用隔离配置与合成字幕，不启动真实音频或付费识别；原有配置目录恢复继续保留。

- [x] SET 中 SRC / TR 为独立图标开关，默认均开启，完整模式和字幕模式均可操作，具备标题与 `aria-pressed` 状态。
- [x] 原文单独显示、译文单独显示及两项隐藏即时生效；已有及新字幕继续保存在 DOM 中，切换不改变会话状态。
- [x] 同时隐藏显示中文提示。420 × 240 的完整、字幕模式中提示覆盖字幕区域，不新增网格行或移出窗口；显示按钮均可滚动到达。
- [x] 原生保存只接受两项布尔字段，字符串及数字不覆盖有效设置；最终原文隐藏、译文显示的组合在完整退出重开后恢复。
- [x] 字号、颜色、透明度、历史浏览和状态动效回归通过；CFG 打开只滚动设置面板，标题栏提示保持可见。
- [x] 原生验证中的 fetch 替身传递恢复浏览器接收者，避免定时健康检查误报服务不可达；没有通过放宽提示可见性断言掩盖失败。
- [x] 30 项单元测试、语法及差异检查通过；包扫描 971 条目没有私有配置、录音或私钥。

## Windows 桌面配置目录迁移 0.4.5 — 2026-10-02

本轮复现了普通 Windows 桌面重开后提示缺配置的问题，确定原因为 Codex 的 MSIX 文件重定向。同一 `%APPDATA%` 文本路径在两种启动环境下指向不同物理文件；对实时后台日志句柄和文件 ID 的比较确认此差异。下方旧版检查属于 Codex 启动环境或隔离配置，不能证明普通桌面启动使用同一配置。

- [x] 普通桌面实际配置文件为 131 字节，区域和密钥均为空；Codex 的明确影子目录中保存了 241 字节的完整配置。诊断仅输出路径、文件身份、长度及是否配置，不输出密钥。
- [x] 使用交付源码中的 `recoverSavedCloudConfig` 将现有配置迁移到真正的用户目录。原空配置已就地备份，原影子配置 SHA256 未改变；真实配置迁移后为已配置。
- [x] 同一迁移再次执行，完整主配置 SHA256 保持不变。已有完整配置或冲突的部分设置均不会被旧配置覆盖；只恢复固定三项云设置，保留原注释和其他内容。
- [x] 冻结后端连续两次独立启动读取同一个真实用户配置文件，`cloud_configured=true`；该验证没有修改配置或启动音频。
- [x] 30/30 单元测试通过，包括新增 8 项配置迁移检查和 3 项实际启动迁移函数检查，覆盖完整主配置保护、冲突保护及安全更新；JavaScript 语法和差异检查通过。
- [x] 0.4.5 ZIP 全新解压后，隔离配置的原生窗口验收 33 项通过；完整退出重开后 34 项通过，覆盖原有设置、字体颜色、状态动画及配置预检。
- [x] 0.4.5 ZIP 971 个条目复查通过，没有 `.env`、录音或私钥，仅包含白名单公开证书。
- [x] 旧实例结束后已打开 0.4.5，配置状态为 true；该次 Codex 启动仍使用重定向目录，普通桌面路径的配置恢复以真实文件和独立后端读取为证据。未把此启动声称为真实付费识别成功。

本轮无需重新输入 API；没有进行真实音频或付费云识别。

## Windows 桌面配置恢复与状态动效 0.4.4 — 2026-10-02

完整 ZIP 全新解压后的原生窗口验收 33 项通过，完整进程重启后 34 项通过，单元测试 19/19。状态图标与配置预检均使用受控状态或合成连接，本轮没有启动真实音频或付费云识别。

- [x] 读取配置尚未完成时点击开始会等待；重复点击仅创建一个模拟字幕连接，不弹出密钥表单。
- [x] 请求、响应、JSON、类型及超时失败均可重试；失败保留字幕历史和原录音路径，不启动音频。
- [x] 已保存本机密钥但后端状态未加载时提示重新打开应用，明确无需重填密钥；只有后端与本机均确认缺少配置时才打开 CFG。
- [x] 本机 `.env` 已保存配置没有被改动；输入框空白用于隐藏并保留现有密钥。
- [x] 字幕模式左上角波形：健康服务与字幕连接、活动会话同时成立时绿色波形动画运行；连接中蓝色，未启动灰色静止，异常红色静止。
- [x] 减少动画偏好会关闭波形 / 呼吸动画，保留状态颜色和中文辅助标签。
- [x] 原文、译文颜色和字号、半透明背景、最小窗口工具栏、SET / CFG、历史跟随回归通过；原生滚轮输入测试先聚焦字幕区域。
- [x] ZIP 972 个唯一条目扫描通过，没有私有配置、录音或私钥；仅包含白名单公开根证书。
- [x] 启动脚本语法检查通过，按实际版本选择最新应用；桌面固定快捷方式避免每次选不同便携目录。

固定启动器从 Codex 调用时曾打开 0.4.4 窗口，`/api/config` 确认云配置与密钥存在；启动前后所读 `.env` SHA256 一致。0.4.5 排查确认该读取属于 MSIX 影子目录，不能作为普通 Windows 桌面重开已恢复配置的证明。该读取检查没有开始新录音或云识别。

## Windows 桌面字体颜色 0.4.3 — 2026-10-02

新增原文、译文独立色块选择器及六位 HEX 输入。颜色立即应用于已有和新出现的字幕；本机 `display.json` 保存两项颜色，跨服务端口及完整应用重启恢复。RST 同时恢复默认字号与颜色。最终完整 ZIP 全新解压后，原生验收 28 项通过；完整退出重开后 29 项全部通过。

- [x] 原文颜色选择器及译文 HEX 输入即时生效，原文蓝色 `#345F93`、译文紫色 `#7B3F69` 独立显示；外围控件与背景不透明度不受影响。
- [x] 不完整 HEX 输入及非法原生桥接颜色值保留上一次有效颜色；输入框失焦恢复有效色值。
- [x] RST 恢复并保存默认原文 `#68788C`、译文 `#283445`。
- [x] 新字幕、英文连续原文、连续译文均使用各自颜色；普通与字幕模式复用同一设置。
- [x] 页面重载、完整进程重启及随机服务端口变化后恢复原文 22 px、译文 48 px、两项自定义颜色、背景 55%、420 × 240 和字幕模式。
- [x] 两种 420 × 240 最小窗口中，原文 / 译文色块及 HEX 输入框均可滚动到达并操作；SET / CFG、隐藏滚动条和历史浏览回归通过。
- [x] 单元测试 10/10、JavaScript 语法及 `git diff --check` 通过；独立源码审查未发现需修复问题。
- [x] 最终 ZIP 971 项扫描通过，私有配置、录音及私钥为 0；仅包含白名单中的两份公开根证书。

颜色与界面验证使用隔离配置、合成字幕，未启动真实音频或付费云识别。

## Windows 桌面配置读取 0.4.2 验证 — 2026-10-02

原问题已在隔离环境复现并修复。完整 ZIP 全新解压后，在继承空白 Speech key / region、文件使用非空测试值及 BOM / 引号的环境中，原生验收 21 项通过；完整退出重开后 22 项全部通过。以下为本次配置读取与界面回归记录。

- [x] 隔离启动验证本机文件配置覆盖继承空白值；配置单元测试验证 key / region / phrase 替换旧值、空白值和大小写冲突继承值。
- [x] 从工作进程启动时传入 `SUBTITLE_STUDIO_ENV_FILE` / `SUBTITLE_STUDIO_DATA_DIR`，隔离配置文件与数据目录选择一致。
- [x] UTF-8 BOM、单 / 双引号解析测试通过，CFG 与后端 `cloud_configured` 状态一致。
- [x] 缺配置点击播放，CFG 直接打开并显示中文提示，没有字幕 WebSocket 或录音启动，现有字幕历史保留。
- [x] 用户现有 `.env` 只读启动新版隔离窗口，后端 `cloud_configured=true`、桌面配置 true、界面 Ready；SHA 校验确认用户配置未改。
- [x] 完整便携目录及 ZIP 已重新构建，全新解压启动和完整重开验收通过，配置状态及显示设置恢复。
- [x] 0.4.1 淡色布局、图标、SET / CFG 可达、字幕滚轮 / 键盘浏览和历史跟随回归通过。
- [x] 单元测试 10/10（配置 6 项、几何 4 项）、JavaScript 语法和 `git diff --check` 通过。
- [x] 0.4.2 便携目录扫描及 ZIP 971 个条目复查通过，私有配置 / 录音 / 私钥为 0；精确白名单保留 certifi 与 gRPC 两份公开根证书，均不含私钥，`cloud-config.cjs` 已包含在包中。

本轮只验证配置读取与界面，没有验证真实云识别、音频授权或付费识别；Ready 和配置状态为 true 均作为读取结果记录。

## Windows 桌面 UI 0.4.1 验证 — 2026-10-02

完整 ZIP 全新解压后的原生验收 19 项通过；使用同一隔离配置完整退出并重开后，20 项全部通过。以下记录对应 0.4.1，0.4.0 历史记录另列。

- [x] 完整 Windows x64 便携目录和 ZIP 已构建，全新解压后的独立 EXE 启动和原生界面验收通过。
- [x] 完整界面与字幕模式视觉检查：雾白半透明背景、深灰正常字重字幕、淡蓝 PIN 激活状态，功能按键使用细线图标。
- [x] 图标映射、功能标签、中文及英文缩写悬停提示通过：ST 播放、SP 方块、CAP / UI 字幕窗 / 布局、SET 调节、PIN 图钉、CFG 钥匙、LOG 文件夹、RST / CHK 刷新、SAV 保存。
- [x] 字幕区域没有可见滚动条或预留滚动槽，原生滚轮可浏览历史；聚焦后 PageUp 向上翻页、End 返回末尾通过。
- [x] 向上浏览时新字幕不跳回底部，回到末尾后自动跟随恢复；长连续英文字幕无横向溢出。
- [x] 完整界面与字幕模式的 SET 按需展开 / 收起及 CFG 展开通过；两种 420 × 240 模式下区域输入和保存按钮均可到达。
- [x] 错误状态使标题栏增高后，SET 浮层仍在窗口范围内。
- [x] 同一隔离配置完整退出并重开后，恢复 420 × 240、原文 22 px、译文 48 px、背景不透明度 55% 和字幕模式。
- [x] 窗口几何测试 4/4、JavaScript 语法、PowerShell 解析及 `git diff --check` 通过。
- [x] 公开证书白名单包扫描通过，未发现 `.env`、密钥、录音或离线模型。

补充人工验收（本轮未执行）：

- [ ] 使用真正的鼠标拖动移动窗口和八向调整尺寸。
- [ ] 检查原文与译文分别为 10 / 160 px 的极限字号，确认长字幕和设置仍可访问。
- [ ] 检查 15% / 100% 背景不透明度及不同桌面底图上的可读性。
- [ ] 真实麦克风 / 系统音频、实时字幕、录音保存及有效配置下的付费 Cloud 识别；本轮使用样例字幕，未进行真实音频和付费识别验收。

## Windows 桌面包 0.4.0 历史验证 — 2026-10-02

- 独立打包后端启动、页面加载和正常退出通过；退出后所属端口不再监听。
- 实际 Electron 窗口检查通过：置顶切换、650 × 340 尺寸调整、420 × 240 最小尺寸、字幕模式显示设置。
- 原文 22 px、译文 48 px 独立设置及背景 55% 不透明度检查通过；文字 opacity 为 1。
- 窗口截图空白背景像素 alpha 为 140/255（约 55%），圆角外侧 alpha 为 0，确认透明背景实际生效。
- 完整退出并再次启动后，窗口尺寸、字号、背景不透明度及字幕模式恢复通过。
- 最终 ZIP 全新解压后的独立 EXE 启动和桌面界面检查通过。
- Python / JavaScript 语法、PowerShell 解析、窗口几何测试 4/4 和 `git diff --check` 通过。
- 应用包不含 `.env`、私钥、录音或离线模型，仅保留 SDK 所需公开根证书。
- 截图字幕为测试样例；本次未启动真实麦克风、系统音频或付费云端识别。

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

Current closeout result on 2026-07-20:

- Python syntax checks passed for changed backend modules and `scripts/process-recording.py`.
- Frontend JavaScript syntax checks passed for `frontend/app.js`, `frontend/ui-editor.js`, and `frontend/diagnostics.js` with the bundled Codex Node runtime.
- PowerShell parse checks passed for `scripts/start-server.ps1`, `scripts/start-remote-server.ps1`, `scripts/launch-app.ps1`, and `scripts/cleanup-local-artifacts.ps1`.
- `git diff --check` passed with GitHub Desktop's bundled Git.
- Secret scan found placeholders and documented environment-variable names only, not live Azure, Aliyun, Tencent Relay, SAS, or app secrets.
- Cloud quota smoke tests passed for quota exhaustion, remaining time display payloads, active-session accounting, and backend ledger updates.
- Runtime smoke test passed for `GET /api/health` and the main page on a temporary local port.
- Remote tester mode is code-ready, but real external testing still requires an HTTPS tunnel, VPN, or authenticated reverse proxy so browser audio capture is allowed and the center backend is not exposed openly.
- Default dependencies are cloud-first/lightweight; install `backend\requirements-local.txt` only when local/offline models are needed.

Current closeout result on 2026-05-17:

- This closeout is local-only for the T600 4GB GPU machine and should not be treated as the GitHub/5070Ti baseline.
- Frontend JavaScript syntax check passed after the guided meeting-flow UI changes.
- Backend and recording-processing Python compile checks passed.
- Latest minutes lookup prefers generated `.minutes.docx` files.
- A generated `.minutes.docx` file rendered successfully with English and Chinese sections in one document.
- Post-meeting transcript cleanup removes raw ASR markup before minutes are written.
- Backend compile check passed.
- Backend import check passed.
- Frontend JavaScript syntax check passed with the bundled Node runtime.
- UI editor JavaScript syntax check passed with the bundled Node runtime.
- Default local ASR tier now reports `iGPU` with `base.en`, CPU, and `int8`.
- faster-whisper quality parameters are accepted by the installed package signature.
- ASR Preset control maps `iGPU`, `dGPU`, and `HP` to local ASR model / device / compute-type choices.
- Hardware tier guidance assumes tester machines have 16GB RAM; choose the tier by graphics/compute class.
- CTranslate2 CUDA check sees one CUDA device on the NVIDIA T600 Laptop GPU.
- Torch CUDA remains unavailable, so MarianMT/NLLB should still be treated as CPU-bound unless the environment is changed.
- Local sentence aggregation simulation passed: short ASR fragments are held and merged before Chinese translation.
- Git CLI status/sync check could not run because `git` is not available in this PowerShell environment.
- Accidental local text dump containing account/session data was removed from the workspace and added to `.gitignore`.
- Local runtime smoke test passed for `GET /` and `GET /api/health` on port `8000`.
- Azure startup path now works without importing `faster-whisper` until a local engine is selected.
- `Input: System` now prefers current-default-device loopback before Stereo Mix fallback.
- Local realtime defaults now use `2s` / `3s` chunk behavior depending on latency preset, with fuller sentence aggregation before Chinese translation.
- Argos remains the recommended local real-time engine on this environment.

Current closeout result on 2026-05-24:

- Python syntax checks passed for backend modules and post-meeting scripts.
- Frontend JavaScript syntax check passed for `frontend/app.js`.
- `git diff --check` passed.
- Secret scan found only placeholders and documented environment-variable names, not live tokens or SAS signatures.
- Azure Batch configuration smoke test currently reports `azure_batch_configured=False`, so this machine will use local post-meeting fallback until `AZURE_BATCH_CONTAINER_SAS_URL` is added.
- Selected-engine meeting-notes routing was verified: Azure mode attempts Azure Batch when configured, and local engines use local faster-whisper without speaker separation.
- Local fallback regression test completed on a real WAV recording and did not create a `.speakers.md` file for unverified pause-based turns.
- Azure Fast Transcription diarization was tested and returned an endpoint-side 400 response, so it is not the chosen diarization route.

Current closeout result on 2026-05-25:

- Backend Python syntax check passed for `backend/main.py`.
- Frontend JavaScript syntax check passed for `frontend/app.js` with the bundled Node runtime.
- Local runtime smoke test passed for `GET /` on port `8001`.
- `GET /api/azure-usage` returned a safe `configured=false` payload when Azure Monitor service-principal variables were not configured.
- `.gitignore` excludes `.env` and `.env*`, while keeping `.env.example` tracked.
- Azure Speech live credentials can remain local in `.env`; Azure Monitor sync still requires `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and `AZURE_SPEECH_RESOURCE_ID`.

Current closeout result on 2026-05-28:

- Python syntax checks passed for `backend/main.py`, `backend/aliyun_tingwu.py`, core backend modules, and `scripts/process-recording.py`.
- Backend import check passed.
- Frontend JavaScript syntax checks passed for `frontend/app.js` and `frontend/ui-editor.js` with the bundled Codex Node runtime. The system `node.exe` was blocked by Windows access policy, so the bundled runtime was used.
- `git diff --check` passed.
- Secret scan found no live Aliyun AccessKey, Tingwu AppKey, relay IP, or Azure secret in committed paths.
- Ollama local notes default is `qwen3:14b`; `gemma4:e4b` and `phi3:mini` were removed locally.
- Aliyun Tingwu cloud notes support now includes OSS or Tencent Relay upload, diagnostics, progress reporting, raw result payloads, Markdown/DOCX output, and temporary audio cleanup.

Current closeout result on 2026-05-30:

- Backend Python syntax/import checks passed.
- Frontend JavaScript syntax checks passed for `frontend/app.js`, `frontend/ui-editor.js`, and `frontend/diagnostics.js`.
- `scripts/translation-quality-preview.py` syntax check passed.
- `git diff --check` passed.
- Runtime smoke test passed for `GET /api/health` and `GET /static/diagnostics.html` on port `8000`.
- Secret scan found placeholders only and no live Aliyun AccessKey, Tingwu AppKey, relay IP, or Azure secret in candidate committed paths.
- Manual visual checks performed during development: compact UI, diagnostics entry, diagnostics page, and local draft visual tape behavior were inspected in the browser.
- Known local model limitation: `qwen3:14b` is installed, but a polish test can fail on this machine when Ollama reports insufficient available memory. This does not block the live subtitle path.

Current closeout result on 2026-06-04:

- Python syntax check passed for `backend/notes_quality.py`.
- Speaker-evidence smoke test passed on `recordings/rec-0603-220033.transcript.md`: the extractor kept substantive speaker-attributed discussion and filtered short greetings/acknowledgements.
- `git diff --check` passed with GitHub Desktop's bundled Git.
- Runtime health check passed for `GET /api/health` on port `8000`.
- UI cleanup is limited to `frontend/index.html` and `frontend/style.css`: the Notes context input block is removed, the left side-panel shell is transparent, and the subtitle workspace gets more width.
- Full local notes regeneration with Ollama `qwen3:14b` could not be completed in this closeout because Ollama reported insufficient available memory (`6.3 GiB` required, `4.3 GiB` available). Retry after freeing memory or switching to a smaller notes rewrite model.

Current closeout result on 2026-06-03:

- Frontend JavaScript syntax check passed for `frontend/app.js` with the bundled Codex Node runtime.
- Python syntax checks passed for `backend/main.py`, `asr/subtitle_state.py`, and the FunASR streaming modules.
- `git diff --check` passed.
- Runtime smoke test passed for `GET /` on port `8000`.
- `/ws/asr/funasr` route registration was verified.
- Local Chinese FunASR mode now shows startup progress text, live-window captions, and manual meeting-notes behavior after End Meeting.
- Current performance limitation: the venv has CPU-only Torch, so CUDA acceleration requires installing CUDA-enabled PyTorch.

- Python syntax checks passed for `backend/main.py`, `backend/cloud_speech.py`, and `scripts/process-recording.py`.
- Frontend JavaScript syntax check passed for `frontend/app.js` with the bundled Node runtime.
- Local runtime smoke test passed for `GET /` on port `8000`.
- `GET /api/cloud-usage` returned a configured account-level payload with neutral `source=cloud_usage` and `metric=audio_seconds`.
- `GET /api/config` returned only provider-neutral public config fields.
- Frontend visible HTML text no longer contains provider-specific names.
- Meeting-notes generation was regression-tested on `recordings/rec-0528-131932.wav` and produced `rec-0528-131932.minutes.docx`.
- `/api/open-latest-minutes` opened the generated Word notes file.
- Post-meeting local fallback now defaults to CPU to avoid CUDA DLL failures on tester machines; set `POST_MEETING_ASR_DEVICE=cuda` only on machines with a complete CUDA runtime.
- GitHub Desktop's bundled Git was found and used for repository checks because `git` is not available in the default PowerShell PATH.

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

- Source: English, Input: System, Engine: Azure Cloud.
- Source: Spanish, Input: System, Engine: Azure Cloud.
- Source: Japanese, Input: Mic or System, Engine: Azure Cloud.
- Input: Mic, Engine: Azure Cloud, when room or headset microphone audio is needed.
- Remote tester Cloud path: open the hosted HTTPS page, start with `Input: Mic`, verify browser permission prompt, live subtitles, quota timer, and local recording creation on the center backend.
- Source: English, ASR: small.en, Engine: Argos, Latency: Low, Chunk: 2s.
- Source: Spanish, Engine: Argos or NLLB, if offline/local fallback is needed.

## Manual UX Checks

- Start button connects and changes status.
- Stop button stops streaming and returns to stopped state.
- Red status lamp is dim but visible when stopped.
- Red status lamp pulses slowly while running or connecting.
- Live subtitles appear without waiting for full paragraphs.
- In local Low latency mode, the English upper area keeps continuous readable context and begins scrolling only after the pane fills.
- In local Low latency mode, the Chinese monitor appends complete translated sentences as a continuous text flow.
- Azure mode keeps one bilingual subtitle monitor.
- Azure mode still uses subtitle rows, internal scroll history, and bottom auto-follow.
- English/Spanish local mode shows source context and Chinese complete translations as separate panes.
- Chinese local FunASR mode shows recent live Chinese captions without the old draft pane.
- `Input: System` can capture the current active Windows playback device when loopback is available.
- Switching Source to Spanish updates the subtitle direction and still starts the stream.
- Final subtitles enter history.
- No MiniMax, Balanced, or Quality mode controls are visible.
- Browser Azure subtitle monitor has its own right-side scrollbar; the desktop UI hides the scrollbar while retaining history scrolling.
- In Azure mode, scrolling upward does not prevent new subtitles from arriving.
- In Azure mode, returning to the bottom resumes auto-follow.
- Long subtitles do not overflow the monitor.
- Short and long subtitles use the same fixed source/translation font sizes.
- Subtitle row padding and spacing stay compact enough to show more history.
- UI Editor opens at `/static/ui-editor.html`.
- UI Editor changes update the preview immediately.
- Clicking "save" stores the theme and the main page applies it after reload.
- Background decoration can be shown or removed through the editor.
- Transcript export stays disabled before final subtitle text is captured.
- Transcript export downloads the full final subtitle list, not just the visible rolling history.
- Minutes export opens as a Word `.docx` file for normal review.
- Minutes export includes English minutes first and Chinese minutes second in the same document.
- Azure usage panel labels local browser estimates clearly when Azure Monitor sync is not configured.
- Azure usage panel should switch to Cloud Day / Cloud Month after `/api/azure-usage` returns a configured Azure Monitor payload.
- No raw ASR language/emotion tags appear in the generated minutes.
- Speaker labels in exports are pause-based turns and are not treated as verified diarization.
- Starting a session creates a local WAV file in `recordings/`.
- Pressing Stop and Start again within 5 minutes appends to the same WAV file instead of splitting the meeting audio.
- Pressing End Meeting closes the recording session so the next Start creates a new WAV file.
- Pressing End Meeting does not auto-run meeting-notes processing; notes are built manually from the Notes tools.
- `recordings/` is ignored by Git.
- `scripts/diarize-recording.py` exits with a clear setup message if `pyannote.audio` or `HF_TOKEN` is missing.
- `scripts/process-recording.py` can generate `.transcript.md` and `.minutes.md` from a WAV file.
- Generated `.minutes.md` files include readable sections for summary, key discussion, decisions, action items, risks/open questions, speaker notes, and full transcript.
- `scripts/process-recording.py` supports `--quality fast`, `--quality balanced`, and `--quality high`.
- `scripts/process-recording.py --asr-engine funasr` uses optional Alibaba/FunASR post-meeting ASR when `funasr` is installed.
- `scripts/process-recording.py --diarize` can add anonymous speaker clusters when pyannote and `HF_TOKEN` are available.
