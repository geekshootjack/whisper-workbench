# whisper-workbench

[English](README.en.md) | 中文

把会议录音变成一份校正过、分好段的文档，用来喂给 agent 当上下文。

分两步，两步可以在不同机器上跑：

```
wb transcribe meeting.m4a     ->  meeting.txt              本地 whisper.cpp，不联网
wb format meeting.txt         ->  meeting.corrected.txt    LLM 按行校正识别错误
                                  meeting.md               LLM 改写成分段正文
```

两步之间只需要传 `meeting.txt` 这一个文件。

最终 `meeting.md` 按话题在录音中出现的先后顺序分段，没有标题层级和摘要段，论点、数据、决定和分歧保留；`meeting.corrected.txt` 留在磁盘上。

写出文件前，整篇会过一遍 [autocorrect](https://github.com/huacnlee/autocorrect)，统一全半角标点、补上中英文之间的空格，再把成对的直角引号换成弯角引号。

## 安装

```sh
uv tool install git+https://github.com/geekshootjack/whisper-workbench            # 跟随 main
uv tool install git+https://github.com/geekshootjack/whisper-workbench@v0.1.0     # 锁定版本
uv tool upgrade whisper-workbench
```

一次性使用：

```sh
uvx --from git+https://github.com/geekshootjack/whisper-workbench wb transcribe meeting.m4a
```

## 每台机器第一次使用

转录那台机器的前置要求：`ffmpeg` 和 `whisper-cli`（macOS 用 `brew install whisper-cpp`；Windows 从 whisper.cpp 的 GitHub releases 下载）。

```sh
wb setup      # 下载模型，每台机器跑一次
```
后处理那台机器需要 `claude` 或 `codex` 其中之一在 PATH 上。

不确定这台机器能跑哪一步：

```sh
wb doctor
```

## 常用

```sh
wb transcribe a.m4a b.m4a -o ./out      # 多个文件，指定输出目录
wb transcribe meeting.m4a --srt         # 顺带出一份字幕
wb transcribe meeting.m4a --no-vad      # 关掉静音跳过，保证时间轴连续

wb format meeting.txt -g glossary.txt   # 带专有名词表校正
wb format meeting.txt --from compose    # 复用已有校正稿，只重跑改写
wb format meeting.txt --backend claude  # 指定用哪个 LLM CLI
wb format meeting.txt --json            # 机器可读的结果路径与状态
```

完整参数看 `wb --help` 和 `wb <命令> --help`。

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `WHISPER_CLI_PATH` | 指定 whisper-cli 可执行文件 |
| `WHISPER_MODEL_PATH` | 指定 ggml 模型文件 |
| `WHISPER_VAD_MODEL_PATH` | 指定 VAD 模型文件 |

## 开发

```sh
git clone https://github.com/geekshootjack/whisper-workbench
cd whisper-workbench
uv sync --all-groups
uv run wb --help
uv run pytest
```

架构说明见 [docs/architecture.md](./docs/architecture.md)，协作流程见 [AGENTS.md](./AGENTS.md)。

## License

MIT
