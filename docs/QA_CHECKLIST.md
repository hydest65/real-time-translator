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
- Default local ASR tier now reports `1 核显` with `base.en`, CPU, and `int8`.
- faster-whisper quality parameters are accepted by the installed package signature.
- ASR Preset control maps `1 核显`, `2 独显`, and `3 工作站` to local ASR model / device / compute-type choices.
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
- Input: Mic, Engine: Azure Cloud, when room or headset microphone audio is needed.
- Source: English, ASR: small.en, Engine: Argos, Latency: Low, Chunk: 2s.
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
- Pressing End Meeting runs post-meeting processing for the latest `recordings/session-*.wav` file and does not select append-test recordings.
- `recordings/` is ignored by Git.
- `scripts/diarize-recording.py` exits with a clear setup message if `pyannote.audio` or `HF_TOKEN` is missing.
- `scripts/process-recording.py` can generate `.transcript.md` and `.minutes.md` from a WAV file.
- Generated `.minutes.md` files include readable sections for summary, key discussion, decisions, action items, risks/open questions, speaker notes, and full transcript.
- `scripts/process-recording.py` supports `--quality fast`, `--quality balanced`, and `--quality high`.
- `scripts/process-recording.py --asr-engine funasr` uses optional Alibaba/FunASR post-meeting ASR when `funasr` is installed.
- `scripts/process-recording.py --diarize` can add anonymous speaker clusters when pyannote and `HF_TOKEN` are available.
