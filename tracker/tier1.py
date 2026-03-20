import re

from .applications import group_processes_by_application, infer_action_map, list_installed_applications, list_running_processes
from .utils import run_json_command, run_osascript


IDLE_THRESHOLD_SECONDS = 60
NORMALIZE_PATTERN = r'[^a-z0-9]+'


def get_frontmost_application():
    script = r'''
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set appName to name of frontApp
            set bundleId to ""
            set windowTitle to ""
            try
                set bundleId to id of application appName
            end try
            try
                if (count of windows of frontApp) > 0 then
                    set windowTitle to name of front window of frontApp
                end if
            end try
            return appName & linefeed & bundleId & linefeed & windowTitle
        end tell
    '''
    result = run_osascript(script)
    if not result['ok']:
        return {
            'app_name': 'Unknown',
            'bundle_id': '',
            'window_title': '',
            'normalized_name': '',
            'normalized_bundle_id': '',
            'error': result['stderr'],
        }

    lines = result['stdout'].splitlines()
    app_name = lines[0].strip() if lines else 'Unknown'
    bundle_id = lines[1].strip() if len(lines) > 1 else ''
    window_title = lines[2].strip() if len(lines) > 2 else ''
    return {
        'app_name': app_name,
        'bundle_id': bundle_id,
        'window_title': window_title,
        'normalized_name': re.sub(NORMALIZE_PATTERN, '', app_name.lower()),
        'normalized_bundle_id': re.sub(NORMALIZE_PATTERN, '', bundle_id.lower()),
    }


def get_idle_state(idle_threshold_seconds=IDLE_THRESHOLD_SECONDS):
    result = run_osascript('return do shell script "ioreg -c IOHIDSystem | grep HIDIdleTime | head -n 1"')
    if not result['ok']:
        return {
            'status': 'unavailable',
            'reason': result['stderr'],
        }

    match = re.search(r'"HIDIdleTime" = (\d+)', result['stdout'])
    if not match:
        return {
            'status': 'unavailable',
            'reason': 'HIDIdleTime not found',
        }

    idle_nanoseconds = int(match.group(1))
    idle_seconds = round(idle_nanoseconds / 1_000_000_000, 2)
    return {
        'status': 'ok',
        'idle_seconds': idle_seconds,
        'activity_state': 'idle' if idle_seconds >= idle_threshold_seconds else 'active',
        'idle_threshold_seconds': idle_threshold_seconds,
    }


def get_audio_device_state():
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

    normalized_devices = []
    default_input = None
    default_output = None
    for device in devices:
        normalized = {
            'name': device.get('_name', 'Unknown'),
            'manufacturer': device.get('coreaudio_device_manufacturer'),
            'transport': device.get('coreaudio_device_transport'),
            'input_channels': device.get('coreaudio_device_input', 0),
            'output_channels': device.get('coreaudio_device_output', 0),
            'is_default_input': device.get('coreaudio_default_audio_input_device') == 'spaudio_yes',
            'is_default_output': device.get('coreaudio_default_audio_output_device') == 'spaudio_yes',
            'is_default_system_output': device.get('coreaudio_default_audio_system_device') == 'spaudio_yes',
        }
        normalized_devices.append(normalized)
        if normalized['is_default_input']:
            default_input = normalized
        if normalized['is_default_output']:
            default_output = normalized

    return {
        'status': 'ok',
        'default_input': default_input,
        'default_output': default_output,
        'devices': normalized_devices,
        'virtual_devices': [device for device in normalized_devices if device['transport'] == 'coreaudio_device_type_virtual'],
    }


def infer_media_active_hints(action_map):
    hints = []
    media_app_names = {'spotify', 'music', 'quicktimeplayer', 'quicktime', 'vlc', 'safari', 'googlechrome'}
    audio_markers = ('audio.mojom.audioservice', 'video_capture.mojom.videocaptureservice', 'share', 'screen')

    for app in action_map:
        normalized_name = re.sub(NORMALIZE_PATTERN, '', app['name'].lower())
        cmdline_blob = ' '.join(' '.join(process['cmdline']) for process in app['processes']).lower()
        matched_markers = [marker for marker in audio_markers if marker in cmdline_blob]

        if normalized_name in media_app_names and app['process_count'] > 0:
            hints.append({
                'app': app['name'],
                'hint': 'media_capable_app_running',
                'confidence': 0.45,
            })

        if matched_markers:
            hints.append({
                'app': app['name'],
                'hint': 'audio_or_video_service_detected',
                'confidence': 0.7,
                'signals': matched_markers,
            })

    return hints


def collect_tier1_snapshot():
    frontmost_app = get_frontmost_application()
    applications = list_installed_applications()
    processes = list_running_processes()
    grouped_apps = group_processes_by_application(processes, applications, frontmost_app)
    action_map = infer_action_map(grouped_apps)
    audio_state = get_audio_device_state()
    media_hints = infer_media_active_hints(action_map)

    return {
        'frontmost_app': frontmost_app,
        'idle_state': get_idle_state(),
        'running_processes': {
            'count': len(processes),
        },
        'installed_applications': {
            'count': len(applications),
            'apps': [
                {
                    'name': app['name'],
                    'path': app['path'],
                    'bundle_id': app['bundle_id'],
                    'executable': app['executable'],
                }
                for app in applications
            ],
        },
        'action_map': {
            'total_process_groups': len(action_map),
            'applications': [
                {
                    'name': app['name'],
                    'bundle_id': app['bundle_id'],
                    'focus': app['focus'],
                    'process_count': app['process_count'],
                    'activity': app['activity'],
                }
                for app in action_map
                if app['installed']
            ],
        },
        'audio_device_state': audio_state,
        'media_active_hints': media_hints,
    }
