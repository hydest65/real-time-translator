from __future__ import annotations

import json
import http.client
import os
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class TingwuSegment:
    start: float
    end: float
    text: str
    speaker: str = "Speaker ?"


@dataclass
class TingwuNotes:
    task_id: str
    task_key: str
    status: str
    transcript_url: str = ""
    meeting_url: str = ""
    summary_url: str = ""
    text_polish_url: str = ""
    transcript_json: dict[str, Any] = field(default_factory=dict)
    meeting_json: dict[str, Any] = field(default_factory=dict)
    summary_json: dict[str, Any] = field(default_factory=dict)
    text_polish_json: dict[str, Any] = field(default_factory=dict)
    segments: list[TingwuSegment] = field(default_factory=list)


@dataclass
class TingwuUploadRef:
    provider: str
    file_url: str
    object_key: str = ""
    relay_token: str = ""


ProgressCallback = Callable[[str, str, dict[str, Any] | None], None]
_MINUTES_TRANSLATOR: Any | None = None
_MINUTES_TRANSLATOR_FAILED = False


def process_tingwu_recording(
    audio: Path,
    source_language: str = "en",
    upload_provider: str = "",
    progress_callback: ProgressCallback | None = None,
) -> TingwuNotes:
    config = tingwu_config(upload_provider)
    upload_ref = prepare_tingwu_audio_source(audio, config, progress_callback)
    try:
        client = tingwu_client(config)
        task_key = f"subtitle-studio-{audio.stem}-{uuid.uuid4().hex[:8]}"
        task_id = create_tingwu_task(client, config, task_key, upload_ref.file_url, source_language, progress_callback)
        notes = wait_for_tingwu_task(client, task_id, config, progress_callback)
        notes.task_key = task_key
        notes.segments = extract_tingwu_segments(notes.transcript_json)
        return notes
    finally:
        cleanup_tingwu_audio_source(upload_ref, config)


def tingwu_config(upload_provider: str = "") -> dict[str, str]:
    selected_provider = normalize_tingwu_upload_provider(
        upload_provider or os.getenv("ALIYUN_TINGWU_UPLOAD_PROVIDER", "oss")
    )
    values = {
        "access_key_id": os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip(),
        "access_key_secret": os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip(),
        "region": os.getenv("ALIYUN_TINGWU_REGION", "cn-beijing").strip() or "cn-beijing",
        "endpoint": os.getenv("ALIYUN_TINGWU_ENDPOINT", "tingwu.cn-beijing.aliyuncs.com").strip()
        or "tingwu.cn-beijing.aliyuncs.com",
        "app_key": os.getenv("ALIYUN_TINGWU_APP_KEY", "").strip(),
        "upload_provider": selected_provider,
        "oss_region": os.getenv("ALIYUN_OSS_REGION", "cn-beijing").strip() or "cn-beijing",
        "oss_endpoint": os.getenv("ALIYUN_OSS_ENDPOINT", "").strip(),
        "oss_bucket": os.getenv("ALIYUN_OSS_BUCKET", "").strip(),
        "oss_prefix": os.getenv("ALIYUN_OSS_OBJECT_PREFIX", "subtitle-studio/recordings/").strip()
        or "subtitle-studio/recordings/",
        "relay_base_url": os.getenv("TENCENT_RELAY_BASE_URL", "").strip().rstrip("/"),
        "relay_delete_after_complete": os.getenv("TENCENT_RELAY_DELETE_AFTER_TINGWU", "1").strip() or "1",
        "poll_seconds": os.getenv("ALIYUN_TINGWU_POLL_SECONDS", "10").strip() or "10",
        "timeout_seconds": os.getenv("ALIYUN_TINGWU_TIMEOUT_SECONDS", "7200").strip() or "7200",
        "signed_url_seconds": os.getenv("ALIYUN_OSS_SIGNED_URL_SECONDS", "21600").strip() or "21600",
        "delete_after_complete": os.getenv("ALIYUN_OSS_DELETE_AFTER_TINGWU", "1").strip() or "1",
    }
    missing = [name for name in ("access_key_id", "access_key_secret", "app_key") if not values[name]]
    if selected_provider == "oss":
        if not values["oss_bucket"]:
            missing.append("oss_bucket")
    elif selected_provider == "tencent-relay":
        if not values["relay_base_url"]:
            missing.append("relay_base_url")
    if missing:
        public_names = {
            "access_key_id": "ALIBABA_CLOUD_ACCESS_KEY_ID",
            "access_key_secret": "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
            "app_key": "ALIYUN_TINGWU_APP_KEY",
            "oss_bucket": "ALIYUN_OSS_BUCKET",
            "relay_base_url": "TENCENT_RELAY_BASE_URL",
        }
        raise RuntimeError("Missing Aliyun Tingwu settings: " + ", ".join(public_names[item] for item in missing))
    if not values["oss_endpoint"]:
        values["oss_endpoint"] = f"https://oss-{values['oss_region']}.aliyuncs.com"
    return values


