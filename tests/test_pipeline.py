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
