#!/usr/bin/env python3
"""Tallyboard: a desk status board for your coding agents, served to an old tablet.

Python standard library only. Private-LAN clients only. Read-only except for
two opt-in taps: "open that session on this computer" and "wave this row away".
"""
import argparse
import hashlib
import ipaddress
import json
import logging
import os
import subprocess
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agenda  # noqa: E402
import antigravity  # noqa: E402
import codex  # noqa: E402
import demo  # noqa: E402
import sound  # noqa: E402
import tablet  # noqa: E402
import usage  # noqa: E402
from sources import Collector, DropinSource  # noqa: E402
from state import DEFAULTS, build_view, normalize_config  # noqa: E402

STATIC = Path(__file__).resolve().parent / 'static'
ASSETS = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/console.css': ('console.css', 'text/css; charset=utf-8'),
    '/console.js': ('console.js', 'application/javascript; charset=utf-8'),
}
PRIVATE_NETWORKS = [ipaddress.ip_network(n) for n in ('127.0.0.0/8', '192.168.0.0/16', '10.0.0.0/8', '172.16.0.0/12')]
CONFIG_KEYS = set(DEFAULTS) | {'brightness'}
LANGUAGES = ('en', 'pt-BR')
DEFAULT_STATE_DIR = '~/.local/state/tallyboard'


