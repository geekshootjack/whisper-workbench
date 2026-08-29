"""Stale CMake cache detection.

A build directory carried over from a different absolute path breaks every
later build, so setup has to notice and clear it.
"""

from __future__ import annotations

from pathlib import Path

from whisper_workbench import setup_whisper


def _write_cache(build_dir: Path, home: Path, cachefile_dir: Path) -> None:
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "CMakeCache.txt").write_text(
        "// comment line\n"
        "# another comment\n"
        f"CMAKE_HOME_DIRECTORY:INTERNAL={home}\n"
        f"CMAKE_CACHEFILE_DIR:INTERNAL={cachefile_dir}\n"
        "CMAKE_BUILD_TYPE:STRING=Release\n",
        encoding="utf-8",
    )


def test_no_cache_is_not_stale(tmp_path: Path) -> None:
    source = tmp_path / "whisper.cpp"
    source.mkdir()

    assert setup_whisper.stale_cmake_cache_reason(source, source / "build") is None


def test_matching_cache_is_not_stale(tmp_path: Path) -> None:
    source = tmp_path / "whisper.cpp"
    build = source / "build"
    _write_cache(build, source, build)

    assert setup_whisper.stale_cmake_cache_reason(source, build) is None


def test_cache_from_another_path_is_stale(tmp_path: Path) -> None:
    source = tmp_path / "whisper.cpp"
    build = source / "build"
    old = tmp_path / "elsewhere" / "whisper.cpp"
    _write_cache(build, old, old / "build")

    reason = setup_whisper.stale_cmake_cache_reason(source, build)

    assert reason is not None
    assert "CMAKE_HOME_DIRECTORY" in reason


def test_unparsable_cache_lines_do_not_crash(tmp_path: Path) -> None:
    source = tmp_path / "whisper.cpp"
    build = source / "build"
    build.mkdir(parents=True)
    (build / "CMakeCache.txt").write_text(
        "garbage without an equals sign\nNO_TYPE=value\n", encoding="utf-8"
    )

    assert setup_whisper.stale_cmake_cache_reason(source, build) is None
