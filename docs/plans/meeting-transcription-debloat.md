# Plan: Debloat into a meeting-transcription tool

Branch: `refactor/meeting-transcription-debloat`

## Background

The project was built for subtitle production: transcribe media, emit an
aligned `.srt` + `.txt` pair, and postprocess them while preserving a strict
1:1 line correspondence. It grew a Groq cloud backend, five subcommands, three
decode profiles, an autocorrect stage, and a resumable postprocess state
machine.

The only surviving use case is different: transcribe a meeting recording,
correct the raw transcript, and rewrite it into a readable prose document that
gets handed to an agent as context. Transcription runs on a Mac;
post-processing runs on the Windows box. The two halves must be independently
runnable.

The SRT/TXT alignment invariant (`_validate_srt_txt_line_alignment`,
`sync_txt_to_srt`, `split_on_punc`) is the single biggest source of complexity,
and it is directly opposed to the new goal — rewriting speech into paragraphs
means breaking line boundaries.

## Goal

One installable CLI, `wb`, whose two working commands map onto the two
machines:

- `wb transcribe` — local whisper.cpp only, audio in, `.txt` out. No LLM, no
  network.
- `wb format` — raw `.txt` in, corrected transcript and prose document out.

Plus `wb setup` (one-time per machine) and `wb doctor` (environment check).

Agent-native means: predictable output paths derived from the input, `--json`
result output, no interactive prompts, a `doctor` command for environment
self-check, and a `--help` that reads as the whole workflow. After
`uv tool install` the agent works in the directory holding the audio, not in
this repo — there is no AGENTS.md or README for it to read, so `wb --help` is
the entire discovery surface and has to carry the two-step workflow itself.

The project must also conform to the `py-tool-standard`.

## Non-goals

- Speaker diarization. whisper.cpp emits no speaker labels and the compose
  pass will not guess at them. Worth a separate issue if it becomes a problem.
