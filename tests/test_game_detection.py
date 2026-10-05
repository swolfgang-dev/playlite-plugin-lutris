from plugin_test_support import require_plugin
require_plugin('Lutris')
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from playlite.providers import discover_plugins, installation_methods, IntegrationPlugin
from playlite_plugins.lutris.detection import detect_running, process_snapshot
from playlite.game_detection import GameDetection, record_playtime
from playlite.editor import MetadataEditor
from playlite.add_game import AddGameEditor

APP = QApplication.instance() or QApplication([])


class IntegrationTests(unittest.TestCase):
    def test_failed_checkpoint_retries_without_losing_or_duplicating_time(self):
        plugin = discover_plugins()['Lutris']
        games = [{'Id': 'a', 'GameProvider': 'Lutris', 'LutrisId': 42}]
        attempts = []
        def recorder(identity, seconds, count, stamp):
            attempts.append((seconds, count))
            return len(attempts) != 2
        monitor = GameDetection([plugin], lambda: games, recorder=recorder)
        for now in (0, 30, 31, 60, 61):
            monitor.observe({'Lutris': (games, {'a'})}, now=now)
        self.assertEqual(attempts, [(0, 1), (30, 0), (31, 0), (30, 0)])
        self.assertEqual(monitor.sessions['a']['saved'], 61)

    def test_recording_checkpoints_handoffs_exit_and_failed_launch(self):
        plugin = discover_plugins()['Lutris']
        games = [{'Id': 'a', 'Name': 'Example', 'GameProvider': 'Lutris', 'LutrisId': 42,
                  'Playtime': 100, 'PlayCount': 2}]
        with TemporaryDirectory() as directory:
            data = Path(directory)
            monitor = GameDetection([plugin], lambda: games)
            def persist(identity, seconds, count, stamp):
                games[:] = record_playtime(data, games, identity, seconds, count, stamp)
            monitor.recorded.connect(persist)
            def scan(now, running):
                monitor.observe({'Lutris': (games, {'a'} if running else set())}, now=now)
            with patch('playlite.game_detection.time.monotonic', return_value=0):
                monitor.launching('a')
            scan(5, True)
            self.assertEqual(games[0]['PlayCount'], 3)
            self.assertEqual(games[0]['Playtime'], 100)
            scan(15, False)
            scan(16, True)  # A short hand-off remains one session.
            scan(35.5, True)
            self.assertEqual(games[0]['Playtime'], 130)
            editor = MetadataEditor(games[0], data)
            scan(40.9, False)
            scan(43, False)
            self.assertEqual(games[0]['Playtime'], 135)
            self.assertEqual(games[0]['PlayCount'], 3)
            self.assertEqual(editor.collect()['Playtime'], 135)
            editor.fields['Playtime'].setText('200')
            self.assertEqual(editor.collect()['Playtime'], 200)
            editor.reject()
            with patch('playlite.game_detection.time.monotonic', return_value=50):
                monitor.launching('a')
            scan(111, False)
            self.assertEqual(games[0]['PlayCount'], 3)
            scan(120, True)  # External launch, even after a failed launch.
            with patch('playlite.game_detection.time.monotonic', return_value=130.2):
                monitor.stop()
                monitor.stop()  # Shutdown must not double count.
            self.assertEqual(games[0]['PlayCount'], 4)
            self.assertEqual(games[0]['Playtime'], 145)
            from datetime import datetime
            self.assertIsNotNone(datetime.fromisoformat(games[0]['LastActivity']).utcoffset())

    def test_history_merges_latest_library_without_resurrecting_removed_game(self):
        import json
        with TemporaryDirectory() as directory:
            data = Path(directory)
            games = [{'Id': 'a', 'Name': 'Old name', 'Playtime': 10, 'PlayCount': 1}]
            latest = [dict(games[0], Name='Edited name', Playtime=20)]
            (data / 'library.json').write_text(json.dumps(latest))
            saved = record_playtime(data, games, 'a', 5, 1, '2026-10-04T12:00:00+00:00')
            self.assertEqual(saved[0]['Name'], 'Edited name')
            self.assertEqual(saved[0]['Playtime'], 25)
            (data / 'library.json').write_text('[]')
            self.assertEqual(record_playtime(data, games, 'a', 5, 0, 'later'), [])

    def test_one_lutris_integration_supplies_both_add_methods(self):
        plugins = discover_plugins()
        self.assertNotIn('LutrisAdd', plugins)
        self.assertNotIn('LutrisImport', plugins)
        self.assertIsInstance(plugins['Lutris'], IntegrationPlugin)
        self.assertEqual(plugins['Lutris'].name, 'Lutris Integration')
        self.assertEqual(set(installation_methods(plugins)), {'Manual', 'LutrisAdd', 'LutrisImport'})
        self.assertTrue(plugins['Lutris'].owns({'LutrisId': 42}))
        self.assertFalse(plugins['Lutris'].owns({'LutrisId': 42, 'GameProvider': None}))

    def test_edit_actions_and_add_integration_dropdown(self):
        with TemporaryDirectory() as directory:
            game = {'Id': 'example', 'Name': 'Example', 'LutrisId': '42'}
            editor = MetadataEditor(game, Path(directory))
            self.assertEqual(editor.play_actions.cards[0].integration.currentData(), 'Lutris')
            editor.play_actions.remove(editor.play_actions.cards[0])
            result = editor.collect()
            self.assertIsNone(result['GameProvider'])
            self.assertNotIn('LutrisId', result)
            editor.reject()
            for method in ('Manual', 'LutrisAdd', 'LutrisImport'):
                editor = AddGameEditor(None, Path(directory), installation_method=method)
                self.assertFalse(hasattr(editor, 'integration'))
                self.assertEqual(editor.installation_method.currentData(), method)
                self.assertEqual(editor.installation_plugin.id, method)
                editor.fields['Executable'].setText('/games/example/game.exe')
                editor.fields['SteamId'].setText('123')
                editor.installation_method.setCurrentIndex(editor.installation_method.findData('LutrisAdd'))
                editor.installation_widget.runner.setCurrentIndex(editor.installation_widget.runner.count() - 1)
                selected_runner = editor.installation_widget.runner.currentData()
                editor.installation_method.setCurrentIndex(editor.installation_method.findData('Manual'))
                self.assertEqual(editor.fields['Executable'].text(), '/games/example/game.exe')
                self.assertEqual(editor.fields['SteamId'].text(), '123')
                self.assertIsNone(editor.game.get('GameProvider'))
                editor.installation_method.setCurrentIndex(editor.installation_method.findData('LutrisAdd'))
                self.assertEqual(editor.installation_widget.runner.currentData(), selected_runner)
                self.assertIs(editor.fields['Executable'], editor.installation_widget.fields['Executable'])
                editor.reject()


