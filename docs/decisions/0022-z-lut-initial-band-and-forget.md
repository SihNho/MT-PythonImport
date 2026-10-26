# 0022 — Initial z-LUT settings at 50x: LOW 0 / HIGH 40 / forget 10; no further edits to the V6 LabVIEW code

**Decided:** 2026-10-27 (owner, in chat)

Owner:
- "Initial value만 그렇게 바꿔두면 좋을듯."
- "앞으로도 필요하지 않다면 V6 랩뷰 코드는 수정하지 마. 어차피 안쓰는 모듈이니까. 기존 코드는 애초에 손대지 말아야 하고, 새로 짜는 코드는 Python이고."
- "Python 기록값은 기록하고 인제스트, 푸시하도록."

## Decision
1. **The initial values for a new calibration are LOW 0, HIGH 40 and forget 10 px.** The old LabVIEW panel values
   were 0 / 25 / 20.
   - The user still picks the three values per bead, as now. They are stored in the `.cal`, so no computation
     changes (0008).
   - In code: `mtpy.calib.DEFAULT_LOW`, `DEFAULT_HIGH`, `DEFAULT_FORGET`. The register is
     [rig/core-parameters.md](../rig/core-parameters.md).
2. **Basis:** an offline sweep on fixed reference beads at 50x (203 nm / px), in
   [results/2026-10-26-refbead.md](../results/2026-10-26-refbead.md) section 3b.
   - The z noise drops from 7.25 to 4.64 nm (-36 %), and its variance by -60 %.
   - Forget removes the INNER radii (`Tracking-prep I of r.vi`). At 50x, forget 20 dropped the first bright ring
     (15-16 px).
   - Not yet checked on tethered beads.
3. **The V6 LabVIEW code is not changed further unless it is needed.** The original LabVIEW files were never to
   be touched (CLAUDE.md), and all new code is Python. So the LabVIEW panel keeps its old initial values. The new
   values live in the Python program and in this record.
