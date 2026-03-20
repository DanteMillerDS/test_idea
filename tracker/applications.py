import os
import plistlib

import psutil

from .utils import normalize_name


def extract_outer_app_bundle(path_value):
    if not path_value:
        return None

    marker = '.app/'
    marker_index = path_value.find(marker)
    if marker_index != -1:
        return path_value[:marker_index + len('.app')]

    if path_value.endswith('.app'):
        return path_value

    return None


def extract_bundle_name(path_value):
    bundle_path = extract_outer_app_bundle(path_value)
    if not bundle_path:
        return None
    return os.path.basename(bundle_path)[:-4]


def detect_process_app_bundle(executable_path, cmdline):
    app_bundle_path = extract_outer_app_bundle(executable_path)
    if app_bundle_path:
        return app_bundle_path

    for argument in cmdline:
        app_bundle_path = extract_outer_app_bundle(argument)
        if app_bundle_path:
            return app_bundle_path

    return None


def read_app_metadata(app_path):
    plist_path = os.path.join(app_path, 'Contents', 'Info.plist')
    metadata = {
        'bundle_id': 'Unknown',
        'executable': None,
    }

    try:
        with open(plist_path, 'rb') as file_handle:
            plist = plistlib.load(file_handle)
    except FileNotFoundError:
        metadata['bundle_id'] = f'Missing Info.plist: {plist_path}'
        return metadata
    except Exception as error:
        metadata['bundle_id'] = f'Error: {error}'
        return metadata

    metadata['bundle_id'] = plist.get('CFBundleIdentifier', 'Unknown')
    metadata['executable'] = plist.get('CFBundleExecutable')
    return metadata


def list_installed_applications():
    apps = []
    app_paths = [
        '/Applications',
        os.path.expanduser('~/Applications'),
    ]

    for path in app_paths:
        if not os.path.exists(path):
            continue

        try:
            for item in os.listdir(path):
                if not item.endswith('.app'):
                    continue

                app_path = os.path.join(path, item)
                metadata = read_app_metadata(app_path)
                app_name = item[:-4]
                apps.append({
                    'name': app_name,
                    'path': app_path,
                    'bundle_id': metadata['bundle_id'],
                    'executable': metadata['executable'],
                    'normalized_name': normalize_name(app_name),
                    'normalized_executable': normalize_name(metadata['executable']),
                })
        except PermissionError:
            continue

    return sorted(apps, key=lambda app: app['name'].lower())


