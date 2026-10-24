# Coverage — every front-panel object and every case / event frame

Each row maps one object of the original VI to a feature heading in the step files, or says `unknown` (with what
would settle it) or `unused` (only with wiring evidence, decision 0008). Checked by
[tools/spec_coverage.py](../../tools/spec_coverage.py).

## Inventory source

<!-- inventory: panel=114 frames=81 -->
<!-- source-dir: G:/Codes/LabVIEW_Codes/MinLab/zz_LabView VI/AAA_UNIST/2. Tracking/V6_ParallelLoop/tools/bench -->

- **Front panel: 114 objects** (60 controls, 54 indicators) — `V6:tools/bench/main_vi_panel_wiring.json`, read from
  the VI's own `Panel.Controls[]` (described in `V6:docs/main-vi-panel-map.md`). Top-level objects only: the read
  is not recursive, so elements inside clusters or tab pages are not rows (`V6:docs/main-vi-stop-and-save.md`
  section 1). Row order = the VI's tab order (`P000`–`P113`).
- **Frames: 81** — the 76 `CaseStructure` frames and 5 `EventStructure` frames among the 170 diagrams of
  `V6:tools/bench/diagram_tree_main.json` (37 case structures and 2 event structures). Rows are named by the
  diagram index `D<n>`.
- Both were measured on the working copy `Min_Track N beads V6_ParallelLoop.vi` (see [README.md](README.md),
  "Sources"). That its front panel equals the original 4.5 panel is *not measured* (Q0.11).
- **Diagrams** column (panel table): diagrams that hold the object's terminal wire (`main_vi_netmap.json`) or a
  local / `Value` property node named after it (`main_vi_node_labels.json`). `-` = the terminal wire is not on any
  netmap diagram (front-panel terminals are not nodes).
- **Nodes on the frame** (frame table): node labels from `main_vi_node_labels.json`. Structures nested in a frame are
  listed as nodes, except flat sequences, which never appear as nodes. `(empty)` = no node at all.

## Front-panel objects

