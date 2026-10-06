from playlite.manual_installation import ManualInstallation
from pathlib import Path
import re
from PyQt6.QtWidgets import QComboBox, QCheckBox, QHBoxLayout, QSizePolicy, QPushButton
from playlite.providers import InstallationPlugin, discover_plugins
from .registration import plan, normalize_runner
from .runners import validate_runner


class Plugin(InstallationPlugin):
    description = 'Creates a Lutris entry when you save, then links it to Playlite.'

    def create_editor(self, editor, game):
        plugins = discover_plugins()
        self.manual = ManualInstallation()
        self.lutris = plugins['LutrisIntegration']
        widget = self.manual.create_editor(editor, game, directory_defaults=self.lutris.directory_defaults(), extra_fields=[dict(key='LutrisId', label='Lutris game ID', positive_id=True)])
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
            if not selected:
                return
            try:
                relative = Path(selected).resolve().relative_to(Path(root).resolve()) if root else None
            except (ValueError, OSError):
                relative = None
            if relative is not None and not relative.parts:
                return
            name = relative.parts[0] if relative is not None else Path(selected).name
            installation = str(Path(root).resolve() / name) if relative is not None else selected
            if widget.fields['InstallDirectory'].text() != installation:
                from PyQt6.QtCore import QSignalBlocker
                with QSignalBlocker(widget.fields['InstallDirectory']):
                    widget.fields['InstallDirectory'].setText(installation)
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
        widget.fields['Executable'].textChanged.connect(autofill)
        autofill()
        widget.runner = QComboBox()
        widget.runner.setObjectName('WineRunner')
        widget.runner.setFixedHeight(widget.fields['Prefix'].height())
        widget.runner.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        selected_runner = normalize_runner(game.get('WineRunner') or 'ge-proton')
        widget.runner_choices = None
        runner_row = QHBoxLayout()
        runner_row.setSpacing(8)
        runner_row.addWidget(widget.runner)
        browse = widget.findChild(QPushButton, 'browsePrefix')
        widget.refresh_runners = QPushButton('Refresh')
        widget.refresh_runners.setFixedSize(browse.sizeHint().width(), widget.runner.height())
        runner_row.addWidget(widget.refresh_runners)
        widget.layout().insertRow(3, 'Wine runner', runner_row)
        from .runner_loader import RunnerLoader
        widget.runner_loader = RunnerLoader(widget)

        def loaded(choices):
            widget.runner_choices = choices
            widget.runner.clear()
            for title, version in choices:
                widget.runner.addItem(title, version)
            index = widget.runner.findData(widget.selected_runner)
            if index < 0:
                widget.runner.addItem(f'{widget.selected_runner} (unavailable)', widget.selected_runner)
                index = widget.runner.count() - 1
                widget.runner.model().item(index).setEnabled(False)
            widget.runner.setCurrentIndex(index)
            widget.runner.setEnabled(True)
            widget.runner.setToolTip('')
            widget.refresh_runners.setEnabled(True)

        def failed(message):
            widget.runner.clear()
            widget.runner.addItem('Could not load runners')
            widget.runner.setToolTip(message)
            widget.refresh_runners.setEnabled(True)

        def refresh():
            widget.selected_runner = widget.runner.currentData() or selected_runner
            widget.runner_choices = None
            widget.runner.clear()
            widget.runner.addItem('Loading runners…')
            widget.runner.setEnabled(False)
            widget.refresh_runners.setEnabled(False)
            widget.runner_loader.refresh()

        widget.runner_loader.loaded.connect(loaded)
        widget.runner_loader.failed.connect(failed)
        widget.refresh_runners.clicked.connect(refresh)
        refresh()
        widget.create_prefix = QCheckBox('Create prefix folder if it does not exist')
        widget.create_prefix.setChecked(True)
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
        if widget.runner_choices is None:
            raise ValueError('Wait for Lutris runners to load, or refresh and try again.')
        runner = validate_runner(widget.runner.currentData(), widget.runner_choices)
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
        game.update(GameProvider='LutrisIntegration', LutrisId=result['id'], Prefix=result['prefix'])
        widget.fields['LutrisId'].setText(str(result['id']))
        return game

    cli_name = 'add-lutris'

    def configure_cli(self, parser):
        ManualInstallation().configure_cli(parser)
        parser.add_argument('--steam-id', default='')
        parser.add_argument('--lutris-id', default='')
        parser.add_argument('--runner', default='ge-proton')
        parser.add_argument('--create-prefix', action='store_true')

    def cli_game(self, args, plugins):
        for value in (args.steam_id, args.lutris_id):
            if value and (not value.isascii() or not value.isdigit() or int(value) < 1):
                raise ValueError('Game IDs must be positive whole numbers.')
        game = ManualInstallation().cli_game(args, plugins)
        game['LutrisId'] = args.lutris_id
        game['MetadataIds'] = {'SteamMetadata': args.steam_id} if args.steam_id else {}
        if not game['Prefix'] or not game['Executable'] or not game['InstallDirectory']:
            raise ValueError('Provide --exe, --folder (or executable folder), and --prefix.')
        registration = plan(game['Executable'], game['Name'], installation_directory=game['InstallDirectory'], prefix=game['Prefix'])
        if not registration.prefix.exists() and not args.create_prefix:
            raise ValueError('Choose an existing prefix or pass --create-prefix.')
        game['WineRunner'] = validate_runner(args.runner)
        game['InstallationMethod'] = self.id
        return game

    def validate_cli_library(self, game, games):
        if game.get('LutrisId') and any(str(entry.get('LutrisId')) == str(game['LutrisId']) for entry in games):
            raise ValueError('This Lutris game is already in Playlite.')

    def cli_commit(self, args, game, plugins):
        registration = plan(game['Executable'], game['Name'], installation_directory=game['InstallDirectory'], prefix=game['Prefix'])
        result = plugins['LutrisIntegration'].register(registration, args.runner, args.arguments)
        game.update(GameProvider='LutrisIntegration', LutrisId=result['id'], Prefix=result['prefix'])
        return game
