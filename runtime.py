"""Keep database paths, runner discovery, and launch commands on one Lutris install."""
import os
from pathlib import Path
import shutil
import pwd

APP_ID = 'net.lutris.Lutris'


def environment():
    """Lutris belongs to the desktop user, outside Playlite's private profile."""
    env = dict(os.environ)
    if env.get('PLAYLITE_PROFILE') == 'repo':
        env['HOME'] = env.get('PLAYLITE_HOST_HOME') or pwd.getpwuid(os.getuid()).pw_dir
        for name in ('DATA', 'CONFIG', 'CACHE', 'STATE'):
            variable = f'XDG_{name}_HOME'
            saved = env.get(f'PLAYLITE_HOST_{variable}')
            if saved:
                env[variable] = saved
            else:
                env.pop(variable, None)
    return env


def installation(home=None, data_home=None):
    env = environment()
    home = Path(home or env.get('HOME') or Path.home())
    native = Path(data_home or env.get('XDG_DATA_HOME') or str(home / '.local/share')) / 'lutris'
    flatpak = home / '.var/app' / APP_ID / 'data/lutris'
    if not (native / 'pga.db').is_file() and (flatpak / 'pga.db').is_file():
        return flatpak, True
    return native, False


def library_override():
    from PyQt6.QtCore import QSettings
    return QSettings('Playlite', 'Lutris').value('LibraryDirectory', '', type=str).strip()


def library_path(fallback=None):
    selected = library_override()
    return Path(selected).expanduser() if selected else (fallback if fallback is not None else LUTRIS)


def is_flatpak():
    selected = library_override()
    return (APP_ID in Path(selected).parts or FLATPAK) if selected else FLATPAK


LUTRIS, FLATPAK = installation()


def launch_command(uri):
    executable = shutil.which('flatpak' if is_flatpak() else 'lutris')
    if not executable:
        raise ValueError('Install Lutris to launch this game.')
    return [executable, 'run', APP_ID, uri] if is_flatpak() else [executable, uri]


def inventory_command(script):
    if is_flatpak():
        executable = shutil.which('flatpak')
        if not executable:
            raise OSError('Flatpak is not installed.')
        return [executable, 'run', '--command=python3', APP_ID, '-c', script]
    return ['/usr/bin/python3', '-c', script]
