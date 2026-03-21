import json
from concurrent.futures import ThreadPoolExecutor

from .stream import build_output
from .tier1 import collect_tier1_snapshot
from .tier2 import SAMPLE_SECONDS, collect_tier2_snapshot
from .tier3 import collect_tier3_snapshot
from .utils import utc_timestamp


VERBOSE_CONSOLE = False


def format_reason(reason):
    return reason or 'None'


def print_tier1_summary(tier1):
    print('\nTier 1')
    print('-' * 72)
    applications = tier1['action_map']['applications']
    prioritized = [app for app in applications if app['focus'].get('priority_rank') is not None]
    print(f"  Applications tracked: {len(applications)}")
    print(f"  Prioritized apps: {len(prioritized)}")

    for app in prioritized[:5]:
        focus = app['focus']
        print(
            f"  P{focus['priority_rank']}: {app['name']} | {app['activity']['state']} | "
            f"windows={focus['window_count']} | processes={app['process_count']}"
        )
        if focus.get('primary_window_title'):
            print(f"     Window: {focus['primary_window_title']}")


def print_tier2_summary(tier2):
    print('\nTier 2')
    print('-' * 72)
    interaction_sample = tier2['interaction_sample']
    print(f"  Interaction sample status: {interaction_sample.get('status', 'unknown')}")
    print(f"  Sample duration: {interaction_sample.get('sample_seconds', 0)}s")
    if interaction_sample.get('status') == 'ok':
        actions = interaction_sample.get('actions', {})
        permissions = interaction_sample.get('permissions', {})
        typing = actions.get('typing', {})
        mouse_clicks = actions.get('mouse_clicks', {})
        mouse_motion = actions.get('mouse_motion', {})
        scrolls = actions.get('scrolls', {})

        print(
            '  Permissions: '
            f"input_monitoring={permissions.get('input_monitoring', 'unknown')}"
        )
        print(f"  Typing: {typing.get('status', 'unknown')} ({typing.get('count', 0)})")
        print(f"  Character count: {typing.get('character_count', 0)}")
        print(f"  Characters typed (raw): {typing.get('characters_typed_raw') or 'None'}")
        print(f"  Characters typed: {typing.get('characters_typed') or 'None'}")
        print(f"  Words typed: {', '.join(typing.get('words_typed', [])) or 'None'}")
        print(f"  Sentences typed: {' | '.join(typing.get('sentences_typed', [])) or 'None'}")
        print(f"  Mouse clicks: {mouse_clicks.get('status', 'unknown')} ({mouse_clicks.get('count', 0)})")
        for target in mouse_clicks.get('targets', [])[:3]:
            target_context = target.get('app_name', 'Unknown app')
            if target.get('window_title'):
                target_context = f"{target_context} -> {target.get('window_title')}"
            print(
                f"     Target: {target.get('label', 'Unknown')} "
                f"[{target_context}] (button={target.get('button_label', target.get('button', 'unknown'))})"
            )
        print(f"  Mouse motion: {mouse_motion.get('status', 'unknown')}")
        print(f"  Scrolls: {scrolls.get('status', 'unknown')}")
        print(f"  Scroll direction: {scrolls.get('direction', 'none')}")
        print(f"  Typing burst detected: {typing.get('typing_burst_detected', False)}")
    else:
        print(f"  Reason: {format_reason(interaction_sample.get('reason'))}")


def print_tier3_summary(tier3):
    print('\nTier 3')
    print('-' * 72)
    active_window = tier3['active_window']
    print(f"  User state: {active_window.get('user_state', 'unknown')}")
    print(f"  Window type: {active_window.get('window_type', 'unknown')}")
    print(f"  Description: {active_window.get('description', 'None')}")
    print(f"  Window title: {active_window.get('window_title') or 'None'}")

    microphone = tier3['microphone_transcription']
    system_output = tier3['system_output_audio_transcription']

    print(f"  Microphone transcription: {microphone.get('status', 'unknown')}")
    print(f"  Live capture running: {microphone.get('live_capture_running', False)}")
    print(f"  Transcript: {microphone.get('transcript') or 'None'}")
    print(f"  Notes: {format_reason(microphone.get('description'))}")
    print(f"  Microphone device: {microphone.get('device_name') or 'None'}")
    print(
        f"  Microphone audio detected: {microphone.get('audio_detected', False)} "
        f"(mean_db={microphone.get('mean_volume_db')}, max_db={microphone.get('max_volume_db')}, min_db={microphone.get('min_volume_db')})"
    )
    print(f"  Talking detected: {microphone.get('talking_detected', False)}")

    print(f"  System output transcription: {system_output.get('status', 'unknown')}")
    print(f"  Live capture running: {system_output.get('live_capture_running', False)}")
    print(f"  Transcript: {system_output.get('transcript') or 'None'}")
    print(f"  Notes: {format_reason(system_output.get('description'))}")
    print(f"  Source app: {system_output.get('source_app') or 'Unknown'}")
    print(f"  Source active now: {system_output.get('source_active', False)}")
    print(f"  Playback state: {system_output.get('playback_state', 'unknown')}")
    print(f"  Sound text: {system_output.get('sound_text') or 'None'}")
    print(f"  Content hint: {system_output.get('content_hint') or 'None'}")
    print(f"  System output device: {system_output.get('device_name') or 'None'}")
    print(
        f"  System output audio detected: {system_output.get('audio_detected', False)} "
        f"(mean_db={system_output.get('mean_volume_db')}, max_db={system_output.get('max_volume_db')}, min_db={system_output.get('min_volume_db')})"
    )
    print(f"  Listening detected: {system_output.get('listening_detected', False)}")


