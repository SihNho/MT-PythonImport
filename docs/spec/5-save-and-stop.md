# 5 — Save and stop

Form and evidence levels: [README.md](README.md).

### F5.01 — Stop conditions of the frame loop

- **Trigger:** `stop (end)`, `stop (end) 2`, or the auto-reset limit.
- **Inputs:** `stop (end)`, `stop (end) 2`, `Limit of Program` (via F4.05).
- **Steps:** `Compound Arithmetic` uid 11639 ORs `stop (end)` with two internal conditions (one is
  `# of Auto-Reset = Limit of Program`); its result (wire 3457) is the frame loop's stop terminal and is also written
  to the indicator `TurnOff`, which the motor loop reads to stop (F1.09). `stop (end) 2` goes into a separate OR
  (uid 17883) that feeds case uid 22082, not the stop terminal; what that case does is `unknown — needs VI read`.
- **Outputs:** `TurnOff`.
- **Moves hardware?** no.
- **Timing and errors:** checked once per frame.
- **Evidence:** wiring — `V6:docs/main-vi-stop-and-save.md` section 1 (closed 2026-09-17 by `OpLoopEndRef_v0`).
- **Owner's intent:** the normal way to stop is LabVIEW's Abort button, which saves nothing that is still in memory
  (statement recorded in `V6:docs/frame-ownership-design.md:105`; the original has no "stop without saving",
  decision 0008). Q5.01.
- **Port:** change — explicit **Stop and save** and **Stop without saving** buttons, plus the emergency stop of
  decision 0007.

### F5.02 — Final save after the loop

- **Trigger:** the frame loop has stopped (frame D19, after the loop).
- **Inputs:** the loop's final `total data array`, `file progress` (rows so far), `file number to append`, the
  base path, the `.cal` path, the nominal size.
- **Steps:** `Array Subset` keeps the filled rows → `save N xyz traces.vi` (uid 6384) writes the last `.tra` file:
  header text (date, `cal cluster:` and path, `file N of a series`, `actual data points/nominal`, column order, the
  units note) then the 2D array. `Max Trans Pos.vi` is called in the same frame; the three VI Global fields are
  written (F0.07).
- **Outputs:** the last `.tra` file.
- **Moves hardware?** no.
- **Timing and errors:** if the program is aborted instead of stopped, this does not run and the rows in memory are
  lost.
- **Evidence:** wiring — `V6:docs/main-vi-stop-and-save.md` section 2; data — header of the recorded `.tra`
  ([../format/tra-cal.md](../format/tra-cal.md)).
- **Owner's intent:** ask (Q5.02).
- **Port:** port byte-identical; change — rows are flushed continuously so a crash loses at most a short interval
  (decision 0006 item 5).

### F5.03 — Shutdown

- **Trigger:** frame D83, after the save.
- **Inputs:** sessions; `Total Lost Frames`.
- **Steps:** `IMAQdx Stop Acquisition` → `IMAQdx Close Camera` → `Simple Error Handler`; `ASI TG-1000 Close`
  (error chain unwired); `IMAQ Dispose`; `Trans position` and `Rot position` written to the VI Global from
  `Trans Pos (mm)` / `Rot pos (deg)`; if `Total Lost Frames ≠ 0` (D84) `Lost Frame Message` is written, else D85
  (empty). The PI controller and the rotor port are not closed in this frame (no close node found).
- **Outputs:** `Lost Frame Message`.
- **Moves hardware?** no.
- **Timing and errors:** whether a `VISA Close` exists elsewhere is not established.
- **Evidence:** wiring — `V6:docs/main-vi-stop-and-save.md` section 3; node census D83–D85.
- **Owner's intent:** motors, magnet and laser stay where they are on an abort (decision 0007). Q5.03.
- **Port:** change — every device is closed and the session-state file is closed (decision 0007).
