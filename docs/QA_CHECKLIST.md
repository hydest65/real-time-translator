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
