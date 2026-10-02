# Agent Video

**Let your agent watch videos.**

给 Agent 一个视频链接或本地文件，让它按问题获取文字、画面、音频、视频和信息。所有材料保存在同一个结果目录，方便继续追问和直接交付文件。

平台解析与下载由本项目实现，不需要安装 yt-dlp、F2 或 BBDownT。FFmpeg / ffprobe 用于底层媒体处理；本地语音转录可选。

> 当前为最小可用的 v0.1 MVP。优先本地文件、通用公开媒体与已验证的 B 站路径；腾讯视频及其他平台按样本标记实验支持。

## 安装

需要 Python 3.11+。完整安装包含 Python 环境和宿主 Skill 注册。以下命令在下载后的项目根目录运行，适用于 macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

将 FFmpeg 和 ffprobe 加入 PATH。媒体获取、合并、抽帧和音频提取按需使用它们；只读取平台信息或字幕通常不需要解码器。

然后按使用的宿主注册产品 Skill；两者都使用时分别执行：

```bash
# Codex
mkdir -p "$HOME/.agents/skills"
ln -s "$(pwd -P)" "$HOME/.agents/skills/agent-video"

# Claude Code
mkdir -p "$HOME/.claude/skills"
ln -s "$(pwd -P)" "$HOME/.claude/skills/agent-video"
```

链接的是完整项目目录，包含 [SKILL.md](SKILL.md)、README、脚本和 `.venv`，只复制 SKILL.md 无法运行。保留项目原位置；已有 `agent-video` 时先检查它的指向，不重复创建或覆盖其他安装。更新同一项目目录后链接继续有效；移动目录后需要重建链接，并在新位置重新创建虚拟环境。

