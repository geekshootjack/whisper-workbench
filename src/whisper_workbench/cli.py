"""The ``wb`` command line.

Installed as a tool, this help text is the only documentation an agent gets —
it is working in the directory that holds the audio, not in this repo. So the
top-level help spells out the whole two-step workflow rather than just listing
subcommand names.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import socket
import sys
from pathlib import Path

from whisper_workbench import __version__, assets, compose, llm, pipeline, transcribe
from whisper_workbench.setup_whisper import run_setup

LOG = logging.getLogger("wb")

DESCRIPTION = "会议录音转录与整理：音频 -> 逐行转录 -> 分段正文文档。"

EPILOG = """\
分两步，两步可以在不同机器上跑：

  第一步 转录（需要 whisper.cpp，不联网、不调用 LLM）
      wb transcribe meeting.m4a          ->  meeting.txt

  第二步 整理（需要 claude 或 codex 在 PATH 上）
      wb format meeting.txt              ->  meeting.corrected.txt   校正后的逐行转录
                                             meeting.md              分段正文文档

两步之间只需要传 meeting.txt 这一个文件。

第一次在一台机器上使用，先跑 `wb setup`（只需一次）。
不确定这台机器能跑哪一步时，跑 `wb doctor`。
"""


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _ssh_host() -> str:
    """Return the name the other machine can reach this one by.

    The short lowercase hostname is what an ssh config alias is normally
    named after. ``WB_SSH_HOST`` overrides it when that guess is wrong.
    """
    override = os.environ.get("WB_SSH_HOST")
    if override:
        return override
    return socket.gethostname().split(".")[0].lower()


def _scp_source(path: Path) -> str:
    """Build the remote half of an scp command pointing at ``path`` here."""
    text = path.as_posix()
    spec = f"{_ssh_host()}:{text}"
    if any(char in text for char in " '\"()"):
        escaped = text.replace("\\", "\\\\").replace(" ", "\\ ")
        spec = f"'{_ssh_host()}:{escaped}'"
    return spec


def _repo_relative(path: Path) -> Path | None:
    """Return ``path`` relative to its enclosing git work tree, if any."""
    for parent in path.parents:
        if (parent / ".git").exists():
            return path.relative_to(parent)
    return None


def _print_next_steps(txt_paths: list[Path]) -> None:
    joined = " ".join(str(path) for path in txt_paths)
    print(f"\n下一步：wb format {joined}")

    # Mirror the layout on the other machine: copying into the same
    # repo-relative directory keeps the follow-up path valid there.
    relatives = [_repo_relative(path) for path in txt_paths]
    if any(relative is not None for relative in relatives):
        print("\n在另一台机器上处理（在仓库根目录运行）：")
    else:
        print("\n在另一台机器上处理，先拉过去：")

    targets: list[str] = []
    for path, relative in zip(txt_paths, relatives):
        if relative is None:
            destination = "."
            targets.append(path.name)
        else:
            parent = relative.parent.as_posix()
            destination = "." if parent == "." else f"{parent}/"
            targets.append(relative.as_posix())
        print(f"  scp {_scp_source(path)} {destination}")

    print(f"  wb format {' '.join(targets)}")


def _read_text_file(path: Path, label: str) -> str:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    text = resolved.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"{label} is empty: {resolved}")
    return text


def cmd_setup(args: argparse.Namespace) -> int:
    return run_setup(model=args.model, update=args.update)


def cmd_transcribe(args: argparse.Namespace) -> int:
    if args.model_path:
        model_path = Path(args.model_path).expanduser().resolve()
        if not model_path.is_file():
            raise FileNotFoundError(f"Model file not found: {model_path}")
    else:
        model_path = assets.require_model(args.model)

    initial_prompt = (
        _read_text_file(Path(args.prompt_file), "Prompt file").strip()
        if args.prompt_file
        else None
    )

    results: list[transcribe.TranscribeResult] = []
    for audio in args.audio:
        audio_path = Path(audio).expanduser().resolve()
        output_dir = (
            Path(args.output_dir).expanduser().resolve()
            if args.output_dir
            else audio_path.parent
        )
        results.append(
            transcribe.transcribe_file(
                audio_path,
                output_dir,
                lang=args.lang,
                model_path=model_path,
                use_vad=not args.no_vad,
                initial_prompt=initial_prompt,
                want_srt=args.srt,
            )
        )

    if args.json:
        _print_json(
            {
                "command": "transcribe",
                "results": [
                    {
                        "audio": str(r.audio),
                        "txt": str(r.txt),
                        "srt": str(r.srt) if r.srt else None,
                    }
                    for r in results
                ],
            }
        )
        return 0

    for result in results:
        line_count = len(result.txt.read_text(encoding="utf-8").splitlines())
        print(f"✓ {result.txt}  ({line_count} 行)")
        if result.srt:
            print(f"  {result.srt}")
    _print_next_steps([result.txt for result in results])
    return 0


def cmd_format(args: argparse.Namespace) -> int:
    glossary = (
        _read_text_file(Path(args.glossary), "Glossary file") if args.glossary else None
    )

    result = pipeline.format_transcript(
        Path(args.txt),
        output=Path(args.output) if args.output else None,
        glossary=glossary,
        backend=args.backend,
        model=args.model,
        timeout_sec=args.timeout,
        chunk_lines=args.chunk_lines,
        start_stage=args.start_stage,
    )

    if args.json:
        _print_json(
            {
                "command": "format",
                "source": str(result.source),
                "corrected": str(result.corrected),
                "document": str(result.document),
                "correct_status": result.correct_status,
                "compose_status": result.compose_status,
            }
        )
        return 0

    if args.stdout:
        sys.stdout.write(result.document.read_text(encoding="utf-8"))
        return 0

    print(f"✓ {result.document}")
    print(f"  {result.corrected}  (校正后的逐行转录)")
    if result.correct_status and result.correct_status != "applied":
        print(f"  注意：校正状态为 {result.correct_status}")
    if result.compose_status != "applied":
        print(f"  注意：改写状态为 {result.compose_status}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    ffmpeg = shutil.which("ffmpeg")
    whisper_cli = assets.find_whisper_cli()
    # Report every variant, not just the default: a machine set up before the
    # default changed still has a perfectly usable model.
    models = {variant: assets.find_model(variant) for variant in assets.MODEL_CHOICES}
    vad_model = assets.find_vad_model()
    backends = llm.available_backends()

    can_transcribe = bool(whisper_cli and any(models.values()))
    can_format = bool(backends)

    if args.json:
        _print_json(
            {
                "command": "doctor",
                "ffmpeg": ffmpeg,
                "whisper_cli": str(whisper_cli) if whisper_cli else None,
                "models": {
                    variant: str(path) if path else None
                    for variant, path in models.items()
                },
                "vad_model": str(vad_model) if vad_model else None,
                "llm_backends": backends,
                "install_dir": str(assets.install_dir()),
                "can_transcribe": can_transcribe,
                "can_format": can_format,
            }
        )
    else:
        def status(value: object) -> str:
            return str(value) if value else "缺失"

        print(f"ffmpeg       {status(ffmpeg)}")
        print(f"whisper-cli  {status(whisper_cli)}")
        for variant, path in models.items():
            default_mark = " (默认)" if variant == assets.DEFAULT_MODEL else ""
            print(f"模型 {variant}{default_mark}  {status(path)}")
        print(f"VAD 模型      {status(vad_model)}")
        print(f"LLM CLI      {', '.join(backends) if backends else '缺失'}")
        print(f"安装目录      {assets.install_dir()}")
        print()
        print(f"wb transcribe  {'可用' if can_transcribe else '不可用 —— 跑 wb setup'}")
        if can_transcribe and models[assets.DEFAULT_MODEL] is None:
            usable = next(v for v, p in models.items() if p)
            print(f"               默认模型不在，转录时加 -m {usable}")
        print(
            f"wb format      "
            f"{'可用' if can_format else '不可用 —— 需要 claude 或 codex 在 PATH 上'}"
        )

    return 0 if (can_transcribe or can_format) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wb",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    setup_parser = subparsers.add_parser(
        "setup",
        help="下载并编译 whisper.cpp 和模型（每台机器跑一次）",
        description="下载并编译 whisper.cpp 和模型。装到用户数据目录，每台机器跑一次。",
    )
    setup_parser.add_argument(
        "-m",
        "--model",
        choices=assets.MODEL_CHOICES,
        default=assets.DEFAULT_MODEL,
        help=f"下载哪个 whisper 模型（默认 {assets.DEFAULT_MODEL}）",
    )
    setup_parser.add_argument(
        "--update",
        action="store_true",
        help="拉取上游 whisper.cpp 的最新代码并重新编译（默认不拉，重复跑是幂等的）",
    )
    setup_parser.set_defaults(func=cmd_setup)

    transcribe_parser = subparsers.add_parser(
        "transcribe",
        help="本地 whisper.cpp 转录音频，输出逐行 txt",
        description="本地 whisper.cpp 转录音频，输出逐行 txt。不联网、不调用 LLM。",
    )
    transcribe_parser.add_argument("audio", nargs="+", help="音频或视频文件（可多个）")
    transcribe_parser.add_argument(
        "-o",
        "--output-dir",
        help="输出目录（默认写在输入文件旁边）",
    )
    transcribe_parser.add_argument("-l", "--lang", default="zh", help="语言代码（默认 zh）")
    transcribe_parser.add_argument(
        "-m",
        "--model",
        choices=assets.MODEL_CHOICES,
        default=assets.DEFAULT_MODEL,
        help=f"whisper 模型（默认 {assets.DEFAULT_MODEL}）",
    )
    transcribe_parser.add_argument("--model-path", help="直接指定一个 ggml 模型文件")
    transcribe_parser.add_argument(
        "--prompt-file",
        help="UTF-8 文本文件，内容作为 whisper 的 initial prompt（提示专有名词、术语）",
    )
    transcribe_parser.add_argument("--srt", action="store_true", help="同时输出一份 .srt 字幕")
    transcribe_parser.add_argument(
        "--no-vad",
        action="store_true",
        help="关闭语音活动检测（VAD 会跳过静音段，关掉可保证时间轴连续）",
    )
    transcribe_parser.add_argument("--json", action="store_true", help="以 JSON 输出结果路径")
    transcribe_parser.set_defaults(func=cmd_transcribe)

    format_parser = subparsers.add_parser(
        "format",
        help="LLM 校正转录稿，再改写成分段正文文档",
        description=(
            "两趟 LLM 处理：先按行校正识别错误，再改写成分段正文。"
            "改写是整理不是摘要，实质内容全部保留。"
        ),
    )
    format_parser.add_argument("txt", help="wb transcribe 产出的逐行 txt")
    format_parser.add_argument(
        "-o", "--output", help="最终文档路径（默认 <输入名>.md）"
    )
    format_parser.add_argument(
        "-g", "--glossary", help="专有名词表，一行一个，用于校正阶段"
    )
    format_parser.add_argument(
        "--backend",
        choices=llm.BACKENDS,
        default=llm.DEFAULT_BACKEND,
        help=f"使用哪个 LLM CLI（默认 {llm.DEFAULT_BACKEND}，失败时自动换用其它）",
    )
    format_parser.add_argument("--model", help="传给该 LLM CLI 的模型名")
    format_parser.add_argument(
        "--timeout",
        type=int,
        default=llm.DEFAULT_TIMEOUT_SEC,
        help=f"单次 LLM 请求超时秒数（默认 {llm.DEFAULT_TIMEOUT_SEC}）",
    )
    format_parser.add_argument(
        "--from",
        dest="start_stage",
        choices=pipeline.STAGES,
        default="correct",
        help="从哪一步开始。compose 会复用已有的 .corrected.txt，跳过校正",
    )
    format_parser.add_argument(
        "--chunk-lines",
        type=int,
        default=compose.CHUNK_LINES,
        help=f"改写阶段每块多少行（默认 {compose.CHUNK_LINES}）",
    )
    output_group = format_parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--stdout", action="store_true", help="把最终文档打到标准输出（文件照常写）"
    )
    output_group.add_argument("--json", action="store_true", help="以 JSON 输出结果路径与状态")
    format_parser.set_defaults(func=cmd_format)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="检查这台机器能跑哪一步",
        description="检查 ffmpeg、whisper.cpp、模型和 LLM CLI 是否就位。",
    )
    doctor_parser.add_argument("--json", action="store_true", help="以 JSON 输出检查结果")
    doctor_parser.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(asctime)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError, PermissionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