| # | object | kind | diagrams | feature | note |
|---:|---|---|---|---|---|
| P000 | `stop (end)` | CTL | D43 | F5.01 |  |
| P001 | `Total Lost Frames` | IND | D78 | F4.03 |  |
| P002 | `Focus Step (F1)` | CTL | D16, D43, D99 | F1.02 |  |
| P003 | `+ Inc (PgUp)` | CTL | D16, D43, D99 | F1.02 |  |
| P004 | `- Inc (PgDn)` | CTL | D16, D43, D99 | F1.02 |  |
| P005 | `File Size` | IND | - | F4.11 |  |
| P006 | `error out 2` | IND | - | F0.10 |  |
| P007 | `File # Saved` | IND | D43 | F4.11 |  |
| P008 | `file progress` | IND | D8, D43 | F4.11, F5.02 |  |
| P009 | `Missing Frames?` | IND | D43, D157 | F4.03, F3.02 | also written on D157 during the Z scan |
| P010 | `Pos within cal image` | IND | D8, D43 | F4.04 |  |
| P011 | `continue tracking` | CTL | D1, D9, D16, D17 | F4.01, F0.08 |  |
| P012 | `Image` | IND | D16, D17, D97 | F4.01 |  |
| P013 | `Reset Tracking` | CTL | D43, D82 | F4.05 |  |
| P014 | `exp/ref \narray` | IND | D16 | F2.04 |  |
| P015 | `Send` | CTL | D20 | F1.05 |  |
| P016 | `Rot step (turns)` | CTL | D20 | F1.07 |  |
| P017 | `HOME` | CTL | D20 | F1.05 |  |
| P018 | `Rot pos (deg)` | IND | D8, D20, D43, D116 | F1.08, F0.07 |  |
| P019 | `Max Trans Pos` | IND | - | F0.09 |  |
| P020 | `Z/dZ` | CTL | D43 | F4.09 |  |
| P021 | `Correction Factor` | CTL | D43 | F4.09 |  |
| P022 | `Trans Speed (mm/s)` | CTL | D5, D20, D91, D129 | F1.03 |  |
| P023 | `Stop Trans` | CTL | D20 | F1.05 |  |
| P024 | `Force (pN) vs Extension (nm) ` | IND | D1, D43 | F4.10, F0.08 |  |
| P025 | `# FD points` | CTL | D19 | F4.02 |  |
| P026 | `Lc` | CTL | D53, D55 | F4.10 |  |
| P027 | `Lp` | CTL | D43 | F4.10 |  |
| P028 | `Baseline` | CTL | D43 | F4.10 |  |
| P029 | `Exp Baseline` | CTL | D53, D74 | F4.10 |  |
| P030 | `Pos: Diffraction Pattern` | IND | D43 | F4.04 |  |
| P031 | `Fix to a Certain Pattern` | CTL | D43 | F4.06 |  |
| P032 | `Focus Pos (Track)` | IND | D99 | F4.06, F1.02 |  |
| P033 | `Focus Deviation from the Center` | CTL | D73 | F4.06 |  |
| P034 | `Width` | IND | D87, D97 | F0.02 |  |
| P035 | `Height` | IND | D87, D97 | F0.02 |  |
| P036 | `min value` | IND | D43 | F4.05 |  |
| P037 | `Auto-Reset` | CTL | D43 | F4.05 |  |
| P038 | `Auto-Focus` | CTL | D43 | F4.06 |  |
| P039 | `# of Auto-Reset` | IND | D1, D43, D70, D71 | F4.05 |  |
| P040 | `Auto-reset zero` | CTL | D1 | F4.05, F0.08 | meaning unknown (Q4.05) |
| P041 | `Lost Frame Message` | IND | D1, D84 | F5.03, F0.08 | also reset on D1 (F0.08) |
| P042 | `# of Points` | CTL | D8 | F4.04 |  |
| P043 | `Autoreference? 1=Y` | CTL | D2 | F0.04 |  |
| P044 | `If no: current pos z?` | CTL | D2 | F0.04 |  |
| P045 | `Current pos rot?` | CTL | - | F0.06 | its terminal enters the start-up sequence uid 3593 |
| P046 | `Set Focus  (0->50)` | CTL | - | F0.05 | its terminal enters the start-up sequence uid 3593 |
| P047 | `Limit of Program` | CTL | D43 | F4.05, F5.01 |  |
| P048 | `Limit of Auto-Focus` | CTL | D43 | F4.06 |  |
| P049 | `stop (end) 2` | CTL | D43 | F5.01 |  |
| P050 | `Start Moving?` | IND | D59, D61, D66, D69 | F4.08 |  |
| P051 | `Reached clamp` | IND | D18, D61, D66, D67 | F4.08 |  |
| P052 | `SubCycle` | IND | D43, D59, D69 | F4.08 |  |
| P053 | `Set # of Cycles` | CTL | D43 | F4.08 |  |
| P054 | `Start Cycles` | CTL | D18, D43, D59 | F4.08 |  |
| P055 | `Initial Time at Start` | IND | D64, D67 | F4.08 |  |
| P056 | `Estimated end time (min)` | IND | D43 | F4.08 |  |
| P057 | `Time span after start (min)` | IND | D61 | F4.08 |  |
| P058 | `Switch` | CTL | D43, D57, D59 | F4.08 |  |
| P059 | `Cycle Start Time` | IND | D56, D57 | F4.08 |  |
| P060 | `+ -> Lc` | CTL | D53 | F4.10 |  |
| P061 | `x -> Lc` | CTL | D53 | F4.10 |  |
| P062 | `pixel distance (nm)` | CTL | - | F3.01, F3.06 |  |
| P063 | `Cross length (pixels)` | CTL | D86 | F3.01, F3.06 |  |
| P064 | `z step (um)` | CTL | D86 | F3.01 |  |
| P065 | `# to avg per image` | CTL | D86 | F3.01 |  |
| P066 | `# images in stack` | CTL | D86 | F3.01 |  |
| P067 | `Focus Pos (Start)` | CTL | D87, D88 | F0.05 |  |
| P068 | `color table string` | IND | D87 | F1.01 |  |
| P069 | `Color table` | IND | D87 | F1.01 |  |
| P070 | `1 L-Turn` | CTL | D21, D25, D100, D104 | F1.06 |  |
| P071 | `1 R-Turn` | CTL | D21, D29, D100, D108 | F1.06 |  |
| P072 | `Rot Step (deg) ` | CTL | D32, D33, D111, D112 | F1.07 |  |
| P073 | `Rot \nSpeed` | CTL | D32, D111 | F1.07 |  |
| P074 | `Send to Rot` | CTL | D21, D33, D100, D112 | F1.07 |  |
| P075 | `- Cal Zero` | CTL | D21, D37, D100, D122 | F1.04 | reachable: read on D21 / D100, drives `MOV` (Q1.04) |
| P076 | `+ Cal Zero` | CTL | D21, D41, D100, D126 | F1.04 |  |
| P077 | `Trans Step (mm)` | CTL | D20, D87, D129, D130 | F1.03 |  |
| P078 | `Send to Trans` | CTL | D20, D100, D130 | F1.03 |  |
| P079 | `Done Picking \nBeads?` | CTL | - | F2.03, F0.01 | its terminal is the picking loop's stop terminal (wire 19456) |
| P080 | `Bead Pos` | IND | D141 | F2.01 |  |
| P081 | `Waveform Graph` | IND | D148 | F3.02 |  |
| P082 | `Focus Pos (Cal)` | IND | D87, D146, D148, D151, D153 | F3.02 |  |
| P083 | `Picture` | IND | D17, D97, D99, D141, D158 | F1.01, F2.01 |  |
| P084 | `Intensity vs Radius` | IND | D86, D158 | F3.03 |  |
| P085 | `size(s)` | IND | D167 | F3.04 |  |
| P086 | `output cluster` | IND | D169 | F3.05 |  |
| P087 | `Trans Pos (mm)` | IND | D5, D20, D43 | F1.08, F0.07 |  |
| P088 | `Max Travel Limit` | IND | - | F0.03 |  |
| P089 | `Cal Zero` | IND | D21, D87, D100 | F1.04 | computed on D87 |
| P090 | `Cal File Path` | IND | D9 | F4.11 |  |
| P091 | `Track File Path` | IND | D9 | F4.11 |  |
| P092 | `Count` | CTL | D86, D142, D144 | F2.01 |  |
| P093 | `Mp measure freq` | CTL | D19 | F1.09 |  |
| P094 | `Force\nsmoothing\nhalf-width` | CTL | D43 | F4.10 |  |
| P095 | `Extension\nmedian filter\nhalf-width` | CTL | D43 | F4.10 |  |
| P096 | `Extension (nm) vs Time (Frame #)` | IND | D43, D55 | F4.10 |  |
| P097 | `# DT points` | CTL | D19 | F4.02, F4.10 |  |
| P098 | `Frame rate` | CTL | D43, D99 | F4.06, F1.01 | the autofocus period in frames, not the camera rate |
| P099 | `Total cycle #` | IND | D43 | F4.08 |  |
| P100 | `RotationVISA` | IND | D9 | F0.06 |  |
| P101 | `IMAQimage` | IND | D16 | F0.02 |  |
| P102 | `CamSessionOut` | IND | D16 | F0.02 |  |
| P103 | `current image number` | IND | D43 | F4.03 |  |
| P104 | `TurnOff` | IND | D18, D20, D43 | F5.01, F0.01 | written with the frame-loop stop condition (wire 3457), read by the motor loop |
| P105 | `CycleSchedule` | CTL | D43, D46, D47 | F4.07 |  |
| P106 | `Mag Position` | IND | D18, D43, D47 | F4.07 |  |
| P107 | `NumCol` | CTL | D46, D47 | F4.07 |  |
| P108 | `x < y?` | IND | D61 | F4.08 | debug indicator: default primitive name |
| P109 | `Target` | IND | D69 | F4.08 | debug indicator |
| P110 | `Value` | IND | D61 | F4.08 | debug indicator: default name |
| P111 | `abs(x)` | IND | D61 | F4.08 | debug indicator: default primitive name |
| P112 | `Value 2` | IND | D43 | unknown | wired to the output of a `Value` property read on D43; the object read needs a VI read (Q4.10) |
| P113 | `Value 3` | IND | D43 | unknown | wired to the output of a `Value` property read on D43; the object read needs a VI read (Q4.10) |

