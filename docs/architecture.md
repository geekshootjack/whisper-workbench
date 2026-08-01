# Architecture

One CLI, `wb`, over a two-stage workflow that is deliberately splittable
across machines.

```
audio ──▶ wb transcribe ──▶ meeting.txt ──▶ wb format ──▶ meeting.corrected.txt
          (whisper.cpp)     one line per                  meeting.md
                            speech segment
```

`wb transcribe` never invokes an LLM and never touches the network;
`wb format` never touches audio. The handoff between them is a single `.txt`
file, which is what lets transcription run on a machine with whisper.cpp
while post-processing runs somewhere with an LLM CLI.

## Modules

| Module | Responsibility |
| --- | --- |
| `cli.py` | argparse surface and the human/JSON output. |
| `assets.py` | The one place that resolves whisper-cli, model, and VAD model paths. |
| `setup_whisper.py` | `wb setup`: clone, build, download into the user data dir. |
| `transcribe.py` | ffmpeg normalization plus the whisper-cli invocation. |
| `llm.py` | Subprocess plumbing shared by both post-processing stages. |
| `correct.py` | Stage 1. Line-preserving error correction. |
| `compose.py` | Stage 2. Prose rewrite. |
| `pipeline.py` | Output path derivation and stage sequencing for `wb format`. |

## Why the two post-processing stages differ

They have opposite contracts, which is why they cannot be one pass.

**Correction** must preserve structure: N lines in, N lines out, same order.
The model is asked for a *patch* — only the lines it wants to change, keyed by
id — rather than a rewritten document. A confused or truncated response can
therefore fail to correct something, but it cannot drop, merge, or reorder
transcript lines. Chunks run concurrently because they are independent.

**Composition** must break structure: recognition segments are neither
sentences nor paragraphs. Chunks run *sequentially*, each one receiving the
tail of the previous chunk's output as read-only context, so the minutes
continue across a seam instead of restarting.

The output is meeting minutes, not a cleaned-up verbatim transcript, but it
keeps the order topics came up in — no regrouping, no headings, no summary
block. Condensing is expected; losing a topic is not, so an extreme drop in
character count is logged as a warning.

Model output also passes a deterministic guard that demotes stray markdown
headings and drops horizontal rules. LLM CLIs do not reliably obey "no
headings", and enforcing it in code is free.

The assembled document then goes through `autocorrect` once — full-width
punctuation, CJK/Latin spacing — as the last thing before it is written.
Applied to the whole document rather than per chunk, because chunk
boundaries are not sentence boundaries. Models are inconsistent about
punctuation width in Chinese prose, so it is normalized deterministically
instead of being asked for in the prompt. (The default rules apply, spacing
included; that is wanted in a document, unlike in subtitle lines.)

## Failure behavior

Neither stage is allowed to lose the transcript.

- A correction chunk that fails is retried as smaller sub-chunks, then falls
  back to the original lines.
- A compose chunk that fails on every available backend falls back to emitting
  its input lines verbatim.
- Both stages report `applied` / `partial` / `failed`, surfaced in the
  `--json` output and in the human summary.
- Backends not present on `PATH` are filtered out before any work starts, so
  requesting an uninstalled CLI does not burn a full pass over every chunk.

## Asset resolution

`assets.py` resolves in this order, and both `wb setup` and `wb transcribe`
go through it so their defaults cannot drift apart:

1. `WHISPER_CLI_PATH` / `WHISPER_MODEL_PATH` / `WHISPER_VAD_MODEL_PATH`
2. `whisper-cli` on `PATH` (covers `brew install whisper-cpp`)
3. the user data dir — `~/.local/share/whisper-workbench/` or
   `%LOCALAPPDATA%\whisper-workbench\` — which is where `wb setup` installs
4. `<repo>/vendor/whisper.cpp`, only when running from a source checkout

Installing into the user data dir rather than next to the source is what makes
`uv tool install` viable: a `__file__`-relative path would put a git clone and
multi-GB models inside `site-packages`.
