# Update Agent Video

Instructions for coding agents updating an existing installation. For a first installation or missing prerequisites, see [INSTALL.md](INSTALL.md).

## Find the installation

Locate the current host's `agent-video` Skill link: usually `$HOME/.agents/skills/agent-video` for Codex or `$HOME/.claude/skills/agent-video` for Claude Code. Follow that link to the existing checkout; a Windows installation may use a junction. If it cannot be found, ask for the installed directory rather than cloning a second copy.

Keep the checkout, `.venv`, Skill link, prepared models, model environment variables, Cookie files and saved evidence in place. Updating does not require registering the Skill again or downloading models.

## Update the checkout

From that directory, inspect the working tree, branch and remote:

```bash
git status --short
git branch --show-current
git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}'
git remote get-url origin
```

Confirm that the remote is `russeell/Agent-Video` on GitHub and the branch uses the intended upstream, normally `origin/main`. Do not publish remote credentials if an URL contains them. If there are local changes, a different remote, a detached HEAD or an unclear upstream, report what needs resolving before continuing; do not reset, stash, switch branches or replace the installation automatically.

With a clean working tree and the correct upstream:

```bash
git pull --ff-only
```

If fast-forwarding fails, report it and preserve the checkout. Do not force an update or merge divergent history.

## Refresh dependencies

Use the existing Python environment. Check whether speech-to-text is already installed:

```bash
.venv/bin/python -c "import importlib.util; print('ASR installed:', importlib.util.find_spec('faster_whisper') is not None)"
```

Then run **one** matching command:

```bash
# Standard installation
.venv/bin/python -m pip install -e .

# Existing ASR installation: keep its optional dependencies
.venv/bin/python -m pip install -e '.[asr]'
```

For a uv-managed environment without pip, use `uv pip install --python .venv/bin/python -e .` or `uv pip install --python .venv/bin/python -e '.[asr]'`. On Windows, substitute `.venv\Scripts\python.exe`; the CLI is `.venv\Scripts\agent-video.exe`.

## Verify

```bash
.venv/bin/agent-video --help
.venv/bin/agent-video --version
```

Confirm that the existing command runs and the Skill link still points to this checkout. Start a new host session to load the updated [SKILL.md](SKILL.md). If you have a local video or saved manifest, request only the material you need and check its returned files; an update check does not need a network download or ASR run.

Use [INSTALL.md](INSTALL.md) only to fill a missing prerequisite or optional setup. Preserve existing models and settings; a platform access failure is separate from an installation failure.
