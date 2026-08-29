English | [中文](README.md)

# whisper-workbench

Turn a meeting recording into a corrected, sectioned document to feed to an
agent as context.

Two steps, and the two steps can run on different machines:

```
wb transcribe meeting.m4a     ->  meeting.txt              local whisper.cpp, offline
wb format meeting.txt         ->  meeting.corrected.txt    an LLM fixes recognition errors line by line
                              meeting.md               an LLM rewrites it into sectioned prose
```

The only file passed between the steps is `meeting.txt`.

The final `meeting.md` is sectioned in the order topics come up in the
recording — no heading hierarchy, no summary section — keeping the arguments,
numbers, decisions, and disagreements; `meeting.corrected.txt` stays on disk.

Before the file is written, the whole document passes through
[autocorrect](https://github.com/huacnlee/autocorrect), which normalizes
full/half-width punctuation, adds spacing between Chinese and Latin text, and
converts paired straight quotes to curly quotes.

## Install

```sh
uv tool install git+https://github.com/geekshootjack/whisper-workbench            # track main
uv tool install git+https://github.com/geekshootjack/whisper-workbench@v0.1.0     # pin a version
uv tool upgrade whisper-workbench
```

One-off use:

```sh
uvx --from git+https://github.com/geekshootjack/whisper-workbench wb transcribe meeting.m4a
```

## First Use Per Machine

The transcribing machine needs `ffmpeg` and a whisper.cpp `whisper-cli`: on
macOS `brew install whisper-cpp`; on Windows, download a prebuilt zip from the
[whisper.cpp releases](https://github.com/ggml-org/whisper.cpp/releases) and put
`whisper-cli.exe` on `PATH` (or point `WHISPER_CLI_PATH` at it). For NVIDIA GPU
acceleration, note the official CUDA builds top out at the RTX 40 series; the
50 series (Blackwell) needs a self-built binary with CUDA 12.8+.

Then one command downloads the models (about 3 GB; falls back to the
hf-mirror.com mirror when huggingface is unreachable, resumable):

```sh
wb setup      # models only, once per machine
```
The post-processing machine needs `claude` or `codex` on `PATH`.

Not sure what a given machine can run:

```sh
wb doctor
```

## Common Commands

```sh
wb transcribe a.m4a b.m4a -o ./out      # multiple files, custom output dir
wb transcribe meeting.m4a --srt         # also emit a subtitle file
wb transcribe meeting.m4a --no-vad      # disable silence skipping, keep the timeline continuous

wb format meeting.txt -g glossary.txt   # correct with a glossary of proper nouns
wb format meeting.txt --from compose    # reuse an existing corrected file, rerun only the rewrite
wb format meeting.txt --backend claude  # pick which LLM CLI to use
wb format meeting.txt --json            # machine-readable result paths and status
```

Full options: `wb --help` and `wb <command> --help`.

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `WHISPER_CLI_PATH` | Path to the whisper-cli executable |
| `WHISPER_MODEL_PATH` | Path to the ggml model file |
| `WHISPER_VAD_MODEL_PATH` | Path to the VAD model file |

## Development

```sh
git clone https://github.com/geekshootjack/whisper-workbench
cd whisper-workbench
uv sync --all-groups
uv run wb --help
uv run pytest
```

Architecture notes live in [docs/architecture.md](./docs/architecture.md), the
contribution process in [AGENTS.md](./AGENTS.md).

## License

MIT
