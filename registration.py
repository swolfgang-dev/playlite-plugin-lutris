"""Standalone game registration; never runs the selected executable."""
import fcntl
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path.home() / 'Games'
PREFIXES = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'playlite/prefixes'
from .runtime import LUTRIS, library_path
STATE = Path.home() / '.local/state/playlite'


def atomic_json(path, data):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class Plan:
    name: str
    exe: Path
    directory: Path
    prefix: Path
    slug: str


def plan(executable, name='', root=ROOT, prefixes=PREFIXES, installation_directory='', prefix=''):
    exe = Path(executable).resolve(strict=True)
    if installation_directory:
        directory = Path(installation_directory).expanduser()
        if not directory.is_absolute():
            raise ValueError('Installation folder must be an absolute path.')
        directory = directory.resolve(strict=True)
        if not directory.is_dir() or not exe.is_relative_to(directory):
            raise ValueError('The executable must be inside the installation folder.')
    else:
        relative = exe.relative_to(root.resolve())
        if len(relative.parts) < 2:
            raise ValueError('Select an executable inside a game folder.')
        directory = root / relative.parts[0]
    if not exe.is_file() or exe.suffix.lower() != '.exe':
        raise ValueError('Select a Windows .exe.')
    name = name.strip() or directory.name
    if any(ord(c) < 32 for c in name):
        raise ValueError('Game names cannot contain control characters.')
    slug = re.sub(r'[^a-z0-9]+', '-', directory.name.lower()).strip('-') or 'game'
    prefix_path = Path(prefix).expanduser() if prefix else prefixes / slug
    if not prefix_path.is_absolute():
        raise ValueError('Prefix location must be an absolute path.')
    if prefix_path.exists() and not prefix_path.is_dir():
        raise ValueError('Prefix location must be a directory.')
    return Plan(name, exe, directory, prefix_path, slug)


def existing_locations(executable, lutris=None):
    lutris = lutris if lutris is not None else library_path(LUTRIS)
    database = lutris / 'pga.db'
    if not database.is_file():
        return None
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        rows = db.execute('SELECT directory, configpath FROM games WHERE executable = ?',
                          (str(Path(executable).resolve()),)).fetchall()
    if len(rows) != 1 or not rows[0][1]:
        return None
    config = lutris / 'games' / (rows[0][1] + '.yml')
    if not config.is_file():
        return None
    saved = yaml.safe_load(config.read_text()) or {}
    return rows[0][0], saved.get('game', {}).get('prefix', '')


def normalize_runner(runner):
    runner = runner.strip()
    return 'ge-proton' if runner.casefold() in ('ge-proton', 'ge-proton (latest)') else runner


