import re
import time

from .utils import run_osascript, utc_timestamp


SAMPLE_SECONDS = 3.0
MAX_CLICK_TARGETS = 5
MAX_TIMELINE_EVENTS = 300
MOTION_EVENT_MIN_INTERVAL_SECONDS = 0.2
APP_CONTEXT_CACHE_SECONDS = 0.35
APP_NAME_OVERRIDES = {
    'com.microsoft.VSCode': 'Visual Studio Code',
}
KEYCODE_CHAR_MAP = {
    0: 'a', 1: 's', 2: 'd', 3: 'f', 4: 'h', 5: 'g', 6: 'z', 7: 'x', 8: 'c', 9: 'v',
    11: 'b', 12: 'q', 13: 'w', 14: 'e', 15: 'r', 16: 'y', 17: 't', 18: '1', 19: '2',
    20: '3', 21: '4', 22: '6', 23: '5', 24: '=', 25: '9', 26: '7', 27: '-', 28: '8',
    29: '0', 30: ']', 31: 'o', 32: 'u', 33: '[', 34: 'i', 35: 'p', 37: 'l', 38: 'j',
    39: "'", 40: 'k', 41: ';', 42: '\\', 43: ',', 44: '/', 45: 'n', 46: 'm', 47: '.',
    49: ' ', 50: '`',
}
KEYCODE_TOKEN_MAP = {
    36: '[enter]',
    48: '[tab]',
    51: '[backspace]',
    53: '[escape]',
}


def get_quartz_bindings():
    try:
        from Quartz import (  # pylint: disable=import-outside-toplevel
            CGEventTapEnable,
            CFMachPortCreateRunLoopSource,
            CFMachPortInvalidate,
            CFRunLoopAddSource,
            CFRunLoopGetCurrent,
            CFRunLoopRunInMode,
            CGEventGetIntegerValueField,
            CGEventMaskBit,
            CGEventTapCreate,
            kCFRunLoopCommonModes,
            kCFRunLoopDefaultMode,
            kCGEventKeyDown,
            kCGEventLeftMouseDown,
            kCGEventLeftMouseDragged,
            kCGEventMouseMoved,
            kCGEventOtherMouseDown,
            kCGEventOtherMouseDragged,
            kCGEventRightMouseDown,
            kCGEventRightMouseDragged,
            kCGEventScrollWheel,
            kCGEventTapDisabledByTimeout,
            kCGEventTapDisabledByUserInput,
            kCGEventTapOptionListenOnly,
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGKeyboardEventKeycode,
            kCGMouseEventButtonNumber,
            kCGScrollWheelEventDeltaAxis1,
        )
        return {
            'ok': True,
            'bindings': {
                'CFMachPortCreateRunLoopSource': CFMachPortCreateRunLoopSource,
                'CFMachPortInvalidate': CFMachPortInvalidate,
                'CFRunLoopAddSource': CFRunLoopAddSource,
                'CFRunLoopGetCurrent': CFRunLoopGetCurrent,
                'CFRunLoopRunInMode': CFRunLoopRunInMode,
                'CGEventTapEnable': CGEventTapEnable,
                'CGEventGetIntegerValueField': CGEventGetIntegerValueField,
                'CGEventMaskBit': CGEventMaskBit,
                'CGEventTapCreate': CGEventTapCreate,
                'kCFRunLoopCommonModes': kCFRunLoopCommonModes,
                'kCFRunLoopDefaultMode': kCFRunLoopDefaultMode,
                'kCGEventKeyDown': kCGEventKeyDown,
                'kCGEventLeftMouseDown': kCGEventLeftMouseDown,
                'kCGEventLeftMouseDragged': kCGEventLeftMouseDragged,
                'kCGEventMouseMoved': kCGEventMouseMoved,
                'kCGEventOtherMouseDown': kCGEventOtherMouseDown,
                'kCGEventOtherMouseDragged': kCGEventOtherMouseDragged,
                'kCGEventRightMouseDown': kCGEventRightMouseDown,
                'kCGEventRightMouseDragged': kCGEventRightMouseDragged,
                'kCGEventScrollWheel': kCGEventScrollWheel,
                'kCGEventTapDisabledByTimeout': kCGEventTapDisabledByTimeout,
                'kCGEventTapDisabledByUserInput': kCGEventTapDisabledByUserInput,
                'kCGEventTapOptionListenOnly': kCGEventTapOptionListenOnly,
                'kCGSessionEventTap': kCGSessionEventTap,
                'kCGHeadInsertEventTap': kCGHeadInsertEventTap,
                'kCGKeyboardEventKeycode': kCGKeyboardEventKeycode,
                'kCGMouseEventButtonNumber': kCGMouseEventButtonNumber,
                'kCGScrollWheelEventDeltaAxis1': kCGScrollWheelEventDeltaAxis1,
            },
        }
    except Exception as error:  # pragma: no cover - depends on local OS packages
        return {
            'ok': False,
            'error': str(error),
        }