[Codex 官方文档](https://learn.chatgpt.com/docs/build-skills)和 [Claude Code 官方文档](https://code.claude.com/docs/en/skills)说明了目录发现与自动匹配方式。安装后开始新一轮对话；若 Skill 尚未出现，重启宿主。在 Codex 的 Skill 列表或 Claude Code 的 `/agent-video` 菜单中确认它可用。

Windows 使用 PowerShell 在项目根目录创建环境，并用目录联接注册；下面以 Codex 为例，Claude Code 将 `.agents` 替换为 `.claude`：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
New-Item -ItemType Directory -Force "$env:USERPROFILE\.agents\skills" | Out-Null
New-Item -ItemType Junction -Path "$env:USERPROFILE\.agents\skills\agent-video" -Target (Get-Location).Path
```

Windows 后续调用使用 `.venv\Scripts\python.exe`。其他宿主支持 Agent Skills 时，将完整项目放入它规定的 Skill 目录，并按同样方式创建环境。当前分发以源码目录为单位；仅 `pip install` 不会自动注册 Skill。本机开发 Skill `agent-video-dev` 不属于产品安装内容。

完成后可从其他工作目录检查入口；将路径替换为实际安装位置：

```bash
"$HOME/.agents/skills/agent-video/.venv/bin/python" "$HOME/.agents/skills/agent-video/scripts/watch.py" --help
```

卸载时移除宿主的 `agent-video` 目录链接即可；保留项目和结果文件。

## 使用

Skill 可用后，直接向 Agent 提问：“这个视频讲了什么”“02:10 在说什么”“提取视频文字”“下载最清晰版本”或“保存刚才的视频”，并提供链接、文件或当前视频的上下文。无需每次指定项目名称；Agent 根据请求选择材料，调用脚本后读取证据、回答或交付文件。

自动匹配由宿主 Agent 决定；未触发时可明确说“使用 Agent Video”，或在 Codex 中提及 `$agent-video`、在 Claude Code 中调用 `/agent-video`。安装 Skill 不会改变网站支持范围或宿主执行权限。

以下为脚本直接调用示例：

```bash
# 文字稿，附带可取得的视频信息
.venv/bin/python scripts/watch.py "/path/to/video.mp4"

# 看画面、取信息或直接拿文件
.venv/bin/python scripts/watch.py "<video-url>" --get frames --max-frames 6
.venv/bin/python scripts/watch.py "<video-url>" --get info
.venv/bin/python scripts/watch.py "<video-url>" --get video,audio

# 用返回的 manifest 路径继续补取
.venv/bin/python scripts/watch.py --evidence "/path/to/manifest.json" --get frames --start 01:20 --end 01:35
.venv/bin/python scripts/watch.py --evidence "/path/to/manifest.json" --get frames --at 01:23 --width 1600
.venv/bin/python scripts/watch.py --evidence "/path/to/manifest.json" --get video
```

`--get` 支持 `info,transcript,frames,audio,video` 的组合，默认 `transcript`。没有字幕时仅在 ASR 已配置后转录；程序不自动改成抽帧，Agent 根据问题决定下一步。完整参数见 `--help`。

默认结果保存在当前目录 `.agent-video/`。stdout 是短 JSON，包含状态、manifest 和材料路径；长文字、图片和媒体都在文件里。已有材料优先复用，只有缺少或不满足要求时才补取。

- 文字稿来自字幕或语音转录；简介、弹幕和抽样硬字幕不会冒充完整文字稿。录屏正文可由 Agent 读取画面并单独保存整理稿；项目未内置 OCR 引擎。
- 帧和文字时间相对原视频，帧同时记录请求和实际时间。
- `--get video` 默认选择当前可取得的最高质量，与 `--quality source` 一致，不再默认限制1080p。显式 `--quality 1080p` 可限制下载档位；仅抽帧时 `auto` 仍按目标尺寸选择。最高可取得质量不代表上传原始母版。需要读小字可用 `--width 0 --quality source`。
- 平台声明档位与实际可取得格式分别记录；画面不足时提示实际尺寸，复用当前上限，不反复下载相同低清源。显式提供新的 Cookie 或更高质量要求时可重新检查。
- 先看画面再保存时，已有完整、最高质量的视频轨就只补取缺少的音轨并无损合并；再次保存直接返回完整文件。
- B 站一次取一个分 P，默认 P1；可使用 URL 的 `p` 或 `--part`，继续 evidence 时仍是同一部分。
- 用户原文件只读；结果目录由用户决定保留或删除，同一结果目录串行调用。
- 临时网络故障、下载途中断流或长度不足时最多尝试三次；HLS 只重试当前片段。完整下载后才交付，失败不覆盖已有文件。
- Cookie 仅接受显式 `--cookies` 文件，不读取浏览器凭据；不要提交凭据和运行结果。

退出码：`0` 请求完成，`2` 部分成功，`1` 无可用材料，`64` 参数错误。部分成功时先使用已有材料，并查看 `diagnostics` 的原因与下一步。

## 可选语音转录

```bash
.venv/bin/python -m pip install -e '.[asr]'
```

首次使用时明确下载一个模型，例如多语言 small（约 484 MB，保存在项目外）：

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

让调用脚本的进程使用这个模型目录：

```bash
export AGENT_VIDEO_ASR_MODEL="$HOME/.cache/agent-video/models/faster-whisper-small"
```

已准备其他 faster-whisper 模型时可直接使用它的绝对路径。默认 CPU / int8；普通读取不会下载模型，区间转录只处理目标音频段。未配置时仍可取得信息、字幕、画面和媒体。

在单独终端 `export` 不会更新已经运行的 Agent 桌面进程；可把模型目录告诉 Agent，由它在调用脚本时传入 `AGENT_VIDEO_ASR_MODEL`。可选依赖已限制 PyAV 版本，避免 faster-whisper 1.2.1 与 PyAV 19 的已知不兼容。

## 验证与限制

2026-10-03 在 macOS、Python 3.12、FFmpeg 8.0.1 验证：

| 来源 / 能力 | 实际结果 |
|---|---|
| 本地文件 | 信息、同名字幕、定点 / 区间帧、音视频导出和跨轮复用通过 |
| Bilibili | 公开多 P 样本 P1 与 BV1ggFseVES3 的匿名信息、完整音视频和帧获取通过；后者1920×1080、约237.9秒，字幕未取得。独立 Agent 自动选择 Skill，改看高清画面后完成概括与02:10追问；随后保存仅补音频，再次保存零网络请求 |
| 通用 HTTP / HTML / HLS | 本地真实 HTTP 样本验证直链、单个 video/source、TS 和 fMP4 点播 HLS、master 变体及音轨 / 时长；不是任意网页或任意 HLS 支持 |
| 腾讯视频（实验） | [公开短视频 q326831cny0](https://v.qq.com/x/page/q326831cny0.html) 匿名完整下载和抽帧通过：1280×720、215.958秒、H.264 + AAC；不推广到所有腾讯内容 |
| TikTok（实验） | 公开样本信息、媒体候选与 12 段字幕获取通过；视频下载尚未实测 |
| YouTube（实验） | 仅公开 player response 的信息、字幕及直接媒体地址路径；不处理播放器签名 / JS challenge，暂无成功线上下载验收 |
| Douyin（实验） | 仅公开页面嵌入信息路径；未通过真实样本验收，挑战页面可能无法读取 |
| 本地 ASR（可选） | small / CPU / int8 实测英文真人语音与中文合成语音、区间时间和文字稿复用通过；中文有少量错字，尚未做真人普通话质量评估 |

通用路径支持公开媒体直链、单个 HTML video/source 和基础非加密 VOD HLS（含 TS、fMP4 初始化段和 master 变体）。多视频网页、JS 动态播放器、HLS 独立音轨组 / 字节范围 / discontinuity / 加密 / 直播、MPD、跨调用断点续传仍未支持；返回具体诊断。腾讯只接单视频 `/x/page/VID.html` 或 `/x/cover/CID/VID.html`，不遍历整剧集，不补齐试看，不处理 DRM。以上是少量样本验证，不能推断平台所有链接均可用。

不处理直播、DRM、账号批量、图集、评论正文、自动翻译、说话人分离或内置全视频 OCR。平台接口变化、地区、网络和认证条件可能影响获取。遇到需要尚未实现的平台挑战时返回具体限制，不暗中调用外部下载项目。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

本轮42项测试通过；另以真实本地HTTP/HLS媒体验证1080p升级到4K、音轨完整和后续无联网复用。线上B站样本已通过匿名1080p完整下载验证。

默认测试离线，使用临时合成媒体；需 FFmpeg / ffprobe 的测试在缺失时明确跳过。网络和真实 ASR 测试单独验证，不在每次测试中下载视频或大模型。

## 参考

设计参考 [yt-dlp](https://github.com/yt-dlp/yt-dlp)、[claude-video](https://github.com/bradautomates/claude-video)、[claude-real-video](https://github.com/HUANGCHIHHUNGLeo/claude-real-video)、[BBDownT](https://github.com/LOVAHE/BBDownT) 和 [F2](https://github.com/Johnserf-Seed/f2) 的职责拆分与材料获取思路。这些不是运行依赖。源码移植或改编涉及的许可与署名随相应文件保留。
