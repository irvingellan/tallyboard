import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent / 'tallyboard'
sys.path.insert(0, str(APP))

import demo  # noqa: E402
import server  # noqa: E402
from sources import Collector, DropinSource  # noqa: E402
from state import build_view, clean, error_summary, from_dropin, humanize_error, parse_time  # noqa: E402

NOW = 1_800_000_000.0


def work(state, session=None, **extra):
    """A session as the Claude Code hook would report it -> the item the board works with."""
    record = {'agent': 'codex', 'session': session or state, 'project': 'shop', 'title': 'Do the thing', 'state': state,
              'started_at': NOW - 600, 'updated_at': NOW - 60}
    if state == 'blocked':
        record.update(blocked_since=NOW - 60, reason='Asks permission to use Bash', reason_kind='approval')
    if state in ('done', 'failed'):
        record['ended_at'] = extra.pop('ended', NOW - 60)
        record['updated_at'] = record['ended_at']
    record.update(extra)
    return from_dropin(record, NOW)


class StateTest(unittest.TestCase):
    def test_parse_time_accepts_iso_and_epoch(self):
        self.assertAlmostEqual(parse_time('2027-01-15T08:00:00.000Z'), NOW)
        self.assertEqual(parse_time(NOW * 1000), NOW)
        self.assertIsNone(parse_time('soon'))
        self.assertIsNone(parse_time(None))

    def test_clean_removes_paths_controls_and_bounds_length(self):
        self.assertEqual(clean('run\n/home/someone/secret/x.py now'), 'run [local] now')
        self.assertEqual(len(clean('x' * 500, 40)), 40)
        self.assertIsNone(clean('  \n '))

    def test_error_summary_unwraps_nested_engine_json(self):
        raw = '{"type":"error","error":{"message":"{\\"error\\":{\\"message\\":\\"Model not supported.\\"}}"}}'
        self.assertEqual(error_summary(raw), 'Model not supported.')
        self.assertEqual(error_summary('plain failure'), 'plain failure')

    def view(self, *items, **config):
        return build_view(list(items), NOW, config)

    def test_idle_when_nothing_is_live(self):
        view = self.view(work('done', ended=NOW - 4000))
        self.assertEqual((view['mode'], view['focus']), ('idle', None))
        self.assertEqual(view['counts']['done'], 1)
        self.assertEqual([(a['id'], a['state']) for a in view['agents']], [('claude', 'idle'), ('codex', 'idle')])

    def test_blocked_outranks_everything_and_oldest_wait_wins(self):
        view = self.view(work('running'), work('failed'), work('blocked', 'new', blocked_since=NOW - 10),
                         work('blocked', 'old', blocked_since=NOW - 500, reason_kind='input'))
        self.assertEqual(view['mode'], 'blocked')
        self.assertEqual(view['focus']['id'], 'dropin:codex:old')
        self.assertEqual(view['counts'], {'active': 1, 'waiting': 2, 'done': 0, 'failed': 1, 'awaiting': 0, 'projects': 1})
        self.assertEqual([i['state'] for i in view['queue']], ['blocked', 'running'])

    def test_fresh_failure_headlines_over_running_then_yields(self):
        self.assertEqual(self.view(work('running'), work('failed', ended=NOW - 30))['mode'], 'failed')
        self.assertEqual(self.view(work('running'), work('failed', ended=NOW - 400))['mode'], 'running')
        self.assertEqual(self.view(work('failed', ended=NOW - 400))['mode'], 'failed')
        self.assertEqual(self.view(work('failed', ended=NOW - 4000))['mode'], 'idle')

    def test_done_is_temporary_and_announces_its_expiry(self):
        view = self.view(work('done', ended=NOW - 60))
        self.assertEqual(view['mode'], 'done')
        self.assertEqual(view['focus_expires_at'], NOW - 60 + 300)
        self.assertEqual(self.view(work('done', ended=NOW - 301))['mode'], 'idle')

    def test_roster_is_multi_agent_and_includes_unlisted_agents(self):
        items = [work('running'), from_dropin({'agent': 'gemini', 'state': 'blocked', 'updated_at': NOW - 5, 'reason': 'Need input'}, NOW)]
        view = build_view(items, NOW, {'roster': ['claude', 'codex']})
        self.assertEqual([(a['id'], a['state']) for a in view['agents']],
                         [('claude', 'idle'), ('codex', 'running'), ('gemini', 'blocked')])

    def test_rev_ignores_the_clock_but_tracks_content(self):
        a, b = self.view(work('running')), build_view([work('running')], NOW + 5)
        self.assertEqual(a['rev'], b['rev'])
        self.assertNotEqual(a['rev'], self.view(work('running', title='Other'))['rev'])

    def test_dropin_without_heartbeat_expires(self):
        record = {'agent': 'claude', 'session': 's', 'state': 'running', 'started_at': NOW - 9000, 'updated_at': NOW - 3000}
        self.assertIsNone(from_dropin(record, NOW))
        self.assertEqual(from_dropin(dict(record, updated_at=NOW - 30), NOW)['state'], 'running')
        self.assertIsNone(from_dropin({'agent': 'claude', 'state': 'dancing', 'updated_at': NOW}, NOW))

    def test_failure_gets_a_human_headline_and_keeps_the_raw_text_secondary(self):
        raw = "The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account."
        self.assertEqual(humanize_error(raw), ('@err_model:gpt-6.1-sol', raw))
        self.assertEqual(humanize_error('Request failed: 429 Too Many Requests from upstream provider, retry later please')[0], '@err_limit')
        self.assertEqual(humanize_error('connect ECONNREFUSED 127.0.0.1:8787 while calling the engine endpoint for a turn')[0], '@err_network')
        self.assertEqual(humanize_error('boom'), ('boom', None))
        self.assertEqual(humanize_error(None), ('@err_unknown', None))
        self.assertEqual(humanize_error('x' * 100), ('@err_generic', 'x' * 100))
        item = from_dropin({'agent': 'codex', 'state': 'failed', 'updated_at': NOW, 'reason': '{"error":{"message":"%s"}}' % raw}, NOW)
        self.assertEqual((item['reason'], item['reason_raw']), ('@err_model:gpt-6.1-sol', raw))
        own = from_dropin({'agent': 'claude', 'state': 'failed', 'updated_at': NOW, 'summary': 'Testes quebraram', 'reason': 'exit 1'}, NOW)
        self.assertEqual((own['reason'], own['reason_raw']), ('Testes quebraram', 'exit 1'))

    def test_action_required_starts_strong_then_settles_into_ambient(self):
        blocked = lambda seconds, **extra: work('blocked', started_at=NOW - 5000, blocked_since=NOW - seconds, **extra)
        self.assertEqual(self.view(blocked(30))['alert'], 'strong')
        self.assertEqual(self.view(blocked(900))['alert'], 'ambient')
        self.assertEqual(self.view(blocked(900), alert_strong_s=1200)['alert'], 'strong')
        self.assertIsNone(self.view(work('running'))['alert'])
        # anything new happening next to an old wait makes it loud again
        self.assertEqual(self.view(blocked(900), work('running', started_at=NOW - 20))['alert'], 'strong')
        self.assertEqual(self.view(blocked(900), work('done', ended=NOW - 20))['alert'], 'strong')

    def test_a_change_without_a_new_timestamp_still_rearms_the_alert(self):
        memory = {}
        old = work('blocked', 'a', started_at=NOW - 5000, blocked_since=NOW - 900)
        other = work('blocked', 'b', started_at=NOW - 5000, blocked_since=NOW - 800, reason_kind='input')
        build = lambda at, *items: build_view(list(items), at, memory=memory)
        self.assertEqual(build(NOW, old, other)['alert'], 'ambient')
        self.assertEqual(build(NOW + 3, old, other)['alert'], 'ambient')
        self.assertEqual(build(NOW + 6, old)['alert'], 'strong')          # the other request was answered
        self.assertEqual(build(NOW + 100, old)['alert'], 'strong')
        self.assertEqual(build(NOW + 6 + 181, old)['alert'], 'ambient')   # and it settles again
        build(NOW + 200, work('running'))
        self.assertEqual(memory, {})

    def test_every_demo_scenario_builds(self):
        modes = {name: build_view(demo.scenario(name, NOW)[1], NOW)['mode'] for name in demo.SCENARIOS}
        self.assertEqual(modes, {'idle': 'idle', 'running': 'running', 'blocked': 'blocked', 'question': 'blocked', 'ambient': 'blocked',
                                 'waiting': 'idle', 'done': 'done', 'failed': 'failed', 'multi': 'blocked'})
        agenda, usage = demo.extras('idle', NOW)
        started = lambda at: demo.scenario('running', at)[1][0]['started_at']
        self.assertEqual(started(NOW + 1), started(NOW + 30))  # pinned to the minute: the timer ticks instead of snapping back
        self.assertEqual((len(agenda['events']), len(usage['windows'])), (3, 3))


