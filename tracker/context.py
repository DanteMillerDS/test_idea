"""
Semantic context layer — converts raw tier data into an agent-readable object.

The context tells an agent:
  - What the user is doing (session.activity)
  - How the user is doing (user_state: presence, load, speaking, etc.)
  - What audio is in the environment (audio_state)
  - What mode and directives the agent should adopt (agent)
"""

MEETING_APP_BUNDLE_IDS = frozenset({
    'us.zoom.xos',
    'com.microsoft.teams',
    'com.microsoft.teams2',
    'com.cisco.webexmeetings',
    'com.hnc.discord',
    'com.tinyspeck.slackmacgap',
})

MEETING_APP_NAME_FRAGMENTS = frozenset({
    'zoom', 'teams', 'webex', 'discord', 'slack', 'skype', 'facetime', 'google meet',
})

MUSIC_APP_NAME_FRAGMENTS = frozenset({
    'spotify', 'apple music', 'music', 'tidal', 'deezer', 'youtube music',
})


# ── helpers ───────────────────────────────────────────────────────────────────


def _is_meeting_app(app_name, bundle_id=''):
    name = (app_name or '').lower()
    bid = (bundle_id or '').lower()
    return (
        any(frag in name for frag in MEETING_APP_NAME_FRAGMENTS)
        or bid in MEETING_APP_BUNDLE_IDS
    )


def _get_focused_app(tier1):
    for app in tier1.get('action_map', {}).get('applications', []):
        if app.get('focus', {}).get('is_frontmost'):
            return app
    return None


# ── inference functions ───────────────────────────────────────────────────────


def _infer_activity(tier1, tier2, tier3):
    """
    Classify the current session activity.
    Priority: meeting > window_type (coding/chat/browser/document) > media_consumption > idle > active
    """
    focused = _get_focused_app(tier1)
    focused_name = focused['name'] if focused else ''
    bundle_id = focused.get('bundle_id', '') if focused else ''

    mic = tier3.get('microphone_transcription', {})
    sys_out = tier3.get('system_output_audio_transcription', {})
    sample = tier2.get('interaction_sample', {})
    actions = sample.get('actions', {})

    # Meeting: focused on a meeting app with mic active
    if _is_meeting_app(focused_name, bundle_id) and mic.get('audio_detected'):
        return 'meeting'

    # Meeting: speaking + any meeting app running in background
    if mic.get('talking_detected') and mic.get('audio_detected'):
        for app in tier1.get('action_map', {}).get('applications', []):
            if (
                _is_meeting_app(app['name'], app.get('bundle_id', ''))
                and app.get('activity', {}).get('state') in ('focused', 'running')
            ):
                return 'meeting'

    # Classify by active window type from tier3
    window_type = tier3.get('active_window', {}).get('window_type', '')
    if window_type in ('coding', 'chat', 'browser', 'document'):
        return window_type

    # Media consumption: system audio detected, no typing
    typing_observed = actions.get('typing', {}).get('status') == 'observed'
    if sys_out.get('listening_detected') and not typing_observed:
        return 'media_consumption'

    # No input at all
    any_input = any(
        actions.get(k, {}).get('status') == 'observed'
        for k in ('typing', 'mouse_clicks', 'mouse_motion', 'scrolls')
    )
    return 'idle' if not any_input else 'active'


def _infer_typing_intensity(tier2):
    sample = tier2.get('interaction_sample', {})
    actions = sample.get('actions', {})
    typing = actions.get('typing', {})

    if typing.get('status') != 'observed':
        return 'none'

    sample_seconds = max(sample.get('sample_seconds', 3.0), 0.1)
    chars_per_sec = typing.get('character_count', 0) / sample_seconds

    if typing.get('typing_burst_detected') or chars_per_sec > 3:
        return 'high'
    if typing.get('character_count', 0) > 2:
        return 'medium'
    return 'low'


def _infer_cognitive_load(tier2, speaking, listening):
    """
    Weighted signal count:
      typing           = 1.0
      typing burst     = +0.5 bonus
      clicks           = 0.5
      speaking         = 1.0
      listening/audio  = 0.5 (passive)
    """
    sample = tier2.get('interaction_sample', {})
    actions = sample.get('actions', {})
    typing = actions.get('typing', {})

    signals = 0.0
    if typing.get('status') == 'observed':
        signals += 1.0
        if typing.get('typing_burst_detected'):
            signals += 0.5
    if actions.get('mouse_clicks', {}).get('status') == 'observed':
        signals += 0.5
    if speaking:
        signals += 1.0
    if listening:
        signals += 0.5

    if signals >= 2.0:
        return 'high'
    if signals >= 1.0:
        return 'medium'
    return 'low'


def _infer_confidence(tier2, tier3):
    """
    Score 0.0–1.0 reflecting how many distinct signal types were captured.
    5 possible signals: typing, clicks, mic audio, system audio source, event timeline.
    """
    sample = tier2.get('interaction_sample', {})
    actions = sample.get('actions', {})

    signals = 0
    if actions.get('typing', {}).get('status') == 'observed':
        signals += 1
    if actions.get('mouse_clicks', {}).get('count', 0) > 0:
        signals += 1
    if tier3.get('microphone_transcription', {}).get('audio_detected'):
        signals += 1
    if tier3.get('system_output_audio_transcription', {}).get('source_app'):
        signals += 1
    if sample.get('event_timeline'):
        signals += 1  # richer per-event data = more confidence

    return round(min(signals / 5, 1.0), 2)


