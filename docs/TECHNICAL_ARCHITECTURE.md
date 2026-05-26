# Technical Architecture

## Runtime Routes

### Azure Cloud Route

```text
Audio capture
  -> Azure Speech Translation streaming session
  -> websocket_push_worker
  -> browser subtitle monitor
```

This is the preferred low-latency route. Azure provides live partial subtitles and final bilingual subtitle results.
The source language selector maps English to `en-US` and Spanish to `es-ES`; the target is fixed to `zh-Hans`.

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
English local mode defaults to `small.en` for better meeting transcription, with `base.en` kept as the faster option. Spanish local mode automatically maps those selections to multilingual `small` and `base`, then translates `spa_Latn -> zho_Hans`.
The faster-whisper wrapper uses multi-candidate decoding, light repetition control, a meeting-domain prompt, and a less aggressive VAD silence window so local ASR favors transcript quality over the previous fastest possible decode.
The browser exposes local ASR presets for the 4GB NVIDIA T600 Laptop GPU: `Fast` maps to `base.en + int8`, `Balanced` maps to `small.en + int8`, and `Accurate` maps to `small.en + int8_float16`. `medium.en` remains a manual experiment rather than a default preset because available VRAM is tight once Windows, Teams, the browser, and Codex are running.
The local default max chunk is `2s`. The `Low` preset uses a `2s` max chunk, `1s` adaptive minimum, `0.35s` silence flush, `0.3s` overlap, queue size `2`, and sentence-oriented utterance segmentation so English remains responsive while Chinese waits for a fuller thought. The `Steady` preset uses a `3s` max chunk, `1.5s` adaptive minimum, `0.45s` silence flush, `0.5s` overlap, queue size `2`, and looser segmentation for more complete wording. The audio chunker keeps the max window for continuous speech, but flushes early after speech followed by a short quiet tail. Because normal use is `System` loopback, the backend applies a stricter system-audio RMS gate before ASR and adaptive flush decisions to reduce low-level loopback silence hallucinations. `LocalUtteranceAggregator` turns ASR chunks into a stable English utterance stream, then sends only ready utterances to translation after a meaningful idle pause, max length, or max duration. `ContextualTranslationBuffer` can briefly hold short or dependent ready utterances and merge them with the next ready utterance before translation. Translation jobs are queued in the background so English draft updates do not wait for Chinese translation.
The `faster-whisper` module is loaded lazily when local ASR is actually requested, so Azure startup does not fail just because local ASR dependencies are unavailable on a given Windows machine.

## Key Backend Modules

- `backend/main.py`: FastAPI app, WebSocket orchestration, queues, local utterance aggregation, workers, direct fast translation flow, Azure usage sync endpoint, and paragraph turn detection.
- `backend/audio_capture.py`: microphone capture plus Windows system-audio capture that prefers current-default-device loopback through `soundcard`, then falls back to Stereo Mix / speaker-monitor matching through `sounddevice`.
- `backend/cloud_speech.py`: Azure streaming translation integration.
- `backend/asr.py`: faster-whisper wrapper.
- `backend/translator.py`: Argos, MarianMT, and NLLB local translators.
- `backend/config.py`: runtime defaults and selectable options.
- Language handling: `eng_Latn` and `spa_Latn` are accepted source languages; `zho_Hans` remains the fixed target language.

## Frontend Modules

- `frontend/index.html`: main Subtitle Studio operating surface.
- `frontend/style.css`: shared visual tokens, soft UI layout, subtitle monitor, controls, and saved-theme CSS variable hooks.
- `frontend/app.js`: WebSocket client, subtitle rendering, status lamp state, scroll-follow behavior, Azure usage panel state, and saved UI theme loading.
- Frontend rendering uses two UI modes: Azure events render into the original single bilingual subtitle stream, while local events split into continuous English context, live English draft, and complete Chinese translation panes.
- `frontend/ui-editor.html`: visual editor page for tuning the main UI.
- `frontend/ui-editor.css`: editor layout and control styling.
- `frontend/ui-editor.js`: editor preview, `localStorage` save/reset behavior, and generated CSS preview.

Saved UI editor choices are stored in the browser under `subtitleStudioUiThemeCompact20260502`. This is a local browser preference, not a server-side user setting.

## Azure Usage Sync

The left runtime panel includes an Azure usage block. Without Azure Monitor credentials, it records the current session and local day/month estimate in browser `localStorage` under `subtitleStudioAzureUsageEstimate20260525`; this does not synchronize across machines or browsers.

When Azure Monitor credentials are configured, the frontend polls `GET /api/azure-usage` once per minute. The backend uses a service principal client-credentials token for `https://management.azure.com/.default`, queries the Speech resource metric `AudioSecondsTranslated`, and returns day/month account-level translated-audio seconds. Results are cached for 60 seconds so the UI does not repeatedly hit Azure Monitor.

## Post-Meeting Notes

The meeting-notes route processes the latest session WAV after the meeting is ended, cleans raw ASR tags from the transcript, creates an English minutes draft, then appends a Chinese reading version in the same notes document. The browser opens the `.docx` output by default so normal review happens in Word rather than Markdown.

If the transcript is too short or too noisy, the minutes generator keeps the document readable but avoids inventing decisions, action items, or risks.

When `POST_MEETING_ASR_ENGINE=azure-batch` and `AZURE_BATCH_CONTAINER_SAS_URL` is configured, post-meeting notes use Azure Batch Transcription with diarization. The original WAV is uploaded to Azure Blob, submitted as `contentUrls`, polled until completion, then converted into local transcript/minutes files. If Blob SAS is missing, the backend reports local fallback status and uses faster-whisper without speaker separation.

The post-meeting route also receives the currently selected frontend engine. Azure Cloud mode attempts Azure Batch, while local engines force local faster-whisper notes and skip speaker separation.

## Latency Design

- Azure route avoids fixed local time slicing.
- Live Azure partials update the current subtitle row.
- Final Azure results enter history.
- Local low-latency mode keeps English ASR drafts responsive, accumulates short ASR fragments into fuller utterances, and translates only ready utterances.
- Audio queues may drop stale chunks for responsiveness. The local translation queue is background-only and preserves ready utterances so completed sentences are not lost or allowed to block the English draft path.
- There is no MiniMax polish queue and no Balanced/Quality path.
- The active translation mode is fixed to fast/direct output.
- The local audio queue is size-limited so stale audio work is dropped rather than displayed late.
- MarianMT and NLLB run through Transformers. In the current environment, the installed `torch` runtime is CPU-only, so those translators do not gain practical GPU acceleration even if local ASR is using CUDA.

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
$env:AZURE_SPEECH_MONTHLY_SECONDS_LIMIT="360000"
```

Terminology hotwords are loaded by `backend/terminology.py` from built-in engineering defaults, `AZURE_PHRASE_LIST`, `ASR_PROMPT_TERMS`, and `backend/glossary.csv`. Azure uses the final list as a `PhraseListGrammar`. Local faster-whisper can use terminology for `initial_prompt` and `hotwords`, but this is disabled by default for live `System` mode because an overly specific prompt can bias general meeting or video audio. Post-meeting faster-whisper processing reuses the same module.

Do not commit real API keys, service-principal secrets, SAS URLs, or `.env` files.
