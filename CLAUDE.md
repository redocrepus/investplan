# Agent Instructions

Read readme.md and requirements.md before every response.

## Documentation Maintenance

Every code change must include updates to all relevant documentation:

- **README.md** — Keep install, dev-run, test, and build instructions accurate
- **Requirements.md** — Keep feature/input/output specifications in sync with implementation
- **requirements.txt** — Keep dependency list accurate with pinned versions
- **plan.md** — Update checklists and architecture when implementation changes
- **GUI tooltips** — Keep all input field tooltips accurate and consistent with documentation

No change is complete until documentation is updated.

## Bug Detection Policy

Never hide bugs with silent fallbacks. When an internal invariant is violated (e.g., lots exhausted, invalid price, inconsistent state), report the bug with enough context for developers to diagnose and fix it — write a structured error report (JSON with relevant state snapshot and config) and halt execution. Users must be able to provide developers with the data needed to reproduce and patch the issue.

## Git Commit Policy

When committing multiple changes, divide into separate commits **by feature/fix item**, not by area (implementation/tests/docs). Each commit should contain the full vertical slice for one logical change: code + tests + docs together. This keeps each commit self-contained and bisectable.
