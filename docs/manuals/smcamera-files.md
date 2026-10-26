# smCamera file formats, read from the files

Source (owner 2026-10-26: "Dropbox\_config\smCameraRelated ... 들어가면 smCamera 관련 코드, 데이터 등등"):
`G:\Data\SiHyeong\Dropbox\_config\smCameraRelated` (read-only; nothing copied into the repo except the short excerpts
below). It holds a program install `smCamera\{Common,Devices,Movies,Run,Tools}`, a real dataset
`LONG - Copy\LONG - Copy\film1.*` (recorded 2026-08-07, 300 frames) and the MATLAB viewer
`a_trace_range_selection_123.m` ([smcamera-workflow-mtfret.md](smcamera-workflow-mtfret.md) section 4).
The parameters smCamera sends to the camera are in [smcamera-emccd-parameters.md](smcamera-emccd-parameters.md); this
note is about the files. Read 2026-10-26 with read-only Python scripts (`open(..., 'rb')`, numpy); no program run.

Verification levels used here:

- **[F]** read from the file (bytes decoded, numbers compared, or text as written).
- **[P]** checked by parsing one file against another (e.g. `.traces` recomputed from `.smt`), with the result stated.
- **[S]** from the colleague's slides (`mtFRET_2.pptx`, screenshots of smCamera dialogs).
- **[I]** inferred; not proven by the files.

## 1. The dataset and how its files relate

| file | size | what it is |
|---|---|---|
| `film1.smm` | 157 286 417 B | raw movie, 300 frames of 512 x 512 uint16 |
| `film1.log` | 352 B | recording settings (text) |
| `film1.tif` | 524 486 B | one 16-bit 512 x 512 image: average of the green-excited frames 6-14 used for peak finding |
| `film1_max.tif` | 524 486 B | one 16-bit image: per-pixel maximum over all 300 frames |
| `film1.pks` | 24 713 B | 462 peak pairs (CH1 position + mapped CH2 position), text |
| `film1.smt` / `film1.smt2` | 2 236 117 B each | per-peak, per-frame signal and background of both channels (float32) |
| `film1.tlog` | 167 B | trace-extraction settings (text) |
| `film1.traces` | 554 406 B | the old ("Old Trace") format the MATLAB scripts read: int16 donor/acceptor traces |

Pipeline [F timestamps + S + P]: Movie Recorder writes `.smm` + `.log` -> Movie Analysis finds peaks (`.pks`, `.tif`,
`_max.tif`) and extracts traces (`.smt`, `.smt2`, `.tlog`, all 2026-08-07) -> File Format Converter, "Convert
Trace(s) To Old Trace(s)" (slide 12), writes `.traces` (2026-08-08) -> MATLAB. `.traces` is exactly `.smt` reduced to
integers (section 5) [P].

## 2. `.smm` - the movie

17-byte little-endian header, then the frames, nothing after them [F, three files]:

| offset | type | field | `LONG/film1` | `Movies/film1` | `Movies/film2` |
|---|---|---|---|---|---|
| 0 | uint16 | frame width (px) | 512 | 512 | 512 |
| 2 | uint16 | frame height (px) | 512 | 512 | 512 |
| 4 | uint8 | bytes per pixel | 2 | 2 | 2 |
| 5 | uint32 | "Background" (display setting) | 3000 | 3120 | 3000 |
| 9 | uint32 | "Data Scaler" (display setting) | 300 | 500 | 1500 |
| 13 | float32 | kinetic cycle (ms) | 101.75 | 101.75 | 101.75 |
| 17 | uint16[frames][height][width] | pixel data, row-major | | | |

- Frame count is **not stored**; it is `(file size - 17) / (w * h * bytes)`. It is an exact integer for all three
  files: 300, 12 and 50 frames [F].
- Background and Data Scaler match the `.log` of the same film in all three cases [F]. They are display / 8-bit-export
  settings of the Movie Recorder, not a camera offset: the raw pixels of `LONG/film1` frame 1 are 2762..4430, median
  2838, below the stored "Background" 3000 [F].
