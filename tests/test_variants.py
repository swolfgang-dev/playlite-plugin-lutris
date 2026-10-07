from contextlib import closing
import importlib.util
import sys
from pathlib import Path
import sqlite3
import tempfile
import unittest
import yaml

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('variant_lutris_test',root/'__init__.py',submodule_search_locations=[str(root)])
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
from variant_lutris_test.variants import create_variant,launch_configuration
from variant_lutris_test.registration import existing_locations


class VariantTests(unittest.TestCase):
    def test_variant_preserves_original_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);lutris=root/'lutris';(lutris/'games').mkdir(parents=True)
            config={'game':{'exe':'/games/Example/bin/game.exe','prefix':'/prefix/example','args':'--keep'},'wine':{'version':'ge-proton','dll_overrides':{'other':'n'}},'system':{'env':{'KEEP':'yes'},'gamemode':True}}
            source=lutris/'games/original.yml';source.write_text(yaml.safe_dump(config));original=source.read_bytes()
            with closing(sqlite3.connect(lutris/'pga.db')) as db, db:
                db.execute('CREATE TABLE games(id INTEGER PRIMARY KEY,name,sortname,slug,runner,executable,directory,installed,configpath,playtime)')
                db.execute('INSERT INTO games VALUES (1,?,?,?,?,?,?,?,?,?)',('Example','Example','example','wine','/games/Example/bin/game.exe','/games/Example',1,'original',120))
            result=create_variant(1,'Example - Modded','BepInEx',{'WINEDLLOVERRIDES':'winhttp=n,b'},{'winhttp':'n,b'},lutris,root/'state')
            again=create_variant(1,'Example - Modded','BepInEx',lutris=lutris,state=root/'state')
            self.assertEqual(result['id'],again['id']);self.assertTrue(again['reused'])
            self.assertEqual(source.read_bytes(),original)
            self.assertEqual(existing_locations('/games/Example/bin/game.exe',lutris),('/games/Example','/prefix/example'))
            new=launch_configuration(result['id'],lutris)
            self.assertEqual(new['game']['working_dir'],'/games/Example/bin')
            self.assertEqual(new['game']['prefix'],'/prefix/example');self.assertEqual(new['game']['args'],'--keep')
            self.assertEqual(new['wine']['version'],'ge-proton')
            self.assertEqual(new['wine']['dll_overrides'],{'other':'n','winhttp':'n,b'})
            self.assertEqual(new['system']['env']['KEEP'],'yes')
            self.assertEqual(new['system']['env']['WINEDLLOVERRIDES'],'winhttp=n,b')
            with closing(sqlite3.connect(lutris/'pga.db')) as db, db:self.assertEqual(db.execute('SELECT COUNT(*) FROM games').fetchone()[0],2)
