# `.tra` and `.cal` file formats (as written by the LabVIEW program)

Reverse-engineered on 2026-10-21 from a recorded pair of files (7 beads, 100,081 rows) and a second pair (5 beads), and cross-checked against the NumPy reader used to verify the tracking kernel. **Not yet confirmed against the lab's MATLAB readers.** Items marked *inferred* need that confirmation.

## `.tra` — traces

```
[U32 little-endian  header_length]
[header text, header_length bytes, Windows code page 949 (Korean locale)]
[U32 LE rows][U32 LE cols]                 <- a LabVIEW 2D array header
[rows x cols  float64 little-endian]        <- row-major
```

**Header text** (one example, line by line):
- creation date and time;
- `Raw data file of N bead xyz trace`;
- `cal cluster:` followed by the full path of the matching `.cal` file;
- `file 0 of a series` (files are split; the suffix `-000`, `-001`, … numbers them);
- `actual data points/nominal: 100081/2000000`;
- `Data follows in order: time, trans, rot x1,y1,z1,x2,y2,z2,....`;
- `NOTE: x,y are msd in PIXELS; z is measured in UNCORRECTED nm (the index difference of oil/water is not in z!)`.

**Columns:**
| col | content |
|---|---|
| 0 | frame number = camera buffer number − first buffer number. Gaps mean lost frames. The header calls it "time" |
| 1 | magnet ("trans") position |
| 2 | rotor position |
| 3 + 3i, 4 + 3i, 5 + 3i | x, y, z of bead i+1 |

- **Bead 1 is the reference bead** (the first click). Its z noise is the smallest in both files. There are no separate reference columns; analysis code takes them from bead 1.
- x, y are in pixels.
- **z appears to be in µm** (values around 3), despite the header saying nm (*inferred*).
- z values pinned at −1.0 or 5.9 look like lost-bead or out-of-range markers (*inferred*).

## `.cal` — calibration

LabVIEW flattened data, **big-endian** (unlike `.tra`):

```
[I32 n][I32 2]            n x 2 float64     bead x, y picked
[I32 n][I32 S][I32 L]     n x S x L float64 radial-profile stack per bead (S = 60 slices, L = 119)
tail:
  I32 S (60)
  I32 n
  per bead: 3 x I32
  float64 z step (0.1)
  I32 number of averages (20)
  string (I32 length + bytes, CP949): date, e.g. "2026년 9월 7일 월요일 오전 12:10:44"
  I32 n + per-bead flags
  float64 nm per pixel (84.0)
```

## Pitfalls for readers
- **Mixed byte order** between the two files.
- The header text is **CP949**, not UTF-8.
- Use absolute buffer numbers (see decision 0005) when aligning with other data. The `.tra` frame column is relative to the first saved buffer.
