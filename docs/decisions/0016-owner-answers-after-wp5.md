# 0016 — Owner answers after WP5: magnet speed, `zero`, protocol end, `.tra` frame origin, MATLAB version

**Decided:** 2026-10-25 (owner, in chat, answering the open questions listed after the WP5 reviews)

## Decision
1. **Magnet speed maximum 15 mm/s** (owner: "15로 하자(15 mm/s)"). It goes into the rig safety profile as a new
   profile version through the admin write path (0015 item 5), so it is logged and versioned. Until now profile v1 had
   no magnet speed maximum and refused every magnet move.
2. **`zero` sends the magnet to 0 mm** (owner: "이거는 0으로 보내는게 맞는듯"). When the tracking zero is set (U12)
   is still open.
3. **Protocol end statement** (owner: "프로토콜에 종료 기능을 추가해야 할듯. 즉, 프로토콜 내부에 종료가 선언되지
   않았으면 그냥 쭉 찍도록"). The grammar gets an explicit end statement. If a protocol declares it, recording is
   switched off there. If it does not, recording simply continues after the protocol ends. A stop by the user or an
   e-stop does not switch recording off either (as in 0007).
   *Interpretation recorded by the AI, to confirm:* the end statement switches recording off; it does not stop
   acquisition (live display continues).
   **Confirmed 2026-10-25** (owner: "프로토콜이 끝나도 종료 아니면 영상 계속 받아야지. 이어서 다른 프로토콜 실행할 수도
   있으니까."): acquisition keeps running after a protocol, with or without the end statement.
   **Changed 2026-10-25** (owner: "프로터콜 종료해도 녹화는 계속. 녹화를 껐다 켰다 할 거는 형광임"): the MT recording
   is NOT switched off by the end statement either; `end protocol` only ends the protocol. Switching recording off and
   on during an experiment concerns the fluorescence (EMCCD) channel, not the MT camera. *AI reading, to confirm:* the
   MT recording stops only by the user (or at program stop).
4. **`.tra` frame column counts from the first recorded frame** (owner: "첫 프레임부터 세는게 맞을듯").
   **Refined 2026-10-25** (owner: "동일한 파일이라면 프레임 숫자는 계속 이어져야함. 아니면 아예 새 파일 저장하여 프레임을
   갱신하는 방법도 있겠지만, 그 경우 cal ~ tra 까지 이어지는 이름 규칙이 깨질까 두려움"): 0 is the first recorded frame
   of the FILE; within one file the numbers continue across recording off / on and across segments (no restart at 0,
   no split into a new `.tra` series per segment), so the `.cal` -> `.tra` naming stays intact.
5. **MATLAB version 2026** (owner: "우선 2026으로 하자") for the MATLAB reader and its check in WP6. Release letter
   (a / b) not given. MATLAB is not installed on the development PC; the reader is checked where MATLAB is available.
