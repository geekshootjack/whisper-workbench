"""Output paths must be predictable from the input path alone."""

from __future__ import annotations

from pathlib import Path

import pytest

from whisper_workbench import pipeline


def test_derive_paths_from_raw_transcript(tmp_path: Path) -> None:
    source = tmp_path / "meeting.txt"
    corrected, document = pipeline.derive_paths(source)

    assert corrected == tmp_path / "meeting.corrected.txt"
    assert document == tmp_path / "meeting.md"


def test_derive_paths_does_not_stack_corrected_suffix(tmp_path: Path) -> None:
    source = tmp_path / "meeting.corrected.txt"
    corrected, document = pipeline.derive_paths(source)

    assert corrected == tmp_path / "meeting.corrected.txt"
    assert document == tmp_path / "meeting.md"


def test_derive_paths_honours_explicit_output(tmp_path: Path) -> None:
    source = tmp_path / "meeting.txt"
    target = tmp_path / "out" / "notes.md"
    corrected, document = pipeline.derive_paths(source, target)

    assert corrected == tmp_path / "meeting.corrected.txt"
    assert document == target


def test_derive_paths_keeps_dots_inside_the_name(tmp_path: Path) -> None:
    source = tmp_path / "2026-07-02_18.00.03.txt"
    corrected, document = pipeline.derive_paths(source)

    assert corrected.name == "2026-07-02_18.00.03.corrected.txt"
    assert document.name == "2026-07-02_18.00.03.md"


def test_format_rejects_missing_transcript(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        pipeline.format_transcript(tmp_path / "nope.txt")


def test_format_rejects_unknown_stage(tmp_path: Path) -> None:
    source = tmp_path / "meeting.txt"
    source.write_text("一行\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown stage"):
        pipeline.format_transcript(source, start_stage="summarize")


def test_compose_stage_needs_an_existing_corrected_file(tmp_path: Path) -> None:
    source = tmp_path / "meeting.txt"
    source.write_text("一行\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="corrected transcript"):
        pipeline.format_transcript(source, start_stage="compose")


def _command(**overrides) -> list[str]:
    from whisper_workbench import transcribe

    defaults = dict(
        whisper_cli=Path("whisper-cli"),
        model_path=Path("model.bin"),
        audio=Path("a.wav"),
        lang="zh",
        output_base=Path("out"),
        vad_model_path=Path("vad.bin"),
        initial_prompt=None,
        want_srt=False,
    )
    return transcribe._build_command(**{**defaults, **overrides})


def test_vad_segmentation_is_tuned_for_transcripts_not_subtitles() -> None:
    from whisper_workbench import transcribe

    cmd = _command()

    # The 100ms default splits on every breath, yielding context-free lines.
    assert "--vad-min-silence-duration-ms" in cmd
    assert str(transcribe.VAD_MIN_SILENCE_MS) in cmd
    assert transcribe.VAD_MIN_SILENCE_MS > 100


def test_split_on_word_is_gone() -> None:
    # A no-op without --max-len, and --max-len is not set.
    cmd = _command()

    assert "-sow" not in cmd
    assert "--split-on-word" not in cmd
    assert "--max-len" not in cmd


def test_vad_flags_are_omitted_when_vad_is_off() -> None:
    cmd = _command(vad_model_path=None)

    assert not [flag for flag in cmd if flag.startswith("--vad")]


def test_srt_output_is_opt_in() -> None:
    assert "--output-srt" not in _command()
    assert "--output-srt" in _command(want_srt=True)
    assert "--output-txt" in _command()
