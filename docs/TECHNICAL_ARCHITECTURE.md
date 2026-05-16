# Technical Architecture

## Runtime Routes

### Azure Cloud Route

```text
Audio capture
  -> Azure Speech Translation streaming session
  -> websocket_push_worker
  -> browser English and Chinese subtitle panes
```

Azure provides live partial subtitles and final bilingual subtitle results as an optional cloud comparison/fallback route.
The high-end local edition fixes the source language to English. Azure maps that source to `en-US`; the target is fixed to `zh-Hans`.
The frontend renders Azure source partials in the upper pane and live Chinese partial translations in the lower pane as soon as Azure emits them; final Azure results enter the scrollable history.

### High-End Local Route

```text
audio_capture_worker
  -> asr_worker
  -> TranscriptStabilizer
  -> SentenceBuilder
  -> translate_worker
  -> websocket_push_worker
  -> browser English and Chinese subtitle panes
```

Local mode is the primary high-end English-to-Chinese workflow. It uses faster-whisper for ASR and MarianMT, Argos, or NLLB for translation.
English local mode defaults to `medium.en` on CUDA, with `small.en` and `base.en` available as lighter realtime profiles.
Translation defaults to MarianMT with beam search for better Chinese wording; Argos remains the low-latency fallback. All local translators run through a Chinese post-edit layer for punctuation cleanup and `backend/glossary.csv` professional glossary fixes such as `commissioning -> 调试`, `WFI -> 注射用水`, `FAT -> 工厂验收测试`, `developer -> 开发商`, and `land reclamation -> 填海造地`.
The local default chunk is `1.5s`. The `Low` preset uses a `1.5s` chunk, `0.25s` overlap, queue size `1`, and medium-length sentence segmentation so subtitles stay realtime without fragmenting every short phrase. The `Steady` preset uses a `2s` chunk, `0.3s` overlap, queue size `1`, and looser segmentation for more stable wording. `TranscriptStabilizer` turns overlapping ASR chunks into a stable rolling English transcript, repairs common false periods, removes repeated overlap words/phrases, and applies light domain corrections. `SentenceBuilder` buffers short or dangling fragments, then finalizes only on sentence punctuation, a strong internal boundary, idle pause, max length, or max duration. Translation jobs are queued in the background so English draft updates do not wait for Chinese translation.
Audio chunks pass through a front VAD gate before ASR. Silent chunks are skipped, low RMS speech sends a warning notice, chunks waiting more than `3s` are dropped, and the audio queue keeps the newest chunk to avoid latency buildup.
Each local segment records pipeline metrics: audio capture, VAD, ASR, translation, glossary, polish, queue wait, total latency, GPU memory, dropped chunk count, and queue length. `/metrics` returns rolling averages over the latest 50 segments.
Final local subtitles are sent first as `rule_polished`; the websocket also supports `subtitle_update` for replacing the same `segmentId` within one second if a future LLM polish stage is added.
The `faster-whisper` module is loaded lazily when local ASR is actually requested, so Azure startup does not fail just because local ASR dependencies are unavailable on a given Windows machine.

## Key Backend Modules

- `backend/main.py`: FastAPI app, WebSocket orchestration, queues, local sentence pipeline, workers, direct fast translation flow, metrics, and paragraph turn detection.
- `backend/audio_capture.py`: microphone capture plus Windows system-audio capture that prefers current-default-device loopback through `soundcard`, then falls back to Stereo Mix / speaker-monitor matching through `sounddevice`.
- `backend/cloud_speech.py`: Azure streaming translation integration.
- `backend/asr.py`: faster-whisper wrapper.
- `backend/transcript_stabilizer.py`: rolling English transcript stabilization, overlap de-duplication, repeated phrase cleanup, and false-period repair.
- `backend/sentence_builder.py`: natural sentence buffering and readiness detection before local translation.
- `backend/translator.py`: Argos, MarianMT, and NLLB local translators plus glossary post-editing.
- `backend/glossary.csv`: editable professional term and mistranslation correction table.
- `backend/config.py`: runtime defaults and selectable options.
- Language handling: `eng_Latn` is the fixed source language; `zho_Hans` remains the fixed target language.

## Frontend Modules

- `frontend/index.html`: main Subtitle Studio operating surface.
- `frontend/style.css`: shared visual tokens, soft UI layout, subtitle monitor, controls, and saved-theme CSS variable hooks.
- `frontend/app.js`: WebSocket client, subtitle rendering, status lamp state, scroll-follow behavior, and saved UI theme loading.
- Frontend rendering uses a two-level subtitle workspace. In local mode, draft events update the upper continuous English live transcript while final translated events append to the lower continuous polished Chinese text flow. In Azure mode, live English and live Chinese partials update both panes immediately, and final results enter history.
- `frontend/ui-editor.html`: visual editor page for tuning the main UI.
- `frontend/ui-editor.css`: editor layout and control styling.
- `frontend/ui-editor.js`: editor preview, `localStorage` save/reset behavior, and generated CSS preview.

Saved UI editor choices are stored in the browser under `subtitleStudioUiThemeCompact20260502`. This is a local browser preference, not a server-side user setting.

## Latency Design

- Azure route avoids fixed local time slicing.
- Live Azure partials update the current English and Chinese pane when translated text is available.
- Final Azure results enter history.
- Local low-latency mode balances chunk size, overlap, and queue pressure, accumulates English ASR output into utterances, filters repeated phrases, and translates only ready utterances.
- Audio queues may drop stale chunks for responsiveness. The local translation queue is background-only and preserves ready utterances so completed sentences are not lost or allowed to block the English draft path.
- There is no MiniMax polish queue and no Balanced/Quality path.
- The active translation mode is fixed to fast/direct output.
- The local audio queue is size-limited so stale audio work is dropped rather than displayed late.
- MarianMT and NLLB run through Transformers. The high-end local environment pins CUDA PyTorch, and MarianMT is now the offline quality default.

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
