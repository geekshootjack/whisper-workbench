"""Download the whisper models that ``wb transcribe`` needs.

whisper.cpp itself is expected to come from the system — ``brew install
whisper-cpp``, an official release zip, or ``WHISPER_CLI_PATH`` — so setup
only fetches the ggml model and the VAD model into the user data dir.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from whisper_workbench import assets

# huggingface.co first; hf-mirror.com is a path-identical mirror of it, used
# as the fallback where HF is slow or unreachable.
HOSTS = ("https://huggingface.co", "https://hf-mirror.com")
MODEL_REPO = "ggerganov/whisper.cpp"
VAD_REPO = "ggml-org/whisper-vad"


def model_urls(variant: str) -> list[str]:
    """Return the download URLs for a ggml model, mirrors last."""
    path = f"{MODEL_REPO}/resolve/main/{assets.model_file_name(variant)}"
    return [f"{host}/{path}" for host in HOSTS]


def vad_model_urls() -> list[str]:
    """Return the download URLs for the VAD model, mirrors last."""
    path = f"{VAD_REPO}/resolve/main/{assets.model_file_name(assets.VAD_MODEL)}"
    return [f"{host}/{path}" for host in HOSTS]


def _curl(urls: list[str], destination: Path) -> None:
    """Download once per URL until one succeeds, resuming the partial file."""
    curl = shutil.which("curl")
    if curl is None:
        raise RuntimeError(
            "curl not found. Install curl, or download the model manually to "
            f"{destination}."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    failed: list[str] = []
    for url in urls:
        result = subprocess.run(
            [
                curl,
                "-L",
                "--fail",
                "--retry",
                "3",
                "--retry-delay",
                "2",
                "-C",
                "-",
                "--output",
                str(partial),
                url,
            ]
        )
        if result.returncode == 0:
            partial.replace(destination)
            return
        failed.append(url)
    raise RuntimeError(
        "Download failed from every mirror (" + "; ".join(failed) + "). "
        f"The partial file is kept at {partial}; rerun `wb setup` to resume."
    )


def _fetch(urls: list[str], destination: Path, label: str) -> None:
    if destination.is_file():
        print(f"==> {label} already present: {destination.name}")
        return
    print(f"==> Downloading {label}: {destination.name}")
    _curl(urls, destination)


def run_setup(model: str = assets.DEFAULT_MODEL) -> int:
    """Download the ggml model and the VAD model into the user data dir."""
    models_dir = assets.user_data_dir() / "models"
    model_path = models_dir / assets.model_file_name(model)
    vad_path = models_dir / assets.model_file_name(assets.VAD_MODEL)

    print(f"==> Models directory: {models_dir}")
    print(f"==> Model: {model}")
    _fetch(model_urls(model), model_path, "model")
    _fetch(vad_model_urls(), vad_path, "VAD model")

    print("\n==> Setup complete\n")
    print(f"model:       {model_path}")
    print(f"VAD model:   {vad_path}")
    if assets.find_whisper_cli() is None:
        print(
            "\nwhisper-cli 未找到：wb setup 只下载模型，转录还需要 whisper.cpp。"
            "\n  macOS:   brew install whisper-cpp"
            "\n  Windows: 从 github.com/ggml-org/whisper.cpp/releases 下载预编译包，"
            "把 whisper-cli.exe 放进 PATH（或设 WHISPER_CLI_PATH）"
        )
    print("\nCheck the environment any time with: wb doctor")
    return 0