def get_focused_accessibility_element():
    script = r'''
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            try
                set focusedElement to value of attribute "AXFocusedUIElement" of frontApp
                set elementRole to value of attribute "AXRole" of focusedElement
                set elementSubrole to ""
                set elementTitle to ""
                set elementValue to ""
                try
                    set elementSubrole to value of attribute "AXSubrole" of focusedElement
                end try
                try
                    set elementTitle to value of attribute "AXTitle" of focusedElement
                end try
                try
                    set elementValue to value of attribute "AXValue" of focusedElement
                end try
                return elementRole & linefeed & elementSubrole & linefeed & elementTitle & linefeed & elementValue
            on error errMsg
                return "ERROR" & linefeed & errMsg
            end try
        end tell
    '''
    result = run_osascript(script)
    if not result['ok']:
        return {
            'status': 'unavailable',
            'reason': result['stderr'],
        }

    lines = result['stdout'].splitlines()
    if lines and lines[0] == 'ERROR':
        return {
            'status': 'permission_or_app_limited',
            'reason': lines[1] if len(lines) > 1 else 'Accessibility query failed.',
        }

    return {
        'status': 'ok',
        'role': lines[0].strip() if len(lines) > 0 else '',
        'subrole': lines[1].strip() if len(lines) > 1 else '',
        'title': lines[2].strip() if len(lines) > 2 else '',
        'value': lines[3].strip() if len(lines) > 3 else '',
    }


def get_frontmost_app_context():
    script = r'''
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set appName to name of frontApp
            set bundleId to ""
            set windowTitle to ""
            try
                set bundleId to bundle identifier of frontApp
            end try
            try
                set appWindow to first window of frontApp
                set windowTitle to name of appWindow
            end try
            return appName & linefeed & bundleId & linefeed & windowTitle
        end tell
    '''
    result = run_osascript(script)
    if not result['ok']:
        return {
            'status': 'unavailable',
            'reason': result['stderr'],
        }

    lines = result['stdout'].splitlines()
    return {
        'status': 'ok',
        'app_name': lines[0].strip() if len(lines) > 0 else '',
        'bundle_id': lines[1].strip() if len(lines) > 1 else '',
        'window_title': lines[2].strip() if len(lines) > 2 else '',
    }


def normalize_app_name(app_name, bundle_id):
    if bundle_id in APP_NAME_OVERRIDES:
        return APP_NAME_OVERRIDES[bundle_id]
    if app_name == 'Code' and bundle_id == 'com.microsoft.VSCode':
        return 'Visual Studio Code'
    return app_name or 'Unknown app'


def format_accessibility_reason(reason):
    if not reason:
        return 'Focused element was not exposed by macOS accessibility APIs.'
    lowered = reason.lower()
    if 'axrole' in lowered and 'missing value' in lowered:
        return 'Focused element was not exposed by macOS accessibility APIs.'
    return reason


def format_button_label(button_number):
    if button_number == 0:
        return 'left'
    if button_number == 1:
        return 'right'
    if button_number == 2:
        return 'middle'
    if button_number is None:
        return 'unknown'
    return f'button_{button_number}'


def build_context_label(app_name, window_title, button_label):
    if window_title:
        return f'{button_label.capitalize()} click in {app_name} ({window_title})'
    return f'{button_label.capitalize()} click in {app_name}'


