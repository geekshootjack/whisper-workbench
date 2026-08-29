"""Asset resolution.

The setup and transcribe sides must agree on the default model name — they
disagreed before this refactor, so a default setup left a default transcribe
unable to find its model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from whisper_workbench import assets


def test_default_model_is_one_of_the_offered_choices() -> None:
    assert assets.DEFAULT_MODEL in assets.MODEL_CHOICES


def test_model_file_name_matches_the_ggml_convention() -> None:
    assert assets.model_file_name("large-v3-turbo") == "ggml-large-v3-turbo.bin"


def test_install_dir_lives_under_the_user_data_dir() -> None:
    assert assets.install_dir().parent == assets.user_data_dir()


def test_env_override_wins_for_the_cli(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "whisper-cli"
    target.write_text("", encoding="utf-8")
    monkeypatch.setenv(assets.ENV_CLI, str(target))

    assert assets.find_whisper_cli() == target.resolve()


def test_env_override_wins_for_the_model(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "ggml-custom.bin"
    target.write_text("", encoding="utf-8")
    monkeypatch.setenv(assets.ENV_MODEL, str(target))

    assert assets.find_model() == target.resolve()


def test_env_override_wins_for_the_vad_model(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "vad.bin"
    target.write_text("", encoding="utf-8")
    monkeypatch.setenv(assets.ENV_VAD_MODEL, str(target))

    assert assets.find_vad_model() == target.resolve()


def test_require_model_names_the_fix_in_its_error(monkeypatch) -> None:
    monkeypatch.delenv(assets.ENV_MODEL, raising=False)
    monkeypatch.setattr(assets, "_model_search_dirs", list)

    with pytest.raises(FileNotFoundError, match="wb setup"):
        assets.require_model()


def test_require_whisper_cli_names_the_fix_in_its_error(monkeypatch) -> None:
    monkeypatch.setattr(assets, "find_whisper_cli", lambda: None)

    with pytest.raises(FileNotFoundError, match="brew install whisper-cpp"):
        assets.require_whisper_cli()


def test_setup_target_dir_is_searched_for_models(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.delenv(assets.ENV_MODEL, raising=False)
    monkeypatch.setattr(assets, "user_data_dir", lambda: tmp_path)
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True)
    model = models_dir / assets.model_file_name(assets.DEFAULT_MODEL)
    model.write_bytes(b"x")

    assert assets.find_model() == model


def test_repo_checkout_dir_is_only_trusted_for_a_real_source_tree() -> None:
    repo = assets._repo_checkout_dir()

    # Running from this checkout it resolves; installed into site-packages it
    # must be None rather than pointing at the virtualenv.
    if repo is not None:
        assert (repo / "pyproject.toml").is_file()
        assert (repo / "src" / "whisper_workbench").is_dir()
