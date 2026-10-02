<h1 align="center">Agent Video</h1>
<p align="center"><strong>Let your agent watch videos.</strong></p>

<p align="center">
  <a href="https://github.com/russeell/Agent-Video/actions/workflows/test.yml"><img src="https://github.com/russeell/Agent-Video/actions/workflows/test.yml/badge.svg?branch=main" alt="测试"></a>
  <a href="INSTALL.md"><img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="MIT 许可证"></a>
</p>

<p align="center">
  <a href="README.md">English</a> · 简体中文 · <a href="INSTALL.md">安装与更新</a> · <a href="SKILL.md">Agent Skill</a>
</p>

给 Coding Agent 一个视频链接或本地文件。Agent Video 按问题获取所需的**文字稿、画面、音频、视频和元数据**，Agent 阅读证据后回答，并保留材料供后续追问使用。

适用于 **Codex、Claude Code** 等支持 Agent Skills 的宿主。

## 一个视频，继续追问

直接向 Agent 提问：

```text
总结这个教程：<视频链接>
把 02:10 屏幕上的代码截清楚，讲一下。
保存这个视频，使用当前可获取的最高质量。
```

每次提问都接着已有材料进行。文字稿用来理解讲话，清晰画面用来检查实际内容；需要文件时，已有媒体优先复用，质量不足再补取。

- **按问题取材。** 优先字幕，可选本地语音转录；视觉问题按需抽帧，要文件时再获取素材。
- **保留原视频时间。** 文字稿与画面都对应源视频时刻，读取区间后仍可准确追问。
- **读完还能拿走。** 材料保存在本地目录，通过 manifest 复用，同一份文件既能支持回答，也能直接交付。

平台解析由本项目实现，运行依赖 Python 和 FFmpeg；语音转录另需可选本地模型。理解内容和组织回答由宿主 Agent 完成。

## 开始使用

把下面这段话复制给你的 Coding Agent：

```text
请按照以下指南，为我当前使用的宿主安装 Agent Video：
https://raw.githubusercontent.com/russeell/Agent-Video/main/INSTALL.md
```

需要 **Python 3.11+** 和 **FFmpeg / ffprobe**。[安装指南](INSTALL.md) 包含环境准备、Skill 注册、Windows、更新和可选语音转录。已经安装过？让 Agent 按同一份指南更新即可。

Skill 的发现与选择由宿主处理；需要时可明确要求“使用 Agent Video”或手动选择该 Skill。

## 还可以这样问

| 向 Agent 提问 | 使用的材料 |
|---|---|
| “提取带时间戳的文字稿。” | 可用字幕，或已配置的本地 ASR |
| “看看这个录屏里的 UI、代码或图表。” | Agent 实际打开并阅读的抽样画面 |
| “保存 01:20 到 01:35 的音频。” | 从视频实际音轨裁剪的对应片段 |
| “作者是谁？视频多长？” | 作者、标题、时长等元数据 |
| “找一个中文、10分钟以内、有实际演示的 FFmpeg 教程。” | 宿主搜索工具，以及验证候选内容的证据 |

寻找视频使用宿主已有搜索工具，优先用户指定平台，其次当前视频任务的平台，否则默认 YouTube；用户明确要求时再跨平台。标题和搜索摘要用于初筛，关于实际内容的推荐理由需要读取视频证据。

## 来源支持

**v0.1 是早期 MVP。** 下表是公开样本的实际验证范围；获取受作品、地区和平台变化影响。

| 来源 | 当前范围 |
|---|---|
| **本地文件** | 字幕、画面、音视频导出、区间处理和复用 |
| **YouTube** | 公开视频与 Shorts：字幕、含音轨的视频、画面和复用；已验证1080p |
| **Bilibili** | 公开视频与指定分 P：可用字幕、音视频、本地 ASR 和复用；已验证1080p |
| **TikTok** · 实验 | 两个公开样本验证了字幕或本地 ASR、完整音视频、画面和复用 |
| **腾讯视频** · 实验 | 一个公开、非 DRM 样本下载与读取通过 |
| **抖音** · 实验 | 当前匿名路径遇到签名挑战；内容和下载仍未通过真实验收 |

YouTube 的其他签名、token 和登录路径尚未实现。未知网站、普通网页和媒体直链不支持；已下载文件可作为本地输入。当前不处理直播或 DRM。

字幕和 ASR 可能有错字或没有覆盖全片；抽样画面不代表完整阅读。画面文字与讲话文字稿分别表达。Cookie 仅使用用户显式提供的文件，不自动读取浏览器凭据。

## CLI

安装后，在项目目录运行：

```bash
# 读取讲话文字
.venv/bin/agent-video "<视频链接或本地文件>" --get transcript

# 使用返回的 manifest 获取指定时刻的源尺寸画面
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get frames --at 02:10 --width 0 --quality source

# 使用返回的 manifest 保存同一视频
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get video
```

`--get` 支持 `info,transcript,frames,audio,video`，可组合请求。结果默认保存在 `.agent-video/`，JSON 返回文件路径和 manifest；部分失败仍保留成功证据。区间、语言、质量、分 P 和显式 Cookie 文件参数见 `--help`。Windows 使用 `.venv\Scripts\agent-video.exe`。

## 参与贡献

欢迎反馈失效的公开视频链接、改进诊断和简化 Agent 使用流程。[提交 Issue](https://github.com/russeell/Agent-Video/issues) 时附来源平台、需要的材料和诊断信息；不要包含凭据或带签名的媒体地址。

安装项目并完成改动后，确保 FFmpeg 可用，运行离线回归：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

线上获取与真实 ASR 分别验证。改进应保留证据复用，让工具保持简洁。

## 许可与参考

[MIT](LICENSE)。获取逻辑参考 [yt-dlp](https://github.com/yt-dlp/yt-dlp)、[youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)、[BBDownT](https://github.com/LOVAHE/BBDownT) 和 [F2](https://github.com/Johnserf-Seed/f2)；设计参考 [claude-video](https://github.com/bradautomates/claude-video)、[claude-real-video](https://github.com/HUANGCHIHHUNGLeo/claude-real-video) 和 [Video-Browser](https://github.com/chrisx599/Video-Browser)。必要的第三方许可与署名保留在源码中。