def diagnose_tingwu_setup(upload_provider: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "checks": [],
    }

    def add_check(name: str, ok: bool, message: str) -> None:
        result["checks"].append({"name": name, "ok": ok, "message": message})
        if not ok:
            result["ok"] = False

    try:
        import oss2  # noqa: F401

        add_check("OSS SDK", True, "oss2 is installed.")
    except ImportError:
        add_check("OSS SDK", False, "oss2 is not installed.")

    try:
        import alibabacloud_tingwu20230930  # noqa: F401

        add_check("Tingwu SDK", True, "alibabacloud-tingwu20230930 is installed.")
    except ImportError:
        add_check("Tingwu SDK", False, "alibabacloud-tingwu20230930 is not installed.")

    enabled = os.getenv("ALIYUN_TINGWU_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    selected_provider = normalize_tingwu_upload_provider(
        upload_provider or os.getenv("ALIYUN_TINGWU_UPLOAD_PROVIDER", "oss")
    )
    add_check(
        "Tingwu Enabled",
        enabled,
        "ALIYUN_TINGWU_ENABLED is enabled." if enabled else "Set ALIYUN_TINGWU_ENABLED=1 in .env.",
    )
    add_check(
        "Upload Provider",
        True,
        "Aliyun Tingwu upload path is using Tencent Relay." if selected_provider == "tencent-relay" else "Aliyun Tingwu upload path is using OSS.",
    )

    access_key_id = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip()
    access_key_secret = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip()
    app_key = os.getenv("ALIYUN_TINGWU_APP_KEY", "").strip()
    bucket_name = os.getenv("ALIYUN_OSS_BUCKET", "").strip()
    relay_base_url = os.getenv("TENCENT_RELAY_BASE_URL", "").strip().rstrip("/")
    add_check(
        "AccessKey",
        bool(access_key_id and access_key_secret),
        "RAM AccessKey is present." if access_key_id and access_key_secret else "Add RAM AccessKey ID and Secret.",
    )
    add_check(
        "Tingwu AppKey",
        bool(app_key),
        "Tingwu AppKey is present." if app_key else "Copy the AppKey from the Tingwu project/API console.",
    )
    add_check(
        "OSS Bucket",
        bool(bucket_name) if selected_provider == "oss" else True,
        f"OSS bucket is set: {bucket_name}." if bucket_name else (
            "Create or choose an OSS bucket and set ALIYUN_OSS_BUCKET." if selected_provider == "oss" else "Not needed for Tencent Relay mode."
        ),
    )
    add_check(
        "Tencent Relay URL",
        bool(relay_base_url) if selected_provider == "tencent-relay" else True,
        f"Tencent Relay URL is set: {relay_base_url}." if relay_base_url else (
            "Set TENCENT_RELAY_BASE_URL before using Tencent Relay." if selected_provider == "tencent-relay" else "Not needed for OSS mode."
        ),
    )

    if selected_provider == "oss" and access_key_id and access_key_secret and bucket_name:
        try:
            config = tingwu_config_for_diagnostics()
            check_oss_bucket(config)
            add_check("OSS Access", True, "OSS bucket is reachable with the current RAM AccessKey.")
        except Exception as exc:
            add_check("OSS Access", False, explain_aliyun_error("Could not access OSS bucket.", exc))
        try:
            config = tingwu_config_for_diagnostics()
            check_oss_write_access(config)
            add_check("OSS Write Access", True, "OSS bucket accepts object upload and delete with the current RAM AccessKey.")
        except Exception as exc:
            add_check("OSS Write Access", False, explain_aliyun_error("Could not write to OSS bucket.", exc))
    else:
        add_check("OSS Access", True if selected_provider != "oss" else False, "Skipped in Tencent Relay mode." if selected_provider != "oss" else "Skipped until AccessKey and ALIYUN_OSS_BUCKET are both set.")
        add_check("OSS Write Access", True if selected_provider != "oss" else False, "Skipped in Tencent Relay mode." if selected_provider != "oss" else "Skipped until AccessKey and ALIYUN_OSS_BUCKET are both set.")

    if selected_provider == "tencent-relay" and relay_base_url:
        try:
            check_relay_service(relay_base_url)
            add_check("Tencent Relay Access", True, "Tencent Relay service is reachable.")
        except Exception as exc:
            add_check("Tencent Relay Access", False, f"Could not reach Tencent Relay service: {exc}")
    else:
        add_check("Tencent Relay Access", True if selected_provider != "tencent-relay" else False, "Skipped in OSS mode." if selected_provider != "tencent-relay" else "Skipped until TENCENT_RELAY_BASE_URL is set.")

    return result


def tingwu_config_for_diagnostics() -> dict[str, str]:
    values = {
        "access_key_id": os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip(),
        "access_key_secret": os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip(),
        "oss_region": os.getenv("ALIYUN_OSS_REGION", "cn-beijing").strip() or "cn-beijing",
        "oss_endpoint": os.getenv("ALIYUN_OSS_ENDPOINT", "").strip(),
        "oss_bucket": os.getenv("ALIYUN_OSS_BUCKET", "").strip(),
    }
    if not values["oss_endpoint"]:
        values["oss_endpoint"] = f"https://oss-{values['oss_region']}.aliyuncs.com"
    return values


def check_oss_bucket(config: dict[str, str]) -> None:
    import oss2

    auth = oss2.Auth(config["access_key_id"], config["access_key_secret"])
    bucket = oss2.Bucket(auth, config["oss_endpoint"], config["oss_bucket"])
    bucket.get_bucket_info()


def check_oss_write_access(config: dict[str, str]) -> None:
    import oss2

    auth = oss2.Auth(config["access_key_id"], config["access_key_secret"])
    bucket = oss2.Bucket(auth, config["oss_endpoint"], config["oss_bucket"])
    object_key = f"{config.get('oss_prefix', 'subtitle-studio/recordings/').strip('/')}/healthcheck-{uuid.uuid4().hex[:8]}.txt"
    try:
        bucket.put_object(object_key, b"subtitle-studio-healthcheck")
        bucket.delete_object(object_key)
    except Exception as exc:
        raise RuntimeError(explain_aliyun_error("OSS write test failed.", exc)) from exc


def check_relay_service(base_url: str) -> None:
    with urllib.request.urlopen(f"{base_url}/docs", timeout=20) as response:
        if int(getattr(response, "status", 200) or 200) >= 400:
            raise RuntimeError(f"Relay docs returned HTTP {response.status}")


def prepare_tingwu_audio_source(
    audio: Path,
    config: dict[str, str],
    progress_callback: ProgressCallback | None = None,
) -> TingwuUploadRef:
    provider = normalize_tingwu_upload_provider(config.get("upload_provider", "oss"))
    if provider == "tencent-relay":
        return upload_audio_to_relay(audio, config, progress_callback)
    object_key = upload_audio_to_oss(audio, config, progress_callback)
    return TingwuUploadRef(
        provider="oss",
        file_url=signed_oss_url(object_key, config),
        object_key=object_key,
    )


def cleanup_tingwu_audio_source(upload_ref: TingwuUploadRef, config: dict[str, str]) -> None:
    if upload_ref.provider == "tencent-relay":
        if should_delete_relay_object(config) and upload_ref.relay_token:
            try:
                delete_relay_object(upload_ref.relay_token, config)
                print("Aliyun Tingwu: cleaned up temporary Tencent Relay recording", flush=True)
            except Exception as exc:
                print(f"Aliyun Tingwu: could not delete temporary Tencent Relay recording: {exc}", flush=True)
        return
    if should_delete_oss_object(config) and upload_ref.object_key:
        try:
            delete_oss_object(upload_ref.object_key, config)
            print("Aliyun Tingwu: cleaned up temporary OSS recording", flush=True)
        except Exception as exc:
            print(f"Aliyun Tingwu: could not delete temporary OSS recording: {exc}", flush=True)


