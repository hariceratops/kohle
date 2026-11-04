"""Checked documentation examples: parse `console` fences out of the markdown pages and run them.

Syntax (design dev/design/cli-documentation.md §4; this docstring is the
authoritative description for page authors).

A checked example is any fenced block whose info string is `console`:

    ```console
    $ kohle-cli add-account Checking --type asset
    Added account Checking (asset) with id 2
    ```

- A line beginning with `$ ` is a command; one ending in ` \\` continues on
  the next line. The lines after it, up to the next `$ ` line or the end of
  the block, are its expected output. The language tag is the only marker.
  Install lines and config snippets go in `sh` / `toml` fences and are never run.
- Each example runs against a fresh scratch home and a fresh ledger made by
  `kohle-cli init` (`KOHLE_DB` points at it). Every file in `docs/examples/`
  is copied into the home, which is also the working directory, so commands
  refer to `statement.csv` directly. Today is pinned to DOCS_TODAY and the
  network is blocked. Pass explicit `--from` / `--to` where a command takes
  them, so a reader reproducing the session later gets the same rows.
- Comparison is exact except that the scratch home prints as `~`, lines are
  right-stripped and trailing blank lines are dropped. The first mismatch
  stops the example. Exit codes are not compared.
- Commands may start with `NAME=value` assignments, which apply to that
  command only. A token starting with `~` is expanded against the scratch home.
  Only `kohle-cli` may be run, shell operators (`| && ; > <`) are not
  supported, and commands that prompt must pass `--yes`.

Options go in an HTML comment on the line directly above a fence:

    <!-- docs: file PATH -->            non-console fence: its content is the
                                        page file PATH (relative to the home,
                                        `~/` allowed, no `..`)
    <!-- docs: uses PATH [PATH ...] --> console: write those page files first
                                        (latest `file` fence earlier on the page)
    <!-- docs: first-run -->           console: no init file, no ledger; the
                                        block runs `kohle-cli init` itself
    <!-- docs: illustration -->        non-console: shows `kohle-cli` lines on
                                        purpose and is not run

`first-run` and `uses` combine in one comment. Anything else is a problem.
A `$ kohle-cli` line outside a console fence is also a problem, so no shown
invocation escapes checking.
"""

import difflib
import os
import re
import shlex
import shutil
import socket
import traceback
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from markdown_it import MarkdownIt

from kohle.app.cli.cli import cli

DOCS_TODAY = date(2026, 6, 17)
INIT_TOML = 'state = "BW"\n'

_OPTION_COMMENT = re.compile(r"^\s*<!--\s*docs:\s*(.*?)\s*-->\s*$")
_INVOCATION = re.compile(r"^\s*\$ (\w+=\S+ )*kohle-cli\b")
_ASSIGNMENT = re.compile(r"^\w+=")
_OPERATOR_TOKEN = re.compile(r"^[();<>|&]+$")
_KEYWORDS = {"file", "uses", "first-run", "illustration"}


@dataclass(frozen=True, slots=True)
class Command:
    line: int
    text: str
    expected: list[str]


@dataclass(frozen=True, slots=True)
class Example:
    page: str
    line: int
    first_run: bool
    files: dict[str, str]
    commands: list[Command]


@dataclass(frozen=True, slots=True)
class _Options:
    file: str | None = None
    uses: tuple[str, ...] = ()
    first_run: bool = False
    illustration: bool = False


def _home_relative(path: str) -> str | None:
    relative = path.removeprefix("~/")
    parts = Path(relative).parts
    if Path(relative).is_absolute() or ".." in parts or not parts:
        return None
    return relative


def _parse_options(words: list[str]) -> _Options | str:
    if not words or words[0] not in _KEYWORDS:
        return f"unknown option {' '.join(words)!r}"
    if words[0] == "file":
        if len(words) != 2:
            return "`file` takes exactly one PATH"
        return _Options(file=words[1])
    if words[0] == "illustration":
        return _Options(illustration=True) if len(words) == 1 else "`illustration` takes no arguments"
    first_run = words[0] == "first-run"
    rest = words[1:] if first_run else words
    if not rest:
        return _Options(first_run=True)
    if rest[0] != "uses" or len(rest) == 1:
        return f"unknown option {' '.join(words)!r}"
    return _Options(first_run=first_run, uses=tuple(rest[1:]))


