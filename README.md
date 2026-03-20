# Process Tracker

This project now emits a tiered macOS context snapshot and event stream.

## Files

- `process_tracker.py`: thin launcher
- `tracker/applications.py`: app discovery and process grouping
- `tracker/tier1.py`: reliable low-friction signals
- `tracker/tier2.py`: permissioned interaction probes
- `tracker/tier3.py`: expensive and sensitive probes
- `tracker/stream.py`: event stream builder
- `tracker/main.py`: orchestration and console output

## Usage

Run `python process_tracker.py` to collect a snapshot and write `tracker_output.json`.

## Tier Coverage

- Tier 1: frontmost app, window title, idle state, grouped processes, audio-device state, media hints
- Tier 2: focused accessibility element plus capability reporting for typing, clicks, and scroll capture
- Tier 3: active-window OCR plus capability reporting for microphone and system-audio transcription

## Requirements

- Python 3
- `psutil`
- macOS system tools: `osascript`, `ioreg`, `system_profiler`, `screencapture`, `tesseract`