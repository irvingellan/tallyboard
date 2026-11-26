"""Optional tablet minder: keeps an Android tablet on the board over ADB.

Off unless config.json has a "tablet" block. It only ever issues five fixed
commands to the one device whose serial is configured: read its serial, set
the backlight, bring the kiosk browser to the console URL (within seconds when
the page went silent, once a night as hygiene), restart that browser when
reloading keeps failing, and re-enable ADB over Wi-Fi when the tablet is seen
on USB. Every failure is silent: the
console keeps serving whether or not the tablet can be reached.
"""
import json
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

ADB_CANDIDATES = ('/opt/homebrew/bin/adb', '/usr/local/bin/adb')
SERIAL = re.compile(r'^[A-Za-z0-9]{6,32}$')
PACKAGE = re.compile(r'^[A-Za-z0-9_.]{3,80}$')
WIFI = re.compile(r'^(\d{1,3}(?:\.\d{1,3}){3}):5555$')
# Out of 255. An idle level much lower than this made the clock unreadable in daylight on the test tablet.
DEFAULT_LEVELS = {'idle': 170, 'night': 40, 'active': 200, 'ambient': 200, 'blocked': 255}


def load(path):
    """-> validated tablet config dict, or None when absent or malformed."""
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8')).get('tablet')
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(raw, dict) or not SERIAL.match(str(raw.get('serial') or '')):
        return None
    package = raw.get('package') if PACKAGE.match(str(raw.get('package') or '')) else 'de.ozerov.fully'
    levels = dict(DEFAULT_LEVELS)
    if raw.get('brightness') is False:
        levels = None
    elif isinstance(raw.get('brightness'), dict):
        for key, value in raw['brightness'].items():
            if key in levels and isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 255:
                levels[key] = value
    recover = raw.get('recover_after_s')
    return {'serial': raw['serial'], 'package': package, 'levels': levels,
            'recover_after_s': recover if isinstance(recover, int) and 20 <= recover <= 3600 else 60}


SILENT_S = 25
NIGHTLY_HOUR = 5


def hour_now(hour=None):
    return time.localtime().tm_hour if hour is None else hour


def level_for(view, levels, hour):
    """Backlight for what is on screen: dark when idle, full only for the strong alert."""
    if view['mode'] == 'blocked':
        return levels['ambient'] if view.get('alert') == 'ambient' else levels['blocked']
    if view['mode'] == 'idle':
        return levels['night'] if (hour >= 23 or hour < 7) else levels['idle']
    return levels['active']


