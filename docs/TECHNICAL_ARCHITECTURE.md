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

### Optional MiniMax Polish Route

```text
Azure final subtitle
  -> MiniMaxTextPolisher
  -> polished final Chinese replacement
  -> browser subtitle monitor
```

MiniMax is optional. If credentials are missing or polishing fails, the Azure translation remains visible.

### Local Fallback Route

```text
audio_capture_worker
  -> asr_worker
  -> translate_worker
  -> websocket_push_worker
  -> browser subtitle monitor
```

Local mode uses faster-whisper for ASR and Argos, MarianMT, or NLLB for translation.

## Key Backend Modules

- `backend/main.py`: FastAPI app, WebSocket orchestration, queues, workers, polish flow, paragraph turn detection.
- `backend/audio_capture.py`: microphone and system audio capture.
- `backend/cloud_speech.py`: Azure streaming translation integration.
- `backend/text_polisher.py`: MiniMax domain subtitle polishing prompt and API call.
- `backend/asr.py`: faster-whisper wrapper.
- `backend/translator.py`: Argos, MarianMT, and NLLB local translators.
- `backend/config.py`: runtime defaults and selectable options.

## Latency Design

- Azure route avoids fixed local time slicing.
- Live Azure partials update the current subtitle row.
- Final Azure results enter history.
- Balanced polishing is asynchronous and does not block the first visible translation.
- Local queues are size-limited so stale work is dropped rather than displayed late.

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

$env:MINIMAX_API_KEY="..."
$env:MINIMAX_BASE_URL="https://api.minimax.io/v1"
$env:MINIMAX_MODEL="MiniMax-M2.7"
```

Do not commit real API keys.

