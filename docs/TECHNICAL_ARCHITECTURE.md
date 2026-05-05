# Technical Architecture

## Runtime Routes

### Azure Cloud Route

```text
Audio capture
  -> Azure Speech Translation streaming session
  -> websocket_push_worker
  -> browser subtitle monitor
```

Azure provides live partial subtitles and final bilingual subtitle results as an optional cloud comparison/fallback route.
The high-end local edition fixes the source language to English. Azure maps that source to `en-US`; the target is fixed to `zh-Hans`.

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
English local mode defaults to `medium.en` on CUDA, with `small.en` and `base.en` available as lighter realtime profiles.
The local default chunk is `1.5s`. The `Low` preset uses a `1.5s` chunk, `0.25s` overlap, queue size `1`, and medium-length utterance segmentation so subtitles stay realtime without fragmenting every short phrase. The `Steady` preset uses a `2s` chunk, `0.3s` overlap, queue size `1`, and looser utterance segmentation for more stable wording. `LocalUtteranceAggregator` turns ASR chunks into a stable English utterance stream, filters repeated loopback fragments, then sends only ready utterances to translation after an idle pause, max length, or max duration. Translation jobs are queued in the background so English draft updates do not wait for Chinese translation.
The `faster-whisper` module is loaded lazily when local ASR is actually requested, so Azure startup does not fail just because local ASR dependencies are unavailable on a given Windows machine.

## Key Backend Modules

- `backend/main.py`: FastAPI app, WebSocket orchestration, queues, local utterance aggregation, workers, direct fast translation flow, and paragraph turn detection.
- `backend/audio_capture.py`: microphone capture plus Windows system-audio capture that prefers current-default-device loopback through `soundcard`, then falls back to Stereo Mix / speaker-monitor matching through `sounddevice`.
- `backend/cloud_speech.py`: Azure streaming translation integration.
- `backend/asr.py`: faster-whisper wrapper.
- `backend/translator.py`: Argos, MarianMT, and NLLB local translators.
- `backend/config.py`: runtime defaults and selectable options.
- Language handling: `eng_Latn` is the fixed source language; `zho_Hans` remains the fixed target language.

## Frontend Modules

- `frontend/index.html`: main Subtitle Studio operating surface.
- `frontend/style.css`: shared visual tokens, soft UI layout, subtitle monitor, controls, and saved-theme CSS variable hooks.
- `frontend/app.js`: WebSocket client, subtitle rendering, status lamp state, scroll-follow behavior, and saved UI theme loading.
- Frontend rendering uses a two-level local subtitle workspace. Draft events update the upper continuous English live transcript, while final translated events append to the lower continuous polished Chinese text flow.
- `frontend/ui-editor.html`: visual editor page for tuning the main UI.
- `frontend/ui-editor.css`: editor layout and control styling.
- `frontend/ui-editor.js`: editor preview, `localStorage` save/reset behavior, and generated CSS preview.

Saved UI editor choices are stored in the browser under `subtitleStudioUiThemeCompact20260502`. This is a local browser preference, not a server-side user setting.

## Latency Design

- Azure route avoids fixed local time slicing.
- Live Azure partials update the current subtitle row.
- Final Azure results enter history.
- Local low-latency mode balances chunk size, overlap, and queue pressure, accumulates English ASR output into utterances, filters repeated phrases, and translates only ready utterances.
- Audio queues may drop stale chunks for responsiveness. The local translation queue is background-only and preserves ready utterances so completed sentences are not lost or allowed to block the English draft path.
- There is no MiniMax polish queue and no Balanced/Quality path.
- The active translation mode is fixed to fast/direct output.
- The local audio queue is size-limited so stale audio work is dropped rather than displayed late.
- MarianMT and NLLB run through Transformers. The high-end local environment pins CUDA PyTorch, but Argos remains the realtime default.

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
