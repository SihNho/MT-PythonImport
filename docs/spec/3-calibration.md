# 3 — Calibration (Z scan → `.cal`)

After picking, the program scans the focus through a range, records each bead's radial intensity profile at every
step, and writes a `.cal` file. Frames D86 and D145–D169. Form and evidence levels: [README.md](README.md).
File layout: [../format/tra-cal.md](../format/tra-cal.md).

### F3.01 — Calibration parameters

- **Trigger:** read once when the calibration starts (D86).
- **Inputs:** `# images in stack` (slices, e.g. 60), `# to avg per image` (frames averaged per slice, e.g. 20),
  `z step (um)` (e.g. 0.1), `Cross length (pixels)` (e.g. 120), `pixel distance (nm)` (e.g. 84).
- **Steps:** `Bundle By Name` puts them in one cluster with the bead list; `Intensity vs Radius` gets its x-axis
  range from `cross length`; `Count` is written (value `unknown`).
- **Outputs:** the calibration cluster used by F3.02–F3.05.
- **Moves hardware?** no.
- **Timing and errors:** values are not range-checked (none seen).
- **Evidence:** wiring — panel rows 62–66 land on D86 (`V6:tools/bench/main_vi_netmap.json`); data — the values in
  `cal002` (60, 20, 0.1, 119 = 120 − 1, 84.0).
- **Owner's intent:** `Cross length`, `CCD height/width`, `# FD points`, `# DT points` and others are per-room
  parameters (in-VI comment, `V6:docs/GLOSSARY.md` "Per-room parameters").
- **Port:** port; change — keep them in a saved configuration instead of panel defaults (Q3.01).

### F3.02 — Z scan

- **Trigger:** after `Done Picking \nBeads?` (F2.03).
- **Inputs:** F3.01; the ASI session; the camera session.
- **Steps:**
  1. D145 busy cursor; D146 `Get Current Position` → `Focus Pos (Cal)` (the scan start); D147 builds the bandpass and
     cosine window (`make both cosine bandpass.vi`) and an image buffer.
  2. For each slice i (D148 → D149 → stacked sequence D150–D157):
     D150 / D151: unless i = 0 (`x = 0?`, *inferred* order), `Move Axis to Position` to start + i × z step;
     D153 `Wait (ms)` (constant unread) and `Focus Pos (Cal)` update; D154 reads `LastBufferNumber`;
     D155–D157: for each of `# to avg per image` frames, `IMAQdx Get Image` with an explicit buffer number
     (last + k); `Equal?` of requested vs returned buffer drives `Missing Frames?`.
  3. Profiles per frame: F3.03.
- **Outputs:** `Focus Pos (Cal)`, `Missing Frames?`, `Waveform Graph` (written on D148; content `unknown`).
- **Moves hardware?** **yes — ASI focus axis, one move per slice.**
- **Timing and errors:** a missing frame only sets the indicator; whether that frame is skipped or used is
  `unknown — needs VI read`.
- **Evidence:** wiring — node census D145–D157; `Move Axis to Position` on D151 and `Get Current Position` on D146 /
  D148 (`V6:docs/motor-call-site-census.md` count table).
- **Owner's intent:** ask (Q3.02: scan direction and whether the start is the slice centre).
- **Port:** port.

### F3.03 — Radial profiles of each bead, averaged into the stack

- **Trigger:** each averaged frame of F3.02 (D158); averaging after each slice (D164–D166).
- **Inputs:** the frame, the bead list, cross size, the cosine windows; `# to avg per image`.
- **Steps:**
  1. A case on the bead count handles beads in pairs with `calibration- generate 2 I of r, reentrant.vi` and an odd
     bead with `calibration- generate 1 I of r, reentrant.vi` (D159 empty, D160 one bead, D161 two, D162 two plus
     one; D163 loops over pairs). Each call returns the bead's radial intensity profile and draws the bead on the
     picture.
  2. Transpose and average (`Add Array Elements` / `Array Size` / `Divide`) → one profile per bead per slice; the
     stack is n beads × S slices × L points (L = cross length − 1).
- **Outputs:** the stack (`cal image array`); `Picture`; `Intensity vs Radius`.
- **Moves hardware?** no.
- **Timing and errors:** none known.
- **Evidence:** wiring — node census D158–D166; `V6:docs/MAIN_VI_MAP.md` section 3 (1-bead / 2-bead pairing); data —
  `cal002` stack shape 5 × 60 × 119.
- **Owner's intent:** ask (none needed).
- **Port:** port — same arithmetic as the subVIs (decision 0003; the computation is specified by the NumPy reference
  in MT_LabVIEW).

### F3.04 — Return focus, build calibration images, choose bandpass

- **Trigger:** after the last slice (D167).
- **Inputs:** the stack; F3.01.
- **Steps:** `Move Axis to Position` (target `unknown`; returning to the start is *inferred*); per bead
  `build cal image.vi` (power spectrum of the stack) → `choose bandpass v2.vi` (forget radius, low and high
  bandpass) (D168).
- **Outputs:** `size(s)`; per-bead bandpass values (`bandpass/forget array`).
- **Moves hardware?** **yes — ASI focus axis.**
- **Timing and errors:** whether `choose bandpass v2.vi` asks the user is `unknown — needs a read of the subVI`.
- **Evidence:** wiring — node census D167–D168; `V6:docs/MAIN_VI_MAP.md` section 3 (bandpass is built in
  calibration, not in tracking).
- **Owner's intent:** the forget radius and bandpass are set during calibration (owner, `V6:docs/MAIN_VI_MAP.md`
  section 3). Q3.05.
- **Port:** port.

### F3.05 — Write the `.cal` file

- **Trigger:** end of the calibration (D169).
- **Inputs:** the calibration cluster.
- **Steps:** a file dialog (`Choose or enter file path`) → `Bundle By Name` adds the date and time
  (`Get Date/Time String`, concatenated) → `Write to Binary File`, big-endian, sizes prepended.
- **Outputs:** the `.cal` file; `output cluster` (indicator); the file refnum, from which the trace path is made
  (F4.11).
- **Moves hardware?** no.
- **Timing and errors:** cancelling the dialog (`cancelled`) — behavior `unknown — needs VI read`.
- **Evidence:** wiring — node census D169 (terminal `byte order (0:big-endian, network order)`); data — `cal002`.
- **Owner's intent:** ask (Q3.06: is a calibration ever reused from an older `.cal` file?).
- **Port:** port, byte-identical (decision 0006).

### F3.06 — Load the calibration into the tracker

- **Trigger:** the experiment set-up frames D6, D7, D18.
- **Inputs:** the calibration cluster (in memory).
- **Steps:** D6 unbundles the cluster; D7 (For loop per bead) runs `prep cal image.vi` and
  `proc cal image-make bandpass.vi` → one cal cluster per bead (`r shifted cal real`, `r shifted cal ampl`,
  `r-shifted corkscrew cal`, `Cosine bandpass`); D18 builds the real-space cosine window and the Hilbert bandpass
  (`make both cosine bandpass.vi`).
- **Outputs:** `Array of cal clusters`, the windows (inputs of F4.04).
- **Moves hardware?** no.
- **Timing and errors:** once.
- **Evidence:** wiring — node census D6, D7, D18; `V6:docs/main-vi-stop-and-save.md` section 4 (the kernel's inputs).
- **Owner's intent:** ask (none needed).
- **Port:** port.
