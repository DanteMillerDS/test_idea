import json

from .stream import build_output
from .tier1 import collect_tier1_snapshot
from .tier2 import collect_tier2_snapshot
from .tier3 import collect_tier3_snapshot


def display_output(output):
    tier1 = output['tiers']['tier1']
    tier2 = output['tiers']['tier2']
    tier3 = output['tiers']['tier3']

    print('\n' + '=' * 72)
    print('macOS CONTEXT EVENT STREAM')
    print('=' * 72)
    print(f"\nTimestamp: {output['timestamp']}")

    print('\nTier 1')
    print('-' * 72)
    print(f"  Frontmost app: {tier1['frontmost_app']['app_name']}")
    print(f"  Window title: {tier1['frontmost_app'].get('window_title') or 'Unknown'}")
    print(f"  Idle state: {tier1['idle_state'].get('activity_state', 'unknown')}")
    print(f"  Running processes: {tier1['running_processes']['count']}")
    print(f"  Installed applications: {tier1['installed_applications']['count']}")
    print(f"  Media hints: {len(tier1['media_active_hints'])}")

    print('\nTier 2')
    print('-' * 72)
    focused_element = tier2['focused_accessibility_element']
    print(f"  Focused accessibility element status: {focused_element.get('status', 'unknown')}")
    if focused_element.get('status') == 'ok':
        print(f"  Role: {focused_element.get('role') or 'Unknown'}")
        print(f"  Title: {focused_element.get('title') or 'Unknown'}")

    print('\nTier 3')
    print('-' * 72)
    ocr = tier3['active_window_ocr']
    print(f"  Active window OCR status: {ocr.get('status', 'unknown')}")
    if ocr.get('status') == 'ok':
        print(f"  OCR characters: {ocr.get('characters', 0)}")
    print(f"  Microphone transcription: {tier3['microphone_transcription']['status']}")
    print(f"  System output transcription: {tier3['system_output_audio_transcription']['status']}")

    print('\nEvent stream summary')
    print('-' * 72)
    print(f"  Events emitted: {len(output['event_stream'])}")
    for event in output['event_stream'][:6]:
        print(f"  [{event['tier']}] {event['type']}")


def main():
    print('Collecting macOS context event stream...\n')

    tier1 = collect_tier1_snapshot()
    tier2 = collect_tier2_snapshot()
    tier3 = collect_tier3_snapshot()
    output = build_output(tier1, tier2, tier3)

    display_output(output)

    with open('tracker_output.json', 'w') as file_handle:
        json.dump(output, file_handle, indent=2)

    print('\nOutput saved to tracker_output.json')
