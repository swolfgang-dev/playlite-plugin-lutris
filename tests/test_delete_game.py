from plugin_test_support import require_plugin
require_plugin('Lutris')
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from playlite_plugins.lutris.registration import delete_lutris_entry


class DeleteGameTests(unittest.TestCase):
    def test_lutris_delete_keeps_other_entries_and_game_files(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            lutris = root / 'lutris'
            lutris.mkdir()
            game_file = root / 'game.exe'
            game_file.write_bytes(b'keep')
            with sqlite3.connect(lutris / 'pga.db') as db:
                db.execute('CREATE TABLE games (id INTEGER PRIMARY KEY, name TEXT)')
                db.executemany('INSERT INTO games VALUES (?, ?)', [(1, 'Delete'), (2, 'Keep')])
            backup = delete_lutris_entry(1, lutris, root / 'state')
            with sqlite3.connect(lutris / 'pga.db') as db:
                self.assertEqual(db.execute('SELECT id FROM games').fetchall(), [(2,)])
            with sqlite3.connect(backup) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM games').fetchone()[0], 2)
            self.assertEqual(game_file.read_bytes(), b'keep')
