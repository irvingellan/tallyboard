import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import install  # noqa: E402

THEIRS = {'hooks': [{'type': 'command', 'command': 'say done'}]}


class InstallTest(unittest.TestCase):
    def test_hooks_are_added_once_beside_existing_ones_and_removed_alone(self):
        before = {'model': 'x', 'hooks': {'Stop': [THEIRS], 'PreToolUse': [{'matcher': 'Bash', 'hooks': THEIRS['hooks']}]}}
        frozen = json.dumps(before, sort_keys=True)
        layout = install.Layout('/home/someone')
        once = install.with_hooks(before, layout.hook_command('/usr/bin/python3'))
        twice = install.with_hooks(once, layout.hook_command('/usr/bin/python3'))
        self.assertEqual(once, twice)
        self.assertEqual(json.dumps(before, sort_keys=True), frozen)
        self.assertEqual(sorted(once['hooks']), sorted(install.EVENTS))
        self.assertEqual(once['hooks']['Stop'][0], THEIRS)
        self.assertEqual(len(once['hooks']['Stop']), 2)
        self.assertEqual(once['hooks']['PreToolUse'][0]['matcher'], 'Bash')
        self.assertNotIn('matcher', once['hooks']['PreToolUse'][1])
        self.assertEqual(install.without_hooks(once), before)
        self.assertEqual(install.without_hooks(install.with_hooks({}, 'x ' + install.MARK)), {})
        with self.assertRaises(ValueError):
            install.with_hooks({'hooks': []}, 'x')

    def test_install_and_uninstall_stay_inside_the_given_home(self):
        with tempfile.TemporaryDirectory() as home:
            layout = install.Layout(home, 'local.tallyboard.test')
            layout.settings.parent.mkdir(parents=True)
            layout.settings.write_text(json.dumps({'hooks': {'Stop': [THEIRS]}, 'theme': 'dark'}))
            said = []
            self.assertEqual(install.install(layout, 'pt-BR', 5298, True, False, said.append), 0)
            self.assertFalse(layout.app.exists())                               # a dry run changes nothing
            self.assertEqual(install.install(layout, 'pt-BR', 5298, False, False, said.append), 0)
            self.assertEqual(install.install(layout, None, 5298, False, False, said.append), 0)   # again: same result
            self.assertTrue((layout.app / 'server.py').exists() and (layout.app / 'static' / 'console.js').exists())
            self.assertEqual(json.loads(layout.config.read_text())['lang'], 'pt-BR')
            settings = json.loads(layout.settings.read_text())
            self.assertEqual((settings['theme'], len(settings['hooks']['Stop']), settings['hooks']['Stop'][0]), ('dark', 2, THEIRS))
            self.assertIn(str(layout.state), settings['hooks']['Stop'][1]['hooks'][0]['command'])
            self.assertEqual(len(list(layout.settings.parent.glob('settings.json.before-tallyboard-*'))), 1)  # second run changed nothing
            self.assertFalse(layout.plist.exists())
            self.assertTrue(any('http://' in line for line in said))
            self.assertEqual(install.uninstall(layout, False, False, False, said.append), 0)
            self.assertEqual(json.loads(layout.settings.read_text()), {'hooks': {'Stop': [THEIRS]}, 'theme': 'dark'})
            self.assertFalse(layout.app.exists())
            self.assertTrue(layout.config.exists())
            self.assertEqual(install.uninstall(layout, True, False, False, said.append), 0)
            self.assertFalse(layout.state.exists())

    def test_a_broken_settings_file_stops_the_install_untouched(self):
        with tempfile.TemporaryDirectory() as home:
            layout = install.Layout(home)
            layout.settings.parent.mkdir(parents=True)
            layout.settings.write_text('{ not json')
            self.assertEqual(install.main(['install', '--home', home, '--no-service']), 1)
            self.assertEqual(layout.settings.read_text(), '{ not json')
            self.assertFalse(layout.state.exists())

    def test_service_definition_runs_the_installed_copy(self):
        layout = install.Layout('/home/someone')
        plist = install.service_plist(layout, '/usr/bin/python3', 5199)
        self.assertEqual(plist['ProgramArguments'][3], str(layout.app / 'server.py'))
        self.assertTrue(plist['RunAtLoad'] and plist['KeepAlive'])
        self.assertIn('5199', plist['ProgramArguments'])
        self.assertIn('--allow-focus', plist['ProgramArguments'])
        self.assertNotIn('--allow-focus', install.service_plist(layout, '/usr/bin/python3', 5199, touch=False)['ProgramArguments'])


if __name__ == '__main__':
    unittest.main()
