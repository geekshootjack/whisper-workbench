English | [中文](architecture.zh.md)

# Architecture

One CLI, `wb`, over a two-stage workflow that is deliberately splittable
across machines:

```
audio ──▶ wb transcribe ──▶ meeting.txt ──▶ wb format ──▶ meeting.corrected.txt
          (whisper.cpp)     one line per                  meeting.md
                            speech segment
```

`wb transcribe` never invokes an LLM and never touches the network; `wb
format` never touches audio. The handoff is a single `.txt` file.

## Modules

| Module | Responsibility |
| --- | --- |
| `cli.py` | argparse surface and the human/JSON output. |
| `assets.py` | The one place that resolves whisper-cli, model, and VAD model paths. |
| `setup_whisper.py` | `wb setup`: download models into the user data dir (huggingface.co with hf-mirror.com fallback, resumable). |
| `transcribe.py` | ffmpeg normalization plus the whisper-cli invocation. |
| `llm.py` | Subprocess plumbing shared by both post-processing stages. |
| `correct.py` | Stage 1. Line-preserving error correction. |
| `compose.py` | Stage 2. Prose rewrite. |
| `pipeline.py` | Output path derivation and stage sequencing for `wb format`. |

## Correction and composition

**Correction** preserves structure: N lines in, N lines out, same order. The
model returns a *patch* — only the lines it wants to change, keyed by id — so
a confused or truncated response can miss a correction but cannot drop, merge,
or reorder lines. Independent chunks run concurrently.

**Composition** breaks structure: recognition segments are neither sentences
nor paragraphs. It runs as a single call by default because a topic's
conclusion usually lands far after its opening, and splitting risks writing
one topic up twice. The budget is measured in characters — segments run 8-16
characters, so a line count says nothing about how much meeting a chunk holds
— and the 60k default means splitting essentially never happens. When it does,
chunks run sequentially, each receiving the previous chunk's output tail as
read-only context, with a warning logged.

The output keeps the order topics came up in — no regrouping, no headings, no
summary block. Condensing is expected; losing a topic is not, so an extreme
drop in character count is logged as a warning.

Deterministic guards run around the model output:

- Stray markdown headings are demoted and horizontal rules dropped; LLM CLIs
  do not reliably obey "no headings", and enforcing it in code is free.
- The document is normalized once over the whole text, as the last step before
  it is written — chunk boundaries are not sentence boundaries. `autocorrect`
  does the bulk of it; models are inconsistent about punctuation width in
  Chinese prose, so this is enforced in code rather than asked for in the
  prompt.

Two things autocorrect will not do are handled around it:

- **Quote direction.** autocorrect leaves quotes alone entirely. The quote
  pass rewrites only *balanced pairs on a line containing Chinese*, where the
  direction is unambiguous; an odd quote out is left alone, and single quotes
  are only touched when they wrap Chinese, so English apostrophes survive.
- **Punctuation after a quote.** autocorrect only widens punctuation preceded
  by a *word* character, so `看看”,` is still half-width after autocorrect has
  run; a follow-up pass widens it and drops the space autocorrect inserted
  before the following CJK, which is wrong once the punctuation is full-width.

Half-width parentheses are left as they are; autocorrect spaces rather than
widens them by design.

## Segmentation

whisper.cpp VAD defaults are tuned for subtitles, where a short cue is a
feature; for a transcript they split on every breath and hesitation, and
correction — which works line by line — gets two-character lines that give the
model no context to judge. The VAD is retuned: ride over hesitation pauses
(`--vad-min-silence-duration-ms 700`), cap runaway segments
(`--vad-max-speech-duration-s 30`, matching whisper's own window), stop
clipping onsets (`--vad-speech-pad-ms 200`).

`--split-on-word` was dropped: it only takes effect together with `--max-len`,
which is left at 0, so it had been a no-op since the subtitle days.

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
go through it so their defaults cannot drift:

1. `WHISPER_CLI_PATH` / `WHISPER_MODEL_PATH` / `WHISPER_VAD_MODEL_PATH`
2. `whisper-cli` on `PATH` (covers `brew install whisper-cpp` and the official
   release zips)
3. the user data dir — `~/.local/share/whisper-workbench/` or
   `%LOCALAPPDATA%\whisper-workbench\` — where `wb setup` downloads the models
   to `<dir>/models`; `<dir>/whisper.cpp` from older setups still counts
4. `<repo>/vendor/whisper.cpp`, only when running from a source checkout

Assets live in the user data dir rather than next to the source so `uv tool
install` stays viable: a `__file__`-relative path would put multi-GB models
inside `site-packages`.