def upload_audio_to_oss(
    audio: Path,
    config: dict[str, str],
    progress_callback: ProgressCallback | None = None,
) -> str:
    import oss2

    prefix = config["oss_prefix"].strip("/")
    object_key = f"{prefix}/{int(time.time())}-{uuid.uuid4().hex[:8]}-{audio.name}" if prefix else audio.name
    auth = oss2.Auth(config["access_key_id"], config["access_key_secret"])
    bucket = oss2.Bucket(auth, config["oss_endpoint"], config["oss_bucket"])
    print("Aliyun Tingwu: uploading recording to OSS", flush=True)
    if progress_callback:
        progress_callback("uploading", "Uploading recording to Aliyun OSS.", {"uploaded": 0, "total": audio.stat().st_size})
    try:
        bucket.put_object_from_file(
            object_key,
            str(audio),
            progress_callback=(
                lambda uploaded, total: progress_callback(
                    "uploading",
                    "Uploading recording to Aliyun OSS.",
                    {"uploaded": uploaded, "total": total},
                )
                if progress_callback
                else None
            ),
        )
    except Exception as exc:
        raise RuntimeError(explain_aliyun_error(f"Aliyun OSS upload failed for {audio.name}.", exc)) from exc
    return object_key


def upload_audio_to_relay(
    audio: Path,
    config: dict[str, str],
    progress_callback: ProgressCallback | None = None,
) -> TingwuUploadRef:
    boundary = f"subtitle-studio-{uuid.uuid4().hex}"
    filename = audio.name
    content_type = "audio/wav" if audio.suffix.lower() == ".wav" else "application/octet-stream"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    total_size = len(head) + audio.stat().st_size + len(tail)
    parsed = urllib.parse.urlparse(config["relay_base_url"])
    upload_path = (parsed.path.rstrip("/") or "") + "/upload"
    connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    connection: http.client.HTTPConnection | http.client.HTTPSConnection | None = None
    print("Aliyun Tingwu: uploading recording to Tencent Relay", flush=True)
    if progress_callback:
        progress_callback("uploading", "Uploading recording to Tencent Relay.", {"uploaded": 0, "total": total_size})
    try:
        connection = connection_type(parsed.hostname, port, timeout=300)
        connection.putrequest("POST", upload_path)
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length", str(total_size))
        connection.endheaders()
        uploaded = 0
        connection.send(head)
        uploaded += len(head)
        if progress_callback:
            progress_callback("uploading", "Uploading recording to Tencent Relay.", {"uploaded": uploaded, "total": total_size})
        with audio.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                connection.send(chunk)
                uploaded += len(chunk)
                if progress_callback:
                    progress_callback("uploading", "Uploading recording to Tencent Relay.", {"uploaded": uploaded, "total": total_size})
        connection.send(tail)
        uploaded += len(tail)
        if progress_callback:
            progress_callback("uploading", "Uploading recording to Tencent Relay.", {"uploaded": uploaded, "total": total_size})
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Relay returned HTTP {response.status}")
    except Exception as exc:
        raise RuntimeError(f"Tencent Relay upload failed for {audio.name}. {exc}") from exc
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
    url = str(payload.get("url") or "").strip()
    token = str(payload.get("token") or "").strip()
    if not url or not token:
        raise RuntimeError("Tencent Relay upload did not return a usable URL and token.")
    return TingwuUploadRef(provider="tencent-relay", file_url=url, relay_token=token)


def explain_aliyun_error(prefix: str, exc: Exception) -> str:
    detail = str(exc)
    if "UserDisable" in detail or "0003-00000801" in detail:
        return (
            f"{prefix} Aliyun OSS returned UserDisable (0003-00000801). "
            "This usually means the Alibaba Cloud account is overdue, disabled for security reasons, "
            "or OSS write access is not currently available for the account. "
            "Check Expenses/Billing, account security status, and whether OSS is fully active for this account."
        )
    if "AccessDenied" in detail or "NoSuchBucket" in detail:
        return f"{prefix} {detail}"
    return f"{prefix} {detail}"


def signed_oss_url(object_key: str, config: dict[str, str]) -> str:
    import oss2

    auth = oss2.Auth(config["access_key_id"], config["access_key_secret"])
    bucket = oss2.Bucket(auth, config["oss_endpoint"], config["oss_bucket"])
    expires = max(3600, int(config["signed_url_seconds"]))
    return bucket.sign_url("GET", object_key, expires, slash_safe=True)


def should_delete_oss_object(config: dict[str, str]) -> bool:
    return str(config.get("delete_after_complete", "1")).strip().lower() in {"1", "true", "yes", "on"}


def should_delete_relay_object(config: dict[str, str]) -> bool:
    return str(config.get("relay_delete_after_complete", "1")).strip().lower() in {"1", "true", "yes", "on"}


def delete_oss_object(object_key: str, config: dict[str, str]) -> None:
    import oss2

    auth = oss2.Auth(config["access_key_id"], config["access_key_secret"])
    bucket = oss2.Bucket(auth, config["oss_endpoint"], config["oss_bucket"])
    bucket.delete_object(object_key)


