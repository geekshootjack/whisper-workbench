"""Model download URLs and setup idempotency."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from whisper_workbench import assets, setup_whisper


def test_model_urls_cover_both_mirrors() -> None:
    urls = setup_whisper.model_urls("large-v3")

    assert urls == [
        "https://hf-mirror.com/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin",
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin",
    ]


def test_vad_urls_use_the_vad_repo() -> None:
    urls = setup_whisper.vad_model_urls()

    assert urls[0].startswith("https://hf-mirror.com/ggml-org/whisper-vad/resolve/main/")
    assert all(
        url.endswith(assets.model_file_name(assets.VAD_MODEL)) for url in urls
    )


def test_run_setup_skips_existing_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / assets.model_file_name(assets.DEFAULT_MODEL)).write_bytes(b"x")
    (models_dir / assets.model_file_name(assets.VAD_MODEL)).write_bytes(b"x")
    monkeypatch.setattr(assets, "user_data_dir", lambda: tmp_path)

    def fail(_cmd: list[str], *_args: object, **_kwargs: object) -> None:
        raise AssertionError("setup must not download when models exist")

    monkeypatch.setattr(setup_whisper.subprocess, "run", fail)

    assert setup_whisper.run_setup() == 0


def test_uninstall_removes_the_models_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "ggml-large-v3.bin").write_bytes(b"x")
    monkeypatch.setattr(assets, "user_data_dir", lambda: tmp_path)

    assert setup_whisper.run_setup(uninstall=True) == 0
    assert not models_dir.exists()


def test_uninstall_is_a_noop_without_the_models_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(assets, "user_data_dir", lambda: tmp_path)

    assert setup_whisper.run_setup(uninstall=True) == 0


def test_curl_failure_falls_back_to_the_mirror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_run(cmd: list[str], *_args: object, **_kwargs: object) -> subprocess.CompletedProcess:
        calls.append(cmd[-1])
        code = 0 if len(calls) == 2 else 1
        if code == 0:
            output = Path(cmd[cmd.index("--output") + 1])
            output.write_bytes(b"x")
        return subprocess.CompletedProcess(cmd, code)

    monkeypatch.setattr(setup_whisper.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(setup_whisper.subprocess, "run", fake_run)
    destination = tmp_path / "m.bin"

    setup_whisper._curl(setup_whisper.model_urls("large-v3"), destination)

    hosts = [url.split("//", 1)[1].split("/", 1)[0] for url in calls]
    assert hosts == ["hf-mirror.com", "huggingface.co"]
    assert destination.is_file()


def test_every_mirror_failing_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_whisper.shutil, "which", lambda name: "curl")
    monkeypatch.setattr(
        setup_whisper.subprocess,
        "run",
        lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 22),
    )

    with pytest.raises(RuntimeError, match="every mirror"):
        setup_whisper._curl(["https://a/x.bin", "https://b/x.bin"], tmp_path / "x.bin")
