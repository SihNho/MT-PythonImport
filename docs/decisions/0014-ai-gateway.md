# 0014 — A defined AI gateway: AI works through one restricted interface, never by changing code

**Decided:** 2026-10-22 (owner, chat; tiers proposed in the same discussion)

Owner: "AI 접근성과 관련하여서 창구를 특정하고 오픈하여서 코드를 뜯어고치지 않고 AI를 제한된 환경에서 사용하는 환경을
준비하면 좋겠음. 예를 들면, 실험 프로토콜을 짤 때나 혹은 비드 선별 프로토콜을 활용한다거나, AI에게 자동화를 맡기고 가동한다거나"

## Decision
1. **One gateway (API) for any AI model** (a local model such as Laya, or a hosted one). AI has no direct device access
   and cannot change the application's code.
2. **Permission tiers**, chosen by the user:
   1. *read* - state, data, bead tables;
   2. *propose* - write experiment or screening protocols **as files** in the normal protocol format (0012); they pass
      the same validation and safety checks as a person's, and are used only after the user approves;
   3. *run approved* - execute an approved protocol and read its results;
   4. *autonomous* (later) - decide and act within a declared safety envelope and time limit.
3. **Every AI action is logged**, and the user can stop it from the UI at any time.

## Consequences
- Consistent with 0001 item 5 (AI only as an add-on on top of the normal interfaces, same safety layer). The
  application works fully without the gateway being used.
- Uses foreseen in the chat: drafting experiment protocols, applying screening protocols, running automation, the
  troubleshooting guide (U9).