class Tablet:
    def __init__(self, config, console, port, state_dir, run=subprocess.run, clock=time.monotonic):
        self.config, self.console, self.port = config, console, port
        self.memo = Path(state_dir) / 'tablet.json'
        self.run, self.clock = run, clock
        self.adb_path = next((p for p in ADB_CANDIDATES if Path(p).exists()), None) or shutil.which('adb')
        self.verified = {}       # transport -> serial it answered with
        self.level = None
        self.manual_mode_set = False
        self.started = clock()
        self.away_since = None   # when something other than the kiosk browser took the screen
        self.last = {}           # action -> monotonic time, for rate limits
        self.failed = 0          # recoveries in a row that did not bring the page back
        self.heard = None        # console.tablet_seen at the last recovery

    def adb(self, *args, transport=None, timeout=8):
        command = [self.adb_path] + (['-s', transport] if transport else []) + list(args)
        try:
            done = self.run(command, capture_output=True, text=True, timeout=timeout)
            return done.returncode, (done.stdout or '').strip()
        except (OSError, subprocess.SubprocessError):
            return 1, ''

    def _due(self, action, every):
        now = self.clock()
        if now - self.last.get(action, -1e9) < every:
            return False
        self.last[action] = now
        return True

    def _is_ours(self, transport):
        if transport == self.config['serial']:
            return True
        if transport not in self.verified:
            code, out = self.adb('shell', 'getprop', 'ro.serialno', transport=transport)
            if code == 0 and out:
                self.verified[transport] = out
        return self.verified.get(transport) == self.config['serial']

    def transports(self):
        code, out = self.adb('devices')
        names = [line.split('\t')[0] for line in out.splitlines()[1:] if line.endswith('\tdevice')] if code == 0 else []
        return [name for name in names if (name == self.config['serial'] or WIFI.match(name)) and self._is_ours(name)]

    def _remember(self, address):
        try:
            self.memo.write_text(json.dumps({'address': address}), encoding='utf-8')
        except OSError:
            pass

    def _recall(self):
        try:
            address = json.loads(self.memo.read_text(encoding='utf-8')).get('address')
        except (OSError, ValueError, AttributeError):
            return None
        return address if isinstance(address, str) and WIFI.match(address) else None

    def connect(self):
        """-> a usable transport or None. Prefers Wi-Fi so the cable stays optional."""
        mine = self.transports()
        wifi = [t for t in mine if WIFI.match(t)]
        if wifi:
            self._remember(wifi[0])
            return wifi[0]
        if self.config['serial'] in mine:
            if self._due('tcpip', 600):  # seen on USB: turn Wi-Fi control back on for next time
                code, out = self.adb('shell', 'ip', '-4', 'addr', 'show', 'wlan0', transport=self.config['serial'])
                found = re.search(r'inet (\d{1,3}(?:\.\d{1,3}){3})/', out)
                self.adb('tcpip', '5555', transport=self.config['serial'])
                if found:
                    time.sleep(3)
                    self.adb('connect', found.group(1) + ':5555')
            return self.config['serial']
        address = self._recall()
        if address and self._due('reconnect', 60):
            self.adb('disconnect', address, timeout=6)  # a stale "offline" entry blocks a fresh connect
            self.adb('connect', address, timeout=6)
            if address in self.transports():
                return address
        return None

    def mac_address_for(self, transport):
        """The Mac's LAN address as the tablet sees it (works after the Mac's IP changes)."""
        match = WIFI.match(transport)
        target = match.group(1) if match else None
        if not target:
            code, out = self.adb('shell', 'ip', '-4', 'addr', 'show', 'wlan0', transport=transport)
            found = re.search(r'inet (\d{1,3}(?:\.\d{1,3}){3})/', out)
            target = found.group(1) if found else None
        if not target:
            return None
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect((target, 9))
            return probe.getsockname()[0]
        except OSError:
            return None
        finally:
            probe.close()

    def step(self, hour=None):
        if not self.adb_path:
            return 'no-adb'
        transport = self.connect()
        if not transport:
            return 'unreachable'
        did = []
        levels = self.config['levels']
        if levels:
            hour = time.localtime().tm_hour if hour is None else hour
            wanted = level_for(self.console.state(), levels, hour)
            if wanted != self.level or self.clock() - self.last.get('reassert', -1e9) >= 300:
                if not self.manual_mode_set:
                    self.adb('shell', 'settings', 'put', 'system', 'screen_brightness_mode', '0', transport=transport)
                    self.manual_mode_set = True
                if self.adb('shell', 'settings', 'put', 'system', 'screen_brightness', str(wanted), transport=transport)[0] == 0:
                    self.level = wanted
                    self.last['reassert'] = self.clock()
                    did.append('brightness=%d' % wanted)
        # The page keeps polling from the background, so silence alone misses a tablet
        # that wandered to the launcher: also ask which app owns the screen.
        code, focus = self.adb('shell', 'dumpsys', 'window', 'windows', transport=transport)
        current = re.search(r'mCurrentFocus=.*', focus)
        if code == 0 and current and self.config['package'] + '/' not in current.group(0):
            self.away_since = self.away_since if self.away_since is not None else self.clock()
        else:
            self.away_since = None
        away = self.clock() - self.away_since if self.away_since is not None else 0
        seen = self.console.tablet_seen
        quiet = self.clock() - (seen if seen is not None else self.started)
        # Another app on screen gets the full grace period; a kiosk that is in front but
        # silent (error page, half-loaded page) is simply broken and is reloaded quickly.
        silent = quiet > SILENT_S and self.away_since is None
        nightly = hour_now(hour) == NIGHTLY_HOUR and self._due('nightly', 20 * 3600)
        if (silent and self._due('recover', 40)) or nightly or (max(quiet, away) > self.config['recover_after_s'] and self._due('recover', 120)):
            address = self.mac_address_for(transport)
            if address:
                url = 'http://%s:%d/' % (address, self.port)
                self.failed = self.failed + 1 if (silent and seen == self.heard) else 0
                self.heard = seen
                if self.failed >= 2:  # two reloads did nothing; reloading is not enough: restart the kiosk browser itself
                    self.adb('shell', 'am', 'force-stop', self.config['package'], transport=transport)
                    self.failed = 0
                    did.append('restart')
                self.adb('shell', 'am', 'start', '-n', self.config['package'] + '/.MainActivity',
                         '-a', 'android.intent.action.VIEW', '-d', url, transport=transport)
                did.append('recover=' + url)
                self.away_since = None
        return ' '.join(did) or 'ok'

    def forever(self, interval=10):
        last = None
        while True:
            try:
                result = self.step()
            except Exception as error:  # the display must outlive any tablet trouble
                result = 'error: %s' % type(error).__name__
            if result != last and result != 'ok':
                print('tablet: %s' % result, flush=True)
            last = result
            time.sleep(interval)

    def start(self):
        threading.Thread(target=self.forever, name='tablet-minder', daemon=True).start()