class SourcesTest(unittest.TestCase):
    def test_dropin_directory_ignores_garbage_and_oversized_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'ok.json').write_text(json.dumps({'agent': 'claude', 'state': 'running', 'updated_at': NOW}))
            (root / 'bad.json').write_text('{not json')
            (root / 'big.json').write_text(json.dumps({'agent': 'x', 'state': 'running', 'updated_at': NOW, 'pad': 'x' * 20000}))
            (root / 'note.txt').write_text('ignored')
            self.assertEqual([i['agent'] for i in DropinSource(root).read(NOW)], ['claude'])
        self.assertEqual(DropinSource(root).read(NOW), [])

    def test_collector_merges_sources(self):
        class Fixed:
            def __init__(self, value): self.value = value
            def read(self): return self.value
        self.assertEqual(Collector(Fixed(['a']), extra=[Fixed(['b'])]).snapshot(), ['a', 'b'])


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Empty:
            def snapshot(self): return []
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.make_handler(server.Console(Empty(), allow_demo=True), server.make_logger('/nonexistent')))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path, method='GET', headers=None):
        request = urllib.request.Request('http://127.0.0.1:%d%s' % (self.port, path), method=method, headers=headers or {})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def test_serves_the_console_and_its_assets(self):
        status, headers, body = self.get('/')
        self.assertEqual(status, 200)
        self.assertIn(b'/console.js', body)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("default-src 'self'", headers['Content-Security-Policy'])
        self.assertEqual(self.get('/console.css')[0], 200)
        self.assertEqual(self.get('/console.js')[0], 200)

    def test_state_is_idle_without_sources(self):
        view = json.loads(self.get('/api/state')[2])
        self.assertEqual((view['v'], view['mode'], view['demo']), (1, 'idle', None))
        self.assertTrue(view['build'])
        self.assertIn('tz_offset_min', view)

    def test_demo_scenarios_are_labelled_and_bring_sample_extras(self):
        view = json.loads(self.get('/api/state?demo=blocked')[2])
        self.assertEqual((view['mode'], view['demo']), ('blocked', 'blocked'))
        self.assertEqual((len(view['agenda']['events']), view['usage']['windows'][0]['label']), (3, '@u_5h'))

    def test_status_probe_answers(self):
        self.assertIn('uptime_seconds', json.loads(self.get('/status')[2]))

    def test_read_only_and_closed_by_default(self):
        for method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            self.assertEqual(self.get('/api/state', method=method)[0], 405, method)
        self.assertEqual(self.get('/static/../server.py')[0], 404)
        self.assertEqual(self.get('/server.py')[0], 404)
        self.assertEqual(self.get('/', headers={'Host': 'evil.example.com'})[0], 403)

    def test_only_private_ipv4_clients_and_hosts(self):
        self.assertTrue(server.is_private('192.168.0.132'))
        self.assertTrue(server.is_private('::ffff:10.0.0.4'))
        for outside in ('8.8.8.8', '2001:db8::1', 'not-an-ip'):
            self.assertFalse(server.is_private(outside))
        self.assertTrue(server.host_allowed('192.168.0.20:5199'))
        self.assertTrue(server.host_allowed('my-laptop.local:5199'))
        self.assertFalse(server.host_allowed(None))

    def test_broken_config_never_takes_the_display_down(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text('{oops')
            self.assertEqual(server.load_config(path), {})
            path.write_text(json.dumps({'done_ttl': 60, 'surprise': 1}))
            self.assertEqual(server.load_config(path), {'done_ttl': 60})


class TabletTest(unittest.TestCase):
    """The minder drives ADB; here ADB is a script of canned answers."""

    def make(self, answers, view=None, seen=None):
        import tablet
        calls = []

        class Done:
            def __init__(self, out, code=0): self.stdout, self.returncode = out, code

        def run(command, **_):
            args = command[1:]
            calls.append(args)
            for prefix, out in answers:
                if args[:len(prefix)] == prefix:
                    return Done(out)
            return Done('', 1)

        class FakeConsole:
            tablet_seen = seen
            def state(self): return view or {'mode': 'idle', 'alert': None}

        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder) / 'config.json'
            cfg.write_text(json.dumps({'tablet': {'serial': 'G000TEST01', 'recover_after_s': 60}}))
            minder = tablet.Tablet(tablet.load(cfg), FakeConsole(), 5199, folder, run=run, clock=lambda: 1000.0)
        minder.adb_path = 'adb'
        minder.mac_address_for = lambda transport: '192.168.0.9'
        return minder, calls

    WIFI = [(['devices'], 'List of devices attached\n192.168.0.50:5555\tdevice\nother:5555\tdevice\nPHONE1\tdevice'),
            (['-s', '192.168.0.50:5555', 'shell', 'getprop'], 'G000TEST01')]

    def test_config_must_name_one_valid_device(self):
        import tablet
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            for bad in ({}, {'tablet': {}}, {'tablet': {'serial': 'x; reboot'}}, {'tablet': 'G000TEST01'}):
                path.write_text(json.dumps(bad))
                self.assertIsNone(tablet.load(path), bad)
            path.write_text(json.dumps({'tablet': {'serial': 'G000TEST01', 'brightness': {'idle': 30, 'blocked': 999, 'nope': 5}}}))
            loaded = tablet.load(path)
            self.assertEqual((loaded['levels']['idle'], loaded['levels']['blocked'], loaded['package']), (30, 255, 'de.ozerov.fully'))

    def test_backlight_follows_the_screen(self):
        import tablet
        levels = tablet.DEFAULT_LEVELS
        self.assertEqual(tablet.level_for({'mode': 'idle'}, levels, 14), levels['idle'])
        self.assertEqual(tablet.level_for({'mode': 'idle'}, levels, 2), levels['night'])
        self.assertEqual(tablet.level_for({'mode': 'blocked', 'alert': 'strong'}, levels, 2), levels['blocked'])
        self.assertEqual(tablet.level_for({'mode': 'blocked', 'alert': 'ambient'}, levels, 14), levels['ambient'])
        self.assertEqual(tablet.level_for({'mode': 'running'}, levels, 14), levels['active'])

    def test_only_the_configured_tablet_is_touched_and_a_silent_one_is_brought_back(self):
        minder, calls = self.make(self.WIFI + [(['-s', '192.168.0.50:5555', 'shell', 'settings'], '')], seen=900.0)
        result = minder.step(hour=14)
        self.assertIn('brightness=170', result)
        self.assertIn('recover=http://192.168.0.9:5199/', result)
        self.assertTrue(all(c[:2] != ['-s', 'PHONE1'] and c[:2] != ['-s', 'other:5555'] or c[2:4] == ['shell', 'getprop'] for c in calls))
        self.assertFalse(any(c[:2] == ['-s', 'PHONE1'] for c in calls))
        start = [c for c in calls if 'am' in c][0]
        self.assertEqual(start[-6:], ['-n', 'de.ozerov.fully/.MainActivity', '-a', 'android.intent.action.VIEW', '-d', 'http://192.168.0.9:5199/'])

    def test_a_tablet_that_left_the_kiosk_is_brought_back_after_a_grace_period(self):
        import tablet
        away = self.WIFI + [(['-s', '192.168.0.50:5555', 'shell', 'settings'], ''),
                            (['-s', '192.168.0.50:5555', 'shell', 'dumpsys'], '  mCurrentFocus=Window{1 u0 com.launcher/com.launcher.Home}')]
        now = [1000.0]
        minder, calls = self.make(away, seen=1000.0)
        minder.clock = lambda: now[0]
        minder.console.tablet_seen = 1000.0
        self.assertNotIn('recover', minder.step(hour=14))      # just left: maybe someone is using the tablet
        now[0] = 1070.0
        minder.console.tablet_seen = 1069.0                     # still polling from the background
        self.assertIn('recover=http://192.168.0.9:5199/', minder.step(hour=14))
        home, calls = self.make(self.WIFI + [(['-s', '192.168.0.50:5555', 'shell', 'settings'], ''),
                                             (['-s', '192.168.0.50:5555', 'shell', 'dumpsys'], '  mCurrentFocus=Window{1 u0 de.ozerov.fully/de.ozerov.fully.FullyActivity}')], seen=995.0)
        home.step(hour=14)
        self.assertIsNone(home.away_since)

    def test_a_silent_kiosk_is_reloaded_fast_then_restarted_and_refreshed_nightly(self):
        front = self.WIFI + [(['-s', '192.168.0.50:5555', 'shell', 'settings'], ''),
                             (['-s', '192.168.0.50:5555', 'shell', 'dumpsys'], '  mCurrentFocus=Window{1 u0 de.ozerov.fully/de.ozerov.fully.FullyActivity}')]
        now = [1000.0]
        minder, calls = self.make(front, seen=990.0)
        minder.clock = lambda: now[0]
        self.assertNotIn('recover', minder.step(hour=14))       # 10 s of silence is just a slow poll
        results = []
        for _ in range(3):                                      # silent for good: an error page never retries
            now[0] += 45
            results.append(minder.step(hour=14))
        self.assertTrue(all('recover=' in r for r in results))
        self.assertEqual(['restart' in r for r in results], [False, False, True])
        self.assertIn(['-s', '192.168.0.50:5555', 'shell', 'am', 'force-stop', 'de.ozerov.fully'], calls)
        minder.console.tablet_seen = now[0]                     # healthy again
        self.assertNotIn('recover', minder.step(hour=14))
        self.assertIn('recover=', minder.step(hour=5))          # hygiene reload, once a night
        self.assertNotIn('recover', minder.step(hour=5))

    def test_a_polling_tablet_is_left_alone_and_an_unreachable_one_is_harmless(self):
        minder, calls = self.make(self.WIFI + [(['-s', '192.168.0.50:5555', 'shell', 'settings'], '')], seen=990.0)
        self.assertEqual(minder.step(hour=14), 'brightness=170')
        self.assertEqual(minder.step(hour=14), 'ok')
        self.assertFalse(any('am' in c for c in calls))
        gone, calls = self.make([(['devices'], 'List of devices attached\n')])
        self.assertEqual(gone.step(hour=14), 'unreachable')
        self.assertTrue(all(c[0] in ('devices', 'connect') for c in calls))


class HookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('claude_code_hook', str(APP / 'hooks' / 'claude_code_hook.py'))
        cls.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.hook)

    def test_claude_session_lifecycle(self):
        event = lambda name, **extra: dict({'hook_event_name': name, 'session_id': 's1', 'cwd': str(HERE)}, **extra)
        record = self.hook.apply(event('UserPromptSubmit', prompt='Build the console\nmore'), None, NOW)
        self.assertEqual((record['state'], record['title'], record['agent']), ('running', 'Build the console', 'claude'))
        record = self.hook.apply(event('Notification', notification_type='permission_prompt', message='Claude needs your permission to use Bash'), record, NOW + 5)
        self.assertEqual((record['state'], record['blocked_since']), ('blocked', NOW + 5))
        record = self.hook.apply(event('PostToolUse'), record, NOW + 9)
        self.assertEqual(record['state'], 'running')
        record = self.hook.apply(event('Stop'), record, NOW + 20)
        self.assertEqual((record['state'], record['ended_at']), ('done', NOW + 20))
        self.assertEqual(self.hook.apply(event('Notification', message='waiting for input'), record, NOW + 90)['state'], 'done')
        self.assertEqual(from_dropin(record, NOW + 21)['duration_s'], 20)
        self.assertIsNone(self.hook.apply(event('SessionEnd'), record, NOW + 99))

    def test_claude_waits_are_reported_from_every_signal_it_may_send(self):
        event = lambda name, **extra: dict({'hook_event_name': name, 'session_id': 's2', 'cwd': str(HERE)}, **extra)
        running = self.hook.apply(event('UserPromptSubmit', prompt='Go'), None, NOW)
        asked = self.hook.apply(event('PermissionRequest', tool_name='Bash'), running, NOW + 3)
        self.assertEqual((asked['state'], asked['reason'], asked['reason_kind']), ('blocked', '@permission:Bash', 'approval'))
        again = self.hook.apply(event('Notification', notification_type='permission_prompt', message='Claude needs your permission to use Bash'), asked, NOW + 4)
        self.assertEqual(again['blocked_since'], NOW + 3)
        question = self.hook.apply(event('PreToolUse', tool_name='AskUserQuestion'), running, NOW + 3)
        self.assertEqual((question['state'], question['reason_kind']), ('blocked', 'input'))
        self.assertEqual(self.hook.apply(event('PreToolUse', tool_name='Bash'), running, NOW + 3)['state'], 'running')
        self.assertEqual(self.hook.apply(event('PostToolUse', tool_name='AskUserQuestion'), question, NOW + 9)['state'], 'running')
        self.assertIsNone(self.hook.apply(event('PermissionRequest', tool_name='Bash'), None, NOW))

    def test_hook_says_what_the_session_is_doing_without_leaking_commands(self):
        event = lambda name, **extra: dict({'hook_event_name': name, 'session_id': 's3', 'cwd': str(HERE)}, **extra)
        running = self.hook.apply(event('UserPromptSubmit', prompt='Go'), None, NOW)
        self.assertEqual(running['detail'], '@thinking')
        doing = lambda tool, **given: self.hook.apply(event('PreToolUse', tool_name=tool, tool_input=given), running, NOW + 1)['detail']
        self.assertEqual(doing('Bash', command='curl -H "Authorization: secret" x', description='Run the  tests'), 'Run the tests')
        self.assertEqual(doing('Bash', command='rm x'), '@command')
        self.assertEqual(doing('Edit', file_path='/home/x/private/state.py'), '@editing:state.py')
        self.assertEqual(doing('Read', file_path='/a/b.md'), '@reading:b.md')
        self.assertEqual(doing('mcp__Claude_Browser__navigate'), '@browser')
        self.assertEqual(doing('mcp__d06d04ad-389a-4dcd-b114-7100dcaf6f86__reply'), '@connector')
        self.assertEqual(doing('SomethingNew'), '@thinking')
        asked = self.hook.apply(event('PermissionRequest', tool_name='Bash'), running, NOW + 2)
        self.assertEqual(self.hook.apply(event('PreToolUse', tool_name='Read', tool_input={}), asked, NOW + 3)['state'], 'running')
        self.assertIsNone(self.hook.apply(event('Stop'), running, NOW + 9)['detail'])
        # seen live: a question fires PreToolUse, then PermissionRequest, then a permission_prompt notice
        question = self.hook.apply(event('PreToolUse', tool_name='AskUserQuestion'), running, NOW + 3)
        question = self.hook.apply(event('PermissionRequest', tool_name='AskUserQuestion'), question, NOW + 3)
        question = self.hook.apply(event('Notification', notification_type='permission_prompt', message='Claude needs your permission to use AskUserQuestion'), question, NOW + 9)
        self.assertEqual((question['reason_kind'], question['reason'], question['blocked_since']), ('input', '@question', NOW + 3))

    def test_the_board_lists_the_agents_it_is_wired_to(self):
        self.assertEqual(server.Console(Collector(DropinSource('/nonexistent'))).state()['mode'], 'idle')
        idle = build_view([], NOW, {'roster': ['claude'], 'available_agents': ['claude']})
        self.assertEqual([(a['id'], a['available']) for a in idle['agents']], [('claude', True)])

    def test_finished_claude_turns_are_listed_as_your_turn_until_answered(self):
        app = 'local_d1bfe26a-6531-4d1d-b507-09dc7ba9bf93'
        record = {'agent': 'claude', 'session': 's9', 'state': 'done', 'awaiting': True, 'project': 'p', 'title': 'last prompt',
                  'session_title': 'My session', 'app_session': app, 'started_at': NOW - 900, 'updated_at': NOW - 600, 'ended_at': NOW - 600}
        item = from_dropin(record, NOW)
        self.assertEqual((item['awaiting'], item['touch'], item['session_title']), (True, True, 'My session'))
        view = build_view([item], NOW)
        self.assertEqual((view['mode'], len(view['awaiting']), view['recent'], view['counts']['awaiting']), ('idle', 1, [], 1))
        fresh = build_view([from_dropin(dict(record, ended_at=NOW - 30, updated_at=NOW - 30), NOW)], NOW)
        self.assertEqual((fresh['mode'], fresh['awaiting']), ('done', []))  # still the green headline, not listed twice
        self.assertEqual(build_view([from_dropin(dict(record, ended_at=NOW - 30000, updated_at=NOW - 30000), NOW)], NOW)['awaiting'], [])
        self.assertFalse(from_dropin(dict(record, app_session='local_x; rm -rf /'), NOW)['touch'])
        self.assertFalse(from_dropin(dict(record, awaiting='yes'), NOW)['awaiting'])

    def test_a_tap_can_only_open_a_session_the_agent_reported(self):
        app = 'local_d1bfe26a-6531-4d1d-b507-09dc7ba9bf93'
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'a.json').write_text(json.dumps({'agent': 'claude', 'session': 's9', 'state': 'running', 'app_session': app,
                                                             'updated_at': __import__('time').time()}))
            opened = []
            console = server.Console(Collector(DropinSource(folder)), allow_focus=True, opener=opened.append)
            self.assertTrue(console.focus('dropin:claude:s9'))
            self.assertFalse(console.focus('dropin:claude:other'))
            self.assertFalse(console.focus(app))
            self.assertEqual(opened, ['claude://claude.ai/epitaxy/' + app])
            off = server.Console(Collector(DropinSource(folder)), opener=opened.append)
            self.assertFalse(off.focus('dropin:claude:s9'))
            self.assertEqual(len(opened), 1)

    def test_a_hold_waves_a_waiting_session_away_until_its_next_turn(self):
        import time as clock
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.json'
            ended = clock.time() - 600
            write = lambda at: path.write_text(json.dumps({'agent': 'claude', 'session': 's9', 'state': 'done', 'awaiting': True,
                                                          'started_at': at - 60, 'ended_at': at, 'updated_at': at}))
            write(ended)
            make = lambda **kw: server.Console(Collector(DropinSource(folder), min_interval=0), **kw)
            console = make(allow_focus=True)
            self.assertEqual(len(console.state()['awaiting']), 1)
            self.assertFalse(console.dismiss('dropin:claude:other'))
            self.assertTrue(console.dismiss('dropin:claude:s9'))
            self.assertEqual(console.state()['awaiting'], [])
            write(ended + 300)  # the session spoke again: it is the person's turn again
            self.assertEqual(len(console.state()['awaiting']), 1)
            self.assertFalse(make().dismiss('dropin:claude:s9'))

    def test_hook_marks_your_turn_and_finds_the_desktop_session(self):
        event = lambda name, **extra: dict({'hook_event_name': name, 'session_id': 'cli-1', 'cwd': str(HERE)}, **extra)
        done = self.hook.apply(event('Stop'), self.hook.apply(event('UserPromptSubmit', prompt='Go'), None, NOW), NOW + 5)
        self.assertTrue(done['awaiting'])
        self.assertFalse(self.hook.apply(event('UserPromptSubmit', prompt='Again'), done, NOW + 9)['awaiting'])
        noticed = self.hook.apply(event('UserPromptSubmit', prompt='<task-notification>\n<status>done</status>'), self.hook.apply(event('UserPromptSubmit', prompt='Real ask'), None, NOW), NOW + 50)
        self.assertEqual((noticed['title'], noticed['started_at'], noticed['state']), ('Real ask', NOW, 'running'))
        self.assertEqual(self.hook.apply(event('UserPromptSubmit', prompt='<pasted_content id="1">\nx\n</pasted_content>\nFaça isso'), None, NOW)['title'], 'Faça isso')
        self.assertEqual(self.hook.apply(event('UserPromptSubmit', prompt='<!-- reply -->\n> citação da resposta anterior\n\ntestei e funcionou'), None, NOW)['title'], 'testei e funcionou')
        with tempfile.TemporaryDirectory() as folder:
            nested = Path(folder) / 'a' / 'b'
            nested.mkdir(parents=True)
            (nested / 'local_1.json').write_text(json.dumps({'sessionId': 'local_1', 'cliSessionId': 'cli-1', 'title': 'Sidebar name'}))
            (nested / 'local_2.json').write_text(json.dumps({'sessionId': 'local_2', 'cliSessionId': 'cli-2', 'note': 'mentions cli-1'}))
            self.assertEqual(self.hook.desktop_session('cli-1', Path(folder)), ('local_1', 'Sidebar name'))
            self.assertEqual(self.hook.desktop_session('cli-9', Path(folder)), (None, None))


