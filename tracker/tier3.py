import importlib.util
from importlib import metadata as importlib_metadata
import os
import re
import shutil
import tempfile

from .utils import run_command, run_json_command, run_osascript, utc_timestamp


TRANSCRIPTION_LOOPBACK_HINTS = (
    'blackhole',
    'loopback',
    'soundflower',
    'zoomaudio',
    'teams audio',
)

ACTIVE_WINDOW_KEYWORDS = {
    'coding': ('def ', 'class ', 'import ', 'function', 'json', 'python', 'vscode', 'terminal', 'git'),
    'chat': ('chat', 'message', 'prompt', 'assistant', 'copilot'),
    'browser': ('chrome', 'safari', 'http', 'www.', 'tab', 'search'),
    'document': ('slides', 'doc', 'notion', 'word', 'presentation', 'notes'),
}

LIKELY_AUDIO_APP_KEYWORDS = (
    'spotify',
    'music',
    'chrome',
    'safari',
    'youtube',
    'vlc',
    'quicktime',
    'teams',
    'zoom',
    'discord',
    'podcast',
)


def command_available(command_name):
    return shutil.which(command_name) is not None


def python_module_available(module_name):
    return importlib.util.find_spec(module_name) is not None


def command_info(command_name, version_args=None):
    path = shutil.which(command_name)
    info = {
        'detected': path is not None,
        'path': path,
    }
    if not path:
        return info

    args = version_args or ['-version'] if command_name == 'ffmpeg' else ['--version']
    version_result = run_command([command_name, *args], timeout=5)
    if not version_result['ok']:
        info['version'] = 'unknown'
        return info

    version_blob = (version_result.get('stdout') or version_result.get('stderr') or '').strip()
    info['version'] = version_blob.splitlines()[0] if version_blob else 'unknown'
    return info


def python_module_info(module_name, distribution_name=None):
    detected = python_module_available(module_name)
    info = {
        'detected': detected,
        'module': module_name,
        'distribution': distribution_name or module_name,
    }
    if not detected:
        return info

    try:
        info['version'] = importlib_metadata.version(distribution_name or module_name)
    except importlib_metadata.PackageNotFoundError:
        info['version'] = 'unknown'
    return info


def detect_transcription_backend():
    backends = []
    if command_available('whisper'):
        backends.append('whisper_cli')
    if python_module_available('whisper'):
        backends.append('python_whisper')
    if python_module_available('faster_whisper'):
        backends.append('faster_whisper')
    return backends


def get_audio_device_probe():
    result = run_json_command(['system_profiler', 'SPAudioDataType', '-json'])
    if not result['ok']:
        return {
            'status': 'unavailable',
            'reason': result['error'],
        }

    device_groups = result['data'].get('SPAudioDataType', [])
    devices = []
    for group in device_groups:
        devices.extend(group.get('_items', []))

    default_input = None
    default_output = None
    for device in devices:
        name = device.get('_name', 'Unknown')
        if device.get('coreaudio_default_audio_input_device') == 'spaudio_yes':
            default_input = name
        if device.get('coreaudio_default_audio_output_device') == 'spaudio_yes':
            default_output = name

    return {
        'status': 'ok',
        'device_count': len(devices),
        'default_input': default_input,
        'default_output': default_output,
    }


def list_avfoundation_audio_devices():
    if not command_available('ffmpeg'):
        return {
            'status': 'unavailable',
            'reason': 'ffmpeg not found',
            'devices': [],
        }

    result = run_command(
        ['ffmpeg', '-hide_banner', '-f', 'avfoundation', '-list_devices', 'true', '-i', ''],
        timeout=8,
    )
    output = ((result.get('stdout') or '') + '\n' + (result.get('stderr') or '')).splitlines()

    devices = []
    in_audio_section = False
    for line in output:
        if 'AVFoundation video devices' in line:
            in_audio_section = False
            continue
        if 'AVFoundation audio devices' in line:
            in_audio_section = True
            continue
        if not in_audio_section:
            continue

        match = re.search(r'\[(\d+)\]\s+(.+)$', line)
        if match:
            devices.append({
                'index': int(match.group(1)),
                'name': match.group(2).strip(),
            })

    return {
        'status': 'ok' if devices else 'unavailable',
        'reason': None if devices else 'No avfoundation audio devices detected by ffmpeg.',
        'devices': devices,
    }


