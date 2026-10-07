import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('lutris_stop_test', ROOT / 'plugin.py', submodule_search_locations=[str(ROOT)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class StopSession(unittest.TestCase):
    def test_selected_session_only_and_keeps_steam_client(self):
        plugin = module.Plugin()
        plugin.id = 'LutrisIntegration'
        game = {'Id': 'game', 'Executable': '/games/example.exe', 'PlayActions': [
            {'Name': 'Play', 'Integration': plugin.id, 'GameId': '1', 'Executable': '/games/example.exe'}]}
        records = [dict(pid=1, start='a', session='one', exe='/games/example.exe'),
                   dict(pid=2, start='b', session='one', exe='/usr/bin/steam'),
                   dict(pid=3, start='c', session='two', exe='/games/other.exe')]
        with patch.object(plugin, 'import_games', return_value=[]), patch('lutris_stop_test.detection.process_snapshot', return_value=records), patch('playlite.process_control.terminate_processes', side_effect=lambda selected: list(selected)):
            self.assertEqual(plugin.stop(game), records[:1])
