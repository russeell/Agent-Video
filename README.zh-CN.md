<h1 align="center">Agent Video</h1>
<p align="center"><strong>Let your agent find and watch videos.</strong></p>

<p align="center">
  <a href="https://github.com/russeell/Agent-Video/actions/workflows/test.yml"><img src="https://github.com/russeell/Agent-Video/actions/workflows/test.yml/badge.svg?branch=main" alt="测试"></a>
  <a href="INSTALL.md"><img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="MIT 许可证"></a>
</p>

<p align="center">
  <a href="README.md">English</a> · 简体中文 · <a href="INSTALL.md">安装</a> · <a href="UPDATE.md">更新</a> · <a href="SKILL.md">Agent Skill</a>
</p>

给 Coding Agent 一个**主题、视频链接或本地文件**。让它帮你找视频、理解视频说了什么和展示了什么，或者保存你需要的文件。

## 使用示例

![Agent Video 演示：理解七龙珠片段、查看 01:48 画面、保存视频](assets/demo.gif)

*基于已验证输出制作的演示动画，非原始会话录屏；获取材料的等待时间已省略。*

用这段[七龙珠视频](https://www.bilibili.com/video/BV1X5411b7xA/)：解释抽样画面 → 查看 **01:48** → 保存 **1080p 有声视频**，复用已保存的材料。

## 你可以这样问

```text
找一个有实际操作演示的 Blender 短教程。
总结这个视频：<视频链接>
这个视频在 <时间点> 展示了什么？截一张清晰的图给我看看。
提取带时间戳的文字稿。
下载这个视频，选能获取到的最高画质。
```

Agent 使用[宿主已有搜索工具](SEARCH.md)寻找候选，Agent Video 按需获取选中视频的信息、文字稿、画面和音视频。你也可以直接要求下载视频。

## 安装

适用于 **Codex、Claude Code** 等支持 Skill 的 Coding Agent。把下面这段话复制给 Agent：

```text
帮我按照这份指南安装 Agent Video：
https://raw.githubusercontent.com/russeell/Agent-Video/main/INSTALL.md
```

需要 **Python 3.11+** 和 **FFmpeg**。[安装指南](INSTALL.md) 包含首次安装、Windows 和可选语音转文字的步骤。

## 更新

把下面这段话复制给 Agent：

```text
帮我按照这份指南更新已安装的 Agent Video：
https://raw.githubusercontent.com/russeell/Agent-Video/main/UPDATE.md
```

[更新指南](UPDATE.md)会保留现有环境和已保存的文件。

## 支持哪些视频

**v0.1 是早期版本。** 各平台的支持情况如下，部分链接仍可能无法获取。

| 来源 | 目前能做什么 |
|---|---|
| **本地文件** | 读取字幕、截图、导出音视频，也可以只处理指定片段 |
| **YouTube** | 实验支持：读取字幕，下载公开视频和 Shorts；已验证 1080p 下载 |
| **Bilibili** | 读取可用字幕，下载公开视频，也可以指定分 P；已验证 1080p 下载 |
| **TikTok** | 实验支持：已用两个公开视频验证文字稿、下载和截图 |
| **抖音** | 实验支持：已验证一个公开视频的信息、1080p 有声下载和截图；需要 [Chrome 或 Chromium](INSTALL.md#douyin) |

暂不支持其他网站、媒体直链、直播和 DRM 加密视频。已经下载的视频可以作为本地文件使用。

B 站充电专属视频需要有观看权限的账号和显式提供的 Cookie 文件；能打开作品页面不代表能匿名播放。

优先读取字幕，没有字幕时可配置语音转文字。文字稿可能有错字，也可能没有覆盖全片；截图只展示选取的时刻。

<details>
<summary><strong>命令行用法</strong></summary>

安装后，在项目目录运行：

```bash
# 获取文字稿
.venv/bin/agent-video "<视频链接或本地文件>" --get transcript

# 使用已保存的 manifest 获取清晰截图
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get frames --at 00:10 --width 0 --quality source

# 直接下载视频
.venv/bin/agent-video "<video-url>" --get video
```

`--at` 应选择视频时长内的时刻。`--get` 支持 `info,transcript,frames,audio,video`，可以单独获取，也可以组合。文件默认保存在 `.agent-video/`。命令返回 JSON，其中有文件路径和 `manifest.json`；追问或下载时用 `--evidence` 复用已有材料。退出码 `2` 表示部分成功，已完成的文件仍可使用。

时间范围、语言、画质、分 P 和 Cookie 文件等参数见 `--help`；`--version` 显示安装版本。Windows 使用 `.venv\Scripts\agent-video.exe`。

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
