"""The shutdown sequence, visible (docs/design/shutdown.md; owner 2026-10-30: a protocol that disconnects the devices
when the program is closed). Used by Disconnect and by closing the window.

Steps, in order: stop the protocol, stop acquisition, close each device (magnet home + limits released, rotor, stage,
focus, iXon shutter closed / cooler off / warm-up / ShutDown, JAI, Arduino, light), release the rig lock. Each step
runs on a worker thread and is ticked in the dialog; the first failure stops the sequence, the dialog stays open with
the error and offers Retry (the remaining steps again) or "Close anyway" (the rig lock is then NOT released: the lock
file keeps saying the rig is not clean, RULES.md 3).

    d = ShutdownDialog(parent)
    d.exec()            # True when every step succeeded (the window may close), False on "Close anyway"
"""
import contextlib

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QPushButton, QVBoxLayout

from mtpy import api
from mtpy.api import events

OK, FAIL, TODO, RUN = "[ok]  ", "[FAIL]", "[  ]  ", "[...] "


def steps():
    """[(label, fn)] for what is connected now; each fn is idempotent, so Retry re-runs the rest safely."""
    st = api.devices.status()
    out = [("stop the protocol", lambda: api.protocol.running() and (api.protocol.stop(), api.protocol.wait(10))),
           ("stop acquisition (recording closed)", lambda: api.acq.running() and api.acq.stop())]
    names = [n for n in api.devices.CLOSE_ORDER if n in st] + [n for n in st if n not in api.devices.CLOSE_ORDER]
    notes = {"magnet": " (home 0 mm, limits released)", "stage": " (limits released)",
             "emccd": " (shutter closed, cooler off, warm-up to -20 C: minutes, ShutDown)"}
    out += [(f"close {n}{notes.get(n, '')}", lambda n=n: api.devices.close(n)) for n in names]
    out.append(("release the rig lock", api.devices.disconnect))      # also drops anything left over
    return out


class _Signals(QObject):
    step = Signal(int, str)       # index, "" = ok or the error text
    finished = Signal(bool)


class _Runner(QRunnable):
    def __init__(self, items, start):
        super().__init__()
        self.items, self.start, self.signals = items, start, _Signals()
        self.setAutoDelete(False)

    def run(self):
        with events.as_caller("gui"):
            for i in range(self.start, len(self.items)):
                try:
                    self.items[i][1]()
                except Exception as e:  # noqa: BLE001 - shown in the dialog, the sequence stops here
                    self.signals.step.emit(i, f"{type(e).__name__}: {e}")
                    self.signals.finished.emit(False)
                    return
                self.signals.step.emit(i, "")
        self.signals.finished.emit(True)


class ShutdownDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shutting down the rig")
        self.setModal(True)
        self.items = steps()
        self.list = QListWidget()
        for label, _ in self.items:
            self.list.addItem(TODO + label)
        self.msg = QLabel("Closing every device; the window stays open until the rig is clean.")
        self.msg.setWordWrap(True)
        self.buttons = QDialogButtonBox()
        self.btn_retry = QPushButton("Retry")
        self.btn_force = QPushButton("Close anyway (rig lock kept)")
        self.buttons.addButton(self.btn_retry, QDialogButtonBox.ActionRole)
        self.buttons.addButton(self.btn_force, QDialogButtonBox.DestructiveRole)
        self.buttons.setEnabled(False)
        self.btn_retry.clicked.connect(lambda: self._run(self.failed_at))
        self.btn_force.clicked.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.list)
        lay.addWidget(self.msg)
        lay.addWidget(self.buttons)
        self.failed_at = 0
        self._runner = None
        self.ok = False
        self._run(0)

    def _run(self, start):
        self.buttons.setEnabled(False)
        for i in range(start, len(self.items)):
            self.list.item(i).setText(TODO + self.items[i][0])
        if start < len(self.items):
            self.list.item(start).setText(RUN + self.items[start][0])
        self._runner = _Runner(self.items, start)
        self._runner.signals.step.connect(self._on_step)
        self._runner.signals.finished.connect(self._on_finished)
        QThreadPool.globalInstance().start(self._runner)

    def _on_step(self, i, err):
        label = self.items[i][0]
        self.list.item(i).setText((FAIL + label + "  -  " + err) if err else (OK + label))
        if err:
            self.failed_at = i
            self.msg.setText(f"Step failed: {err}\nThe rig lock is kept. Fix the cause and Retry, or close anyway "
                             "and report the state to the owner.")
        elif i + 1 < len(self.items):
            self.list.item(i + 1).setText(RUN + self.items[i + 1][0])

    def _on_finished(self, ok):
        self.ok = ok
        if ok:
            self.accept()
        else:
            self.buttons.setEnabled(True)

    def closeEvent(self, e):
        if self._runner is not None and not self.buttons.isEnabled() and not self.ok:
            e.ignore()                              # no closing the dialog while a step runs
            return
        super().closeEvent(e)


def run_shutdown(parent):
    """Run the sequence modally; True when the rig is clean (lock released), False when the user closed anyway."""
    d = ShutdownDialog(parent)
    with contextlib.suppress(Exception):
        return d.exec() == QDialog.Accepted
    return False
