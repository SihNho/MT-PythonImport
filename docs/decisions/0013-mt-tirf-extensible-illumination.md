# 0013 — MT-TIRF: solid basics plus extensibility (smFRET, ALEX, ...)

**Decided:** 2026-10-22 (owner, chat; details still to be discussed)

Owner: "이 부분은 논의가 필요하기는 함. 사실 MT-TIRF를 통해서 단순히 smFRET을 볼 수도 있겠지만 ALEXA도 있겠고, 결국
기본적인 기능을 잘 갖춤과 동시에 확장성을 갖추는게 중요하겠음." ("ALEXA" is read as ALEX, alternating-laser
excitation; to be confirmed.)

## Decision
1. **Basic functions first, built to extend.** Fluorescence modes are not hard-coded.
2. **An "illumination sequence" module** describes which laser is on for each EMCCD frame: one laser on every frame
   (smFRET), alternating lasers (ALEX), or other patterns. The Arduino of 0005, which already divides JAI frames for the
   EMCCD, also gates the lasers per frame (0005 already foresees the OBIS modulation input); the PC never times frames.
3. **Fluorescence analysis is a plug-in** (channel registration, per-molecule traces, FRET efficiency, ALEX
   stoichiometry, ...), so a new method does not change the core program.

## Open (to discuss)
- ~~Lasers and wavelengths~~ answered: **532 nm and 637 nm** ([rig-facts.md](../rig-facts.md), MT-TIRF optical
  layout). Still open: whether each OBIS unit accepts the digital modulation needed (check `docs/manuals/coherent-obis.md`).
- How the EMCCD image is split into donor / acceptor channels and how channels are registered.
- Exposure and laser-on timing, photobleaching management, the experiment flow with fluorescence.

## Later notes (not changes to the decision)
- Requirements that build on this decision ([ui-requirements.md](../spec/ui-requirements.md)): U22 (mapping /
  channel registration), U24 (shutter and laser control, illumination sequence editor), U28 (FRET pipeline; the
  red-excited frames are a FRET correction per the owner, not ALEX), U36 (flexible fluorescence measurements).
