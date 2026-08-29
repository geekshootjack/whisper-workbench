[English](architecture.md) | 中文

# 架构

一个 CLI `wb`，承载一条刻意拆成两段、可以分布在两台机器上的工作流：

```
audio ──▶ wb transcribe ──▶ meeting.txt ──▶ wb format ──▶ meeting.corrected.txt
          (whisper.cpp)     每行一段语音                  meeting.md
```

`wb transcribe` 不调用 LLM、不联网；`wb format` 不碰音频。两段之间只交接一个 `.txt` 文件。

## 模块

| 模块 | 职责 |
| --- | --- |
| `cli.py` | argparse 参数面与人类可读/JSON 输出。 |
| `assets.py` | 解析 whisper-cli、模型、VAD 模型路径的唯一入口。 |
| `setup_whisper.py` | `wb setup`：克隆、编译、下载到用户数据目录。 |
| `transcribe.py` | ffmpeg 归一化加 whisper-cli 调用。 |
| `llm.py` | 两个后处理阶段共用的子进程管道。 |
| `correct.py` | 阶段一。保持行结构的错误校正。 |
| `compose.py` | 阶段二。改写成正文。 |
| `pipeline.py` | `wb format` 的输出路径推导与阶段编排。 |

## 校正与改写

**校正**保持结构：N 行进、N 行出、顺序不变。模型返回的是*补丁*——只给想改的行、按 id 索引——所以模型输出混乱或被截断时，最多漏掉某处校正，不会丢行、并行或重排。相互独立的分块并发执行。

**改写**打破结构：识别分段既不是句子也不是段落。默认单次调用完成，因为一个话题的结论通常落在开头很远处，切开会把同一个话题写两遍。预算按字符数衡量——识别分段每行只有 8-16 个字符，行数说明不了 chunk 装了多少会议内容——60k 的默认值意味着切分几乎不会发生。真的发生时，分块串行执行，每块拿到上一块输出的尾部作为只读上下文，并记录一条警告。

输出保持话题在录音中出现的先后顺序——不重组、不加标题、没有摘要段。压缩是预期行为；丢话题不是，所以字符数骤降会记一条警告。

模型输出外面包着一层确定性守卫：

- 游离的 markdown 标题被降级、水平线被删除；LLM CLI 不会稳定遵守“不要标题”，而在代码里强制执行是免费的。
- 整篇文档在写出前统一归一化一次——分块边界不是句子边界。`autocorrect` 承担大部分工作；模型对中文标点的全半角不一致，所以这件事在代码里强制执行，而不是写进提示词。

autocorrect 不做的两件事由外围代码处理：

- **引号方向。** autocorrect 完全不碰引号。引号处理只改写*中文所在行上的成对引号*，此时方向无歧义；落单的引号不去猜，单引号只在包裹中文时才处理，英文撇号得以幸存。
- **引号后的标点。** autocorrect 只加宽*单词字符*后面的标点，所以 autocorrect 跑完时 `看看”,` 仍是半角；由后续一遍把它加宽，并删掉 autocorrect 在其后 CJK 前多插的空格——标点变成全角后那个空格是错的。

半角括号保持原样；autocorrect 的设计是对它们加空格而不是加宽。

## 分段

whisper.cpp 的 VAD 默认值按字幕调优，短 cue 在字幕里是优点；放到转录稿里就成了灾难：每个呼吸和犹豫处都切行，而逐行工作的校正拿到的两三个字的行给不了模型判断上下文。于是 VAD 重新调参：跨过犹豫停顿（`--vad-min-silence-duration-ms 700`），限制失控长段（`--vad-max-speech-duration-s 30`，与 whisper 自身窗口一致），避免切掉句首（`--vad-speech-pad-ms 200`）。

`--split-on-word` 已移除：它只在配合 `--max-len` 时生效，而 `--max-len` 保持 0，从字幕时代起它就是空操作。

## 失败行为

任何阶段都不允许丢转录稿。

- 校正分块失败时，先拆成更小的子块重试，再回退到原始行。
- 改写分块在所有可用后端上都失败时，回退为逐字输出输入行。
- 两个阶段都报告 `applied` / `partial` / `failed`，体现在 `--json` 输出和人类可读摘要中。
- 不在 `PATH` 上的后端在任何工作开始前就被过滤掉，请求一个未安装的 CLI 不会烧掉整轮分块处理。

## 资产解析

`assets.py` 按此顺序解析，`wb setup` 和 `wb transcribe` 都经过它，两边的默认值不会漂移：

1. `WHISPER_CLI_PATH` / `WHISPER_MODEL_PATH` / `WHISPER_VAD_MODEL_PATH`
2. `PATH` 上的 `whisper-cli`（覆盖 `brew install whisper-cpp`）
3. 用户数据目录——`~/.local/share/whisper-workbench/` 或 `%LOCALAPPDATA%\whisper-workbench\`——即 `wb setup` 的安装位置
4. `<repo>/vendor/whisper.cpp`，仅在从源码 checkout 运行时

装进用户数据目录而不是源码旁边，`uv tool install` 才可行：相对 `__file__` 的路径会把 git 克隆和几个 GB 的模型塞进 `site-packages`。
