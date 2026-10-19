"""Layer 4 — structural guards.

Issue 034, design §11. The separation of recorded books from fetched prices is structural, so a test fails if someone wires them together.
"""

import ast
import inspect
import subprocess
import sys
import textwrap
from collections.abc import Callable, Iterator, Sequence
from datetime import date
from decimal import Decimal
from importlib.metadata import EntryPoint, EntryPoints, entry_points
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kohle.app.cli import cli as cli_module
from kohle.app.cli.cli import cli
from kohle.core.result import Result
from kohle.db.connection import base
from kohle.domain.models import Operation, OperationGroup, Price, Unit
from kohle.plugin.price_plugin import (
    Close,
    PriceFetcherPlugin,
    PriceFetchError,
    PriceResult,
)

ROOT = Path(__file__).parent.parent
FORBIDDEN_IDENTIFIERS = {"Price", "PriceBinding", "PriceFetcherPlugin", "load_price_plugins"}
PRICE_MODULES = ("kohle.plugin.price_plugin", "kohle.services.price_services", "kohle.use_cases.prices")
RECORDING_MODULES = (
    "kohle.use_cases.journal",
    "kohle.use_cases.classification",
    "kohle.use_cases.splitting",
    # Not a recording module: listed because realised gain must come from recorded prices only.
    "kohle.use_cases.lots",
)
PRICE_ENTRY_POINT_NAMES = {"file", "alphavantage"}


