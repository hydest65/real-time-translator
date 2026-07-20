# Technical Architecture

## Runtime Routes

### Cloud Route

```text
Browser audio capture or server-machine audio capture
  -> cloud speech translation streaming session
  -> websocket_push_worker
  -> browser subtitle monitor
```

This is the preferred low-latency route. The UI presents this route with provider-neutral `Cloud` wording for testers while preserving the existing backend configuration contract.
For remote tester mode, the tester's browser captures audio, downsamples it to 16 kHz mono PCM16, sends it over the subtitle WebSocket, and the center backend pushes that audio into the cloud speech stream. This keeps the cloud key on the center backend instead of distributing it to testers. For local single-machine operation, the backend can still capture local `System` or `Mic` audio directly.
The source language selector maps English to `en-US`, Spanish to `es-ES`, Japanese to `ja-JP`, and Chinese to `zh-CN`; the target is fixed to `zh-Hans`.
Chinese meeting speech maps to `zh-CN` for transcription and still produces bilingual meeting notes for review.

### Local Fallback Route

```text
audio_capture_worker
  -> asr_worker
  -> LocalUtteranceAggregator
  -> translate_worker
  -> websocket_push_worker
  -> browser subtitle monitor
```

Local mode uses faster-whisper for ASR and Argos, MarianMT, or NLLB for translation.
English local mode uses `base.en` or `small.en` according to the selected hardware tier. Spanish and Chinese local modes automatically map those selections to multilingual `base` or `small`, then translate into `zho_Hans` when a local translation engine is selected.
The faster-whisper wrapper uses multi-candidate decoding, light repetition control, a meeting-domain prompt, and a less aggressive VAD silence window so local ASR favors transcript quality over the previous fastest possible decode.
The browser exposes local ASR hardware tiers while treating tester machines as 16GB RAM by default: `iGPU` maps to `base(.en) + cpu + int8 + beam 1`, `dGPU` maps to `small(.en) + auto + int8 + beam 2`, and `HP` maps to `small(.en) + cuda + int8_float16 + beam 3`. `medium.en` remains a manual experiment rather than a default preset because GPU memory, not system RAM, is usually the limiting factor once Windows, Teams, the browser, and Codex are running.
The local default max chunk is `2s`. The `Low` preset uses a `2s` max chunk, `1s` adaptive minimum, `0.35s` silence flush, `0.3s` overlap, queue size `2`, and sentence-oriented utterance segmentation so source ASR remains responsive while Chinese waits for a fuller thought. The `Steady` preset uses a `3s` max chunk, `1.5s` adaptive minimum, `0.45s` silence flush, `0.5s` overlap, queue size `2`, and looser segmentation for more complete wording. The audio chunker keeps the max window for continuous speech, but flushes early after speech followed by a short quiet tail. Because normal use is `System` loopback, the backend applies a stricter system-audio RMS gate before ASR and adaptive flush decisions to reduce low-level loopback silence hallucinations. `LocalUtteranceAggregator` turns ASR chunks into a stable source utterance stream, then sends only ready utterances to translation after a meaningful idle pause, max length, or max duration. `ContextualTranslationBuffer` can briefly hold short or dependent ready utterances and merge them with the next ready utterance before translation. Translation jobs are queued in the background so source updates do not wait for Chinese translation.
The `faster-whisper` module is loaded lazily when local ASR is actually requested, so Azure startup does not fail just because local ASR dependencies are unavailable on a given Windows machine.

### Local Chinese FunASR Streaming Route

```text
StreamingAudioCapture
  -> /ws/asr/funasr
  -> FunASR AutoModel streaming cache
  -> SubtitleState partial/final merge
  -> browser Chinese live window
```

Chinese local realtime mode uses FunASR Paraformer streaming instead of Whisper. Audio is captured as mono PCM int16 at 16 kHz, sliced into small chunks, and sent through a small asyncio queue so stale work is dropped rather than displayed late. The streaming model cache is reused across chunks and flushed with `is_final=True` at the end of an utterance or session.

The current CPU-safe tuning uses 800 ms chunks, FunASR chunk size `[5, 10, 5]`, queue size 3, no punctuation model, and no complex VAD. The browser displays only the recent live subtitle window while the backend keeps the full transcript buffer. CUDA is preferred when the virtual environment has a CUDA-enabled PyTorch build; the current local venv may fall back to CPU.

## Key Backend Modules

