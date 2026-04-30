# UI Style

## Direction

The app uses the selected `Soft UI Evolution / Focus Display` direction. It is still a compact working subtitle studio, not a marketing page, but the visual priority is now the large subtitle monitor.

## Layout

- Top bar:
  - product name
  - small red status lamp
  - input selector
  - engine selector
  - start/stop controls
  - UI Editor entry button
- Left side panel:
  - status
  - notice
  - activity
  - performance
- Main subtitle monitor:
  - largest visual area on the screen
  - soft raised outer shell
  - recessed inner subtitle stream
  - internal right-side scrollbar
  - preserved subtitle history
  - live row plus final bilingual rows

## Subtitle Behavior

- Chinese translation is visually emphasized.
- English source remains visible above the Chinese.
- Long subtitles remain semantically continuous; the UI reduces font size rather than cutting by time.
- User can scroll up inside the subtitle monitor without losing incoming live subtitles.
- If the user is at the bottom, new subtitles auto-follow.
- If the user scrolls upward, auto-follow pauses until the user scrolls back to the bottom.

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
- The top-level topbar shell is transparent; the brand block and toolbar keep their own soft raised cards.
- The main subtitle monitor keeps its soft raised outer shell because removing it made the page feel visually unfinished.

## Visual UI Editor

- The editor is available at `/static/ui-editor.html`.
- It provides browser-side controls for background color, panel color, accent/subtitle color, text color, Chinese subtitle size, English subtitle size, left panel width, corner radius, and background decoration.
- The editor previews the live page through an embedded frame and saves changes to browser `localStorage`.
- The editor is for fast local tuning. Permanent design decisions should still be copied into `frontend/style.css` after the user accepts them.
