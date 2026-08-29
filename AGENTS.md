# AGENTS.md

## What This Project Is

One CLI, `wb`, that turns a meeting recording into a corrected, readable
document for use as agent context. Two stages, split across machines:
`wb transcribe` (whisper.cpp, offline) and `wb format` (LLM correction, then
prose rewrite). See `docs/architecture.md`.

Scope discipline matters here. This project was previously a subtitle toolkit
and was deliberately cut back. Do not reintroduce cloud transcription
backends, SRT/TXT alignment pipelines, or subtitle editing features.

## Source Of Truth

This repository uses GitHub Issues and the GitHub Project as the only
task-tracking system.

- GitHub Issues define what we are building or fixing.
- Labels and milestones define priority and release scope.
- The GitHub Project is the planning board.
- Local markdown files must not become a second backlog.

Do not recreate `.codex/TASKS.md`, `.codex/TODO.md`, `.codex/ISSUES.md`, or
any local todo board.

Issue titles and bodies are written in Chinese. Commit messages stay English.

## Read Order

1. `AGENTS.md`
2. the active GitHub issue or pull request
3. `docs/architecture.md`
4. `docs/plans/*.md` when a reviewed implementation plan exists

## Agentic Dev Process

### Default Loop

1. Read the target GitHub issue and confirm the acceptance criteria.
2. Inspect the relevant code before proposing a solution.
3. Decide whether the task is small enough to implement directly or needs a
   reviewed plan first.
4. For non-trivial work, write a plan doc under `docs/plans/`.
5. Review and refine that plan before implementation.
6. Implement according to the approved plan.
7. Run verification appropriate to the scope.
8. Update user-facing docs when behavior, setup, or workflow changes.
9. Report the result and verification evidence back on GitHub, then close the
   issue when done.

### When To Write A Plan First

Write a plan doc for work that:

- spans multiple files or modules
- changes architecture
- changes CLI or operator workflow
- carries meaningful regression risk
- benefits from explicit scope review before coding

Small, obvious fixes do not need a separate plan doc.

### Plan Review Rules

Plan docs live under `docs/plans/` and are for review, not tracking.

A good plan doc should include background, goal, non-goals, current code
findings, proposed implementation, risks and tradeoffs, verification plan, and
open questions.

If implementation reveals the plan is wrong, update the plan before continuing
with major changes.

## Documentation Rules

- User-facing text is Chinese: `README.md` and every CLI help string.
  Contributor-facing text is English: `AGENTS.md`, `docs/`, code comments,
  docstrings, commit messages.
- Never hard-wrap Chinese prose. One paragraph is one line.
- `README.md` stays short. Architecture notes belong in `docs/`.
- There is no separate CLI reference document. `wb --help` is the CLI
  reference, and it is load-bearing: once installed with `uv tool install`, an
  agent works in the directory holding the audio, not in this repo, so the
  top-level help must teach the whole two-step workflow on its own. Keep it
  current.
- `docs/plans/` is only for reviewable plans tied to active work.
- Do not mirror issue state inside docs.
- `CLAUDE.md` points at `AGENTS.md` so tool-specific entry points stay
  aligned.

## Packaging And Release

This project follows the shared Python CLI tool standard.

- Managed with `uv`. `uv.lock` is committed.
- The version comes only from git tags via hatch-vcs. There is no version
  string in the source. Legacy date-based tags are excluded by the
  `git_describe_command` setting in `pyproject.toml`; only `vX.Y.Z` counts.
- Distribution is `uv tool install` from the git remote. No PyPI.
- Release: `git tag vX.Y.Z && git push origin vX.Y.Z`. The workflow builds
  sdist and wheel and publishes a GitHub Release. Semver: PATCH for fixes and
  cleanup, MINOR for backwards-compatible behavior, MAJOR for breaking CLI or
  output changes.

## Commits

Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`,
`refactor:`). Small, reversible commits; commit after each verified batch
without being asked. Never push unless asked.

## Verification Baseline

After meaningful code changes:

```sh
uv run ruff check .
uv run pytest
uv run wb --help
uv run wb doctor
```

CI runs the same on Ubuntu, Windows, and macOS across Python 3.10 and 3.13.

### Cross-OS Test Rules

- Never hardcode path separators in test expectations. Build them with `Path`
  so they hold on both Windows and POSIX.
- Never rely on filesystem enumeration order (`os.walk`, `scandir`):
  alphabetical on NTFS, arbitrary on ext4. If order matters, sort in the
  product code so behavior is deterministic everywhere.
- Do not poke at argparse private attributes in tests; they differ across
  Python versions. Assert on parsed results and on `SystemExit` instead.

### What Cannot Be Verified Locally

`wb transcribe` needs whisper.cpp, and `wb format` spends real LLM calls.
Neither runs in CI. Changes to those paths need a manual run on a machine that
has the prerequisites, and the result should be reported on the issue.

## Decision Rules

- Prefer simple, contained patches.
- Keep implementation and docs aligned in the same change.
- Every new CLI flag needs a reason it cannot be a sensible default. This tool
  was debloated on purpose.
