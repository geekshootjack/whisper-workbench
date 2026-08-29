"""Orchestration for ``wb format``: correct, then compose.

Output paths are a pure function of the input path so that an agent can
predict them without globbing a directory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from whisper_workbench import compose, correct, llm

LOG = logging.getLogger(__name__)

CORRECTED_SUFFIX = ".corrected.txt"
STAGES = ("correct", "compose")


@dataclass(slots=True)
class FormatResult:
    """Files written by one ``wb format`` run."""

    source: Path
    corrected: Path
    document: Path
    correct_status: str | None
    compose_status: str


def derive_paths(txt_path: Path, output: Path | None = None) -> tuple[Path, Path]:
    """Return the (corrected transcript, document) paths for an input file."""
    txt_path = txt_path.expanduser().resolve()
    stem = txt_path.stem
    # Re-running against an already-corrected file must not produce
    # meeting.corrected.corrected.txt.
    if stem.endswith(".corrected"):
        stem = stem[: -len(".corrected")]

    corrected = txt_path.with_name(stem + CORRECTED_SUFFIX)
    document = (
        output.expanduser().resolve()
        if output is not None
        else txt_path.with_name(stem + ".md")
    )
    return corrected, document


def format_transcript(
    txt_path: Path,
    *,
    output: Path | None = None,
    glossary: str | None = None,
    backend: str = llm.DEFAULT_BACKEND,
    model: str | None = None,
    timeout_sec: int = llm.DEFAULT_TIMEOUT_SEC,
    max_chars: int = compose.MAX_CHARS,
    start_stage: str = "correct",
) -> FormatResult:
    """Run the correct -> compose pipeline over a raw transcript."""
    if start_stage not in STAGES:
        raise ValueError(f"Unknown stage: {start_stage}")

    txt_path = txt_path.expanduser().resolve()
    if not txt_path.is_file():
        raise FileNotFoundError(f"Transcript not found: {txt_path}")

    corrected_path, document_path = derive_paths(txt_path, output)
    correct_status: str | None = None

    if start_stage == "correct":
        lines = txt_path.read_text(encoding="utf-8").splitlines()
        content = [line for line in lines if line.strip()]
        if not content:
            raise ValueError(f"Transcript is empty: {txt_path}")

        corrected_lines, correct_status = correct.correct_lines(
            content,
            backend=backend,
            model=model,
            timeout_sec=timeout_sec,
            glossary=glossary,
        )
        corrected_path.write_text("\n".join(corrected_lines) + "\n", encoding="utf-8")
        LOG.info("Wrote corrected transcript: %s", corrected_path)
    else:
        if not corrected_path.is_file():
            raise FileNotFoundError(
                f"--from compose needs an existing corrected transcript: {corrected_path}"
            )
        corrected_lines = corrected_path.read_text(encoding="utf-8").splitlines()
        LOG.info("Reusing corrected transcript: %s", corrected_path)

    document, compose_status = compose.compose_document(
        corrected_lines,
        backend=backend,
        model=model,
        timeout_sec=timeout_sec,
        max_chars=max_chars,
    )
    document_path.parent.mkdir(parents=True, exist_ok=True)
    document_path.write_text(document, encoding="utf-8")
    LOG.info("Wrote document: %s", document_path)

    return FormatResult(
        source=txt_path,
        corrected=corrected_path,
        document=document_path,
        correct_status=correct_status,
        compose_status=compose_status,
    )
