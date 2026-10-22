# Coherent OBIS laser (TIRF excitation)

## Purpose on the rig

The TIRF excitation laser for the planned MT-TIRF experiments. It is set up but not used in experiments now, and today
it is run only from Coherent's own program, **Coherent Connection 3.0.0.8**. The LabVIEW program does not control it.
The owner will either put a shutter in front of it or switch it through the laser controller, and first wants to know
how fast and how accurately the controller path works (owner, 2026-10-20). Later its modulation input may be driven by
the Arduino frame divider (decision 0005).

## Connection

| item | value | evidence |
|---|---|---|
| model | OBIS, **LX or LS not known**; wavelength and power not recorded | owner |
| interface | the OBIS USB port is a USB virtual COM port with its own identity: Windows device "Coherent OBIS Device", **VID_0D4D PID_003B**, driver `obis_01.inf` 1.0.0.0 (Coherent, 2011) | `Get-PnpDevice -Class Ports` and `pnputil /enum-drivers`, read 2026-10-22 |
| port | the device has been seen as **COM8** and **COM9** (two instance ids = two USB sockets, or two units); both were **not present** on 2026-10-22 (status Unknown) | same |
| COM6 | an FTDI FT232R (VID_0403 PID_6001, FTDI serial `FTY0W18RA`) - **not** the OBIS USB identity; it could be an OBIS RS-232 cable through an adapter, a remote, or something else. **Never opened** | same |
| framing (RS-232) | 115200 baud, 8N1, no flow control; commands end CR LF; with handshaking on (`SYST:COMM:HAND ON`, the default) every reply is followed by `OK`, errors by `ERR-<n>` | OBIS operator's manual (V0); Coherent Connection uses handshaking (its library builds `SYST:COMM:HAND ON` and reports "Handshake error") |
| only one owner | Coherent Connection and a script cannot hold the COM port at the same time | general serial behaviour |

## Driver / SDK

- **Coherent Connection 3.0.0.8**, `C:\Program Files (x86)\Coherent\Coherent Connection 3\` (.NET;
  `Coherent_Connection.exe`, `CoherentConnectionLibrary.dll`, `Hoosier.dll`). It supports OBIS LX, OBIS LS and the OBIS
  Mini-Controller (strings in the library).
- USB driver `obis_01.inf` 1.0.0.0; also Coherent `sraybus.inf` / `srayport.inf` 2.8.14.0 in the driver store.
- No SDK is needed: OBIS is controlled by SCPI-style ASCII commands. The command spellings below appear in
  `CoherentConnectionLibrary.dll` (read as text on 2026-10-22), which confirms the vocabulary the vendor's own program
  uses; the meanings are from the OBIS operator's manual. `{0}` in the library = an optional device index for a
  multi-laser remote.

## Command table

Nothing has been sent to this laser from any project script. Every entry is V0.

| command | meaning | arguments + units | response | LabVIEW program use | level + evidence |
|---|---|---|---|---|---|
| `*IDN?` | identify | - | maker, model, serial, firmware | not used | **V0** - manual; string in Coherent library |
| `SYST:INF:MOD?` / `SYST:INF:SNUM?` / `SYST:INF:WAV?` / `SYST:INF:POW?` / `SYST:INF:FVER?` | model, serial, wavelength (nm), nominal power (W), firmware | - | text / number | not used | **V0** - same |
| `SYST:STAT?` / `SYST:FAUL?` | status and fault bit fields | - | hex code | not used | **V0** - same |
| `SYST:ERR:NEXT?` / `SYST:ERR:CLE` | read / clear the error queue | - | code and text | not used | **V0** - same |
| `SYST:LOCK?` | interlock state | - | `ON` / `OFF` | not used | **V0** - same |
| `SYST:COMM:HAND ON|OFF` / `SYST:COMM:PROM ON|OFF` | reply handshake (`OK`) / prompt | - | `OK` | not used | **V0** - same |
| `SOUR:AM:STATE ON|OFF` / `SOUR:AM:STATE?` | **laser emission on / off** | - | `OK` | not used | **V0** - same |
| `SOUR:AM:INT CWP|CWC` | internal CW mode: constant power / constant current | - | `OK` | not used | **V0** - same |
| `SOUR:AM:EXT DIG|ANAL|MIX` | external modulation: digital, analog, mixed (the input the Arduino or a TTL could drive) | - | `OK` | not used | **V0** - same |
| `SOUR:AM:SOUR?` | current operating mode | - | `CWP`, `DIGITAL`, ... | not used | **V0** - same |
| `SOUR:POW:LEV:IMM:AMPL <W>` / `SOUR:POW:LEV:IMM:AMPL?` | set / read the power set point | **watts** | `OK` / number | not used | **V0** - same |
| `SOUR:POW:LEV?` | measured output power | - | W | not used | **V0** - same |
| `SOUR:POW:NOM?` / `SOUR:POW:LIM:HIGH?` / `SOUR:POW:LIM:LOW?` | nominal and limit powers | - | W | not used | **V0** - same |
| `SOUR:TEMP:BAS?` | base-plate temperature | - | deg C | not used | **V0** - same |
| `SYST:CDRH ON|OFF` | 5 s CDRH emission delay after "on" (persistent setting) | - | `OK` | not used | **V0** - same; changing it changes what the owner gets in Coherent Connection |
| `SYST:AUT ON|OFF` | auto-start emission at power-up (persistent setting) | - | `OK` | not used | **V0** - same; never change without the owner |
| `SYST:HOUR?` / `SYST:DIOD:HOUR?` | operating hours | - | hours | not used | **V0** - same |

## Units, signs and offsets

- Power in **watts** (a 100 mW laser is `0.1`). Wavelength in nm. Temperatures in deg C.
- In digital modulation the external input switches the beam; in CW modes `SOUR:AM:STATE` does.

## Safety envelope and what to restore after a job

- **Laser safety comes first**: emission only with the owner present and the room's laser rules in force; the interlock
  (`SYST:LOCK?`) must be respected, never bypassed.
- A job that talks to the laser records the state it found (mode, power set point, emission state, `CDRH`, `AUT`) and
  restores exactly that, emission off unless it was on. Persistent settings (`CDRH`, `AUT`) are not changed.
- The laser is a rig device: the rig lock applies (RULES.md section 2). Close the port, so Coherent Connection can use
  it again.
- Decision 0007 leaves open what an emergency stop or an abnormal end does to the laser.

## Known pitfalls

1. The port number is not stable: the OBIS has appeared as COM8 and COM9. Find it by VID_0D4D PID_003B, not by number.
2. With handshaking on, every command (also a set) is followed by `OK`; a reader that expects one line per command
   gets out of step.
3. `CDRH ON` delays emission by about 5 s after "on" - this dominates any "how fast is the controller" measurement.
4. Only one program can own the port; close Coherent Connection first.

## Open questions for the owner

1. LX or LS, wavelength and power? (`*IDN?` / `SYST:INF:MOD?` would answer it in one read-only query.)
2. Which port does the laser use now - its own USB (COM8/COM9 when plugged in) or COM6?
3. Shutter or laser switching: which latency and accuracy are needed (per frame, per exposure)? Measuring it means
   emission tests with the owner present.
4. Should the laser start in the off state after an abnormal end, and what does the emergency stop do to it
   (decision 0007 open items)?
5. Is the modulation input meant to be driven by the Arduino D9 output (decision 0005), and at which voltage?