def _infer_audio_ambient(sys_out):
    """
    silence          — no audio detected
    music_active     — music app with measurable volume
    music_present    — music app listed but volume low or unknown
    audio_present    — non-music system audio detected
    """
    if not sys_out.get('listening_detected') and not sys_out.get('audio_detected'):
        return 'silence'

    source = (sys_out.get('source_app') or '').lower()
    mean_db = sys_out.get('mean_volume_db')

    if any(frag in source for frag in MUSIC_APP_NAME_FRAGMENTS):
        if mean_db is not None and mean_db > -50:
            return 'music_active'
        return 'music_present'

    if sys_out.get('listening_detected') or sys_out.get('audio_detected'):
        return 'audio_present'

    return 'silence'


# ── agent mode + directives ───────────────────────────────────────────────────

_DIRECTIVES = {
    'non_interruptive_assist': [
        'avoid_interruptions',
        'monitor_mic_transcript',
        'capture_action_items',
        'mute_notifications',
    ],
    'focused_assist': [
        'avoid_interruptions',
        'prepare_contextual_suggestions',
        'track_navigation_patterns',
    ],
    'active_assist': [
        'proactive_suggestions',
        'summarize_recent_activity',
    ],
    'standby': [
        'await_return',
        'save_context_snapshot',
    ],
}

_OPPORTUNITY = {
    'non_interruptive_assist': {'type': 'latent_assist', 'trigger': 'pause_or_idle'},
    'focused_assist':          {'type': 'latent_assist', 'trigger': 'pause_or_idle'},
    'active_assist':           {'type': 'immediate_assist', 'trigger': 'user_idle'},
    'standby':                 {'type': 'scheduled_check', 'trigger': 'user_return'},
}


def _infer_agent_mode(activity, cognitive_load, presence, speaking):
    # No user presence at all
    if presence == 'idle' and not speaking:
        return 'active_assist'

    # Active meeting or heavy multi-modal load outside coding
    if activity == 'meeting':
        return 'non_interruptive_assist'
    if speaking and cognitive_load == 'high' and activity not in ('coding', 'document'):
        return 'non_interruptive_assist'

    # Deep focused work
    if cognitive_load in ('medium', 'high') and activity in ('coding', 'document', 'chat', 'active'):
        return 'focused_assist'

    # Light or no load — good time to assist
    return 'active_assist'


# ── main builder ─────────────────────────────────────────────────────────────


def build_context(tier1, tier2, tier3):
    """Return the semantic context object consumed by downstream agents."""
    focused_app_obj = _get_focused_app(tier1)
    focused_app = focused_app_obj['name'] if focused_app_obj else 'Unknown'
    focused_window = (
        focused_app_obj.get('focus', {}).get('primary_window_title', '')
        if focused_app_obj else ''
    )

    mic = tier3.get('microphone_transcription', {})
    sys_out = tier3.get('system_output_audio_transcription', {})

    speaking = bool(mic.get('talking_detected'))
    listening = bool(sys_out.get('listening_detected'))

    # ── activity & user state ─────────────────────────────────────────────────
    activity = _infer_activity(tier1, tier2, tier3)
    typing_intensity = _infer_typing_intensity(tier2)
    cognitive_load = _infer_cognitive_load(tier2, speaking, listening)
    confidence = _infer_confidence(tier2, tier3)

    sample = tier2.get('interaction_sample', {})
    actions = sample.get('actions', {})
    any_input = any(
        actions.get(k, {}).get('status') == 'observed'
        for k in ('typing', 'mouse_clicks', 'mouse_motion', 'scrolls')
    )
    presence = 'active' if any_input else 'idle'

    user_state = {
        'presence': presence,
        'speaking': speaking,
        'listening': listening,
        'typing_intensity': typing_intensity,
        'cognitive_load': cognitive_load,
        'confidence': confidence,
    }

    # ── audio state ───────────────────────────────────────────────────────────
    audio_state = {
        'microphone_active': bool(mic.get('audio_detected')),
        'speech_detected': speaking,
        'system_audio_active': bool(sys_out.get('audio_detected')),
        'ambient': _infer_audio_ambient(sys_out),
    }
    if sys_out.get('source_app'):
        audio_state['system_audio_source'] = sys_out['source_app']
    if sys_out.get('sound_text'):
        audio_state['system_audio_content'] = sys_out['sound_text']
    # Transcripts only when non-empty
    mic_transcript = (mic.get('transcript') or '').strip()
    sys_transcript = (sys_out.get('transcript') or '').strip()
    if mic_transcript:
        audio_state['mic_transcript'] = mic_transcript
    if sys_transcript:
        audio_state['system_transcript'] = sys_transcript

    # ── environment: apps open ────────────────────────────────────────────────
    apps_open = [
        {'name': app['name'], 'state': app.get('activity', {}).get('state', 'unknown')}
        for app in tier1.get('action_map', {}).get('applications', [])
        if app.get('activity', {}).get('state') in ('focused', 'running')
    ]

    # ── agent ─────────────────────────────────────────────────────────────────
    mode = _infer_agent_mode(activity, cognitive_load, presence, speaking)
    directives = list(_DIRECTIVES.get(mode, []))
    if mode == 'focused_assist' and activity == 'coding':
        directives.append('watch_for_errors')

    return {
        'session': {
            'activity': activity,
            'focus_app': focused_app,
            'focus_window': focused_window,
            'apps_open': apps_open,
        },
        'user_state': user_state,
        'audio_state': audio_state,
        'agent': {
            'mode': mode,
            'directives': directives,
            'opportunity': _OPPORTUNITY.get(mode, _OPPORTUNITY['standby']),
        },
    }
