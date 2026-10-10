# huh (`wtf`)

When a command fails, type `wtf`. It explains the error in plain English and suggests one fix command, which you can run with a single keypress. (`huh` is the same command under a calmer name.)

## Install

```bash
uv tool install git+https://github.com/<you>/huh
wtf setup
```

`wtf setup` asks five things: API format, endpoint, model, API key, and answer language (English or 简体中文). You type the key yourself and it's hidden as you type. The settings are saved to `~/.config/huh/config.toml`, readable only by you. Setup then offers to add one line to `~/.zshrc` (or `~/.bash_profile`) and can send a tiny test request. Open a new terminal tab afterwards.

The endpoint can be a base URL: `https://gw.example` becomes `https://gw.example/v1/responses`. The default is OpenAI's Responses API. See [Endpoints and formats](#endpoints-and-formats).

## Usage

```console
$ python -c "import requests"
ModuleNotFoundError: No module named 'requests'
$ wtf
Last command (exit 1): python -c "import requests"
Re-run it to capture the error? [y/N] y
huh? The `requests` package isn't installed in this environment.

╭─ Suggested fix ──────────╮
│ uv add requests          │
╰──────────────────────────╯
Run it? [y/N]
```

**How it sees your last command.** The shell hook remembers the last command line and its exit status. A shell can't read back output that has already been printed, so `wtf` asks before running the command again to capture it.

**Safety:**
- Nothing ever runs without an explicit `y`. The default answer is No, for both the re-run and the fix.
- Some commands are never re-run, even if you say yes: anything that deletes, moves, pushes, publishes, deploys, uses `sudo`, writes files with `>`, pipes into a shell, and so on. For those, `wtf` tells you to pipe the output instead.
- Re-runs have stdin closed and stop after 120 seconds.

**Piping** works anywhere, with or without the hook:

```bash
npm run build 2>&1 | wtf
pytest 2>&1 | wtf --cmd pytest
```

`2>&1` includes stderr, which is where most errors go. `--cmd` tells huh what you ran.

## Endpoints and formats

| Setting | Flag | Env var | Config key | Default |
|---|---|---|---|---|
| Request format | `--api-format` | `HUH_API_FORMAT` | `api_format` | `openai-responses` |
| Request URL | `--endpoint`, `-e` | `HUH_ENDPOINT` | `endpoint` | depends on the format, see below |
| Model | `--model`, `-m` | `HUH_MODEL` | `model` | depends on the format, see below |
| API key | | `HUH_API_KEY` | `api_key` | see below |
| Answer language | `--lang`, `-l` | `HUH_LANGUAGE` | `language` | `en` (or `zh-CN`) |

Precedence: flag > env var > config file > default.

| Format | Default endpoint | Default model | Vendor key |
|---|---|---|---|
| `openai-responses` | `https://api.openai.com/v1/responses` | `gpt-5-mini` | `OPENAI_API_KEY` |
| `anthropic` | `https://api.anthropic.com/v1/messages` | `claude-haiku-5-5` | `ANTHROPIC_API_KEY` |

`--endpoint` takes the full request URL, so any server that speaks one of these formats works, such as a gateway, a proxy or a local model server:

```bash
cargo build 2>&1 | huh -e http://localhost:8080/v1/responses -m my-local-model
```

**Keys:** `HUH_API_KEY` (or `api_key` in the config file) is sent to whatever endpoint you configure. The vendor variables `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are only sent to that vendor's own host, so pointing huh at a custom endpoint never leaks them. A custom endpoint with no key gets no auth header.

`wtf setup` writes `~/.config/huh/config.toml`, or you can edit it by hand:

```toml
api_format = "openai-responses"
endpoint = "https://api.openai.com/v1/responses"
model = "gpt-5-mini"
language = "en"          # or "zh-CN" for 简体中文
# api_key = "..."   # prefer an env var
```

## Privacy

**What is sent** to the configured endpoint (OpenAI by default), and nowhere else:

- the piped output, trimmed when it's long: lines with error markers plus the last ~50 lines
- the `--cmd` value, if you pass one
- your OS, shell name and current directory path
- the version of the tool involved (e.g. `node -v` for npm errors)
- the first ~40 lines of `package.json`, `pyproject.toml`, `requirements.txt` and `Dockerfile` if they're in the current directory

**What is redacted first.** Everything above goes through a regex redactor before it leaves your machine. Matches are replaced with `[REDACTED]`:

- Anthropic (`sk-ant-…`), OpenAI (`sk-…`, `sk-proj-…`), GitHub (`ghp_…`, `github_pat_…`, etc.), AWS access key IDs and Slack tokens
- `Authorization: Bearer/Basic …` headers and bare bearer tokens
- passwords in URLs (`postgres://user:[REDACTED]@host`)
- PEM private keys
- secret-looking assignments: `API_KEY=…`, `DB_PASSWORD: …`, `"apiKey": "…"`, `--token …`, etc.

Redaction is pattern-based. It catches common formats, not everything. If you're piping output that contains unusual secrets, check it first.

Nothing is stored or logged by huh. With the Responses format, requests set `"store": false`, which asks OpenAI not to keep the response.

## Development

```bash
uv sync
uv run pytest
uv run ruff check
uv tool install --editable .   # puts `wtf` on your PATH, tracking your checkout
```