def find_audio_device_index(devices, preferred_name):
    if not devices:
        return None
    if preferred_name:
        for device in devices:
            if device['name'].strip().lower() == preferred_name.strip().lower():
                return device['index']
        for device in devices:
            if preferred_name.strip().lower() in device['name'].strip().lower():
                return device['index']
    return devices[0]['index']


def run_audio_capture_probe(device_index, duration_seconds=1.0):
    if device_index is None:
        return {
            'status': 'skipped',
            'reason': 'No capture device index available.',
        }

    result = run_command(
        [
            'ffmpeg', '-hide_banner',
            '-f', 'avfoundation',
            '-i', f':{device_index}',
            '-t', str(duration_seconds),
            '-ac', '1',
            '-ar', '16000',
            '-af', 'volumedetect',
            '-f', 'null', '-',
        ],
        timeout=12,
    )

    stderr_text = (result.get('stderr') or '').strip()

    def parse_volume(metric_name):
        match = re.search(rf'{metric_name}:\s*(-?\d+(?:\.\d+)?)\s*dB', stderr_text)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    mean_volume_db = parse_volume('mean_volume')
    max_volume_db = parse_volume('max_volume')
    min_volume_db = parse_volume('min_volume')
    audio_detected = (
        max_volume_db is not None
        and max_volume_db > -60.0
    )

    if result['ok']:
        return {
            'status': 'ok',
            'reason': f'Audio probe succeeded using avfoundation device index {device_index}.',
            'audio_detected': audio_detected,
            'mean_volume_db': mean_volume_db,
            'max_volume_db': max_volume_db,
            'min_volume_db': min_volume_db,
        }

    return {
        'status': 'failed',
        'reason': stderr_text.splitlines()[-1] if stderr_text else 'Audio probe failed.',
        'audio_detected': False,
        'mean_volume_db': mean_volume_db,
        'max_volume_db': max_volume_db,
        'min_volume_db': min_volume_db,
    }


MEDIA_APP_STATE_SCRIPTS = [
    (
        'Spotify',
        r'''
            tell application "Spotify"
                if it is running then
                    set playerStateText to player state as string
                    set trackNameText to ""
                    set artistNameText to ""
                    try
                        set trackNameText to name of current track
                        set artistNameText to artist of current track
                    end try
                    return playerStateText & "|" & trackNameText & "|" & artistNameText
                else
                    return "not_running"
                end if
            end tell
        ''',
    ),
    (
        'Music',
        r'''
            tell application "Music"
                if it is running then
                    set playerStateText to player state as string
                    set trackNameText to ""
                    set artistNameText to ""
                    try
                        set trackNameText to name of current track
                        set artistNameText to artist of current track
                    end try
                    return playerStateText & "|" & trackNameText & "|" & artistNameText
                else
                    return "not_running"
                end if
            end tell
        ''',
    ),
]


def get_media_app_playback_states():
    states = []
    for app_name, script in MEDIA_APP_STATE_SCRIPTS:
        result = run_osascript(script, timeout=4)
        if not result['ok']:
            continue
        raw = result['stdout'].strip()
        if not raw or raw == 'not_running':
            continue
        parts = raw.split('|', 2)
        playback_state = parts[0].strip() if parts else 'unknown'
        track = parts[1].strip() if len(parts) > 1 else ''
        artist = parts[2].strip() if len(parts) > 2 else ''
        sound_text = ''
        if track and artist:
            sound_text = f'{track} - {artist}'
        elif track:
            sound_text = track
        states.append({
            'app': app_name,
            'playback_state': playback_state,
            'sound_text': sound_text,
        })
    return states