def list_running_processes():
    processes = []
    attributes = ['pid', 'ppid', 'name', 'status', 'exe', 'cmdline', 'cpu_percent', 'memory_info']

    for proc in psutil.process_iter(attributes):
        try:
            cmdline = proc.info.get('cmdline') or []
            memory_info = proc.info.get('memory_info')
            app_bundle_path = detect_process_app_bundle(proc.info.get('exe'), cmdline)
            processes.append({
                'pid': proc.info['pid'],
                'ppid': proc.info['ppid'],
                'name': proc.info['name'] or 'Unknown',
                'status': proc.info['status'],
                'exe': proc.info.get('exe'),
                'app_bundle_path': app_bundle_path,
                'cmdline': cmdline,
                'cpu_percent': proc.info.get('cpu_percent') or 0.0,
                'memory_rss_mb': round(memory_info.rss / (1024 * 1024), 2) if memory_info else None,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return processes


def build_application_index(applications):
    indexed_apps = {}

    for app in applications:
        keys = {
            app['normalized_name'],
            normalize_name(app['bundle_id']),
            app['normalized_executable'],
        }
        keys.discard('')
        for key in keys:
            indexed_apps[key] = app

    return indexed_apps


def create_group_for_app(app_name, app_path=None, bundle_id='Unknown', executable=None, installed=False):
    return {
        'name': app_name,
        'path': app_path,
        'bundle_id': bundle_id,
        'executable': executable,
        'installed': installed,
        'focus': {
            'is_frontmost': False,
            'window_title': '',
        },
        'processes': [],
        'process_count': 0,
        'activity': {
            'state': 'background',
            'signals': [],
        },
    }


def match_process_to_app(process, application_index):
    candidate_keys = {
        normalize_name(process['name']),
        normalize_name(os.path.basename(process['exe'] or '')),
        normalize_name(extract_bundle_name(process.get('app_bundle_path'))),
    }
    candidate_keys.discard('')

    for argument in process['cmdline'][:3]:
        candidate_keys.add(normalize_name(os.path.basename(argument)))

    candidate_keys.discard('')
    for key in candidate_keys:
        matched_app = application_index.get(key)
        if matched_app:
            return matched_app

    return None


def build_initial_groups(applications):
    grouped_apps = {}
    for app in applications:
        group_key = app['bundle_id'] if app['bundle_id'] != 'Unknown' else app['normalized_name']
        grouped_apps[group_key] = create_group_for_app(
            app_name=app['name'],
            app_path=app['path'],
            bundle_id=app['bundle_id'],
            executable=app['executable'],
            installed=True,
        )
    return grouped_apps


def get_process_group(process, matched_app, grouped_apps):
    if matched_app:
        group_key = matched_app['bundle_id'] if matched_app['bundle_id'] != 'Unknown' else matched_app['normalized_name']
        return grouped_apps[group_key]

    inferred_name = process['name'] or 'Unknown'
    group_key = f"process:{normalize_name(inferred_name) or process['pid']}"
    if group_key not in grouped_apps:
        grouped_apps[group_key] = create_group_for_app(app_name=inferred_name)
    return grouped_apps[group_key]


def finalize_group_metadata(grouped_apps, frontmost_app):
    for group in grouped_apps.values():
        group['processes'].sort(key=lambda process: (process['name'].lower(), process['pid']))
        group['process_count'] = len(group['processes'])
        matches_frontmost = (
            normalize_name(group['name']) == frontmost_app['normalized_name']
            or normalize_name(group['bundle_id']) == frontmost_app['normalized_bundle_id']
            or normalize_name(group['executable']) == frontmost_app['normalized_name']
        )
        if matches_frontmost:
            group['focus'] = {
                'is_frontmost': True,
                'window_title': frontmost_app.get('window_title', ''),
            }


def infer_zoom_activity(app_group):
    signals = []
    window_title = app_group['focus'].get('window_title', '').lower()
    process_names = {normalize_name(process['name']) for process in app_group['processes']}
    cmdlines = ' '.join(' '.join(process['cmdline']) for process in app_group['processes']).lower()

    if app_group['focus']['is_frontmost']:
        signals.append('frontmost')

    meeting_keywords = ['zoom meeting', 'meeting controls', 'share screen', 'screen share']
    if any(keyword in window_title for keyword in meeting_keywords):
        signals.append(f'window:{window_title}')

    if 'cpthost' in process_names:
        signals.append('process:CptHost')

    if 'meeting' in cmdlines or ('zoom' in cmdlines and 'share' in cmdlines):
        signals.append('cmdline:meeting-like')

    if signals:
        return {
            'state': 'in_call',
            'signals': signals,
        }

    return {
        'state': 'open',
        'signals': [],
    }


def infer_generic_activity(app_group):
    signals = []
    if app_group['focus']['is_frontmost']:
        signals.append('frontmost')

    active_processes = [process for process in app_group['processes'] if process['status'] == 'running']
    if active_processes:
        signals.append(f'running_processes:{len(active_processes)}')

    if app_group['focus']['is_frontmost']:
        state = 'focused'
    elif app_group['process_count'] > 0:
        state = 'running'
    else:
        state = 'installed'

    return {
        'state': state,
        'signals': signals,
    }


def infer_action_map(grouped_apps):
    for app_group in grouped_apps.values():
        normalized_name = normalize_name(app_group['name'])
        if 'zoom' in normalized_name:
            app_group['activity'] = infer_zoom_activity(app_group)
        else:
            app_group['activity'] = infer_generic_activity(app_group)

    return sorted(
        grouped_apps.values(),
        key=lambda group: (
            not group['focus']['is_frontmost'],
            group['activity']['state'] not in {'in_call', 'focused'},
            not group['installed'],
            -group['process_count'],
            group['name'].lower(),
        ),
    )


def group_processes_by_application(processes, applications, frontmost_app):
    application_index = build_application_index(applications)
    grouped_apps = build_initial_groups(applications)

    for process in processes:
        matched_app = match_process_to_app(process, application_index)
        group = get_process_group(process, matched_app, grouped_apps)
        group['processes'].append(process)

    finalize_group_metadata(grouped_apps, frontmost_app)
    return grouped_apps
