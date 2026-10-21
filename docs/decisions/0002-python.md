# 0002 — Python

**Decided:** 2026-10-21

**Decision:** The application is written in Python. Time-critical computation uses **numba** (compiled, multi-core, releases the GIL). For many beads it uses the existing **CUDA** tracking kernel from the LabVIEW project. No separate C code unless numba proves insufficient.

## Why
- **The timing guarantees are in hardware** (decision 0005): the camera clock and the Arduino trigger. The host language therefore needs throughput, not hard real-time behavior, and that removes the main reason for C/C++.
- **The heavy work runs outside the GIL.** Camera SDK calls (ctypes), NumPy, numba (`nogil`), serial I/O and file writing all release the GIL. Only light coordination code stays in Python.
- **Evidence:**
  - A Python + ctypes acquisition test already kept up at 150 Hz with a 6 ms per-frame processing budget and zero lost frames.
  - The same CUDA DLL called from Python ran faster than when called from inside LabVIEW.
- **Maintainability:** the lab mostly uses MATLAB, and NumPy is close to MATLAB. C/C++ would leave few people able to maintain the code.
- **Reuse:** a NumPy reference of the tracking kernel (matching LabVIEW to about 1e-7 px in XY and 1e-6 µm in Z), the CUDA kernel, the camera ctypes layer and the motor protocols already exist in Python.
- **Ecosystem:** HDF5, SciPy, MATLAB interoperability, Qt GUIs.

## Risks and how they are handled
| Risk | Handling |
|---|---|
| GIL | hot loops in numba `nogil`; acquisition inside SDK calls; GUI optionally in a separate process |
| Small-array overhead in per-bead code | batch beads, or numba |
| Garbage-collection pauses, timer jitter | preallocated buffers; event-driven waits instead of `sleep` loops |
| Frame loss when windows are dragged | acquisition, tracking and saving never touch the GUI thread; the GUI reads only the latest frame at about 30 Hz |

## Check before committing to it fully
Replay recorded frames through Python + numba and measure the per-frame time for N beads, its scaling with cores, and the worst-case latency against the 6 ms budget at 150 Hz.