# Browser apps — return newline-separated audible tab titles (or "none" / "not_running")
BROWSER_AUDIO_APP_SCRIPTS = [
    (
        'Google Chrome',
        r'''
            tell application "Google Chrome"
                if it is running then
                    set found to {}
                    repeat with w in windows
                        repeat with t in tabs of w
                            try
                                if audible of t then
                                    set end of found to (title of t as string)
                                end if
                            end try
                        end repeat
                    end repeat
                    if (count of found) > 0 then
                        set AppleScript's text item delimiters to linefeed
                        return found as string
                    end if
                    return "none"
                else
                    return "not_running"
                end if
            end tell
        ''',
    ),
    (
        'Safari',
        r'''
            tell application "Safari"
                if it is running then
                    set found to {}
                    repeat with w in windows
                        repeat with t in tabs of w
                            try
                                if current tab of w is t then
                                    set tab_name to name of t as string
                                    -- Safari exposes no audible flag; use URL hint
                                    set tab_url to URL of t as string
                                    if tab_url contains "youtube.com" or tab_url contains "soundcloud.com" or tab_url contains "twitch.tv" then
                                        set end of found to tab_name & "|" & tab_url
                                    end if
                                end if
                            end try
                        end repeat
                    end repeat
                    if (count of found) > 0 then
                        set AppleScript's text item delimiters to linefeed
                        return found as string
                    end if
                    return "none"
                else
                    return "not_running"
                end if
            end tell
        ''',
    ),
]


def get_media_app_states():
    """Query browser audio sources and return a list of active media entries."""
    playing = []

    # Browsers: audible tab titles
    for app_name, script in BROWSER_AUDIO_APP_SCRIPTS:
        result = run_osascript(script, timeout=4)
        if not result['ok']:
            continue
        raw = result['stdout'].strip()
        if not raw or raw in {'not_running', 'none'}:
            continue
        # Each line is a tab title (or title|url for Safari URL-hint fallback)
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            entry = {'app': app_name, 'source_type': 'browser'}
            if '|' in line:
                tab_title, tab_url = line.split('|', 1)
                entry['tab_title'] = tab_title.strip()
                entry['tab_url'] = tab_url.strip()
                entry['sound_text'] = entry['tab_title']
            else:
                entry['tab_title'] = line
                entry['sound_text'] = line
            playing.append(entry)

    return playing


def clean_window_title(window_title):
    title = (window_title or '').strip()
    if not title:
        return ''
    if ' - Google Chrome' in title:
        title = title.split(' - Google Chrome')[0].strip()
    if ' — ' in title:
        title = title.split(' — ')[0].strip()
    return title


def get_frontmost_app_context():
    script = r'''
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set appName to name of frontApp
            set windowTitle to ""
            try
                set appWindow to first window of frontApp
                set windowTitle to name of appWindow
            end try
            return appName & linefeed & windowTitle
        end tell
    '''
    result = run_osascript(script, timeout=5)
    if not result['ok']:
        return {
            'status': 'unavailable',
            'reason': result['stderr'],
        }

    lines = result['stdout'].splitlines()
    return {
        'status': 'ok',
        'app_name': lines[0].strip() if len(lines) > 0 else '',
        'window_title': lines[1].strip() if len(lines) > 1 else '',
    }


def detect_virtual_audio_loopback_devices():
    result = run_json_command(['system_profiler', 'SPAudioDataType', '-json'])
    if not result['ok']:
        return {
            'status': 'unavailable',
            'reason': result['error'],
            'devices': [],
        }

    device_groups = result['data'].get('SPAudioDataType', [])
    devices = []
    for group in device_groups:
        devices.extend(group.get('_items', []))

    matches = []
    for device in devices:
        name = (device.get('_name') or '').strip()
        manufacturer = (device.get('coreaudio_device_manufacturer') or '').strip()
        normalized = f"{name} {manufacturer}".lower()
        if any(hint in normalized for hint in TRANSCRIPTION_LOOPBACK_HINTS):
            matches.append({
                'name': name,
                'manufacturer': manufacturer,
            })

    return {
        'status': 'ok',
        'devices': matches,
    }


