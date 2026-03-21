from .context import build_context
from .utils import utc_timestamp


def _get_frontmost_app(tier1, tier3):
    """Return (app_name, window_title) for the current frontmost app."""
    for app in tier1.get('action_map', {}).get('applications', []):
        if app.get('focus', {}).get('is_frontmost'):
            return app['name'], app['focus'].get('primary_window_title', '')
    aw = tier3.get('active_window', {})
    return aw.get('app_name', 'Unknown'), aw.get('window_title', '')


def build_action_sequence(tier1, tier2, tier3):
    timestamp = utc_timestamp()
    sequence = []
    frontmost_app, frontmost_window = _get_frontmost_app(tier1, tier3)

    # focused
    focused = {'timestamp': timestamp, 'app': frontmost_app, 'event': 'focused'}
    if frontmost_window:
        focused['window_title'] = frontmost_window
    sequence.append(focused)

    # input events from tier2
    sample = tier2.get('interaction_sample', {})
    actions = sample.get('actions', {})
    has_input = False
    timeline = sample.get('event_timeline', [])

    if timeline:
        for item in timeline:
            event_name = item.get('event')
            if event_name not in {'typed', 'clicked', 'moved', 'scrolled'}:
                continue
            has_input = True
            event_payload = {
                'timestamp': item.get('timestamp', timestamp),
                'app': item.get('app') or frontmost_app,
                'event': event_name,
            }
            if item.get('window_title'):
                event_payload['window_title'] = item['window_title']
            if event_name == 'typed' and item.get('token'):
                event_payload['token'] = item['token']
            if event_name == 'clicked' and item.get('button'):
                event_payload['button'] = item['button']
            if event_name == 'scrolled' and item.get('direction'):
                event_payload['direction'] = item['direction']
            sequence.append(event_payload)

    # clicks
    clicks = actions.get('mouse_clicks', {})
    click_count = clicks.get('count', 0)
    if click_count > 0 and not timeline:
        has_input = True
        targets = clicks.get('targets', [])
        for target in targets:
            click_event = {
                'timestamp': timestamp,
                'app': target.get('app_name') or frontmost_app,
                'event': 'clicked',
                'label': target.get('label', ''),
                'button': target.get('button_label', 'left'),
            }
            if target.get('window_title'):
                click_event['window_title'] = target['window_title']
            sequence.append(click_event)
        if click_count > len(targets):
            sequence.append({
                'timestamp': timestamp,
                'app': frontmost_app,
                'event': 'clicked',
                'note': f'{click_count - len(targets)} additional click(s) not captured',
            })

    # typing
    typing = actions.get('typing', {})
    if typing.get('count', 0) > 0 and not timeline:
        has_input = True
        typed_event = {
            'timestamp': timestamp,
            'app': frontmost_app,
            'event': 'typed',
            'character_count': typing.get('character_count', 0),
        }
        words = typing.get('words_typed', [])
        if words:
            typed_event['words'] = words[:10]
        sequence.append(typed_event)

    # scrolls
    scrolls = actions.get('scrolls', {})
    if scrolls.get('status') == 'observed' and not timeline:
        has_input = True
        sequence.append({
            'timestamp': timestamp,
            'app': frontmost_app,
            'event': 'scrolled',
            'direction': scrolls.get('direction', 'unknown'),
        })

    # idle if no input during sample window
    if not has_input:
        sequence.append({'timestamp': timestamp, 'app': frontmost_app, 'event': 'idle'})

    # passive events — happen without user input
    mic = tier3.get('microphone_transcription', {})
    if mic.get('talking_detected'):
        sequence.append({
            'timestamp': mic.get('captured_at', timestamp),
            'app': frontmost_app,
            'event': 'talking',
        })

    sys_out = tier3.get('system_output_audio_transcription', {})
    if sys_out.get('listening_detected'):
        audio_event = {
            'timestamp': sys_out.get('captured_at', timestamp),
            'app': sys_out.get('source_app') or frontmost_app,
            'event': 'audio_playing',
            'sound_text': sys_out.get('sound_text', ''),
            'playback_state': sys_out.get('playback_state', 'unknown'),
        }
        sequence.append(audio_event)

    return sequence


def build_output(tier1, tier2, tier3):
    return {
        'timestamp': utc_timestamp(),
        'context': build_context(tier1, tier2, tier3),
        'action_sequence': build_action_sequence(tier1, tier2, tier3),
        'tiers': {
            'tier1': tier1,
            'tier2': tier2,
            'tier3': tier3,
        },
    }
