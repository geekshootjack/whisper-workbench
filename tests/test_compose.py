"""The compose stage's deterministic output guard.

The prompt forbids headings; LLM CLIs do not reliably obey. These tests cover
the cleanup that enforces it regardless.
"""

from __future__ import annotations

from whisper_workbench import compose


def test_headings_are_demoted_to_plain_paragraphs() -> None:
    raw = "# 会议开场\n今天讨论三件事。\n\n### 第二部分\n预算问题。"
    cleaned = compose._clean_output(raw)

    assert "#" not in cleaned
    assert "会议开场" in cleaned
    assert "第二部分" in cleaned
    assert "预算问题。" in cleaned


def test_hash_inside_a_sentence_survives() -> None:
    cleaned = compose._clean_output("他说走 C#/.NET 那条路线。")

    assert cleaned == "他说走 C#/.NET 那条路线。"


def test_code_fence_wrapper_is_removed() -> None:
    cleaned = compose._clean_output("```markdown\n正文内容。\n```")

    assert cleaned == "正文内容。"


def test_horizontal_rules_are_dropped() -> None:
    cleaned = compose._clean_output("第一段。\n\n---\n\n第二段。")

    assert "---" not in cleaned
    assert cleaned == "第一段。\n\n第二段。"


def test_blank_line_runs_collapse_to_one_paragraph_break() -> None:
    cleaned = compose._clean_output("第一段。\n\n\n\n第二段。")

    assert cleaned == "第一段。\n\n第二段。"


def test_empty_input_yields_empty_document() -> None:
    document, status = compose.compose_document(["", "   ", "\t"])

    assert document == ""
    assert status == "applied"


def test_all_chunks_failing_falls_back_to_the_raw_transcript(monkeypatch) -> None:
    monkeypatch.setattr(compose, "_compose_chunk", lambda *a, **k: None)

    lines = ["第一句话", "第二句话", "第三句话"]
    document, status = compose.compose_document(lines, chunk_lines=2)

    assert status == "failed"
    # Nothing is lost even when every backend is unreachable.
    for line in lines:
        assert line in document


def test_partial_failure_is_reported_as_partial(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_chunk(chunk, preceding, **kwargs):
        calls["n"] += 1
        return None if calls["n"] == 1 else "整理后的段落。"

    monkeypatch.setattr(compose, "_compose_chunk", fake_chunk)

    document, status = compose.compose_document(["甲", "乙", "丙", "丁"], chunk_lines=2)

    assert status == "partial"
    assert "甲" in document
    assert "整理后的段落。" in document


def test_preceding_context_is_the_tail_of_the_previous_output(monkeypatch) -> None:
    seen: list[str | None] = []

    def fake_chunk(chunk, preceding, **kwargs):
        seen.append(preceding)
        return f"整理:{chunk[0]}"

    monkeypatch.setattr(compose, "_compose_chunk", fake_chunk)
    compose.compose_document(["甲", "乙", "丙"], chunk_lines=1)

    assert seen[0] is None
    assert seen[1] == "整理:甲"
    assert seen[2] == "整理:乙"