def register(p, runner='ge-proton', lutris=None, state=STATE, arguments=''):
    lutris = lutris if lutris is not None else library_path(LUTRIS)
    if not runner.strip() or any(ord(c) < 32 for c in runner):
        raise ValueError('Choose a Wine runner.')
    runner = normalize_runner(runner)
    database = lutris / 'pga.db'
    if not database.is_file():
        raise ValueError('Lutris database not found. Open Lutris once first.')
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'registration.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with closing(sqlite3.connect(database, timeout=10)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            matches = db.execute('SELECT * FROM games WHERE executable = ?', (str(p.exe),)).fetchall()
            if len(matches) > 1:
                raise ValueError('Multiple Lutris entries use this executable. Resolve them in Lutris first.')
            existing = matches[0] if matches else None
            if existing and (existing['runner'] != 'wine' or not existing['installed']):
                raise ValueError('This executable has an incompatible Lutris entry. Edit it in Lutris first.')
            config = None
            original_config = None
            request = None
            prefix_created = False
            try:
                backup = state / ('lutris-before-' + uuid.uuid4().hex + '.db')
                with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(backup)) as destination:
                    source.backup(destination)
                if not p.prefix.exists():
                    p.prefix.mkdir(parents=True)
                    prefix_created = True
                if existing:
                    game_id = existing['id']
                    config_file = lutris / 'games' / (existing['configpath'] + '.yml')
                    if not config_file.is_file():
                        raise ValueError('Existing Lutris entry is missing its configuration.')
                    saved = yaml.safe_load(config_file.read_text())
                    actual_prefix = str(p.prefix)
                    if (saved.get('game', {}).get('prefix') != actual_prefix or
                            existing['directory'] != str(p.directory) or
                            saved.get('game', {}).get('working_dir') != str(p.exe.parent) or
                            saved.get('game', {}).get('args', '') != arguments or
                            saved.get('wine', {}).get('version') != runner):
                        original_config = config_file.read_bytes()
                        (state / (backup.stem + '.yml')).write_bytes(original_config)
                        config = config_file
                        saved.setdefault('game', {})['prefix'] = actual_prefix
                        saved['game']['working_dir'] = str(p.exe.parent)
                        saved['game']['args'] = arguments
                        saved.setdefault('wine', {})['version'] = runner
                        temp_config = config.with_suffix('.yml.tmp')
                        temp_config.write_text(yaml.safe_dump(saved))
                        os.replace(temp_config, config)
                        db.execute('UPDATE games SET directory = ? WHERE id = ?', (str(p.directory), game_id))
                else:
                    conflicts = db.execute('SELECT name FROM games WHERE directory = ? OR slug = ?',
                                           (str(p.directory), p.slug)).fetchall()
                    if conflicts:
                        raise ValueError('This game folder or slug already has a Lutris entry. Select its registered executable or edit it in Lutris.')
                    config_name = p.slug + '-standalone-manager-' + uuid.uuid4().hex[:8]
                    config = lutris / 'games' / (config_name + '.yml')
                    config.parent.mkdir(parents=True, exist_ok=True)
                    if p.prefix.exists() and not p.prefix.is_dir():
                        raise ValueError('The prefix path exists but is not a directory.')
                    if not p.prefix.exists():
                        p.prefix.mkdir(parents=True)
                        prefix_created = True
                    actual_prefix = str(p.prefix)
                    with config.open('x') as stream:
                        yaml.safe_dump({'game': {'exe': str(p.exe), 'working_dir': str(p.exe.parent),
                                                'prefix': str(p.prefix), 'args': arguments},
                                        'wine': {'version': runner}, 'system': {'gamemode': False}}, stream)
                    game_id = db.execute('''INSERT INTO games
                        (name,sortname,slug,platform,runner,executable,directory,installed,installed_at,configpath,playtime,service)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (p.name,p.name,p.slug,'Windows','wine',str(p.exe),str(p.directory),1,int(time.time()),config_name,0,'manual')).lastrowid
                db.commit()
                return {'id': game_id, 'reused': bool(existing), 'prefix': actual_prefix,
                        'link': 'lutris:rungameid/' + str(game_id)}
            except Exception:
                # Once committed, retain registration and staged request for recovery.
                if db.in_transaction:
                    db.rollback()
                    if config:
                        if original_config is not None:
                            config.write_bytes(original_config)
                        else:
                            config.unlink(missing_ok=True)
                    if request:
                        request.unlink(missing_ok=True)
                    if prefix_created:
                        p.prefix.rmdir()
                raise


def delete_lutris_entry(game_id, lutris=None, state=STATE):
    lutris = lutris if lutris is not None else library_path(LUTRIS)
    """Remove a launcher entry, retaining the game's files and Wine prefix."""
    database = lutris / 'pga.db'
    if not database.is_file():
        raise OSError('Lutris database not found.')
    game_id = int(game_id)
    state.mkdir(parents=True, exist_ok=True)
    backup = state / f'lutris-before-delete-{game_id}-{uuid.uuid4().hex}.db'
    with closing(sqlite3.connect(database, timeout=10)) as db:
        with closing(sqlite3.connect(backup)) as destination:
            db.backup(destination)
        with db:
            db.execute('DELETE FROM games WHERE id = ?', (game_id,))
    # Keep the launch configuration with the backup for recovery.
    return backup
