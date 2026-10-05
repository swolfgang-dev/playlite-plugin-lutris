"""Identify Lutris sessions using their UUID and game paths, never client lifetime."""
import os
from pathlib import Path


def process_snapshot(proc=Path('/proc')):
    records = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            stat = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if stat[0] == 'Z':
                continue
            env = dict(value.split('=', 1) for value in (entry / 'environ').read_bytes().decode(
                errors='replace').split('\0') if '=' in value)
            session = env.get('LUTRIS_GAME_UUID')
            if not session:
                continue
            args = (entry / 'cmdline').read_bytes().decode(errors='replace').strip('\0').split('\0')
            records.append({'pid': int(entry.name), 'start': stat[19], 'session': session,
                            'args': args, 'cwd': os.readlink(entry / 'cwd'),
                            'exe': os.readlink(entry / 'exe'),
                            'prefix': env.get('WINEPREFIX') or env.get('STEAM_COMPAT_DATA_PATH', '')})
        except (OSError, ValueError, IndexError):
            continue
    return records


def normalized(path):
    return os.path.realpath(os.path.expanduser(str(path))) if path else ''


def inside(path, folder):
    return bool(path and folder and (path == folder or path.startswith(folder + os.sep)))


def matches(game, processes):
    executable = normalized(game.get('Executable'))
    folder = normalized(game.get('InstallDirectory'))
    prefix = normalized(game.get('Prefix'))
    if not executable and not folder:
        return False
    for process in processes:
        process_prefix = normalized(process.get('prefix'))
        if prefix and process_prefix and process_prefix != prefix:
            continue
        args = process.get('args', [])
        paths = [normalized(process.get('exe'))]
        for arg in args:
            if arg.startswith('/'):
                paths.append(normalized(arg))
            elif len(arg) > 2 and arg[1:3] in (':\\', ':/') and prefix:
                drive = arg[0].lower()
                tail = arg[3:].replace('\\', '/')
                paths.append(normalized(Path(prefix) / ('drive_c' if drive == 'c' else f'dosdevices/{drive}:') / tail))
            elif arg.lower().endswith('.exe') and not arg.startswith('-'):
                paths.append(normalized(Path(process.get('cwd') or '/') / arg))
        if executable and executable in paths:
            return True
        # The Lutris wrapper owns the session, including launcher hand-offs.
        wrapper = any('lutris-wrapper' in arg for arg in args)
        if wrapper and inside(normalized(process.get('cwd')), folder):
            return True
    return False


def detect_running(games, records):
    sessions = {}
    for process in records:
        if process.get('session'):
            sessions.setdefault(process['session'], []).append(process)
    running = set()
    for processes in sessions.values():
        matches_ids = {game['Id'] for game in games if matches(game, processes)}
        if len(matches_ids) == 1:
            running.update(matches_ids)
    return running
