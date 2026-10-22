# third_party

Preserved copies of code this project reuses. `MANIFEST` lists every file with its SHA-256 and the source commit.

- `mt_labview/` — files from [MT_LabVIEW](https://github.com/SihNho/MT_LabVIEW), copied **unchanged** at the commit
  named in `MANIFEST`. MT_LabVIEW owns them: a fix is made there first and re-copied here with a new hash.
- These copies are a **record**, not part of the package. `src/` never imports from here; code that is reused is
  ported into `src/` and tested there.
- **Never run the motor files from here** (`motor_gate.py`, `motor_*.ps1`). Motion during development goes only through
  MT_LabVIEW's own gate in its own folder (`G:\Codes\rig\RULES.md` §3).
- Vendor SDKs (NI-IMAQdx, Andor SDK2, PI, ...) are not redistributed; `docs/manuals/` says where to get each one.
