<h1 align="center">Agent Video</h1>
<p align="center"><strong>Let your agent watch videos.</strong></p>

<p align="center">
  <a href="https://github.com/russeell/Agent-Video/actions/workflows/test.yml"><img src="https://github.com/russeell/Agent-Video/actions/workflows/test.yml/badge.svg?branch=main" alt="Tests"></a>
  <a href="INSTALL.md"><img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License"></a>
</p>

<p align="center">
  English · <a href="README.zh-CN.md">简体中文</a> · <a href="INSTALL.md">Install & update</a> · <a href="SKILL.md">Agent Skill</a>
</p>

Send your agent a video link. Ask what it's about, what's happening at a particular moment, or ask it to download the video. Local videos and screen recordings work too.

Agent Video gives your agent the **transcript, screenshots, audio, video files and video information** it needs. Your agent reads those materials and answers your question.

Works with **Codex, Claude Code**, and other coding agents that support Skills.

## What you can ask

```text
Summarize this tutorial: <video-url>
Extract the transcript with timestamps.
What's happening at 02:10? Show me a clear screenshot.
Save the video in the best available quality.
```

You can also read code or charts in a recording, save an audio clip, or find a tutorial that meets your requirements. Finding videos uses your agent's search tools; Agent Video reads the candidates when their content needs checking.

Only the materials needed for your question are fetched. Follow-up questions reuse saved files, and you can keep the transcripts, screenshots and media yourself.

## Install

Copy this message to your agent:

```text
Install Agent Video by following this guide:
https://raw.githubusercontent.com/russeell/Agent-Video/main/INSTALL.md
```

Requires **Python 3.11+** and **FFmpeg**. The [guide](INSTALL.md) covers installation, Windows, updates and optional speech-to-text. To update, ask your agent to follow the same guide.

After installation, ask your agent to use Agent Video with a link or local file.

## Supported sources

**v0.1 is an early release.** Support varies by platform and video; some links may still fail.

| Source | What works today |
|---|---|
| **Local files** | Read subtitles, take screenshots, and export audio, video or a selected clip |
| **YouTube** | Read captions and download public videos and Shorts; 1080p downloads tested |
| **Bilibili** | Read available captions and download public videos, including a chosen part; 1080p downloads tested |
| **TikTok** | Experimental: transcripts, downloads and screenshots tested on two public videos |
| **Douyin** | Not working yet: the current request is blocked by a signature check |

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

`--get` accepts `info,transcript,frames,audio,video`, separately or together. Files are saved in `.agent-video/` by default. The command returns JSON with file paths and a `manifest.json` that tracks saved materials for reuse. If one step fails, successful files are still kept.

See `--help` for time ranges, language, quality, video parts and Cookie files. Windows uses `.venv\Scripts\agent-video.exe`.

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
