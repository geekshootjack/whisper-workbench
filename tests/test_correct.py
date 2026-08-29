"""The correction stage must never lose or reorder lines.

A confused model response may fail to correct, but it must not be able to
scramble the transcript.
"""

from __future__ import annotations

import json

import pytest

from whisper_workbench import correct, llm


def _patch(items: list[dict[str, object]]) -> str:
    return json.dumps({"corrections": items}, ensure_ascii=False)


def test_patch_replaces_only_the_listed_ids() -> None:
    lines = ["深度求索", "开放人工智能", "第三行"]
    raw = _patch([{"id": 2, "text": "OpenAI"}])

    assert correct._apply_patch(raw, lines, 1) == ["深度求索", "OpenAI", "第三行"]


def test_patch_respects_the_line_offset() -> None:
    lines = ["甲", "乙"]
    raw = _patch([{"id": 401, "text": "甲改"}])

    assert correct._apply_patch(raw, lines, 401) == ["甲改", "乙"]


def test_out_of_range_ids_are_ignored() -> None:
    lines = ["甲", "乙"]
    raw = _patch([{"id": 99, "text": "不该出现"}])

    assert correct._apply_patch(raw, lines, 1) == lines


def test_duplicate_ids_keep_the_first_correction() -> None:
    lines = ["甲", "乙"]
    raw = _patch([{"id": 1, "text": "第一次"}, {"id": 1, "text": "第二次"}])

    assert correct._apply_patch(raw, lines, 1) == ["第一次", "乙"]


def test_malformed_entries_are_skipped_without_failing() -> None:
    lines = ["甲", "乙"]
    raw = _patch(["not a dict", {"id": "2", "text": "字符串 id"}, {"id": 2}])

    assert correct._apply_patch(raw, lines, 1) == lines


def test_empty_corrections_leave_everything_alone() -> None:
    lines = ["甲", "乙", "丙"]

    assert correct._apply_patch(_patch([]), lines, 1) == lines


def test_response_wrapped_in_a_code_fence_is_still_parsed() -> None:
    lines = ["甲"]
    raw = "```json\n" + _patch([{"id": 1, "text": "改"}]) + "\n```"

    assert correct._apply_patch(raw, lines, 1) == ["改"]


def test_non_json_response_raises() -> None:
    with pytest.raises(ValueError):
        correct._apply_patch("抱歉，我无法处理。", ["甲"], 1)


def test_corrections_must_be_a_list() -> None:
    raw = json.dumps({"corrections": {"id": 1}})

    with pytest.raises(ValueError, match="corrections"):
        correct._apply_patch(raw, ["甲"], 1)


def test_empty_input_short_circuits() -> None:
    assert correct.correct_lines([]) == ([], "applied")


def test_line_count_is_preserved_when_every_backend_fails(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(correct, "_correct_chunk_once", boom)
    monkeypatch.setattr(llm, "available_backends", lambda: ["claude"])

    lines = [f"第{i}行" for i in range(120)]
    corrected, status = correct.correct_lines(lines)

    assert status == "failed"
    assert corrected == lines
