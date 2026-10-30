# Owner's motor sequence on the rig (2026-10-30, `tools/phase7_sequence.py`)

Owner: "PI motor 0 --> 30 --> 0 (motor speed 15 mm/s, no wait) / rotor -10 turns --> +10 turns --> 0 / Piezo stage:
+2 um --> -2 um --> 0 / X,Y: +0.5 mm --> -0.5 mm --> 0, each". Run through the API (profile v7 + motion gate,
decision 0025) inside V6 `tools/rig_session.py --no-motor-session`; rig state `assembled`, sample mounted (bench only).
Lock held 09:32:15-09:32:45, released; magnet homed, controller limits released on disconnect.
Raw record: `bench_out/sequence/sequence_20261030_093215.json` (git-ignored).

| move | request | read back | s |
|---|---|---|---|
| magnet | 0 -> 30 mm @ 15 mm/s | 30.0002 mm | 2.26 |
| magnet | 30 -> 0 mm @ 15 mm/s (no dwell) | -0.0002 mm | 2.25 |
| rotor | start 200 turns -> -10 | **refused**: 190 outside [195, 205] (window +-5 turns, profile v7) | 0.06 |
| rotor | -> +10 | **refused**: 210 outside [195, 205] | 0.06 |
| rotor | -> 0 | 200.0 turns (no motion needed) | 0.66 |
| focus | 0 -> +2 um | 2.0 um | 0.02 |
| focus | -> -2 um | -2.0 um | 0.02 |
| focus | -> 0 | 0.0 um | 0.02 |
| stage x | -1.4380 + 0.5 mm | -0.9378 mm (y unchanged) | 0.37 |
| stage x | -0.5 mm | -1.9378 mm | 0.39 |
| stage x | back | -1.4379 mm | 0.39 |
| stage y | -3.6445 + 0.5 mm | -3.1445 mm (x unchanged) | 0.48 |
| stage y | -0.5 mm | -4.1445 mm | 0.57 |
| stage y | back | -3.6445 mm | 0.53 |

Every move inside the envelope arrived and read back within tolerance (stage x back differs by 0.1 um, the ASI
read-back step). The rotor +-10 turns was outside the window the owner verified on the rig the same morning
(`rotor_turns` +-5 from session start, profile v7) and was refused before anything was sent; the rotor did not move.
Widening the window is a rig-admin change that needs the owner's word and a readback at the new edges
(`tools/phase7_rotor.py`).

Not covered: the EMCCD (run separately the same day), the magnet speed above 15 mm/s (profile maximum).