class UsageTest(unittest.TestCase):
    SAMPLE = json.dumps([{'provider': 'claude', 'usage': {
        'accountEmail': 'someone@example.com',
        'primary': {'usedPercent': 50, 'windowMinutes': 300, 'resetsAt': '2026-11-20T02:10:00Z'},
        'secondary': {'usedPercent': 24.4, 'resetsAt': '2026-11-25T04:00:00Z'},
        'extraRateWindows': [{'id': 'claude-weekly-scoped-fable', 'window': {'usedPercent': 39, 'resetsAt': 'soon'}}]}}])

    def test_keeps_three_numbers_and_no_identity(self):
        import usage
        windows = usage.parse(self.SAMPLE)
        self.assertEqual([(w['label'], w['used']) for w in windows], [('@u_5h', 50), ('@u_week', 24), ('Fable', 39)])
        self.assertEqual((windows[0]['resets_at'], windows[2]['resets_at']), (1795140600, None))
        self.assertNotIn('example.com', json.dumps(windows))
        for junk in ('', 'not json', '{}', '[{"provider":"codex","usage":{}}]', '[{"provider":"claude","usage":{"primary":{"usedPercent":"9"}}}]'):
            self.assertEqual(usage.parse(junk), [])

    def test_stale_or_failed_reads_show_nothing(self):
        import usage
        now = [1000.0]

        class Done:
            def __init__(self, out, code=0): self.stdout, self.returncode = out, code

        answers = [Done(self.SAMPLE), Done('', 1)]
        meter = usage.Usage(run=lambda *a, **k: answers.pop(0), clock=lambda: now[0])
        meter.cli = '/bin/echo'
        self.assertIsNone(meter.view())
        self.assertTrue(meter.refresh())
        self.assertFalse(meter.refresh())  # a failed read keeps the last good numbers...
        self.assertEqual(len(meter.view()['windows']), 3)
        now[0] += usage.STALE_S + 1        # ...but not forever
        self.assertIsNone(meter.view())


