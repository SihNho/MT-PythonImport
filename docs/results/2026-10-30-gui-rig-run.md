# First rig run of the GUI without the wrapper (2026-10-30, decision 0026)

Owner away ("지금은 외부에 있어서, 너가 화면 직접 체크해야함" / "화면 및 마우스 컨트롤 직접 해서 조작하도록"), so the
GUI was checked two ways, both on the real rig (JAI + iXon + PI / ASI / Autonics, backend `real-motors`, a channel
with reference and magnetic beads mounted, no illumination): (1) the window driven in-process with a screenshot at
each step; (2) a second window launched by `MT Tracker (rig).cmd` and operated with the real mouse (Win32 input,
desktop screenshots). Pictures in `bench_out/gui_rig/` (git-ignored).

| step | result |
|---|---|
| Connect | 8 / 8 connected in about 30 s; rig lock holder `mtpy` (the program's own, decision 0026), state assembled |
| EMCCD apply (GUI defaults 30 ms, 20 Hz) | **refused**: 30 ms exposure outside [0.001, 25.41] ms at 20 Hz (frame period minus the 24.59 ms readout). Default rate changed to 18 Hz in this commit |
| EMCCD snap, shutter default / closed / open | mean 207.2 / 197.6 / 208.2 counts, 512 x 512 - bias only, no light in the room; the frame shows in the image view |
| magnet 5 mm, back to 0 | read back 5.0 / -0.00015 mm, status line "magnet -> 5.000 mm: ok" |
| Disconnect (shutdown dialog) | 10 steps ticked in 1.8 s (iXon warm, no cooling today): protocol, acquisition, magnet home + limits released, rotor, stage, focus, emccd, camera, arduino, light, lock release; `[ok]` on every line |
| rig lock after | holder null, state assembled (checked twice, once per window) |
| close window with no devices | closes at once, no dialog |

Two windows had the same title; closing the idle one with the mouse worked. Not covered: a failing shutdown step on
real hardware (only the simulator test), the iXon warm-up wait (cooler never on), shutter open vs closed with light,
beads (no calibration for this channel yet).
