"""Optional sound cue when a session needs you.

Off unless config.json has "sound": true (or a dict). By default the tablet
plays it (the page synthesizes the notes); {"where": "mac"} plays macOS system
sounds from this file instead. Two cues only: one when
a session finishes its turn, a more insistent one when a session blocks on a
permission or a question. Silent at night and on the first snapshot, so a
restart never replays old news. It plays fixed macOS system sounds; nothing
from an agent reaches the command line.
"""
import json
import subprocess
import threading
import time
from pathlib import Path

PLAYER = '/usr/bin/afplay'
SOUNDS = {'turn': '/System/Library/Sounds/Glass.aiff', 'blocked': '/System/Library/Sounds/Funk.aiff'}


def load(path):
    """-> {'quiet': (from_hour, to_hour)} or None when sound is off."""
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8')).get('sound')
    except (OSError, ValueError, AttributeError):
        return None
    if raw is True:
        raw = {}
    if not isinstance(raw, dict):
        return None
    quiet = raw.get('quiet_hours')
    ok = (isinstance(quiet, list) and len(quiet) == 2
          and all(isinstance(h, int) and not isinstance(h, bool) and 0 <= h <= 23 for h in quiet))
    return {'quiet': tuple(quiet) if ok else (23, 7), 'where': 'mac' if raw.get('where') == 'mac' else 'tablet'}


def is_quiet(hour, quiet):
    start, end = quiet
    return start <= hour < end if start <= end else (hour >= start or hour < end)


def needs(view):
    """-> (ids blocked on the person, ids whose turn ended) for everything on screen."""
    items = [view.get('focus')] + list(view.get('queue') or []) + list(view.get('recent') or []) + list(view.get('awaiting') or [])
    items = [item for item in items if isinstance(item, dict) and item.get('id')]
    return (set(i['id'] for i in items if i.get('state') == 'blocked'),
            set(i['id'] for i in items if i.get('state') == 'done'))


def cue(previous, current):
    """The one sound a change deserves; blocked wins. None on the first snapshot."""
    if previous is None:
        return None
    if current[0] - previous[0]:
        return 'blocked'
    if current[1] - previous[1]:
        return 'turn'
    return None


class Sound:
    def __init__(self, config, console, popen=subprocess.Popen):
        self.config, self.console, self.popen = config, console, popen
        self.previous = None

    def step(self, hour=None):
        current = needs(self.console.state())
        wanted = cue(self.previous, current)
        self.previous = current
        hour = time.localtime().tm_hour if hour is None else hour
        if not wanted or is_quiet(hour, self.config['quiet']):
            return None
        try:
            self.popen([PLAYER, SOUNDS[wanted]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return None
        return wanted

    def forever(self, interval=2):
        while True:
            try:
                played = self.step()
                if played:
                    print('sound: %s' % played, flush=True)
            except Exception:  # the display must outlive any sound trouble
                pass
            time.sleep(interval)

    def start(self):
        threading.Thread(target=self.forever, name='sound-cue', daemon=True).start()
