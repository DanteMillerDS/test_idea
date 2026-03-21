from .applications import group_processes_by_application, infer_action_map, list_installed_applications, list_running_processes
from .utils import run_osascript


FIELD_DELIMITER = chr(31)
WINDOW_DELIMITER = chr(30)


def parse_window_count(parts):
    if len(parts) <= 3 or not parts[3].strip():
        return 0

    try:
        return int(parts[3].strip())
    except ValueError:
        return 0


def parse_window_titles(parts):
    if len(parts) <= 4 or not parts[4]:
        return []

    return [title.strip() for title in parts[4].split(WINDOW_DELIMITER) if title.strip()]


def parse_focus_entry(raw_line):
    parts = raw_line.split(FIELD_DELIMITER)
    window_titles = parse_window_titles(parts)
    return {
        'app_name': parts[0].strip() if parts else 'Unknown',
        'is_frontmost': len(parts) > 1 and parts[1].strip().lower() == 'true',
        'is_visible': len(parts) > 2 and parts[2].strip().lower() == 'true',
        'window_count': parse_window_count(parts),
        'window_titles': window_titles,
        'primary_window_title': window_titles[0] if window_titles else '',
    }


def sort_focus_entries(focus_entries):
    return sorted(
        focus_entries,
        key=lambda entry: (
            not entry['is_frontmost'],
            not entry['is_visible'],
            -entry['window_count'],
            entry['app_name'].lower(),
        ),
    )


def assign_priority_ranks(focus_entries):
    priority_rank = 1
    for entry in focus_entries:
        if entry['is_frontmost'] or entry['is_visible'] or entry['window_count'] > 0:
            entry['priority_rank'] = priority_rank
            priority_rank += 1
        else:
            entry['priority_rank'] = None
    return focus_entries


def build_action_map_entries(action_map):
    exported_applications = [
        {
            'name': app['name'],
            'bundle_id': app['bundle_id'],
            'focus': dict(app['focus']),
            'process_count': app['process_count'],
            'activity': app['activity'],
        }
        for app in action_map
        if app['installed']
    ]

    priority_rank = 1
    for app in exported_applications:
        if app['focus'].get('priority_rank') is not None:
            app['focus']['priority_rank'] = priority_rank
            priority_rank += 1

    return exported_applications


def list_application_focus_states():
    script = r'''
        on join_list(items_to_join, delimiter_value)
            set previous_delimiters to AppleScript's text item delimiters
            set AppleScript's text item delimiters to delimiter_value
            set joined_text to items_to_join as text
            set AppleScript's text item delimiters to previous_delimiters
            return joined_text
        end join_list

        set field_delimiter to ASCII character 31
        set window_delimiter to ASCII character 30

        tell application "System Events"
            set output_lines to {}
            repeat with proc_ref in application processes
                set app_name to name of proc_ref
                set is_frontmost to "false"
                set is_visible to "false"
                try
                    if frontmost of proc_ref then set is_frontmost to "true"
                end try
                try
                    if visible of proc_ref then set is_visible to "true"
                end try

                set window_titles to {}
                try
                    repeat with win_ref in windows of proc_ref
                        try
                            set window_name to name of win_ref as text
                            if window_name is not "" then set end of window_titles to window_name
                        end try
                    end repeat
                end try

                set window_blob to my join_list(window_titles, window_delimiter)
                set window_count_text to (count of window_titles) as text
                set end of output_lines to app_name & field_delimiter & is_frontmost & field_delimiter & is_visible & field_delimiter & window_count_text & field_delimiter & window_blob
            end repeat
            return my join_list(output_lines, linefeed)
        end tell
    '''
    result = run_osascript(script, timeout=20)
    if not result['ok']:
        return []

    focus_entries = [parse_focus_entry(raw_line) for raw_line in result['stdout'].splitlines() if raw_line.strip()]
    prioritized_entries = sort_focus_entries(focus_entries)
    return assign_priority_ranks(prioritized_entries)


def collect_tier1_snapshot():
    applications = list_installed_applications()
    processes = list_running_processes()
    focus_entries = list_application_focus_states()
    grouped_apps = group_processes_by_application(processes, applications, focus_entries)
    action_map = infer_action_map(grouped_apps)
    action_map_entries = build_action_map_entries(action_map)

    return {
        'action_map': {
            'applications': action_map_entries,
        },
    }
