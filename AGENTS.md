# AGENTS.md

## Packaging And Release

- The version comes only from `vX.Y.Z` git tags via hatch-vcs; there is no
  version string in the source. Legacy date-based tags are excluded by the
  `git_describe_command` setting in `pyproject.toml`.
- Release: `git tag vX.Y.Z && git push origin vX.Y.Z`. The workflow builds
  sdist and wheel and publishes a GitHub Release. Semver: PATCH for fixes,
  MINOR for compatible behavior, MAJOR for breaking CLI or output changes.
