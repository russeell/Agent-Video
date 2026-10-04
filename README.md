<h1 align="center">Agent Video</h1>
<p align="center"><strong>Let your agent find and watch videos.</strong></p>

<p align="center">
  <a href="https://github.com/russeell/Agent-Video/actions/workflows/test.yml"><img src="https://github.com/russeell/Agent-Video/actions/workflows/test.yml/badge.svg?branch=main" alt="测试"></a>
  <a href="INSTALL.md"><img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="MIT 许可证"></a>
</p>

<p align="center">
  简体中文 · <a href="README.en.md">English</a> · <a href="INSTALL.md">安装</a> · <a href="UPDATE.md">更新</a> · <a href="SKILL.md">Agent Skill</a>
</p>

让你的 AI Agent 帮你**找视频、理解内容、提取文字、保存音视频**。给它一个视频链接、本地文件，或直接描述你的需求。

## 使用示例

![Agent Video 演示：理解七龙珠片段、查看 01:48 画面、保存视频](assets/demo.gif)

*基于已验证输出制作的演示动画，非原始会话录屏；获取材料的等待时间已省略。*

用这段[七龙珠视频](https://www.bilibili.com/video/BV1X5411b7xA/)：根据抽样画面解释发生了什么 → 查看 **01:48** 的清晰截图 → 保存 **1080p 有声视频**。后续追问复用已保存的材料。

## 能帮你做什么

| 你想做什么 | 可以这样问 Agent |
|---|---|
| **找视频**：按主题和条件挑选 | “找一个有实际操作演示的 Blender 短教程。” |
| **理解内容**：总结讲话与画面 | “总结这个视频，告诉我关键内容。” |
| **提取文字**：带时间戳的文字稿 | “把视频里的讲话整理成带时间戳的文字稿。” |
| **查看画面**：定点截图，看清 UI、代码或图表 | “这个视频在 `<时间点>` 展示了什么？给我一张清晰截图。” |
| **保存音频**：单独导出音轨 | “把这个视频的音频单独保存下来。” |
| **下载视频**：最高可获取画质，或指定片段 | “下载这个视频，选能获取到的最高画质。” |
| **继续追问**：复用同一视频的材料 | “根据刚才的文字稿，解释一下第二个观点。” |

找视频使用 Agent 的[已有搜索工具](SEARCH.md)，按你的条件核对所需信息；内容结论依据实际读过的文字或画面。

只需要文件时，直接下载即可。已获取的材料自动保留，后续追问、补截图或保存文件时优先复用。

## 安装

适用于能运行命令、读取文本与图片的 AI Agent。支持 Skill 的宿主可注册后使用，也可直接调用 CLI。把下面这段话复制给 Agent：

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
| **抖音** | 实验支持：已验证信息、1080p 有声下载和截图；需要 [Chrome 或 Chromium](INSTALL.md#douyin) |
| **Instagram** | 实验支持：已验证公开 Reel 的有声下载和截图；匿名读取页面可能需要 [Chrome 或 Chromium](INSTALL.md#douyin) |
| **X / Twitter** | 实验支持：已验证帖子视频下载、截图和复用 |
| **微博** | 实验支持：已验证普通帖子和视频页，包括 1080p 下载 |
| **Dailymotion** | 实验支持：已验证 1080p 有声下载、截图和复用 |
| **TED** | 已验证原生字幕、有声下载、截图和复用；部分 HLS 版本暂不支持 |
| **Twitch** | 实验支持：已验证公开片段的 1080p 下载；录像信息和媒体地址已核对，完整录像下载未验证 |
| **Pornhub** | 实验支持：已验证公开 MP4 的有声下载和复用；部分 HLS 接口仍不可用 |
| **Vimeo** | 已验证信息和字幕；测试视频流加密或限制访问，下载仍未验证 |
| **Reddit** | 实验支持：已验证站内视频下载、截图和复用，包括无音轨视频 |
| **快手** | 实验支持：已验证公开作品和分享链接，包括 720p 有声下载、截图和复用 |
| **小红书** | 实验支持：测试笔记跳转到暂不可浏览或安全验证页，信息和下载仍未验证 |
| **微信视频号** | 实验支持：已验证公开分享链接的信息获取；已实现播放链接和用户提供的元宝 Cookie 路径，下载仍未实测通过（[配置](INSTALL.md#wechat-channels)） |

公开链接仍可能需要登录或验证。暂不支持 Netflix、Facebook、未知网站、媒体直链、直播和 DRM 加密视频。已经下载的视频可以作为本地文件使用。

B 站充电专属视频需要有观看权限的账号和显式提供的 Cookie 文件；能打开作品页面不代表能匿名播放。

优先读取字幕，没有字幕时可配置语音转文字。文字稿可能有错字，也可能没有覆盖全片；截图只展示选取的时刻。

<details>
<summary><strong>命令行用法</strong></summary>

安装后，在项目目录运行：

```bash
# 获取文字稿
.venv/bin/agent-video "<视频链接或本地文件>" --get transcript

# 单独保存音频
.venv/bin/agent-video "<视频链接或本地文件>" --get audio

# 使用已保存的 manifest 获取清晰截图
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get frames --at 00:10 --width 0 --quality source

# 直接下载视频
.venv/bin/agent-video "<video-url>" --get video
```

`--at` 应选择视频时长内的时刻。`--get` 支持 `info,transcript,frames,audio,video`，可以单独获取，也可以组合。文件默认保存在 `.agent-video/`。命令返回 JSON，其中有文件路径和 `manifest.json`；追问或下载时用 `--evidence` 复用已有材料。退出码 `2` 表示部分成功，已完成的文件仍可使用。

时间范围、语言、画质、分 P 和 Cookie 文件等参数见 `--help`；`--version` 显示安装版本。Windows 使用 `.venv\Scripts\agent-video.exe`。

</details>

## 参与贡献

遇到无法读取的链接或不好用的地方，欢迎[提交 Issue](https://github.com/russeell/Agent-Video/issues)，附上公开视频链接、想做什么、系统和 Agent、`--version` 输出，以及返回的 `status` / `diagnostics`。请勿附带 Cookie、私人链接或带签名的下载地址。

修改代码后，安装项目和 FFmpeg，再运行测试：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

这些测试离线运行。修改下载或语音转文字功能时，还需要单独检查实际效果。

## 许可证

[MIT](LICENSE)。
