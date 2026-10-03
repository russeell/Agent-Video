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

Give your coding agent a **topic, a video link, or a local file**. Agent Video supplies the **transcripts, frames and media** it needs to understand what is said and shown.

## What you can ask

```text
Find a short tutorial about <topic>.
Summarize this video: <video-url>
What's happening at 02:10? Show me a clear frame.
Extract the transcript with timestamps.
Download this video in the best available quality.
```

Your agent uses its [available search tools](SEARCH.md) to find candidates; Agent Video provides the information, words and images it needs to judge selected videos.

Only the materials needed for your question are fetched. Follow-ups reuse saved files; downloading a video also works as a direct request.

## Install

Works with **Codex, Claude Code**, and other coding agents that support Skills. Copy this message to your agent:

```text
Install Agent Video by following this guide:
https://raw.githubusercontent.com/russeell/Agent-Video/main/INSTALL.md
```

Requires **Python 3.11+** and **FFmpeg**. The [installation guide](INSTALL.md) covers setup, Windows and optional speech-to-text.

## Update

Ask your agent to follow [UPDATE.md](UPDATE.md). It keeps your existing environment, Skill link, models and saved files.

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
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get frames --at 02:10 --width 0 --quality source

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
