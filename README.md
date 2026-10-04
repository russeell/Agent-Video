<h1 align="center">Agent Video</h1>
<p align="center"><strong>Let your agent find and watch videos.</strong></p>

<p align="center">
  <a href="https://github.com/russeell/Agent-Video/actions/workflows/test.yml"><img src="https://github.com/russeell/Agent-Video/actions/workflows/test.yml/badge.svg?branch=main" alt="Tests"></a>
  <a href="INSTALL.md"><img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License"></a>
</p>

<p align="center">
  English · <a href="README.zh-CN.md">简体中文</a> · <a href="INSTALL.md">Install</a> · <a href="UPDATE.md">Update</a> · <a href="SKILL.md">Agent Skill</a>
</p>

Give **Codex, Claude Code or another coding agent** a video link or local file. Ask what's said or shown, get a timestamped transcript, capture a clear screenshot, or save the audio and video you need.

## Example walkthrough

![Agent Video demo: understand a Dragon Ball clip, inspect 01:48, and save the video](assets/demo.gif)

*Animation made from verified outputs, not a raw session recording. Material acquisition waits are omitted.*

With this [Dragon Ball clip](https://www.bilibili.com/video/BV1X5411b7xA/): explain what's happening from sampled frames → show a clear frame at **01:48** → save the **1080p video with audio**. Follow-ups reuse the saved materials.

## What you can ask

```text
Summarize this video: <video-url>
Extract the transcript with timestamps.
What does this video show at <timestamp>? Show me a clear frame.
Save just the audio from this video.
Download this video in the best available quality.
Find a short Blender tutorial with an on-screen demonstration.
```

Describe a topic to find videos using your agent's [available search tools](SEARCH.md). Agent Video gets the materials your agent needs to answer you and saves them for follow-ups. You can also request audio or video files directly.

## Install

Works with **Codex, Claude Code**, and other coding agents that support Skills. Copy this message to your agent:

```text
Install Agent Video by following this guide:
https://raw.githubusercontent.com/russeell/Agent-Video/main/INSTALL.md
```

Requires **Python 3.11+** and **FFmpeg**. The [installation guide](INSTALL.md) covers setup, Windows and optional speech-to-text.

## Update

Copy this message to your agent:

```text
Update my existing Agent Video installation by following this guide:
https://raw.githubusercontent.com/russeell/Agent-Video/main/UPDATE.md
```

The [update guide](UPDATE.md) preserves your existing setup and saved files.

## Supported sources

**v0.1 is an early release.** Support varies by platform and video; some links may still fail.

| Source | What works today |
|---|---|
| **Local files** | Read subtitles, take screenshots, and export audio, video or a selected clip |
| **YouTube** | Experimental: read captions and download public videos and Shorts; 1080p downloads tested |
| **Bilibili** | Read available captions and download public videos, including a chosen part; 1080p downloads tested |
| **TikTok** | Experimental: transcripts, downloads and screenshots tested on two public videos |
| **Douyin** | Experimental: information, 1080p downloads with audio and screenshots tested; requires [Chrome or Chromium](INSTALL.md#douyin) |
| **Instagram** | Experimental: public Reel download with audio and screenshots tested; anonymous page reading may need [Chrome or Chromium](INSTALL.md#douyin) |
| **X / Twitter** | Experimental: attached-video downloads, screenshots and reuse tested |
| **Weibo** | Experimental: single posts and TV pages tested, including a 1080p download |
| **Dailymotion** | Experimental: 1080p download with audio, screenshots and reuse tested |
| **TED** | Native captions, download with audio, screenshots and reuse tested; some HLS variants are unsupported |
| **Twitch** | Experimental: public clips tested at 1080p; completed-VOD information and stream discovery tested, full VOD download unverified |
| **Pornhub** | Experimental: public MP4 download with audio and reuse tested; some HLS endpoints remain unavailable |
| **Vimeo** | Information and captions tested; tested video streams were encrypted or access-restricted, so downloads remain unverified |
| **Reddit** | Experimental: native-video downloads, screenshots and reuse tested, including videos without audio |
| **Kuaishou** | Experimental: public works and share links tested, including 720p downloads with audio, screenshots and reuse |
| **Xiaohongshu** | Experimental: tested notes redirected to unavailable or security pages; information and downloads remain unverified |
| **WeChat Channels** | Experimental: public share-link information tested; playback-link and user-supplied Yuanbao Cookie paths implemented, downloads remain unverified ([setup](INSTALL.md#wechat-channels)) |

Public links can still require authentication or verification. Netflix, Facebook, unknown websites, direct media links, live streams and DRM-protected videos are not supported. Downloaded files can be used as local input.

Bilibili supporter-only videos require an account with access and an explicitly supplied Cookie file; a public video page does not guarantee public playback.

Subtitles are used first. If none are available, optional speech-to-text can transcribe the audio. Transcripts may contain errors or cover only part of a video; screenshots show selected moments.

<details>
<summary><strong>Use the command line</strong></summary>

After installation, run from the project directory:

```bash
# Get a transcript
.venv/bin/agent-video "<video-url-or-local-file>" --get transcript

# Save the audio
.venv/bin/agent-video "<video-url-or-local-file>" --get audio

# Get a clear screenshot using the saved manifest
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get frames --at 00:10 --width 0 --quality source

# Download a video directly
.venv/bin/agent-video "<video-url>" --get video
```

Choose a time within the video's duration for `--at`. `--get` accepts `info,transcript,frames,audio,video`, separately or together. Files are saved in `.agent-video/` by default. The command returns JSON with file paths and a `manifest.json`; use `--evidence` to reuse its materials for follow-ups or downloads. Exit code `2` means partial success; completed files remain usable.

See `--help` for time ranges, language, quality, video parts and Cookie files; `--version` shows the installed version. Windows uses `.venv\Scripts\agent-video.exe`.

</details>

## Contributing

Found a broken link or confusing behavior? [Open an issue](https://github.com/russeell/Agent-Video/issues) with the video link, what you wanted to do and the error message. Leave out cookies and private download addresses.

For code changes, install the project and FFmpeg, then run the tests:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

These tests run offline. Check real downloads or speech-to-text separately when changing those features.

## License

[MIT](LICENSE).
