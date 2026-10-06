import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from PyQt6.QtCore import QThreadPool, QTimer
from PyQt6.QtWidgets import QWidget
from test_directory_defaults import APP, Plugin
from lutris_defaults_under_test.add import Plugin as Add
from lutris_defaults_under_test import runtime


def wait_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(.005)
    assert predicate(), 'Background runner discovery did not finish'


class RunnerLoadingTests(unittest.TestCase):
    def editor(self):
        editor = QWidget()
        editor.fields = {}
        plugin = Plugin()
        with patch('lutris_defaults_under_test.add.discover_plugins', return_value={'LutrisIntegration': plugin}):
            widget = Add().create_editor(editor, {'WineRunner': 'saved-runner'})
        return editor, widget

    def test_slow_discovery_keeps_gui_responsive_and_does_not_block_save(self):
        release = threading.Event()
        started = threading.Event()
        def discover():
            started.set()
            release.wait(3)
            return [('GE-Proton (Latest)', 'ge-proton'), ('Saved', 'saved-runner')]
        with patch('lutris_defaults_under_test.runner_loader.runner_choices', side_effect=discover):
            editor, widget = self.editor()
            try:
                self.assertTrue(started.wait(1))
                tick = []
                QTimer.singleShot(0, lambda: tick.append(True))
                wait_until(lambda: tick)
                self.assertIsNone(widget.runner_choices)
                self.assertFalse(widget.runner.isEnabled())
                release.set()
                wait_until(lambda: widget.runner_choices is not None)
                self.assertEqual(widget.runner.currentData(), 'saved-runner')
                self.assertTrue(widget.runner.isEnabled())
                widget.refresh_runners.click()
                wait_until(lambda: widget.runner_choices is not None)
                self.assertEqual(widget.runner.currentData(), 'saved-runner')
            finally:
                release.set()
                QThreadPool.globalInstance().waitForDone(3000)
                widget.deleteLater()
                editor.deleteLater()
                APP.processEvents()

    def test_discovery_failure_can_be_retried(self):
        with patch('lutris_defaults_under_test.runner_loader.runner_choices', side_effect=RuntimeError('failed')):
            editor, widget = self.editor()
            wait_until(lambda: widget.refresh_runners.isEnabled())
        self.assertFalse(widget.runner.isEnabled())
        with patch('lutris_defaults_under_test.runner_loader.runner_choices', return_value=[('Saved', 'saved-runner')]):
            widget.refresh_runners.click()
            wait_until(lambda: widget.runner_choices is not None)
        self.assertEqual(widget.runner.currentData(), 'saved-runner')

    def test_closing_editor_while_discovery_runs_is_safe(self):
        release = threading.Event()
        with patch('lutris_defaults_under_test.runner_loader.runner_choices', side_effect=lambda: (release.wait(2), [('GE', 'ge-proton')])[1]):
            editor, widget = self.editor()
            import PyQt6.sip
            PyQt6.sip.delete(widget)
            release.set()
            self.assertTrue(QThreadPool.globalInstance().waitForDone(3000))
            APP.processEvents()

    def test_flatpak_database_and_native_precedence(self):
        with TemporaryDirectory() as folder:
            home = Path(folder)
            data = home / 'custom-data'
            self.assertEqual(runtime.installation(home, data), (data / 'lutris', False))
            flat = home / '.var/app/net.lutris.Lutris/data/lutris'
            flat.mkdir(parents=True)
            (flat / 'pga.db').touch()
            self.assertEqual(runtime.installation(home, data), (flat, True))
            native = data / 'lutris'
            native.mkdir(parents=True)
            (native / 'pga.db').touch()
            self.assertEqual(runtime.installation(home, data), (native, False))

    def test_flatpak_commands_share_the_selected_installation(self):
        with patch.object(runtime, 'FLATPAK', True), patch.object(runtime.shutil, 'which', return_value='/bin/flatpak'):
            self.assertEqual(runtime.launch_command('lutris:rungameid/1'), ['/bin/flatpak', 'run', runtime.APP_ID, 'lutris:rungameid/1'])
            self.assertEqual(runtime.inventory_command('script'), ['/bin/flatpak', 'run', '--command=python3', runtime.APP_ID, '-c', 'script'])

    def test_repo_profile_uses_host_lutris_and_environment(self):
        with TemporaryDirectory() as folder:
            home = Path(folder)
            data = home / 'desktop-data'
            (data / 'lutris').mkdir(parents=True)
            (data / 'lutris/pga.db').touch()
            private = str(home / 'private')
            values = dict(PLAYLITE_PROFILE='repo', HOME=private,
                          XDG_DATA_HOME=private + '/data', XDG_CONFIG_HOME=private + '/config',
                          PLAYLITE_HOST_HOME=str(home), PLAYLITE_HOST_XDG_DATA_HOME=str(data),
                          PLAYLITE_HOST_XDG_CONFIG_HOME='')
            with patch.dict(runtime.os.environ, values, clear=True):
                self.assertEqual(runtime.installation(), (data / 'lutris', False))
                env = runtime.environment()
                self.assertEqual(env['HOME'], str(home))
                self.assertEqual(env['XDG_DATA_HOME'], str(data))
                self.assertNotIn('XDG_CONFIG_HOME', env)
                self.assertEqual(runtime.os.environ['HOME'], private)

    def test_existing_repo_session_falls_back_to_desktop_home(self):
        from types import SimpleNamespace
        with patch.dict(runtime.os.environ, {'PLAYLITE_PROFILE': 'repo', 'HOME': '/private',
                                            'XDG_DATA_HOME': '/private/data'}, clear=True), \
                patch.object(runtime.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir='/desktop')):
            self.assertEqual(runtime.installation(), (Path('/desktop/.local/share/lutris'), False))
