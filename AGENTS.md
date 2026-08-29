# AGENTS.md

## Source Of Truth

Task tracking lives only in GitHub Issues, labels and milestones, and the
GitHub Project.

Issue titles and bodies are Chinese. Commit messages are English.

## Workflow

1. Read the target GitHub issue and confirm the acceptance criteria.
2. Inspect the relevant code before proposing a solution.
3. Non-trivial work (multiple modules, architecture or CLI changes, regression
   risk) gets a plan doc under `docs/plans/` first: background, goal,
   non-goals, findings, proposal, risks, verification. Small fixes just get
   done.
4. Verify, update user-facing docs when behavior changes, report the evidence
   on the issue, close it.

## Documentation Rules

- User-facing text is Chinese: `README.md` and every CLI help string.
  Contributor-facing text is English: `AGENTS.md`, `docs/`, code comments,
  docstrings, commit messages.
- One paragraph of Chinese prose is one line.
- `README.md` stays short. Architecture notes live in `docs/`.
- `wb --help` is the CLI reference; keep it teaching the full workflow on
  its own.
- `docs/plans/` holds review-only plan docs for active work.

## Packaging And Release

- Managed with `uv`; `uv.lock` is committed.
- The version comes only from `vX.Y.Z` git tags via hatch-vcs; there is no
  version string in the source. Legacy date-based tags are excluded by the
  `git_describe_command` setting in `pyproject.toml`.
- Distribution is `uv tool install` from the git remote. No PyPI.
- Release: `git tag vX.Y.Z && git push origin vX.Y.Z`. The workflow builds
  sdist and wheel and publishes a GitHub Release. Semver: PATCH for fixes,
  MINOR for compatible behavior, MAJOR for breaking CLI or output changes.

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

`wb transcribe` needs whisper.cpp and `wb format` spends real LLM calls; CI
covers neither. Verify those paths by hand on a machine that has the
prerequisites and report the result on the issue.

Cross-OS test rules:

- Build path expectations with `Path`.
- When order matters, sort in product code.
- Assert on parsed results and `SystemExit`, not argparse internals.

## Decision Rules

- Prefer simple, contained patches.
- Keep implementation and docs aligned in the same change.
- Every new CLI flag needs a reason it cannot be a sensible default.
- Scope is `wb transcribe` plus `wb format`; cloud transcription backends,
  SRT alignment, and subtitle editing are out of scope.
