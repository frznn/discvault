#!/usr/bin/env python3
"""Generate the DiscVault man page and shell completions from the argparse parser."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from discvault import __version__
from discvault.cli import build_parser


PATH_COMPLETIONS = {
    "device": "file",
    "base_dir": "dir",
    "work_dir": "dir",
    "metadata_file": "file",
}


def main(argv: list[str] | None = None) -> int:
    args = _build_script_parser().parse_args(argv)
    parser = build_parser()
    assets = {
        ROOT / "share" / "man" / "man1" / "discvault.1": generate_man_page(parser),
        ROOT / "share" / "bash-completion" / "completions" / "discvault": generate_bash_completion(parser),
        ROOT / "share" / "zsh" / "site-functions" / "_discvault": generate_zsh_completion(parser),
        ROOT / "share" / "fish" / "vendor_completions.d" / "discvault.fish": generate_fish_completion(parser),
    }
    mismatches: list[Path] = []
    for path, text in assets.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                mismatches.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if args.check and mismatches:
        for path in mismatches:
            print(f"Out of date: {path.relative_to(ROOT)}")
        return 1
    return 0


def _build_script_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify generated assets are up to date")
    return parser


def generate_man_page(parser: argparse.ArgumentParser) -> str:
    lines = [
        '.TH DISCVAULT 1 "" "discvault %s" "User Commands"' % _roff_escape(__version__),
        ".SH NAME",
        "discvault \\- Linux CD archiver with CLI and Textual TUI",
        ".SH SYNOPSIS",
        ".B discvault",
        "[options]",
        ".SH DESCRIPTION",
        _roff_escape(parser.description or ""),
    ]
    for title, actions in _grouped_actions(parser):
        if not actions:
            continue
        section_title = "OPTIONS" if title.lower() == "options" else title.upper()
        lines.append(f".SH {_roff_escape(section_title)}")
        for action in actions:
            option_text = _man_option_text(action)
            lines.append(".TP")
            lines.append(option_text)
            lines.append(_roff_escape(action.help or ""))
    return "\n".join(lines) + "\n"


def generate_bash_completion(parser: argparse.ArgumentParser) -> str:
    actions = _visible_option_actions(parser)
    option_words = " ".join(_all_option_strings(actions))
    path_cases = []
    for action in actions:
        completion_kind = PATH_COMPLETIONS.get(action.dest)
        if not completion_kind or not _takes_value(action):
            continue
        options = "|".join(action.option_strings)
        compgen_mode = "-d" if completion_kind == "dir" else "-f"
        path_cases.append(f"        {options}) COMPREPLY=($(compgen {compgen_mode} -- \"$cur\")); return 0 ;;")
    path_case_block = "\n".join(path_cases)
    return f"""# shellcheck shell=bash
_discvault_completions() {{
    local cur prev
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"

    case "$prev" in
{path_case_block}
    esac

    if [[ "$cur" == -* ]]; then
        COMPREPLY=($(compgen -W "{option_words}" -- "$cur"))
    fi
}}

complete -F _discvault_completions discvault
"""


def generate_zsh_completion(parser: argparse.ArgumentParser) -> str:
    entries = []
    for action in _visible_option_actions(parser):
        help_text = (action.help or "").replace("[", "\\[").replace("]", "\\]")
        option_bits = []
        for option in action.option_strings:
            if _takes_value(action):
                option_bits.append(f"{option}[{help_text}]:{_zsh_metavar(action)}:{_zsh_completion(action)}")
            else:
                option_bits.append(f"{option}[{help_text}]")
        if option_bits:
            entries.append("  " + " \\\n  ".join(_zsh_quote(bit) for bit in option_bits))
    body = " \\\n".join(entries)
    return f"""#compdef discvault

_discvault() {{
  _arguments -s \\
{body}
}}

_discvault "$@"
"""


def generate_fish_completion(parser: argparse.ArgumentParser) -> str:
    lines = ["# fish completion for discvault"]
    for action in _visible_option_actions(parser):
        parts = ["complete", "-c", "discvault"]
        for option in action.option_strings:
            if option.startswith("--"):
                parts.extend(["-l", option[2:]])
            elif option.startswith("-"):
                parts.extend(["-s", option[1:]])
        if _takes_value(action):
            parts.append("-r")
        help_text = action.help or ""
        if help_text:
            parts.extend(["-d", _fish_quote(help_text)])
        lines.append(" ".join(parts))
    return "\n".join(lines) + "\n"


def _grouped_actions(parser: argparse.ArgumentParser) -> list[tuple[str, list[argparse.Action]]]:
    groups: list[tuple[str, list[argparse.Action]]] = []
    for group in parser._action_groups:  # noqa: SLF001 - argparse stores group membership here
        actions = [
            action for action in group._group_actions  # noqa: SLF001 - argparse stores group actions here
            if action.option_strings and action.help is not argparse.SUPPRESS
        ]
        if actions:
            groups.append((group.title or "options", actions))
    return groups


def _visible_option_actions(parser: argparse.ArgumentParser) -> list[argparse.Action]:
    return [
        action for action in parser._actions  # noqa: SLF001 - argparse stores actions here
        if action.option_strings and action.help is not argparse.SUPPRESS
    ]


def _all_option_strings(actions: list[argparse.Action]) -> list[str]:
    option_strings: list[str] = []
    for action in actions:
        option_strings.extend(action.option_strings)
    return option_strings


def _takes_value(action: argparse.Action) -> bool:
    return not isinstance(
        action,
        (
            argparse._HelpAction,  # noqa: SLF001
            argparse._StoreTrueAction,  # noqa: SLF001
            argparse._StoreFalseAction,  # noqa: SLF001
            argparse._VersionAction,  # noqa: SLF001
        ),
    )


def _man_option_text(action: argparse.Action) -> str:
    parts = []
    metavar = _display_metavar(action)
    for option in action.option_strings:
        if _takes_value(action):
            parts.append(f"\\fB{_roff_escape(option)}\\fR {metavar}")
        else:
            parts.append(f"\\fB{_roff_escape(option)}\\fR")
    return ", ".join(parts)


def _display_metavar(action: argparse.Action) -> str:
    if action.metavar:
        return _roff_escape(str(action.metavar))
    return _roff_escape(action.dest.upper().replace("_", "-"))


def _zsh_metavar(action: argparse.Action) -> str:
    if action.metavar:
        return str(action.metavar).lower()
    return action.dest.replace("_", "-")


def _zsh_completion(action: argparse.Action) -> str:
    completion_kind = PATH_COMPLETIONS.get(action.dest)
    if completion_kind == "dir":
        return "_files -/"
    if completion_kind == "file":
        return "_files"
    return ""


def _fish_quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _roff_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("-", "\\-")


def _zsh_quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
    return f'"{escaped}"'


if __name__ == "__main__":
    raise SystemExit(main())
