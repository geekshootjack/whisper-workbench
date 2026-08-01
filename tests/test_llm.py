"""Backend selection and response unwrapping."""

from __future__ import annotations

import pytest

from whisper_workbench import llm


def test_requested_backend_comes_first_when_installed(monkeypatch) -> None:
    monkeypatch.setattr(llm, "available_backends", lambda: ["gemini", "claude"])

    assert llm.ordered_backends("claude") == ["claude", "gemini"]


def test_uninstalled_backends_are_not_attempted(monkeypatch) -> None:
    monkeypatch.setattr(llm, "available_backends", lambda: ["claude"])

    assert llm.ordered_backends("gemini") == ["claude"]


def test_no_installed_backend_fails_with_an_actionable_message(monkeypatch) -> None:
    monkeypatch.setattr(llm, "available_backends", lambda: [])

    with pytest.raises(RuntimeError, match="No LLM CLI found"):
        llm.ordered_backends("gemini")


def test_available_backends_are_a_subset_in_declared_order() -> None:
    found = llm.available_backends()

    assert found == [name for name in llm.BACKENDS if name in found]


def test_strip_code_fence_drops_the_opening_line_with_its_language_tag() -> None:
    assert llm.strip_code_fence("```json\n{}\n```") == "{}"
    assert llm.strip_code_fence("```\n正文\n```") == "正文"


def test_strip_code_fence_leaves_unfenced_text_alone() -> None:
    assert llm.strip_code_fence("  正文内容  ") == "正文内容"


def test_extract_json_object_ignores_surrounding_prose() -> None:
    raw = '好的，这是结果：\n{"corrections": []}\n希望有帮助。'

    assert llm.extract_json_object(raw) == {"corrections": []}


def test_extract_json_object_rejects_a_response_without_json() -> None:
    with pytest.raises(ValueError, match="did not contain a JSON object"):
        llm.extract_json_object("抱歉，我无法完成。")


def test_default_backend_is_a_known_backend() -> None:
    assert llm.DEFAULT_BACKEND in llm.BACKENDS
