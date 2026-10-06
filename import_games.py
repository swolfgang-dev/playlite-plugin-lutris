from playlite.manual_installation import ManualInstallation
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QDialogButtonBox, QPushButton
from playlite.providers import InstallationPlugin, discover_plugins
from playlite.lifecycle import run_dialog, show_warning


class Plugin(InstallationPlugin):
    description = 'Select an existing Lutris game. Saving links it to Playlite without changing Lutris.'

    def create_editor(self, editor, game):
        plugins = discover_plugins()
        self.manual = ManualInstallation()
        widget = self.manual.create_editor(editor, game, extra_fields=[dict(key='LutrisId', label='Lutris game ID', positive_id=True)])
        button = QPushButton('Import from Lutris…')
        widget.import_button = button
        widget.layout().insertRow(0, '', button)
        widget.editor = editor
        button.clicked.connect(lambda: self.choose_game(widget, plugins['LutrisIntegration']))
        return widget

    def choose_game(self, widget, provider):
        editor = widget.editor
        try:
            games = provider.import_games()
            dialog = QDialog(editor)
            dialog.setWindowTitle('Import from Lutris')
            dialog.resize(480, 520)
            layout = QVBoxLayout(dialog)
            search = QLineEdit()
            search.setPlaceholderText('Search games')
            layout.addWidget(search)
            choices = QListWidget()
            layout.addWidget(choices)
            known = {str(game.get('LutrisId')) for game in getattr(editor.parent(), 'games', []) if game.get('LutrisId')}
            for game in sorted(games, key=lambda game: game['Name'].casefold()):
                if str(game['LutrisId']) in known:
                    continue
                item = QListWidgetItem(f"{game['Name']} — {game['LutrisId']}")
                item.setData(Qt.ItemDataRole.UserRole, game)
                choices.addItem(item)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
            select = buttons.addButton('Import selected', QDialogButtonBox.ButtonRole.AcceptRole)
            select.setEnabled(False)
            def update():
                item = choices.currentItem()
                select.setEnabled(item is not None and not item.isHidden())
            def filter_games(query):
                for index in range(choices.count()):
                    item = choices.item(index)
                    item.setHidden(query.casefold() not in item.text().casefold())
                update()
            search.textChanged.connect(filter_games)
            choices.currentItemChanged.connect(lambda *_: update())
            select.clicked.connect(dialog.accept)
            choices.itemDoubleClicked.connect(lambda *_: dialog.accept())
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if run_dialog(dialog) != QDialog.DialogCode.Accepted:
                return
            item = choices.currentItem()
            if item is None or item.isHidden():
                return
            selected = item.data(Qt.ItemDataRole.UserRole)
            editor.apply_metadata({key: value for key, value in selected.items() if key != 'Id'})
            editor.game['GameProvider'] = 'LutrisIntegration'
            editor.flags['IsInstalled'].setChecked(selected.get('IsInstalled', False))
        except Exception as error:
            show_warning(editor, 'Cannot import from Lutris', str(error))

    def collect(self, widget, game):
        game = self.manual.collect(widget, game)
        if not game.get('LutrisId'):
            raise ValueError('Select a Lutris game first.')
        game['InstallationMethod'] = self.id
        game['GameProvider'] = 'LutrisIntegration'
        return game

    cli_name = 'import-lutris'

    def configure_cli(self, parser):
        parser.add_argument('--lutris-id', type=int, required=True)

    def cli_game(self, args, plugins):
        game = next((game for game in plugins['LutrisIntegration'].import_games() if game['LutrisId'] == args.lutris_id), None)
        if game is None:
            raise ValueError('Lutris game ID not found.')
        game['InstallationMethod'] = self.id
        return game