- Exposure time, gain and the camera name are **not** in the `.smm`; they are only in the `.log` [F]. The header field
  names quoted from the exe in smcamera-emccd-parameters.md section 5 are the `.log` keys.
- Pixels are raw camera counts as uint16 (the program reads 32-bit `GetImages` and writes 2 bytes) [F header + I].

**Port:** read `.smm` (memory-map at offset 17) so old movies open in the new viewer and analysis; never write it -
the new program records raw EMCCD frames in its own format with full metadata (decisions 0006, U15).

## 3. `.log` - recording settings

Text, CRLF, key line followed by value line [F]. Example (`LONG/film1.log`):

```
Filming Date and Time / Fri Aug 07 19:37:13 2026     Server Index / 127
Frame Resolution / 512 512        Background / 3000         Data Scaler / 300
Byte Per Pixel / 2                Camera Information / Andor Ixon DU897_BV
Camera Bit Depth / 16             Gain / 299                Exposure Time [ms] / 100.000
Kinetic Cycle Time [ms] / 101.750 Lag Beetween Images [ms] / 1.750   Active Area / 1 512 1 512
```

(Shown as key / value pairs; in the file each is on its own line. "Beetween" is spelled so in the file, with a tab
before "[ms]".) The camera is an **iXon DU897_BV** in all three logs (2017, 2018, 2026) [F]; EM gain was 20, 295 and
299 [F]. Kinetic cycle = exposure + 1.75 ms [F].

**Port:** read it (key/value parser) when importing old movies; the new metadata (U15) covers every key.

## 4. `.pks` - peak pairs

Text, CRLF [F]:

```
Frame Resolution
512 512
Num Channels
2
Num Peak Sets
462
52.00 1.00 282.80 1.00 1, 306.41 1.02 286.78 1.01 1
```

- One line per molecule: CH1 block `, ` CH2 block; each block = `x  s_x  y  s_y  flag` [F layout].
- CH1 x is 8.0..246.6 and CH2 x is 262.4..503.4: **CH1 = left half, CH2 = right half** [F]. CH2 = CH1 shifted by
  +255.8 px in x and +4.1 px in y on average [F].