def _references(source: str) -> set[str]:
    """Every imported module, imported name and bare or attribute identifier in `source`."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(textwrap.dedent(source))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
                found.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            found.add(module)
            found.update(module.split("."))
            for alias in node.names:
                found.add(alias.name)
                found.add(f"{module}.{alias.name}")
        elif isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


def _guarded_sources() -> dict[str, str]:
    sources = {
        path: (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "kohle/use_cases/journal.py",
            "kohle/use_cases/classification.py",
            "kohle/use_cases/splitting.py",
            "kohle/use_cases/lots.py",
            "kohle/plugin/importer_plugin.py",
        )
    }
    callback = cli_module.import_statement.callback
    assert callback is not None
    sources["cli.import_statement"] = inspect.getsource(callback)
    return sources


@pytest.mark.parametrize("site", list(_guarded_sources()))
def test_recording_and_import_code_never_reference_prices(site: str) -> None:
    found = _references(_guarded_sources()[site])

    assert found & FORBIDDEN_IDENTIFIERS == set()
    for module in PRICE_MODULES:
        assert not any(name == module or name.startswith(f"{module}.") for name in found)


def test_the_ast_walk_is_exact_not_substring() -> None:
    assert _references("unit_price = 1\nx.from_price = 2") & FORBIDDEN_IDENTIFIERS == set()
    assert "Price" in _references("from kohle.domain.models import Price")
    assert "PriceBinding" in _references("import m\nm.PriceBinding")
    assert "kohle.use_cases.prices" in _references("import kohle.use_cases.prices")
    assert "kohle.use_cases.prices" in _references("from kohle.use_cases import prices")


def test_recording_use_cases_do_not_transitively_import_price_modules() -> None:
    code = (
        "import sys\n"
        + "".join(f"import {module}\n" for module in RECORDING_MODULES)
        + f"loaded = [m for m in {PRICE_MODULES!r} if m in sys.modules]\n"
        + "print(','.join(loaded))\n"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=ROOT, check=False
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def _fresh_factory() -> Iterator[sessionmaker]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    base.metadata.create_all(bind=engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        base.metadata.drop_all(bind=engine)
        engine.dispose()


def _patched_entry_points(
    monkeypatch: pytest.MonkeyPatch, keep: Callable[[EntryPoint], bool], extra: Sequence[EntryPoint] = ()
) -> None:
    def fake(*, group: str) -> EntryPoints:
        selected = [ep for ep in entry_points(group=group) if keep(ep)]
        return EntryPoints([*selected, *extra])

    monkeypatch.setattr("kohle.plugin.plugin_manager.entry_points", fake)


_SCRIPT: list[list[str]] = [
    ["add-account", "Depot", "--type", "asset"],
    ["add-account", "Cash", "--type", "asset"],
    ["add-account", "Broker", "--type", "asset"],
    ["add-account", "People", "--type", "asset"],
    ["add-unit", "EUR", "Euro", "--kind", "currency"],
    ["add-unit", "X1", "Thing", "--kind", "security"],
    ["add-unit", "DE0005190003", "BMW", "--kind", "security"],
    ["record", "2026-01-02", "buy", "10", "--from", "Cash", "--to", "Depot", "--to-unit", "X1", "--to-price", "5"],
    [
        "import-statement", "kohle-simple-broker", "Cash", "Broker",
        str(ROOT / "tests" / "fixtures" / "simple_broker.csv"),
    ],
    ["balance", "Depot"],
    ["balance", "Cash"],
    ["net-worth"],
    ["list-operations"],
    ["list-importer-plugins"],
    ["list-units"],
]


def _run_script() -> list[tuple[int, str]]:
    outputs = []
    for factory in _fresh_factory():
        runner = CliRunner()
        for args in _SCRIPT:
            result = runner.invoke(cli, args, obj=factory)
            outputs.append((result.exit_code, result.output))
    return outputs


def test_no_price_plugins_means_no_output_change(monkeypatch: pytest.MonkeyPatch) -> None:
    _patched_entry_points(monkeypatch, lambda ep: True)
    with_price_plugins = _run_script()

    _patched_entry_points(monkeypatch, lambda ep: ep.name not in PRICE_ENTRY_POINT_NAMES)
    without_price_plugins = _run_script()

    assert [code for code, _ in with_price_plugins] == [0] * len(_SCRIPT), with_price_plugins
    assert with_price_plugins == without_price_plugins


class ThirdPricePlugin(PriceFetcherPlugin):
    @property
    def name(self) -> str:
        return "third"

    def fetch_latest_closes(
        self, symbols: Sequence[str]
    ) -> Result[dict[str, PriceResult], PriceFetchError]:
        return Result.ok(
            {s: Close(price_date=date(2026, 3, 2), price=Decimal("42.5"), currency="EUR") for s in symbols}
        )


def test_third_plugin_binds_and_fetches_without_core_changes(
    monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker
) -> None:
    third = EntryPoint(name="third", value=f"{__name__}:ThirdPricePlugin", group="kohle.plugins")
    _patched_entry_points(monkeypatch, lambda ep: True, extra=[third])
    factory = session_factory
    runner = CliRunner()
    setup = [
        ["add-account", "Depot", "--type", "asset"],
        ["add-account", "Cash", "--type", "asset"],
        ["add-unit", "EUR", "Euro", "--kind", "currency"],
        ["add-unit", "X1", "Thing", "--kind", "security"],
        ["record", "2026-01-02", "buy", "10", "--from", "Cash", "--to", "Depot", "--to-unit", "X1", "--to-price", "5"],
    ]
    for args in setup:
        result = runner.invoke(cli, args, obj=factory)
        assert result.exit_code == 0, result.output

    bound = runner.invoke(cli, ["set-price-source", "X1", "third", "XYZ"], obj=factory)
    fetched = runner.invoke(cli, ["fetch-prices"], obj=factory)

    assert bound.exit_code == 0, bound.output
    assert fetched.exit_code == 0, fetched.output
    assert "third:XYZ" in fetched.output
    with factory() as session:
        (stored,) = session.scalars(select(Price))
        assert (stored.price, stored.price_date, stored.source) == (Decimal("42.5"), date(2026, 3, 2), "third")


def test_reports_leave_prices_and_operations_untouched(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    setup = [
        ["add-account", "Depot", "--type", "asset"],
        ["add-account", "Cash", "--type", "asset"],
        ["add-account", "People", "--type", "asset"],
        ["add-unit", "EUR", "Euro", "--kind", "currency"],
        ["add-unit", "X1", "Thing", "--kind", "security"],
        ["record", "2026-01-02", "buy", "10", "--from", "Cash", "--to", "Depot", "--to-unit", "X1", "--to-price", "5"],
    ]
    for args in setup:
        result = runner.invoke(cli, args, obj=session_factory)
        assert result.exit_code == 0, result.output
    with session_factory() as session:
        unit_id = session.scalars(select(Unit.id).where(Unit.identifier == "X1")).one()
        session.add(Price(unit_id=unit_id, price_date=date(2026, 1, 3), price=Decimal(6), source="file"))
        session.commit()

    def counts() -> tuple[int, int]:
        with session_factory() as session:
            return (
                session.scalar(select(func.count()).select_from(Price)) or 0,
                session.scalar(select(func.count()).select_from(Operation)) or 0,
            )

    before = counts()
    for args in (["balance", "Depot"], ["net-worth"]):
        result = runner.invoke(cli, args, obj=session_factory)
        assert result.exit_code == 0, result.output

    assert before[0] == 1
    assert counts() == before


def test_new_reports_leave_prices_operations_and_groups_untouched(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    setup = [
        ["add-account", "Depot", "--type", "asset"],
        ["add-account", "Cash", "--type", "asset"],
        ["add-account", "People", "--type", "asset"],
        ["add-unit", "EUR", "Euro", "--kind", "currency"],
        ["add-unit", "X1", "Thing", "--kind", "security"],
        ["record", "2026-01-02", "buy", "10", "--from", "Cash", "--to", "Depot", "--to-unit", "X1", "--to-price", "5"],
        ["record", "2026-01-03", "sell", "4", "--from", "Depot", "--to", "Cash", "--from-unit", "X1", "--from-price", "6"],
        ["set-setting", "state", "BY"],
    ]
    for args in setup:
        result = runner.invoke(cli, args, obj=session_factory)
        assert result.exit_code == 0, result.output
    with session_factory() as session:
        unit_id = session.scalars(select(Unit.id).where(Unit.identifier == "X1")).one()
        session.add(Price(unit_id=unit_id, price_date=date(2026, 1, 3), price=Decimal(6), source="file"))
        session.commit()

    def counts() -> tuple[int, int, int]:
        with session_factory() as session:
            return tuple(
                session.scalar(select(func.count()).select_from(model)) or 0
                for model in (Price, Operation, OperationGroup)
            )

    before = counts()
    for args in (["realised"], ["positions"], ["net-worth-history", "--from", "2026-01-02"]):
        result = runner.invoke(cli, args, obj=session_factory)
        assert result.exit_code == 0, result.output

    assert before[0] == 1
    assert counts() == before


PRICE_WRITER_IDENTIFIERS = {
    "load_price_plugins",
    "PriceFetcherPlugin",
    "call_price_plugins",
    "AppendPrices",
    "add_price_service",
}


def _report_sources() -> dict[str, str]:
    sources = {
        path: (ROOT / path).read_text(encoding="utf-8")
        for path in ("kohle/use_cases/reporting.py", "kohle/use_cases/lots.py")
    }
    for name in ("balance_cmd", "net_worth_cmd", "realised_cmd", "positions_cmd", "net_worth_history_cmd"):
        callback = getattr(cli_module, name).callback
        assert callback is not None
        sources[f"cli.{name}"] = inspect.getsource(callback)
    return sources


@pytest.mark.parametrize("site", list(_report_sources()))
def test_report_code_never_references_price_writers(site: str) -> None:
    assert _references(_report_sources()[site]) & PRICE_WRITER_IDENTIFIERS == set()
