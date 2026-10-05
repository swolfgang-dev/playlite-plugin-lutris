from playlite.manual_installation import ManualInstallation
from pathlib import Path
import re
from PyQt6.QtWidgets import QLineEdit, QCheckBox
from playlite.providers import InstallationPlugin, discover_plugins
from .registration import plan


class Plugin(InstallationPlugin):
    description = 'Creates a Lutris entry when you save, then links it to Playlite.'

    def create_editor(self, editor, game):
        plugins = discover_plugins()
        self.manual = ManualInstallation()
        self.lutris = plugins['Lutris']
        widget = self.manual.create_editor(editor, game, directory_defaults=self.lutris.directory_defaults())
        defaults = self.lutris.directory_defaults()
        widget.autofilled_name = ''
        widget.autofilled_prefix = ''
        name_field = editor.fields.get('Name')
        # Add Game initially names an executable after its containing folder.
        initial_directory_name = Path(game.get('Executable') or '/').parent.name
        initial_name = name_field.text() if name_field is not None else ''
        if initial_name == initial_directory_name:
            widget.autofilled_name = initial_name

        def autofill(*unused):
            root = defaults.get('InstallDirectory', '')
            selected = widget.fields['InstallDirectory'].text().strip()
            if not root or not selected:
                return
            try:
                relative = Path(selected).resolve().relative_to(Path(root).resolve())
            except (ValueError, OSError):
                return
            if not relative.parts:
                return
            name = relative.parts[0]
            if name_field is not None and (not name_field.text().strip() or name_field.text() == widget.autofilled_name):
                name_field.setText(name)
                widget.autofilled_name = name
            prefix_root = defaults.get('Prefix', '')
            words = re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', name)
            words = re.sub(r'([A-Z])([A-Z][a-z])', r'\1-\2', words)
            slug = re.sub(r'[^\w]+', '-', words.casefold().replace('_', '-')).strip('-')
            prefix_field = widget.fields['Prefix']
            if prefix_root and slug and (not prefix_field.text().strip() or prefix_field.text() == widget.autofilled_prefix):
                prefix = str(Path(prefix_root) / slug)
                prefix_field.setText(prefix)
                widget.autofilled_prefix = prefix
        widget.fields['InstallDirectory'].textChanged.connect(autofill)
        autofill()
        widget.runner = QLineEdit(game.get('WineRunner') or 'GE-Proton')
        widget.layout().insertRow(3, 'Wine runner', widget.runner)
        widget.create_prefix = QCheckBox('Create prefix folder if it does not exist')
        widget.layout().insertRow(4, '', widget.create_prefix)
        widget.fields['LutrisId'].setReadOnly(True)
        widget.fields['LutrisId'].setPlaceholderText('Assigned on save')
        return widget

    def collect(self, widget, game):
        game = self.manual.collect(widget, game)
        if not game.get('Executable') or not game.get('InstallDirectory'):
            raise ValueError('Choose an executable and installation folder.')
        if not game.get('Prefix'):
            raise ValueError('Enter a Wine prefix location.')
        runner = widget.runner.text().strip()
        if not runner:
            raise ValueError('Enter a Wine runner.')
        registration = plan(game['Executable'], game['Name'],
                            installation_directory=game['InstallDirectory'], prefix=game['Prefix'])
        if not registration.prefix.exists() and not widget.create_prefix.isChecked():
            raise ValueError('Choose an existing prefix, or enable prefix folder creation.')
        widget.registration = registration
        game['WineRunner'] = runner
        game['InstallationMethod'] = self.id
        return game

    def commit(self, widget, game):
        result = self.lutris.register(widget.registration, game['WineRunner'], game.get('LaunchArguments', ''))
        game.update(GameProvider='Lutris', LutrisId=result['id'], Prefix=result['prefix'])
        widget.fields['LutrisId'].setText(str(result['id']))
        return game

    cli_name = 'add-lutris'

    def configure_cli(self, parser):
        ManualInstallation().configure_cli(parser)
        parser.add_argument('--runner', default='GE-Proton')
        parser.add_argument('--create-prefix', action='store_true')

    def cli_game(self, args, plugins):
        game = ManualInstallation().cli_game(args, plugins)
        if not game['Prefix'] or not game['Executable'] or not game['InstallDirectory']:
            raise ValueError('Provide --exe, --folder (or executable folder), and --prefix.')
        registration = plan(game['Executable'], game['Name'], installation_directory=game['InstallDirectory'], prefix=game['Prefix'])
        if not registration.prefix.exists() and not args.create_prefix:
            raise ValueError('Choose an existing prefix or pass --create-prefix.')
        if not args.runner.strip():
            raise ValueError('Enter --runner.')
        game['WineRunner'] = args.runner
        game['InstallationMethod'] = self.id
        return game

    def cli_commit(self, args, game, plugins):
        registration = plan(game['Executable'], game['Name'], installation_directory=game['InstallDirectory'], prefix=game['Prefix'])
        result = plugins['Lutris'].register(registration, args.runner, args.arguments)
        game.update(GameProvider='Lutris', LutrisId=result['id'], Prefix=result['prefix'])
        return game
