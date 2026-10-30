"""The visible shutdown sequence (gui/shutdown.py): every step ticked and the dialog accepted when the rig is clean;
a failed step keeps the dialog open with Retry, and Retry finishes the rest. Offscreen Qt on the simulators."""
import os
import time

import pytest
from test_devices import _config

from mtpy import api
from mtpy.api import estop, events

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _until(app, cond, timeout_s, what):
    t_end = time.monotonic() + timeout_s
    while time.monotonic() < t_end:
        app.processEvents()
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError(f"timeout: {what}")


@pytest.fixture
def app(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    _config(tmp_path, monkeypatch, True)
    a = QApplication.instance() or QApplication([])
    with events.as_caller("gui"):
        estop.clear()
        api.devices.connect({"backend": "sim"})
    yield a
    with events.as_caller("gui"):
        if api.devices.status():
            api.devices.disconnect()
        estop.clear()


def test_shutdown_dialog_closes_everything(app):
    from mtpy.gui.shutdown import OK, ShutdownDialog
    d = ShutdownDialog()
    d.show()
    _until(app, lambda: d.ok, 20, "shutdown finished")
    assert api.devices.status() == {}
    assert all(d.list.item(i).text().startswith(OK) for i in range(d.list.count()))
    assert [lbl for lbl, _ in d.items][:2] == ["stop the protocol", "stop acquisition (recording closed)"]
    assert d.items[2][0].startswith("close magnet") and d.items[-1][0] == "release the rig lock"


def test_failed_step_waits_for_retry(app, monkeypatch):
    from mtpy.gui.shutdown import FAIL, ShutdownDialog
    dev = api.devices.service("magnet").device
    real_close, calls = dev.close, []

    def flaky():                      # the PI's close fails once (home not reached), then succeeds on the retry
        calls.append("magnet")
        if len(calls) == 1:
            raise ConnectionError("PI magnet return: POS 3.0, not within 0.01 of 0 mm; limits NOT released")
        real_close()
    monkeypatch.setattr(dev, "close", flaky)
    d = ShutdownDialog()
    d.show()
    _until(app, lambda: d.buttons.isEnabled(), 20, "dialog waiting after the failure")
    assert not d.ok and d.list.item(d.failed_at).text().startswith(FAIL) and "limits NOT released" in d.msg.text()
    assert "magnet" in api.devices.status()                      # still listed: the rig is not clean
    d.btn_retry.click()
    _until(app, lambda: d.ok, 20, "retry finished")
    assert api.devices.status() == {} and calls.count("magnet") == 2
