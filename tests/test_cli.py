"""CLI surface.

After `uv tool install` the top-level help is the only documentation an agent
sees, so its contents are part of the contract.
"""

from __future__ import annotations

import pytest

from pathlib import Path

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


def test_scp_source_names_this_host(monkeypatch) -> None:
    monkeypatch.delenv("WB_SSH_HOST", raising=False)
    monkeypatch.setattr(cli.socket, "gethostname", lambda: "GSJ-5.local")

    spec = cli._scp_source(Path("/Users/geekshootjack/a/meeting.txt"))

    # Short lowercase name only: it matches the ssh config alias, and the
    # user is whatever that alias resolves to.
    assert spec == "gsj-5:/Users/geekshootjack/a/meeting.txt"


def test_ssh_host_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setattr(cli.socket, "gethostname", lambda: "GSJ-5.local")
    monkeypatch.setenv("WB_SSH_HOST", "mac-studio")

    assert cli._ssh_host() == "mac-studio"


def test_scp_source_quotes_paths_containing_spaces(monkeypatch) -> None:
    monkeypatch.delenv("WB_SSH_HOST", raising=False)
    monkeypatch.setattr(cli.socket, "gethostname", lambda: "h.local")

    spec = cli._scp_source(Path("/a/BL Live Mix.txt"))

    assert spec.startswith("'") and spec.endswith("'")
    assert r"BL\ Live\ Mix.txt" in spec


def test_next_steps_mirrors_the_repo_relative_location(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("WB_SSH_HOST", raising=False)
    monkeypatch.setattr(cli.socket, "gethostname", lambda: "gsj-5")

    repo = tmp_path / "whisper-workbench"
    (repo / ".git").mkdir(parents=True)
    txt = repo / "data" / "pgmrecon" / "2026-07-28" / "rec.txt"
    txt.parent.mkdir(parents=True)

    cli._print_next_steps([txt])
    out = capsys.readouterr().out

    # Copying into the matching directory keeps the follow-up path valid on
    # the other machine.
    assert "data/pgmrecon/2026-07-28/\n" in out
    assert "wb format data/pgmrecon/2026-07-28/rec.txt" in out
    assert "在仓库根目录运行" in out


def test_next_steps_falls_back_to_cwd_outside_a_repo(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("WB_SSH_HOST", raising=False)
    monkeypatch.setattr(cli.socket, "gethostname", lambda: "gsj-5")

    txt = tmp_path / "loose" / "meeting.txt"
    txt.parent.mkdir(parents=True)

    cli._print_next_steps([txt])
    out = capsys.readouterr().out

    assert out.rstrip().endswith("wb format meeting.txt")
    assert " ." in out