def get_front_window_bounds():
    script = r'''
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            try
                tell front window of frontApp
                    set {xPos, yPos} to position
                    set {winWidth, winHeight} to size
                end tell
                return xPos & "," & yPos & "," & winWidth & "," & winHeight
            on error errMsg
                return "ERROR," & errMsg
            end try
        end tell
    '''
    result = run_osascript(script)
    if not result['ok']:
        return {
            'status': 'unavailable',
            'reason': result['stderr'],
        }

    output = result['stdout'].strip()
    if output.startswith('ERROR,'):
        return {
            'status': 'permission_or_app_limited',
            'reason': output.split(',', 1)[1],
        }

    parts = re.findall(r'-?\d+', output)
    if len(parts) < 4:
        return {
            'status': 'unavailable',
            'reason': 'Could not parse front window bounds.',
        }

    try:
        x_pos, y_pos, width, height = [int(part) for part in parts[:4]]
    except ValueError:
        return {
            'status': 'unavailable',
            'reason': 'Front window bounds were not numeric.',
        }

    return {
        'status': 'ok',
        'x': x_pos,
        'y': y_pos,
        'width': width,
        'height': height,
    }


def capture_active_window_ocr():
    if not command_available('tesseract'):
        return {
            'status': 'requires_setup',
            'reason': 'tesseract not found. Install tesseract and retry.',
        }

    bounds = get_front_window_bounds()
    if bounds['status'] != 'ok':
        return {
            'status': bounds['status'],
            'reason': bounds.get('reason', 'Window bounds unavailable.'),
        }

    screenshot_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as file_handle:
            screenshot_path = file_handle.name

        region = f"{bounds['x']},{bounds['y']},{bounds['width']},{bounds['height']}"
        screenshot_result = run_command(['screencapture', '-x', '-R', region, screenshot_path], timeout=20)
        capture_scope = 'active_window'
        if not screenshot_result['ok']:
            screenshot_result = run_command(['screencapture', '-x', screenshot_path], timeout=20)
            capture_scope = 'fullscreen_fallback'
        if not screenshot_result['ok']:
            return {
                'status': 'unavailable',
                'reason': screenshot_result['stderr'],
            }

        ocr_result = run_command(['tesseract', screenshot_path, 'stdout', '--psm', '6'], timeout=30)
        if not ocr_result['ok']:
            return {
                'status': 'unavailable',
                'reason': ocr_result['stderr'],
            }

        text = ocr_result['stdout'].strip()
        return {
            'status': 'ok',
            'characters': len(text),
            'text_excerpt': text[:1000],
            'capture_scope': capture_scope,
            'bounds': bounds,
        }
    finally:
        if screenshot_path and os.path.exists(screenshot_path):
            os.remove(screenshot_path)


def detect_active_window_type(text_excerpt):
    lowered = (text_excerpt or '').lower()
    for window_type, keywords in ACTIVE_WINDOW_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return window_type
    return 'general'


def infer_user_state_from_tier2(tier2):
    if not tier2:
        return 'unknown'

    interaction_sample = tier2.get('interaction_sample', {})
    actions = interaction_sample.get('actions', {})
    typing = actions.get('typing', {})
    mouse_clicks = actions.get('mouse_clicks', {})
    mouse_motion = actions.get('mouse_motion', {})
    scrolls = actions.get('scrolls', {})

    activity_signals = {
        typing.get('status'),
        mouse_clicks.get('status'),
        mouse_motion.get('status'),
        scrolls.get('status'),
    }
    return 'active' if 'observed' in activity_signals else 'idle'


def build_active_window_summary(tier2=None, captured_at=None):
    captured_at = captured_at or utc_timestamp()
    ocr = capture_active_window_ocr()
    user_state = infer_user_state_from_tier2(tier2)
    frontmost = get_frontmost_app_context()

    if ocr.get('status') != 'ok':
        return {
            'captured_at': captured_at,
            'user_state': user_state,
            'window_type': 'unknown',
            'description': 'Active window context unavailable.',
            'window_title': clean_window_title(frontmost.get('window_title', '')),
        }

    excerpt = (ocr.get('text_excerpt') or '').strip()
    window_type = detect_active_window_type(excerpt)
    description_map = {
        'coding': 'User appears to be working in a code/editor view.',
        'chat': 'User appears to be reading or writing chat-style content.',
        'browser': 'User appears to be viewing a browser/web page.',
        'document': 'User appears to be working in a document or notes view.',
        'general': 'User appears to be focused on a general application window.',
    }

    return {
        'captured_at': captured_at,
        'user_state': user_state,
        'window_type': window_type,
        'description': description_map[window_type],
        'window_title': clean_window_title(frontmost.get('window_title', '')),
    }


