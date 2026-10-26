# smCamera workflow and the MT-FRET requirements (`mtFRET_2.pptx`, 2026-10-26)

Source: the slide deck `mtFRET_2.pptx` (12 slides, 14 images) from a colleague who runs smFRET with smCamera, written
as requirements for the MT + FRET program; plus the colleague's MATLAB script `a_trace_range_selection_123.m` and the
smCamera install / dataset described in [smcamera-files.md](smcamera-files.md). Slide text is quoted verbatim
(including its spelling); screenshot content is read from the images.

Verification levels: **[S]** on the slide (text or screenshot), **[F]** read from a file, **[P]** checked by parsing
files, **[I]** inferred.

## 1. Slide by slide

| slide | content | verbatim quote | what it asks of the new program |
|---|---|---|---|
| 1 | Recorder interface (text) | "Recorder interface / Frame rate: 100ms / Background: 3000 / Data scalar : 300 / Select path to save / Max Frames = / Current Frames = / Number of films- / Record/ stop / Max/ min- intensities / Overlay molecules" | a recorder panel with these fields (R1 below) |
| 2 | two phone photos of smCamera's Movie Recorder + ShutterManager | (image only) | see section 2 |
| 3 | Mapping, CH1 / CH2 | "Pair a set of molecules at a time, each recognized by a different color." "No frame sequence needed" "No threshold needed" "No analysis needed" ". Traces file will have both intensities and fret. That's how I read the file using matlab code I sent and it shows both intensities and fret." "When we map here, it should also reflect in MT interface and select the beads accordingly." | manual pairing; `.traces` output; map shared with the bead (MT) view (R2-R5) |
| 4 | Movie Mapper screenshots | "In our case due to low number of molecule, we don't have to use frame seq, we can select and pair the molecules by ourself." | manual pairing replaces automatic peak finding (R2) |
| 5 | Movie Analysis window | "No analysis needed like this" | no automatic peak-find / analyse step in the MT-FRET case (R3) |
| 6 | Methods text + formula | "Background-subtracted donor and acceptor intensities were corrected for the donor leakage into the acceptor channel and the direct excitation of the acceptor." "The first and last five frames of each trace were used to select molecules with colocalizing donor and acceptor, and were excluded from histogram and trace analyses." "This is how the fret is calculated by the program." | FRET formula and corrections (R6), first / last 5 frames rule (R7) |
| 7 | Tools menu; empty FRET Trace window | (image only) | the FRET Trace viewer as model (R8) |
| 8 | FRET Trace "Open" dialog, `film1..6` of type "Trace Files (*.smt)" in a `LONG` folder | (image only) | |
| 9 | FRET Trace with a molecule (Peak 207 / 671) | "For frames / To see different molecules" | per-molecule browsing with frame slider (R8) |
| 10 | FRET Histogram window | "Make the histograms of the smt files we selected according to the frames we selected in ch1 and ch2." | histograms over chosen frames per channel (R9) |
| 11 | histogram result for film1-6.smt | (image only) | |
| 12 | Tools menu; File Format Converter | "To convert the smt files to trace file" | `.smt` -> `.traces` export (R4) |

## 2. What the screenshots show [S]

- **Movie Recorder (slide 2):** Exposure Time 100.000 ms, Kinetic Cycle 101.750 ms, Gain range "(6 ~ 300)" (value
  cut off; logs show 295-299 [F]); Buffering "In Camera" / "In Memory [MB]"; Max / Min of the image (5386 / 2593),
  Background 3000 or 3120, Data Scaler 300; Auto Scale, Overlay Channels, Log Selected Spot; Set Path, Film # (13, 1),
  Frame #, "Set Max Length 20 Frames" ticked, Record / Stop, Save as PMA files, Save a Pixel in 8 Bit, Comment.
  The status line reads "Exposure Time[100.000 ms] Kinetice Cycle[101.750 ms]".
- **ShutterManager (slide 2, partly hidden):** three sequence paths `...\ShutterManager\Shutter\NN\R5...`,
  `...\NN\G1...`, `...\NN\5 frames - 4 red 1 green...`; device `Dev1`, lines 1, 4, 7, one shutter "On/Off" ticked,
  Shutter Delay 20 ms. With smcamera-emccd-parameters.md section 7 (header / body / footer) this is: 5 red frames,
  then green frames, then the footer "4 red 1 green" [I] - exactly the pattern found in `LONG/film1.traces` (frames
  1-5 and 296-299 red, the rest green) [P].
