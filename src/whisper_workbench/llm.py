"""Shared plumbing for driving LLM CLIs as subprocesses.

Both post-processing stages talk to the same set of coding-agent CLIs, so the
subprocess handling, backend ordering, and JSON extraction live here.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

BACKENDS = ("gemini", "claude", "codex")
DEFAULT_BACKEND = "gemini"
DEFAULT_TIMEOUT_SEC = 300


def _decode(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


def _summarize_cli_error(stderr: bytes | str | None) -> str:
    lines = [line.strip() for line in _decode(stderr).splitlines() if line.strip()]
    if not lines:
        return "(no stderr output)"
    preview = "\n".join(lines[:8])
    return preview + "\n..." if len(lines) > 8 else preview


def _default_model_for(backend: str) -> str | None:
    if backend == "claude":
        return "haiku"
    return None


def available_backends() -> list[str]:
    """Return the LLM CLIs that are actually on PATH."""
    return [name for name in BACKENDS if shutil.which(name)]


def ordered_backends(primary: str) -> list[str]:
    """Return the installed backends, ``primary`` first, for fallback.

    Backends that are not on PATH are filtered out rather than attempted —
    otherwise asking for a CLI the machine does not have burns a full pass
    over every chunk before failing over.
    """
    available = available_backends()
    if not available:
        raise RuntimeError(
            "No LLM CLI found in PATH. Install one of: " + ", ".join(BACKENDS)
        )
    if primary not in available:
        LOG.warning(
            "LLM backend '%s' is not in PATH; using %s instead",
            primary,
            available[0],
        )
    return [
        *([primary] if primary in available else []),
        *(name for name in available if name != primary),
    ]


def _run(cmd: list[str], prompt: str, timeout_sec: int, backend: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            cmd,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=timeout_sec,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"{backend} CLI not found in PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{backend} request timed out after {timeout_sec} seconds."
        ) from exc


def _call_gemini(prompt: str, model: str | None, timeout_sec: int) -> str:
    cmd = ["gemini", "--prompt", "", "--output-format", "text"]
    if model:
        cmd.extend(["--model", model])
    result = _run(cmd, prompt, timeout_sec, "gemini")
    if result.returncode != 0:
        raise RuntimeError(f"gemini failed: {_summarize_cli_error(result.stderr)}")
    return _decode(result.stdout).strip()


def _call_claude(prompt: str, model: str | None, timeout_sec: int) -> str:
    cmd = ["claude", "--print", "--no-session-persistence"]
    if model:
        cmd.extend(["--model", model])
    result = _run(cmd, prompt, timeout_sec, "claude")
    if result.returncode != 0:
        raise RuntimeError(f"claude failed: {_summarize_cli_error(result.stderr)}")
    return _decode(result.stdout).strip()


def _call_codex(prompt: str, model: str | None, timeout_sec: int) -> str:
    with tempfile.NamedTemporaryFile(
        prefix="codex_last_", suffix=".txt", delete=False
    ) as handle:
        output_path = Path(handle.name)

    cmd = [
        "codex",
        "exec",
        "-",
        "--skip-git-repo-check",
        "--output-last-message",
        str(output_path),
    ]
    if model:
        cmd.extend(["--model", model])

    try:
        result = _run(cmd, prompt, timeout_sec, "codex")
        if result.returncode != 0:
            raise RuntimeError(f"codex failed: {_summarize_cli_error(result.stderr)}")
        if output_path.is_file():
            text = output_path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text
        return _decode(result.stdout).strip()
    finally:
        output_path.unlink(missing_ok=True)


def call(prompt: str, *, backend: str, model: str | None, timeout_sec: int) -> str:
    """Send a prompt to one LLM CLI and return its raw text response."""
    effective_model = model or _default_model_for(backend)
    if backend == "gemini":
        return _call_gemini(prompt, effective_model, timeout_sec)
    if backend == "claude":
        return _call_claude(prompt, effective_model, timeout_sec)
    if backend == "codex":
        return _call_codex(prompt, effective_model, timeout_sec)
    raise ValueError(f"Unsupported llm backend: {backend}")


def strip_code_fence(raw: str) -> str:
    """Remove a wrapping markdown code fence if the model added one."""
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def extract_json_object(raw: str) -> dict[str, Any]:
    """Pull the first JSON object out of an LLM response."""
    text = strip_code_fence(raw)
    if text.lower().startswith("json"):
        text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response did not contain a JSON object.")
    return json.loads(text[start : end + 1])
