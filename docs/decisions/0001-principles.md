# 0001 — Project principles

**Decided:** 2026-10-21

1. **Safeguards exist to stop AI tools from breaking the program or the machine, not to restrict the user.** During development AI assistants write and test code on the rig PC, so locks, gates and hooks exist for that period. None of them may limit what a person does.
2. **After the project ends, no AI runs.** The final software must work and be maintainable by people alone. It must not depend on AI tools, chat sessions, development locks or development gates. Safety and recovery live in the application's own code and user interface.
3. **Experiments carry no restriction.** During experiments several lab members use the rig without any AI involvement. Everything motor-related must then be exactly as it was before the project. That is why development jobs set controller limits at their start and release them at their end, verified by reading them back.
4. **Two worlds.**
   - The *development world* follows locks, gates and limits. It covers AI sessions, automated runs, tests, and the application while it is still being developed.
   - The *experiment world* has no such restrictions. It covers people running experiments with LabVIEW today and with this application once it is released.
   - The application never contains development-lock code. Keeping automation away from a running experiment is the automation's job.
5. **AI may be added later only as an add-on.** Future automation (for example a decision model or an LLM helping with bead selection) sits on top of the application's normal interfaces and passes through the same safety layer. The user can always stop it from the UI. It is never the main path.

## Consequences
- The development-period safeguards are removed when the project ends, and the rig must be shown to be in its original state.
- Documentation is written for people. AI working notes are kept separate and archived at the end.