def delete_relay_object(token: str, config: dict[str, str]) -> None:
    request = urllib.request.Request(
        f"{config['relay_base_url']}/files/{urllib.parse.quote(token)}",
        method="DELETE",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if int(getattr(response, "status", 200) or 200) >= 400:
            raise RuntimeError(f"Relay delete returned HTTP {response.status}")


def normalize_tingwu_upload_provider(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"relay", "tencent", "tencent-relay", "tencent_relay"}:
        return "tencent-relay"
    return "oss"


def tingwu_client(config: dict[str, str]):
    from alibabacloud_tea_openapi import models as open_api_models
    from alibabacloud_tingwu20230930.client import Client

    client_config = open_api_models.Config(
        access_key_id=config["access_key_id"],
        access_key_secret=config["access_key_secret"],
        region_id=config["region"],
        endpoint=config["endpoint"],
    )
    return Client(client_config)


def create_tingwu_task(
    client: Any,
    config: dict[str, str],
    task_key: str,
    file_url: str,
    source_language: str,
    progress_callback: ProgressCallback | None = None,
) -> str:
    from alibabacloud_tingwu20230930 import models as tingwu_models

    transcription = tingwu_models.CreateTaskRequestParametersTranscription(
        diarization_enabled=True,
        diarization=tingwu_models.CreateTaskRequestParametersTranscriptionDiarization(speaker_count=0),
        output_level=1,
    )
    parameters = tingwu_models.CreateTaskRequestParameters(
        transcription=transcription,
        meeting_assistance_enabled=True,
        meeting_assistance=tingwu_models.CreateTaskRequestParametersMeetingAssistance(
            types=["Actions", "KeyInformation"]
        ),
        summarization_enabled=True,
        summarization=tingwu_models.CreateTaskRequestParametersSummarization(
            types=["Paragraph", "Conversational", "QuestionsAnswering"]
        ),
        text_polish_enabled=True,
        auto_chapters_enabled=True,
        translation_enabled=False,
        llm_output_language="cn",
    )
    request = tingwu_models.CreateTaskRequest(
        type="offline",
        app_key=config["app_key"],
        input=tingwu_models.CreateTaskRequestInput(
            file_url=file_url,
            source_language=tingwu_language(source_language),
            task_key=task_key,
        ),
        parameters=parameters,
    )
    print("Aliyun Tingwu: creating cloud meeting-notes task", flush=True)
    if progress_callback:
        progress_callback("submitting", "Submitting the recording to Aliyun Tingwu.", None)
    response = client.create_task(request)
    body = response.body
    code = str(getattr(body, "code", "") or "")
    if code not in {"0", "OK", "Success", ""}:
        raise RuntimeError(f"Aliyun Tingwu CreateTask failed: {code} {getattr(body, 'message', '')}")
    data = getattr(body, "data", None)
    task_id = str(getattr(data, "task_id", "") or "")
    if not task_id:
        raise RuntimeError("Aliyun Tingwu CreateTask did not return a TaskId.")
    return task_id


def wait_for_tingwu_task(
    client: Any,
    task_id: str,
    config: dict[str, str],
    progress_callback: ProgressCallback | None = None,
) -> TingwuNotes:
    timeout_seconds = max(60, int(config["timeout_seconds"]))
    poll_seconds = max(3, int(config["poll_seconds"]))
    deadline = time.time() + timeout_seconds
    last_status = "ONGOING"
    while time.time() < deadline:
        response = client.get_task_info(task_id)
        body = response.body
        code = str(getattr(body, "code", "") or "")
        if code not in {"0", "OK", "Success", ""}:
            raise RuntimeError(f"Aliyun Tingwu GetTaskInfo failed: {code} {getattr(body, 'message', '')}")
        data = getattr(body, "data", None)
        status = str(getattr(data, "task_status", "") or "ONGOING")
        if status != last_status:
            print(f"Aliyun Tingwu status: {status}", flush=True)
            last_status = status
        if progress_callback:
            progress_callback("waiting", f"Aliyun Tingwu is processing the recording ({status}).", {"status": status})
        if status == "COMPLETED":
            return build_tingwu_notes(task_id, data, progress_callback)
        if status in {"FAILED", "INVALID"}:
            error_code = getattr(data, "error_code", "") or ""
            error_message = getattr(data, "error_message", "") or ""
            raise RuntimeError(f"Aliyun Tingwu task failed: {status} {error_code} {error_message}")
        time.sleep(poll_seconds)
    raise RuntimeError("Aliyun Tingwu task timed out.")


def build_tingwu_notes(
    task_id: str,
    data: Any,
    progress_callback: ProgressCallback | None = None,
) -> TingwuNotes:
    result = getattr(data, "result", None)
    notes = TingwuNotes(
        task_id=task_id,
        task_key=str(getattr(data, "task_key", "") or ""),
        status=str(getattr(data, "task_status", "") or ""),
        transcript_url=str(getattr(result, "transcription", "") or ""),
        meeting_url=str(getattr(result, "meeting_assistance", "") or ""),
        summary_url=str(getattr(result, "summarization", "") or ""),
        text_polish_url=str(getattr(result, "text_polish", "") or ""),
    )
    print("Aliyun Tingwu: downloading task results", flush=True)
    if progress_callback:
        progress_callback("downloading", "Downloading Tingwu transcript and meeting-notes results.", None)
    notes.transcript_json = download_json(notes.transcript_url)
    notes.meeting_json = download_json(notes.meeting_url)
    notes.summary_json = download_json(notes.summary_url)
    notes.text_polish_json = download_json(notes.text_polish_url)
    return notes


def download_json(url: str) -> dict[str, Any]:
    if not url:
        return {}
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = response.read().decode("utf-8", errors="replace")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return {"raw": payload}
    return value if isinstance(value, dict) else {"value": value}


def tingwu_language(value: str) -> str:
    language = (value or "").strip().lower()
    if language.startswith("zh") or language in {"cn", "chinese", "mandarin"}:
        return "cn"
    if language.startswith("ja"):
        return "ja"
    if language.startswith("yue") or language in {"cantonese"}:
        return "yue"
    if language in {"fspk", "mixed", "auto"}:
        return "fspk"
    return "en"


def extract_tingwu_segments(payload: dict[str, Any]) -> list[TingwuSegment]:
    transcription = payload.get("Transcription") if isinstance(payload, dict) else None
    if not isinstance(transcription, dict):
        transcription = payload
    paragraphs = transcription.get("Paragraphs") if isinstance(transcription, dict) else None
    if not isinstance(paragraphs, list):
        return []
    segments: list[TingwuSegment] = []
    for paragraph in paragraphs:
        if not isinstance(paragraph, dict):
            continue
        words = paragraph.get("Words")
        if not isinstance(words, list) or not words:
            continue
        speaker = str(paragraph.get("SpeakerId") or paragraph.get("speakerId") or "?")
        grouped: dict[Any, list[dict[str, Any]]] = {}
        for word in words:
            if not isinstance(word, dict):
                continue
            sentence_id = word.get("SentenceId", word.get("sentenceId", len(grouped)))
            grouped.setdefault(sentence_id, []).append(word)
        for sentence_words in grouped.values():
            text = "".join(str(item.get("Text") or item.get("text") or "") for item in sentence_words).strip()
            if not text:
                continue
            starts = [to_seconds(item.get("Start", item.get("start"))) for item in sentence_words]
            ends = [to_seconds(item.get("End", item.get("end"))) for item in sentence_words]
            segments.append(
                TingwuSegment(
                    start=min(starts) if starts else 0.0,
                    end=max(ends) if ends else 0.0,
                    text=text,
                    speaker=f"Speaker {speaker}",
                )
            )
    return sorted(segments, key=lambda item: (item.start, item.end))


def to_seconds(value: Any) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number / 1000.0


def render_tingwu_transcript(audio: Path, notes: TingwuNotes) -> str:
    lines = [
        "# Meeting Transcript",
        "",
        f"- Audio: `{audio.name}`",
        f"- Provider: Aliyun Tingwu",
        f"- TaskId: `{notes.task_id}`",
        "",
        "## Full Transcript",
        "",
    ]
    if not notes.segments:
        lines.append("- No readable transcript segments were returned.")
    for item in notes.segments:
        lines.append(f"- {format_time(item.start)}-{format_time(item.end)} `{item.speaker}` {item.text}")
    return "\n".join(lines).strip() + "\n"


def render_tingwu_minutes(audio: Path, notes: TingwuNotes, notes_language: str = "en") -> str:
    summary_title = extract_summary_title(notes.summary_json) or "Meeting Minutes"
    paragraph_summary = extract_paragraph_summary(notes.summary_json)
    summary_points = filter_summary_points(
        dedupe_texts(extract_summary_points(notes.summary_json, limit=8)),
        summary_title,
        paragraph_summary,
    )
    actions = dedupe_texts(extract_action_items(notes.meeting_json, limit=12))
    key_sentences = dedupe_texts(extract_key_sentences(notes.meeting_json, limit=10))
    attendees = format_attendees(notes)
    meeting_time = format_meeting_time(audio)
    meeting_duration = format_audio_duration(notes)
    agenda_topics = build_agenda_topics(actions, key_sentences, summary_points)
    topic_sections = build_topic_sections(actions, key_sentences, summary_points)
    conclusion_points = build_conclusion_points(summary_points, actions)
    title_line = build_minutes_title(audio, summary_title)
    minutes_data = {
        "title_line": title_line,
        "summary_title": summary_title,
        "paragraph_summary": paragraph_summary or "This meeting focused on the main engineering topics, open issues, and required follow-up work captured in the transcript.",
        "meeting_time": meeting_time,
        "meeting_duration": meeting_duration,
        "audio_name": audio.name,
        "attendees": attendees,
        "agenda_topics": agenda_topics,
        "summary_points": summary_points[:5],
        "topic_sections": topic_sections,
        "actions": actions,
        "conclusion_points": conclusion_points,
        "key_sentences": key_sentences[:6],
    }
    minutes_data = polish_english_minutes_data(minutes_data)
    if is_chinese_minutes_language(notes_language):
        return render_tingwu_minutes_chinese(minutes_data)
    return render_tingwu_minutes_bilingual(minutes_data)


def is_chinese_minutes_language(notes_language: str) -> bool:
    lowered = (notes_language or "").strip().lower()
    return lowered.startswith("zh") or lowered in {"cn", "chinese", "zh-cn", "zh-hans"}


def polish_english_minutes_data(data: dict[str, Any]) -> dict[str, Any]:
    polished = dict(data)
    polished["summary_title"] = polish_english_minutes_text(str(data["summary_title"]))
    polished["title_line"] = polish_minutes_title(str(data["title_line"]))
    polished["paragraph_summary"] = polish_english_minutes_text(str(data["paragraph_summary"]))
    polished["agenda_topics"] = [polish_english_heading(item) for item in data["agenda_topics"]]
    polished["summary_points"] = [polish_english_minutes_text(item) for item in data["summary_points"]]
    polished["topic_sections"] = [
        (polish_english_heading(heading), [polish_english_minutes_text(item) for item in items])
        for heading, items in data["topic_sections"]
    ]
    polished["actions"] = [polish_english_action_item(item) for item in data["actions"]]
    polished["conclusion_points"] = [polish_english_minutes_text(item) for item in data["conclusion_points"]]
    polished["key_sentences"] = [polish_english_minutes_text(item) for item in data["key_sentences"]]
    return polished


def polish_minutes_title(text: str) -> str:
    if " : " not in text:
        return polish_english_heading(text).rstrip(".")
    prefix, title = text.split(" : ", 1)
    return f"{prefix} : {polish_english_heading(title).rstrip('.')}"


def polish_english_heading(text: str) -> str:
    cleaned = polish_english_minutes_text(text).rstrip(".")
    heading_map = {
        "Piping Design Review and Capacity Changes": "Piping Design Review and Capacity Impact",
        "Tank Condition and Replacement Evaluation": "Tank Condition and Replacement Assessment",
        "Distribution Line and Flow Plate Configuration": "Distribution Line and Flow Plate Configuration",
        "CIP, Pigging, and Operational Constraints": "CIP, Pigging, and Operational Constraints",
        "Model Updates and Engineering Follow-up": "Model Updates and Engineering Follow-up",
        "Additional Discussion and Follow-up": "Additional Discussion and Follow-up",
    }
    return heading_map.get(cleaned, cleaned)


def polish_english_action_item(text: str) -> str:
    cleaned = polish_english_minutes_text(text)
    action_replacements = [
        ("Judy will issue", "Judy to issue"),
        ("the latest version of the PNI D", "the latest version of the P&ID"),
        ("provide feedback by next Monday", "provide feedback by next Monday"),
    ]
    for source, target in action_replacements:
        cleaned = cleaned.replace(source, target)
    return cleaned


def polish_english_minutes_text(text: str) -> str:
    cleaned = clean_result_line(text)
    if not cleaned:
        return ""
    replacements = [
        ("PNI D", "P&ID"),
        ("P N I D", "P&ID"),
        ("PFD words", "PFD documents"),
        ("flow plate", "Flow Plate"),
        ("floor plate", "Flow Plate"),
        ("floor blade", "Flow Plate"),
        ("distro line", "distribution line"),
        ("distro lines", "distribution lines"),
        ("drop tank up to", "drop tank to"),
        ("upsized to 6\"", "increased to 6 inches"),
        ("4\"", "4 inches"),
        ("6\"", "6 inches"),
        ("what it would look like", "the expected configuration"),
        ("piping transfer size increase", "increase in transfer pipe size"),
        ("The issue of picking from", "The issue of product transfer from"),
        ("pushing the feed through", "pushing the product through"),
        ("another head tank before transferring it to the line", "another head tank before sending it to the production line"),
        ("lead to significant downtime", "create significant downtime"),
        ("was not fully addressed in the transcript", "requires further confirmation"),
        ("around $250,000 worth of repairs", "approximately $250,000 in repairs"),
        ("as part of the project", "within the project scope"),
        ("in a brief conversation", "during a brief discussion"),
        ("The team is assessing whether it makes more sense", "The team is assessing whether it is more practical"),
    ]
    for source, target in replacements:
        cleaned = cleaned.replace(source, target)
    cleaned = clean_repeated_words(cleaned)
    cleaned = cleaned.replace(" ,", ",").replace(" .", ".").replace(" ;", ";").replace(" :", ":")
    cleaned = cleaned.replace("..", ".")
    cleaned = cleaned.replace(" i ", " I ")
    if cleaned and cleaned[-1].isalnum() and len(cleaned.split()) > 8:
        cleaned += "."
    return cleaned


def clean_repeated_words(text: str) -> str:
    words = text.split()
    if not words:
        return ""
    result = [words[0]]
    for word in words[1:]:
        previous = result[-1].strip(".,;:!?").lower()
        current = word.strip(".,;:!?").lower()
        if current == previous and len(current) > 2:
            continue
        result.append(word)
    return " ".join(result)


def render_tingwu_minutes_bilingual(data: dict[str, Any]) -> str:
    lines = render_tingwu_minutes_english(data)
    chinese_data = translate_minutes_data_to_chinese(data)
    lines.extend(
        [
            "",
            "---",
            "",
            "## 中文阅读版",
            "",
            "以下内容为中文阅读版，便于快速理解会议重点；如需对外发送，建议结合英文主版一起复核。",
            "",
        ]
    )
    lines.extend(render_tingwu_minutes_chinese_sections(chinese_data))
    return "\n".join(lines).strip() + "\n"


def render_tingwu_minutes_chinese(data: dict[str, Any]) -> str:
    chinese_data = translate_minutes_data_to_chinese(data)
    lines = [f"# {data['title_line']}", ""]
    lines.extend(render_tingwu_minutes_chinese_sections(chinese_data))
    return "\n".join(lines).strip() + "\n"


def render_tingwu_minutes_english(data: dict[str, Any]) -> list[str]:
    lines = [
        f"# {data['title_line']}",
        "",
        "Content Summary",
        "",
        data["paragraph_summary"],
        "",
        "## Meeting Information",
        "",
        "| Item | Description |",
        "| --- | --- |",
        f"| Meeting Time | {data['meeting_time']} |",
        "| Meeting Location | No information |",
        f"| Meeting Duration | {data['meeting_duration']} |",
        f"| Source Audio | {data['audio_name']} |",
        f"| Attendees | {data['attendees']} |",
        "| Provider | Aliyun Tingwu |",
        "",
        "## Meeting Agenda",
        "",
    ]
    agenda_topics = data["agenda_topics"]
    if agenda_topics:
        for topic in agenda_topics:
            lines.append(f"- {topic}")
    else:
        lines.append("- Main discussion topics were not clearly extracted.")
    lines.extend(["", "## I. Discussion Highlights", ""])
    summary_points = data["summary_points"]
    if summary_points:
        for item in summary_points:
            lines.append(f"- {item}")
    else:
        lines.append("- No concise highlight points were returned.")
    lines.extend(["", "## II. Detailed Discussion", ""])
    topic_sections = data["topic_sections"]
    if topic_sections:
        for index, (heading, items) in enumerate(topic_sections, start=1):
            lines.append(f"### {index}. {heading}")
            lines.append("")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")
    else:
        lines.append("- No structured topic sections were extracted.")
        lines.append("")
    lines.extend(["## III. Action Items", ""])
    actions = data["actions"]
    if actions:
        for item in actions:
            lines.append(f"- {item}")
    else:
        lines.append("- No clear action items were returned.")
    lines.extend(["", "## Meeting Conclusions", ""])
    conclusion_points = data["conclusion_points"]
    if conclusion_points:
        for item in conclusion_points:
            lines.append(f"- {item}")
    else:
        lines.append("- No clear meeting conclusions were returned.")
    lines.extend(["", "## Reference Notes", ""])
    key_sentences = data["key_sentences"]
    if key_sentences:
        for item in key_sentences:
            lines.append(f"- {item}")
    else:
        lines.append("- No concise reference notes were returned.")
    return lines


def render_tingwu_minutes_chinese_sections(data: dict[str, Any]) -> list[str]:
    lines = [
        "内容摘要",
        "",
        data["paragraph_summary"],
        "",
        "## 会议信息",
        "",
        "| 项目 | 内容 |",
        "| --- | --- |",
        f"| 会议时间 | {data['meeting_time']} |",
        "| 会议地点 | 暂未提供 |",
        f"| 会议时长 | {data['meeting_duration']} |",
        f"| 录音文件 | {data['audio_name']} |",
        f"| 参会对象 | {data['attendees']} |",
        "| 生成方式 | 阿里听悟 |",
        "",
        "## 会议议题",
        "",
    ]
    agenda_topics = data["agenda_topics"]
    if agenda_topics:
        for topic in agenda_topics:
            lines.append(f"- {topic}")
    else:
        lines.append("- 暂未提取出清晰的议题。")
    lines.extend(["", "## 一、重点结论", ""])
    summary_points = data["summary_points"]
    if summary_points:
        for item in summary_points:
            lines.append(f"- {item}")
    else:
        lines.append("- 暂未提取出清晰的重点结论。")
    lines.extend(["", "## 二、讨论内容", ""])
    topic_sections = data["topic_sections"]
    if topic_sections:
        for index, (heading, items) in enumerate(topic_sections, start=1):
            lines.append(f"### {index}. {heading}")
            lines.append("")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")
    else:
        lines.append("- 暂未生成结构化讨论内容。")
        lines.append("")
    lines.extend(["## 三、后续行动", ""])
    actions = data["actions"]
    if actions:
        for item in actions:
            lines.append(f"- {item}")
    else:
        lines.append("- 暂未提取出明确行动项。")
    lines.extend(["", "## 四、会议结论", ""])
    conclusion_points = data["conclusion_points"]
    if conclusion_points:
        for item in conclusion_points:
            lines.append(f"- {item}")
    else:
        lines.append("- 暂未提取出明确会议结论。")
    lines.extend(["", "## 五、补充参考", ""])
    key_sentences = data["key_sentences"]
    if key_sentences:
        for item in key_sentences:
            lines.append(f"- {item}")
    else:
        lines.append("- 暂无补充参考信息。")
    return lines


def translate_minutes_data_to_chinese(data: dict[str, Any]) -> dict[str, Any]:
    translated = dict(data)
    translated["paragraph_summary"] = translate_minutes_text(data["paragraph_summary"])
    translated["agenda_topics"] = translate_minutes_list(data["agenda_topics"])
    translated["summary_points"] = translate_minutes_list(data["summary_points"])
    translated["topic_sections"] = [
        (translate_minutes_text(heading), translate_minutes_list(items))
        for heading, items in data["topic_sections"]
    ]
    translated["actions"] = polish_chinese_action_items(translate_minutes_list(data["actions"]))
    translated["conclusion_points"] = translate_minutes_list(data["conclusion_points"])
    translated["key_sentences"] = translate_minutes_list(data["key_sentences"])
    translated["attendees"] = polish_attendees_for_chinese(data["attendees"])
    return translated


def translate_minutes_list(items: list[str]) -> list[str]:
    return [translate_minutes_text(item) for item in items if clean_result_line(item)]


def translate_minutes_text(text: str) -> str:
    cleaned = clean_result_line(text)
    if not cleaned:
        return ""
    if contains_cjk(cleaned):
        return cleaned
    direct = direct_minutes_translation(cleaned)
    if direct:
        return direct
    translator = get_minutes_translator()
    if translator is None:
        return cleaned
    try:
        translated = translator._translate_sync(cleaned, "eng_Latn", "zho_Hans")
    except Exception:
        return cleaned
    return polish_chinese_minutes_text(translated or cleaned)


def get_minutes_translator() -> Any | None:
    global _MINUTES_TRANSLATOR, _MINUTES_TRANSLATOR_FAILED
    if _MINUTES_TRANSLATOR is not None:
        return _MINUTES_TRANSLATOR
    if _MINUTES_TRANSLATOR_FAILED:
        return None
    try:
        from backend.translator import ArgosTranslator

        _MINUTES_TRANSLATOR = ArgosTranslator("eng_Latn", "zho_Hans")
        return _MINUTES_TRANSLATOR
    except Exception:
        _MINUTES_TRANSLATOR_FAILED = True
        return None


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def direct_minutes_translation(text: str) -> str:
    normalized = " ".join(text.split())
    direct_map = {
        "Piping Design Review and Capacity Changes": "管道方案复核与产能调整",
        "Tank Condition and Replacement Evaluation": "罐体现状与更换评估",
        "Distribution Line and Flow Plate Configuration": "分配管线与 Flow Plate 配置",
        "CIP, Pigging, and Operational Constraints": "CIP、清管与运行限制",
        "Model Updates and Engineering Follow-up": "模型更新与工程跟进",
        "Additional Discussion and Follow-up": "其他讨论与后续跟进",
    }
    return direct_map.get(normalized, "")


def polish_chinese_action_items(items: list[str]) -> list[str]:
    polished: list[str] = []
    for item in items:
        text = polish_chinese_minutes_text(item)
        if text and not text.startswith(("需", "请", "后续", "建议", "由")):
            text = f"后续需{trim_leading_connector(text)}"
        polished.append(text)
    return polished


def polish_attendees_for_chinese(text: str) -> str:
    cleaned = clean_result_line(text)
    if not cleaned:
        return "暂未识别"
    if cleaned == "No speaker names identified":
        return "暂未识别具体姓名"
    if cleaned.lower().startswith("speaker "):
        return cleaned.replace("Speaker", "发言人")
    return cleaned


def polish_chinese_minutes_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    replacements = [
        ("Piping Design Review and Capacity Changes", "管道方案复核与产能调整"),
        ("Tank Condition and Replacement Evaluation", "罐体现状与更换评估"),
        ("Distribution Line and Flow Plate Configuration", "分配管线与 Flow Plate 配置"),
        ("CIP, Pigging, and Operational Constraints", "CIP、清管与运行限制"),
        ("Additional Discussion and Follow-up", "其他讨论与后续跟进"),
        ("pigging", "清管作业"),
        ("pig", "清管"),
        ("flow plate", "Flow Plate"),
        ("distribution line", "分配管线"),
        ("common base tank", "公共基础罐"),
        ("drop tank", "落料罐"),
        ("whip tank", "whip 罐"),
        ("head tank", "头罐"),
        ("booster pump", "增压泵"),
        ("caustic tank", "苛性碱罐"),
        ("sorbitol", "山梨醇"),
        ("c sku", "C SKU"),
        ("speaker", "发言人"),
        ("meeting", "会议"),
        ("minutes", "纪要"),
        ("action item", "行动项"),
        ("action items", "行动项"),
        ("follow-up", "后续跟进"),
        ("follow up", "后续跟进"),
        ("no information", "暂未提供"),
        ("not identified", "暂未识别"),
        ("reliability", "可靠性"),
        ("ergonomics", "人机工程"),
        ("operational needs", "运营需求"),
        ("cost-effectiveness", "成本效益"),
        ("tank", "罐体"),
        ("piping", "管道"),
    ]
    for source, target in replacements:
        cleaned = cleaned.replace(source, target).replace(source.title(), target).replace(source.upper(), target)

    post_replacements = [
        ("养猪", "清管"),
        ("跑猪", "进行清管"),
        ("猪笼草", "清管"),
        ("致癌罐", "苛性碱罐"),
        ("致病罐", "苛性碱罐"),
        ("轨道醇", "山梨醇"),
        ("坦克", "罐体"),
        ("普通基罐", "公共基础罐"),
        ("滴水箱", "落料罐"),
        ("头型油箱", "头罐"),
        ("另一头油箱", "另一只头罐"),
        ("分布线", "分配管线"),
        ("业务限制", "运行限制"),
        ("业务需要", "运营需求"),
        ("业务效率", "运营效率"),
        ("工程学", "人机工程"),
        ("奶油", "物料"),
        ("鞭子油箱", "whip 罐"),
        ("鞭子箱", "whip 罐"),
        ("头箱", "头罐"),
        ("投放油箱", "落料罐"),
        ("轨道醇", "山梨醇"),
        ("评价", "评估"),
        ("更换评价", "更换评估"),
        ("普通头型", "公共头罐"),
        ("普通头条", "公共总管"),
        ("车头油箱", "头罐"),
        ("回头返回", "回流总管返回"),
        ("捕捉可行性", "清管可行性"),
        ("PFD词", "PFD文档"),
        ("PNI D", "P&ID"),
        ("转移到线路", "再送入产线"),
        ("through common headers", "通过公共总管"),
    ]
    for source, target in post_replacements:
        cleaned = cleaned.replace(source, target)

    cleaned = cleaned.replace(" ,", "，").replace(" .", "。").replace(" ;", "；").replace(" :", "：")
    cleaned = cleaned.replace('4"', "4英寸").replace('6"', "6英寸")
    cleaned = cleaned.replace("..", "。").replace(". ", "。")
    cleaned = cleaned.replace(",", "，")
    cleaned = cleaned.replace("(", "（").replace(")", "）")
    return trim_leading_connector(cleaned)


def trim_leading_connector(text: str) -> str:
    cleaned = text.strip(" -")
    for prefix in ("并且", "同时", "另外", "此外", "以及", "然后", "需要", "需", "请"):
        if cleaned.startswith(prefix) and len(cleaned) > len(prefix) + 1:
            cleaned = cleaned[len(prefix):].lstrip("，,:： ")
            break
    return cleaned


def extract_paragraph_summary(value: Any) -> str:
    summarization = value.get("Summarization") if isinstance(value, dict) else None
    if isinstance(summarization, dict):
        text = clean_result_line(summarization.get("ParagraphSummary") or "")
        if text:
            return text
    return ""


def filter_summary_points(items: list[str], title: str, paragraph_summary: str) -> list[str]:
    filtered: list[str] = []
    title_key = clean_result_line(title).lower()
    summary_key = clean_result_line(paragraph_summary).lower()
    for item in items:
        key = clean_result_line(item).lower()
        if not key:
            continue
        if key == title_key or key == summary_key:
            continue
        filtered.append(item)
    return filtered[:6]


def extract_action_items(value: Any, limit: int = 10) -> list[str]:
    meeting = value.get("MeetingAssistance") if isinstance(value, dict) else None
    items = meeting.get("Actions") if isinstance(meeting, dict) else None
    if not isinstance(items, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        text = clean_result_line(item.get("Text") or "")
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def extract_key_sentences(value: Any, limit: int = 8) -> list[str]:
    meeting = value.get("MeetingAssistance") if isinstance(value, dict) else None
    items = meeting.get("KeySentences") if isinstance(meeting, dict) else None
    if not isinstance(items, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        text = clean_result_line(item.get("Text") or "")
        if not text or text in seen or len(text) < 25:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def dedupe_texts(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = clean_result_line(item)
        lowered = cleaned.lower()
        if not cleaned or lowered in seen:
            continue
        seen.add(lowered)
        result.append(cleaned)
    return result


def format_attendees(notes: TingwuNotes) -> str:
    speakers: list[str] = []
    seen: set[str] = set()
    for item in notes.segments:
        speaker = clean_result_line(item.speaker)
        lowered = speaker.lower()
        if speaker and lowered not in seen:
            seen.add(lowered)
            speakers.append(speaker)
    return ", ".join(speakers) if speakers else "No speaker names identified"


def format_meeting_time(audio: Path) -> str:
    stamp = time.localtime(audio.stat().st_mtime)
    return time.strftime("%Y-%m-%d %H:%M", stamp)


def build_minutes_title(audio: Path, summary_title: str) -> str:
    stamp = time.localtime(audio.stat().st_mtime)
    return f"{time.strftime('%m-%d', stamp)} : {summary_title}"


def format_audio_duration(notes: TingwuNotes) -> str:
    transcription = notes.transcript_json.get("Transcription") if isinstance(notes.transcript_json, dict) else None
    audio_info = transcription.get("AudioInfo") if isinstance(transcription, dict) else None
    duration_ms = 0
    if isinstance(audio_info, dict):
        try:
            duration_ms = int(audio_info.get("Duration") or 0)
        except (TypeError, ValueError):
            duration_ms = 0
    total_seconds = max(0, duration_ms // 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes}m {seconds}s"


def build_agenda_topics(actions: list[str], key_sentences: list[str], summary_points: list[str]) -> list[str]:
    sections = build_topic_sections(actions, key_sentences, summary_points)
    return [heading for heading, _ in sections]


def build_topic_sections(
    actions: list[str],
    key_sentences: list[str],
    summary_points: list[str],
) -> list[tuple[str, list[str]]]:
    topic_rules = [
        ("Piping Design Review and Capacity Changes", ("piping", "pipe", "common base tank", "booster pump", '6 inches', '4 inches', "transfer size")),
        ("Tank Condition and Replacement Evaluation", ("tank", "sorbitol", "caustic", "inspection", "repair", "replacement")),
        ("Distribution Line and Flow Plate Configuration", ("flow plate", "distribution", "distro", "head tank", "jumper", "transfer line")),
        ("CIP, Pigging, and Operational Constraints", ("cip", "pigging", "cleaning", "changeover", "flexibility", "radius")),
        ("Model Updates and Engineering Follow-up", ("3d model", "color-coded", "connection matrix", "automation", "robot", "documentation")),
    ]
    source_items = dedupe_texts(summary_points + actions + key_sentences)
    grouped: list[tuple[str, list[str]]] = []
    used: set[str] = set()
    for heading, keywords in topic_rules:
        bucket = []
        for item in source_items:
            lowered = item.lower()
            if lowered in used:
                continue
            if any(keyword in lowered for keyword in keywords):
                used.add(lowered)
                bucket.append(item)
        if bucket:
            grouped.append((heading, bucket[:4]))
    remainder = [item for item in source_items if item.lower() not in used]
    if remainder:
        grouped.append(("Additional Discussion and Follow-up", remainder[:4]))
    return grouped[:5]


def build_conclusion_points(summary_points: list[str], actions: list[str]) -> list[str]:
    conclusions = dedupe_texts(summary_points[:3] + actions[:3])
    return conclusions[:5]


def readable_json_text(value: Any) -> str:
    texts = collect_strings(value)
    filtered: list[str] = []
    seen: set[str] = set()
    for text in texts:
        cleaned = " ".join(text.split())
        if len(cleaned) < 2 or cleaned in seen or cleaned.startswith("http"):
            continue
        if cleaned.isdigit() and len(cleaned) >= 8:
            continue
        filtered.append(cleaned)
        seen.add(cleaned)
        if len(filtered) >= 40:
            break
    if not filtered and value:
        return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2)[:6000] + "\n```"
    return "\n".join(f"- {text}" for text in filtered)


def extract_summary_title(value: Any) -> str:
    for text in collect_strings(value):
        cleaned = clean_result_line(text)
        if not cleaned:
            continue
        if is_speaker_label(cleaned) or is_question_like(cleaned) or is_action_like(cleaned):
            continue
        if 12 <= len(cleaned) <= 120 and "." not in cleaned and ":" not in cleaned:
            return cleaned
    return ""


def extract_summary_points(value: Any, limit: int = 4) -> list[str]:
    points: list[str] = []
    seen: set[str] = set()
    for text in collect_strings(value):
        cleaned = clean_result_line(text)
        if not cleaned or cleaned in seen:
            continue
        if is_speaker_label(cleaned) or is_question_like(cleaned) or is_action_like(cleaned):
            continue
        if len(cleaned) < 35 or len(cleaned) > 360:
            continue
        points.append(cleaned)
        seen.add(cleaned)
        if len(points) >= limit:
            break
    return points


def extract_keywords(value: Any, limit: int = 10) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for text in collect_strings(value):
        cleaned = clean_result_line(text)
        if not cleaned or cleaned in seen:
            continue
        if is_speaker_label(cleaned) or is_question_like(cleaned) or is_action_like(cleaned):
            continue
        if len(cleaned) > 42:
            continue
        if re_full_sentence(cleaned):
            continue
        keywords.append(cleaned)
        seen.add(cleaned)
        if len(keywords) >= limit:
            break
    return keywords


def render_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def clean_result_line(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    cleaned = cleaned.strip(" -")
    return cleaned


def is_speaker_label(text: str) -> bool:
    lowered = text.lower()
    return lowered.startswith("speaker ") or lowered.startswith("发言人") or lowered.startswith("speaker:")


def is_question_like(text: str) -> bool:
    lowered = text.lower().strip()
    return lowered.endswith("?") or lowered.startswith(("what ", "why ", "how ", "when ", "where ", "who ", "which "))


def is_action_like(text: str) -> bool:
    lowered = text.lower()
    patterns = [
        " will ",
        " should ",
        " needs to ",
        " need to ",
        " responsible ",
        " due ",
        " within ",
        " report ",
        " follow-up",
        " investigate ",
        " provide ",
        " prepare ",
        " conduct ",
        " submit ",
        " presented ",
        " next board meeting",
        " next quarterly review",
    ]
    return any(pattern in f" {lowered} " for pattern in patterns)


def re_full_sentence(text: str) -> bool:
    return len(text.split()) >= 7


def collect_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(collect_strings(item))
        return result
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            if str(key).lower() in {"taskid", "code", "message", "requestid"}:
                continue
            result.extend(collect_strings(item))
        return result
    return []


def format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
