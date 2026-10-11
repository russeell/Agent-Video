<h1 align="center">Agent Video</h1>
<p align="center"><strong>Let your agent find and watch videos.</strong></p>

<p align="center">
  <a href="https://github.com/russeell/Agent-Video/actions/workflows/test.yml"><img src="https://github.com/russeell/Agent-Video/actions/workflows/test.yml/badge.svg?branch=main" alt="Tests"></a>
  <a href="INSTALL.md"><img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License"></a>
</p>

<p align="center">
  English · <a href="README.md">简体中文</a> · <a href="INSTALL.md">Install</a> · <a href="UPDATE.md">Update</a> · <a href="SKILL.md">Agent Skill</a>
</p>

**Give your agent a video link. Get answers, a transcript, or the audio and video files.**

Agent Video retrieves transcripts, frames, audio and video so your AI agent can read the content and deliver files. It works with online videos and local files. Describe what you need to let your agent find candidates with its existing search tools, then read as needed.

[Ask your agent to install it](#install) · [Check supported sources](#supported-sources)

## Example walkthrough

![Agent Video demo: understand a Dragon Ball clip, inspect 01:48, and save the video](assets/demo.gif)

*Animation made from verified outputs, not a raw session recording. Material acquisition waits are omitted.*

With this [Dragon Ball clip](https://www.bilibili.com/video/BV1X5411b7xA/): explain what's happening from sampled frames → show a clear frame at **01:48** → save the **1080p video with audio**. Follow-ups reuse the saved materials.

## What you can do

| What you need | Ask your agent |
|---|---|
| **Find videos** by topic and requirements | “Find a short Blender tutorial with an on-screen demonstration.” |
| **Understand the content** from speech and visuals | “Summarize this video and explain the key points.” |
| **Extract a transcript** with timestamps | “Extract what's said in this video, with timestamps.” |
| **Inspect a moment** with a clear screenshot of UI, code or charts | “What does this video show at `<timestamp>`? Give me a clear screenshot.” |
| **Save audio** as a separate file | “Save just the audio from this video.” |
| **Download video** in the best available quality, or save a selected clip | “Download this video in the best available quality.” |
| **Ask follow-ups** using the same saved materials | “Using that transcript, explain the second point.” |

**Get what you need, reuse what you have.** Read a transcript for speech, inspect frames for visual questions, or download a file directly. Materials stay on your machine and are reused for follow-ups.

Your agent handles search and understanding; Agent Video retrieves the materials. Finding videos requires [available search tools](SEARCH.md) in your host. Summaries and answers use text or frames the agent has actually read.

## Install

Use it with any AI agent that can run commands and read text and images. Register the Skill if your host supports it, or use the CLI directly. Send this message to your agent:

```text
Install Agent Video by following this guide:
https://raw.githubusercontent.com/russeell/Agent-Video/main/INSTALL.md
```

Requires **Python 3.11+** and **FFmpeg**. The [installation guide](INSTALL.md) covers setup, Windows and optional speech-to-text.

## Update

Send this message to your agent:

```text
Update my existing Agent Video installation by following this guide:
https://raw.githubusercontent.com/russeell/Agent-Video/main/UPDATE.md
```

The [update guide](UPDATE.md) preserves your existing setup and saved files.

## Supported sources

Works with local files and videos from YouTube, Bilibili, Douyin, TikTok and other platforms. **v0.1 is an early release: support varies by platform and link. Not every video can be retrieved.**

Complete video downloads from Xiaohongshu, WeChat Channels and 91porn have not passed real-world verification. Other sources also have limits, detailed below.

<details>
<summary><strong>Verified capabilities and limits by platform</strong></summary>

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
| **Vimeo** | Experimental: available captions, 1080p downloads with audio, screenshots and reuse tested; some videos are encrypted or access-restricted |
| **Reddit** | Experimental: native-video downloads, screenshots and reuse tested, including videos without audio |
| **Kuaishou** | Experimental: public works and share links tested, including 720p downloads with audio, screenshots and reuse |
| **Xiaohongshu** | Experimental: tested notes redirected to unavailable or security pages; information and downloads remain unverified |
| **WeChat Channels** | Experimental: public share-link information tested; playback-link and user-supplied Yuanbao Cookie paths implemented, downloads remain unverified ([setup](INSTALL.md#wechat-channels)) |
| **Loom** | Experimental: public-share captions, download with audio, screenshots and reuse tested; some original files have audio decoding errors |
| **Google Drive** | Experimental: public video-share downloads, screenshots and reuse tested; downloads use playable versions, original files and captions remain unverified |
| **LinkedIn** | Experimental: public native post videos, captions, screenshots and reuse tested; excludes Learning, events and external video links |
| **Streamable** | Experimental: single-video downloads with audio, screenshots and reuse tested |
| **Bluesky** | Experimental: original 1080p video, available captions, screenshots and reuse tested; captions may cover only part of a video |
| **Zhihu** | Experimental: zvideo downloads with audio, screenshots and reuse tested |
| **Ixigua** | Experimental: 720p downloads with audio, screenshots and reuse tested; anonymous reading may need [Chrome or Chromium](INSTALL.md#douyin), share links remain unverified |
| **CCTV** | Experimental: CCTV / CNTV VOD downloads with audio, screenshots and audio export tested; best exposed quality in the samples was 270p; excludes Yangshipin |
| **91porn** | Experimental: page information available on the main site and `up.91splt.app`; sample media differed from the page duration, so complete-work downloads remain unverified and mismatched files are rejected |
| **MissAV** | Experimental: single-work information, complete 720p downloads with audio, frame extraction and reuse tested; some pages may still require verification |

</details>

Public links can still require authentication or verification. Netflix, Facebook, unknown websites, direct media links, live streams and DRM-protected videos are not supported. Downloaded files can be used as local input.

Bilibili supporter-only videos require an account with access and an explicitly supplied Cookie file. Premium series links using `ep/ss` are not yet implemented. Access to a video page does not guarantee a complete download.

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

Found a broken link or confusing behavior? [Open an issue](https://github.com/russeell/Agent-Video/issues) with a public video link, what you wanted to do, your OS / agent, the `--version` output and the returned `status` / `diagnostics`. Leave out cookies, private links and signed download addresses.

For code changes, install the project and FFmpeg, then run the tests:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

These tests run offline. Check real downloads or speech-to-text separately when changing those features.

## License

[MIT](LICENSE).