- Any cloud transcription backend.
- Subtitle editing, timing repair, or SRT/TXT alignment guarantees.
- A web UI (open issues #5–#7 cover this and are now out of scope).

## Decisions taken

| Question | Decision |
| --- | --- |
| SRT | Kept as an opt-in byproduct of `wb transcribe` (`--srt`). Nothing downstream reads or edits it; no alignment is promised. |
| Postprocess shape | One command runs correct → compose. Intermediate corrected transcript is written to disk. `--from` reruns a single stage. |
| CLI | Single `wb` entry point with subcommands. |
| Kept | whisper.cpp setup, `doctor`, `--glossary`, the four `scripts/` media utilities. |
| Setup surface | Becomes the `wb setup` subcommand; the separate `wb-setup` entry point is dropped so `wb --help` lists every capability. |
| Compose fidelity | **Amended after the first real run.** Originally near-lossless tidy-up; now meeting minutes. Condensing is expected, but topic order is preserved verbatim (no regrouping) and every argument, figure, decision and disagreement must survive. The corrected transcript stays on disk as the full record. |
| Document head | None. Body prose only, no summary block, no heading hierarchy. |

## Current code findings

- `main.py` (495 lines) holds the whole CLI: `transcribe`, `postprocess`,
  `convert`, `batch`, `doctor`.
- `src/` is used as the package name itself (`from src.whisper_utils import …`),
  which is not a valid installable layout.
- `run_whisper_command` calls `postprocess_transcription_outputs` internally —
  transcription and post-processing are coupled at the lowest level. This is
  what has to be cut for the Mac/Windows split.
- The three decode profiles are near-identical; `legacy` and `balanced` are
  byte-for-byte the same dict.
- `_selected_postprocess_steps` + resume/from-step/to-step is a state machine
  serving four steps, three of which exist only for SRT alignment.
- `src/llm_correct.py` is the one piece worth keeping mostly intact: chunked,
  ID-patch based, retries, chunk degradation, backend fallback. Its correction
  contract (line count in == line count out) is exactly right for stage 1 and
  exactly wrong for stage 2.
- `pyproject.toml` pins `version = "0.1.0"` and exposes an entry point named
  `main`, which would land a binary called `main` on `PATH`.
- Only runtime dependency is `autocorrect-py`, used solely by the autocorrect
  stage being removed. Removing it leaves zero runtime dependencies.
- **Asset paths break under `uv tool install`.** `setup_whisper_cpp.py:206`
  derives `project_root` from `Path(__file__).parent.parent` and clones,
  builds, and downloads models into `<project_root>/vendor/whisper.cpp`.
  Installed as a tool, `__file__` lives in the uv tool venv, so that resolves
  to `site-packages/vendor/whisper.cpp` — a git clone and multi-GB models
  inside site-packages, wiped by the next `uv tool upgrade`.
  `whisper_utils.get_whisper_cli_path` and `get_model_path` use the same
  relative base and fail the same way.
- `setup_whisper_cpp.py` advertises `WHISPER_CPP_DIR` as an environment
  override in its completion output, but nothing in the codebase reads that
  variable. It is dead text.
- **Default model mismatch.** `setup_whisper_cpp.py` defaults `--model` to
  `large-v3`, while `whisper_utils.get_model_path` looks for
  `ggml-large-v3-turbo.bin`. A default setup followed by a default transcribe
  cannot find its model; it only works via `-m turbo` or
  `WHISPER_MODEL_PATH`. Both sides must read one shared constant.

## Proposed implementation

### Layout

```
src/whisper_workbench/
    __init__.py        # __version__ from importlib.metadata
    cli.py             # argparse: setup | transcribe | format | doctor
    assets.py          # single resolver for whisper-cli / model / VAD paths
    transcribe.py      # whisper.cpp invocation (from whisper_utils)
    llm.py             # LLM CLI subprocess plumbing (from llm_correct)
    correct.py         # stage 1: chunked ID-patch correction
    compose.py         # stage 2: sequential chunked prose rewrite (new)
    setup_whisper.py   # wb setup (moved from scripts/)
scripts/               # unpackaged dev utilities, unchanged
```

Deleted outright: `main.py`, `src/transcription_backends.py`,
`src/postprocess.py`, `src/srt_utils.py`, `src/text_normalization.py`.

### Asset resolution

`assets.py` becomes the one place that knows where whisper.cpp lives, shared
by `setup`, `transcribe`, and `doctor`. Resolution order:

1. `WHISPER_CLI_PATH` / `WHISPER_MODEL_PATH` / `WHISPER_VAD_MODEL_PATH`
2. `whisper-cli` on `PATH` (covers `brew install whisper-cpp` on the Mac,
   which makes `wb setup` unnecessary there)
3. the user data dir — `~/.local/share/whisper-workbench/` on POSIX,
   `%LOCALAPPDATA%\whisper-workbench\` on Windows
4. `<repo>/vendor/whisper.cpp`, for running out of a git checkout only

`wb setup` installs into (3). The dead `WHISPER_CPP_DIR` mention is removed.
The default model name is a single module-level constant consumed by both
setup and transcribe, fixing the current mismatch.

### `wb setup`

```
wb setup [--model large-v3-turbo|large-v3] [--update]
```

Reduced from four flags to two:

- `--model` drops `medium`, `medium.en`, `small`, `small.en`. The `.en`
  variants cannot transcribe Chinese at all, and the smaller multilingual
  models are not good enough for multi-speaker meeting audio. Default is
  `large-v3-turbo`.
- `--vad-model` is removed; `silero-v5.1.2` is pinned.
- `--skip-vad` is removed; the VAD model is a few MB and
  `wb transcribe --no-vad` already covers turning it off at use time.
- `--skip-update` is inverted into `--update`. Re-running `wb setup` to check
  an environment must not silently pull upstream whisper.cpp and rebuild;
  the bare command is now idempotent and returns in seconds.

### `wb transcribe`

```
wb transcribe AUDIO [AUDIO ...] [-o DIR] [-l LANG] [-m VARIANT | --model-path P]
                    [--prompt-file F] [--srt] [--no-vad] [--json]
```

- `-o` defaults to the input file's own directory.
- `-l` defaults to `zh` (was `en`).
- Output is `<stem>.txt`; `<stem>.srt` only with `--srt`. The `_{lang}` suffix
  in output names is dropped — the path is now a pure function of the input.
- Non-WAV inputs are converted to a temp 16 kHz mono WAV via ffmpeg, unchanged.
- Never invokes an LLM and never touches the network.
- The three decode profiles collapse into one fixed decode config; the
  `--decode-profile` flag is removed. `--no-vad` stays.

### `wb format`

```
wb format TXT [-o OUT.md] [--glossary FILE] [--backend gemini|claude|codex]
              [--model M] [--timeout SEC] [--from correct|compose]
              [--chunk-lines N] [--stdout] [--json]
```

Stage 1 `correct` — reuses the existing chunked ID-patch machinery verbatim.
Input `meeting.txt`, output `meeting.corrected.txt`. Line count is preserved.

Stage 2 `compose` — new. Input `meeting.corrected.txt`, output `meeting.md`.

- Chunks of `--chunk-lines` (default 300) corrected lines.
- Processed **sequentially**, not in parallel: each request carries the tail
  (~400 chars) of the previous chunk's *output* as read-only preceding context,
  so paragraphs continue across seams instead of restarting.
- Prompt contract: keep every substantive statement; drop fillers and verbal
  tics; merge fragmented recognition lines into complete sentences; repair
  punctuation; break paragraphs on topic shift with a blank line; emit no
  headings, no bullet lists unless the speaker was literally enumerating, no
  summary, no commentary.
- Model output is passed through a deterministic guard that demotes any stray
  `^#{1,6}\s` heading line back to a plain paragraph line — LLM CLIs are
  unreliable about the "no headings" instruction and this costs nothing.
- A chunk that fails after retry falls back to emitting its input lines joined
  as-is, logs a warning, and marks the run `partial`.

`--from compose` skips stage 1 and consumes an existing `.corrected.txt`.

### `wb doctor`

Reports ffmpeg, whisper-cli, default model, VAD model, and which of the
gemini/claude/codex CLIs are on `PATH`. `--json` for agent consumption.

### py-tool-standard alignment

- `pyproject.toml`: `dynamic = ["version"]`, hatchling + hatch-vcs,
  `requires-python = ">=3.10"`, `packages = ["src/whisper_workbench"]`, a
  single `wb` script entry. Drop the `autocorrect-py` dependency.
- Add `.github/workflows/ci.yml` (3 OS × Python 3.10/3.13) and
  `release.yml` (tag-triggered GitHub Release) as specified.
- README documents `uv tool install git+https://github.com/geekshootjack/whisper-workbench`
  as the install path; `git clone` + `uv sync` becomes the dev-only route.
- AGENTS.md records the commit style, release procedure, and the cross-OS test
  rules (no hardcoded path separators, no reliance on FS enumeration order).

## Risks and tradeoffs

- **Compose is slow.** A two-hour meeting is roughly 3000 lines ≈ 10 sequential
  calls. Parallelising would break paragraph continuity across seams, so the
  cost is accepted; progress is logged per chunk.
- **Near-lossless is a prompt-level promise.** Nothing mechanically verifies
  that the model kept every claim. Mitigation: the corrected transcript stays
  on disk, so the source of truth is always one file away, and a large
  length drop is worth logging as a warning.
- **Removing Groq and the SRT pipeline is a hard break** of the current CLI.
  Acceptable — the tool has one user and the old behavior stays in git history.
- **Output path change** (`_{lang}` suffix dropped, `-o` now optional) will
  break any existing shell muscle memory. Documented in the README.

## Verification plan

```bash
uv run pytest
uv run wb --help
uv run wb setup --help
uv run wb transcribe --help
uv run wb format --help
uv run wb doctor
uv build
```

Plus a real run of `wb format` against an existing transcript in
`data/interview/output/` and `data/bailu-pgm/output/`, checking that the
document has no heading hierarchy and that no section of the meeting vanished.

## Follow-ups (not in this change)

- File an issue for speaker attribution if unlabeled prose turns out to be
  insufficient in practice.