def print_action_sequence_summary(action_sequence):
    print('\nAction Sequence')
    print('-' * 72)
    for event in action_sequence:
        app = event.get('app', 'Unknown')
        evt = event.get('event', '?')
        parts = [f"  {app}: {evt}"]
        if evt == 'focused':
            wt = event.get('window_title', '')
            if wt:
                parts.append(f"({wt})")
        elif evt == 'clicked':
            note = event.get('note')
            if note:
                parts.append(f"({note})")
            else:
                label = event.get('label', '')
                button = event.get('button', '')
                parts.append(f"[{label}] ({button})")
        elif evt == 'typed':
            chars = event.get('character_count', 0)
            words = event.get('words', [])
            word_str = ', '.join(words[:5]) if words else 'none'
            parts.append(f"({chars} chars — {word_str})")
        elif evt == 'scrolled':
            parts.append(f"({event.get('direction', '')})")
        elif evt == 'audio_playing':
            sound_text = event.get('sound_text', '')
            if sound_text:
                parts.append(f"({sound_text})")
        print(' '.join(parts))


def print_context_summary(context):
    print('\nContext')
    print('-' * 72)
    session = context.get('session', {})
    user = context.get('user_state', {})
    audio = context.get('audio_state', {})
    agent = context.get('agent', {})

    print(f"  Activity:       {session.get('activity', '?')}")
    print(f"  Focus:          {session.get('focus_app', '?')} — {session.get('focus_window', '')}")
    apps = ', '.join(a['name'] for a in session.get('apps_open', []))
    print(f"  Apps open:      {apps or 'none'}")

    print(f"  Presence:       {user.get('presence', '?')}")
    print(f"  Speaking:       {user.get('speaking', False)}")
    print(f"  Listening:      {user.get('listening', False)}")
    print(f"  Typing:         {user.get('typing_intensity', 'none')}")
    print(f"  Cognitive load: {user.get('cognitive_load', '?')}  (confidence={user.get('confidence', 0)})")

    print(f"  Mic active:     {audio.get('microphone_active', False)}")
    print(f"  Ambient:        {audio.get('ambient', 'silence')}")
    if audio.get('system_audio_source'):
        print(f"  Audio source:   {audio['system_audio_source']} — {audio.get('system_audio_content', '')}")
    if audio.get('mic_transcript'):
        print(f"  Mic transcript: {audio['mic_transcript']}")

    print(f"  Agent mode:     {agent.get('mode', '?')}")
    print(f"  Directives:     {', '.join(agent.get('directives', []))}")
    opp = agent.get('opportunity', {})
    print(f"  Opportunity:    {opp.get('type', '?')} → {opp.get('trigger', '?')}")


def display_output(output):
    tier1 = output['tiers']['tier1']
    tier2 = output['tiers']['tier2']
    tier3 = output['tiers']['tier3']

    print('\n' + '=' * 72)
    print('macOS CONTEXT EVENT STREAM')
    print('=' * 72)
    print(f"\nTimestamp: {output['timestamp']}")

    print_context_summary(output.get('context', {}))
    print_tier1_summary(tier1)
    print_tier2_summary(tier2)
    print_tier3_summary(tier3)
    if 'action_sequence' in output:
        print_action_sequence_summary(output['action_sequence'])

def main():
    print('Step 1/4: Collecting running app focus map...')
    tier1 = collect_tier1_snapshot()

    print(
        f'Step 2/4: Capturing interaction + window/audio in parallel for {int(SAMPLE_SECONDS)} seconds. '
        'You can type/click/scroll/move now.'
    )
    sync_timestamp = utc_timestamp()
    with ThreadPoolExecutor(max_workers=2) as pool:
        tier2_future = pool.submit(collect_tier2_snapshot)
        tier3_future = pool.submit(
            collect_tier3_snapshot,
            tier1=tier1,
            tier2=None,
            capture_timestamp=sync_timestamp,
        )
        tier2 = tier2_future.result()
        tier3 = tier3_future.result()

    print('Step 3/4: Building semantic context...')

    print('Step 4/4: Writing output JSON...')
    output = build_output(tier1, tier2, tier3)

    if VERBOSE_CONSOLE:
        display_output(output)

    with open('tracker_output.json', 'w') as file_handle:
        json.dump(output, file_handle, indent=2)

    print('Done: Output saved to tracker_output.json')