- **Movie Mapper (slide 4):** CH1 and CH2 halves side by side with circled peaks; "CH1 Frame Sequence"
  (`...\FrameSequence\00 6-14.txt`), "Superpose CH2 onto CH1" ticked with "Use this map", Peak Radius 3 pixel,
  Threshold / Scaler 20 %, "Allow bad peaks from CH1 / CH2", Allowable Error 3 pixel; log lines "Mapping with [116]
  point pairs", "Mapping Error(rms) : CH1X[0.706794] CH1Y[0.667482] CH2X[0.695...", "460(541) peaks in CH1",
  "283(302) peaks in CH2" (circled in red), and in the second photo 271 point pairs, rms 0.70 / 0.65 / 0.71 px.
- **Movie Analysis (slide 5):** Open File, Spot 1 / Spot 2 with Radius 6 px, Load Map ("Mapping is not available."),
  Frame Sequence `00 6-14.txt` with Repeat / Apply, Peak Radius 3, Peak Threshold / Data Scaler 20 %, Find CH1 / CH2,
  Find & Save Peaks, Peak Sigma 1.6, Analyze bad peaks / again / background, Analyze, Analyze Folder.
- **FRET Trace (slides 7-9):** Use Mapping (Load, "1 to 2", "2 to 1"), Peak No x / N, Build Trace, Save Trace,
  `F0 / Fsum : 1`, `ID1 / ID_all : 0.9`, `IA1 / IA_all : 0`; Peak 1 and Peak 2 zooms with R1 4 px, R2 3 px; Show Total
  Emission, Show Background, Flat Background; two plots: emission intensity (green donor, red acceptor) and FRET vs
  time in s. In the example the first and last frames show high acceptor and FRET ~1 (red excitation) [S].
- **FRET Histogram (slides 10-11):** Frames 1 = `00 6-14.txt`, Frames 2 = `0 1-5.txt`; Leakage Correction "ID in CH1"
  0.91, "IA in CH1" 0; two histograms with a quantity menu ("1. FRET", "4. CH1+CH2"), LB / UB, Bin (0.01, 1000 / 140),
  Save. The result for film1-6.smt shows FRET peaks near 0.0 and 0.2.
- **File Format Converter (slide 12):** Convert Films (to "1. Old Film", resize), Convert Traces ("Convert Trace(s) To
  Old Trace(s)", "Convert 2nd Traces"), Convert Maps (origin, area, binning).

## 3. FRET formula and corrections

Slide 6 formula: `E_FRET = (I_A - beta * I_D) / (I_D + I_A)`, where I_D and I_A are donor and acceptor intensities
"after correction for the background and the direct excitation of the acceptor" (Sohn et al. 2020), smCamera cited as
"Lee and Ha, 2025" [S]. beta is not given on the slide.

What the files add:

- `.traces` holds only background-subtracted intensities, truncated to int16; no leakage or direct-excitation
  correction is applied in it [P, smcamera-files.md section 5].
- smCamera's own correction is entered as "ID in CH1" = 0.91 (FRET Histogram) / "ID1/ID_all" = 0.9 (FRET Trace) [S,
  F `.save`]: the fraction of donor emission landing in CH1. The leakage into CH2 relative to CH1 is then
  (1 - 0.91) / 0.91 = 0.099, i.e. beta ~ 0.1 [I].
- The MATLAB script uses `leakage=0.1` and `gamma = 0.76` (gamma defined but **not used**) and computes
  `fretE = (A - ma - leakage*(D - md)) ./ (A + D - ma - md)` [F code]: the slide formula with beta = 0.1 and no gamma.
- Direct excitation of the acceptor: no number on the slides or in the script; the red-excited frames (first / last 5)
  are where it would be measured [I]. Open question.

## 4. `a_trace_range_selection_123.m` (read from the code)

A keyboard-driven trace browser for one `filmN.traces` (MATLAB, CP949-encoded comments; authors' comments name
Sunghyun, Kaushik, SeungWon) [F]:

1. Asks for the folder, the film index N, the time unit (default 0.1 s) and an output subfolder (default `blink`).
2. Reads `.traces` (int32 len, int16 Ntraces, int16 data, frame-major) and splits odd rows = donor, even rows =
   acceptor (smcamera-files.md section 6) [F].
3. For each molecule: top plot donor (green) and `acceptor - leakage*donor` (red); bottom plot
   `fretE = (A - ma - 0.1*(D - md)) / (A + D - ma - md)`, set to -0.5 where A + D = 0 [F]. `md`, `ma` are offsets:
   0 by default; key `t` sets them to the mean of frames 6..end-5 (the first and last 5 frames excluded, as on slide 6),
   key `y` back to 0 [F]. The y-range of the intensity plot uses frames 10..end-10 [F].
4. Keys [F]: `b` back, `g` go to molecule n, `s` save the whole trace as `<N> tr<i>.dat` (time, donor, acceptor),
   `q`/`w`/`e`/`r` pick time ranges with the mouse and append the selected frames to `<key> <N> tr<i> F <k>.dat` in the
   subfolder (this is the "trace range selection"), `u` dwell times -> `total_time.dat` + `no_transitions.dat`,
   `0` writes a zero to `low_fret_dwell_time.dat`, `x` crops one range and saves it.
5. Defects [F]: the loop has no end test (`while Ntraces/2 - 1 > 0`), so it ends with an index error after the last
   molecule; the `x` branch builds the file name from the literal text `' fname '`; `fprintf('%d ...')` is given
   non-integer times; `gamma` and the binned FRET (`binE`) are computed but unused.

**Consequence for the port:** a `.traces` written by the new program is enough for this script; the FRET it shows is
the script's own (beta 0.1, no gamma). A port of this viewer into the application (basic on-site analysis, 0011) would
need: per-molecule browse, offset toggle, range picking with export, dwell-time picking.

## 5. Requirement candidates (to be confirmed by the owner; also listed in ui-requirements.md)

- **R1 Recorder panel:** exposure / kinetic cycle (read back), EM gain, background and data scaler (display only),
  path, film number auto-increment, current / max frames with a "max length" stop, Record / Stop, min / max intensity
  readout, overlay of the two channels and of selected molecules (slide 1-2).
- **R2 Manual molecule pairing in mapping:** with few molecules the user clicks a CH1 spot and its CH2 partner; each
  pair gets its own colour; no frame sequence, threshold or automatic analysis required (slides 3-5). Automatic
  peak finding (U23) stays optional.
- **R3 No automatic analysis step for MT-FRET:** after pairing, traces are built directly (slide 5).
- **R4 `.traces` output with intensities, FRET from the reader:** write smCamera's `.traces` (byte-compatible) so the
  MATLAB scripts work; FRET is recomputed by the reader; the new program's own file also stores FRET and the
  corrections used (slides 3, 12).
- **R5 Mapping shared with the MT view:** pairs picked in fluorescence are shown on the bead image and select the
  corresponding beads, and the other way round (slide 3; extends U22 / U25).
- **R6 FRET formula with corrections as presets:** `E = (I_A - beta I_D) / (I_D + I_A)` after background and
  acceptor direct-excitation correction; beta (~0.1 here), direct-excitation factor and an optional gamma are preset
  values stored with the data (slide 6; extends U28).
- **R7 First / last 5 frames rule:** the red-excited frames at the start and end are used to accept a molecule
  (donor and acceptor colocalise) and are excluded from traces and histograms; the frame counts come from the
  executed illumination sequence, not typed in (slide 6; U24 / 0013).
- **R8 Trace viewer:** molecule-by-molecule browsing (Peak No, previous / next), frame slider, donor / acceptor and
  FRET plots on a time axis, zooms of both spots with radii, background display options (slides 7-9).
- **R9 Histograms from selected frames per channel:** FRET and intensity histograms over several films, frames chosen
  separately for CH1 and CH2, bin / bounds, save (slides 10-11).
- **R10 Import of old smCamera data:** `.smt` -> `.traces` conversion as the converter does, plus reading `.smm`,
  `.pks`, maps (slide 12; smcamera-files.md section 13).

## 6. Open questions for the owner / colleague

1. beta, the direct-excitation factor and gamma actually used (the script has beta 0.1 and an unused gamma 0.76;
   smCamera shows 0.91 / 0.9). Which values go into the default preset?
2. In MT-FRET, is the excitation pattern still 5 red - green - 4 red + 1 green, and are movies short (20 frames,
   "Set Max Length 20") or long (300+)?
3. "Pair a set of molecules at a time": pick one pair after another by hand, or pick in CH1 and let the map propose the
   CH2 partner?
4. Should the mapping step pick beads in the MT view automatically from the fluorescence pairs (needs the JAI <-> EMCCD
   map of U22), or only highlight them?
5. Live maps on the slides have rms ~0.7 px versus 0.05 px in the stored map files: acceptable, or should the new
   program warn above a threshold?
