# Install Agent Video

Instructions for coding agents setting up Agent Video for the first time. If it is already installed, follow [UPDATE.md](UPDATE.md). Reuse an existing checkout; otherwise choose a dedicated, stable tools directory, such as `~/.local/share/agent-video` or the user's existing tools folder. Do not clone into the current business repository unless the user explicitly asks. Keep the whole project in place: the host Skill links to it, including its `.venv`.

## Install

Requires **Python 3.11+**, **FFmpeg** and **ffprobe** on `PATH`. Check them first:

```bash
python3 --version
ffmpeg -version
ffprobe -version
```

Obtain explicit user confirmation before using `sudo`, administrator privileges or making system-wide package-manager changes, including `brew` or `apt` installs. Prerequisite checks, the project's virtual environment and installs within it do not require elevated privileges.

If no checkout exists, the following uses a dedicated tools directory; otherwise enter the existing checkout and skip cloning.

```bash
mkdir -p "$HOME/.local/share"
git clone https://github.com/russeell/Agent-Video.git "$HOME/.local/share/agent-video"
cd "$HOME/.local/share/agent-video"
# Create this only if no suitable .venv exists
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/agent-video --help
```

Keep an existing `.venv` if it uses Python 3.11+. If it is managed by uv and has no pip, install with `uv pip install --python .venv/bin/python -e .` instead.

Register the Skill for the current host from the project directory. Check an existing `agent-video` link before replacing it; do not overwrite an unrelated installation.

```bash
# Codex
mkdir -p "$HOME/.agents/skills"
ln -s "$(pwd -P)" "$HOME/.agents/skills/agent-video"

# Claude Code
mkdir -p "$HOME/.claude/skills"
ln -s "$(pwd -P)" "$HOME/.claude/skills/agent-video"
```

Use the appropriate host block. Start a new session; restart the host if the Skill is not detected. Installing the Python package alone does not register the Skill.

## Windows

In PowerShell, use `python` and `.venv\Scripts\` instead of the Unix paths. Reuse an existing checkout, or choose a dedicated tools directory, for example:

```powershell
git clone https://github.com/russeell/Agent-Video.git "$env:LOCALAPPDATA\agent-video"
Set-Location "$env:LOCALAPPDATA\agent-video"
# Create this only if no suitable .venv exists
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\agent-video.exe --help
New-Item -ItemType Directory -Force "$env:USERPROFILE\.agents\skills" | Out-Null
New-Item -ItemType Junction -Path "$env:USERPROFILE\.agents\skills\agent-video" -Target (Get-Location).Path
```

Use `.claude` instead of `.agents` for Claude Code. Check existing links first. A uv-managed environment without pip uses `uv pip install --python .venv\Scripts\python.exe -e .`.

## Douyin

Douyin requires **Google Chrome**, or **Chromium with its executable on `PATH`**; Instagram and Ixigua may also need it for anonymous page reading. Agent Video starts the installed browser headlessly in a temporary, empty profile to obtain the work's data; it does not read your existing browser profile or cookies. Downloads and media processing use Agent Video's own code.

Chrome is detected in its normal macOS / Windows location, or `google-chrome`, `chromium` or `chromium-browser` on `PATH`. Interactive verification or login pages may still prevent access; these are not automated.

## WeChat Channels

Use a `weixin.qq.com/sph/...` share link or a `channels.weixin.qq.com/finder-preview/pages/feed?...` playback link. Public shares can return information without a video stream. For playback, try a valid preview link or supply your own exported **yuanbao.tencent.com Netscape Cookie file** with `--cookies "/path/to/cookies.txt"`. The official Yuanbao parser is contacted only when media is needed and the share preview provides none; information-only requests do not require it.

Agent Video does not read browser credentials, install interception certificates or use a third-party parser service. Captions and authenticated downloads are not yet verified; preview access restrictions may still prevent retrieval. The work description is not a transcript.

## Optional speech-to-text

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

An `export` in another terminal does not update a running desktop agent. Give the agent the model path so it can pass the variable when invoking Agent Video. On Windows, set `$env:AGENT_VIDEO_ASR_MODEL` and use `.venv\Scripts\python.exe`.

Defaults to CPU/int8; normal calls do not download models. Speech-to-text may contain errors, and captions may not cover the whole video. Without ASR, other materials remain available.

## Verify

Run `agent-video --help` and `agent-video --version` from the project environment, then read [SKILL.md](SKILL.md). With an existing short local video, check basic media processing without depending on platform access, subtitles or an ASR model:

```bash
.venv/bin/agent-video "/path/to/local-video.mp4" --get frames --max-frames 1 --width 0
# Use the manifest path returned above to check follow-up reuse and file delivery
.venv/bin/agent-video --evidence "/path/to/manifest.json" --get video
```

Open the returned frame and video; check the picture, duration and expected audio. The source file must remain unchanged, and both calls should use the same manifest. If no local video is available, report that media processing has not yet been verified.

Then try the user's task with a supported URL or local file. Captions need no model; without captions, ASR requires the optional setup above. Missing subtitles or a platform access failure does not mean installation failed. See [README.en.md](README.en.md) for current support and limits.
