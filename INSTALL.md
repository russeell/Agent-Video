# Install & update Agent Video

Instructions for coding agents. Use an existing checkout when available; otherwise clone the public repository into the user's workspace. Keep the whole project in place: the host Skill links to it, including its `.venv`.

## Install

Requires **Python 3.11+**, **FFmpeg** and **ffprobe** on `PATH`. Check them first:

```bash
python3 --version
ffmpeg -version
ffprobe -version
```

Install missing prerequisites with the environment's package manager (for example, `brew install ffmpeg` on macOS or `sudo apt-get install ffmpeg` on Ubuntu).

```bash
git clone https://github.com/russeell/Agent-Video.git
cd Agent-Video
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/agent-video --help
```

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

## Update

From the existing project directory, inspect local changes and confirm its remote, then update without rewriting history:

```bash
git status --short
git remote -v
git pull --ff-only
.venv/bin/python -m pip install -e .
.venv/bin/agent-video --help
```

Preserve local changes, evidence directories and prepared models. If the pull cannot fast-forward, report the conflict rather than resetting or forcing it. If ASR is installed, reinstall `-e '.[asr]'` instead. With a uv-managed environment lacking pip, use `uv pip install --python .venv/bin/python -e .` (or the ASR extra).

The existing Skill link stays valid when the project remains in place. Start a new host session to load the updated Skill.

## Windows

In PowerShell, use `python` and `.venv\Scripts\` instead of the Unix paths. After cloning:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\agent-video.exe --help
New-Item -ItemType Directory -Force "$env:USERPROFILE\.agents\skills" | Out-Null
New-Item -ItemType Junction -Path "$env:USERPROFILE\.agents\skills\agent-video" -Target (Get-Location).Path
```

Use `.claude` instead of `.agents` for Claude Code. Check existing links first. For updates, use the same Git commands and `.\.venv\Scripts\python.exe -m pip install -e .`; a uv-managed environment uses `uv pip install --python .venv\Scripts\python.exe -e .`.

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

Run `agent-video --help` from the project environment, then read [SKILL.md](SKILL.md). With a supported URL or local video, request only the needed evidence:

```bash
.venv/bin/agent-video "<video-url-or-local-file>" --get transcript
```

Check the returned files, not just the exit code. Captions need no model; without captions, ASR requires the optional setup above. A platform access failure is separate from installation. See [README.md](README.md) for current support and limits.
