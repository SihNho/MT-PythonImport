# 0005 — Camera synchronisation: the JAI is the master clock

**Decided:** 2026-10-21 (the wiring exists but has not been run yet)

## Decision
```
JAI (internal clock = the only master) --ExposureActive--> Arduino UNO-compatible, pin D5 (Timer1 hardware counter)
                                                            | every N frames, a pulse k frames wide (hardware PWM)
                                                            v
                                                         pin D9 --> iXon external trigger   (later also the OBIS modulation input)
```
- **The PC never generates frame triggers.** PC timestamps are kept for monitoring only. They never define synchronisation.
- **N changes per experiment.** The PC opens the Arduino port only at setup and at the end. Opening it auto-resets the board; then N, k and the firmware version are set. During a run there is no PC communication.
- **Firmware rules:**
  - when JAI pulses stop, the count resets to 0;
  - the count is extended to 32 bits;
  - a watchdog runs.
- **Alignment:** EMCCD frame m belongs to absolute JAI buffer numbers [mN, (m+1)N). IMAQdx buffer numbers count every camera frame from acquisition start, including frames the PC dropped. Data files therefore store the absolute buffer number.

## Why
- **One clock means no drift.** Two free-running cameras drift apart; a 50 ppm difference is about 0.18 s per hour.
- **The JAI keeps running on its own clock, exactly as today**, so MT-only experiments do not change.
- **The Arduino's own clock precision does not matter.** It only counts, and its clock is used only for the "pulses stopped" timeout.

## Known limits and checks
- **The JAI SP-5000M-USB has no chunk data, counter or hardware timestamp features** (from its GenICam description). Per-event cross-checking inside the JAI data is therefore impossible. Totals are checked instead: EMCCD frames vs. JAI buffers divided by N.
- **Before use:**
  - set the JAI output line to an exposure-start signal and turn auto-exposure off; otherwise the master period changes;
  - choose the iXon trigger mode (External, External Exposure, or Frame Transfer + External);
  - check voltage levels;
  - run a long soak test (Arduino count vs. JAI buffers, longer than the longest movie), a high-rate margin test and an oscilloscope check of the signal.
- **Arduino pitfalls:** a CH340 USB chip has no unique serial number, so the board is identified by asking the firmware. The port must not be reopened during a run, because that resets the counter.
- **Motors are still polled by the PC.** Each motor reading is stored with the latest JAI frame number, the same as the LabVIEW program does today, so timing uncertainty is at the millisecond level.
