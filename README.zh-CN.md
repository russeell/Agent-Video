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

把视频链接发给 Agent，问它视频讲了什么、某个时刻发生了什么，或者让它帮你下载。本地视频和录屏也能处理。

Agent Video 为 Agent 提供所需的**文字稿、截图、音频、视频文件和视频信息**，由 Agent 阅读这些材料并回答你的问题。

适用于 **Codex、Claude Code** 等支持 Skill 的 Coding Agent。

## 你可以这样问

```text
总结这个教程：<视频链接>
提取带时间戳的文字稿。
02:10 在发生什么？截一张清晰的图给我看看。
下载这个视频，选能获取到的最高画质。
```

也可以让 Agent 看录屏里的代码或图表、保存一段音频，或找一个符合要求的视频教程。找视频用 Agent 已有的搜索工具，需要确认内容时，再用 Agent Video 读取候选视频。

只获取回答问题需要的材料。继续追问同一个视频时，复用已经保存的文件；文字稿、截图和音视频也可以直接拿走。

## 安装

把下面这段话复制给 Agent：

```text
帮我按照这份指南安装 Agent Video：
https://raw.githubusercontent.com/russeell/Agent-Video/main/INSTALL.md
```

需要 **Python 3.11+** 和 **FFmpeg**；抖音还需要 **Chrome 或 Chromium**。[指南](INSTALL.md) 包含安装、Windows、更新和可选语音转文字的步骤。更新时，让 Agent 按同一份指南操作即可。

安装后，给 Agent 一个链接或本地文件，让它使用 Agent Video。

## 支持哪些视频

**v0.1 是早期版本。** 各平台的支持情况如下，部分链接仍可能无法获取。

| 来源 | 目前能做什么 |
|---|---|
| **本地文件** | 读取字幕、截图、导出音视频，也可以只处理指定片段 |
| **YouTube** | 读取字幕，下载公开视频和 Shorts；已验证 1080p 下载 |
| **Bilibili** | 读取可用字幕，下载公开视频，也可以指定分 P；已验证 1080p 下载 |
| **TikTok** | 实验支持：已用两个公开视频验证文字稿、下载和截图 |
| **抖音** | 实验支持：已验证一个公开视频的信息、1080p 有声下载和截图；需要 Chrome 或 Chromium |

暂不支持其他网站、媒体直链、直播和 DRM 加密视频。已经下载的视频可以作为本地文件使用。

优先读取字幕，没有字幕时可配置语音转文字。文字稿可能有错字，也可能没有覆盖全片；截图只展示选取的时刻。

<details>
<summary><strong>命令行用法</strong></summary>

安装后，在项目目录运行：

```bash
# 获取文字稿
.venv/bin/agent-video "<视频链接或本地文件>" --get transcript

# 使用已保存的 manifest 获取清晰截图
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get frames --at 02:10 --width 0 --quality source

# 保存同一个视频
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get video
```

`--get` 支持 `info,transcript,frames,audio,video`，可以单独获取，也可以组合。文件默认保存在 `.agent-video/`。命令返回 JSON，其中有文件路径和用于记录、复用材料的 `manifest.json`。某一步失败时，已经成功获取的文件仍会保留。

时间范围、语言、画质、分 P 和 Cookie 文件等参数见 `--help`。Windows 使用 `.venv\Scripts\agent-video.exe`。

</details>

## 参与贡献

遇到无法读取的链接或不好用的地方，欢迎[提交 Issue](https://github.com/russeell/Agent-Video/issues)，附上视频链接、想做什么和报错信息。请勿附带 Cookie 或私有下载地址。

修改代码后，安装项目和 FFmpeg，再运行测试：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

这些测试离线运行。修改下载或语音转文字功能时，还需要单独检查实际效果。

## 许可证

[MIT](LICENSE)。