def format_click_target(element, app_context, button_number):
    app_name = normalize_app_name(app_context.get('app_name', ''), app_context.get('bundle_id', ''))
    button_label = format_button_label(button_number)

    if element.get('status') != 'ok':
        target = {
            'label': build_context_label(app_name, app_context.get('window_title', ''), button_label),
            'reason': format_accessibility_reason(element.get('reason', 'Accessibility query failed.')),
            'capture_method': 'context_fallback',
        }
    else:
        parts = [part for part in [element.get('role'), element.get('subrole'), element.get('title')] if part]
        value = element.get('value')
        if value and value not in parts:
            parts.append(value)
        target = {
            'label': ' | '.join(parts) if parts else build_context_label(app_name, app_context.get('window_title', ''), button_label),
            'capture_method': 'accessibility',
        }

    if app_context.get('status') == 'ok':
        target['app_name'] = app_name
        if app_context.get('bundle_id'):
            target['bundle_id'] = app_context['bundle_id']
        if app_context.get('window_title'):
            target['window_title'] = app_context['window_title']
    elif app_context.get('reason'):
        target['app_context_reason'] = app_context['reason']

    target['button_label'] = button_label

    return target


def keycode_to_text(keycode):
    if keycode in KEYCODE_CHAR_MAP:
        return KEYCODE_CHAR_MAP[keycode]
    if keycode in KEYCODE_TOKEN_MAP:
        return KEYCODE_TOKEN_MAP[keycode]
    return f'[keycode:{keycode}]'


def summarize_typed_text(typed_tokens):
    raw_text = ''.join(typed_tokens)
    resolved_chars = []

    for token in typed_tokens:
        if token == '[backspace]':
            if resolved_chars:
                resolved_chars.pop()
            continue
        if token == '[enter]':
            resolved_chars.append('\n')
            continue
        if token == '[tab]':
            resolved_chars.append('\t')
            continue
        if token == '[escape]':
            continue
        if token.startswith('[keycode:'):
            continue
        resolved_chars.append(token)

    resolved_text = ''.join(resolved_chars).strip()
    normalized_for_words = resolved_text.replace('\n', ' ').replace('\t', ' ')
    words = [word for word in normalized_for_words.split() if word]
    sentence_parts = [segment.strip() for segment in re.split(r'[\n]+|(?<=[.!?])\s+', resolved_text) if segment.strip()]

    return {
        'raw_characters': raw_text,
        'resolved_characters': resolved_text,
        'character_count': len(resolved_text),
        'words': words,
        'sentences': sentence_parts,
    }


def build_action_status(count, sample_seconds, extra=None, include_count=True):
    payload = {
        'status': 'observed' if count > 0 else 'not_observed',
        'sample_seconds': sample_seconds,
    }
    if include_count:
        payload['count'] = count
    if extra:
        payload.update(extra)
    return payload


def build_requires_setup_sample(reason, sample_seconds):
    return {
        'status': 'requires_setup',
        'sample_seconds': round(sample_seconds, 2),
        'reason': reason,
        'permissions': get_permission_state(),
        'actions': {
            'typing': {
                'status': 'requires_setup',
                'count': 0,
                'sample_seconds': round(sample_seconds, 2),
                'typing_burst_detected': False,
                'character_count': 0,
                'characters_typed_raw': '',
                'characters_typed': '',
                'words_typed': [],
                'sentences_typed': [],
            },
            'mouse_clicks': {'status': 'requires_setup', 'count': 0, 'sample_seconds': round(sample_seconds, 2)},
            'mouse_motion': {'status': 'requires_setup', 'sample_seconds': round(sample_seconds, 2)},
            'scrolls': {'status': 'requires_setup', 'sample_seconds': round(sample_seconds, 2), 'direction': 'none'},
        },
    }


def get_permission_state():
    permission_state = {
        'input_monitoring': 'unknown',
    }

    try:
        from Quartz import CGPreflightListenEventAccess  # pylint: disable=import-outside-toplevel

        permission_state['input_monitoring'] = 'granted' if CGPreflightListenEventAccess() else 'not_granted'
    except Exception:
        permission_state['input_monitoring'] = 'unknown'

    return permission_state


