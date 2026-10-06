from plugin_test_support import require_plugin
require_plugin('IGDB')
require_plugin('GameArchiver')
require_plugin('SteamMetadata')
require_plugin('SteamAutoCrack')
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from playlite.providers import discover_providers, discover_plugins, GameProvider, GenericPlugin
from playlite.metadata_dialog import MetadataDownloader

APP = QApplication.instance() or QApplication([])


class ProviderPluginTests(unittest.TestCase):
    def test_lutris_plugin_import_and_launch(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with sqlite3.connect(root / 'pga.db') as db:
                db.execute('CREATE TABLE games (id INTEGER, name TEXT, installed INTEGER, executable TEXT, directory TEXT)')
                db.execute('INSERT INTO games VALUES (42, "Example", 1, "/games/example/game.exe", "/games/example")')
            plugin = discover_plugins()['LutrisIntegration']
            with patch.dict(plugin.import_games.__globals__, {'LUTRIS': root}):
                games = plugin.import_games()
            self.assertEqual(games[0]['GameProvider'], 'LutrisIntegration')
            self.assertEqual(games[0]['LutrisId'], 42)
            with patch('playlite_plugins.lutrisintegration.runtime.FLATPAK', False), \
                 patch('shutil.which', return_value='/usr/bin/lutris'), patch('subprocess.Popen') as launch:
                plugin.launch(games[0])
                launch.assert_called_once_with(['/usr/bin/lutris', 'lutris:rungameid/42'], start_new_session=True)

    def test_game_and_generic_plugins_are_separate_from_metadata(self):
        with TemporaryDirectory() as directory:
            plugins = discover_plugins()
            self.assertIsInstance(plugins['LutrisIntegration'], GameProvider)
            self.assertTrue(plugins['LutrisIntegration'].owns({'LutrisId': 42}))
            self.assertEqual(plugins['LutrisIntegration'].association_id({'LutrisId': 42}), 42)
            self.assertIsInstance(plugins['SteamAutoCrack'], GenericPlugin)
            self.assertIsInstance(plugins['GameArchiver'], GenericPlugin)
            disabled = discover_plugins(include_disabled=True)
            self.assertIsInstance(disabled['SteamAutoCrack'], GenericPlugin)
            self.assertIsInstance(disabled['GameArchiver'], GenericPlugin)
            self.assertTrue({'SteamMetadata', 'IGDB'} <= set(discover_providers()))
            self.assertNotIn('LutrisIntegration', discover_providers())
            self.assertNotIn('SteamAutoCrack', discover_providers())
    def test_igdb_metadata_is_enabled_and_uses_saved_id(self):
        with TemporaryDirectory() as directory:
            self.assertIn('SteamMetadata', discover_plugins())
            self.assertIn('IGDB', discover_plugins())
            self.assertIn('IGDB', discover_plugins(include_disabled=True))
            dialog = MetadataDownloader({'Name': 'Example', 'MetadataIds': {'IGDB': '123'}})
            self.assertTrue({'SteamMetadata', 'IGDB'} <= set(dialog.providers))
            self.assertEqual(dialog.id_fields['IGDB'].text(), '123')
            self.assertEqual(dialog.metadata_ids['IGDB'], '123')
            dialog.reject()
            dialog.cache.cleanup()

    def test_igdb_artwork_catalogue_includes_all_images_and_caches_across_types(self):
        with TemporaryDirectory() as directory:
            plugin = discover_providers()['IGDB']
            response = [{'cover': {'image_id': 'cover1'},
                         'artworks': [{'image_id': 'art1'}, {'image_id': 'art2'}, {'image_id': '../bad'}],
                         'screenshots': [{'image_id': 'screen1'}, {'image_id': 'art1'}]}]
            with patch.object(plugin.client, 'games', return_value=response) as fetch:
                covers = plugin.images(123, 'CoverImage')
                headers = plugin.images(123, 'HeaderImage')
                backgrounds = plugin.images(123, 'BackgroundImage')
                fetch.assert_called_once()
                self.assertEqual(len(covers), 1)
                self.assertEqual(len(headers), 3)
                self.assertEqual(headers, backgrounds)
                self.assertTrue(all('/t_1080p_2x/' in item['url'] for item in covers + headers))

    def test_builtin_providers_use_existing_apis(self):
        with TemporaryDirectory() as directory:
            providers = discover_providers(include_disabled=True)
            self.assertTrue({'SteamMetadata', 'IGDB'} <= set(providers))
            self.assertFalse('Tags' in providers['SteamMetadata'].fields)
            with patch('playlite_plugins.steammetadata.metadata.fetch_metadata', return_value={'fields': {}}) as fetch:
                providers['SteamMetadata'].fetch(123, {'Name'})
                fetch.assert_called_once_with(123)
            self.assertTrue(providers['SteamMetadata'].is_exact_query('123', 123))
            self.assertTrue(providers['IGDB'].is_exact_query('https://igdb.com/games/example', 456))

    def test_user_plugin_appears_in_downloader_and_picker(self):
        with TemporaryDirectory() as directory:
            plugin = Path(directory) / 'example'
            plugin.mkdir()
            (plugin / 'manifest.json').write_text(json.dumps({'id': 'example', 'name': 'Example Source',
                'version': '1.0', 'api_version': 1, 'fields': ['Name']}))
            (plugin / 'plugin.py').write_text('''from playlite.providers import MetadataProvider
class Provider(MetadataProvider):
    def search(self, query):
        return [{'id': 'one', 'name': 'Example game'}]
    def fetch(self, game_id, fields):
        return {'id': game_id, 'name': 'Example game', 'fields': {'Name': 'Example game'}, 'images': {}}
''')
            providers = discover_providers(directory, include_disabled=True)
            with patch('playlite.providers.discover_providers', return_value=providers):
                dialog = MetadataDownloader({'Name': 'Current'}, mode='metadata')
            self.assertEqual(dialog.fields.columnCount(), 2)
            self.assertTrue(dialog.source_toggles['Name']['example'].isEnabled())
            self.assertFalse(dialog.source_toggles['Genres']['example'].isEnabled())
            dialog.selected_fields = ['Name']
            dialog.provider_payloads = {'example': providers['example'].fetch('one', {'Name'})}
            dialog.show_combined_preview()
            self.assertEqual(dialog.preview.columnCount(), 3)
            dialog.select_source_values('example')
            dialog.apply()
            self.assertEqual(dialog.applied['Name'], 'Example game')

    def test_invalid_plugin_does_not_prevent_builtin_loading(self):
        with TemporaryDirectory() as directory:
            plugin = Path(directory) / 'bad'
            plugin.mkdir()
            (plugin / 'manifest.json').write_text('{}')
            with self.assertLogs(level='ERROR'):
                providers = discover_providers(directory, include_disabled=True)
            self.assertEqual(providers, {})

    def test_lutris_uses_config_executable_and_working_directory(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'games').mkdir()
            with sqlite3.connect(root / 'pga.db') as db:
                db.execute('CREATE TABLE games (id INTEGER, name TEXT, executable TEXT, directory TEXT, configpath TEXT)')
                db.execute('INSERT INTO games VALUES (42, "Example", "/old/game.exe", "/old", "example")')
            config = root / 'games/example.yml'
            config.write_text('game:\n  exe: /games/example/bin/game.exe\n  working_dir: /games/example\n')
            plugin = discover_plugins()['LutrisIntegration']
            with patch.dict(plugin.import_games.__globals__, {'LUTRIS': root}):
                game = plugin.import_games()[0]
                self.assertEqual(game['Executable'], '/games/example/bin/game.exe')
                self.assertEqual(game['InstallDirectory'], '/games/example')
                config.write_text('game:\n  exe: /games/example/bin/game.exe\n')
                self.assertEqual(plugin.import_games()[0]['InstallDirectory'], '/games/example/bin')
