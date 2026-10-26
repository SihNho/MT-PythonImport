# 0021 — Camera through NI-IMAQdx first, SDK swappable later; rotor speed, focus and laser limits; MT before MT-TIRF

**Decided:** 2026-10-26 (owner, in chat)

Owner:
- "로터 속도는 150 리밋으로 잡자. focus 범위는 기계 리밋 그대로 해도 문제 없고 레이저 파워는 나중에."
- "우선은 MT 구현 먼저 --> MT-TIRF."
- "우선은 NI 드라이버 사용을 하고 나중에 드라이버 교체할 수 있도록 준비하면 되겠음."
- "기본적으로 다 모듈형식 코딩 하는걸테니 아마 후반에 바꿔도 큰 문제 없으리라 생각함."

## Decision
1. **The JAI camera is driven through the NI-IMAQdx C API** (`niimaqdx.dll` via ctypes), the path LabVIEW uses and
   already exercised from Python in V6 ([manuals/camera-jai-imaqdx.md](../manuals/camera-jai-imaqdx.md)). No Windows
   driver is changed, so LabVIEW keeps working.
2. **The SDK stays swappable.** The real camera is one implementation of the device interface
   (`src/mtpy/devices/base.py`) next to the simulator; nothing above it may depend on IMAQdx. JAI's own eBUS SDK
   (installed at `C:\Program Files\JAI\eBUS SDK`, C++ / .NET; a Python API is a separate JAI download) or a GenTL path
   can replace it later. A switch probably needs JAI's own USB3 Vision driver instead of NI's, which may stop LabVIEW
   from opening the camera - unverified, and a system change only the owner makes.
3. **Rotor speed limit 150**, in the unit of the LabVIEW panel `Rot Speed` (the controller `SPD` argument; LabVIEW
   default 100). With the speed multiplier 10 (not yet read from the controller) that is 1500 pps, about 3 turns/s.
   During development the V6 gate still caps `SPD` at 100; raising it is a V6 change.
4. **Focus window = the mechanical (controller) limits**; no narrower window.
5. **Laser powers: later** (with MT-TIRF).
6. **Order: MT first, then MT-TIRF** (plan phases 6-9 before 10a).

## Follows
- Rig safety profile: `rotor_speed_turns_s` and `focus_z_um` get these values in a new version through the admin path
  (0015 item 5); `verified` only after a rig read-back (speed multiplier; focus controller limits).
- Register [rig/core-parameters.md](../rig/core-parameters.md): add the rotor speed limit and the focus limits.
