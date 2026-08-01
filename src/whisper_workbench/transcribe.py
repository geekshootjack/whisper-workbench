"""Local whisper.cpp transcription.

Deliberately free of any LLM or network dependency: this half of the workflow
usually runs on a different machine from ``wb format``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from whisper_workbench import assets

LOG = logging.getLogger(__name__)

# One fixed decode configuration. The three former "decode profiles" differed
# only in beam width, and two of them were byte-for-byte identical.
THREADS = max(1, min(8, os.cpu_count() or 4))
BEAM_SIZE = 5
BEST_OF = 5
ENTROPY_THOLD = 2.8
MAX_CONTEXT = 64


@dataclass(slots=True)
class TranscribeResult:
    """Paths produced for one input file."""

    audio: Path
    txt: Path
    srt: Path | None


def _decode_stderr(stderr: bytes | str | None) -> str:
    """Decode subprocess stderr safely across platform code pages."""
    if stderr is None:
        return ""
    if isinstance(stderr, bytes):
        return stderr.decode("utf-8", errors="replace")
    return stderr


def _convert_to_temp_16khz_wav(input_file: Path) -> Path:
    """Convert any media file to a temporary 16 kHz mono WAV."""
    fd, temp_path = tempfile.mkstemp(suffix="_16khz.wav")
    os.close(fd)
    temp_wav = Path(temp_path)
    temp_wav.unlink(missing_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_file),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(temp_wav),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg not found in PATH. Install ffmpeg to transcribe non-WAV input."
        ) from exc
    except subprocess.CalledProcessError as exc:
        temp_wav.unlink(missing_ok=True)
        raise RuntimeError(
            f"ffmpeg failed to convert {input_file}: "
            f"{_decode_stderr(exc.stderr).strip()}"
        ) from exc

    if not temp_wav.is_file() or temp_wav.stat().st_size == 0:
        temp_wav.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg produced an empty wav for {input_file}")

    return temp_wav


def _build_command(
    *,
    whisper_cli: Path,
    model_path: Path,
    audio: Path,
    lang: str,
    output_base: Path,
    vad_model_path: Path | None,
    initial_prompt: str | None,
    want_srt: bool,
) -> list[str]:
    cmd = [
        str(whisper_cli),
        "-t",
        str(THREADS),
        "-m",
        str(model_path),
        "-f",
        str(audio),
        "--language",
        lang,
        "--beam-size",
        str(BEAM_SIZE),
        "--best-of",
        str(BEST_OF),
        "--entropy-thold",
        str(ENTROPY_THOLD),
        "--max-context",
        str(MAX_CONTEXT),
        "-sow",
        "--suppress-nst",
    ]
    if vad_model_path is not None:
        cmd.extend(["--vad", "--vad-model", str(vad_model_path)])
    if initial_prompt:
        cmd.extend(["--prompt", initial_prompt])

    cmd.append("--output-txt")
    if want_srt:
        cmd.append("--output-srt")
    cmd.extend(["--output-file", str(output_base)])
    return cmd


def transcribe_file(
    audio_file: Path,
    output_dir: Path,
    *,
    lang: str,
    model_path: Path,
    use_vad: bool = True,
    initial_prompt: str | None = None,
    want_srt: bool = False,
) -> TranscribeResult:
    """Transcribe one audio/video file to ``<stem>.txt`` (and optionally .srt)."""
    audio_file = audio_file.expanduser().resolve()
    if not audio_file.is_file():
        raise FileNotFoundError(f"Input file not found: {audio_file}")

    whisper_cli = assets.require_whisper_cli()
    vad_model_path = assets.require_vad_model() if use_vad else None

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_base = output_dir / audio_file.stem

    input_for_whisper = audio_file
    cleanup_temp = False
    if audio_file.suffix.lower() != ".wav":
        LOG.info("Converting %s to temporary 16 kHz WAV", audio_file.name)
        input_for_whisper = _convert_to_temp_16khz_wav(audio_file)
        cleanup_temp = True

    cmd = _build_command(
        whisper_cli=whisper_cli,
        model_path=model_path,
        audio=input_for_whisper,
        lang=lang,
        output_base=output_base,
        vad_model_path=vad_model_path,
        initial_prompt=initial_prompt,
        want_srt=want_srt,
    )

    try:
        subprocess.run(cmd, check=True)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 4551:
            raise RuntimeError(
                "Windows App Control policy blocked whisper-cli. Set "
                f"{assets.ENV_CLI} to an approved whisper-cli.exe path."
            ) from exc
        raise
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"whisper-cli failed (exit {exc.returncode}). "
            f"model={model_path} cli={whisper_cli}"
        ) from exc
    finally:
        if cleanup_temp:
            input_for_whisper.unlink(missing_ok=True)

    txt_path = output_base.with_suffix(".txt")
    if not txt_path.is_file():
        raise RuntimeError(f"whisper-cli reported success but wrote no {txt_path}")

    srt_path = output_base.with_suffix(".srt") if want_srt else None
    if srt_path is not None and not srt_path.is_file():
        LOG.warning("Expected SRT output was not written: %s", srt_path)
        srt_path = None

    return TranscribeResult(audio=audio_file, txt=txt_path, srt=srt_path)
