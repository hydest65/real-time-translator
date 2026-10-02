# Aliyun Tingwu Machine Handoff

This note is for moving the Subtitle Studio Aliyun Tingwu meeting-notes setup to another Windows machine.

Do not paste real keys into GitHub, chat, or shared screenshots. Fill secrets only in the target machine's local `.env`.

## What Tingwu Does In This App

- Tingwu is used for post-meeting notes, not for realtime subtitles.
- The app records a local WAV file during a meeting.
- After `End Meeting`, choose notes engine `Cloud` and build notes.
- The backend uploads the WAV to a public temporary audio URL, submits an offline Tingwu task, polls until complete, downloads Tingwu result payloads, and writes transcript/minutes files.
- Normal review output is a Word file: English professional minutes first, then a Chinese reading version in the same `.docx`.

## Active Project

Use this project folder on the target machine:

```text
real_time_translator_latest
```

Important files:

```text
backend/aliyun_tingwu.py
backend/main.py
backend/requirements.txt
frontend/index.html
frontend/app.js
.env.example
docs/TECHNICAL_ARCHITECTURE.md
```

## Dependencies

Install normal project dependencies from:

```powershell
python -m pip install -r backend\requirements.txt
```

The Tingwu-related packages are already listed there:

```text
oss2==2.19.1
alibabacloud-tingwu20230930==2.0.25
```

## Required Cloud Items

You need these from Alibaba Cloud:

- A Tingwu project / application AppKey.
- A RAM AccessKey ID and AccessKey Secret.
- Permission to create/query Tingwu offline tasks.
- A way to provide Tingwu with a public audio URL.

The app supports two upload paths:

- `oss`: upload the WAV to Aliyun OSS, then create a signed URL for Tingwu.
- `tencent-relay`: upload the WAV to a self-hosted Tencent Relay service, then pass that public URL to Tingwu.

## Option A: Aliyun OSS Upload

Use this when the target machine can upload directly to an Aliyun OSS bucket.

Create or choose:

- OSS bucket region, usually `cn-beijing` if matching the Tingwu region.
- OSS bucket name.
- Optional object prefix, such as `subtitle-studio/recordings/`.

The RAM key needs enough access for:

- Tingwu task create/query.
- OSS bucket info/read check.
- OSS object upload.
- OSS signed download URL creation.
- OSS object delete if cleanup is enabled.

Local `.env` block:

```env
ALIYUN_TINGWU_ENABLED=1
ALIBABA_CLOUD_ACCESS_KEY_ID=your_ram_access_key_id
ALIBABA_CLOUD_ACCESS_KEY_SECRET=your_ram_access_key_secret
ALIYUN_TINGWU_REGION=cn-beijing
ALIYUN_TINGWU_ENDPOINT=tingwu.cn-beijing.aliyuncs.com
ALIYUN_TINGWU_APP_KEY=your_tingwu_app_key

ALIYUN_TINGWU_UPLOAD_PROVIDER=oss
ALIYUN_OSS_REGION=cn-beijing
ALIYUN_OSS_BUCKET=your_oss_bucket
ALIYUN_OSS_OBJECT_PREFIX=subtitle-studio/recordings/
ALIYUN_OSS_DELETE_AFTER_TINGWU=1
```

Optional OSS settings:

```env
ALIYUN_OSS_ENDPOINT=https://oss-cn-beijing.aliyuncs.com
ALIYUN_OSS_SIGNED_URL_SECONDS=21600
ALIYUN_TINGWU_POLL_SECONDS=10
ALIYUN_TINGWU_TIMEOUT_SECONDS=7200
```

## Option B: Tencent Relay Upload

Use this when you do not want the app to upload directly to OSS, or when a separate relay already handles the public file URL.

The relay must be reachable from the target machine and from Tingwu. The current app checks the relay by opening:

```text
<TENCENT_RELAY_BASE_URL>/docs
```

Local `.env` block:

