# Local T600 Profile

Date: 2026-05-08

This file describes the local-only tuning profile for the current machine:

- CPU: Intel Core i7-11800H
- RAM: 16GB
- GPU: NVIDIA T600 Laptop GPU
- GPU memory: 4GB

## Scope

This profile is for the local T600 laptop only. It should not be treated as the general GitHub baseline for a stronger 5070Ti machine.

The 5070Ti machine can likely use a larger or more aggressive local ASR profile. Do not push the T600 defaults to the 5070Ti branch unless the 5070Ti version is explicitly being changed to support multi-machine presets.

## Recommended Local Settings

- Engine: `Argos`
- Input: `System`, when translating meeting audio from the computer
- ASR Preset: `Balanced`
- ASR model: `small.en`
- Device: `cuda`
- Compute type: `int8`
- Decode: `beam 2`, `best_of 2`, no previous-chunk conditioning
- Latency: `Low`
- Chunk: `2s`

## Optional Experiments

- `Fast`: `base.en + int8 + beam 1`
  - Use when local latency is more important than transcript detail.
- `Balanced`: `small.en + int8 + beam 2`
  - Recommended default for the T600 4GB GPU.
- `Accurate`: `small.en + int8_float16 + beam 3`
  - Try only when enough GPU memory is free.
  - If the model fails to load or latency becomes too high, return to `Balanced`.
- `medium.en + int8`
  - Manual experiment only.
  - Not recommended as a default on a 4GB GPU.

## Separation Rule

Keep this profile separate from the GitHub/5070Ti baseline.

If syncing to GitHub later:

1. Create or switch to a dedicated branch such as `codex/t600-local-profile` or `codex/t600-guided-meeting-notes`.
2. Do not merge this directly into the 5070Ti baseline branch.
3. If both machines should share one codebase later, convert these settings into explicit machine profiles instead of changing global defaults.

## Current T600 Closeout

- Version: `0.1.10-local-t600`
- Branch intent: keep the guided meeting workflow, T600 local ASR presets, and bilingual Word meeting-notes behavior together for this laptop.
- Notes behavior: end the meeting, generate one `.docx`, then open the bilingual document in Word.
