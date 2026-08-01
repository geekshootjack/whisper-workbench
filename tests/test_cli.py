"""CLI surface.

After `uv tool install` the top-level help is the only documentation an agent
sees, so its contents are part of the contract.
"""

from __future__ import annotations

import pytest

from whisper_workbench import assets, cli, llm


def _parse(argv: list[str]):
    return cli.build_parser().parse_args(argv)


def test_transcribe_defaults_to_chinese_and_the_default_model() -> None:
    args = _parse(["transcribe", "meeting.m4a"])

    assert args.audio == ["meeting.m4a"]
    assert args.lang == "zh"
    assert args.model == assets.DEFAULT_MODEL
    assert args.output_dir is None
    assert args.srt is False
    assert args.no_vad is False


def test_transcribe_accepts_several_inputs() -> None:
    args = _parse(["transcribe", "a.wav", "b.wav", "-o", "out"])

    assert args.audio == ["a.wav", "b.wav"]
    assert args.output_dir == "out"


def test_format_defaults() -> None:
    args = _parse(["format", "meeting.txt"])

    assert args.txt == "meeting.txt"
    assert args.start_stage == "correct"
    assert args.backend == llm.DEFAULT_BACKEND
    assert args.timeout == llm.DEFAULT_TIMEOUT_SEC
    assert args.output is None


def test_from_flag_maps_onto_the_start_stage() -> None:
    args = _parse(["format", "meeting.txt", "--from", "compose"])

    assert args.start_stage == "compose"


def test_stdout_and_json_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        _parse(["format", "meeting.txt", "--stdout", "--json"])


@pytest.mark.parametrize(
    "flag",
    ["--skip-vad", "--vad-model", "--skip-update"],
)
def test_retired_setup_flags_are_gone(flag: str) -> None:
    with pytest.raises(SystemExit):
        _parse(["setup", flag])


@pytest.mark.parametrize(
    "flag",
    ["--backend", "--decode-profile", "--split-on-punc", "--autocorrect"],
)
def test_retired_transcribe_flags_are_gone(flag: str) -> None:
    with pytest.raises(SystemExit):
        _parse(["transcribe", "meeting.m4a", flag])


@pytest.mark.parametrize("command", ["convert", "batch", "postprocess"])
def test_retired_subcommands_are_gone(command: str) -> None:
    with pytest.raises(SystemExit):
        _parse([command])


def test_setup_defaults_are_idempotent() -> None:
    args = _parse(["setup"])

    assert args.model == assets.DEFAULT_MODEL
    assert args.update is False


def test_top_level_help_teaches_both_steps() -> None:
    help_text = cli.build_parser().format_help()

    assert "wb transcribe" in help_text
    assert "wb format" in help_text
    assert "wb setup" in help_text
    assert "wb doctor" in help_text


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit):
        _parse([])
