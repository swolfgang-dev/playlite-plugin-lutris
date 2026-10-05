"""Keep database paths, runner discovery, and launch commands on one Lutris install."""
import os
from pathlib import Path
import shutil

APP_ID = 'net.lutris.Lutris'


def installation(home=None, data_home=None):
    home = Path(home or Path.home())
    native = Path(data_home or os.environ.get('XDG_DATA_HOME', str(home / '.local/share'))) / 'lutris'
    flatpak = home / '.var/app' / APP_ID / 'data/lutris'
    if not (native / 'pga.db').is_file() and (flatpak / 'pga.db').is_file():
        return flatpak, True
    return native, False


LUTRIS, FLATPAK = installation()


def launch_command(uri):
    executable = shutil.which('flatpak' if FLATPAK else 'lutris')
    if not executable:
        raise ValueError('Install Lutris to launch this game.')
    return [executable, 'run', APP_ID, uri] if FLATPAK else [executable, uri]


def inventory_command(script):
    if FLATPAK:
        executable = shutil.which('flatpak')
        if not executable:
            raise OSError('Flatpak is not installed.')
        return [executable, 'run', '--command=python3', APP_ID, '-c', script]
    return ['/usr/bin/python3', '-c', script]