def split_command(text: str) -> tuple[dict[str, str], list[str]] | str:
    """Return (env, args after `kohle-cli`), or a message saying what to do instead."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as error:
        return f"cannot parse {text!r}: {error}"
    if any(_OPERATOR_TOKEN.match(token) for token in tokens):
        return f"shell operators are not supported in {text!r}; show the effect in prose or a file fence"
    env: dict[str, str] = {}
    while tokens and _ASSIGNMENT.match(tokens[0]):
        name, _, value = tokens.pop(0).partition("=")
        env[name] = value
    if not tokens or tokens[0] != "kohle-cli":
        return f"only kohle-cli can be run, not {text!r}; use an sh fence for other commands"
    return env, tokens[1:]


def _commands(page: str, fence_line: int, content: str) -> tuple[list[Command], list[str]]:
    commands: list[Command] = []
    problems: list[str] = []
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("$ "):
            problems.append(f"{page}:{fence_line + 1 + index}: output before the first `$ ` command")
            index += 1
            continue
        start = index
        text = line[2:].rstrip()
        while text.endswith("\\") and index + 1 < len(lines):
            index += 1
            text = text[:-1].rstrip() + " " + lines[index].strip()
        index += 1
        expected: list[str] = []
        while index < len(lines) and not lines[index].startswith("$ "):
            expected.append(lines[index])
            index += 1
        number = fence_line + 1 + start
        split = split_command(text)
        if isinstance(split, str):
            problems.append(f"{page}:{number}: {split}")
        commands.append(Command(number, text, expected))
    return commands, problems


def parse_page(page: str, text: str) -> tuple[list[Example], list[str]]:
    raw = text.split("\n")
    fences = [t for t in MarkdownIt("commonmark").parse(text) if t.type == "fence" and t.map]
    problems: list[str] = []
    examples: list[Example] = []
    page_files: dict[str, str] = {}
    inside = set()

    for token in fences:
        start, end = token.map
        inside.update(range(start, end))
        fence_line = start + 1
        options = _Options()
        if start > 0 and (match := _OPTION_COMMENT.match(raw[start - 1])):
            parsed = _parse_options(match.group(1).split())
            if isinstance(parsed, str):
                problems.append(f"{page}:{start}: {parsed}")
            else:
                options = parsed
        is_console = token.info.split()[:1] == ["console"]

        if not is_console:
            if options.file is not None:
                relative = _home_relative(options.file)
                if relative is None:
                    problems.append(f"{page}:{start}: file path {options.file!r} must be relative with no `..`")
                else:
                    page_files[relative] = token.content
            if not options.illustration:
                for offset, line in enumerate(token.content.split("\n")):
                    if _INVOCATION.match(line):
                        problems.append(
                            f"{page}:{fence_line + 1 + offset}: kohle-cli shown outside a console block; "
                            "make it a console example or mark the fence `<!-- docs: illustration -->`"
                        )
            continue

        files: dict[str, str] = {}
        for name in options.uses:
            relative = _home_relative(name)
            if relative is None or relative not in page_files:
                problems.append(f"{page}:{start}: `uses {name}` has no earlier `file` fence on this page")
            else:
                files[relative] = page_files[relative]
        commands, command_problems = _commands(page, fence_line, token.content)
        problems.extend(command_problems)
        examples.append(Example(page, fence_line, options.first_run, files, commands))

    for number, line in enumerate(raw):
        if number not in inside and _INVOCATION.match(line):
            problems.append(f"{page}:{number + 1}: kohle-cli shown outside a fenced console block")
    return examples, problems


def collect(root: Path) -> tuple[list[Example], list[str]]:
    examples: list[Example] = []
    problems: list[str] = []
    for path in sorted((root / "docs").rglob("*.md")):
        page_examples, page_problems = parse_page(
            path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")
        )
        examples.extend(page_examples)
        problems.extend(page_problems)
    return examples, problems


def prepare_home(
    home: Path,
    example: Example,
    template_ledger: Path,
    samples: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build the starting state of design §4.3 in `home`; `monkeypatch` undoes it."""
    home.mkdir(parents=True)
    ledger = home / ".local" / "share" / "kohle" / "kohle.db"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("COLUMNS", "80")
    if example.first_run:
        monkeypatch.delenv("KOHLE_DB", raising=False)
    else:
        init = home / ".config" / "kohle" / "init.toml"
        init.parent.mkdir(parents=True)
        init.write_text(INIT_TOML)
        ledger.parent.mkdir(parents=True)
        shutil.copyfile(template_ledger, ledger)
        monkeypatch.setenv("KOHLE_DB", str(ledger))
    if samples.is_dir():
        shutil.copytree(samples, home, dirs_exist_ok=True)
    for relative, content in example.files.items():
        target = home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    monkeypatch.chdir(home)

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("network access in a docs example")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def _normalise(text: str, home: Path | None) -> list[str]:
    if home is not None:
        text = text.replace(str(home), "~")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def run_example(example: Example, home: Path) -> str | None:
    """Run each command in order; return failure text for the first mismatch, or None."""
    for command in example.commands:
        split = split_command(command.text)
        assert not isinstance(split, str), split  # parse_page reports these as problems
        env, args = split
        args = [os.path.expanduser(arg) if arg.startswith("~") else arg for arg in args]
        result = CliRunner().invoke(cli, args, env=env, prog_name="kohle-cli")
        actual = _normalise(result.output, home)
        expected = _normalise("\n".join(command.expected), None)
        if actual == expected:
            continue
        diff = difflib.unified_diff(
            expected, actual, "expected (page)", "actual", lineterm="", n=3
        )
        message = [
            (
                f"{example.page}:{command.line}: `{command.text}` printed something else "
                f"(example at line {example.line})"
            ),
            *diff,
        ]
        if result.exc_info and result.exception and not isinstance(result.exception, SystemExit):
            message.append("".join(traceback.format_exception(*result.exc_info)))
        return "\n".join(message)
    return None
