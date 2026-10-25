"""Issue 054: no test reads or writes the developer's real kohle files."""

import os
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest
from click.testing import CliRunner

from kohle.app.cli.cli import cli


def _real_kohle_dir(env_var: str, home_subdir: str) -> Path:
    base = os.environ.get(env_var) or Path.home() / home_subdir
    return Path(base) / "kohle"


# Captured at import, before any fixture redirects the environment.
_REAL_DIRS = (
    _real_kohle_dir("XDG_CONFIG_HOME", ".config"),
    _real_kohle_dir("XDG_DATA_HOME", ".local/share"),
)

# Audit hooks cannot be removed; recording only while this is a list scopes it.
_recorded: list[Path] | None = None


def _sqlite_path(name: str) -> Path:
    if name.startswith("file:"):
        name = unquote(name.removeprefix("file:").split("?", 1)[0])
    return Path(name)


def _audit(event: str, args: tuple) -> None:
    if _recorded is None:
        return
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        _recorded.append(Path(os.fsdecode(args[0])))
    elif event == "sqlite3.connect" and isinstance(args[0], str):
        _recorded.append(_sqlite_path(args[0]))


sys.addaudithook(_audit)


def test_commands_never_touch_the_real_kohle_directories(write_init_rc) -> None:
    global _recorded
    write_init_rc('state = "BW"\n')
    runner = CliRunner()
    _recorded = []
    try:
        runner.invoke(cli, ["init"])
        runner.invoke(cli, ["list-accounts"])
        runner.invoke(cli, ["--help"])
        recorded = _recorded
    finally:
        _recorded = None

    assert recorded
    real = [
        path
        for path in recorded
        if any(path.absolute().is_relative_to(directory) for directory in _REAL_DIRS)
    ]
    assert real == []


@pytest.mark.skip(reason="055: not implemented")
def test_temp_config_toml_is_among_the_recorded_opens() -> None:
    # TODO(055): positive assertion that the redirect is used (design 15.1).
    ...


@pytest.mark.skip(reason="057: not implemented")
def test_list_config_never_touches_the_real_kohle_directories() -> None:
    # TODO(057): add list-config to the invocations (design 15.1).
    ...