class CodexTest(unittest.TestCase):
    def make(self, folder, rows, logs):
        import codex, sqlite3
        home = Path(folder)
        link = sqlite3.connect(str(home / 'state_5.sqlite'))
        link.execute('create table threads (id, rollout_path, updated_at, source, cwd, title, name, git_branch, archived, attached_thread_parent_id)')
        for ident, source, archived, parent in rows:
            path = home / (ident + '.jsonl')
            path.write_text(logs.get(ident, ''))
            os.utime(str(path), (NOW - 5, NOW - 5))
            link.execute('insert into threads values (?,?,?,?,?,?,?,?,?,?)',
                         (ident, str(path), int(NOW), source, '/home/x/proj-' + ident, 'Faça isso\nsegredo na segunda linha', 'Nome ' + ident, 'main', archived, parent))
        link.commit(); link.close()
        return codex.CodexSource(home=home)

    def test_reads_turn_markers_and_only_people_get_a_turn(self):
        line = lambda kind, **extra: json.dumps({'type': 'event_msg', 'payload': dict({'type': kind}, **extra)}) + '\n'
        logs = {'run': line('task_complete', completed_at=NOW - 500) + line('task_started', started_at=str(NOW - 60)),
                'mine': line('task_started', started_at=NOW - 900) + 'not json task_complete"\n' + line('task_complete', completed_at=str(NOW - 300)),
                'bot': line('task_complete', completed_at=NOW - 300), 'botrun': line('task_started', started_at=NOW - 30),
                'old': line('task_complete', completed_at=NOW - 300), 'kid': line('task_started', started_at=NOW - 30)}
        with tempfile.TemporaryDirectory() as folder:
            source = self.make(folder, [('run', 'vscode', 0, None), ('mine', 'cli', 0, None), ('bot', 'exec', 0, None),
                                        ('botrun', 'exec', 0, None), ('old', 'cli', 1, None), ('kid', 'vscode', 0, 'run')], logs)
            items = {i['id'].split(':')[-1]: i for i in source.read(NOW)}
            self.assertEqual(sorted(items), ['botrun', 'mine', 'run'])
            self.assertEqual((items['run']['state'], items['run']['started_at'], items['run']['agent']), ('running', NOW - 60, 'codex'))
            self.assertEqual((items['mine']['state'], items['mine']['awaiting'], items['mine']['ended_at']), ('done', True, NOW - 300))
            self.assertEqual((items['mine']['session_title'], items['mine']['project'], items['mine']['title']), ('Nome mine', 'proj-mine', 'Faça isso'))
            self.assertFalse(items['mine']['touch'])
        with tempfile.TemporaryDirectory() as empty:
            import codex
            self.assertEqual(codex.CodexSource(home=empty).read(NOW), [])