def infer_possible_audio_apps(tier1, active_window):
    if not tier1:
        fallback = None
        return [fallback] if fallback else []

    applications = tier1.get('action_map', {}).get('applications', [])
    scored = []
    for app in applications:
        app_name = app.get('name', '')
        normalized = app_name.lower()
        focus = app.get('focus', {})
        activity = app.get('activity', {})

        score = 0
        if any(keyword in normalized for keyword in LIKELY_AUDIO_APP_KEYWORDS):
            score += 3
        if focus.get('priority_rank') is not None:
            score += 2
        if focus.get('window_count', 0) > 0:
            score += 1
        if activity.get('state') in {'focused', 'in_call', 'running'}:
            score += 1

        if score > 0:
            scored.append((score, app_name))

    scored.sort(key=lambda item: (-item[0], item[1]))
    result = [name for _, name in scored[:3]]

    frontmost_app = next(
        (app.get('name', '') for app in applications if app.get('focus', {}).get('is_frontmost')),
        '',
    )
    if frontmost_app and frontmost_app not in result:
        result.insert(0, frontmost_app)
        result = result[:3]
    return result


def get_transcription_runtime_state():
    backends = detect_transcription_backend()
    has_backend = len(backends) > 0
    ffmpeg = command_info('ffmpeg')
    has_ffmpeg = ffmpeg['detected']

    loopback = detect_virtual_audio_loopback_devices()
    loopback_devices = loopback.get('devices', []) if loopback['status'] == 'ok' else []
    has_loopback = len(loopback_devices) > 0
    audio_probe = get_audio_device_probe()
    avfoundation_audio_devices = list_avfoundation_audio_devices()

    backend_details = {
        'whisper_cli': command_info('whisper', ['--version']),
        'python_whisper': python_module_info('whisper', 'openai-whisper'),
        'faster_whisper': python_module_info('faster_whisper', 'faster-whisper'),
    }

    mic_available = has_backend
    system_available = has_backend and has_ffmpeg and has_loopback

    missing = []
    if not has_backend:
        missing.append('speech-to-text backend (whisper/faster-whisper)')
    if not has_ffmpeg:
        missing.append('ffmpeg')
    if not has_loopback:
        missing.append('loopback virtual audio device')

    return {
        'microphone_ready': mic_available,
        'system_output_ready': system_available,
        'detected_backends': backends,
        'backend_details': backend_details,
        'ffmpeg': ffmpeg,
        'loopback_devices': loopback_devices,
        'audio_device_probe': audio_probe,
        'avfoundation_audio_devices': avfoundation_audio_devices,
        'missing_dependencies': missing,
    }


def build_microphone_snapshot(runtime_state, captured_at=None):
    captured_at = captured_at or utc_timestamp()
    device_index = find_audio_device_index(
        runtime_state['avfoundation_audio_devices'].get('devices', []),
        runtime_state['audio_device_probe'].get('default_input'),
    )
    probe = run_audio_capture_probe(device_index)

    if runtime_state['microphone_ready']:
        return {
            'captured_at': captured_at,
            'status': 'idle',
            'live_capture_running': False,
            'transcript': '',
            'description': 'Microphone capture ready.',
            'talking_detected': probe.get('audio_detected', False),
            'device_name': runtime_state['audio_device_probe'].get('default_input'),
            'audio_detected': probe.get('audio_detected', False),
            'mean_volume_db': probe.get('mean_volume_db'),
            'max_volume_db': probe.get('max_volume_db'),
            'min_volume_db': probe.get('min_volume_db'),
        }

    return {
        'captured_at': captured_at,
        'status': 'requires_setup',
        'live_capture_running': False,
        'transcript': '',
        'description': 'Microphone capture unavailable until dependencies are installed.',
        'missing_dependencies': runtime_state['missing_dependencies'],
        'talking_detected': False,
        'device_name': runtime_state['audio_device_probe'].get('default_input'),
        'audio_detected': False,
        'mean_volume_db': None,
        'max_volume_db': None,
        'min_volume_db': None,
    }


