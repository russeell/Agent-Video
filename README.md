# Agent Video

**Let your agent watch videos.**

**English** | [简体中文](README.zh-CN.md)

Give your coding agent a video link, a local file, or a topic. Agent Video fetches transcripts, frames, audio, video files, and metadata as needed. Your agent reads the results, answers questions, and reuses the same files for follow-ups.

Works with Codex, Claude Code, and other hosts that support Agent Skills. Platform extraction is implemented here; no external video downloader is required.

## Quick start

Requires **Python 3.11+**. Add **FFmpeg and ffprobe** to `PATH` for downloads and media processing. Speech-to-text is optional.

```bash
git clone https://github.com/russeell/Agent-Video.git
cd Agent-Video
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Register the Skill for your host from the project directory:

```bash
# Codex
mkdir -p "$HOME/.agents/skills"
ln -s "$(pwd -P)" "$HOME/.agents/skills/agent-video"

# Claude Code
mkdir -p "$HOME/.claude/skills"
ln -s "$(pwd -P)" "$HOME/.claude/skills/agent-video"
```

Link the **whole project**, including `.venv`, and keep it in place. Check any existing `agent-video` link before replacing it. Start a new session; restart the host if the Skill is not detected. Installing the Python package alone does not register the Skill.

<details>
<summary>Windows setup</summary>

Run in PowerShell after cloning the project. This registers Codex; use `.claude` instead of `.agents` for Claude Code.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
New-Item -ItemType Directory -Force "$env:USERPROFILE\.agents\skills" | Out-Null
New-Item -ItemType Junction -Path "$env:USERPROFILE\.agents\skills\agent-video" -Target (Get-Location).Path
```

Use `.venv\Scripts\python.exe` for subsequent commands. macOS has been tested; Windows and Linux have not yet been validated.

</details>

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
.venv/bin/python scripts/watch.py "<video-url-or-local-file>" --get transcript

# Get a clear frame or download media
.venv/bin/python scripts/watch.py "<video-url>" --get frames --at 02:10 --width 0 --quality source
.venv/bin/python scripts/watch.py "<video-url>" --get video,audio

# Continue with the manifest returned by an earlier call
.venv/bin/python scripts/watch.py --evidence "/path/to/manifest.json" --get video
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

<details>
<summary>Prepare a local faster-whisper model</summary>

Install the optional dependencies:

```bash
.venv/bin/python -m pip install -e '.[asr]'
```

Download a model explicitly, outside the project:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import truststore
truststore.inject_into_ssl()
from huggingface_hub import snapshot_download
snapshot_download("Systran/faster-whisper-small", token=False,
    local_dir=Path.home() / ".cache/agent-video/models/faster-whisper-small",
    allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*"])
PY
```

Set the model path in the process that invokes Agent Video:

```bash
export AGENT_VIDEO_ASR_MODEL="$HOME/.cache/agent-video/models/faster-whisper-small"
```

An `export` in another terminal does not update a running desktop agent. Give the agent the model path so it can pass the variable when calling the script. On Windows, set `$env:AGENT_VIDEO_ASR_MODEL` and use `.venv\Scripts\python.exe`.

Defaults to CPU/int8; normal calls do not download models. Speech-to-text may contain errors, and captions may not cover the whole video. Without ASR, other materials remain available.

</details>

## Development

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Regression tests use temporary media and local HTTP servers. Online samples and real ASR are verified separately. The product is distributed as a source folder containing the Skill; a wheel alone is not a registered Skill.

## License & credits

[MIT](LICENSE). Acquisition research includes [yt-dlp](https://github.com/yt-dlp/yt-dlp), [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api), [BBDownT](https://github.com/LOVAHE/BBDownT), and [F2](https://github.com/Johnserf-Seed/f2). Design references include [claude-video](https://github.com/bradautomates/claude-video), [claude-real-video](https://github.com/HUANGCHIHHUNGLeo/claude-real-video), and [Video-Browser](https://github.com/chrisx599/Video-Browser). Required third-party notices are preserved in the source.
