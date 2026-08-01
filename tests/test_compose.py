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
    document, status = compose.compose_document(lines, max_chars=8)

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

    # 4 chars of budget fits two 1-char lines per chunk, so this splits in two.
    document, status = compose.compose_document(["甲", "乙", "丙", "丁"], max_chars=4)

    assert status == "partial"
    assert "甲" in document
    assert "整理后的段落。" in document


def test_preceding_context_is_the_tail_of_the_previous_output(monkeypatch) -> None:
    seen: list[str | None] = []

    def fake_chunk(chunk, preceding, **kwargs):
        seen.append(preceding)
        return f"整理:{chunk[0]}"

    monkeypatch.setattr(compose, "_compose_chunk", fake_chunk)
    compose.compose_document(["甲", "乙", "丙"], max_chars=1)

    assert seen[0] is None
    assert seen[1] == "整理:甲"
    assert seen[2] == "整理:乙"


def test_normalize_converts_punctuation_to_fullwidth() -> None:
    assert compose.normalize("预算是300万.下周再看看,先这样") == "预算是 300 万。下周再看看，先这样"


def test_normalize_keeps_paragraph_breaks() -> None:
    normalized = compose.normalize("第一段有内容,写了一些东西.\n\n第二段也有内容,同样写了些.")

    assert normalized.count("\n\n") == 1
    assert normalized.splitlines()[1] == ""


def test_document_is_normalized_before_being_returned(monkeypatch) -> None:
    monkeypatch.setattr(compose, "_compose_chunk", lambda *a, **k: "预算是300万.")

    document, status = compose.compose_document(["甲"], max_chars=1)

    assert status == "applied"
    assert document == "预算是 300 万。\n"


def test_raw_fallback_lines_are_normalized_too(monkeypatch) -> None:
    monkeypatch.setattr(compose, "_compose_chunk", lambda *a, **k: None)

    document, status = compose.compose_document(["预算是300万."], max_chars=1)

    assert status == "failed"
    assert "预算是 300 万。" in document


def test_a_realistic_transcript_is_one_call() -> None:
    # 938 lines of ~15 chars is a real meeting transcript; it must not split.
    lines = ["这是一句会议里的话大概十五个字" for _ in range(938)]

    assert len(compose._split_by_chars(lines, compose.MAX_CHARS)) == 1


def test_splitting_counts_characters_not_lines() -> None:
    short = ["甲"] * 100
    long = ["这是一句很长的话" * 10] * 100

    # Same line count, wildly different size: only the big one splits.
    assert len(compose._split_by_chars(short, 1000)) == 1
    assert len(compose._split_by_chars(long, 1000)) > 1


def test_split_never_drops_a_line() -> None:
    lines = [f"第{i}句" for i in range(50)]
    chunks = compose._split_by_chars(lines, 10)

    assert [line for chunk in chunks for line in chunk] == lines


def test_a_line_longer_than_the_budget_still_gets_its_own_chunk() -> None:
    chunks = compose._split_by_chars(["短", "特别长" * 100, "短"], 10)

    assert [line for chunk in chunks for line in chunk] == ["短", "特别长" * 100, "短"]


def test_straight_double_quotes_become_curly_in_chinese_prose() -> None:
    assert compose.normalize('他说"下周再看看"，然后散会') == "他说“下周再看看”，然后散会"


def test_multiple_quote_pairs_on_one_line() -> None:
    out = compose.normalize('先谈"排期"，再谈"预算"这件事')

    assert out == "先谈“排期”，再谈“预算”这件事"


def test_an_unbalanced_quote_is_left_alone() -> None:
    # Guessing the direction would be worse than leaving it.
    assert '"' in compose.normalize('他说"这个事情还没定，先这样')


def test_english_apostrophes_survive() -> None:
    out = compose.normalize("他提到 don't repeat yourself 这个原则很重要")

    assert "don't" in out
    assert "‘" not in out


def test_single_quotes_wrapping_chinese_become_curly() -> None:
    out = compose.normalize("他把这个叫做'饱和式工作'这种说法")

    assert "‘饱和式工作’" in out


def test_lines_without_chinese_are_untouched_by_quote_rules() -> None:
    assert compose._curly_quotes('print("hello")') == 'print("hello")'


def test_normalize_preserves_a_trailing_newline() -> None:
    assert compose._curly_quotes("他说了一句话。\n") == "他说了一句话。\n"


def test_normalize_only_touches_what_it_claims_to() -> None:
    original = '第一段有"引号"在里面。\n\n第二段没有。\n'
    normalized = compose._curly_quotes(original)

    assert normalized == '第一段有“引号”在里面。\n\n第二段没有。\n'