def create_event_mask(q):
    return (
        q['CGEventMaskBit'](q['kCGEventKeyDown'])
        | q['CGEventMaskBit'](q['kCGEventLeftMouseDown'])
        | q['CGEventMaskBit'](q['kCGEventMouseMoved'])
        | q['CGEventMaskBit'](q['kCGEventLeftMouseDragged'])
        | q['CGEventMaskBit'](q['kCGEventRightMouseDown'])
        | q['CGEventMaskBit'](q['kCGEventRightMouseDragged'])
        | q['CGEventMaskBit'](q['kCGEventOtherMouseDown'])
        | q['CGEventMaskBit'](q['kCGEventOtherMouseDragged'])
        | q['CGEventMaskBit'](q['kCGEventScrollWheel'])
    )


def create_interaction_state():
    return {
        'event_counts': {
            'key_down': 0,
            'mouse_click': 0,
            'mouse_move': 0,
            'scroll': 0,
        },
        'typed_tokens': [],
        'click_targets': [],
        'scroll_deltas': [],
        'event_timeline': [],
        'last_motion_event_time': 0.0,
        'cached_app_context': None,
        'cached_app_context_time': 0.0,
    }


def get_cached_app_context(state, force_refresh=False):
    now = time.time()
    if not force_refresh:
        cached = state.get('cached_app_context')
        cached_time = state.get('cached_app_context_time', 0.0)
        if cached and (now - cached_time) <= APP_CONTEXT_CACHE_SECONDS:
            return cached

    app_context = get_frontmost_app_context()
    state['cached_app_context'] = app_context
    state['cached_app_context_time'] = now
    return app_context


def append_timeline_event(state, event_name, app_context=None, extra=None):
    if len(state['event_timeline']) >= MAX_TIMELINE_EVENTS:
        return

    event_payload = {
        'timestamp': utc_timestamp(),
        'event': event_name,
    }
    if app_context and app_context.get('status') == 'ok':
        event_payload['app'] = normalize_app_name(app_context.get('app_name', ''), app_context.get('bundle_id', ''))
        if app_context.get('window_title'):
            event_payload['window_title'] = app_context['window_title']
    if extra:
        event_payload.update(extra)
    state['event_timeline'].append(event_payload)


def record_key_event(q, event, state):
    state['event_counts']['key_down'] += 1
    app_context = get_cached_app_context(state)
    try:
        keycode = int(q['CGEventGetIntegerValueField'](event, q['kCGKeyboardEventKeycode']))
        typed_token = keycode_to_text(keycode)
        state['typed_tokens'].append(typed_token)
        append_timeline_event(state, 'typed', app_context, {'token': typed_token})
    except Exception:
        pass


def record_click_event(q, event, state):
    state['event_counts']['mouse_click'] += 1

    try:
        button_number = int(q['CGEventGetIntegerValueField'](event, q['kCGMouseEventButtonNumber']))
    except Exception:
        button_number = None

    app_context = get_cached_app_context(state, force_refresh=True)

    append_timeline_event(state, 'clicked', app_context, {'button': format_button_label(button_number)})

    if len(state['click_targets']) >= MAX_CLICK_TARGETS:
        return

    focused_element = get_focused_accessibility_element()
    target = format_click_target(focused_element, app_context, button_number)
    target['button'] = button_number
    state['click_targets'].append(target)


def record_motion_event(state):
    state['event_counts']['mouse_move'] += 1
    now = time.time()
    if (now - state['last_motion_event_time']) < MOTION_EVENT_MIN_INTERVAL_SECONDS:
        return
    state['last_motion_event_time'] = now
    append_timeline_event(state, 'moved', get_cached_app_context(state))


def record_scroll_event(q, event, state):
    try:
        delta = int(q['CGEventGetIntegerValueField'](event, q['kCGScrollWheelEventDeltaAxis1']))
        if delta == 0:
            return
        state['event_counts']['scroll'] += 1
        state['scroll_deltas'].append(delta)
        direction = 'down' if delta < 0 else 'up'
        append_timeline_event(state, 'scrolled', get_cached_app_context(state), {'direction': direction})
    except Exception:
        pass


def is_click_event(q, event_type):
    return event_type in {
        q['kCGEventLeftMouseDown'],
        q['kCGEventRightMouseDown'],
        q['kCGEventOtherMouseDown'],
    }


def is_motion_event(q, event_type):
    return event_type in {
        q['kCGEventMouseMoved'],
        q['kCGEventLeftMouseDragged'],
        q['kCGEventRightMouseDragged'],
        q['kCGEventOtherMouseDragged'],
    }


