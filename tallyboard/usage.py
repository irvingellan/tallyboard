"""Optional plan-usage strip, read from the CodexBar CLI already on this Mac.

Off unless config.json has "usage": true. CodexBar owns the login; this file
only runs its fixed command every few minutes and keeps three numbers per
window (label, percent used, reset time). Account names and emails in its
answer are never read. Any failure simply leaves the strip empty.
"""
import calendar
import json
import subprocess
import threading
import time
from pathlib import Path

CLI_CANDIDATES = ('/opt/homebrew/bin/codexbar', '/usr/local/bin/codexbar',
                  '/Applications/CodexBar.app/Contents/Helpers/CodexBarCLI')
COMMAND = ('--provider', 'claude', '--format', 'json')
STALE_S = 1800


def enabled(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8')).get('usage') is True
    except (OSError, ValueError, AttributeError):
        return False


def _window(label, raw):
    if not isinstance(raw, dict):
        return None
    used = raw.get('usedPercent')
    if isinstance(used, bool) or not isinstance(used, (int, float)) or not 0 <= used <= 1000:
        return None
    try:
        resets = calendar.timegm(time.strptime(str(raw.get('resetsAt'))[:19], '%Y-%m-%dT%H:%M:%S'))
    except ValueError:
        resets = None
    return {'label': label, 'used': int(round(used)), 'resets_at': resets}


def parse(text):
    """CodexBar JSON -> up to three windows, or [] when it is not what we expect."""
    try:
        entries = json.loads(text)
    except ValueError:
        return []
    for entry in entries if isinstance(entries, list) else []:
        usage = entry.get('usage') if isinstance(entry, dict) and entry.get('provider') == 'claude' else None
        if not isinstance(usage, dict):
            continue
        found = [_window('@u_5h', usage.get('primary')), _window('@u_week', usage.get('secondary'))]
        for extra in usage.get('extraRateWindows') or []:
            if isinstance(extra, dict) and 'fable' in str(extra.get('id')).lower():
                found.append(_window('Fable', extra.get('window')))
        return [window for window in found if window][:3]
    return []


class Usage:
    def __init__(self, run=subprocess.run, clock=time.time):
        self.run, self.clock = run, clock
        self.cli = next((path for path in CLI_CANDIDATES if Path(path).exists()), None)
        self.windows, self.at = [], None

    def refresh(self):
        if not self.cli:
            return False
        try:
            done = self.run([self.cli] + list(COMMAND), capture_output=True, text=True, timeout=40)
        except (OSError, subprocess.SubprocessError):
            return False
        windows = parse(done.stdout or '') if done.returncode == 0 else []
        if windows:
            self.windows, self.at = windows, self.clock()
        return bool(windows)

    def view(self):
        """What the tablet may show: nothing once the numbers are too old to trust."""
        if self.at is None or self.clock() - self.at > STALE_S:
            return None
        return {'at': self.at, 'windows': self.windows}

    def forever(self, interval=300):
        while True:
            try:
                self.refresh()
            except Exception:  # the display must outlive any usage trouble
                pass
            time.sleep(interval)

    def start(self):
        threading.Thread(target=self.forever, name='plan-usage', daemon=True).start()
