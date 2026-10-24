# 0015 — Extension architecture: a fixed core, extension levels, one public function layer

**Decided:** 2026-10-24 (owner: "동의함", on the proposal recorded in [ui-requirements.md](../spec/ui-requirements.md) U37)

Owner's questions that led to it: "결국 어느 시점에는 지금은 생각하지 못한 방식으로 실험 구조 수정이 필요할 수 있겠는데, 이를
어떻게 대처할지가 의문" and "이를 위해서는 모듈화 함수가 잘 준비되어 있어야겠네."

## Decision
1. **A fixed core** that experiments never need to change: complete raw data with metadata (MT, EMCCD, events,
   settings; 0006); one time base (frame / buffer numbers, Arduino sync; 0005); device interfaces; the safety layer.
2. **Extension levels, lowest first:** 0 settings and presets; 1 scripts in the defined grammar (protocols,
   illumination sequences, analysis recipes); 2 Python plug-ins at defined extension points (detectors, observables
   and event rules, protocol step types, devices); 3 Python experiment scripts against the public API; 4 core changes
   through the normal development process. A new need is solved at the lowest level that works.
3. **One public function layer** used by the GUI, scripts, plug-ins and the AI gateway (0014) alike: one job per
   function, units in names / arguments, safety enforced inside the functions, a docstring, example, test and
   simulator support for each, a versioned API with a deprecation period. It is specified in
   [docs/design/api.md](../design/api.md) before the phase-5 device code.
4. **Reproducibility:** the content and version of every script, plug-in and recipe used is stored with the data.
5. **Safety parameters are adjustable, but protected** (owner: "안전 계층 파라미터도 나중에 리그 해체 이후 재조립한다면
   바뀔 수 있음. 이 또한 어느정도는 조절 가능 필요함."). They live in a versioned **rig safety profile** (magnet travel
   and force limits, ASI window, rotor range and speed, laser power, ...), not in code:
   - changed only from a dedicated settings screen, by a person with the rig-admin role, with a reason;
   - a change starts a guided **re-commissioning check** (move to the new limits slowly, read back positions, confirm
     on the rig) before the profile becomes active;
   - every profile version is kept (who, when, why) and the active one is written into each data file;
   - scripts, plug-ins and the AI gateway can read the profile but never change it.

## Consequences
- The plug-in and scripting APIs are documented with examples so lab members can extend the program without AI after
  the project ends (0001).
- Phase 5 (device layer) builds the device services on this function layer and on the safety profile.
