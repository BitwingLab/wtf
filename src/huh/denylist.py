"""Commands that are never re-run automatically, even with confirmation.

Re-running is only for capturing output. Anything that changes state in a way
that is destructive, hard to undo, outward-facing, or privileged is refused, and
the user is told to pipe the output in instead.
"""

from __future__ import annotations

import re
import shlex

# First word of a command segment -> always refused.
_DENY_PROGRAMS = {
    "rm", "rmdir", "mv", "dd", "mkfs", "shred", "truncate", "srm", "unlink",
    "sudo", "su", "doas", "chmod", "chown", "chgrp", "chflags",
    "kill", "killall", "pkill", "shutdown", "reboot", "halt", "launchctl", "diskutil",
    "ssh", "scp", "sftp", "rsync", "ftp",
    "crontab", "passwd", "security", "defaults",
    "vi", "vim", "nvim", "nano", "emacs", "less", "more", "top", "htop", "man",
    "tee", "xargs", "wget", "open", "osascript", "eval", "source", ".",
}  # fmt: skip

# Programs where only certain subcommands or flags are dangerous. If any argument
# matches, the command is refused ("*" refuses the program outright). Erring
# towards refusing is fine: the user can always pipe the output in instead.
_DENY_SUBCOMMANDS: dict[str, set[str]] = {
    "git": {
        "push", "reset", "clean", "checkout", "switch", "restore", "rebase", "merge",
        "commit", "stash", "rm", "mv", "tag", "branch", "cherry-pick", "revert",
        "am", "apply", "pull", "filter-branch", "gc", "prune", "update-ref", "worktree",
    },
    "gh": {"pr", "release", "repo", "issue", "api", "secret", "workflow", "auth"},
    "npm": {"publish", "unpublish", "deprecate", "uninstall", "rm", "remove", "un", "login"},
    "yarn": {"publish", "remove", "npm"},
    "pnpm": {"publish", "remove", "rm", "uninstall"},
    "cargo": {"publish", "yank", "uninstall", "login", "owner"},
    "pip": {"uninstall"},
    "pip3": {"uninstall"},
    "uv": {"publish", "remove"},
    "poetry": {"publish", "remove"},
    "twine": {"upload", "register"},
    "brew": {"uninstall", "remove", "rm", "cleanup", "untap"},
    "docker": {
        "rm", "rmi", "push", "kill", "stop", "prune", "system", "volume", "network", "login",
    },
    "kubectl": {"delete", "apply", "create", "replace", "patch", "scale", "drain", "edit", "exec"},
    "helm": {"install", "upgrade", "uninstall", "delete", "rollback"},
    "terraform": {"apply", "destroy", "import", "taint", "state"},
    "aws": {"*"},
    "gcloud": {"*"},
    "az": {"*"},
    "heroku": {"*"},
    "vercel": {"*"},
    "fly": {"*"},
    "firebase": {"deploy"},
    "find": {"-delete", "-exec", "-execdir", "-ok", "-okdir"},
    "sed": {"-i", "--in-place"},
    "perl": {"-i"},
    "curl": {
        "-X", "--request", "-d", "--data", "--data-raw", "--data-binary", "--json",
        "-F", "--form", "-T", "--upload-file", "-o", "--output", "-O", "--remote-name",
    },
}  # fmt: skip

# Wrappers to skip past when finding the real program.
_WRAPPERS = {"command", "builtin", "time", "nohup", "nice", "exec", "env", "caffeinate"}

_SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|&\n]")
# A `>` that writes a file; fd duplication like 2>&1 or >&2 is fine.
_FILE_REDIRECT = re.compile(r"&>|(?<![0-9&])>>?(?!&)|[0-9]>>?(?!&)")
_HARMLESS_REDIRECTS = re.compile(r"[0-9]?>&[0-9]|[0-9&]?>>?\s*/dev/null")
_SQL_DANGER = re.compile(r"(?i)\b(?:drop|truncate|delete\s+from|alter\s+table)\b")
_PIPE_TO_SHELL = re.compile(r"\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh\b")


def _program(words: list[str]) -> tuple[str, list[str]]:
    i = 0
    while i < len(words):
        word = words[i]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", word) or word in _WRAPPERS:
            i += 1
            continue
        if words[i - 1 : i] == ["env"] and word.startswith("-"):
            i += 1
            continue
        break
    if i >= len(words):
        return "", []
    return words[i].rsplit("/", 1)[-1], words[i + 1 :]


def check_rerun(command: str) -> str | None:
    """Return why ``command`` must not be re-run, or None if re-running is allowed."""
    command = command.strip()
    if not command:
        return "there is no command to re-run"
    if _PIPE_TO_SHELL.search(command):
        return "it pipes into a shell"
    if _FILE_REDIRECT.search(_HARMLESS_REDIRECTS.sub("", command)):
        return "it writes to a file with >"
    if _SQL_DANGER.search(command):
        return "it looks like it modifies a database"
    if "$(" in command or "`" in command:
        return "it contains command substitution"

    for segment in _SEGMENT_SPLIT.split(command):
        segment = segment.strip().lstrip("(").rstrip(")").strip()
        if not segment:
            continue
        try:
            words = shlex.split(segment)
        except ValueError:
            return "it couldn't be parsed safely"
        prog, args = _program(words)
        if not prog:
            continue
        if prog in _DENY_PROGRAMS:
            return f"`{prog}` can change or delete things"
        subs = _DENY_SUBCOMMANDS.get(prog)
        if subs is None:
            continue
        if "*" in subs:
            return f"`{prog}` can change things outside this terminal"
        for arg in args:
            if _matches(arg, subs):
                return f"`{prog} {arg}` can change things"
    return None


def _matches(arg: str, subs: set[str]) -> bool:
    if arg in subs:
        return True
    # Short flags with attached values: -XPOST, -i.bak, -dfoo=bar
    return any(len(s) == 2 and s.startswith("-") and arg.startswith(s) for s in subs)
