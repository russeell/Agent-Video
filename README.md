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

Give your coding agent a **topic, a video link, or a local file**. Ask it to find a useful video, explain what is said and shown, or save the files you need.

## A real example

We used [Vogue's *In The Bag* with Emma Watson](https://www.youtube.com/watch?v=yA79KYMLUpI) to get a summary from the English automatic captions, inspect a **clear frame at 01:23**, and save the **complete 1080p video with audio**. Follow-up questions reused the saved materials.

## What you can ask

```text
Find a short Blender tutorial with an on-screen demonstration.
Summarize this video: <video-url>
What's happening at 01:23? Show me a clear frame.
Extract the transcript with timestamps.
Download this video in the best available quality.
```

Your agent uses its [available search tools](SEARCH.md) to find candidates. Agent Video gets the selected video's information, transcript, frames or media files as needed. You can also ask it to download a video directly.

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
| **Douyin** | Experimental: information, 1080p downloads with audio and screenshots tested on one public video; requires [Chrome or Chromium](INSTALL.md#douyin) |

Other websites, direct media links, live streams and DRM-protected videos are not supported. You can use a downloaded file as local input.

Subtitles are used first. If none are available, optional speech-to-text can transcribe the audio. Transcripts may contain errors or cover only part of a video; screenshots show selected moments.

<details>
<summary><strong>Use the command line</strong></summary>

After installation, run from the project directory:

```bash
# Get a transcript
.venv/bin/agent-video "<video-url-or-local-file>" --get transcript

# Get a clear screenshot using the saved manifest
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get frames --at 01:23 --width 0 --quality source

# Save the same video
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get video
```

`--get` accepts `info,transcript,frames,audio,video`, separately or together. Files are saved in `.agent-video/` by default. The command returns JSON with file paths and a `manifest.json` that tracks saved materials for reuse. Exit code `2` means partial success; completed files remain usable.

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
