# `.tra` and `.cal` file formats (as written by the LabVIEW program)

Reverse-engineered on 2026-10-21 from a recorded pair of files (7 beads, 100,081 rows) and a second pair (5 beads), and cross-checked against the NumPy reader used to verify the tracking kernel. The 5-bead pair is `cal002` / `tra002-000` (10,043 rows) in
`G:\Data\SiHyeong\20260906 Kimlab - 50bp 16X WT 90Hz 1p2 Ramp_Newbatch\test\`, also the V6 replay fixture.
**Not yet confirmed against the lab's MATLAB readers.** Items marked *inferred* need that confirmation.

## `.tra` — traces

```
[U32 little-endian  header_length]
[header text, header_length bytes, Windows code page 949 (Korean locale)]
[U32 LE rows][U32 LE cols]                 <- a LabVIEW 2D array header
[rows x cols  float64 little-endian]        <- row-major
```

Written by `save N xyz traces.vi`: `Format Into String` builds the header, `Write to Binary File` writes it with
the array size prepended and a byte-order constant whose value is unread; the data show little-endian (wiring:
V6 wiki page `docs/wiki/subvi/save N xyz traces.json`; data: the recorded files).

**Header text** (one example, line by line). Lines end with LF (0x0A) only, and the last line has no line end
(data: `tra002-000`, 385-byte header, 11 lines):
- weekday abbreviation, then date and time, e.g. `월 2026-09-07 02:12:44`;
- `Raw data file of N bead xyz trace`;
- `cal cluster:`, and on the next line the full path of the matching `.cal` file;
- `file 0 of a series` (files are split; the suffix `-000`, `-001`, … numbers them);
- `actual data points/nominal: 100081/2000000` (rows in this file / nominal rows per file);
- `Data follows in order:`, and on the next line `time, trans, rot x1,y1,z1,x2,y2,z2,....`;
- `NOTE: x,y are msd in PIXELS;` / `z is measured in UNCORRECTED nm` / `(the index difference of oil/water is not in z!)`
  on three lines.

**Columns:**
| col | content |
|---|---|
| 0 | frame number = camera buffer number − first buffer number (owner, 2026-09-01). Gaps mean lost frames. The header calls it "time". In `tra002-000` the first row is frame 4, not 0, and there are 124 gaps (largest 41). V6 found that the wire feeding `save trace.vi`'s `frame index` comes from the frame loop's counter (V6 `docs/fixture-recording.md`, 2026-10-09 correction); how that yields gaps is open |
| 1 | magnet ("trans") position, mm (*inferred*: the panel shows `Trans Pos (mm)`; the first row of `tra002-000` is 30.0, the value of the start-up control `If no: current pos z?`) |
| 2 | rotor position, degrees (*inferred* from `Rot pos (deg)`) |
| 3 + 3i, 4 + 3i, 5 + 3i | x, y, z of bead i+1 |

- **Bead 1 is the reference bead** (the first click). Its z noise is the smallest in both files. There are no separate reference columns; analysis code takes them from bead 1.
- x, y are in pixels.
- **z appears to be in µm** (values around 3), despite the header saying nm (*inferred*).
- z values pinned at −1.0 or 5.9 look like lost-bead or out-of-range markers (*inferred*). −1 is the kernel's
  lost-bead marker in x, y, z and in the slice index (V6 `docs/stage2-assembly-step-e.md`). 5.9 = (60 − 1) × 0.1, the
  top of the calibration range, and it is stored as `5.900000087916851`, a single-precision 5.9 widened to float64
  — z passes through single precision (data: `tra002-000`, 13 values of each).

## `.cal` — calibration

LabVIEW flattened data, **big-endian** (unlike `.tra`). Written in one call: the calibration cluster through
`Write to Binary File` with `byte order` big-endian and sizes prepended, after a file dialog (wiring: V6 node census
of diagram 169; behavior in [../spec/3-calibration.md](../spec/3-calibration.md) F3.05). The field names in brackets
are the cluster's element names read on diagrams 6 and 169; matching each name to a position is *inferred* from the
values.

```
[I32 n][I32 2]            n x 2 float64     bead x, y picked                  [x,y pos array]
[I32 n][I32 S][I32 L]     n x S x L float64 radial-profile stack per bead     [cal image array]
                                            (S = 60 slices, L = 119 = cross length 120 - 1)
tail (155 bytes for n = 5):
  I32 S (60)                                                                  [# slices in stack]
  [I32 n][I32 3]  n x 3 I32, e.g. 0,25,23 / 0,25,18 ...                       [bandpass/forget array] (inferred)
  float64 z step: bytes 3FB99999A0000000 = 0.10000000149011612,               [obj step between slices]
          a single-precision 0.1 widened to float64 (not 0.1 exactly)
  I32 number of averages (20)                                                 [# avg per slice] (inferred)
  string (I32 length + bytes, CP949): date and time with CR (0x0D) after      [Date and time]
          each part, e.g. "2026년 9월 7일 월요일\r오전 2:10:20\r" (35 bytes)
  [I32 n] n x I32 flags, e.g. 0,1,1,1,1 (bead 1 = 0)                          [exp/ref array] (inferred)
  float64 nm per pixel (84.0)                                                 [Pixel distance]
```

The tail was decoded byte for byte from `cal002` (5 beads, 285,855 bytes; no bytes left over). An earlier version of
this page listed the bead triples as "I32 n, per bead 3 × I32", missing the second dimension (3) of the 2D array, and
the z step as 0.1.

## Pitfalls for readers
- **Mixed byte order** between the two files.
- The header text is **CP949**, not UTF-8.
- Use absolute buffer numbers (see decision 0005) when aligning with other data. The `.tra` frame column is relative to the first saved buffer.
