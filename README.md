# Process Tracker

A macOS background context tracker that captures what the user is doing and converts it into a structured semantic object an AI agent can reason on.

## Architecture

```
process_tracker.py       ← launcher (capture + write tracker_output.json)
agent.py                 ← local LLM agent (reads tracker_output.json, responds)
tracker/
  applications.py        ← app discovery and process grouping
  tier1.py               ← reliable low-friction signals (apps, focus, processes)
  tier2.py               ← Quartz event tap (keyboard/mouse/scroll, per-event timestamps)
  tier3.py               ← expensive probes (OCR, microphone, system audio)
  context.py             ← semantic inference layer (activity, user_state, agent mode)
  stream.py              ← builds action_sequence and final output dict
  main.py                ← orchestration, parallel collection, console output
```

## Output Schema

`tracker_output.json` top-level keys:

```json
{
  "timestamp": "...",
  "context": {
    "session":    { "activity", "focus_app", "focus_window", "apps_open" },
    "user_state": { "presence", "speaking", "listening", "typing_intensity", "cognitive_load", "confidence" },
    "audio_state":{ "microphone_active", "speech_detected", "ambient", "system_audio_source", ... },
    "agent":      { "mode", "directives", "opportunity" }
  },
  "action_sequence": [ ... ],
  "tiers": { "tier1": {...}, "tier2": {...}, "tier3": {...} }
}
```

Agent modes: `non_interruptive_assist` · `focused_assist` · `active_assist` · `standby`

## Setup

### 1. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. macOS permissions

Grant the terminal (or IDE) these permissions in **System Settings → Privacy & Security**:
- **Input Monitoring** — required for Tier 2 keyboard/mouse capture
- **Accessibility** — required for window title and element queries
- **Screen Recording** — required for Tier 3 OCR
- **Microphone** — required for Tier 3 mic audio probe

### 3. Optional system tools

| Tool | Purpose |
|---|---|
| `tesseract` | Tier 3 OCR (`brew install tesseract`) |
| `ffmpeg` | Audio volume probe (`brew install ffmpeg`) |

### 4. Local LLM (for agent.py)

Install [Ollama](https://ollama.com):

```bash
brew install ollama
ollama serve &          # start the local model server
ollama pull llama3.2:3b # download the model (~2 GB, runs on Apple Silicon)
```

## Usage

```bash
# Capture a snapshot
python process_tracker.py

# Run the agent against the latest snapshot (read-only, no env changes)
python agent.py
```

## Tier Coverage

| Tier | What it captures |
|---|---|
| 1 | Frontmost app, window titles, running processes, media hints |
| 2 | Per-event keyboard/mouse/scroll timeline with timestamps |
| 3 | Active-window OCR, microphone volume probe, system audio state |
| context | Semantic inference: activity, cognitive load, agent mode |