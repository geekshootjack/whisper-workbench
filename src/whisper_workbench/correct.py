"""Stage 1: fix recognition errors while preserving the line structure.

The contract here is strict: N lines in, N lines out, same order. The model is
asked for a patch (only the lines it wants to change, keyed by id) rather than
a full rewrite, so a confused response can drop corrections but can never
scramble or lose the transcript.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from whisper_workbench import llm

LOG = logging.getLogger(__name__)

CHUNK_SIZE = 400
MIN_CHUNK_SIZE = 50
MAX_WORKERS = 2

Status = str  # "applied" | "partial" | "failed"


def _build_prompt(lines: list[str], glossary: str | None, line_offset: int) -> str:
    payload = {"lines": [{"id": i + line_offset, "text": t} for i, t in enumerate(lines)]}
    parts = [
        "ROLE:\n"
        "You are a transcript correction assistant for Chinese transcripts.\n\n"
        "GOAL:\n"
        "Review each line. Return ONLY the lines that need correction.\n"
        "If a line is already correct, do NOT include it in your response.\n"
        "Return an empty corrections list if nothing needs changing.\n\n"
        "OUTPUT FORMAT (必须严格遵守):\n"
        '{"corrections":[{"id":<int>,"text":"<corrected_text>"}]}\n'
        "- Return ONLY valid JSON. No markdown, no explanation.\n"
        "- Return ONLY lines you are changing.\n"
        '- The "id" must be one of the input line IDs.\n'
        "- Do NOT invent new IDs. Do NOT merge lines. Do NOT split lines.\n\n"
        "CORRECTION RULES:\n"
        "- Fix homophones and misrecognition errors (同音字与误识别纠错).\n"
        "- Normalize proper nouns (e.g. deep mind -> DeepMind, open ai -> OpenAI).\n"
        "- Expand clearly abbreviated Arabic-numeral years (08年 -> 2008年).\n"
        "- Do not rewrite ambiguous spoken year phrases such as 八九年.\n"
        "- Convert Traditional Chinese to Simplified Chinese (繁体→简体).\n"
        "- Keep numbers, punctuation and non-Chinese tokens unless clearly wrong.\n"
        "- Do NOT rewrite for style. This stage fixes errors only.\n\n"
    ]
    if glossary:
        parts.append(
            "GLOSSARY OVERRIDE (最高优先级):\n"
            "Match any glossary term and normalize to the exact listed form.\n"
            "Glossary rules override all other normalization choices.\n\n"
            f"Glossary:\n{glossary}\n\n"
        )
    parts.append("INPUT:\n")
    parts.append(json.dumps(payload, ensure_ascii=False))
    return "".join(parts)


def _apply_patch(raw: str, input_lines: list[str], line_offset: int) -> list[str]:
    """Apply an id-keyed correction patch onto the original lines."""
    payload = llm.extract_json_object(raw)
    corrections = payload.get("corrections", [])
    if not isinstance(corrections, list):
        raise ValueError("LLM response JSON missing `corrections` array.")

    valid_ids = range(line_offset, line_offset + len(input_lines))
    result = list(input_lines)
    seen: set[int] = set()

    for item in corrections:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        text = item.get("text")
        if not isinstance(item_id, int) or not isinstance(text, str):
            continue
        if item_id not in valid_ids:
            LOG.warning("LLM returned out-of-range id %s, skipping", item_id)
            continue
        if item_id in seen:
            LOG.warning("LLM returned duplicate id %s, skipping", item_id)
            continue
        seen.add(item_id)
        result[item_id - line_offset] = text.strip()

    LOG.info("Applied %d corrections across %d lines", len(seen), len(input_lines))
    return result


def _correct_chunk_once(
    lines: list[str],
    *,
    backend: str,
    model: str | None,
    timeout_sec: int,
    glossary: str | None,
    line_offset: int,
) -> list[str]:
    prompt = _build_prompt(lines, glossary, line_offset)
    raw = llm.call(prompt, backend=backend, model=model, timeout_sec=timeout_sec)
    return _apply_patch(raw, lines, line_offset)


def _correct_chunked(
    lines: list[str],
    *,
    backend: str,
    model: str | None,
    timeout_sec: int,
    glossary: str | None,
    chunk_size: int,
) -> tuple[list[str], int]:
    total = len(lines)
    chunk_size = max(1, chunk_size)
    chunks = [
        (start, min(start + chunk_size, total), lines[start : start + chunk_size])
        for start in range(0, total, chunk_size)
    ]
    workers = max(1, min(len(chunks), MAX_WORKERS))
    LOG.info(
        "Correction: %d line(s), %d chunk(s) of %d, %d worker(s)",
        total,
        len(chunks),
        chunk_size,
        workers,
    )

    def degrade(start: int, chunk: list[str], exc: Exception) -> list[str] | None:
        """Retry a failed chunk as smaller sub-chunks."""
        if len(chunk) <= MIN_CHUNK_SIZE:
            return None
        split_size = max(MIN_CHUNK_SIZE, len(chunk) // 2)
        LOG.warning(
            "Correction chunk %d-%d failed, splitting into %d-line sub-chunks: %s",
            start + 1,
            start + len(chunk),
            split_size,
            exc,
        )
        corrected, failures = _correct_chunked(
            chunk,
            backend=backend,
            model=model,
            timeout_sec=timeout_sec,
            glossary=glossary,
            chunk_size=split_size,
        )
        sub_chunk_count = len(range(0, len(chunk), split_size))
        return None if failures == sub_chunk_count else corrected

    def process(item: tuple[int, tuple[int, int, list[str]]]) -> tuple[int, list[str] | None]:
        index, (start, end, chunk) = item
        LOG.info("Correction chunk %d/%d: lines %d-%d", index, len(chunks), start + 1, end)
        try:
            return start, _correct_chunk_once(
                chunk,
                backend=backend,
                model=model,
                timeout_sec=timeout_sec,
                glossary=glossary,
                line_offset=start + 1,
            )
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            return start, degrade(start, chunk, exc)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = dict(executor.map(process, enumerate(chunks, start=1)))

    corrected: list[str] = []
    failures = 0
    for start, _end, chunk in chunks:
        chunk_result = results[start]
        if chunk_result is None:
            failures += 1
            corrected.extend(chunk)
        else:
            corrected.extend(chunk_result)
    return corrected, failures


def correct_lines(
    lines: list[str],
    *,
    backend: str = llm.DEFAULT_BACKEND,
    model: str | None = None,
    timeout_sec: int = llm.DEFAULT_TIMEOUT_SEC,
    glossary: str | None = None,
) -> tuple[list[str], Status]:
    """Correct transcript lines, falling back to the originals on failure."""
    if not lines:
        return [], "applied"

    total_chunks = max(1, (len(lines) + CHUNK_SIZE - 1) // CHUNK_SIZE)

    for name in llm.ordered_backends(backend):
        corrected, failures = _correct_chunked(
            lines,
            backend=name,
            model=model,
            timeout_sec=timeout_sec,
            glossary=glossary,
            chunk_size=CHUNK_SIZE,
        )
        if failures == 0:
            LOG.info("Correction applied via %s", name)
            return corrected, "applied"
        if failures < total_chunks:
            LOG.warning(
                "Correction partially applied via %s; %d chunk(s) kept as-is",
                name,
                failures,
            )
            return corrected, "partial"
        LOG.warning("Correction failed entirely via %s, trying next backend", name)

    LOG.warning("Correction failed on all backends; keeping the original lines")
    return list(lines), "failed"