class LutrisDetectionTests(unittest.TestCase):
    def setUp(self):
        self.games = [dict(Id='a', Executable='/games/a/game.exe', InstallDirectory='/games/a', Prefix='/prefix/a'),
                      dict(Id='b', Executable='/games/b/game.exe', InstallDirectory='/games/b', Prefix='/prefix/b')]

    def test_separate_uuid_sessions_do_not_match_client_or_other_prefixes(self):
        wrapper = dict(session='session-a', args=['lutris-wrapper: A'], cwd='/games/a', prefix='/prefix/a', exe='/usr/bin/python3')
        self.assertEqual(detect_running(self.games, [wrapper]), {'a'})
        self.assertEqual(detect_running(self.games, [dict(wrapper, prefix='/prefix/b')]), set())
        self.assertEqual(detect_running(self.games, [dict(wrapper, session='', args=['lutris'])]), set())
        self.assertEqual(detect_running(self.games, [dict(wrapper, args=['wineserver'])]), set())
        other = dict(wrapper, session='session-b', cwd='/games/b', prefix='/prefix/b')
        self.assertEqual(detect_running(self.games, [wrapper, other]), {'a', 'b'})
        self.assertEqual(detect_running(self.games + [dict(self.games[0], Id='duplicate')], [wrapper]), set())

    def test_wine_executable_and_session_uuid_survive_wrapper_exit(self):
        record = dict(session='uuid', args=['wine', '/games/a/game.exe'], cwd='/other', prefix='/prefix/a', exe='/usr/bin/wine')
        self.assertEqual(detect_running(self.games, [record]), {'a'})
        game = dict(self.games[0], Executable='/prefix/a/drive_c/Game/game.exe')
        record['args'] = ['wine', 'C:\\Game\\game.exe']
        self.assertEqual(detect_running([game], [record]), {'a'})

    def test_proc_snapshot_skips_zombies_and_unrelated_processes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for pid, state, env in [(1, 'S', 'LUTRIS_GAME_UUID=uuid\0WINEPREFIX=/prefix/a\0'),
                                    (2, 'Z', 'LUTRIS_GAME_UUID=zombie\0'), (3, 'S', 'OTHER=value\0')]:
                process = root / str(pid)
                process.mkdir()
                (process / 'stat').write_text(f'{pid} (some process) {state} ' + ' '.join(['0'] * 18 + ['123']))
                (process / 'cmdline').write_bytes(b'wine\0/games/a/game.exe\0')
                (process / 'environ').write_bytes(env.encode())
                (process / 'cwd').symlink_to('/games/a')
                (process / 'exe').symlink_to('/usr/bin/wine')
            snapshot = process_snapshot(root)
            self.assertEqual(len(snapshot), 1)
            self.assertEqual(snapshot[0]['session'], 'uuid')
            self.assertEqual(snapshot[0]['start'], '123')

    def test_native_proc_detection_observes_process_start_and_exit(self):
        env = dict(os.environ, LUTRIS_GAME_UUID='playlite-detection-test')
        process = subprocess.Popen(['/usr/bin/sleep', '5'], env=env)
        game = {'Id': 'live', 'Executable': '/usr/bin/sleep', 'InstallDirectory': '/nonexistent-game-folder'}
        try:
            deadline = time.monotonic() + 1
            running = set()
            while not running and time.monotonic() < deadline:
                running = detect_running([game], process_snapshot())
                if not running:
                    time.sleep(0.01)
            self.assertEqual(running, {'live'})
        finally:
            process.terminate()
            process.wait()
        self.assertEqual(detect_running([game], process_snapshot()), set())

    def test_status_launch_timeout_exit_grace_and_external_detection(self):
        plugin = discover_plugins()['Lutris']
        games = [{'Id': 'a', 'GameProvider': 'Lutris', 'LutrisId': 42}]
        monitor = GameDetection([plugin], lambda: games)
        with patch('playlite.game_detection.time.monotonic', return_value=0):
            monitor.launching('a')
        monitor.observe({'Lutris': (games, set())}, now=10)
        self.assertEqual(monitor.status('a'), 'Launching')
        monitor.observe({'Lutris': (games, {'a'})}, now=11)
        self.assertEqual(monitor.status('a'), 'Running')
        monitor.observe({'Lutris': (games, set())}, now=12)
        self.assertEqual(monitor.status('a'), 'Running')
        monitor.observe({'Lutris': (games, {'a'})}, now=13)
        monitor.observe({'Lutris': (games, set())}, now=14)
        monitor.observe({'Lutris': (games, set())}, now=16)
        self.assertEqual(monitor.status('a'), 'Stopped')
        with patch('playlite.game_detection.time.monotonic', return_value=20):
            monitor.launching('a')
        monitor.observe({'Lutris': (games, set())}, now=81)
        self.assertEqual(monitor.status('a'), 'Launch failed')
        monitor.observe({'Lutris': (games, {'a'})}, now=82)
        self.assertEqual(monitor.status('a'), 'Running')
        games[0]['GameProvider'] = None
        monitor.observe({}, now=83)
        self.assertEqual(monitor.status('a'), 'Stopped')
