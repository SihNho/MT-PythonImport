# Contributing

## Working together
- Work on a branch and open a pull request into `main`. Keep one topic per PR.
- Every PR says **what changed, why, and how it was checked**: tests run, files compared, rig tests done.
- Write documents in **English**. A Korean version may be added next to it (`name.ko.md`).
- Keep documents for people (`docs/`) apart from notes for AI assistants (`CLAUDE.md`, later `dev/`). Write each fact in one place only and link to it from elsewhere.

## Results must not change silently
- The tracking output and the `.tra` / `.cal` files must match the LabVIEW program unless a change has been decided and recorded in `docs/decisions/`.
- Acceptance is numeric: same input frames, same XYZ within the stated tolerance. "It runs" is not acceptance.

## Hardware safety
The rig is shared with real experiments run by several lab members.

- **Never run code against the rig while an experiment is running.**
- Device code defaults to the **simulator**. Real hardware needs an explicit setting.
- Every motor or stage command goes through the safety layer (travel limits, envelope). Never write directly to a motor port.
- After any rig test, return the rig to its initial condition: devices closed, controller limits as they were before.

## Tests (planned tiers)
1. unit tests (pure computation)
2. replay of recorded frames vs. LabVIEW output
3. simulator runs of the whole pipeline
4. camera only (rig)
5. motion (rig, through the safety layer)
6. experimental A/B validation against LabVIEW

Tiers 1–3 must pass on every PR. Tiers 4–6 are run deliberately, by a person, when the rig is free.

## Third-party material
- Do not commit vendor SDKs, installers, DLLs or manuals unless their license allows redistribution. List them in an install manifest with a download location instead.
- Do not commit experiment data.
- Record every borrowed algorithm or code idea with its source in `docs/decisions/` or the relevant document.
