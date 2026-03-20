from .utils import utc_timestamp


def build_event_stream(tier1, tier2, tier3):
    events = []
    timestamp = utc_timestamp()

    events.append({
        'timestamp': timestamp,
        'tier': 1,
        'type': 'focus.snapshot',
        'data': tier1['frontmost_app'],
    })
    events.append({
        'timestamp': timestamp,
        'tier': 1,
        'type': 'idle.snapshot',
        'data': tier1['idle_state'],
    })
    events.append({
        'timestamp': timestamp,
        'tier': 1,
        'type': 'audio_device.snapshot',
        'data': tier1['audio_device_state'],
    })
    events.append({
        'timestamp': timestamp,
        'tier': 1,
        'type': 'media_hint.snapshot',
        'data': {
            'count': len(tier1['media_active_hints']),
            'hints': tier1['media_active_hints'],
        },
    })
    events.append({
        'timestamp': timestamp,
        'tier': 1,
        'type': 'app_action_map.snapshot',
        'data': {
            'count': tier1['action_map']['total_process_groups'],
            'top_applications': tier1['action_map']['applications'][:10],
        },
    })
    events.append({
        'timestamp': timestamp,
        'tier': 2,
        'type': 'tier2.capabilities',
        'data': tier2['capabilities'],
    })
    events.append({
        'timestamp': timestamp,
        'tier': 2,
        'type': 'accessibility.focused_element',
        'data': tier2['focused_accessibility_element'],
    })
    events.append({
        'timestamp': timestamp,
        'tier': 3,
        'type': 'tier3.capabilities',
        'data': tier3['capabilities'],
    })
    events.append({
        'timestamp': timestamp,
        'tier': 3,
        'type': 'ocr.active_window',
        'data': tier3['active_window_ocr'],
    })
    events.append({
        'timestamp': timestamp,
        'tier': 3,
        'type': 'transcription.microphone',
        'data': tier3['microphone_transcription'],
    })
    events.append({
        'timestamp': timestamp,
        'tier': 3,
        'type': 'transcription.system_output',
        'data': tier3['system_output_audio_transcription'],
    })

    return events


def build_output(tier1, tier2, tier3):
    event_stream = build_event_stream(tier1, tier2, tier3)
    return {
        'timestamp': utc_timestamp(),
        'tiers': {
            'tier1': tier1,
            'tier2': tier2,
            'tier3': tier3,
        },
        'event_stream': event_stream,
    }
