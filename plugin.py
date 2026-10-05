import shutil
import sqlite3
import subprocess
import uuid
import time
from pathlib import Path
from contextlib import closing
from playlite.providers import IntegrationPlugin
from .registration import LUTRIS, register


class Plugin(IntegrationPlugin):
    settings_group = 'installation'
    action_id_field = 'LutrisId'

    def validate_action(self, action):
        identity = action.get('GameId') or ''
        if identity and (not identity.isascii() or not identity.isdigit() or int(identity) < 1):
            raise ValueError('Lutris play actions need a positive numeric game ID.')

    supports_entry_deletion = True

    def delete_entry(self, game):
        from .registration import delete_lutris_entry
        from playlite.play_actions import actions_for
        identities = {action.get('GameId') for action in actions_for(game, [self]) if action.get('Integration') == self.id}
        backups = []
        try:
            for identity in identities:
                if identity:
                    backups.append(delete_lutris_entry(identity))
        except Exception:
            self.restore_deleted_entry(backups)
            raise
        return backups

    def restore_deleted_entry(self, backups):
        from contextlib import closing
        for backup in reversed(backups):
            with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(LUTRIS / 'pga.db')) as destination:
                source.backup(destination)

    def installation_methods(self):
        from .add import Plugin as Add
        from .import_games import Plugin as Import
        methods = []
        for cls, identity, name in [(Add, 'LutrisAdd', 'Add to Lutris'),
                                    (Import, 'LutrisImport', 'Import from Lutris')]:
            method = cls()
            method.id, method.name, method.type = identity, name, 'installation'
            method.version = self.version
            methods.append(method)
        return methods

    def detect_running(self, games):
        from .detection import detect_running, process_snapshot
        games = [game for game in games if self.owns(game)]
        from playlite.play_actions import action_game
        games = [action_game(game, action, self) for game in games
                 for action in (game.get('PlayActions') if 'PlayActions' in game else
                                [dict(Integration=self.id)]) or []
                 if action.get('Integration') == self.id]
        if not games:
            return set()
        if time.monotonic() - getattr(self, '_detection_config_time', -100) > 10:
            try:
                self._detection_configs = {str(game['LutrisId']): game for game in self.import_games()}
            except (ValueError, OSError, sqlite3.Error):
                self._detection_configs = {}
            self._detection_config_time = time.monotonic()
        resolved = []
        for game in games:
            imported = getattr(self, '_detection_configs', {}).get(str(game.get('LutrisId')), {})
            values = dict(game)
            for key in ('Executable', 'InstallDirectory', 'Prefix'):
                values[key] = game.get(key) or imported.get(key)
            resolved.append(values)
        return detect_running(resolved, process_snapshot())

    def association_id(self, game):
        return game.get('LutrisId')
    def owns(self, game):
        if 'PlayActions' in game:
            return any(action.get('Integration') == self.id for action in game['PlayActions'] or [])
        if 'GameProvider' in game:
            return game.get('GameProvider') == self.id
        return bool(game.get('LutrisId'))

    def launch(self, game):
        if not str(game.get('LutrisId') or '').isascii() or not str(game.get('LutrisId') or '').isdigit():
            raise ValueError('Set a valid Lutris game ID on the Installation page.')
        executable = shutil.which('lutris')
        if not executable:
            raise ValueError('Install Lutris to launch this game.')
        return subprocess.Popen([executable, f'lutris:rungameid/{game["LutrisId"]}'], start_new_session=True)

    def register(self, registration, runner, arguments=''):
        return register(registration, runner=runner, arguments=arguments)

    def import_games(self):
        database = LUTRIS / 'pga.db'
        if not database.is_file():
            raise ValueError('Lutris database not found. Open Lutris once first.')
        with closing(sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            entries = db.execute('SELECT * FROM games').fetchall()
        games = []
        for entry in entries:
            row = dict(entry)
            config = {}
            config_name = row.get('configpath')
            if config_name and '/' not in config_name and '\\' not in config_name:
                config_file = LUTRIS / 'games' / (config_name + '.yml')
                if config_file.is_file():
                    import yaml
                    config = (yaml.safe_load(config_file.read_text()) or {}).get('game', {}) or {}
            executable = config.get('exe') or row.get('executable') or ''
            working_directory = config.get('working_dir') or ''
            if executable:
                executable = str(Path(executable).expanduser())
            if working_directory:
                working_directory = str(Path(working_directory).expanduser())
            directory = working_directory or (str(Path(executable).parent) if executable else '')
            games.append({'Id': str(uuid.uuid4()), 'Name': row['name'], 'GameProvider': self.id,
                          'LutrisId': row['id'], 'Executable': executable,
                          'InstallDirectory': directory, 'Source': 'Lutris',
                          'Prefix': config.get('prefix') or '', 'LaunchArguments': config.get('args') or '',
                          'IsInstalled': bool(row.get('installed'))})
        return games

    def create_settings(self, parent=None):
        from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        description = QLabel('Imports or creates Lutris entries, launches through Lutris, and detects running games using Lutris sessions and game paths.')
        description.setWordWrap(True)
        layout.addWidget(description)
        button = QPushButton('Open Lutris library folder')
        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LUTRIS))))
        layout.addWidget(button)
        layout.addStretch()
        return widget
