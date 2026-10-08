from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('lutris_ids_test', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
PACKAGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PACKAGE
SPEC.loader.exec_module(PACKAGE)
from lutris_ids_test.registration import plan, register
from lutris_ids_test.variants import create_variant


class RegistrationIdTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.lutris = self.root / 'lutris'
        self.lutris.mkdir()
        with closing(sqlite3.connect(self.lutris / 'pga.db')) as db:
            db.execute('CREATE TABLE games (id INTEGER PRIMARY KEY, name, sortname, slug, platform, runner, executable, directory, installed, installed_at, configpath, playtime, service)')

    def create(self, name, steam_id=None):
        exe = self.root / 'games' / name / 'game.exe'
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.touch()
        registration = plan(exe, root=self.root / 'games', prefixes=self.root / 'prefixes')
        return register(registration, lutris=self.lutris, state=self.root / 'state', steam_id=steam_id)

    def test_steam_id_is_used_in_database_and_launch_link_and_reused(self):
        first = self.create('Example', '123456')
        self.assertEqual(first['id'], 12345601)
        self.assertEqual(first['link'], 'lutris:rungameid/12345601')
        again = self.create('Example', '123456')
        self.assertEqual(again['id'], first['id'])
        self.assertTrue(again['reused'])

    def test_missing_steam_id_uses_automatic_id(self):
        self.assertEqual(self.create('Example')['id'], 1)

    def test_subsequent_entries_share_steam_prefix_with_unique_suffixes(self):
        self.assertEqual(self.create('Original', '123456')['id'], 12345601)
        self.assertEqual(self.create('Other', '123456')['id'], 12345602)
        self.assertEqual(self.create('Third', '123456')['id'], 12345603)

    def test_variants_use_next_suffix_and_reuse_existing_variants(self):
        base = self.create('Example', '123456')
        # Another launch entry occupies 02 before variants are created.
        self.create('Other', '123456')
        first = create_variant(base['id'], 'Modded', 'ModA', lutris=self.lutris, state=self.root / 'state')
        self.assertEqual(first['id'], 12345603)
        again = create_variant(base['id'], 'Modded', 'ModA', lutris=self.lutris, state=self.root / 'state')
        self.assertEqual(again['id'], first['id'])
        self.assertTrue(again['reused'])
        nested = create_variant(first['id'], 'More mods', 'ModB', lutris=self.lutris, state=self.root / 'state')
        self.assertEqual(nested['id'], 12345604)

    def test_exhausted_suffixes_leave_existing_entries_unchanged(self):
        with closing(sqlite3.connect(self.lutris / 'pga.db')) as db, db:
            db.executemany('INSERT INTO games (id) VALUES (?)', [(12345600 + n,) for n in range(1, 100)])
        with self.assertRaisesRegex(ValueError, 'in use'):
            self.create('Example', '123456')
        with closing(sqlite3.connect(self.lutris / 'pga.db')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM games').fetchone()[0], 99)

    def test_invalid_ids_leave_database_empty(self):
        for identity in ('0', '-1', 'abc', str(2**63)):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                self.create('Example', identity)
        with closing(sqlite3.connect(self.lutris / 'pga.db')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM games').fetchone()[0], 0)