- `backend/main.py`: FastAPI app, WebSocket orchestration, queues, local utterance aggregation, browser-audio remote tester input, monthly cloud quota guard, direct fast translation flow, cloud usage sync endpoint, meeting-notes processing, and paragraph turn detection.
- `backend/audio_capture.py`: microphone capture plus Windows system-audio capture that prefers current-default-device loopback through `soundcard`, then falls back to Stereo Mix / speaker-monitor matching through `sounddevice`.
- `backend/cloud_speech.py`: cloud streaming translation integration.
- `backend/asr.py`: faster-whisper wrapper.
- `asr/funasr_streaming.py`: FunASR AutoModel streaming wrapper and chunk inference metrics.
- `asr/audio_capture.py`: fixed-size PCM16 chunk capture for FunASR streaming.
- `asr/subtitle_state.py`: partial/final merge state for live Chinese captions.
- `backend/translator.py`: Argos, MarianMT, and NLLB local translators.
- `backend/config.py`: runtime defaults and selectable options.
- Language handling: `eng_Latn` and `spa_Latn` are accepted source languages; `zho_Hans` remains the fixed target language.

## Frontend Modules

- `frontend/index.html`: main Subtitle Studio operating surface.
- `frontend/style.css`: shared visual tokens, soft UI layout, subtitle monitor, controls, and saved-theme CSS variable hooks.
- `frontend/app.js`: WebSocket client, browser audio capture for remote Cloud mode, subtitle rendering, status lamp state, scroll-follow behavior, cloud usage panel state, provider-neutral status text rendering, and saved UI theme loading.
- Frontend rendering uses two UI modes: cloud events render into the original single bilingual subtitle stream, while English/Spanish local events split into continuous source context and complete Chinese translation panes. Local Chinese FunASR events render into a recent Chinese live caption window.
- `frontend/ui-editor.html`: visual editor page for tuning the main UI.
- `frontend/ui-editor.css`: editor layout and control styling.
- `frontend/ui-editor.js`: editor preview, `localStorage` save/reset behavior, and generated CSS preview.
- `frontend/diagnostics.html`: compact monitoring page for health, readiness, notes progress, recent recordings, and quick tests.
- `frontend/diagnostics.css`: monitoring page visual style.
- `frontend/diagnostics.js`: polling and quick-test logic for diagnostics. The live WebSocket test opens and closes a connection without starting a caption session.

Diagnostics remains available at `/static/diagnostics.html`, but the main operating toolbar no longer exposes a diagnostics button. This keeps the live surface focused on Start, End, language/input selection, and the compact Notes tool.

Saved UI editor choices are stored in the browser under `subtitleStudioUiThemeCompact20260502`. This is a local browser preference, not a server-side user setting.

## Cloud Usage Sync

The left runtime panel includes a provider-neutral Cloud Usage block. Without account-level sync credentials, it records the current session and local day/month estimate in browser `localStorage` under `subtitleStudioAzureUsageEstimate20260525`; this does not synchronize across machines or browsers.

When account-level sync credentials are configured, the frontend polls `GET /api/cloud-usage` once per minute. The backend uses the existing service-principal configuration to query translated-audio seconds and returns provider-neutral `cloud_usage` / `audio_seconds` fields. Results are cached for 60 seconds so the UI does not repeatedly hit the usage API. The previous `/api/azure-usage` endpoint remains as a compatibility alias.

The center backend now enforces a monthly Cloud quota, defaulting to `18000` seconds, or 5 hours. The quota resets at 00:00 UTC on the first day of each month. Enforcement combines the cloud-provider month total, the local backend ledger at `sync-meta/cloud-usage-quota.json`, and currently active sessions. New Cloud subtitle sessions are rejected after the quota is reached, and active Cloud sessions are stopped by a quota guard worker at the boundary.

## Post-Meeting Notes

The meeting-notes route is now a manual post-meeting action from the Notes tools. `End Meeting` closes the live recording session only. When the user chooses a recording and builds notes, the backend cleans raw ASR tags from the transcript, creates an English minutes draft, then appends a Chinese reading version in the same notes document. The browser opens the `.docx` output by default so normal review happens in Word rather than Markdown.

If the transcript is too short or too noisy, the minutes generator keeps the document readable but avoids inventing decisions, action items, or risks.

Aliyun Tingwu is the preferred cloud meeting-notes path. The app can upload recordings through Aliyun OSS or a self-hosted Tencent Relay service, create an offline Tingwu task with transcription, speaker separation, summary, action-item, and text-polish capabilities, poll for completion, download the raw Tingwu result payloads, and render Markdown/DOCX notes. The original WAV remains the local archive; before upload, the backend can create a lossless FLAC file with `ffmpeg` to reduce transfer size without changing the speech content. Reusable `recordings/*.upload.flac` files are cached by default so repeated notes builds do not recompress the same WAV. If FLAC compression is disabled, unavailable, stale, or not smaller enough, the original WAV is uploaded. Temporary OSS or relay audio files are deleted after Tingwu results are retrieved by default.

