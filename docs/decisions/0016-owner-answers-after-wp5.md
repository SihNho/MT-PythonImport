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
4. **`.tra` frame column counts from the first recorded frame** (owner: "첫 프레임부터 세는게 맞을듯").
5. **MATLAB version 2026** (owner: "우선 2026으로 하자") for the MATLAB reader and its check in WP6. Release letter
   (a / b) not given. MATLAB is not installed on the development PC; the reader is checked where MATLAB is available.
