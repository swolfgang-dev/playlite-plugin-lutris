from plugin_test_support import require_plugin, wait_for_runners
require_plugin('ImageStudio')
require_plugin('LutrisIntegration')
require_plugin('SteamAutoCrack')
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
from PyQt6.QtWidgets import QApplication, QTabWidget
from playlite.editor import MetadataEditor, save_game
from playlite_plugins.lutrisintegration.registration import plan, register
from playlite_plugins.imagestudio.studio import IconStudio
from PyQt6.QtGui import QImage, QColor

APP = QApplication.instance() or QApplication([])


class WorkflowTests(unittest.TestCase):
    def test_completed_steam_dialog_can_close(self):
        from PyQt6.QtCore import QProcess
        from PyQt6.QtWidgets import QDialog
        from playlite_plugins.steamautocrack.progress import SteamProgress
        with tempfile.TemporaryDirectory() as directory, patch('playlite_plugins.steamautocrack.runner.PRIVATE', Path(directory)), patch.object(QProcess, 'start'):
            dialog = SteamProgress({'AppId': '123'})
            (dialog.job / 'result.json').write_text(json.dumps({'Message': 'All operations completed.'}))
            dialog.show()
            dialog.process_finished(0)
            self.assertEqual(dialog.button.text(), 'Close')
            dialog.button.click()
            self.assertFalse(dialog.isVisible())
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            dialog.show()
            dialog.close()
            self.assertFalse(dialog.isVisible())

    def test_register_reuse_has_no_playnite_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'games' / 'Example'
            folder.mkdir(parents=True)
            exe = folder / 'game.exe'
            exe.touch()
            lutris = root / 'lutris'
            lutris.mkdir()
            with closing(sqlite3.connect(lutris / 'pga.db')) as db:
                db.execute('CREATE TABLE games (id INTEGER PRIMARY KEY, name, sortname, slug, platform, runner, executable, directory, installed, installed_at, configpath, playtime, service)')
            registration = plan(exe, root=root / 'games', prefixes=root / 'prefixes')
            first = register(registration, lutris=lutris, state=root / 'state')
            second = register(registration, lutris=lutris, state=root / 'state')
            self.assertEqual(first['id'], second['id'])
            self.assertTrue(second['reused'])
            self.assertFalse((root / 'state/pending').exists())
            self.assertTrue(registration.prefix.is_dir())

    def test_new_library_save_and_metadata_page(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / 'new-library'
            game = {'Id': 'test', 'Name': 'Example'}
            saved = save_game(data, [], game)
            self.assertEqual({key: value for key, value in saved[0].items() if key != 'Added'}, game)
            added = datetime.fromisoformat(saved[0]['Added'])
            self.assertIsNotNone(added.tzinfo)
            self.assertLess(abs((datetime.now().astimezone() - added).total_seconds()), 5)
            self.assertNotIn('Added', game)
            self.assertEqual(json.loads((data / 'library.json').read_text()), saved)
            editor = MetadataEditor(game, data)
            tabs = editor.findChild(QTabWidget)
            self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ['Installation', 'Metadata', 'Images'])
            editor.reject()

    def test_added_date_is_preserved_on_edits_and_supplied_dates_are_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            game = {'Id': 'new', 'Name': 'Example'}
            saved = save_game(data, [], game)
            original = saved[0]['Added']
            saved = save_game(data, [], dict(game, Name='Edited', Added=None))
            self.assertEqual(saved[0]['Added'], original)
            imported = {'Id': 'imported', 'Name': 'Imported', 'Added': '2020-01-02'}
            saved = save_game(data, saved, imported)
            self.assertEqual(next(g for g in saved if g['Id'] == 'imported')['Added'], '2020-01-02')
            legacy = {'Id': 'legacy', 'Name': 'Old entry'}
            (data / 'library.json').write_text(json.dumps([legacy]))
            saved = save_game(data, [legacy], dict(legacy, Name='Edited old entry'))
            self.assertNotIn('Added', saved[0])

    def test_icon_is_transparent_and_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            image = QImage(200, 300, QImage.Format.Format_RGB32)
            image.fill(QColor('red'))
            source = Path(directory) / 'cover.png'
            image.save(str(source))
            studio = IconStudio(source)
            studio.save()
            result = QImage(studio.output)
            self.assertEqual(result.width(), 256)
            self.assertEqual(result.pixelColor(0, 0).alpha(), 0)
            self.assertEqual(result.pixelColor(128, 128).red(), 255)
            studio.cache.cleanup()

    def test_manual_add_only_saves_library_entry(self):
        from playlite.add_game import AddGameEditor
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / 'Example' / 'game.exe'
            exe.parent.mkdir()
            exe.touch()
            with patch('playlite_plugins.lutrisintegration.registration.register') as register_game:
                dialog = AddGameEditor(exe, root / 'library')
                self.assertFalse(dialog.autocrack.isChecked())
                self.assertEqual(dialog.findChild(QTabWidget).currentIndex(), 0)
                self.assertEqual(dialog.fields['Prefix'].text(), '')
                dialog.save()
                self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
                register_game.assert_not_called()
                game = dialog.result_game
                self.assertFalse(game.get('LutrisId'))
                self.assertFalse(game.get('GameProvider'))
                self.assertEqual(game['Executable'], str(exe))
                saved = save_game(root / 'library', [], game)
                self.assertEqual(saved[0]['Name'], 'Example')
                self.assertEqual(list(exe.parent.iterdir()), [exe])

    def test_blank_add_opens_installation(self):
        from playlite.add_game import AddGameEditor
        with tempfile.TemporaryDirectory() as directory:
            dialog = AddGameEditor(None, Path(directory))
            self.assertEqual(dialog.findChild(QTabWidget).currentIndex(), 0)
            self.assertEqual(dialog.fields['InstallDirectory'].text(), '')
            self.assertEqual(dialog.fields['Executable'].text(), '')
            self.assertEqual(dialog.fields['Platforms'].toPlainText(), '')
            dialog.reject()

    def test_manual_plugin_validates_and_collects_installation(self):
        from playlite.add_game import AddGameEditor
        with tempfile.TemporaryDirectory() as directory:
            dialog = AddGameEditor(None, Path(directory))
            self.assertEqual(dialog.installation_plugin.id, 'Manual')
            dialog.fields['Name'].setText('Uninstalled game')
            dialog.fields['Executable'].setText('relative/game.exe')
            dialog.save()
            self.assertIsNone(dialog.result_game)
            self.assertIn('absolute', dialog.error.text())
            dialog.fields['Executable'].clear()
            dialog.fields['LaunchArguments'].setText('--windowed')
            dialog.save()
            self.assertEqual(dialog.result_game['InstallationMethod'], 'Manual')
            self.assertEqual(dialog.result_game['LaunchArguments'], '--windowed')
            self.assertFalse(dialog.result_game.get('LutrisId'))
            self.assertFalse(dialog.result_game.get('Prefix'))

    def test_add_editor_without_steamautocrack_plugin(self):
        from playlite.providers import discover_plugins
        from playlite.add_game import AddGameEditor
        plugins = discover_plugins()
        plugins.pop('SteamAutoCrack', None)
        with tempfile.TemporaryDirectory() as directory, patch('playlite.providers.discover_plugins', return_value=plugins):
            dialog = AddGameEditor(None, Path(directory))
            self.assertFalse(hasattr(dialog, 'autocrack'))
            self.assertFalse(hasattr(dialog, 'api_key'))
            dialog.reject()

    def test_manual_folder_defaults_to_executable_and_preserves_override(self):
        from playlite.add_game import AddGameEditor
        with tempfile.TemporaryDirectory() as directory:
            dialog = AddGameEditor(None, Path(directory))
            dialog.fields['Executable'].setText('/games/first/game.exe')
            self.assertEqual(dialog.fields['InstallDirectory'].text(), '/games/first')
            dialog.fields['Executable'].setText('/games/second/game.exe')
            self.assertEqual(dialog.fields['InstallDirectory'].text(), '/games/second')
            dialog.fields['InstallDirectory'].setText('/games/custom')
            dialog.fields['Executable'].setText('/games/third/game.exe')
            self.assertEqual(dialog.fields['InstallDirectory'].text(), '/games/custom')
            dialog.reject()

    def test_manual_installation_ids_and_prefix_save_without_registration(self):
        from playlite.add_game import AddGameEditor
        with tempfile.TemporaryDirectory() as directory, patch('playlite_plugins.lutrisintegration.registration.register') as register_game:
            dialog = AddGameEditor(None, Path(directory))
            dialog.fields['Name'].setText('Example')
            dialog.fields['Prefix'].setText('/prefixes/example')
            dialog.fields['LutrisId'].setText('42')
            dialog.fields['SteamId'].setText('12345')
            dialog.save()
            self.assertEqual(dialog.result_game['Prefix'], '/prefixes/example')
            self.assertEqual(dialog.result_game['LutrisId'], '42')
            self.assertEqual(dialog.result_game['MetadataIds']['SteamMetadata'], '12345')
            register_game.assert_not_called()

    def test_lutris_import_picker_fills_editor_before_save(self):
        from playlite.add_game import AddGameEditor
        from PyQt6.QtWidgets import QListWidget, QDialog
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dialog = AddGameEditor(None, root, installation_method='LutrisImport')
            dialog.fields['LaunchArguments'].setText('--existing')
            self.assertEqual(dialog.fields['LaunchArguments'].text(), '--existing')
            plugin = dialog.installation_plugin
            from unittest.mock import Mock
            provider = Mock()
            provider.import_games.return_value = [{'Id': 'external', 'Name': 'Lutris example', 'LutrisId': 42,
                'Executable': '/games/example/game.exe', 'InstallDirectory': '/games/example',
                'Prefix': '/prefixes/example', 'LaunchArguments': '--test', 'IsInstalled': True}]
            def select_first(picker):
                picker.findChild(QListWidget).setCurrentRow(0)
                return QDialog.DialogCode.Accepted
            with patch.dict(plugin.choose_game.__globals__, {'run_dialog': select_first}):
                plugin.choose_game(dialog.installation_widget, provider)
            self.assertEqual(dialog.fields['Name'].text(), 'Lutris example')
            self.assertEqual(dialog.fields['Prefix'].text(), '/prefixes/example')
            self.assertFalse((root / 'library.json').exists())
            dialog.autocrack.setChecked(False)
            dialog.save()
            self.assertEqual(dialog.result_game['InstallationMethod'], 'LutrisImport')
            self.assertEqual(dialog.result_game['GameProvider'], 'LutrisIntegration')
            self.assertEqual(dialog.result_game['PlayActions'][0]['GameId'], '42')
            self.assertNotEqual(dialog.result_game['Id'], 'external')

    def test_add_to_lutris_validates_before_registration(self):
        from playlite.add_game import AddGameEditor
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / 'Example/game.exe'
            exe.parent.mkdir()
            exe.touch()
            dialog = AddGameEditor(None, root / 'library', installation_method='LutrisAdd')
            wait_for_runners(dialog.installation_widget)
            dialog.fields['Name'].setText('Example')
            dialog.fields['Executable'].setText(str(exe))
            dialog.fields['Prefix'].setText(str(root / 'prefix'))
            plugin = dialog.installation_plugin
            dialog.autocrack.setChecked(False)
            self.assertTrue(dialog.installation_widget.create_prefix.isChecked())
            dialog.installation_widget.create_prefix.setChecked(False)
            with patch.object(plugin.lutris, 'register', return_value={'id': 42, 'prefix': str(root / 'prefix')}) as register_game:
                dialog.save()
                register_game.assert_not_called()
                self.assertIn('existing prefix', dialog.error.text())
                dialog.installation_widget.create_prefix.setChecked(True)
                dialog.fields['LaunchArguments'].setText('--windowed')
                dialog.save()
                register_game.assert_called_once()
                self.assertEqual(register_game.call_args.args[2], '--windowed')
                self.assertEqual(dialog.result_game['GameProvider'], 'LutrisIntegration')
                self.assertEqual(dialog.result_game['PlayActions'][0]['GameId'], '42')
                self.assertEqual(dialog.result_game['InstallationMethod'], 'LutrisAdd')