Local LLM refinement is configured through Ollama. The current default local notes model is `qwen3:14b`; it is used only after a transcript exists and should not be treated as a real-time subtitle model. When `POST_MEETING_NOTES_REWRITE_ENABLED=1`, `backend/notes_quality.py` runs a second-pass rewrite over the generated minutes and the full transcript. This pass asks the model to expand every important topic with concrete discussion points, examples, numbers, risks, decisions, open questions, and next steps that are supported by the transcript. It also extracts compact speaker-attributed evidence from diarized transcripts so discussion sections can show who raised, answered, challenged, confirmed, or owned each important point. Real names are used only when supplied by the transcript or meeting context; otherwise the notes keep anonymous labels such as `Speaker 1` / `Speaker 2` or `发言人 1` / `发言人 2`. Accepted rewrites replace the Markdown/DOCX minutes, while the original generated draft is preserved as `*.minutes.raw.md`.

When `POST_MEETING_ASR_ENGINE=azure-batch` and `AZURE_BATCH_CONTAINER_SAS_URL` is configured, post-meeting notes use Azure Batch Transcription with diarization. The original WAV is uploaded to Azure Blob, submitted as `contentUrls`, polled until completion, then converted into local transcript/minutes files. If Blob SAS is missing, the backend reports local fallback status and uses faster-whisper without speaker separation.

The post-meeting route also receives the currently selected frontend engine. Azure Cloud mode attempts Azure Batch, while local engines force local faster-whisper notes and skip speaker separation.
If cloud batch storage is missing, local faster-whisper notes now default to CPU through `POST_MEETING_ASR_DEVICE=cpu` behavior. This avoids CUDA DLL failures on tester machines; maintainers can opt back into `cuda` or `auto` with `POST_MEETING_ASR_DEVICE`.

## Latency Design

- Azure route avoids fixed local time slicing.
- Live Azure partials update the current subtitle row.
- Final Azure results enter history.
- Local low-latency mode keeps ASR responsive, accumulates short ASR fragments into fuller utterances, and translates only ready utterances.
- Audio queues may drop stale chunks for responsiveness. The local translation queue is background-only and preserves ready utterances so completed sentences are not lost or allowed to block source ASR updates.
- There is no MiniMax polish queue and no Balanced/Quality path.
- The active translation mode is fixed to fast/direct output.
- The local audio queue is size-limited so stale audio work is dropped rather than displayed late.
- MarianMT and NLLB run through Transformers. In the current environment, the installed `torch` runtime is CPU-only, so those translators do not gain practical GPU acceleration even if local ASR is using CUDA.

## Translation Quality Preview

`scripts/translation-quality-preview.py` is an offline comparison tool. It tests direct Argos output against candidate English stabilization and short-fragment merging, then optionally asks local Ollama `qwen3:14b` to polish the Chinese output when enough memory is available. The script writes a Markdown report under `design-previews/` and does not change the live subtitle path.

## Paragraph Turn Detection

The current version uses a lightweight detector:

- A new paragraph starts when there is a long enough pause between final subtitles.
- Common filler words are marked as noise.
- Noise is not used as a voice-change signal.

This is not true speaker diarization. True diarization is a Phase 2+ feature.

## Environment Variables

```powershell
$env:AZURE_SPEECH_KEY="..."
$env:AZURE_SPEECH_REGION="..."
$env:AZURE_PHRASE_LIST="AHU,BMS,EMS,HVAC,WFI,PW,CIP,SIP,FAT,SAT,P&ID,HAZOP"
$env:ASR_PROMPT_TERMS="cleanroom,commissioning,validation,ISO Class 7"
$env:TERMINOLOGY_GLOSSARY_PATH="backend/glossary.csv"
$env:AZURE_TENANT_ID="..."
$env:AZURE_CLIENT_ID="..."
$env:AZURE_CLIENT_SECRET="..."
$env:AZURE_SPEECH_RESOURCE_ID="/subscriptions/.../resourceGroups/.../providers/Microsoft.CognitiveServices/accounts/..."
$env:AZURE_SPEECH_MONTHLY_SECONDS_LIMIT="18000"
```

Terminology hotwords are loaded by `backend/terminology.py` from built-in engineering defaults, `AZURE_PHRASE_LIST`, `ASR_PROMPT_TERMS`, and `backend/glossary.csv`. Azure uses the final list as a `PhraseListGrammar`. Local faster-whisper can use terminology for `initial_prompt` and `hotwords`, but this is disabled by default for live `System` mode because an overly specific prompt can bias general meeting or video audio. Post-meeting faster-whisper processing reuses the same module.

Do not commit real API keys, service-principal secrets, SAS URLs, or `.env` files.
