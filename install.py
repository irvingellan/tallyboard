#!/usr/bin/env python3
"""Install, remove or inspect Tallyboard on this computer.

    python3 install.py install [--lang pt-BR] [--port 5199]
    python3 install.py status
    python3 install.py uninstall [--purge]

Install does three things, and uninstall undoes exactly those three:
  1. copies the app into the state folder (~/.local/state/tallyboard/app);
  2. adds its status hook to Claude Code's settings.json, next to whatever is
     already there, after saving a backup of that file;
  3. on macOS, registers a per-user background service that serves the board.

Nothing needs sudo and nothing outside your home folder is touched.
Add --dry-run to see what would happen without changing anything.
"""
import argparse
import json
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / 'tallyboard'
LABEL = 'local.tallyboard.server'
EVENTS = ('UserPromptSubmit', 'PreToolUse', 'PermissionRequest', 'PostToolUse', 'Notification', 'Stop', 'SessionEnd')
MARK = 'tallyboard/app/hooks/claude_code_hook.py'  # how our own hook entries are recognised


class Layout:
    """Every path the installer touches, derived from one home folder so tests can use a fake one."""

    def __init__(self, home=None, label=LABEL):
        self.home = Path(home).expanduser() if home else Path.home()
        self.label = label
        self.state = self.home / '.local' / 'state' / 'tallyboard'
        self.app = self.state / 'app'
        self.config = self.state / 'config.json'
        self.settings = self.home / '.claude' / 'settings.json'
        self.plist = self.home / 'Library' / 'LaunchAgents' / (label + '.plist')

    def hook_command(self, python):
        return 'TALLYBOARD_STATE_DIR="%s" "%s" "%s"' % (self.state, python, self.app / 'hooks' / 'claude_code_hook.py')


def python_path():
    return '/usr/bin/python3' if Path('/usr/bin/python3').exists() else sys.executable


def is_ours(entry):
    hooks = entry.get('hooks') if isinstance(entry, dict) else None
    return isinstance(hooks, list) and any(isinstance(h, dict) and MARK in str(h.get('command', '')) for h in hooks)


def without_hooks(settings):
    """A copy of settings with every Tallyboard hook entry removed and nothing else changed."""
    result = json.loads(json.dumps(settings))
    hooks = result.get('hooks')
    if not isinstance(hooks, dict):
        return result
    for event in list(hooks):
        if isinstance(hooks[event], list):
            hooks[event] = [entry for entry in hooks[event] if not is_ours(entry)]
            if not hooks[event]:
                del hooks[event]
    if not hooks:
        del result['hooks']
    return result


def with_hooks(settings, command):
    """A copy of settings with exactly one Tallyboard entry per event, added after the existing ones."""
    result = without_hooks(settings)
    hooks = result.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" in settings.json is not an object; leaving the file alone')
    for event in EVENTS:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise ValueError('"hooks.%s" in settings.json is not a list; leaving the file alone' % event)
        entries.append({'hooks': [{'type': 'command', 'command': command, 'timeout': 5}]})
    return result


def read_settings(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))  # a broken file stops the install: never guess
    if not isinstance(data, dict):
        raise ValueError('%s does not hold a JSON object' % path)
    return data


