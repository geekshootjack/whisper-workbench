"""Stage 2: rewrite a corrected transcript into readable prose.

Unlike stage 1 this deliberately breaks line boundaries — speech recognition
lines are not sentences and not paragraphs. The contract is tidy-up, not
summarization: every substantive statement must survive.

Chunks are processed sequentially rather than in parallel because each request
is given the tail of the previous chunk's *output*, so paragraphs continue
across a seam instead of restarting.
"""

from __future__ import annotations

import logging
import re

from whisper_workbench import llm

LOG = logging.getLogger(__name__)

CHUNK_LINES = 300
CONTEXT_TAIL_CHARS = 400
# Below this ratio of output to input characters, the model probably
# summarized instead of tidying up.
LENGTH_WARN_RATIO = 0.6

Status = str  # "applied" | "partial" | "failed"

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_HR_RE = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")

INSTRUCTIONS = """\
你在把一段会议录音的语音转录稿整理成可读的正式文档。

要求：
- 保留全部实质内容。每一个论点、数据、结论、人名、时间、决定都必须留下。这是整理，不是摘要——不要压缩、不要提炼、不要省略任何一方的表述。
- 去掉口头禅和语气词（那个、然后、就是说、嗯、啊、对对对），去掉重复的半句和自我纠正时被放弃的前半句。
- 把语音识别切碎的短句合并成完整通顺的句子，补齐标点。
- 按话题分段，段与段之间空一行。段落长度自然即可，不要一句一段。
- 不要输出任何标题（不要出现 # ## ###），不要项目符号列表，除非说话人确实在逐条列举。
- 不要添加原文没有的内容。不要写导语、不要写总结、不要写你自己的评论。
- 保持说话人的原意和口吻，只改表达形式，不改立场和事实。
- 直接输出整理后的正文。不要任何前言后语，不要用代码块包裹。
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

    document = "\n\n".join(sections).strip() + "\n"

    source_chars = sum(len(line) for line in content)
    if source_chars and len(document) < source_chars * LENGTH_WARN_RATIO:
        LOG.warning(
            "Document is %d chars from %d chars of transcript — the model may have "
            "summarized instead of tidying up. The corrected transcript is still on disk.",
            len(document),
            source_chars,
        )

    if failures == 0:
        return document, "applied"
    if failures < len(chunks):
        return document, "partial"
    return document, "failed"
