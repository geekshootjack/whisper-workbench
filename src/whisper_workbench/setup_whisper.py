"""One-time per-machine setup: clone, build, and populate whisper.cpp.

Everything is installed under :func:`assets.install_dir` rather than next to
the source, so this keeps working when the tool is installed with
``uv tool install`` and survives ``uv tool upgrade``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from whisper_workbench import assets

WHISPER_CPP_REPO = "https://github.com/ggerganov/whisper.cpp.git"


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    try:
        subprocess.run(cmd, check=True, cwd=str(cwd) if cwd else None)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Required command not found: {cmd[0]}. Install it and ensure it is in PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Command failed (exit {exc.returncode}): {' '.join(cmd)}. "
            "See the output above for the root cause."
        ) from exc


def _load_cmake_cache(cache_path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not cache_path.is_file():
        return entries
    for raw in cache_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith(("//", "#")):
            continue
        key_with_type, sep, value = line.partition("=")
        if not sep or ":" not in key_with_type:
            continue
        key, _, _type = key_with_type.partition(":")
        entries[key] = value
    return entries


def _normalized(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(Path(path).expanduser().resolve(strict=False))))


def stale_cmake_cache_reason(source_dir: Path, build_dir: Path) -> str | None:
    """Return why the CMake cache is stale, or None when it is usable.

    A cache carried over from a different absolute path makes every
    subsequent build fail, so it has to be detected and cleared.
    """
    entries = _load_cmake_cache(build_dir / "CMakeCache.txt")
    if not entries:
        return None

    expected = {
        "CMAKE_HOME_DIRECTORY": source_dir,
        "CMAKE_CACHEFILE_DIR": build_dir,
    }
    mismatches = [
        f"{key} cached={entries[key]} expected={path}"
        for key, path in expected.items()
        if entries.get(key) and _normalized(entries[key]) != _normalized(path)
    ]
    return "; ".join(mismatches) if mismatches else None


def _prepare_build_dir(whisper_cpp_dir: Path) -> None:
    build_dir = whisper_cpp_dir / "build"
    reason = stale_cmake_cache_reason(whisper_cpp_dir, build_dir)
    if reason is None:
        return
    print(f"==> Stale CMake cache detected ({reason})")
    print(f"==> Removing {build_dir} and rebuilding")
    shutil.rmtree(build_dir)


def _download(script_stem: str, variant: str, models_dir: Path) -> None:
    if os.name == "nt":
        _run(["cmd", "/c", str(models_dir / f"{script_stem}.cmd"), variant], cwd=models_dir)
    else:
        _run([str(models_dir / f"{script_stem}.sh"), variant], cwd=models_dir)


def run_setup(model: str = assets.DEFAULT_MODEL, update: bool = False) -> int:
    """Clone/build whisper.cpp and download the model and VAD model."""
    missing = [tool for tool in ("git", "cmake") if not shutil.which(tool)]
    if missing:
        raise RuntimeError(
            f"Missing required command(s): {', '.join(missing)}. Install them first."
        )

    whisper_cpp_dir = assets.install_dir()
    whisper_cpp_dir.parent.mkdir(parents=True, exist_ok=True)

    print(f"==> Install directory: {whisper_cpp_dir}")
    print(f"==> Model: {model}")

    if not whisper_cpp_dir.exists():
        print("==> Cloning whisper.cpp")
        _run(["git", "clone", WHISPER_CPP_REPO, str(whisper_cpp_dir)])
    elif update:
        print("==> Updating whisper.cpp")
        _run(["git", "-C", str(whisper_cpp_dir), "pull"])
    else:
        print("==> whisper.cpp already present (pass --update to pull upstream)")

    print("==> Building whisper.cpp")
    _prepare_build_dir(whisper_cpp_dir)
    _run(["cmake", "-B", "build"], cwd=whisper_cpp_dir)
    _run(["cmake", "--build", "build", "--config", "Release"], cwd=whisper_cpp_dir)

    models_dir = whisper_cpp_dir / "models"

    model_path = models_dir / assets.model_file_name(model)
    if model_path.is_file():
        print(f"==> Model already present: {model_path.name}")
    else:
        print(f"==> Downloading {model_path.name}")
        _download("download-ggml-model", model, models_dir)

    vad_path = models_dir / assets.model_file_name(assets.VAD_MODEL)
    if vad_path.is_file():
        print(f"==> VAD model already present: {vad_path.name}")
    else:
        print(f"==> Downloading {vad_path.name}")
        _download("download-vad-model", assets.VAD_MODEL, models_dir)

    print("\n==> Setup complete\n")
    print(f"whisper-cli: {assets.find_whisper_cli()}")
    print(f"model:       {model_path}")
    print(f"VAD model:   {vad_path}")
    print("\nCheck the environment any time with: wb doctor")
    return 0
