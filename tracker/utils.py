import json
import subprocess
from datetime import datetime, timezone


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def normalize_name(value):
    if not value:
        return ''
    return ''.join(character for character in value.lower() if character.isalnum())


def run_command(command, timeout=10):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
        return {
            'ok': True,
            'stdout': result.stdout,
            'stderr': result.stderr,
        }
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        return {
            'ok': False,
            'stdout': getattr(error, 'stdout', '') or '',
            'stderr': getattr(error, 'stderr', '') or str(error),
        }


def run_osascript(script, timeout=10):
    return run_command(['osascript', '-e', script], timeout=timeout)


def run_json_command(command, timeout=20):
    result = run_command(command, timeout=timeout)
    if not result['ok']:
        return {
            'ok': False,
            'error': result['stderr'],
        }

    try:
        return {
            'ok': True,
            'data': json.loads(result['stdout']),
        }
    except json.JSONDecodeError as error:
        return {
            'ok': False,
            'error': f'Failed to decode JSON: {error}',
        }
