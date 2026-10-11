"""Layer 1 — pure unit tests, no fixture.

The price-fetcher contract and `plugin_manager` kind partitioning (issue 029). dev/design/price-fetcher-plugin.md §2, §3.
"""

from collections.abc import Sequence

import pytest

from kohle.core.result import Result
from kohle.plugin import plugin_manager
from kohle.plugin.importer_plugin import (
    ImportError,
    StatementImporterPlugin,
    StatementRow,
)
from kohle.plugin.price_plugin import PriceFetcherPlugin, PriceFetchError, PriceResult


def _importer(plugin_name: str) -> type[StatementImporterPlugin]:
    class Importer(StatementImporterPlugin):
        @property
        def name(self) -> str:
            return plugin_name

        def import_statement(self, statement_path: str) -> Result[list[StatementRow], ImportError]:
            return Result.ok([])

    return Importer


def _fetcher(plugin_name: str) -> type[PriceFetcherPlugin]:
    class Fetcher(PriceFetcherPlugin):
        @property
        def name(self) -> str:
            return plugin_name

        def fetch_latest_closes(
            self, symbols: Sequence[str]
        ) -> Result[dict[str, PriceResult], PriceFetchError]:
            return Result.ok({})

    return Fetcher


class _EntryPoint:
    def __init__(self, name: str, cls: type) -> None:
        self.name = name
        self._cls = cls

    def load(self) -> type:
        return self._cls


def _install(monkeypatch: pytest.MonkeyPatch, *classes: type) -> None:
    eps = [_EntryPoint(f"ep{i}", cls) for i, cls in enumerate(classes)]
    monkeypatch.setattr(plugin_manager, "entry_points", lambda group: eps)


def test_load_plugins_returns_only_importers(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _importer("broker"), _fetcher("file"))

    assert list(plugin_manager.load_plugins()) == ["broker"]
    assert list(plugin_manager.load_price_plugins()) == ["file"]


def test_a_name_shared_across_kinds_is_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _importer("same"), _fetcher("same"))

    assert list(plugin_manager.load_plugins()) == ["same"]
    assert list(plugin_manager.load_price_plugins()) == ["same"]


def test_class_of_neither_kind_raises_type_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _fetcher("file"), object)

    with pytest.raises(TypeError):
        plugin_manager.load_price_plugins()
    with pytest.raises(TypeError):
        plugin_manager.load_plugins()


def test_duplicate_name_within_a_kind_names_the_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _fetcher("dup"), _fetcher("dup"))

    with pytest.raises(ValueError, match="Duplicate plugin name: dup"):
        plugin_manager.load_price_plugins()