def build_system_output_snapshot(runtime_state, tier1, active_window, captured_at=None):
    captured_at = captured_at or utc_timestamp()
    loopback_devices = runtime_state['loopback_devices']
    preferred_loopback = loopback_devices[0]['name'] if loopback_devices else None
    device_index = find_audio_device_index(
        runtime_state['avfoundation_audio_devices'].get('devices', []),
        preferred_loopback,
    )
    probe = run_audio_capture_probe(device_index)
    possible_apps = infer_possible_audio_apps(tier1, active_window)
    media_playback_states = get_media_app_playback_states()
    media_playing = get_media_app_states()

    probe_audio_detected = probe.get('audio_detected', False)
    confirmed_playing = [entry for entry in media_playback_states if entry.get('playback_state') == 'playing']
    listening_detected = probe_audio_detected or len(media_playing) > 0 or len(confirmed_playing) > 0

    # Promote confirmed-playing apps to front of possible_source_apps
    confirmed_app_names = [entry['app'] for entry in media_playing]
    merged_apps = confirmed_app_names + [a for a in possible_apps if a not in confirmed_app_names]

    frontmost_app = next(
        (app.get('name', '') for app in (tier1 or {}).get('action_map', {}).get('applications', []) if app.get('focus', {}).get('is_frontmost')),
        '',
    )

    source_entry = None
    if confirmed_playing:
        source_entry = confirmed_playing[0]
    elif media_playing:
        source_entry = media_playing[0]

    source_app = source_entry.get('app') if source_entry else (merged_apps[0] if merged_apps else '')
    sound_text = source_entry.get('sound_text', '') if source_entry else active_window.get('description', '')
    playback_state = source_entry.get('playback_state', 'unknown') if source_entry else 'unknown'
    source_active = bool(source_app and frontmost_app and source_app == frontmost_app)

    if source_app and frontmost_app and source_app != frontmost_app:
        content_hint = f'User is listening to audio from {source_app} while using {frontmost_app}.'
    elif source_app:
        content_hint = f'User is listening to audio in {source_app}.'
    else:
        content_hint = active_window.get('description', '')

    return_base = {
        'captured_at': captured_at,
        'live_capture_running': False,
        'transcript': '',
        'description': 'System output capture ready.',
        'listening_detected': listening_detected,
        'source_app': source_app,
        'source_active': source_active,
        'playback_state': playback_state,
        'sound_text': sound_text,
        'content_hint': content_hint,
        'device_name': preferred_loopback,
        'audio_detected': probe_audio_detected,
        'mean_volume_db': probe.get('mean_volume_db'),
        'max_volume_db': probe.get('max_volume_db'),
        'min_volume_db': probe.get('min_volume_db'),
    }

    if runtime_state['system_output_ready']:
        return {
            'status': 'idle',
            **return_base,
        }

    return {
        'status': 'requires_setup',
        'description': 'System output capture unavailable until dependencies are installed.',
        'missing_dependencies': runtime_state['missing_dependencies'],
        **return_base,
    }


def collect_tier3_snapshot(tier1=None, tier2=None, capture_timestamp=None):
    runtime_state = get_transcription_runtime_state()
    synchronized_capture_time = capture_timestamp or utc_timestamp()
    active_window = build_active_window_summary(tier2, captured_at=synchronized_capture_time)

    return {
        'active_window': active_window,
        'microphone_transcription': build_microphone_snapshot(runtime_state, captured_at=synchronized_capture_time),
        'system_output_audio_transcription': build_system_output_snapshot(
            runtime_state,
            tier1,
            active_window,
            captured_at=synchronized_capture_time,
        ),
    }
