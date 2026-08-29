"""Locating whisper.cpp assets: the CLI binary, the model, the VAD model.

This is the single place that knows where things live. ``wb setup`` installs
into :func:`install_dir`, and ``wb transcribe`` / ``wb doctor`` look there.
Keeping one resolver is what stops the setup and transcribe defaults from
drifting apart.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# large-v3 over the distilled turbo: this runs unattended on recorded audio,
# so accuracy on multi-speaker Chinese matters and the extra minutes do not.
DEFAULT_MODEL = "large-v3"
MODEL_CHOICES = ("large-v3", "large-v3-turbo")
VAD_MODEL = "silero-v5.1.2"

ENV_CLI = "WHISPER_CLI_PATH"
ENV_MODEL = "WHISPER_MODEL_PATH"
ENV_VAD_MODEL = "WHISPER_VAD_MODEL_PATH"


def model_file_name(variant: str) -> str:
    """Return the ggml file name for a model variant."""
    return f"ggml-{variant}.bin"


def user_data_dir() -> Path:
    """Return the per-user data directory for this tool."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / "whisper-workbench"

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "whisper-workbench"
    return Path.home() / ".local" / "share" / "whisper-workbench"


def install_dir() -> Path:
    """Return the directory ``wb setup`` clones and builds whisper.cpp into."""
    return user_data_dir() / "whisper.cpp"


def _repo_checkout_dir() -> Path | None:
    """Return the repo root when running from a git checkout, else None.

    Installed into a virtualenv this walks into ``site-packages`` and its
    parents, which is why the result is only trusted when it actually looks
    like this project's source tree.
    """
    root = Path(__file__).resolve().parents[2]
    if (root / "pyproject.toml").is_file() and (root / "src").is_dir():
        return root
    return None


def _cli_names() -> tuple[str, ...]:
    return ("whisper-cli.exe",) if os.name == "nt" else ("whisper-cli",)


def _cli_candidates(whisper_cpp_dir: Path) -> list[Path]:
    build_bin = whisper_cpp_dir / "build" / "bin"
    candidates: list[Path] = []
    for name in _cli_names():
        # MSVC writes into a per-config subdirectory; single-config
        # generators (Ninja, Makefiles) write straight into bin/.
        candidates.extend(
            [
                build_bin / "Release" / name,
                build_bin / "RelWithDebInfo" / name,
                build_bin / "Debug" / name,
                build_bin / name,
            ]
        )
    return candidates


def _search_roots() -> list[Path]:
    roots = [install_dir()]
    repo = _repo_checkout_dir()
    if repo is not None:
        roots.append(repo / "vendor" / "whisper.cpp")
    return roots


def _model_search_dirs() -> list[Path]:
    # user_data_dir()/models is where wb setup downloads; install_dir()/models
    # is the layout older setups created and still counts.
    dirs = [user_data_dir() / "models"]
    dirs.extend(root / "models" for root in _search_roots())
    repo = _repo_checkout_dir()
    if repo is not None:
        dirs.append(repo / "models")
    return dirs


def _from_env(var: str) -> Path | None:
    raw = os.environ.get(var)
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def find_whisper_cli() -> Path | None:
    """Return the whisper-cli binary path, or None when it is not installed."""
    env_path = _from_env(ENV_CLI)
    if env_path is not None:
        return env_path

    # A system install (e.g. `brew install whisper-cpp`) means `wb setup`
    # is never needed on that machine.
    for name in _cli_names():
        found = shutil.which(name)
        if found:
            return Path(found)

    for root in _search_roots():
        for candidate in _cli_candidates(root):
            if candidate.is_file():
                return candidate
    return None


def find_model(variant: str = DEFAULT_MODEL) -> Path | None:
    """Return the path to a whisper model, or None when it is missing."""
    env_path = _from_env(ENV_MODEL)
    if env_path is not None:
        return env_path

    file_name = model_file_name(variant)
    for models_dir in _model_search_dirs():
        candidate = models_dir / file_name
        if candidate.is_file():
            return candidate
    return None


def find_vad_model() -> Path | None:
    """Return the path to the VAD model, or None when it is missing."""
    env_path = _from_env(ENV_VAD_MODEL)
    if env_path is not None:
        return env_path

    names = (
        model_file_name(VAD_MODEL),
        "ggml-silero-v6.2.0.bin",
        "silero_vad.onnx",
    )
    for models_dir in _model_search_dirs():
        for name in names:
            candidate = models_dir / name
            if candidate.is_file():
                return candidate
    return None


def require_whisper_cli() -> Path:
    """Return the whisper-cli path or raise with a fixable message."""
    path = find_whisper_cli()
    if path is None:
        raise FileNotFoundError(
            "whisper-cli not found. Install whisper.cpp (macOS: `brew install "
            "whisper-cpp`; Windows: a release zip from "
            "github.com/ggml-org/whisper.cpp/releases), put it on PATH, or set "
            f"{ENV_CLI} to an existing binary."
        )
    if not path.is_file():
        raise FileNotFoundError(f"whisper-cli path does not exist: {path}")
    return path


def require_model(variant: str = DEFAULT_MODEL) -> Path:
    """Return the model path or raise with a fixable message."""
    path = find_model(variant)
    if path is None:
        raise FileNotFoundError(
            f"Whisper model '{variant}' not found. Run `wb setup --model {variant}`, "
            f"or set {ENV_MODEL} to an existing ggml model file."
        )
    if not path.is_file():
        raise FileNotFoundError(f"Whisper model path does not exist: {path}")
    return path


def require_vad_model() -> Path:
    """Return the VAD model path or raise with a fixable message."""
    path = find_vad_model()
    if path is None:
        raise FileNotFoundError(
            "VAD model not found. Run `wb setup`, pass --no-vad to skip voice "
            f"activity detection, or set {ENV_VAD_MODEL}."
        )
    if not path.is_file():
        raise FileNotFoundError(f"VAD model path does not exist: {path}")
    return path
