"""Discover runners off the GUI thread and deliver results to a live editor."""
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot
from .runners import runner_choices


class Signals(QObject):
    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)


class RunnerTask(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = Signals()

    def run(self):
        try:
            self.signals.loaded.emit(runner_choices())
        except Exception:
            self.signals.failed.emit('Could not load Lutris runners. Try refreshing.')


class RunnerLoader(QObject):
    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.task = None

    def refresh(self):
        if self.task is not None:
            return
        self.task = RunnerTask()
        self.task.signals.loaded.connect(self.complete)
        self.task.signals.failed.connect(self.failure)
        QThreadPool.globalInstance().start(self.task)

    @pyqtSlot(object)
    def complete(self, choices):
        self.task = None
        self.loaded.emit(choices)

    @pyqtSlot(str)
    def failure(self, message):
        self.task = None
        self.failed.emit(message)