```env
ALIYUN_TINGWU_ENABLED=1
ALIBABA_CLOUD_ACCESS_KEY_ID=your_ram_access_key_id
ALIBABA_CLOUD_ACCESS_KEY_SECRET=your_ram_access_key_secret
ALIYUN_TINGWU_REGION=cn-beijing
ALIYUN_TINGWU_ENDPOINT=tingwu.cn-beijing.aliyuncs.com
ALIYUN_TINGWU_APP_KEY=your_tingwu_app_key

ALIYUN_TINGWU_UPLOAD_PROVIDER=tencent-relay
TENCENT_RELAY_BASE_URL=http://your-relay-host:8787
TENCENT_RELAY_DELETE_AFTER_TINGWU=1
```

Optional timing settings:

```env
ALIYUN_TINGWU_POLL_SECONDS=10
ALIYUN_TINGWU_TIMEOUT_SECONDS=7200
```

## Local Notes Refinement

This is optional and happens after transcription. It is not used for realtime subtitles.

```env
POST_MEETING_LLM_ENABLED=1
POST_MEETING_LLM_PROVIDER=ollama
POST_MEETING_LLM_FALLBACK=1
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_NOTES_MODEL=qwen3:14b
```

If the target machine does not have Ollama or `qwen3:14b`, meeting notes can still be generated from Tingwu results, but local refinement may be skipped or fall back depending on configuration.

## UI Workflow On The Target Machine

1. Start Subtitle Studio.
2. Open the main page.
3. In the meeting-notes utility, keep `Notes engine` as `Cloud`.
4. Click `Cloud Check`.
5. Fix any missing settings it reports.
6. Run or select a recording.
7. Click `Build Notes`.
8. Click `Open Notes` after processing finishes.

The diagnostics endpoint used by the UI is:

```text
GET /api/aliyun-tingwu-diagnostics
```

For relay mode, it can be checked with:

```text
GET /api/aliyun-tingwu-diagnostics?uploadProvider=tencent-relay
```

## Generated Files

For a recording such as:

```text
recordings/session-YYYYMMDD-HHMMSS.wav
```

Tingwu processing can write:

```text
recordings/session-YYYYMMDD-HHMMSS.transcript.md
recordings/session-YYYYMMDD-HHMMSS.minutes.md
recordings/session-YYYYMMDD-HHMMSS.minutes.docx
recordings/session-YYYYMMDD-HHMMSS.tingwu.transcription.json
recordings/session-YYYYMMDD-HHMMSS.tingwu.summary.json
recordings/session-YYYYMMDD-HHMMSS.tingwu.meeting.json
recordings/session-YYYYMMDD-HHMMSS.tingwu.polish.json
```

These files can contain meeting content and should be treated as private.

## Transfer Checklist

- Copy project code to the target machine.
- Do not copy `.venv`, `.cache`, `.model-cache`, or old model folders.
- Copy `.env.example` as a reference.
- Recreate `.env` on the target machine with the target machine's real secrets.
- If you must transfer the old `.env`, use a private secure channel, not GitHub or chat.
- Install the lightweight cloud-first dependencies with `python -m pip install -r backend\requirements.txt`.
- Install optional offline/local model dependencies only if needed with `python -m pip install -r backend\requirements-local.txt`.
- Before packaging the project, run `.\scripts\cleanup-local-artifacts.ps1 -WhatIf` to preview cache/model cleanup.
- Confirm `Cloud Check` passes before running a full meeting-notes job.

## Common Failure Meanings

- `ALIYUN_TINGWU_ENABLED is not enabled`: set `ALIYUN_TINGWU_ENABLED=1`.
- `Missing ALIYUN_TINGWU_APP_KEY`: copy the Tingwu AppKey into `.env`.
- `Missing ALIYUN_OSS_BUCKET`: OSS mode needs a bucket name.
- `Missing TENCENT_RELAY_BASE_URL`: relay mode needs the relay base URL.
- `OSS Access` or `OSS Write Access` fails: the RAM key, bucket name, region, endpoint, or bucket policy is wrong.
- `Tencent Relay Access` fails: the relay URL is unreachable from the target machine.
- Processing times out: use a shorter recording first, or increase `ALIYUN_TINGWU_TIMEOUT_SECONDS`.
