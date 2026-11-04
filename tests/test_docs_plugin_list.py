import importlib.util
from collections.abc import Sequence
from importlib.metadata import EntryPoint, EntryPoints, entry_points
from pathlib import Path
from types import ModuleType

import pytest

from kohle.core.result import Result
from kohle.plugin.importer_plugin import (
    ImportError,
    StatementImporterPlugin,
    StatementRow,
)
from kohle.plugin.plugin_manager import load_plugins, load_price_plugins
from kohle.plugin.price_plugin import PriceFetcherPlugin, PriceFetchError, PriceResult

HOOK = Path(__file__).resolve().parent.parent / "docs" / "hooks" / "plugin_list.py"


class StubImporter(StatementImporterPlugin):
    """A fictional ledger export, tab-separated.

    A second paragraph that the table must not show.
    """

    @property
    def name(self) -> str:
        return "stub-importer"

    def import_statement(self, statement_path: str) -> Result[list[StatementRow], ImportError]:
        return Result.ok([])


class UndocumentedPriceStub(PriceFetcherPlugin):
    @property
    def name(self) -> str:
        return "stub-price"

    def fetch_latest_closes(self, symbols: Sequence[str]) -> Result[dict[str, PriceResult], PriceFetchError]:
        return Result.ok({})


def _load_hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("plugin_list_hook", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _with_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    extra = [
        EntryPoint(name="stub-importer", value=f"{__name__}:StubImporter", group="kohle.plugins"),
        EntryPoint(name="stub-price", value=f"{__name__}:UndocumentedPriceStub", group="kohle.plugins"),
    ]

    def fake(*, group: str) -> EntryPoints:
        return EntryPoints([*entry_points(group=group), *extra])

    monkeypatch.setattr("kohle.plugin.plugin_manager.entry_points", fake)


def _row(table: str, name: str) -> list[str]:
    line = next(line for line in table.splitlines() if line.startswith(f"| {name} "))
    return [cell.strip() for cell in line.strip("|").split("|")]


def test_a_newly_installed_plugin_appears_without_a_docs_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_stubs(monkeypatch)

    table = _load_hook().plugin_table()

    assert _row(table, "stub-importer") == ["stub-importer", "importer", "A fictional ledger export, tab-separated."]
    assert _row(table, "stub-price") == ["stub-price", "price", "not stated by the plugin"]


def test_the_table_lists_the_bundled_plugins_by_kind_then_name() -> None:
    table = _load_hook().plugin_table()

    names = [line.strip("|").split("|")[0].strip() for line in table.splitlines()[2:]]
    assert names == ["kohle-deutsche-bank", "kohle-simple-broker", "alphavantage", "file"]


def test_the_hook_replaces_the_placeholder() -> None:
    hook = _load_hook()

    page = hook.on_page_markdown(f"before\n{hook.PLACEHOLDER}\nafter", page=None, config=None, files=None)

    assert hook.PLACEHOLDER not in page
    assert "| kohle-deutsche-bank |" in page


@pytest.mark.parametrize("plugin", [*load_plugins().values(), *load_price_plugins().values()], ids=lambda p: p.name)
def test_every_bundled_plugin_states_what_it_accepts(plugin: object) -> None:
    assert (type(plugin).__doc__ or "").strip()
