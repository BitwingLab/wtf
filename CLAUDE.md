# huh — explain terminal errors in plain English

## What this is
A CLI tool: when a command fails, the user types `huh` and gets a short
plain-English diagnosis of the error plus a suggested fix command they can
run with one keypress. Zero copy-paste, zero prompt writing.

## Principles (non-negotiable)
- Never run a fix or re-run a command without explicit user confirmation.
- Redact secrets (API keys, tokens, passwords, .env values, credentials in
  URLs) before anything is sent to an LLM.
- Fast: the answer should start streaming within ~2 seconds.
- Output is short: diagnosis in 1–3 sentences, then the fix. No essays.
- Works with no config beyond an API key.

## Stack
- Python 3.10+, managed with uv
- Typer (CLI), Rich (output), httpx (HTTP)
- pytest for tests, ruff for lint/format
- Config: ~/.config/huh/config.toml; env vars override config

## Architecture
src/huh/
  cli.py      — Typer entry point
  capture.py  — getting the failed command's output (pipe, re-run, scrollback)
  denylist.py — commands that are never re-run
  shell.py    — shell hook scripts printed by `wtf init <shell>`
  wizard.py   — `wtf setup`
  context.py  — environment info (OS, shell, cwd, tool versions, project files)
  redact.py   — secret redaction
  trim.py     — shrinking long output (keep first error lines + last ~50 lines)
  llm/        — provider interface + implementations: openai_responses (default
                format), anthropic; endpoint URL is configurable
  prompt.py   — builds the LLM prompt, parses diagnosis + fix
  render.py   — Rich output and the "Run it? [y/N]" prompt

## Roadmap
- v0.1: pipe mode (`cmd 2>&1 | huh`), OpenAI Responses format (default) and
  Anthropic format with a configurable endpoint, diagnosis + fix + confirm
- v0.2 (done early): `wtf` command, `wtf setup`, shell hooks (zsh, bash) via
  `eval "$(wtf init zsh)"`, re-run with confirmation, deny-list (denylist.py)
  of dangerous commands never re-run
- v0.3: tmux scrollback capture (no re-run needed) — public launch
- v0.4: Ollama (offline mode), fish shell

## Working style
- Small, focused modules; type hints everywhere.
- Write tests for redact, trim, prompt parsing, and context gathering.
  Mock all LLM calls in tests.
- Run `uv run pytest` and `uv run ruff check` before saying a task is done.
- Ask before adding new dependencies.
