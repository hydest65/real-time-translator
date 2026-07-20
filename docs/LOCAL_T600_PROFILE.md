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

All tester machines are treated as 16GB RAM machines for preset selection. The preset choice is based on graphics/compute class, not memory size.

## Recommended Local Settings

- Engine: `Argos`
- Input: `System`, when translating meeting audio from the computer
- ASR Preset: `HP`
- ASR model: `small.en`
- Device: `cuda`
- Compute type: `int8_float16`
- Decode: `beam 3`, `best_of 3`, no previous-chunk conditioning
- Latency: `Steady`
- Chunk: `2s`

## Optional Experiments

- `iGPU`: `base(.en) + cpu + int8 + beam 1`
  - Recommended for 16GB RAM machines with integrated graphics and ordinary office laptops.
- `dGPU`: `small(.en) + auto + int8 + beam 2`
  - Recommended for 16GB RAM machines with a general discrete GPU when the exact CUDA capability is unknown.
- `HP`: `small(.en) + cuda + int8_float16 + beam 3`
  - Recommended for 16GB RAM workstation-class machines such as the T600 4GB GPU or stronger NVIDIA GPUs.
  - If the model fails to load or latency becomes too high, return to `dGPU` or Cloud mode.
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

- Version: `0.2.0-aliyun-tingwu-qwen-notes`
- Branch intent: keep the guided meeting workflow, tester-friendly hardware tiers, provider-neutral Cloud UI, cloud usage sync, and bilingual Word meeting-notes behavior together for this laptop.
- Notes behavior: end the meeting, generate one `.docx`, then open the bilingual document in Word. Post-meeting local fallback defaults to CPU unless `POST_MEETING_ASR_DEVICE` opts into CUDA/auto.
