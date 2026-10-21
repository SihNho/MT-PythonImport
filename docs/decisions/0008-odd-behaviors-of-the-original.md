# 0008 — Odd behaviors of the original program

**Decided:** 2026-10-21

"Odd" means behavior that may not be intended, or that easily misleads a new reader. It does not mean wrong.

| Kind | Rule | Examples |
|---|---|---|
| Computation | **reproduce exactly** (fixing it is a separate decision, see 0003) | single-precision steps; the out-of-range baseline index; the phase shift applied to an already-shifted spectrum |
| Existing file formats | **reproduce byte-identically**; the new HDF5 uses correct names and units | the `.tra` header calls the frame column "time"; z is labelled nm but looks like µm; `.cal` is big-endian while `.tra` is little-endian; CP949 header text |
| UI and workflow | **may be fixed**, each fix recorded as an *intentional change* in the specification | no "stop without saving" (users must abort LabVIEW); an unused `- Cal Zero` control; `Cal Zero` sounds like calibration but is a magnet-motor preset; frames lost when a window is dragged |
| Hardware | **actions unchanged**; interpretations such as offsets written down; open questions go to the project owner | the rotor angle offset and its intended zero; VI globals shared between loops |

A control or code path is dropped as unused only after the wiring shows it is unreachable, never on memory alone.
