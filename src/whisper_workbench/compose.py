"""Stage 2: rewrite a corrected transcript into meeting minutes.

Unlike stage 1 this deliberately breaks line boundaries — speech recognition
lines are neither sentences nor paragraphs. The output is minutes rather than
a cleaned-up verbatim transcript, but it stays in the order topics came up:
no regrouping, no headings, no summary block.

Condensing is expected; losing a topic is not. The corrected transcript stays
on disk, so the full record is always one file away.

Chunks are processed sequentially rather than in parallel because each request
is given the tail of the previous chunk's *output*, so the minutes continue
across a seam instead of restarting.
"""

from __future__ import annotations

import logging
import re

import autocorrect_py

from whisper_workbench import llm

LOG = logging.getLogger(__name__)

CHUNK_LINES = 300
CONTEXT_TAIL_CHARS = 400
# Minutes legitimately run a fraction of the transcript's length, so this is
# only a floor for "a whole stretch of the meeting went missing", not a
# check on how tightly the model condensed.
LENGTH_WARN_RATIO = 0.15

Status = str  # "applied" | "partial" | "failed"

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_HR_RE = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")

INSTRUCTIONS = """\
你在把一段会议录音的语音转录稿整理成一份会议纪要。

结构要求：
- 严格按照转录稿里话题出现的先后顺序组织。不要重新归类，不要把分散在不同时间的相关内容合并到一处，不要调整顺序。
- 一个话题写成一段或连续几段，话题切换时空一行。段落长度自然即可，不要一句一段。
- 不要输出任何标题（不要出现 # ## ###）。不要在开头写摘要，不要在结尾写总结。整篇就是顺序展开的正文。
- 不要项目符号列表，除非说话人确实在逐条列举。

内容要求：
- 写成纪要，不是逐句誊清。用书面语转述讨论的内容，而不是把口语一句一句修顺。
- 每个话题交代清楚：讨论的是什么问题、各方提出的观点和理由、达成的结论或决定、待办事项和负责人（原文提到才写）。
- 保留全部实质信息：论点、数据、金额、时间、人名、决定、分歧。有分歧要写明是分歧，不要只写一方。
- 去掉寒暄、口头禅、语气词、重复的半句、自我纠正时被放弃的部分，以及与议题无关的闲聊。
- 不要添加原文没有的内容，不要写你自己的评价或建议。
- 不要拔高结论的确定性：原文说"再看看"就不能写成"决定"。

直接输出纪要正文，不要任何前言后语，不要用代码块包裹。
"""


def _build_prompt(lines: list[str], preceding: str | None) -> str:
    parts = [INSTRUCTIONS]
    if preceding:
        parts.append(
            "\n已经整理好的上文结尾（只作为衔接参考，不要重复输出这部分内容）：\n"
            f"{preceding}\n"
        )
    parts.append("\n需要整理的转录片段：\n")
    parts.append("\n".join(lines))
    return "".join(parts)


def _clean_output(text: str) -> str:
    """Strip artifacts the model adds despite being told not to.

    LLM CLIs are unreliable about "no headings", and the fix is deterministic
    and free, so it is done here rather than hoped for in the prompt.
    """
    cleaned: list[str] = []
    for line in llm.strip_code_fence(text).splitlines():
        if _HR_RE.match(line):
            continue
        demoted = _HEADING_RE.sub("", line)
        if demoted != line:
            LOG.debug("Demoted a heading emitted by the model: %r", line.strip())
        cleaned.append(demoted.rstrip())

    # Collapse runs of blank lines down to a single paragraph break.
    result: list[str] = []
    for line in cleaned:
        if not line and (not result or not result[-1]):
            continue
        result.append(line)
    return "\n".join(result).strip()


def _tail(text: str, limit: int = CONTEXT_TAIL_CHARS) -> str:
    return text[-limit:].strip() if len(text) > limit else text.strip()


def normalize(text: str) -> str:
    """Normalize punctuation width and CJK/Latin spacing in the final document.

    Models are inconsistent about full-width versus half-width punctuation in
    Chinese prose, so this is applied deterministically rather than asked for
    in the prompt. Default rules, spacing included — that is wanted in a
    document, unlike in subtitle lines.
    """
    return autocorrect_py.format(text)


def _compose_chunk(
    lines: list[str],
    preceding: str | None,
    *,
    backend: str,
    model: str | None,
    timeout_sec: int,
) -> str | None:
    """Rewrite one chunk, trying each backend once. None means every one failed."""
    prompt = _build_prompt(lines, preceding)
    for name in llm.ordered_backends(backend):
        try:
            raw = llm.call(prompt, backend=name, model=model, timeout_sec=timeout_sec)
        except RuntimeError as exc:
            LOG.warning("Compose chunk failed via %s: %s", name, exc)
            continue
        text = _clean_output(raw)
        if text:
            return text
        LOG.warning("Compose chunk returned empty output via %s", name)
    return None


def compose_document(
    lines: list[str],
    *,
    backend: str = llm.DEFAULT_BACKEND,
    model: str | None = None,
    timeout_sec: int = llm.DEFAULT_TIMEOUT_SEC,
    chunk_lines: int = CHUNK_LINES,
) -> tuple[str, Status]:
    """Rewrite corrected transcript lines into a paragraphed document."""
    content = [line.strip() for line in lines if line.strip()]
    if not content:
        return "", "applied"

    chunk_lines = max(1, chunk_lines)
    chunks = [content[i : i + chunk_lines] for i in range(0, len(content), chunk_lines)]
    LOG.info(
        "Compose: %d line(s) in %d sequential chunk(s) of %d",
        len(content),
        len(chunks),
        chunk_lines,
    )

    sections: list[str] = []
    failures = 0
    for index, chunk in enumerate(chunks, start=1):
        LOG.info("Compose chunk %d/%d (%d lines)", index, len(chunks), len(chunk))
        preceding = _tail(sections[-1]) if sections else None
        text = _compose_chunk(
            chunk,
            preceding,
            backend=backend,
            model=model,
            timeout_sec=timeout_sec,
        )
        if text is None:
            failures += 1
            LOG.warning("Compose chunk %d kept as raw transcript lines", index)
            text = "\n".join(chunk)
        sections.append(text)

    # Applied once over the assembled document rather than per chunk: chunk
    # boundaries are not sentence boundaries, and this is the last thing that
    # touches the text before it is written out.
    document = normalize("\n\n".join(sections).strip()) + "\n"

    source_chars = sum(len(line) for line in content)
    if source_chars and len(document) < source_chars * LENGTH_WARN_RATIO:
        LOG.warning(
            "Minutes are %d chars from %d chars of transcript — that is short even "
            "for minutes, so check whether a topic was dropped. The corrected "
            "transcript is still on disk.",
            len(document),
            source_chars,
        )

    if failures == 0:
        return document, "applied"
    if failures < len(chunks):
        return document, "partial"
    return document, "failed"
