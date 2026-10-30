"""Simulators of every rig device (phase 5); they open no port, camera or LabVIEW."""
from ..ixon import SimEmccd
from .camera import Frame, SimCamera
from .motors import SimFocus, SimMagnet, SimRotor, SimStage
from .sync import SimArduino, SimLight


def make_rig(fixture=None):
    """The simulated rig, wired like the real one: the camera's exposure line drives the Arduino divider, whose
    gating outputs follow the lights."""
    light = SimLight()
    arduino = SimArduino(light)
    camera = SimCamera(fixture)
    camera.exposure_listeners.append(arduino.on_jai_frame)
    return {"camera": camera, "magnet": SimMagnet(), "rotor": SimRotor(), "stage": SimStage(), "focus": SimFocus(),
            "arduino": arduino, "light": light, "emccd": SimEmccd()}


__all__ = ["Frame", "SimArduino", "SimCamera", "SimEmccd", "SimFocus", "SimLight", "SimMagnet", "SimRotor",
           "SimStage", "make_rig"]