## Case and event frames

| # | owner | nodes on the frame | feature | note |
|---:|---|---|---|---|
| D003 | CaseStructure | Build Array; MOV.vi | F0.04 |  |
| D004 | CaseStructure | GOH.vi | F0.04 |  |
| D013 | CaseStructure | In Range and Coerce | F0.05 |  |
| D014 | CaseStructure | (empty) | F0.05 | empty arm of the coerce case, by adjacency |
| D022 | CaseStructure | (empty) | F1.06 |  |
| D023 | CaseStructure | (empty) | F1.06 |  |
| D026 | CaseStructure | (empty) | F1.06 |  |
| D027 | CaseStructure | (empty) | F1.06 |  |
| D030 | CaseStructure | (empty) | F1.07 |  |
| D031 | CaseStructure | (empty) | F1.07 |  |
| D034 | CaseStructure | (empty) | F1.04 |  |
| D035 | CaseStructure | (empty) | F1.04 |  |
| D038 | CaseStructure | (empty) | F1.04 |  |
| D039 | CaseStructure | (empty) | F1.04 |  |
| D045 | EventStructure | Event Data Node | F4.07 |  |
| D046 | EventStructure | Event Data Node; Array Subset; CycleSchedule | F4.07 |  |
| D047 | EventStructure | Event Data Node; For Loop; Index Array; CycleSchedule; Replace Array Subset; NumCol; Array Size | F4.07 |  |
| D051 | CaseStructure | (empty) | unknown | range test (`Less?`, `Greater?`, `Or`); purpose needs a VI read |
| D052 | CaseStructure | Less?; Or; Greater? | unknown | range test (`Less?`, `Greater?`, `Or`); purpose needs a VI read |
| D054 | CaseStructure | (empty) | F4.10 |  |
| D055 | CaseStructure | Lc; Negate; Extension (nm) vs Time (Frame #) | F4.10 |  |
| D056 | CaseStructure | Cycle Start Time | F4.08 |  |
| D057 | CaseStructure | Tick Count (ms); Switch | F4.08 |  |
| D058 | CaseStructure | (empty) | F4.08 | empty frame inside the cycling block D56-D69 |
| D059 | CaseStructure | Start Cycles; SubCycle; Switch; Start Moving? | F4.08 |  |
| D060 | CaseStructure | (empty) | F4.08 | empty frame inside the cycling block D56-D69 |
| D061 | CaseStructure | Case Structure; Start Moving?; Absolute Value; Less?; Not; Tick Count (ms); Subtract; Divide; Round Toward -Infinity; Reached clamp; And | F4.08 |  |
| D062 | CaseStructure | Case Structure | F4.08 |  |
| D063 | CaseStructure | (empty) | F4.08 | empty frame inside the cycling block D56-D69 |
| D064 | CaseStructure | Initial Time at Start; Subtract; Tick Count (ms); Multiply; Case Structure; Less? | F4.08 |  |
| D065 | CaseStructure | (empty) | F4.08 | empty frame inside the cycling block D56-D69 |
| D066 | CaseStructure | Start Moving?; Reached clamp | F4.08 |  |
| D067 | CaseStructure | Tick Count (ms); Reached clamp | F4.08 |  |
| D068 | CaseStructure | Subtract; Index Array; Decrement | F4.08 |  |
| D069 | CaseStructure | Increment; Start Moving?; SubCycle; VEL.vi; Build Array; Index Array; Subtract; MOV.vi; Decrement | F4.08 |  |
| D070 | CaseStructure | # of Auto-Reset | F4.05 | case uid 10445 (auto-reset counter) |
| D071 | CaseStructure | Increment | F4.05 | case uid 10445 (auto-reset counter) |
| D072 | CaseStructure | (empty) | F4.06 | case uid 10407, pass-through frame |
| D073 | CaseStructure | Divide; Subtract; Multiply; Add; Get Current Position.vi; Move Axis Relative.vi; In Range and Coerce | F4.06 | case uid 10407, move frame |
| D075 | CaseStructure | N bead plot dZ.vi | F4.09 |  |
| D076 | CaseStructure | N bead plot Z.vi | F4.09 |  |
| D077 | CaseStructure | (empty) | unknown | empty frame; owning case not identified (case uid 5540's two pass-through frames are among the frame loop's empty frames) |
| D078 | CaseStructure | Subtract | unknown | two subtractions; owning case not identified |
| D079 | CaseStructure | (empty) | unknown | empty frame; owning case not identified (case uid 5540's two pass-through frames are among the frame loop's empty frames) |
| D080 | CaseStructure | (empty) | unknown | empty frame; owning case not identified (case uid 5540's two pass-through frames are among the frame loop's empty frames) |
| D081 | CaseStructure | (empty) | unknown | empty frame; owning case not identified (case uid 5540's two pass-through frames are among the frame loop's empty frames) |
| D082 | CaseStructure | Reset Tracking | F4.05 | resets `Reset Tracking` |
| D084 | CaseStructure | Lost Frame Message | F5.03 |  |
| D085 | CaseStructure | (empty) | F5.03 |  |
| D093 | CaseStructure | To Word Integer; Flatten To String | F1.01 | colour-table data string, inferred from wire 14726 |
| D094 | CaseStructure | Decrement; To Word Integer; Bundle; Flatten To String; For Loop; Concatenate Strings | F1.01 | colour-table data string, inferred from wire 14726 |
| D101 | CaseStructure | (empty) | F1.06 |  |
| D102 | CaseStructure | (empty) | F1.06 |  |
| D105 | CaseStructure | (empty) | F1.06 |  |
| D106 | CaseStructure | (empty) | F1.06 |  |
| D109 | CaseStructure | (empty) | F1.07 |  |
| D110 | CaseStructure | (empty) | F1.07 |  |
| D113 | CaseStructure | (empty) | F1.08 | selector unknown |
| D114 | CaseStructure | (empty) | F1.08 | selector unknown |
| D119 | CaseStructure | (empty) | F1.04 |  |
| D120 | CaseStructure | (empty) | F1.04 |  |
| D123 | CaseStructure | (empty) | F1.04 |  |
| D124 | CaseStructure | (empty) | F1.04 |  |
| D127 | CaseStructure | (empty) | F1.03 |  |
| D128 | CaseStructure | (empty) | F1.03 |  |
| D131 | CaseStructure | (empty) | F2.02 | empty frame of an overlay case, by adjacency |
| D132 | CaseStructure | rect coord from center.vi; Array To Cluster; Draw Grayed Out Rect.vi; Add | F2.02 |  |
| D133 | CaseStructure | For Loop | F2.02 |  |
| D135 | CaseStructure | (empty) | F2.02 | empty frame of an overlay case, by adjacency |
| D136 | CaseStructure | (empty) | F2.02 | empty frame of an overlay case, by adjacency |
| D138 | CaseStructure | (empty) | F2.02 | empty frame of an overlay case, by adjacency |
| D139 | EventStructure | Event Data Node | F2.01 |  |
| D140 | EventStructure | Event Data Node; Stacked Sequence Structure | F2.01 |  |
| D143 | CaseStructure | (empty) | F2.01 |  |
| D144 | CaseStructure | Count | F2.01 |  |
| D151 | CaseStructure | Add; Move Axis to Position.vi; Multiply | F3.02 |  |
| D152 | CaseStructure | (empty) | F3.02 |  |
| D159 | CaseStructure | (empty) | F3.03 |  |
| D160 | CaseStructure | Multiply; Index Array; calibration- generate 1 I of r, reentrant.vi; Build Array; Replace Array Subset | F3.03 |  |
| D161 | CaseStructure | Multiply; Index Array; Increment; calibration- generate 2 I of r, reentrant.vi; Build Array; Replace Array Subset | F3.03 |  |
| D162 | CaseStructure | Multiply; Index Array; Increment; calibration- generate 2 I of r, reentrant.vi; Replace Array Subset; calibration- generate 1 I of r, reentrant.vi; Build Array | F3.03 |  |
