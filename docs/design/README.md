# Design and structure — where everything is

A map of the documents that define what the new program is and how it is built. Start here before GUI, device-layer
or MT-TIRF work. Written 2026-10-24; keep it current when a document is added or superseded.

## 1. Principles and decisions (binding)
[decisions/README.md](../decisions/README.md) — 0001-0015. The ones that shape the architecture most:
- 0001 principles (safeguards restrain AI tools, not users; no AI needed after the project)
- 0003 tracking port first, swappable stages; 0004 numeric verification
- 0005 JAI = master clock, Arduino divides frames and gates lights
- 0006 data format (`.tra` / `.cal` byte-compatible + HDF5 with a `metadata` group)
- 0010 magnet position is raw, force derived · 0011 MATLAB-first analysis · 0012 partial automation first
- 0013 MT-TIRF: extensible illumination and analysis plug-ins · 0014 AI gateway
- **0015 extension architecture**: fixed core, extension levels, one public function layer, protected rig safety profile

## 2. What the owner asked for
- [spec/ui-requirements.md](../spec/ui-requirements.md) — U1-U37: screens, presets, metadata, protocols (blocks +
  script), screening, mapping, illumination, FRET and flexible measurements, focus and camera position, sticking
  detection, extension levels. Each item quotes the owner.
- [spec/questions-for-owner.md](../spec/questions-for-owner.md) — open and answered questions.
- [spec/](../spec/README.md) 0-5 — behaviour of the LabVIEW program step by step.

## 3. How it is built
- [design/api.md](api.md) — the public function layer (draft v0): conventions, function groups, safety behaviour,
  example experiment script.
- [format/mapping.md](../format/mapping.md) — map file format (proposal), detection per target.
- [format/](../format/) — `.tra` / `.cal` layouts.
- [plan.md](../plan.md) — phases 0-11.

## 4. The rig
- [rig-facts.md](../rig-facts.md) — optics, cameras, objectives (MT 50x oil for the running nucleosome project;
  MT-TIRF UPlanApo 60x/1.50), samples, calibration, fixture.
- [hardware/mt-tirf-optical-layout.svg](../hardware/mt-tirf-optical-layout.svg) — editable optical schematic
  (2026-10-06 v1; update in place).
- [manuals/](../manuals/README.md) — one manual per device; [smcamera-emccd-parameters.md](../manuals/smcamera-emccd-parameters.md)
  for the old fluorescence software.

## 5. Evidence behind the choices
- [methods/tracking-benchmarks-explained.md](../methods/tracking-benchmarks-explained.md) (+ `.ko.md`) — how the
  tracker works, what was tested, results, error budget, references.
- [results/](../results/) — raw bench reports.
- [literature/reports/](../literature/reports/) — literature survey of tracking methods.

## 6. Look and feel
- [mockups/2026-10-23-main-window/](../mockups/2026-10-23-main-window/README.md) — source of the clickable mock-up
  (https://claude.ai/artifact/Hg7YRQbKfDN8jZyEDeMLHd).
