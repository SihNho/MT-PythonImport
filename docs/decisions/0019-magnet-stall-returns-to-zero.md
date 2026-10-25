# 0019 — Magnet stall: return the magnet to 0 mm at once (an emergency measure)

**Decided:** 2026-10-25 (owner, in chat)

Owner: "멈춤 감지가 생기면 당장 0으로 돌리도록 짜. (그렇지만, 보통 멈춤 감지가 생길 정도로 모터가 눌러버리면 피에조
스테이지 고장남. 그러니 이는 상시 활용하는 요소보다는 후속 문제를 막기 위해서 소화기 쓰는 느낌으로 두는 것.)"

## Decision
1. **Stall = the PI controller's own detection:** the position error exceeds the controller's programmable maximum,
   the controller switches the servo off and reports error -1024 ("position error too large, servo switched off").
   Sources: PIPython documentation (-1024); C-884 datasheet / GCS manual (stall detection by programmable position
   error, parameter 8 on the C-884). The C-863 parameter id and its current value are NOT yet read on our controller.
2. **On a stall the program returns the magnet to 0 mm (the ceiling, farthest from the sample) at once:** stop the
   running protocol / move, re-enable the servo, move to 0 mm, verify the position, log the event and show it. If the
   return cannot be done or verified, stop everything magnet-related and ask the user; never retry in a loop.
3. **The user must notice it** (owner 2026-10-25: "그리고 그 경우 에러창을 띄우고 레코드를 남겨서 유저가 인지하게
   해야함."): a stall opens an error window that stays until the user closes it (unlike the silent coercion of 0018),
   and it is written as an error record in the data file and the session log (time, position at the stall, the
   controller error, whether the return to 0 mm was verified). Until the GUI exists (phase 8) the API raises a
   distinct error and emits a `magnet_stall` event the GUI will turn into that window.
4. **It is an extinguisher, not a working feature.** A stall hard enough to trigger it has probably already damaged
   the piezo stage; the point is to stop follow-on damage. Normal safety is the position limit (0015, 0017, 0018).
5. To be checked on the rig before relying on it (needs the owner's go): read the C-863 parameter list and the
   current maximum position error; confirm that after a -1024 the servo can be re-enabled and the position is still
   valid (no new reference needed) - otherwise the return path must reference first.
