"""Read runner identifiers from the native Lutris installation."""
import json
import shutil
import subprocess
from .registration import LUTRIS, normalize_runner
from .runtime import inventory_command, environment, library_path


def runner_choices():
    # Use Lutris's own Python environment, independently of Playlite's venv.
    script = ('import json; from lutris.util.wine.wine import get_installed_wine_versions; '
              'print(json.dumps(get_installed_wine_versions()))')
    try:
        command = inventory_command(script)
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=10, env=environment())
        versions = json.loads(result.stdout)
        if not isinstance(versions, list) or not all(isinstance(item, str) for item in versions):
            raise ValueError('Invalid Lutris runner inventory.')
    except (OSError, ValueError, subprocess.SubprocessError):
        # Native installations without importable Python modules can still use
        # Lutris-managed Wine builds and the standard GE-Proton sentinel.
        versions = [path.name for path in (library_path(LUTRIS) / 'runners/wine').glob('*')
                    if (path / 'bin/wine').is_file()]
        if shutil.which('wine'):
            versions.append('system')
    versions = set(versions) | {'ge-proton'}
    versions.discard('custom')  # Requires a separate custom executable field.
    labels = {'ge-proton': 'GE-Proton (Latest)', 'system': 'System Wine',
              'winehq-devel': 'WineHQ Devel', 'winehq-staging': 'WineHQ Staging',
              'wine-development': 'Wine Development'}
    return [(labels.get(version, version), version) for version in
            sorted(versions, key=lambda value: (value != 'ge-proton', value.casefold()))]


def validate_runner(runner, choices=None):
    runner = normalize_runner(runner or '')
    if runner not in {version for _, version in (runner_choices() if choices is None else choices)}:
        raise ValueError('Choose an available Lutris Wine runner. The selected runner is no longer available.')
    return runner