def write_settings(path, data, original_exists):
    path.parent.mkdir(parents=True, exist_ok=True)
    if original_exists:
        backup = path.with_name(path.name + '.before-tallyboard-' + time.strftime('%Y%m%d-%H%M%S'))
        shutil.copy2(str(path), str(backup))
    temporary = path.with_name(path.name + '.tallyboard.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(str(temporary), str(path))


def service_plist(layout, python, port, touch=True):
    return {
        'Label': layout.label, 'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 3, 'ProcessType': 'Interactive',
        'ProgramArguments': [python, '-u', '-B', str(layout.app / 'server.py'), '--port', str(port),
                             '--state-dir', str(layout.state), '--allow-demo'] + (['--allow-focus'] if touch else []),
        'WorkingDirectory': str(layout.state),
        'StandardOutPath': str(layout.state / 'stdout.log'), 'StandardErrorPath': str(layout.state / 'stderr.log'),
    }


def lan_address():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(('192.0.2.1', 9))  # no packet is sent; this only asks the system which interface it would use
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def launchctl(*args):
    return subprocess.run(['/bin/launchctl'] + list(args), capture_output=True, text=True).returncode


def install(layout, lang, port, dry, service, say=print, touch=True):
    python = python_path()
    settings = read_settings(layout.settings)
    merged = with_hooks(settings, layout.hook_command(python))
    say('App folder      %s' % layout.app)
    say('Claude hooks    %s (%d events; a backup is saved first)' % (layout.settings, len(EVENTS)))
    if service:
        say('Service         %s' % layout.plist)
    if dry:
        say('Dry run: nothing was changed.')
        return 0
    layout.state.mkdir(parents=True, exist_ok=True)
    (layout.state / 'agents.d').mkdir(exist_ok=True)
    fresh = layout.state / 'app.new'
    shutil.rmtree(str(fresh), ignore_errors=True)
    shutil.copytree(str(SOURCE), str(fresh), ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.rmtree(str(layout.app), ignore_errors=True)
    os.replace(str(fresh), str(layout.app))
    config = {}
    if layout.config.exists():
        try:
            config = json.loads(layout.config.read_text(encoding='utf-8'))
        except ValueError:
            raise ValueError('%s is not valid JSON; fix or remove it and run install again' % layout.config)
    if lang:
        config['lang'] = lang
    config.setdefault('lang', 'en')
    config.setdefault('sound', True)
    layout.config.write_text(json.dumps(config, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if merged != settings:
        write_settings(layout.settings, merged, layout.settings.exists())
    if service:
        layout.plist.parent.mkdir(parents=True, exist_ok=True)
        with layout.plist.open('wb') as handle:
            plistlib.dump(service_plist(layout, python, port, touch), handle)
        domain = 'gui/%d' % os.getuid()
        launchctl('bootout', '%s/%s' % (domain, layout.label))
        started = 1
        for _ in range(10):  # an old copy takes a moment to let go of its name
            started = launchctl('bootstrap', domain, str(layout.plist))
            if started == 0:
                break
            time.sleep(0.5)
        if started != 0:
            say('The service file is in place but macOS did not start it. Try: launchctl bootstrap %s "%s"' % (domain, layout.plist))
    address = lan_address()
    say('')
    say('Installed. Open this on the tablet, on the same Wi-Fi:')
    say('    http://%s:%d/' % (address or '<this computer\'s IP>', port))
    say('Sample screens, no agent needed:  add  ?demo=cycle  to that address.')
    if not service:
        say('No background service was set up. Start the board yourself with:')
        say('    %s "%s" --port %d --state-dir "%s" --allow-demo%s' % (python, layout.app / 'server.py', port, layout.state, ' --allow-focus' if touch else ''))
    return 0


def uninstall(layout, purge, dry, service, say=print):
    settings = read_settings(layout.settings)
    cleaned = without_hooks(settings)
    say('Claude hooks    %s' % ('removing ours from %s' % layout.settings if cleaned != settings else 'none of ours found'))
    say('Service         %s' % (layout.plist if layout.plist.exists() else 'not installed'))
    say('State folder    %s (%s)' % (layout.state, 'will be deleted' if purge else 'kept; --purge deletes it'))
    if dry:
        say('Dry run: nothing was changed.')
        return 0
    if service:
        launchctl('bootout', 'gui/%d/%s' % (os.getuid(), layout.label))
    if layout.plist.exists():
        layout.plist.unlink()
    if cleaned != settings:
        write_settings(layout.settings, cleaned, True)
    shutil.rmtree(str(layout.app), ignore_errors=True)
    if purge:
        shutil.rmtree(str(layout.state), ignore_errors=True)
    say('Removed.')
    return 0


def status(layout, say=print):
    try:
        hooked = sum(1 for entries in (read_settings(layout.settings).get('hooks') or {}).values()
                     if isinstance(entries, list) for entry in entries if is_ours(entry))
    except ValueError as problem:
        hooked = 'unreadable (%s)' % problem
    say('App folder      %s' % ('present' if (layout.app / 'server.py').exists() else 'missing'))
    say('Claude hooks    %s of %d events' % (hooked, len(EVENTS)))
    say('Service file    %s' % ('present' if layout.plist.exists() else 'missing'))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Install, remove or inspect Tallyboard.')
    parser.add_argument('action', choices=('install', 'uninstall', 'status'))
    parser.add_argument('--lang', choices=('en', 'pt-BR'), help='words on screen (default: keep the current choice, else en)')
    parser.add_argument('--port', type=int, default=5199)
    parser.add_argument('--purge', action='store_true', help='with uninstall: also delete settings and session files')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--home', help='act on this folder instead of your home folder (for testing)')
    parser.add_argument('--label', default=LABEL, help='service name (for testing)')
    parser.add_argument('--no-service', action='store_true', help='write files but do not talk to launchd')
    parser.add_argument('--no-touch', action='store_true', help='make the tablet display-only: taps do nothing')
    args = parser.parse_args(argv)
    if sys.platform.startswith('win'):
        print('Windows is not supported yet: the hook command and the service are written for macOS.', file=sys.stderr)
        return 1
    layout = Layout(args.home, args.label)
    service = sys.platform == 'darwin' and not args.no_service
    try:
        if args.action == 'install':
            return install(layout, args.lang, args.port, args.dry_run, service, touch=not args.no_touch)
        if args.action == 'uninstall':
            return uninstall(layout, args.purge, args.dry_run, service)
        return status(layout)
    except (ValueError, OSError) as problem:
        print('Stopped without finishing: %s' % problem, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
