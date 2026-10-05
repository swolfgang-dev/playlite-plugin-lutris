import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget
from playlite.manual_installation import ManualInstallation

SPEC = importlib.util.spec_from_file_location(
    'lutris_defaults_under_test', Path(__file__).resolve().parents[1] / '__init__.py',
    submodule_search_locations=[str(Path(__file__).resolve().parents[1])])
import sys
PACKAGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PACKAGE
SPEC.loader.exec_module(PACKAGE)
from lutris_defaults_under_test.plugin import Plugin

APP = QApplication.instance() or QApplication([])


class DirectoryDefaultsTests(unittest.TestCase):
    def setUp(self):
        pool = patch('lutris_defaults_under_test.runner_loader.QThreadPool.globalInstance')
        mocked = pool.start()
        mocked.return_value.start.side_effect = lambda task: task.run()
        self.addCleanup(pool.stop)

    def test_runner_inventory_uses_lutris_ids_and_validation(self):
        from types import SimpleNamespace
        from lutris_defaults_under_test.runners import runner_choices, validate_runner
        with patch('lutris_defaults_under_test.runners.subprocess.run', return_value=SimpleNamespace(
                stdout='["ge-proton", "Proton - Experimental", "system", "custom", "wine-build"]')):
            choices = dict(runner_choices())
            self.assertEqual(choices['GE-Proton (Latest)'], 'ge-proton')
            self.assertEqual(choices['Proton - Experimental'], 'Proton - Experimental')
            self.assertNotIn('custom', choices.values())
            self.assertEqual(validate_runner('GE-Proton'), 'ge-proton')
            with self.assertRaises(ValueError):
                validate_runner('made-up-runner')

    def test_runner_dropdown_retains_unavailable_values_and_cannot_be_edited(self):
        from lutris_defaults_under_test.add import Plugin as Add
        plugin = Plugin()
        editor = QWidget()
        editor.fields = {}
        method = Add()
        with patch.object(plugin, 'directory_defaults', return_value={}), \
                patch('lutris_defaults_under_test.add.discover_plugins', return_value={'Lutris': plugin}), \
                patch('lutris_defaults_under_test.runner_loader.runner_choices', return_value=[('GE-Proton (Latest)', 'ge-proton')]):
            widget = method.create_editor(editor, {'WineRunner': 'missing-build',
                'Executable': '/games/Example/game.exe', 'InstallDirectory': '/games/Example', 'Prefix': '/prefixes/Example'})
        self.assertFalse(widget.runner.isEditable())
        self.assertEqual(widget.runner.currentData(), 'missing-build')
        self.assertFalse(widget.runner.model().item(widget.runner.currentIndex()).isEnabled())
        with patch('lutris_defaults_under_test.runners.runner_choices', return_value=[('GE-Proton (Latest)', 'ge-proton')]):
            with self.assertRaisesRegex(ValueError, 'available Lutris'):
                method.collect(widget, {'Name': 'Example'})
        widget.runner.setCurrentIndex(widget.runner.findData('ge-proton'))
        self.assertEqual(widget.runner.currentData(), 'ge-proton')

    def test_runner_inventory_fallback_only_lists_existing_wine_builds(self):
        from lutris_defaults_under_test.runners import runner_choices
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / 'runners/wine/installed/bin/wine'
            executable.parent.mkdir(parents=True)
            executable.touch()
            (root / 'runners/wine/incomplete').mkdir()
            with patch('lutris_defaults_under_test.runners.LUTRIS', root), \
                    patch('lutris_defaults_under_test.runners.subprocess.run', side_effect=OSError()), \
                    patch('lutris_defaults_under_test.runners.shutil.which', return_value=None):
                self.assertEqual({version for _, version in runner_choices()}, {'installed', 'ge-proton'})

    def test_registration_uses_lutris_ge_proton_identifier(self):
        import sqlite3
        import yaml
        from lutris_defaults_under_test.registration import plan, register, normalize_runner
        self.assertEqual(normalize_runner('GE-Proton'), 'ge-proton')
        self.assertEqual(normalize_runner(' GE-Proton (Latest) '), 'ge-proton')
        self.assertEqual(normalize_runner('GE-Proton9-27'), 'GE-Proton9-27')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / 'Example/game.exe'
            executable.parent.mkdir()
            executable.touch()
            lutris = root / 'lutris'
            lutris.mkdir()
            with sqlite3.connect(lutris / 'pga.db') as database:
                database.execute('CREATE TABLE games (id INTEGER PRIMARY KEY, name, sortname, slug, platform, runner, executable, directory, installed, installed_at, configpath, playtime, service)')
            registration = plan(executable, installation_directory=executable.parent, prefix=root / 'prefix')
            register(registration, runner='GE-Proton', lutris=lutris, state=root / 'state')
            config = next((lutris / 'games').glob('*.yml'))
            self.assertEqual(yaml.safe_load(config.read_text())['wine']['version'], 'ge-proton')
            saved = yaml.safe_load(config.read_text())
            saved['wine']['version'] = 'GE-Proton'
            config.write_text(yaml.safe_dump(saved))
            result = register(registration, lutris=lutris, state=root / 'state')
            self.assertTrue(result['reused'])
            self.assertEqual(yaml.safe_load(config.read_text())['wine']['version'], 'ge-proton')

    def test_settings_save_reopen_and_validate(self):
        with tempfile.TemporaryDirectory() as root:
            settings = QSettings(str(Path(root) / 'settings.ini'), QSettings.Format.IniFormat)
            with patch('PyQt6.QtCore.QSettings', return_value=settings):
                plugin = Plugin()
                widget = plugin.create_settings()
                widget.directory_fields['InstallDirectory'].setText('/games')
                widget.directory_fields['Prefix'].setText('/prefixes')
                plugin.save_settings(widget)
                reopened = plugin.create_settings()
                self.assertEqual(reopened.directory_fields['Prefix'].text(), '/prefixes')
                widget.directory_fields['Prefix'].setText('relative')
                with self.assertRaises(ValueError):
                    plugin.save_settings(widget)
                self.assertEqual(plugin.directory_defaults()['Prefix'], '/prefixes')
                widget.directory_fields['Prefix'].clear()
                plugin.save_settings(widget)
                self.assertEqual(plugin.directory_defaults()['Prefix'], '')

    def test_add_selectors_default_and_current_paths(self):
        editor = QWidget()
        editor.fields = {}
        widget = ManualInstallation().create_editor(editor, {}, directory_defaults={
            'InstallDirectory': '/games', 'Prefix': '/prefixes'})
        with patch('playlite.manual_installation.choose_directory', return_value='') as choose:
            for key, default in [('InstallDirectory', '/games'), ('Prefix', '/prefixes')]:
                widget.findChild(QPushButton, 'browse' + key).click()
                self.assertEqual(choose.call_args.args[2], default)
                widget.fields[key].setText(default + '/example')
                widget.findChild(QPushButton, 'browse' + key).click()
                self.assertEqual(choose.call_args.args[2], default + '/example')

    def test_lutris_add_passes_defaults_to_selectors(self):
        from lutris_defaults_under_test.add import Plugin as Add
        plugin = Plugin()
        editor = QWidget()
        editor.fields = {}
        with patch.object(plugin, 'directory_defaults', return_value={
                'InstallDirectory': '/games', 'Prefix': '/prefixes'}), \
                patch('lutris_defaults_under_test.add.discover_plugins', return_value={'Lutris': plugin}):
            widget = Add().create_editor(editor, {})
        with patch('playlite.manual_installation.choose_directory', return_value='') as choose:
            widget.findChild(QPushButton, 'browsePrefix').click()
            self.assertEqual(choose.call_args.args[2], '/prefixes')
            self.assertEqual(widget.fields['Prefix'].text(), '')

    def test_autofill_from_top_level_game_folder(self):
        from lutris_defaults_under_test.add import Plugin as Add
        from PyQt6.QtWidgets import QLineEdit
        plugin = Plugin()
        editor = QWidget()
        editor.fields = {'Name': QLineEdit()}
        with patch.object(plugin, 'directory_defaults', return_value={
                'InstallDirectory': '/games', 'Prefix': '/prefixes'}), \
                patch('lutris_defaults_under_test.add.discover_plugins', return_value={'Lutris': plugin}):
            widget = Add().create_editor(editor, {})
        widget.fields['Executable'].setText('/games/The Witcher 3/bin/x64/game.exe')
        self.assertEqual(widget.fields['InstallDirectory'].text(), '/games/The Witcher 3')
        self.assertTrue(widget.create_prefix.isChecked())
        self.assertEqual(editor.fields['Name'].text(), 'The Witcher 3')
        self.assertEqual(widget.fields['Prefix'].text(), '/prefixes/the-witcher-3')
        widget.fields['InstallDirectory'].setText('/games/The Witcher 3/bin/x64')
        self.assertEqual(widget.fields['InstallDirectory'].text(), '/games/The Witcher 3')
        widget.fields['Executable'].setText('/games/AnotherGame/bin/game.exe')
        self.assertEqual(widget.fields['InstallDirectory'].text(), '/games/AnotherGame')
        self.assertEqual(editor.fields['Name'].text(), 'AnotherGame')
        self.assertEqual(widget.fields['Prefix'].text(), '/prefixes/another-game')
        editor.fields['Name'].setText('My custom title')
        widget.fields['Prefix'].setText('/custom/prefix')
        widget.fields['Executable'].setText('/games/Third Game/bin/game.exe')
        self.assertEqual(editor.fields['Name'].text(), 'My custom title')
        self.assertEqual(widget.fields['Prefix'].text(), '/custom/prefix')

    def test_autofill_requires_game_beneath_default_root(self):
        from lutris_defaults_under_test.add import Plugin as Add
        from PyQt6.QtWidgets import QLineEdit
        plugin = Plugin()
        editor = QWidget()
        editor.fields = {'Name': QLineEdit()}
        with patch.object(plugin, 'directory_defaults', return_value={
                'InstallDirectory': '/games', 'Prefix': '/prefixes'}), \
                patch('lutris_defaults_under_test.add.discover_plugins', return_value={'Lutris': plugin}):
            widget = Add().create_editor(editor, {})
        for folder in ('/games', '/games-other/Example', '/other/Example'):
            widget.fields['InstallDirectory'].setText(folder)
            self.assertEqual(editor.fields['Name'].text(), '')
            self.assertEqual(widget.fields['Prefix'].text(), '')

    def test_action_selectors_use_defaults(self):
        plugin = Plugin()
        with patch.object(plugin, 'directory_defaults', return_value={
                'InstallDirectory': '/games', 'Prefix': '/prefixes'}):
            with patch('playlite.lifecycle.choose_directory', return_value='') as choose:
                widget = plugin.create_action_editor({})
                buttons = widget.findChildren(QPushButton)
                buttons[1].click()
                self.assertEqual(choose.call_args.args[2], '/prefixes')
                buttons[2].click()
                self.assertEqual(choose.call_args.args[2], '/games')
                widget.fields['Prefix'].setText('/prefixes/example')
                buttons[1].click()
                self.assertEqual(choose.call_args.args[2], '/prefixes/example')
