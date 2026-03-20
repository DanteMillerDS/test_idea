import os
import re
import tempfile

from .utils import run_command, run_osascript


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


def get_transcription_capabilities():
    return {
        'microphone_transcription': {
            'available': False,
            'status': 'requires_setup',
            'reason': 'Requires a speech-to-text backend such as Whisper plus microphone permission.',
        },
        'system_output_audio_transcription': {
            'available': False,
            'status': 'requires_setup',
            'reason': 'Requires loopback audio routing plus a speech-to-text backend.',
        },
    }


def collect_tier3_snapshot():
    return {
        'capabilities': get_transcription_capabilities(),
        'active_window_ocr': capture_active_window_ocr(),
        'microphone_transcription': {
            'status': 'requires_setup',
            'reason': 'No local transcription backend detected.',
        },
        'system_output_audio_transcription': {
            'status': 'requires_setup',
            'reason': 'No loopback capture plus transcription backend detected.',
        },
    }