def is_private(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if getattr(ip, 'ipv4_mapped', None):
        ip = ip.ipv4_mapped
    return ip.version == 4 and any(ip in network for network in PRIVATE_NETWORKS)


def host_allowed(header):
    """Refuse DNS-rebinding style Host headers; LAN names and IPs only."""
    host = (header or '').rsplit(':', 1)[0].strip('[]').lower() if header else ''
    return host == 'localhost' or host.endswith(('.local', '.lan', '.home')) or is_private(host)


def load_config(path):
    """Optional overrides. A broken file must never take the display down."""
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    valid = normalize_config(raw)
    result = {key: valid[key] for key in raw if key in valid}
    brightness = raw.get('brightness')
    if isinstance(brightness, dict):
        result['brightness'] = {k: v for k, v in brightness.items() if k in ('idle', 'active', 'blocked', 'ambient', 'running', 'done', 'failed') and isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 255}
    return result


def build_id():
    digest = hashlib.sha256()
    for name, _ in ASSETS.values():
        digest.update((STATIC / name).read_bytes())
    for name in ('server.py', 'sources.py', 'state.py', 'demo.py', 'tablet.py', 'sound.py', 'usage.py', 'codex.py', 'agenda.py', 'antigravity.py'):
        digest.update((STATIC.parent / name).read_bytes())
    return digest.hexdigest()[:12]


class Console:
    def __init__(self, collector, config_path=None, clock=time.time, allow_demo=False,
                 allow_focus=False, opener=None):
        self.collector = collector
        self.config_path = config_path
        self.clock = clock
        self.started = time.monotonic()
        self.memory = {}
        self.allow_demo = allow_demo
        self.allow_focus = allow_focus
        self.opener = opener or (lambda url: subprocess.run(['/usr/bin/open', url], timeout=10, check=False))
        self.tablet_seen = None  # monotonic time of the last LAN poll, for the tablet minder
        self.build = build_id()
        self.dismissed = {}  # item id -> the ended_at the person waved away; a new turn brings it back
        self.lock = threading.Lock()

    def focus(self, item_id):
        """Touch on the tablet: bring that session's window forward on this Mac.

        The only thing this can do is open the desktop app on a session the
        agent itself reported; the id never reaches a shell."""
        if not self.allow_focus:
            return False
        self.collector.snapshot()
        session = getattr(getattr(self.collector, 'dropin', None), 'links', {}).get(item_id)
        if not session:
            return False
        try:
            self.opener('claude://claude.ai/epitaxy/' + session)
        except (OSError, subprocess.SubprocessError):
            return False
        return True

    def dismiss(self, item_id):
        """Long press on the tablet: "I am not going to answer this one". Display only;
        the session itself is untouched and returns to the list after its next turn."""
        if not self.allow_focus:
            return False
        for item in self.collector.snapshot():
            if item['id'] == item_id and item.get('awaiting'):
                with self.lock:
                    self.dismissed[item_id] = item['ended_at']
                return True
        return False

    def language(self):
        """The words on screen: "en" unless config.json says "lang": "pt-BR"."""
        try:
            chosen = json.loads(Path(self.config_path).read_text(encoding='utf-8')).get('lang')
        except (OSError, ValueError, AttributeError, TypeError):
            return 'en'
        return chosen if chosen in LANGUAGES else 'en'

    def state(self, demo_name=None):
        now = self.clock()
        config = load_config(self.config_path) if self.config_path else {}
        if demo_name:
            resolved, items = demo.scenario(demo_name, now)
            view = build_view(items, now, dict(config, roster=['claude', 'codex', 'gemini'], available_agents=['claude', 'codex', 'gemini']), demo=resolved)
        else:
            items = self.collector.snapshot()
            with self.lock:
                live = set(item['id'] for item in items)
                self.dismissed = {key: at for key, at in self.dismissed.items() if key in live}
                items = [dict(item, awaiting=False) if item.get('awaiting') and self.dismissed.get(item['id']) == item['ended_at'] else item
                         for item in items]
                view = build_view(items, now, config, memory=self.memory)
        view['build'] = self.build
        view['touch'] = bool(self.allow_focus)
        view['lang'] = self.language()
        view['chime'] = bool(getattr(self, 'chime', False))
        meter = getattr(self, 'usage', None)
        if demo_name:
            view['agenda'], view['usage'] = demo.extras(demo_name, now)
        else:
            view['usage'] = meter.view() if meter else None
            view['agenda'] = agenda.view(Path(self.config_path).parent / 'agenda.json', now) if self.config_path else None
        view['tz_offset_min'] = time.localtime(now).tm_gmtoff // 60
        if isinstance(config.get('brightness'), dict):
            view['brightness'] = config['brightness']
        return view


def make_handler(console, logger):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'Tallyboard/0'
        protocol_version = 'HTTP/1.1'

        def setup(self):
            self.request.settimeout(10)
            super().setup()

        def log_message(self, fmt, *args):
            logger.info('%s request %s', self.client_address[0], args[1] if len(args) > 1 else '-')

        def _send(self, status, body=b'', mime='text/plain; charset=utf-8', head=False):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.close_connection = True
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
            self.end_headers()
            if head:
                return
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _refuse_writes(self):
            self.close_connection = True
            self.send_response(405)
            self.send_header('Allow', 'GET, HEAD')
            self.send_header('Content-Length', '0')
            self.end_headers()

        do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _refuse_writes

        def do_POST(self):
            # One narrow exception to read-only: "show me that session". The custom
            # header makes a cross-site form or image request unable to trigger it.
            url = urlsplit(self.path)
            if (url.path not in ('/api/focus', '/api/dismiss') or not console.allow_focus or self.headers.get('X-Tallyboard') != '1'
                    or not is_private(self.client_address[0]) or not host_allowed(self.headers.get('Host'))):
                return self._refuse_writes()
            item_id = parse_qs(url.query).get('id', [''])[0][:160]
            done = console.dismiss(item_id) if url.path == '/api/dismiss' else console.focus(item_id)
            return self._send(204 if done else 404, head=True)

        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            if not is_private(self.client_address[0]) or not host_allowed(self.headers.get('Host')):
                return self._send(403, b'Forbidden\n', head=head)
            url = urlsplit(self.path)
            if url.path in ASSETS:
                name, mime = ASSETS[url.path]
                return self._send(200, (STATIC / name).read_bytes(), mime, head)
            if url.path == '/api/state':
                if not self.client_address[0].startswith('127.'):
                    console.tablet_seen = time.monotonic()
                requested = parse_qs(url.query).get('demo', [None])[0]
                if requested and not console.allow_demo:
                    return self._send(403, b'Demo disabled\n', head=head)
                body = json.dumps(console.state(requested), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                return self._send(200, body, 'application/json; charset=utf-8', head)
            if url.path == '/status':  # kept from the prototype: external liveness probes
                body = json.dumps({'uptime_seconds': round(time.monotonic() - console.started, 1)}).encode()
                return self._send(200, body, 'application/json', head)
            if url.path == '/favicon.ico':
                return self._send(204, head=True)
            return self._send(404, b'Not found\n', head=head)

    return Handler


def make_logger(directory):
    logger = logging.getLogger('tallyboard')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        handler = RotatingFileHandler(str(Path(directory) / 'requests.log'), maxBytes=1048576, backupCount=3)
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    logger.handlers = [handler]
    return logger


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('--allow-demo', action='store_true', help='Serve labelled sample screens at /?demo=<name>')
    parser.add_argument('--allow-focus', action='store_true', help='Let a tap on the tablet open that session on this computer')
    parser.add_argument('--host', default=os.environ.get('TALLYBOARD_HOST', '0.0.0.0'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('TALLYBOARD_PORT', '5199')))
    parser.add_argument('--state-dir', default=os.environ.get('TALLYBOARD_STATE_DIR', DEFAULT_STATE_DIR))
    args = parser.parse_args(argv)

    state_dir = Path(args.state_dir).expanduser()
    (state_dir / 'agents.d').mkdir(parents=True, exist_ok=True)
    config_path = state_dir / 'config.json'
    collector = Collector(DropinSource(state_dir / 'agents.d', load_config(config_path)),
                          extra=([codex.CodexSource(load_config(config_path))] if codex.enabled(config_path) else []) +
                                ([antigravity.AntigravitySource(load_config(config_path))] if antigravity.enabled(config_path) else []))
    console = Console(collector, config_path, allow_demo=args.allow_demo, allow_focus=args.allow_focus)
    minder = tablet.load(config_path)
    if minder:
        tablet.Tablet(minder, console, args.port, state_dir).start()
    if usage.enabled(config_path):
        console.usage = usage.Usage()
        console.usage.start()
    chime = sound.load(config_path)
    console.chime = bool(chime and chime['where'] == 'tablet')
    if chime and chime['where'] == 'mac':
        sound.Sound(chime, console).start()
    server = BoundedHTTPServer((args.host, args.port), make_handler(console, make_logger(state_dir)))
    server.daemon_threads = True
    print('Tallyboard listening on %s:%d; private LAN clients only' % (args.host, args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
