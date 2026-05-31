from __future__ import annotations

import argparse
import os
from pathlib import Path


def format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Post-process a meeting audio file with local speaker diarization.",
    )
    parser.add_argument("audio", type=Path, help="Path to the recorded meeting audio file.")
    parser.add_argument(
        "--model",
        default="pyannote/speaker-diarization-3.1",
        help="pyannote model id. Defaults to pyannote/speaker-diarization-3.1.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN"),
        help="Hugging Face token. Defaults to HF_TOKEN or HUGGINGFACE_TOKEN.",
    )
    args = parser.parse_args()

    if not args.audio.exists():
        raise SystemExit(f"Audio file not found: {args.audio}")

    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise SystemExit(
            "pyannote.audio is not installed. Install it in a separate environment, "
            "then run this script again."
        ) from exc

    if not args.token:
        raise SystemExit(
            "Set HF_TOKEN first. pyannote speaker diarization models require Hugging Face access."
        )

    try:
        pipeline = Pipeline.from_pretrained(args.model, token=args.token)
    except TypeError:
        pipeline = Pipeline.from_pretrained(args.model, use_auth_token=args.token)

    try:
        import numpy as np
        import torch
        import soundfile as sf
    except ImportError:
        diarization = pipeline(str(args.audio))
    else:
        samples, sample_rate = sf.read(str(args.audio), dtype="float32", always_2d=True)
        samples = np.asarray(samples)
        samples = samples.T
        waveform = torch.from_numpy(samples)
        diarization = pipeline({"waveform": waveform, "sample_rate": int(sample_rate)})
    if hasattr(diarization, "speaker_diarization"):
        diarization = diarization.speaker_diarization

    output_base = args.audio.with_suffix("")
    rttm_path = output_base.with_suffix(".speakers.rttm")
    md_path = output_base.with_suffix(".speakers.md")

    with rttm_path.open("w", encoding="utf-8") as handle:
        diarization.write_rttm(handle)

    lines = [
        "# Speaker Diarization",
        "",
        f"- Audio: `{args.audio.name}`",
        f"- Model: `{args.model}`",
        "",
        "These labels are anonymous speaker clusters, not verified real names.",
        "",
        "## Speaker Segments",
        "",
    ]
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        lines.append(f"- {format_time(turn.start)}-{format_time(turn.end)} `{speaker}`")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {rttm_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