def run_sampling_loop(q, event_tap, sample_seconds):
    run_loop_source = q['CFMachPortCreateRunLoopSource'](None, event_tap, 0)
    q['CFRunLoopAddSource'](
        q['CFRunLoopGetCurrent'](),
        run_loop_source,
        q['kCFRunLoopCommonModes'],
    )

    start_time = time.time()
    while (time.time() - start_time) < sample_seconds:
        q['CFRunLoopRunInMode'](q['kCFRunLoopDefaultMode'], 0.05, False)


def build_scroll_direction(scroll_deltas):
    direction = 'none'
    if any(delta > 0 for delta in scroll_deltas):
        direction = 'up'
    if any(delta < 0 for delta in scroll_deltas):
        direction = 'down' if direction == 'none' else 'mixed'
    return direction


def build_interaction_sample(state, sample_seconds, sample_started_at, sample_ended_at):
    rounded_seconds = round(sample_seconds, 2)
    event_counts = state['event_counts']
    typed_summary = summarize_typed_text(state['typed_tokens'])
    return {
        'status': 'ok',
        'sample_started_at': sample_started_at,
        'sample_ended_at': sample_ended_at,
        'sample_seconds': rounded_seconds,
        'event_timeline': state['event_timeline'],
        'permissions': get_permission_state(),
        'actions': {
            'typing': build_action_status(
                event_counts['key_down'],
                rounded_seconds,
                {
                    'typing_burst_detected': event_counts['key_down'] >= 3,
                    'character_count': typed_summary['character_count'],
                    'characters_typed_raw': typed_summary['raw_characters'],
                    'characters_typed': typed_summary['resolved_characters'],
                    'words_typed': typed_summary['words'],
                    'sentences_typed': typed_summary['sentences'],
                },
            ),
            'mouse_clicks': build_action_status(
                event_counts['mouse_click'],
                rounded_seconds,
                {'targets': state['click_targets']},
            ),
            'mouse_motion': build_action_status(
                event_counts['mouse_move'],
                rounded_seconds,
                include_count=True,
            ),
            'scrolls': build_action_status(
                event_counts['scroll'],
                rounded_seconds,
                {
                    'direction': build_scroll_direction(state['scroll_deltas']),
                },
                include_count=True,
            ),
        },
    }


def sample_interaction_events(sample_seconds=SAMPLE_SECONDS):
    sample_started_at = utc_timestamp()
    quartz = get_quartz_bindings()
    if not quartz['ok']:
        sample = build_requires_setup_sample(f"PyObjC/Quartz unavailable: {quartz['error']}", sample_seconds)
        sample['sample_started_at'] = sample_started_at
        sample['sample_ended_at'] = utc_timestamp()
        sample['event_timeline'] = []
        return sample

    q = quartz['bindings']
    event_mask = create_event_mask(q)
    state = create_interaction_state()

    def callback(_proxy, event_type, event, _refcon):
        if event_type in {q['kCGEventTapDisabledByTimeout'], q['kCGEventTapDisabledByUserInput']}:
            q['CGEventTapEnable'](event_tap, True)
            return event

        if event_type == q['kCGEventKeyDown']:
            record_key_event(q, event, state)
        elif is_click_event(q, event_type):
            record_click_event(q, event, state)
        elif is_motion_event(q, event_type):
            record_motion_event(state)
        elif event_type == q['kCGEventScrollWheel']:
            record_scroll_event(q, event, state)
        return event

    event_tap = q['CGEventTapCreate'](
        q['kCGSessionEventTap'],
        q['kCGHeadInsertEventTap'],
        q['kCGEventTapOptionListenOnly'],
        event_mask,
        callback,
        None,
    )
    if not event_tap:
        sample = build_requires_setup_sample(
            'Unable to create event tap. Grant Input Monitoring and Accessibility to your terminal app.',
            sample_seconds,
        )
        sample['sample_started_at'] = sample_started_at
        sample['sample_ended_at'] = utc_timestamp()
        sample['event_timeline'] = []
        return sample

    run_sampling_loop(q, event_tap, sample_seconds)

    q['CFMachPortInvalidate'](event_tap)
    return build_interaction_sample(state, sample_seconds, sample_started_at, utc_timestamp())


def collect_tier2_snapshot():
    return {
        'interaction_sample': sample_interaction_events(),
    }
