from .utils import run_osascript


def build_permissioned_capabilities():
    return {
        'keydown_typing_bursts': {
            'available': False,
            'status': 'requires_setup',
            'reason': 'Requires Quartz event tap support plus macOS Input Monitoring permission.',
        },
        'mouse_clicks': {
            'available': False,
            'status': 'requires_setup',
            'reason': 'Requires Quartz event tap support plus Accessibility permission.',
        },
        'scrolls': {
            'available': False,
            'status': 'requires_setup',
            'reason': 'Requires Quartz event tap support plus Accessibility permission.',
        },
        'focused_accessibility_element': {
            'available': True,
            'status': 'probe',
            'reason': 'Can be queried through System Events when Accessibility permission is granted.',
        },
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


def collect_tier2_snapshot():
    return {
        'capabilities': build_permissioned_capabilities(),
        'focused_accessibility_element': get_focused_accessibility_element(),
    }
