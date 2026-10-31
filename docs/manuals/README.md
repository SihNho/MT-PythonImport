# Device manuals

One manual per device of the Kim Lab magnetic-tweezers rig. Each manual is written so that a maintainer can drive
the device from a new program without reading anything else: how it is connected, which driver it needs, every
command with its units and reply, how the LabVIEW program uses it, what must be restored after a job, and what is
still unknown.

| device | manual | on the rig today | used by the LabVIEW program |
|---|---|---|---|
| JAI SP-5000M-USB camera (NI-IMAQdx) | [camera-jai-imaqdx.md](camera-jai-imaqdx.md) | yes | yes |
| JAI SP-5000M-USB camera (eBUS SDK, decision 0028) | [camera-jai-ebus.md](camera-jai-ebus.md) | yes | yes |
| PI C-863.11 + M-126.PD1 magnet stage | [pi-c863.md](pi-c863.md) | yes | yes |
| Autonics PMC-2HS rotor controller | [rotor-autonics-pmc2hs.md](rotor-autonics-pmc2hs.md) | yes | yes |
| ASI Tiger (TG-1000) XY stage + Z piezo | [asi-tiger.md](asi-tiger.md) | yes | yes |
| Andor iXon Ultra EMCCD (SDK2) | [andor-ixon.md](andor-ixon.md) | no (planned for MT-TIRF) | only by the old `4.4_KimLabMTroom_EMCCD` VI |
| Coherent OBIS laser | [coherent-obis.md](coherent-obis.md) | yes (TIRF, run from Coherent Connection) | no |
| Arduino frame divider (JAI -> iXon) | [arduino-sync.md](arduino-sync.md) | wired, never run; firmware not written | no |

smCamera (the lab's old smFRET program, not a device; kept here because the iXon port replaces it):
[smcamera-emccd-parameters.md](smcamera-emccd-parameters.md) (camera parameters and SDK calls),
[smcamera-files.md](smcamera-files.md) (its file formats, read from a real dataset),
[smcamera-workflow-mtfret.md](smcamera-workflow-mtfret.md) (the colleague's workflow and MT-FRET requirements,
`mtFRET_2.pptx`).

Vendor SDKs and drivers (versions found on the rig PC, install paths, where to download, redistribution) are listed
in [`third_party/MANIFEST`](../../third_party/MANIFEST), section "vendor SDKs and drivers".

## Verification levels

Every entry of every command table carries exactly one of these levels.

| level | meaning |
|---|---|
| **V0** | vendor documentation only |
| **V1** | used by the LabVIEW program (seen in its wiring / subVIs / V6 analysis docs) |
| **V2** | sent on this rig with the response recorded (cite the log or doc) |
| **V3** | behavior verified on this rig (readback matched the expectation; cite) |

A higher level includes the lower ones only where the evidence says so; a V3 command is not automatically "used by
the LabVIEW program" - that is a separate column. A level is raised only with a citation to a log or document that
records the response. Evidence older than a firmware or driver change is re-checked before it is relied on.

## Conventions

- **V6** means the MT_LabVIEW working folder
  `G:\Codes\LabVIEW_Codes\MinLab\zz_LabView VI\AAA_UNIST\2. Tracking\V6_ParallelLoop`
  (repository <https://github.com/SihNho/MT_LabVIEW>). Paths such as `V6: tools/bench/hw_rotor_read.log` are relative
  to it. V6 documents are AI working notes and are cited as evidence only; every fact a maintainer needs is stated in
  the manual itself.
- **The running LabVIEW program** is `Min_Track N beads 4.5_KimLabMTroom_3StateClamping.vi` (the original; V6 works on a
  copy). Diagram numbers (`d43`) and node uids are those of V6's census
  (`V6: docs/motor-call-site-census.md`, `V6: docs/main-vi-subvi-identity.md`).
- **The rig rules** (`G:\Codes\rig\RULES.md`) apply to every device here: take the shared lock before any device call,
  move motors only through the approved gate, clean up to the initial condition, and touch nothing during an
  experiment. Each manual states the device-specific part (envelope, what to restore).
- Units are always written next to numbers. "Pulses", "0.1 um units" and "mm" are never mixed without a conversion.

## Adding a manual

1. One file per device, named `<vendor>-<model>.md` in lower case.
2. Sections, in this order, each present even if it only says "none" or "unknown":
   purpose on the rig; connection (interface, port, baud/framing, terminator, timeouts); driver / SDK (version found on
   the rig PC, install path); command table; units, signs and offsets; safety envelope and what to restore after a job;
   known pitfalls; open questions for the owner.
3. Command table columns: command | meaning | arguments + units | response | where the LabVIEW program uses it |
   level + evidence. A command the port will need but the LabVIEW program does not use is listed at V0.
4. Facts come from a document, a log or a measurement - cite it. Anything that needs the device to settle stays an
   open question; it is never guessed into the table.
5. Add the device to the index above and its SDK / driver to `third_party/MANIFEST`.
6. Writing a manual makes no device call. Raising a level to V2/V3 means a rig job, which follows the rig rules.
