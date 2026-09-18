# Aliyun Tingwu Cloud Notes Setup

## Purpose

Use Aliyun Tingwu as the default cloud meeting-notes engine. Azure can remain available for live subtitles or legacy experiments, but the product direction for cloud meeting notes is Aliyun Tingwu.

Target flow:

1. Upload the local meeting recording to an upload path.
2. Generate a temporary public HTTPS URL for the audio file.
3. Create a Tingwu task with transcription, speaker diarization, and meeting-summary capabilities enabled.
4. Poll the task result.
5. Convert Tingwu transcription, speaker labels, summary, and action items into the app's Markdown/DOCX notes.

## Account Details

- Product: Aliyun Tingwu
- Region: `cn-beijing`
- Endpoint: `tingwu.cn-beijing.aliyuncs.com`

Keep RAM usernames, login domains, AppKeys, AccessKey IDs, AccessKey secrets, relay hostnames, and bucket names only in the local `.env` or the user's private notes. Do not commit live account identifiers.

## Required Local Environment

```env
ALIYUN_TINGWU_ENABLED=1
ALIBABA_CLOUD_ACCESS_KEY_ID=
ALIBABA_CLOUD_ACCESS_KEY_SECRET=
ALIYUN_TINGWU_REGION=cn-beijing
ALIYUN_TINGWU_ENDPOINT=tingwu.cn-beijing.aliyuncs.com
ALIYUN_TINGWU_APP_KEY=
ALIYUN_TINGWU_UPLOAD_PROVIDER=oss
ALIYUN_OSS_REGION=cn-shanghai
ALIYUN_OSS_BUCKET=your_oss_bucket
ALIYUN_OSS_OBJECT_PREFIX=subtitle-studio/recordings/
ALIYUN_OSS_DELETE_AFTER_TINGWU=1
TENCENT_RELAY_BASE_URL=http://your-relay-host:8787
TENCENT_RELAY_DELETE_AFTER_TINGWU=1
```

Keep real AccessKey values only in the local `.env`.

## Local Python Dependencies

The current virtual environment has these Aliyun packages installed for the Tingwu integration:

- `oss2`
- `alibabacloud-tingwu20230930`

If the project is moved to a new machine, install them into the app virtual environment before using cloud notes.

## Recommended Permissions

For quick testing:

- `AliyunTingWuFullAccess`
- `AliyunOSSFullAccess`

Before external testing, reduce OSS permission to the selected bucket and keep Tingwu permission limited to the task APIs required by the app.

Minimum Tingwu APIs for the first integration:

- `tingwu:CreateTask`
- `tingwu:GetTaskInfo`

Optional hotword APIs can be added later if the app manages Tingwu hotwords.

## Recommended Tingwu Task Capabilities

- Enable transcription.
- Enable speaker diarization.
- Let speaker count be automatic unless the user specifies a participant count.
- Enable meeting summary.
- Enable action items.
- Enable text polish if available.
- Leave translation disabled by default to control cost.

## Notes

Tingwu cannot read a local WAV path directly. The app must provide an accessible HTTP or HTTPS audio URL. The app now supports two upload paths:

- `oss`: upload to Aliyun OSS and generate a signed OSS URL
- `tencent-relay`: upload to the lightweight Tencent Cloud relay service and return a temporary download URL

The backend now contains the first full integration path:

`local WAV -> OSS upload -> signed OSS URL -> Tingwu offline task -> GetTaskInfo polling -> transcript/minutes Markdown -> DOCX`

By default, the app now deletes the temporary OSS audio object after Tingwu finishes and the result files have been downloaded. Set `ALIYUN_OSS_DELETE_AFTER_TINGWU=0` only if you intentionally want to keep the OSS copy for debugging.

For Tencent Relay mode, set:

- `ALIYUN_TINGWU_UPLOAD_PROVIDER=tencent-relay`
- `TENCENT_RELAY_BASE_URL=http://your-relay-host:8787`
- `TENCENT_RELAY_DELETE_AFTER_TINGWU=1`

When Tencent Relay mode is selected, the app uploads the recording to the relay server, gives Tingwu the relay URL, and then deletes the relay file after Tingwu finishes.

For debugging and quality tuning, the backend now also writes the raw Tingwu result payloads next to each recording:

- `.tingwu.transcription.json`
- `.tingwu.summary.json`
- `.tingwu.meeting.json`
- `.tingwu.polish.json`

The path is intentionally blocked by config validation until `ALIYUN_TINGWU_APP_KEY` and `ALIYUN_OSS_BUCKET` are provided.

## Diagnostics

After updating `.env` and restarting the backend, open:

`http://127.0.0.1:8000/api/aliyun-tingwu-diagnostics`

This checks local SDK installation, whether Tingwu is enabled, whether required local settings exist, and then validates the selected upload path:

- OSS mode: bucket reachability plus tiny write/delete healthcheck
- Tencent Relay mode: relay URL reachability

If diagnostics reports `UserDisable (0003-00000801)` for `OSS Write Access`, Alibaba Cloud's own OSS troubleshooting note says that this usually means one of three things: the account has overdue payments, the account was disabled for security reasons, or OSS is not fully active for that account. See:

- [Alibaba Cloud OSS 0003-00000801](https://www.alibabacloud.com/help/en/oss/support/0003-00000801)
- [阿里云 OSS 0003-00000801](https://help.aliyun.com/zh/oss/support/0003-00000801)
