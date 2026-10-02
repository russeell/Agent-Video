# Agent Video

**Let your agent watch videos.**

[English](README.md) | **简体中文**

给 Coding Agent 一个视频链接、本地文件或主题。Agent Video 按需获取文字稿、画面、音频、视频文件和相关信息，Agent 阅读后回答问题或交付文件，后续追问直接复用已有材料。

适用于 Codex、Claude Code 等支持 Agent Skills 的宿主。平台解析与下载由本项目实现，无需安装其他视频下载项目。

## 快速开始

需要 **Python 3.11+**。下载和媒体处理需要将 **FFmpeg、ffprobe** 加入 `PATH`；语音转录可选。

```bash
git clone https://github.com/russeell/Agent-Video.git
cd Agent-Video
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

在项目目录为使用的宿主注册 Skill：

```bash
# Codex
mkdir -p "$HOME/.agents/skills"
ln -s "$(pwd -P)" "$HOME/.agents/skills/agent-video"

# Claude Code
mkdir -p "$HOME/.claude/skills"
ln -s "$(pwd -P)" "$HOME/.claude/skills/agent-video"
```

链接的是**完整项目目录**，包含 `.venv`，安装后保留原位置。已有 `agent-video` 链接时先检查指向。开启新会话；仍未发现 Skill 时重启宿主。仅安装 Python 包不会自动注册 Skill。

<details>
<summary>Windows 安装</summary>

克隆项目后在 PowerShell 运行。以下注册 Codex；Claude Code 将 `.agents` 替换为 `.claude`。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
New-Item -ItemType Directory -Force "$env:USERPROFILE\.agents\skills" | Out-Null
New-Item -ItemType Junction -Path "$env:USERPROFILE\.agents\skills\agent-video" -Target (Get-Location).Path
```

后续调用使用 `.venv\Scripts\python.exe`。已实测 macOS；Windows、Linux 尚未验收。

</details>

## 使用

直接向 Agent 提问：

- “这个视频讲了什么？`<链接>`”
- “02:10 在说什么？把那里的画面截清楚。”
- “提取带时间戳的文字稿。”
- “下载最清晰版本，再保存音频。”
- “找一个中文、10分钟以内、有实际演示的 FFmpeg 教程。”

寻找视频时，宿主使用已有搜索工具，Agent Video 按需读取候选，验证内容。搜索优先用户指定平台，其次当前任务的平台，否则默认 YouTube；只有明确要求才扩大到其他平台。

自动匹配由宿主决定。未触发时可明确说“使用 Agent Video”，在 Codex 中选择 `$agent-video`，或在 Claude Code 中调用 `/agent-video`。

<details>
<summary>直接调用脚本</summary>

```bash
# 优先字幕；没有可用字幕时使用已配置的本地 ASR
.venv/bin/python scripts/watch.py "<视频链接或本地文件>" --get transcript

# 获取清晰画面或下载素材
.venv/bin/python scripts/watch.py "<视频链接>" --get frames --at 02:10 --width 0 --quality source
.venv/bin/python scripts/watch.py "<视频链接>" --get video,audio

# 使用前一次返回的 manifest 继续获取
.venv/bin/python scripts/watch.py --evidence "/path/to/manifest.json" --get video
```

`--get` 支持 `info,transcript,frames,audio,video`，默认 `transcript`。语言、区间、质量、分 P 和 Cookie 文件等参数见 `--help`。仅使用显式提供的 Cookie 文件，不自动读取浏览器凭据。

默认结果保存在 `.agent-video/`。JSON 返回材料路径、追问用的 manifest 和诊断；部分失败时仍交付成功材料。退出码：`0` 完成，`2` 部分成功，`1` 失败，`64` 参数错误。

</details>

文字稿优先使用字幕；语音转录需要下方的可选配置。视觉问题按需抽帧，也可读取无声录屏。画面文字与讲话文字稿分别表达，项目未内置 OCR，抽样读取不代表完整看过视频。

视频默认下载当前可取得的最高质量。时间相对原视频，已有材料优先复用，用户原文件保持只读。

## 来源支持

当前为早期 MVP；以下是少量真实样本的验证范围，不保证平台所有视频均可获取。

| 来源 | 已验证范围 |
|---|---|
| 本地文件 | 字幕、画面、音视频导出、区间处理和复用 |
| YouTube | 公开视频与 Shorts：字幕、含音轨的1080p视频、画面和复用 |
| Bilibili | 公开视频与指定分 P：1080p下载、可访问字幕、音频/ASR和复用 |
| TikTok | 两个公开样本：字幕或本地ASR、完整音视频、画面和复用 |
| 抖音 | 实验路径，当前受签名挑战阻塞；内容和下载尚未通过真实验收 |
| 腾讯视频 | 实验路径，一个公开、非DRM样本下载与读取通过 |

获取受作品、地区和平台变化影响。YouTube 的其他签名、token、登录路径尚未实现。未知网站、普通网页和媒体直链不支持；已下载文件可作为本地输入。不处理直播或 DRM。

## 可选语音转录

<details>
<summary>准备本地 faster-whisper 模型</summary>

安装可选依赖：

```bash
.venv/bin/python -m pip install -e '.[asr]'
```

明确下载模型，保存在项目之外：

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import truststore
truststore.inject_into_ssl()
from huggingface_hub import snapshot_download
snapshot_download("Systran/faster-whisper-small", token=False,
    local_dir=Path.home() / ".cache/agent-video/models/faster-whisper-small",
    allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*"])
PY
```

在调用 Agent Video 的进程中设置模型路径：

```bash
export AGENT_VIDEO_ASR_MODEL="$HOME/.cache/agent-video/models/faster-whisper-small"
```

另一个终端中的 `export` 不会更新已运行的桌面 Agent。可告诉 Agent 模型目录，由它在调用时传入变量。Windows 使用 `$env:AGENT_VIDEO_ASR_MODEL`，脚本使用 `.venv\Scripts\python.exe`。

默认 CPU/int8，普通调用不下载模型。ASR 可能有错字，字幕也可能没有覆盖全片；未配置 ASR 时仍可获取其他材料。

</details>

## 开发

```bash
.venv/bin/python -m unittest discover -s tests -v
```

默认回归使用临时媒体和本地 HTTP 服务；线上样本、真实 ASR 分别验证。产品以包含 Skill 的完整源码目录分发，仅安装 wheel 不会完成 Skill 注册。

## 许可与参考

[MIT](LICENSE)。获取逻辑参考 [yt-dlp](https://github.com/yt-dlp/yt-dlp)、[youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)、[BBDownT](https://github.com/LOVAHE/BBDownT) 和 [F2](https://github.com/Johnserf-Seed/f2)；设计参考 [claude-video](https://github.com/bradautomates/claude-video)、[claude-real-video](https://github.com/HUANGCHIHHUNGLeo/claude-real-video) 和 [Video-Browser](https://github.com/chrisx599/Video-Browser)。必要的第三方许可与署名保留在源码中。
