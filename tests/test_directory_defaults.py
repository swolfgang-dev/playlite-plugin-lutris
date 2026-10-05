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
        self.assertEqual(editor.fields['Name'].text(), 'The Witcher 3')
        self.assertEqual(widget.fields['Prefix'].text(), '/prefixes/the-witcher-3')
        widget.fields['Executable'].setText('/games/AnotherGame/bin/game.exe')
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