class AgendaTest(unittest.TestCase):
    def test_next_timed_events_only_and_nothing_when_stale(self):
        import agenda
        from datetime import datetime, timezone
        iso = lambda offset: datetime.fromtimestamp(NOW + offset, timezone.utc).isoformat()
        events = [{'title': 'Depois', 'start': iso(7200), 'end': iso(9000)}, {'title': '  Em   andamento ', 'start': iso(-600), 'end': iso(600)},
                  {'title': 'Já acabou', 'start': iso(-7200), 'end': iso(-3600)}, {'title': 'Aniversário', 'start': '2026-11-27', 'end': '2026-11-28'},
                  {'title': 'Sem fuso', 'start': '2026-11-27T10:00:00'}, {'title': 'Longe', 'start': iso(9 * 86400)}, {'title': 5, 'start': iso(60)}, 'x']
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'agenda.json'
            self.assertIsNone(agenda.view(path, NOW))
            path.write_text(json.dumps({'updated_at': NOW - 60, 'events': events}))
            self.assertEqual(agenda.view(path, NOW), {'events': [{'title': 'Em andamento', 'start': NOW - 600}, {'title': 'Depois', 'start': NOW + 7200}]})
            self.assertIsNone(agenda.view(path, NOW + agenda.STALE_S + 120))
            for junk in ('[]', '{"events": 3}', 'nope', '{"updated_at": true, "events": []}'):
                path.write_text(junk)
                self.assertIsNone(agenda.view(path, NOW))


