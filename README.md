# Agent Video

**Let your agent watch videos.**

**English** | [简体中文](README.zh-CN.md)

Give your coding agent a video link, a local file, or a topic. Agent Video fetches transcripts, frames, audio, video files, and metadata as needed. Your agent reads the results, answers questions, and reuses the same files for follow-ups.

Works with Codex, Claude Code, and other hosts that support Agent Skills. Platform extraction is implemented here; no external video downloader is required.

## Quick start

Requires **Python 3.11+** and **FFmpeg / ffprobe**. Ask your agent:

> Read [INSTALL.md](INSTALL.md) and install Agent Video for my host.

[INSTALL.md](INSTALL.md) covers installation, Skill registration, updates, Windows and optional speech-to-text. Keep the project in place after installation.

## Use it

Ask your agent naturally:

- “What is this video about? `<url>`”
- “What happens at 02:10? Show me a clear frame.”
- “Extract the timestamped transcript.”
- “Download the best available quality, then save the audio.”
- “Find a Chinese FFmpeg tutorial under 10 minutes with a hands-on demo.”

For discovery, the host uses its available search tools; Agent Video reads candidates when content verification is needed. Search uses your chosen platform, then the current task's platform, otherwise YouTube. It expands across platforms only when requested.

Skill selection depends on the host. If needed, explicitly ask to use Agent Video, select `$agent-video` in Codex, or invoke `/agent-video` in Claude Code.

<details>
<summary>Direct CLI usage</summary>

```bash
# Captions first; local speech-to-text if configured
.venv/bin/agent-video "<video-url-or-local-file>" --get transcript

# Get a clear frame or download media
.venv/bin/agent-video "<video-url>" --get frames --at 02:10 --width 0 --quality source
.venv/bin/agent-video "<video-url>" --get video,audio

# Continue with the manifest returned by an earlier call
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get video
```

`--get` accepts `info,transcript,frames,audio,video`; the default is `transcript`. See `--help` for language, intervals, quality, parts, and Cookie files. Cookies are used only when you explicitly supply a file; browser credentials are never read automatically.

Results live in `.agent-video/` by default. JSON output contains material paths, a manifest for follow-ups, and diagnostics. Partial success still returns usable files. Exit codes: `0` complete, `2` partial, `1` failed, `64` invalid arguments.

</details>

Captions are preferred; speech-to-text needs the optional setup below. Visual questions use selected frames, including silent recordings. Frame text is distinct from spoken transcripts; there is no built-in OCR. Sampling does not imply a full-video review.

Video downloads select the highest available quality. Timestamps refer to the original video; existing materials are reused and local input files stay unchanged.

## Supported sources

Early MVP: these results come from a small set of real samples, not a guarantee for every video.

| Source | Verified scope |
|---|---|
| Local files | Subtitles, frames, audio/video export, intervals, and reuse |
| YouTube | Public videos and Shorts: captions, 1080p video with audio, frames, and reuse |
| Bilibili | Public videos and individual parts: 1080p downloads, available captions, audio/ASR, and reuse |
| TikTok | Two public samples: captions or local ASR, complete video/audio, frames, and reuse |
| Douyin | Experimental and currently blocked by a signature challenge; content and downloads are not verified |
| Tencent Video | Experimental; one public, non-DRM sample downloaded and inspected |

Access can vary by video, region, and platform changes. Other YouTube signature/token/login paths remain unsupported. Unknown websites, ordinary webpages, and direct media URLs are unsupported; downloaded files can be used locally. No live streams or DRM.

## Optional speech-to-text

Prepare the optional dependencies and a local model using [INSTALL.md](INSTALL.md#optional-speech-to-text). Captions work without ASR; other evidence remains available when speech-to-text is not configured.

## Development

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Regression tests use temporary media and local HTTP servers. Online samples and real ASR are verified separately. The product is distributed as a source folder containing the Skill; a wheel alone is not a registered Skill.

## License & credits

[MIT](LICENSE). Acquisition research includes [yt-dlp](https://github.com/yt-dlp/yt-dlp), [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api), [BBDownT](https://github.com/LOVAHE/BBDownT), and [F2](https://github.com/Johnserf-Seed/f2). Design references include [claude-video](https://github.com/bradautomates/claude-video), [claude-real-video](https://github.com/HUANGCHIHHUNGLeo/claude-real-video), and [Video-Browser](https://github.com/chrisx599/Video-Browser). Required third-party notices are preserved in the source.
