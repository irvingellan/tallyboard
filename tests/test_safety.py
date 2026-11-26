"""What the board must never do: show secrets, crash on bad input, or serve samples unasked."""
import json
import math
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / 'tallyboard'
sys.path.insert(0, str(APP))
import server  # noqa: E402
from sources import DropinSource  # noqa: E402
from state import build_view, clean, from_dropin, parse_time  # noqa: E402

NOW = 1791230000


class SafetyTest(unittest.TestCase):
    def test_credentials_and_local_paths_are_redacted_from_every_displayed_string(self):
        secrets = ['sk-abcdefghijk123456', 'ghp_abcdefghijk123456', 'hiddenvalue', 'userinfo:pass']
        text = ('sk-abcdefghijk123456 ghp_abcdefghijk123456 API_KEY=hiddenvalue Authorization: Bearer hiddenvalue '
                'https://userinfo:pass@host/a /etc/private.conf')
        result = clean(text, 1000)
        for secret in secrets:
            self.assertNotIn(secret, result)
        self.assertNotIn('/etc/private', result)
        self.assertIn('[redacted]', result)
        for state in ('running', 'blocked', 'failed', 'done'):
            item = from_dropin({'agent': 'claude', 'session': 's', 'state': state, 'updated_at': NOW, 'title': text, 'detail': text,
                                'reason': text, 'summary': text, 'project': text, 'branch': text, 'session_title': text}, NOW)
            shown = json.dumps(build_view([item], NOW))
            for secret in secrets:
                self.assertNotIn(secret, shown, state)
            self.assertNotIn('/etc/private', shown, state)

    def test_nonfinite_and_negative_clocks_are_missing(self):
        for value in (math.nan, math.inf, -1, True, [], {}):
            self.assertIsNone(parse_time(value))

    def test_bad_fields_and_config_never_crash(self):
        for bad in ('bad', [], {}, None, math.nan):
            item = from_dropin({'agent': 'claude', 'state': 'running', 'updated_at': NOW,
                                'checks': {'passed': bad, 'failed': bad, 'total': bad}, 'title': bad, 'detail': bad}, NOW)
            self.assertIsNone(item['checks'])
            self.assertEqual(build_view([item], NOW, {'done_ttl': bad, 'roster': bad})['mode'], 'running')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps({'done_ttl': 'oops', 'brightness': {'idle': 'oops', 'blocked': 255}}))
            self.assertEqual(server.load_config(path)['done_ttl'], 300)
            self.assertEqual(server.load_config(path)['brightness'], {'blocked': 255})

    def test_one_bad_file_does_not_hide_good_sessions_and_links_are_not_followed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'bad.json').write_text(json.dumps({'state': 'running', 'updated_at': NOW, 'checks': {'passed': 'bad'}}))
            (root / 'ok.json').write_text(json.dumps({'state': 'running', 'agent': 'claude', 'updated_at': NOW}))
            (root / 'link.json').symlink_to(root / 'ok.json')
            self.assertEqual(len(DropinSource(root).read(NOW)), 2)

    def test_samples_are_refused_unless_asked_for_and_writes_need_the_page_header(self):
        class Empty:
            def snapshot(self): return []
        httpd = server.BoundedHTTPServer(('127.0.0.1', 0), server.make_handler(server.Console(Empty()), server.make_logger('/nonexistent')))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = 'http://127.0.0.1:%d' % httpd.server_address[1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def status(path, method='GET', headers=None):
            try:
                with opener.open(urllib.request.Request(base + path, method=method, headers=headers or {}), timeout=5) as answer:
                    return answer.status
            except urllib.error.HTTPError as error:
                error.close()
                return error.code
        try:
            self.assertEqual(status('/api/state?demo=running'), 403)
            self.assertEqual(status('/api/state'), 200)
            for path in ('/api/focus?id=x', '/api/dismiss?id=x'):   # taps are off unless the server was started with --allow-focus
                self.assertEqual(status(path, 'POST', {'X-Tallyboard': '1'}), 405)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == '__main__':
    unittest.main()
