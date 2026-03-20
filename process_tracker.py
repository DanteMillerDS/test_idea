import psutil
import os
from pathlib import Path
import json
from datetime import datetime

def list_running_processes():
    """Get all running processes"""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'status']):
        try:
            processes.append({
                'pid': proc.info['pid'],
                'name': proc.info['name'],
                'status': proc.info['status']
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return processes

def get_bundle_id(app_path):
    """Extract bundle ID from app's Info.plist"""
    import plistlib
    plist_path = os.path.join(app_path, 'Contents', 'Info.plist')
    try:
        with open(plist_path, 'rb') as f:
            plist = plistlib.load(f)
            return plist.get('CFBundleIdentifier', 'Unknown')
    except Exception as e:
        return f'Error: {str(e)}'

def list_installed_applications():
    """Get all installed applications from /Applications and ~/Applications"""
    apps = []
    app_paths = [
        '/Applications',
        os.path.expanduser('~/Applications')
    ]
    
    for path in app_paths:
        if os.path.exists(path):
            try:
                for item in os.listdir(path):
                    if item.endswith('.app'):
                        app_path = os.path.join(path, item)
                        apps.append({
                            'name': item.replace('.app', ''),
                            'path': app_path,
                            'bundle_id': get_bundle_id(app_path)
                        })
            except PermissionError:
                print(f"Warning: Permission denied accessing {path}")
    
    return apps

def display_output(processes, applications):
    """Display formatted output"""
    output = {
        'timestamp': datetime.now().isoformat(),
        'running_processes': {
            'count': len(processes),
            'samples': processes[:10]  # Show first 10 processes
        },
        'installed_applications': {
            'count': len(applications),
            'apps': applications
        }
    }
    
    print("\n" + "="*60)
    print("macOS PROCESS & APPLICATION TRACKER")
    print("="*60)
    print(f"\nTimestamp: {output['timestamp']}")
    
    print(f"\n📊 RUNNING PROCESSES: {output['running_processes']['count']} total")
    print("-" * 60)
    print("Sample (first 10):")
    for proc in output['running_processes']['samples']:
        print(f"  PID: {proc['pid']:6d} | {proc['name']:30s} | Status: {proc['status']}")
    
    print(f"\n📱 INSTALLED APPLICATIONS: {output['installed_applications']['count']} found")
    print("-" * 60)
    for app in output['installed_applications']['apps']:
        print(f"  Name: {app['name']}")
        print(f"    Path: {app['path']}")
        print(f"    Bundle ID: {app['bundle_id']}\n")
    
    return output

def main():
    """Main function to test the tracker"""
    print("Starting macOS Process & Application Tracker...\n")
    
    # Get running processes
    print("Fetching running processes...")
    processes = list_running_processes()
    print(f"✓ Found {len(processes)} running processes")
    
    # Get installed applications
    print("Fetching installed applications...")
    applications = list_installed_applications()
    print(f"✓ Found {len(applications)} installed applications\n")
    
    # Display output
    output = display_output(processes, applications)
    
    # Save to JSON file
    with open('tracker_output.json', 'w') as f:
        json.dump(output, f, indent=2)
    print("\n✓ Output saved to tracker_output.json")

if __name__ == '__main__':
    main()