class AntigravityTest(unittest.TestCase):
    def test_status_mapping_and_a_failed_read_keeps_the_last_answer(self):
        import antigravity, sqlite3
        stamp = lambda offset: time_text(NOW + offset)
        import time as clock
        time_text = lambda at: clock.strftime('%Y-%m-%d %H:%M:%S', clock.gmtime(at)) + '.50286+00:00'
        self.assertEqual(antigravity.epoch(time_text(NOW)), float(int(NOW)))
        self.assertIsNone(antigravity.epoch('0001-01-01 00:00:00+00:00'))
        self.assertIsNone(antigravity.epoch('soon'))
        rows = [('run', 'Rodando', 'CASCADE_RUN_STATUS_RUNNING', stamp(-5), stamp(-90), '["file:///home/x/My%20App"]', '', '', '', 0),
                ('wait', 'Esperando', 'CASCADE_RUN_STATUS_WAITING_FOR_USER', stamp(-40), stamp(-90), '[]', '', '', '', 0),
                ('mine', 'Terminou', 'CASCADE_RUN_STATUS_IDLE', stamp(-300), stamp(-900), 'x', '', '', '', 0),
                ('cli', '', 'CASCADE_RUN_STATUS_IDLE', stamp(-300), stamp(-900), '[]', 'CORTEX_TRAJECTORY_SOURCE_CLI', '', '', 0),
                ('never', '', 'CASCADE_RUN_STATUS_IDLE', stamp(-300), '0001-01-01 00:00:00+00:00', '[]', '', '', '', 0),
                ('new', 'Valor novo', 'CASCADE_RUN_STATUS_SOMETHING_ELSE', stamp(-5), stamp(-9), '[]', '', '', '', 0),
                ('old', 'Velho', 'CASCADE_RUN_STATUS_IDLE', stamp(-9 * 3600), stamp(-9 * 3600), '[]', '', '', '', 0),
                ('kid', 'Filho', 'CASCADE_RUN_STATUS_RUNNING', stamp(-5), stamp(-9), '[]', '', 'run', '', 0),
                ('sub', 'Navegador', 'CASCADE_RUN_STATUS_RUNNING', stamp(-5), stamp(-9), '[]', '', '', 'browser', 0),
                ('dead', 'Morto', 'CASCADE_RUN_STATUS_RUNNING', stamp(-5), stamp(-9), '[]', '', '', '', 1)]
        with tempfile.TemporaryDirectory() as folder:
            link = sqlite3.connect(str(Path(folder) / 'conversation_summaries.db'))
            link.execute('create table conversation_summaries (conversation_id, title, status, last_modified_time, last_user_input_time, workspace_uris, source, parent_conversation_id, agent_name, killed)')
            link.executemany('insert into conversation_summaries values (?,?,?,?,?,?,?,?,?,?)', rows)
            link.commit(); link.close()
            source = antigravity.AntigravitySource(home=folder)
            items = {i['id'].split(':')[-1]: i for i in source.read(NOW)}
            self.assertEqual(sorted(items), ['mine', 'run', 'wait'])
            self.assertEqual((items['run']['state'], items['run']['agent'], items['run']['project'], items['run']['session_title']), ('running', 'gemini', 'My App', 'Rodando'))
            self.assertEqual((items['wait']['state'], items['wait']['reason_kind']), ('blocked', 'input'))
            self.assertEqual((items['mine']['state'], items['mine']['awaiting'], items['mine']['ended_at']), ('done', True, float(int(NOW - 300))))

            class Flaky:
                calls = 0
                def read(self):
                    Flaky.calls += 1
                    if Flaky.calls == 2:
                        raise sqlite3.OperationalError('database is locked')
                    return [{'id': 'kept'}] if Flaky.calls == 1 else []
            collector = Collector(DropinSource(folder), min_interval=0, extra=[Flaky()])
            self.assertEqual([[i['id'] for i in collector.snapshot()] for _ in range(3)], [['kept'], ['kept'], []])
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(antigravity.AntigravitySource(home=empty).read(NOW), [])


