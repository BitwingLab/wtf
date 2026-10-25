"""Shell integration printed by `wtf init <shell>`.

The hook remembers the last command line and its exit status, and wraps `wtf`
(and `huh`) so that typing it with nothing piped in explains that command.
Nothing is ever re-run by the hook itself; the CLI asks first.
"""

from __future__ import annotations

import sys

SUPPORTED = ("zsh", "bash")

_ZSH = r"""
# huh / wtf shell integration — https://github.com/BitwingLab/wtf
__huh_preexec() {
  case "$1" in
    wtf|wtf\ *|huh|huh\ *) __huh_skip=1 ;;
    *) __huh_skip=; __huh_cmd="$1" ;;
  esac
}
__huh_precmd() {
  local s=$?
  [[ -z "$__huh_skip" ]] && __huh_status=$s
  __huh_skip=
}
__huh_run() {
  local prog=$1; shift
  if [[ -t 0 && -n "$__huh_cmd" ]]; then
    command "$prog" --last-cmd "$__huh_cmd" --last-status "${__huh_status:-0}" "$@"
  else
    command "$prog" "$@"
  fi
}
wtf() { __huh_run wtf "$@"; }
huh() { __huh_run huh "$@"; }
autoload -Uz add-zsh-hook
add-zsh-hook preexec __huh_preexec
# Must run before other precmd hooks so it sees the command's real exit status.
precmd_functions=(__huh_precmd ${precmd_functions:#__huh_precmd})
"""

_BASH = r"""
# huh / wtf shell integration — https://github.com/BitwingLab/wtf
__huh_prompt() {
  local s=$? c
  c=$(HISTTIMEFORMAT= builtin history 1 2>/dev/null | sed -E 's/^ *[0-9]+\*? *//')
  case "$c" in
    ''|wtf|wtf\ *|huh|huh\ *) ;;
    *) __huh_cmd=$c; __huh_status=$s ;;
  esac
  return $s
}
__huh_run() {
  local prog=$1; shift
  if [[ -t 0 && -n "$__huh_cmd" ]]; then
    command "$prog" --last-cmd "$__huh_cmd" --last-status "${__huh_status:-0}" "$@"
  else
    command "$prog" "$@"
  fi
}
wtf() { __huh_run wtf "$@"; }
huh() { __huh_run huh "$@"; }
case ";${PROMPT_COMMAND};" in
  *";__huh_prompt;"*) ;;
  *) PROMPT_COMMAND="__huh_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
esac
"""


def init_script(shell: str) -> str:
    if shell == "zsh":
        return _ZSH.lstrip()
    if shell == "bash":
        return _BASH.lstrip()
    raise ValueError(f"Unsupported shell {shell!r}. Supported: {', '.join(SUPPORTED)}.")


def rc_file(shell: str) -> str:
    if shell == "zsh":
        return "~/.zshrc"
    # macOS Terminal starts bash as a login shell, which reads ~/.bash_profile.
    return "~/.bash_profile" if sys.platform == "darwin" else "~/.bashrc"


def init_line(shell: str, prog: str = "wtf") -> str:
    return f'eval "$({prog} init {shell})"'
