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
sentences nor paragraphs.

It also runs as a *single call* by default. Minutes need the whole arc of a
topic — the conclusion usually lands far after the topic opens — so splitting
risks writing one topic up twice, on either side of the seam. The threshold is
measured in characters, not lines: recognition segments run 8-16 characters, so
a line budget says almost nothing about how much meeting a chunk holds. A real
938-line transcript is under 15k characters, and even a three-hour meeting
lands around 40k, so the 60k default means splitting essentially never happens.
When it does, chunks run sequentially, each receiving the tail of the previous
chunk's output as read-only context, and a warning is logged.

The output is meeting minutes, not a cleaned-up verbatim transcript, but it
keeps the order topics came up in — no regrouping, no headings, no summary
block. Condensing is expected; losing a topic is not, so an extreme drop in
character count is logged as a warning.

Model output also passes a deterministic guard that demotes stray markdown
headings and drops horizontal rules. LLM CLIs do not reliably obey "no
headings", and enforcing it in code is free.

The assembled document then goes through `autocorrect` once — full-width
punctuation, CJK/Latin spacing — plus a quote pass, as the last thing before
it is written. autocorrect deliberately leaves quotes alone because it cannot
tell an opening quote from a closing one, an apostrophe, or an inch mark; the
quote pass sidesteps that by only rewriting *balanced pairs on a line
containing Chinese*, where the direction is unambiguous. An odd quote out is
left alone rather than guessed at.
Applied to the whole document rather than per chunk, because chunk
boundaries are not sentence boundaries. Models are inconsistent about
punctuation width in Chinese prose, so it is normalized deterministically
instead of being asked for in the prompt. (The default rules apply, spacing
included; that is wanted in a document, unlike in subtitle lines.)

Two things autocorrect will not do are handled around it. It leaves quotes
alone entirely, so balanced straight pairs on a line containing Chinese are
curled first. And it only widens punctuation preceded by a *word* character —
after a quote or bracket it declines on purpose, so that code like ``foo(),``
survives — which leaves 看看”, half-width; that case is widened afterwards.
Half-width parentheses are deliberately left as they are.

## Segmentation

whisper.cpp's VAD defaults are tuned for subtitles, where a short cue is a
feature. For a transcript they are actively harmful: the 100 ms silence
threshold splits on every breath and hesitation, so the raw output is full of
lines like `但是` and `因为这个太`.

Composition ignores line structure entirely, but correction does not — it
works line by line, and a two-character line gives the model no context to
judge whether anything is wrong. So the VAD is retuned to ride over hesitation
pauses (`--vad-min-silence-duration-ms 700`), cap runaway segments
(`--vad-max-speech-duration-s 30`, matching whisper's own window), and stop
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
go through it so their defaults cannot drift apart:

1. `WHISPER_CLI_PATH` / `WHISPER_MODEL_PATH` / `WHISPER_VAD_MODEL_PATH`
2. `whisper-cli` on `PATH` (covers `brew install whisper-cpp`)
3. the user data dir — `~/.local/share/whisper-workbench/` or
   `%LOCALAPPDATA%\whisper-workbench\` — which is where `wb setup` installs
4. `<repo>/vendor/whisper.cpp`, only when running from a source checkout

Installing into the user data dir rather than next to the source is what makes
`uv tool install` viable: a `__file__`-relative path would put a git clone and
multi-GB models inside `site-packages`.
