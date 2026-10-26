"""Device settings: facts about one machine, read from `config.toml`.

They never travel with a copy of the ledger, and kohle never writes the file.
Ledger-wide settings are a separate registry, `SETTINGS` in
`kohle/use_cases/settings.py`.
"""

import os
import tomllib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    BadConfigFile,
    InvalidDeviceValue,
    UnknownDeviceKey,
)


def config_dir() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    return (Path(config_home) if config_home else Path.home() / ".config") / "kohle"


def config_path() -> Path:
    return config_dir() / "config.toml"


@dataclass(frozen=True, slots=True)
class DeviceKey:
    validate: Callable[[object], Result[object, InvalidDeviceValue]]
    default: Callable[[], object]


def _ledger_path_value(value: object) -> Result[object, InvalidDeviceValue]:
    # os.path.expanduser, not Path.expanduser: an unexpandable ~user is left
    # as is (and then rejected as relative) instead of raising RuntimeError.
    if isinstance(value, str):
        path = Path(os.path.expanduser(value))
        if path.is_absolute():
            return Result.ok(path)
    return Result.err(InvalidDeviceValue("ledger.path", value, "an absolute path, or one starting with ~"))


def _default_ledger_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    data_dir = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return data_dir / "kohle" / "kohle.db"


# Separate from the ledger SETTINGS in kohle/use_cases/settings.py.
DEVICE_KEYS: dict[str, DeviceKey] = {
    "ledger.path": DeviceKey(_ledger_path_value, _default_ledger_path),
}


def _flatten(table: Mapping[str, object], prefix: str = "") -> Iterator[tuple[str, object]]:
    for name, value in table.items():
        # A quoted key with a dot in it ("ledger.path" = ...) is a different
        # TOML key from the dotted one, so it is shown quoted and never
        # matches a registered key.
        key = prefix + (f'"{name}"' if "." in name else name)
        # A registered key's value is taken whole, so `ledger.path = {}`
        # reaches the validator instead of vanishing as an empty table.
        if isinstance(value, dict) and key not in DEVICE_KEYS:
            yield from _flatten(value, f"{key}.")
        else:
            yield key, value


def validate_device_config(raw: Mapping[str, object]) -> Result[dict[str, object], UnknownDeviceKey | InvalidDeviceValue]:
    values: dict[str, object] = {}
    for key, value in _flatten(raw):
        if key not in DEVICE_KEYS:
            return Result.err(UnknownDeviceKey(key, list(DEVICE_KEYS)))
        validated = DEVICE_KEYS[key].validate(value)
        if validated.is_err:
            return Result.err(validated.unwrap_err())
        values[key] = validated.unwrap()
    return Result.ok(values)


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    path: Path
    found: bool
    values: dict[str, object]


def load_device_config() -> Result[DeviceConfig, BadConfigFile]:
    path = config_path()
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        return Result.ok(DeviceConfig(path, found=False, values={}))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        return Result.err(BadConfigFile(path, str(e)))
    except OSError as e:
        return Result.err(BadConfigFile(path, e.strerror or str(e)))
    return (
        validate_device_config(raw)
        .map(lambda values: DeviceConfig(path, found=True, values=values))
        .map_err(lambda err: BadConfigFile(path, err))
    )


Source = Literal["default", "file", "KOHLE_DB"]


@dataclass(frozen=True, slots=True)
class Effective:
    value: object
    source: Source


def effective(config: DeviceConfig, key: str) -> Effective:
    """`key` must be in DEVICE_KEYS."""
    # KOHLE_DB predates config.toml. It is the only environment variable that
    # overrides a device key, and the spec adds no others. It is taken as
    # given, unvalidated, as it was before this file existed.
    if key == "ledger.path" and (db := os.environ.get("KOHLE_DB")):
        return Effective(Path(db), "KOHLE_DB")
    if key in config.values:
        return Effective(config.values[key], "file")
    return Effective(DEVICE_KEYS[key].default(), "default")
