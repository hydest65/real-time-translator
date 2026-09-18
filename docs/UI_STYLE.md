# UI Style

## Direction

The app uses the selected `Soft UI Evolution / Focus Display` direction. It is still a compact working subtitle studio, not a marketing page, but the visual priority is now the large subtitle monitor.

## Layout

- Top bar:
  - product name
  - small red status lamp
  - input selector
  - speech selector
  - compact `Start` and `End` meeting buttons
  - one compact icon-only shortcut for Notes
- Left side panel:
  - current step
  - caption readiness
  - recording status
  - Cloud usage
  - meeting notes status
  - delay hint
  - no large background capsule behind the whole vertical rail; keep only the individual status cards so the subtitle monitors receive more horizontal space
- Cloud main subtitle monitor:
  - largest visual area on the screen
  - soft raised outer shell
  - recessed inner subtitle stream
  - internal right-side scrollbar
  - preserved subtitle history
  - live row plus final bilingual rows
- Cloud mode keeps the single bilingual subtitle monitor and its scroll-review behavior.
- Local mode uses two stacked monitors:
  - upper monitor for stable source context when English/Spanish local fallback is active
  - lower monitor for slightly delayed complete Chinese sentence translation, or recent live Chinese captions when FunASR local Chinese mode is active

## Subtitle Behavior

- Chinese translation is visually emphasized.
- Cloud mode keeps English source visible above the Chinese in each subtitle row.
- In local mode, English and Chinese are separated into two monitors so the English live transcript can stay responsive while Chinese prioritizes completeness.
- In local Chinese FunASR mode, the Chinese monitor acts as a live caption window: startup status is shown immediately, then only the recent 2-3 lines of realtime text stay visible while the full transcript remains available internally.
- In English/Spanish local mode, stable source context and complete Chinese translation render as continuous text blocks. The source context pane should fill its readable area first and then scroll.
- Long subtitles remain semantically continuous and wrap at the same fixed subtitle size as short subtitles.
- Subtitle rows use compact padding and tight spacing so more history fits inside the monitor.
- Cloud users can scroll up inside the subtitle monitor without losing incoming live subtitles.
- In Cloud mode, if the user is at the bottom, new subtitles auto-follow.
- In Cloud mode, if the user scrolls upward, auto-follow pauses until the user scrolls back to the bottom.
- Tester-facing UI uses `Cloud` wording and avoids naming the underlying provider in labels, hints, status text, and common error messages.

## Status Lamp Behavior

- The top-left lamp is always shaped like a small red indicator.
- When stopped, the lamp remains visible as a dim red bulb.
- When translation is running or connecting, the bulb slowly pulses.
- On error, the bulb stays red without the normal running pulse.

## Visual Style

- Soft gray-blue background `#E8EDF5`.
- Raised panels use dual-direction shadows: dark `#D1D9E6` bottom-right and light `#F0F4FA` top-left.
- Inputs, select controls, subtitle stream, and active/status surfaces use inset shadows for a debossed feel.
- No hard borders, no dark backgrounds, and no pure white surfaces.
- High border radius, generally 16px or above.
- Blue-violet accent is reserved for primary actions, live state, and Chinese subtitle emphasis.
- Red is reserved for the small operating lamp and error state.
- Control chrome stays compact so meeting attention remains on the subtitle display.
- The main operation should be understandable as a simple sequence: start meeting, watch captions, end meeting, open bilingual notes.
- The top-level topbar shell is transparent; the brand block and toolbar keep their own soft raised cards.
- The main subtitle monitor keeps its soft raised outer shell because removing it made the page feel visually unfinished.
- Compact controls prefer familiar icon buttons over long labels when the meaning is clear. Any remaining text buttons should share the same soft capsule style as the rest of the UI.
- Diagnostics remains available at `/static/diagnostics.html`, but it is not shown as a main-toolbar shortcut. Open it directly by URL when backend health checks are needed.
- The Notes utility should stay operationally compact. The old visible `Title`, `People`, `Keywords`, and `Context` input block is intentionally removed from the main UI unless a future workflow clearly needs it.

## Visual UI Editor

- Interface language is English across the main window, connection and font settings, UI editor, diagnostics, and local speech startup messages. Recognized speech, translated captions, and user recording names retain their original language.

### Caption sizing (2026-09-18)

- The main window footer exposes separate source and translation sliders and numeric inputs (12–96px).
- Defaults are 18px source and 32px translation. Changes apply immediately and persist in the existing browser theme storage; reset restores these two defaults without clearing other theme settings.
- Cloud history, local source text, local translation, and FunASR caption text use the same font variables. Resizing the window does not reduce the selected font size.
- Long captions wrap, including unbroken words, and remain scrollable. Changing font size keeps readers following the live end when already at the bottom and preserves the scroll offset when reviewing history.
- Below 980px, hide the status sidebar and keep the subtitle stream and footer inside the viewport. This is a responsive browser layout, not a native always-on-top window.
- Windows packaging, independent floating-window preferences, and overall UI zoom remain future work.
- Verified in headless Edge: numeric input, slider keyboard input, bounds, empty input, reload persistence, reset, long cloud captions at 96px, local translation sizing, history scroll position, and 640px-wide layout. No real microphone/cloud translation session was started during these UI checks.

- The editor is available at `/static/ui-editor.html`.
- It provides browser-side controls for background color, panel color, accent/subtitle color, text color, Chinese subtitle size, English subtitle size, left panel width, corner radius, and background decoration.
- The editor previews the live page through an embedded frame and saves changes to browser `localStorage`.
- The editor is for fast local tuning. Permanent design decisions should still be copied into `frontend/style.css` after the user accepts them.
