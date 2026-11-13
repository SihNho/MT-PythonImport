# COM ports after the mainboard replacement (2026-11-10)

Owner 2026-11-10: the mainboard was replaced; the COM ports must be found again and recorded, the LabVIEW code has
to follow. Read from Windows only (`Win32_PnPEntity`, `Get-PnpDevice -Class Ports`,
`HKLM\HARDWARE\DEVICEMAP\SERIALCOMM`, the COM name arbiter). **No port was opened**, so the device behind each
port is inferred from the adapter identity, not from a reply.

| device | adapter (identity) | before (2026-10-22) | now | evidence |
|---|---|---|---|---|
| PI C-863.11, magnet | SUNIX PCIe card, PORT0 (`\Device\SNX_SerialPort0`) | COM3 | **COM6** | same card, new slot id (`..._00E8_` -> `..._00E5_`), Windows made a new instance |
| ASI Tiger, stage + focus | SUNIX PCIe card, PORT1 (`\Device\SNX_SerialPort1`) | COM4 | **COM7** | same |
| Autonics PMC-2HS, rotor | FTDI FT232R, serial `AI03Q9JZA` | COM5 | **COM5** (unchanged) | the FTDI serial keeps its number |
| unknown FTDI FT232R, serial `FTY0W18RA` | USB | COM6 | **COM6, clashes with the SUNIX PORT0** | two present devices are named COM6; only `VCP0 = COM5` and the two SUNIX ports are in SERIALCOMM |
| mainboard serial port | ACPI `PNP0501` | absent | COM1 (new, unused) | |
| Coherent OBIS | USB `VID_0D4D PID_003B` | COM8 / COM9, absent | absent | not plugged in |
| Arduino (CH340) | USB | absent | absent | |
| JAI camera | USB3 Vision `VID_14FB PID_1006`, serial `U500336` | - | present (not a COM port) | |

Why the numbers moved: the old SUNIX instance (absent now) still reserves COM3 / COM4 in the COM name arbiter
(`ComDB` first byte 125 = COM1, 3, 4, 5, 6, 7), so the card in its new slot got the next numbers.

## Two ways to fix

1. **Give the SUNIX ports their old numbers back** (Device Manager -> the SUNIX port -> Port Settings -> Advanced ->
   COM port number: PORT0 -> COM3, PORT1 -> COM4; Windows warns "in use" because of the absent old instance, accept
   it or remove the old instance first with "Show hidden devices"). Nothing changes in the program
   (`devices/pi.py` COM3, `devices/asi.py` COM4, `devices/autonics.py` COM5) or in the LabVIEW code, and the COM6
   clash disappears. Recommended.
2. Keep COM6 / COM7 and change the three places above plus the LabVIEW program; the unknown FTDI then has to move
   off COM6.

## Not checked

- Which controller answers on which port: needs an identity query on the open port (the program's connect does it
  under the rig lock). The table assumes the two RS-232 cables are on the same card sockets as before.
- Rig state at the read: `assembled`, no lock holder.

## After the owner's reset (2026-11-10, "SUNIX changed")

The owner set the SUNIX ports back in Device Manager; read again from Windows, still no port opened.

| device | adapter | port now | note |
|---|---|---|---|
| PI C-863.11, magnet | SUNIX PORT0 (`..._00E5_PORT0`) | **COM3** | as the program and the LabVIEW code expect |
| ASI Tiger, stage + focus | SUNIX PORT1 (`..._00E5_PORT1`) | **COM4** | same |
| Autonics PMC-2HS, rotor | FTDI `AI03Q9JZA` | **COM5** | `\Device\VCP0` |
| unknown FTDI `FTY0W18RA` | USB | COM6 by name, no clash now | present and OK, but it has no entry in SERIALCOMM (as before the reset); never used by the program |
| mainboard serial port | ACPI | COM1 | unused |
| Coherent OBIS, Arduino | USB | absent | not plugged in |

- SERIALCOMM names the SUNIX device objects `SNX_SerialPort6 = COM3` and `SNX_SerialPort5 = COM4` (they were
  `SNX_SerialPort0 / 1`): the driver made new objects at the rename. The instance ids (PORT0 / PORT1) are the
  mapping; a reboot should bring the names back to 0 / 1. `docs/manuals/pi-c863.md` and `asi-tiger.md` quote the
  old object names.
- The COM name arbiter now reserves COM1, 3, 4, 5 (`ComDB` first byte 29).
- Other rig parts: the JAI camera (`VID_14FB PID_1006`, serial `U500336`) is present under NI-IMAQdx; the GPU
  (RTX 2060) is present and numba sees CUDA.
- Three devices of the new board have no driver (Windows status Error): Intel `8086:43A3` (SMBus), `8086:43A4`
  (PCH SPI) and `ACPI\INT34C6` (GPIO) - the Intel chipset driver of the new mainboard is not installed. Not on the
  rig's signal path.

Still not checked: the controller behind each port (the first connect of the program does it), the camera's
frame rate on the new board's USB port.
