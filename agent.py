"""
Local background agent — read-only mode.

Reads tracker_output.json, distills the context into a compact prompt,
sends it to a locally running Ollama model, and prints the agent's response.
No environment modifications are made.
"""

import json
import sys
import urllib.request
import urllib.error

OLLAMA_URL = 'http://localhost:11434/api/chat'
MODEL = 'llama3.2:3b'
TRACKER_FILE = 'tracker_output.json'


# ── prompt builder ────────────────────────────────────────────────────────────

def build_system_prompt():
    return """You are a silent background assistant running locally on the user's macOS machine.

You receive a structured snapshot of what the user is currently doing — their active app, \
window, typing activity, audio state, cognitive load, and a suggested agent mode.

Your job is to reason about this snapshot and decide what (if anything) to do. \
Right now you are in READ-ONLY mode — you cannot and will not modify the environment, \
open apps, send notifications, or take any action. You only produce a response.

For each snapshot you receive, output a brief structured reasoning block followed \
by a plain-English "agent note" — what you would do if you were allowed to act, \
and why. Be concise. If the user is deep in focus, say so and stay out of the way."""


def build_user_prompt(snapshot: dict) -> str:
    ctx = snapshot.get('context', {})
    session = ctx.get('session', {})
    user_state = ctx.get('user_state', {})
    audio = ctx.get('audio_state', {})
    agent_hint = ctx.get('agent', {})

    # Compact action summary — just key event types (skip all the move noise)
    events = snapshot.get('action_sequence', [])
    key_events = [
        e for e in events
        if e.get('event') in ('focused', 'typed', 'clicked', 'scrolled', 'talking', 'audio_playing', 'idle')
    ]
    event_summary = []
    for e in key_events[:8]:
        parts = [f"{e.get('event')}@{e.get('app', '?')}"]
        if e.get('token'):
            parts.append(f"({e['token']})")
        if e.get('sound_text'):
            parts.append(f"({e['sound_text']})")
        event_summary.append(' '.join(parts))

    lines = [
        f"timestamp: {snapshot.get('timestamp', '?')}",
        "",
        "## Session",
        f"  activity:     {session.get('activity', '?')}",
        f"  focus_app:    {session.get('focus_app', '?')}",
        f"  focus_window: {session.get('focus_window', '?')}",
        f"  apps_open:    {', '.join(a['name'] for a in session.get('apps_open', []))}",
        "",
        "## User State",
        f"  presence:       {user_state.get('presence', '?')}",
        f"  speaking:       {user_state.get('speaking', False)}",
        f"  listening:      {user_state.get('listening', False)}",
        f"  typing:         {user_state.get('typing_intensity', 'none')}",
        f"  cognitive_load: {user_state.get('cognitive_load', '?')}",
        f"  confidence:     {user_state.get('confidence', 0)}",
        "",
        "## Audio",
        f"  mic_active:    {audio.get('microphone_active', False)}",
        f"  speech:        {audio.get('speech_detected', False)}",
        f"  ambient:       {audio.get('ambient', 'silence')}",
    ]
    if audio.get('system_audio_content'):
        lines.append(f"  playing:       {audio['system_audio_content']} (via {audio.get('system_audio_source', '?')})")
    if audio.get('mic_transcript'):
        lines.append(f"  mic_transcript: \"{audio['mic_transcript']}\"")

    lines += [
        "",
        "## Agent Hint (pre-computed)",
        f"  mode:       {agent_hint.get('mode', '?')}",
        f"  directives: {', '.join(agent_hint.get('directives', []))}",
        f"  opportunity: {agent_hint.get('opportunity', {}).get('type', '?')} → {agent_hint.get('opportunity', {}).get('trigger', '?')}",
        "",
        "## Key Events",
        *[f"  - {e}" for e in event_summary],
    ]

    return '\n'.join(lines)


# ── ollama client ─────────────────────────────────────────────────────────────

def chat(system: str, user: str, model: str = MODEL) -> str:
    payload = json.dumps({
        'model': model,
        'stream': False,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
    }).encode()

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
            return body['message']['content'].strip()
    except urllib.error.URLError as exc:
        return f'[ERROR] Could not reach Ollama at {OLLAMA_URL}: {exc}'


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    # Load snapshot
    try:
        with open(TRACKER_FILE) as f:
            snapshot = json.load(f)
    except FileNotFoundError:
        print(f'[ERROR] {TRACKER_FILE} not found. Run process_tracker.py first.')
        sys.exit(1)

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(snapshot)

    print('=' * 72)
    print('CONTEXT SENT TO AGENT')
    print('=' * 72)
    print(user_prompt)
    print()
    print('=' * 72)
    print(f'AGENT RESPONSE  (model: {MODEL})')
    print('=' * 72)

    response = chat(system_prompt, user_prompt)
    print(response)
    print()


if __name__ == '__main__':
    main()