- `s_x`, `s_y`: always 1.00 in CH1, 0.99..1.03 in CH2 [F]. Meaning unknown; plausibly the local scale of the map
  at that point [I]. `flag` is 1 on every line of this file [F]; plausibly "good peak" (Movie Analysis has "Analyze bad
  peaks") [I].

**Port:** read (to import old selections) and write (so an exported dataset can be reopened in smCamera, if wanted).

## 5. `.smt` / `.smt2` - extracted traces

Little-endian binary [F, P]:

| offset | type | field | `film1.smt` |
|---|---|---|---|
| 0 | uint32 | number of peaks (molecules) | 462 |
| 4 | uint32 | number of frames | 300 |
| 8 | uint32 | byte offset of the data block | 18517 |
| 12 | uint16, uint16, uint8 | unknown (2, 2, 2: channels? bytes per pixel?) | 2, 2, 2 |
| 17 | uint32 | Background (from the movie) | 3000 |
| 21 | uint32 | Data Scaler | 300 |
| 25 | float32 | kinetic cycle (ms) | 101.75 |
| 29 | float32 | peak radius (px) | 3.0 |
| 33 | float32 | peak sigma (px) | 1.6 |
| 37 | per peak, per channel: float32 x, s_x, y, s_y; int32 flag (20 bytes) | the `.pks` table | 462 x 2 x 20 B |
| 18517 | float32 [peak][4][frame] | data | |

- Header ends exactly at the stated offset (37 + 462 x 40 = 18517) and its peak table equals `film1.pks` to the
  printed 2 decimals (max difference 0.005) [P].
- Data = 462 x 4 x 300 float32 = 2 217 600 bytes, the rest of the file exactly [P]. For each peak, four vectors of
  300 frames: **CH1 signal, CH1 background, CH2 signal, CH2 background** [P, see below].
- **`film1.traces` = trunc(signal - background)** for both channels: identical for all 277 200 values with
  truncation toward zero (round: 50 % match, floor: 92-94 %) [P]. So the old trace is background-subtracted intensity,
  no leakage or gamma correction, no FRET.
- The signal is about 16 x the pixel level (peak 0, laser-off frames: 44 717 vs a median pixel of 2838), i.e. a
  weighted sum over the spot; the exact weights (Gaussian with sigma 1.6 px inside radius 3 px?) were not reproduced
  [I]. Background vector rises when the spot is lit, so it is measured close to the spot [F].
- `.smt2` has the identical header and peak table; its data differs (2 213 676 bytes differ): values are about 4.4 x
  those of `.smt` and correlate less with `.traces` (0.84 vs 0.97 for the raw signal) [P]. It is the "2nd traces"
  ("Convert 2nd Traces" checkbox, slide 12) [S]: probably a second extraction with a larger area [I]. Which one the
  colleague uses: `.smt` (FRET Trace opens `*.smt`, slide 8) [S].

**Port:** read `.smt` (old data, and it holds both signal and background, so FRET can be recomputed with other
corrections). Writing `.smt` is optional; writing `.traces` is required for the existing MATLAB scripts (U28).

## 6. `.traces` - the format the MATLAB scripts read

```
int32   len            % frames (300)
int16   Ntraces        % 2 x molecules (924)
int16   raw[len*Ntraces]
```

- MATLAB reads `raw` into `Data(Ntraces, len)` column-major (`Data(index)=raw(index)`), i.e. the file is **frame-major**:
  for frame 1 all traces, then frame 2 ... [F code + P]. Row 2i-1 = donor (CH1) of molecule i, row 2i = acceptor (CH2)
  [F code + P against `.smt`]. Size check: 6 + 2 x 924 x 300 = 554 406 bytes = the file [F].
- Values: int16 counts after background subtraction (-804..13 592 here; negative values are normal) [F].
- **No FRET and no time axis in the file** [F]. The colleague's "Traces file will have both intensities and fret"
  (slide 3) is what the MATLAB script displays: it computes FRET itself (workflow note, section 4) [F code].
- No header for frame time, map, excitation pattern or settings; the time unit is typed in MATLAB (default 0.1 s) [F code].
- int16 limits the value to +-32 767: a bright spot or a large weight could overflow; the writer should clip and warn [I].

**Port:** write `.traces` exactly this way (trunc toward zero, clip to int16) from the new program's per-molecule
intensities, so the lab's MATLAB scripts run unchanged; read it too. Acceptance test: recompute `film1.traces` from
`film1.smt` byte-for-byte [P method above].

## 7. `.tlog` - trace-extraction settings

Text, key/value lines [F]: `Frame Resolution 512 512`, `Frame Cycle [ms] 101.750`, `Num Frames 300`,
`Peak Radius[px] 3.000`, `Peak Sigma[px] 1.600`, `Channel(s) in which peaks were found. CH1 CH2`.
**Port:** read for import; the new metadata replaces it.

## 8. `.tif` outputs

Both TIFFs are little-endian, uncompressed, single 16-bit 512 x 512 strip at offset 8 [F tags].
`film1_max.tif` = per-pixel maximum of all 300 frames (identical, correlation 1.00000, median difference 0) [P].
`film1.tif` = average of frames 6-14 (correlation 0.979, median difference -0.2 counts) [P], i.e. the frames named by
the frame-sequence file `00 6-14.txt` set in Movie Analysis [S + F `analysis.save`]; the exact frame set (6-13 or 6-14)
is not pinned [I]. **Port:** write the same two images (standard TIFF, e.g. `tifffile`); they are what users look at.

## 9. Frame-sequence `.txt` (`Common\FrameSequence\`, 44 files)

One `0`/`1` per line (CRLF), line i = frame i; trailing empty lines occur [F]. Files added since 2025 are the ones the
colleague uses for 20- / 600- / 1500-frame movies [F dates]:

| file | ones at frames | use [S + F `.save`] |
|---|---|---|
| `0 1-5.txt` | 1-5 | CH2 (acceptor) peak finding and histogram "Frames 2": the red-excited first frames |
| `00 6-14.txt` | 6-13 (13 lines) | CH1 peak finding, averaged image, histogram "Frames 1": green-excited frames |
| `0 590-595.txt`, `0 1490-1495.txt` | 590-594, 1490-1494 | last red-excited frames of 600- / 1500-frame movies [I] |
| `alex\6-14 - ch1.txt` / `- ch2.txt` | 7,9,11,13 / 6,8,10,12 | alternating frames (ALEX) |
| `alex\586-594-ch1/ch2`, `alex\1486-1494-ch1/ch2` | odd / even frames | same, at the movie end |

The file names are approximate (`00 6-14` marks 6-13) [F]. The excitation itself is the ShutterManager pattern (next
item), not these files; these only select frames for analysis [F, consistent with smcamera-emccd-parameters.md
section 4]. The `LONG/film1` traces show the pattern directly [P, mean over 462 molecules]: frames 1-5 donor ~80 /
acceptor ~1500 (red only), frames 6-295 donor ~1400 -> 800 / acceptor ~500 -> 300 (green), frames 296-299 red, frame
300 green - matching the ShutterManager files on slide 2: header `R5`, body `G1`, footer "5 frames - 4 red 1 green" [S].

**Port:** read them (import of old analysis settings). In the new program the per-frame excitation is the executed
illumination sequence (decision 0013, U24), stored with the data, and frame selection derives from it.

## 10. Mapping files (`Common\*.txt`, 205 files)

All 205 begin with `Frame Width & Height` [F]: the same 4-block format as `map_Andor1_*.txt`
(smcamera-emccd-parameters.md section 5): frame size, then "CH2 onto CH1 X / Y", "CH1 onto CH2 X / Y", each 16
coefficients + `Mapping Error` (rms px). Names are date + user (`20200906 CW.txt`, `171116 Hyewon (1).txt`, ...),
2013-2020, plus `mapping_20150604_4color.txt` [F]. Per-day maps recorded 2026 live in the data folders (e.g.
`...\20261012.txt` in `mapper.save`) [F].

- Stored rms is small (`20200906 CW`: 0.046-0.052 px) [F]; the colleague's live mappings show rms about 0.70 px with
  116 and 271 point pairs (slide 4) [S] - a much worse fit than the old bead maps [I: different samples or settings].
- Coefficient order: in "CH2 onto CH1 X" the term 4 is 1.017 and in "... Y" term 1 is 0.948, consistent with
  `x' = sum c[4i+j] x^i y^j` [I, as before; unconfirmed].

**Port:** import these into the map format proposal ([../format/mapping.md](../format/mapping.md)); export is not needed
unless smCamera stays in use beside the new program (open question).

## 11. `.tbl`, `.save`, `.setup`

- `.tbl` (9 files): colour look-up tables, "R G B" per line [F]. Display only; the port does not need them.
- Text `.save` (one value per line, labels from the dialogs on the slides [S]):

| file | values [F] | meaning [S] |
|---|---|---|
| `Tools\MovieAnalysis\analysis.save` | (empty map path), `00 6-14.txt`, 3.0, 20.0, 1, 1, 1.6, 6 | map, frame sequence, Peak Radius 3 px, Peak Threshold / Data Scaler 20 %, Find CH1, Find CH2, Peak Sigma 1.6 px, spot radius 6 px |
| `Tools\MovieMapper\mapper.save` | data folder, `00 6-14.txt`, map, 3.0, 20.0, `0 1-5.txt`, `171116 Hyewon (1).txt`, 3.0, 20.0, map, 3.0, 3 | CH1 sequence / radius / threshold, CH2 sequence / ..., Allowable Error 3 px, last value unknown |
| `Tools\Histogram\histogram.save` | `00 6-14.txt`, `0 1-5.txt`, 0.91, 0.0, data folder | Frames 1 and 2, Leakage Correction "ID in CH1" 0.91, "IA in CH1" 0 |
| `Tools\Trace\trace.save` | 0.900, 0.000, 4, 3, data folder | ID1/ID_all 0.9, IA1/IA_all 0, R1 4 px, R2 3 px (F0/Fsum = 1 shown, not stored here) |
| `Tools\MovieRecorder\recorder.save` | 1, 0, 0, data folder (2018) | Set Max Length on, Save as PMA off, Save in 8 bit off [I from dialog order] |

  This corrects the guesses in smcamera-emccd-parameters.md section 5 (e.g. 20.0 is the threshold in %, 1.6 the peak
  sigma) with the dialogs now visible [S].
- `Devices\Camera\camera.save` (200 bytes, 2018): **a raw memory image of a C++ object**, not a text file - it starts
  with what look like a vtable and heap pointers (`0x00479e8c`, `0x02628a30`) [F]. Recognisable values: 512, 512;
  doubles 16.0, 16.0 (pixel size in um [I]); -80 and 20 / -120 (temperature set point and range [I]); doubles 100.0
  and 101.75 (exposure and kinetic cycle in ms); 16 (bit depth), 300 (gain upper limit [I]) [F values]. Not portable;
  the port neither reads nor writes it.
- `Run\smCamera.setup`: `C:\smCamera` (the program root) [F].

## 12. `Run`, `Devices`, `Tools`, `Movies` folders

| item | content [F] |
|---|---|
| `Run\smCamera.exe` | 696 320 B, FileVersion 1.0.0.1, SHA-256 `4722a89a...74f6de` = **the same file** as `G:\Codes\EMCCD control code\smCamera\Run\smCamera.exe` analysed before |
| `Run\atmcd32d.dll` | Andor SDK2, **FileVersion 2.97.30007.0**, 3 649 536 B, dated 2014-07-16 (the earlier copy had 2.79.30013.0, 2 600 448 B) |
| `Run\libtiff3.dll` 3.8.2, `jpeg62.dll` 6b, `zlib1.dll` 1.2.3 | third-party libraries of the exe |
| `Run\Detector.ini` | stock Andor file (see smcamera-emccd-parameters.md section 6) |
| `Devices\Camera\camera.save` | camera dialog state (section 11) |
| `Tools\{Histogram,MovieAnalysis,MovieMapper,Trace,MovieRecorder}\*.save` | last-used dialog values (section 11); dated up to 2026-10-23, so this is the **live install** of the colleague's PC [I] |
| `Movies\film1.smm` + `.log` (2017, 12 frames), `film2.smm` + `.log` (2018, 50 frames) | example movies |

The SDK2 functions smCamera imports exist in 2.97 as in 2.79 [I: same exe, imports by ordinal resolved earlier].
The ordinal resolution in smcamera-emccd-parameters.md section 2 used the 2.79 DLL; ordinals can differ between DLL
versions, so the import table should be re-resolved against 2.97 before relying on it (open).

## 13. What the Python port must read or write (decisions 0011, 0013)

| format | read | write | why |
|---|---|---|---|
| `.smm` + `.log` | yes | no | open old movies; new recordings use the new format with full metadata |
| `.pks` | yes | optional | import / reopen old selections |
| `.smt` | yes | optional | old traces with signal and background separate |
| `.traces` | yes | **yes** | the lab's MATLAB scripts (0011 MATLAB-first, U28); byte-exact with trunc + int16 |
| `.tif`, `_max.tif` | - | yes | the images users check |
| frame-sequence `.txt` | yes | no | old analysis settings; new: executed illumination sequence (0013) |
| map `.txt` | yes | open question | import into [../format/mapping.md](../format/mapping.md) |
| `.tlog`, text `.save` | yes (import) | no | settings migration |
| `camera.save`, `.tbl`, `.setup` | no | no | memory dump / display only |

## 14. Open questions

1. `.smt2`: what is the "2nd trace" (larger area? different weighting?) and does anyone use it?
2. The `s_x`, `s_y` columns and the `flag` of `.pks`, and the three small header fields (2, 2, 2) of `.smt`.
3. Exact spot weights behind the `.smt` signal (to reproduce smCamera's intensities in the new program, not just the
   format).
4. Should the new program also write `.smm` / `.smt` / map `.txt` so smCamera can open its data (running both side by
   side), or only `.traces`?
5. Re-resolve smCamera's 55 SDK imports against `atmcd32d.dll` 2.97.