class SoundTest(unittest.TestCase):
    def make(self, views, config=None):
        import sound
        played = []

        class FakeConsole:
            def state(self): return views.pop(0)

        return sound.Sound(config or {'quiet': (23, 7)}, FakeConsole(), popen=lambda cmd, **_: played.append(cmd)), played

    def item(self, ident, state):
        return {'id': ident, 'state': state}

    def test_first_snapshot_is_silent_then_new_needs_ring_once(self):
        done = {'focus': self.item('a', 'done')}
        chime, played = self.make([done, done, {'focus': self.item('b', 'blocked'), 'awaiting': [self.item('a', 'done')]},
                                   {'focus': self.item('b', 'running'), 'recent': [self.item('c', 'done')]}])
        self.assertEqual([chime.step(hour=12) for _ in range(4)], [None, None, 'blocked', 'turn'])
        self.assertEqual([cmd[0] for cmd in played], ['/usr/bin/afplay'] * 2)
        self.assertTrue(played[0][1].endswith('Funk.aiff') and played[1][1].endswith('Glass.aiff'))

    def test_quiet_hours_and_config(self):
        import sound
        chime, played = self.make([{}, {'focus': self.item('a', 'done')}])
        self.assertEqual([chime.step(hour=2), chime.step(hour=2)], [None, None])
        self.assertEqual(played, [])
        self.assertTrue(sound.is_quiet(23, (23, 7)) and sound.is_quiet(6, (23, 7)) and not sound.is_quiet(7, (23, 7)))
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder) / 'config.json'
            cfg.write_text(json.dumps({'sound': False}))
            self.assertIsNone(sound.load(cfg))
            cfg.write_text(json.dumps({'sound': {'quiet_hours': [22, 8]}}))
            self.assertEqual(sound.load(cfg), {'quiet': (22, 8), 'where': 'tablet'})
            cfg.write_text(json.dumps({'sound': {'where': 'mac'}}))
            self.assertEqual(sound.load(cfg), {'quiet': (23, 7), 'where': 'mac'})


if __name__ == '__main__':
    unittest.main()
