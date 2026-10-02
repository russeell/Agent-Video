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

Give your coding agent a video link or local file. Agent Video gets the **transcript, frames, audio, video and metadata** it needs to answer your question. Your agent reads the evidence, explains what it finds, and keeps the materials for follow-ups.

Works with **Codex, Claude Code**, and other hosts that support Agent Skills.

## One video. Keep asking.

Ask your agent naturally:

```text
Summarize this tutorial: <video-url>
Show me the code on screen at 02:10.
Save the video in the best available quality.
```

Each question builds on the same materials. A transcript can answer what was said; a clear frame can show what happened. When you ask for the file, existing media is reused or upgraded as needed.

- **Get just what you need.** Captions first, optional local speech-to-text, selected frames for visual questions, and media files on request.
- **Keep the original timeline.** Transcripts and frames refer to times in the source video, including when you read an interval.
- **Read it, then keep it.** Evidence stays in a local folder with a manifest for reuse. The same files can support an answer or be delivered to you.

Platform extraction is implemented in this project. The runtime uses Python and FFmpeg; speech-to-text adds an optional local model. Your host agent handles understanding and answers.

## Get started

Copy this into your coding agent:

```text
Install Agent Video for my coding agent by following this guide:
https://raw.githubusercontent.com/russeell/Agent-Video/main/INSTALL.md
```

Requires **Python 3.11+** and **FFmpeg / ffprobe**. The [installation guide](INSTALL.md) covers setup, Skill registration, Windows, updates and optional speech-to-text. Already installed? Ask your agent to update Agent Video using the same guide.

Skill discovery is handled by your host. If needed, explicitly request Agent Video or select its Skill.

## More things to try

| Ask your agent | What it uses |
|---|---|
| “Extract a timestamped transcript.” | Available captions, or configured local ASR |
| “Read the UI, code or chart in this recording.” | Selected frames that the agent opens and inspects |
| “Save the audio from 01:20 to 01:35.” | The video's actual audio track, clipped to that interval |
| “Who made this video, and how long is it?” | Metadata such as author, title and duration |
| “Find a Chinese FFmpeg tutorial under 10 minutes with a hands-on demo.” | Host search tools, then evidence to verify the candidates |

Video discovery uses the host's available search tools. Search follows your chosen platform, then the current video task's platform, otherwise YouTube. It expands across platforms when you request it. Titles and search snippets support screening; content claims require reading the video evidence.

## Supported sources

**v0.1 is an early MVP.** The scope below reflects real public samples; access varies by video, region and platform changes.

| Source | Current scope |
|---|---|
| **Local files** | Subtitles, frames, audio/video export, intervals and reuse |
| **YouTube** | Public videos and Shorts: captions, video with audio, frames and reuse; 1080p verified |
| **Bilibili** | Public videos and individual parts: available captions, video/audio, local ASR and reuse; 1080p verified |
| **TikTok** · experimental | Captions or local ASR, complete video/audio, frames and reuse verified on two public samples |
| **Tencent Video** · experimental | One public, non-DRM sample downloaded and inspected |
| **Douyin** · experimental | Current anonymous path encounters a signature challenge; content and downloads remain unverified |

Other YouTube signature, token and login paths remain unsupported. Unknown websites, ordinary webpages and direct media URLs are unsupported; downloaded files can be read locally. Live streams and DRM are outside the current scope.

Captions and ASR may contain errors or cover only part of a video. Frames are samples; reading them does not imply a complete review. Screen text and spoken transcripts are kept distinct. Cookies are used only from a file you explicitly supply; browser credentials are never read automatically.

## CLI

After installation, run from the project directory:

```bash
# Read speech
.venv/bin/agent-video "<video-url-or-local-file>" --get transcript

# Continue with the returned manifest; inspect a moment at source resolution
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get frames --at 02:10 --width 0 --quality source

# Save the same video using the returned manifest
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get video
```

`--get` accepts `info,transcript,frames,audio,video` and supports combinations. Results are saved in `.agent-video/` by default. JSON output points to the files and manifest; partial success preserves usable evidence. Use `--help` for intervals, language, quality, parts and explicit Cookie files. Windows uses `.venv\Scripts\agent-video.exe`.

## Contributing

Broken public video links, clearer diagnostics and simpler agent workflows are useful contributions. [Open an issue](https://github.com/russeell/Agent-Video/issues) with the source platform, requested material and diagnostic message; keep credentials and signed media URLs out of reports.

Install the project, make your change, then run the offline regression suite with FFmpeg available:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Online acquisition and real ASR are checked separately. Improvements should preserve evidence reuse and keep the tool small.

## License & credits

[MIT](LICENSE). Acquisition research includes [yt-dlp](https://github.com/yt-dlp/yt-dlp), [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api), [BBDownT](https://github.com/LOVAHE/BBDownT), and [F2](https://github.com/Johnserf-Seed/f2). Design references include [claude-video](https://github.com/bradautomates/claude-video), [claude-real-video](https://github.com/HUANGCHIHHUNGLeo/claude-real-video), and [Video-Browser](https://github.com/chrisx599/Video-Browser). Required third-party notices are preserved in the source.
