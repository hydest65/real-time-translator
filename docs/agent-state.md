# Agent State

## Current Working Directory

`E:\Users\Administrator\Documents\Codex\2026-05-03-github\real-time-translator`

## Current User Goal

Finish the current coding pass and sync the work to GitHub.

## Completed This Turn

- Reviewed the project continuation state and GitHub publish workflow.
- Confirmed the current branch is `codex/post-meeting-ollama-notes-desktop`.
- Confirmed GitHub CLI `gh` is not installed, so draft PR creation is blocked on this machine.
- Added final closeout notes for Azure Batch meeting notes, selected-engine routing, progress UI, long-recording chunking, and fallback behavior.
- Refreshed QA notes with the 2026-05-24 verification status.

## Main Work Now In The Working Tree

- Stability-first local `System` audio defaults and local ASR hallucination filtering.
- Shared terminology loader with private `backend/glossary.csv` support and a committed `backend/glossary.example.csv`.
- Meeting notes topic timeline generation.
- Meeting notes progress API and frontend progress bar.
- Long-recording chunked faster-whisper transcription.
- Pyannote diarization compatibility improvements for local/offline experiments.
- Azure Batch Transcription support for cloud meeting notes with speaker separation.
- Selected-engine routing: Azure live mode attempts cloud notes when configured; local live engines use local notes without speaker separation.
- User-facing meeting-notes hints and completion logs that explain which path was used.
- One-click Windows command shortcuts for backend restart and shutdown.

## Files Expected In The Commit

- `.env.example`
- `.gitignore`
- `README.md`
- `backend/asr.py`
- `backend/audio_capture.py`
- `backend/cloud_speech.py`
- `backend/config.py`
- `backend/main.py`
- `backend/glossary.example.csv`
- `backend/terminology.py`
- `docs/PRODUCT_REQUIREMENTS.md`
- `docs/RELEASE_NOTES.md`
- `docs/TECHNICAL_ARCHITECTURE.md`
- `docs/QA_CHECKLIST.md`
- `docs/agent-state.md`
- `frontend/app.js`
- `frontend/index.html`
- `frontend/style.css`
- `scripts/diarize-recording.py`
- `scripts/process-recording.py`
- `一键关闭后台.cmd`
- `一键重启后台.cmd`

## Checks And Results

- `.\.venv\Scripts\python.exe -m py_compile backend\main.py backend\asr.py backend\audio_capture.py backend\cloud_speech.py backend\config.py backend\terminology.py scripts\process-recording.py scripts\diarize-recording.py`: passed.
- `node --check frontend\app.js`: passed.
- `git diff --check`: passed.
- Secret scan found placeholders and environment variable references only; no live token, Blob SAS signature, or account key was detected in committed paths.
- Local fallback routing and Azure-without-Blob-SAS fallback were smoke-tested.

## Known Blockers And Warnings

- `gh` is not installed, so the GitHub publish skill cannot create a draft PR from this machine.
- `AZURE_BATCH_CONTAINER_SAS_URL` is not configured in `.env`; Azure Batch meeting notes will fall back to local faster-whisper until Blob SAS is added.
- Azure Batch requires a Blob/container SAS URL because Batch Transcription cannot directly read a local WAV file.
- Local pyannote diarization works after Hugging Face gated model access is accepted, but it is too slow to use as the default long-meeting path on T600-class hardware.

## Next Recommended Step

Run the final syntax checks, stage the intended files explicitly, commit with `Add post-meeting Azure Batch notes`, and push `codex/post-meeting-ollama-notes-desktop` to GitHub. Install/authenticate `gh` later if a draft PR is required from this machine.
