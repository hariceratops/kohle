"""Issue 054: no test reads or writes the developer's real kohle files."""

import os
import sys
from pathlib import Path
from urllib.parse import unquote

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


def _record_invocations(write_init_rc, *extra: str) -> list[Path]:
    global _recorded
    write_init_rc('state = "BW"\n')
    runner = CliRunner()
    _recorded = []
    try:
        runner.invoke(cli, ["init"])
        runner.invoke(cli, ["list-accounts"])
        runner.invoke(cli, ["--help"])
        for command in extra:
            runner.invoke(cli, [command])
        return _recorded
    finally:
        _recorded = None


def test_commands_never_touch_the_real_kohle_directories(write_init_rc) -> None:
    recorded = _record_invocations(write_init_rc)

    assert recorded
    real = [
        path
        for path in recorded
        if any(path.absolute().is_relative_to(directory) for directory in _REAL_DIRS)
    ]
    assert real == []


def test_temp_config_toml_is_among_the_recorded_opens(write_init_rc, tmp_path: Path) -> None:
    recorded = _record_invocations(write_init_rc)

    assert tmp_path / "xdg-config" / "kohle" / "config.toml" in recorded


def test_list_config_never_touches_the_real_kohle_directories(write_init_rc) -> None:
    recorded = _record_invocations(write_init_rc, "list-config")

    real = [
        path
        for path in recorded
        if any(path.absolute().is_relative_to(directory) for directory in _REAL_DIRS)
    ]
    assert real == []
