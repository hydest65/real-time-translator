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
English local mode can use English-only Whisper models such as `base.en` and `small.en`. Spanish local mode automatically maps those selections to multilingual `base` and `small`, then translates `spa_Latn -> zho_Hans`.
The local low-latency preset uses a shorter `2s` chunk and `0.2s` overlap. `LocalUtteranceAggregator` turns ASR chunks into a stable English utterance stream, then sends only ready utterances to translation after a brief idle pause, max length, or max duration. Translation jobs are queued in the background so English draft updates do not wait for Chinese translation.

## Key Backend Modules

- `backend/main.py`: FastAPI app, WebSocket orchestration, queues, local utterance aggregation, workers, direct fast translation flow, and paragraph turn detection.
- `backend/audio_capture.py`: microphone and system audio capture.
- `backend/cloud_speech.py`: Azure streaming translation integration.
- `backend/asr.py`: faster-whisper wrapper.
- `backend/translator.py`: Argos, MarianMT, and NLLB local translators.
- `backend/config.py`: runtime defaults and selectable options.
- Language handling: `eng_Latn` and `spa_Latn` are accepted source languages; `zho_Hans` remains the fixed target language.

## Frontend Modules

- `frontend/index.html`: main Subtitle Studio operating surface.
- `frontend/style.css`: shared visual tokens, soft UI layout, subtitle monitor, controls, and saved-theme CSS variable hooks.
- `frontend/app.js`: WebSocket client, subtitle rendering, status lamp state, scroll-follow behavior, and saved UI theme loading.
- Frontend rendering uses two UI modes: Azure events render into the original single bilingual subtitle stream, while local events split into stable English context, live English draft, and complete Chinese translation panes.
- `frontend/ui-editor.html`: visual editor page for tuning the main UI.
- `frontend/ui-editor.css`: editor layout and control styling.
- `frontend/ui-editor.js`: editor preview, `localStorage` save/reset behavior, and generated CSS preview.

Saved UI editor choices are stored in the browser under `subtitleStudioUiThemeCompact20260502`. This is a local browser preference, not a server-side user setting.

## Latency Design

- Azure route avoids fixed local time slicing.
- Live Azure partials update the current subtitle row.
- Final Azure results enter history.
- Local low-latency mode reduces chunk size, accumulates English ASR output into utterances, and translates only ready utterances.
- Audio queues may drop stale chunks for responsiveness. The local translation queue is background-only and preserves ready utterances so completed sentences are not lost or allowed to block the English draft path.
- There is no MiniMax polish queue and no Balanced/Quality path.
- The active translation mode is fixed to fast/direct output.
- The local audio queue is size-limited so stale audio work is dropped rather than displayed late.

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
```

Do not commit real API keys.
