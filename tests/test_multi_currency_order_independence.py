"""Layer 3 — order independence (issue 118). Design §14."""

from click.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kohle.app.cli.cli import cli
from kohle.db.connection import base

_SETUP = (
    ["add-account", "People", "--type", "asset"],
    ["add-account", "Girokonto", "--type", "asset"],
    ["add-account", "IndianBank", "--type", "asset"],
    ["add-account", "Demat", "--type", "asset"],
    ["add-account", "Dividends", "--type", "income"],
    ["add-unit", "INR", "Indian rupee", "--kind", "currency"],
    ["add-unit", "INFY", "Infosys", "--kind", "security"],
)

_REMITTANCE_1 = ["record", "2026-03-05", "Remittance", "90000", "--from", "Girokonto", "--to", "IndianBank", "--to-unit", "INR", "--total", "1000"]
_REMITTANCE_2 = ["record", "2026-03-06", "Remittance", "100000", "--from", "Girokonto", "--to", "IndianBank", "--to-unit", "INR", "--total", "1100"]
_PURCHASE = ["record", "2026-03-10", "Buy INFY", "100", "--from", "IndianBank", "--to", "Demat", "--to-unit", "INFY", "--to-price", "1200", "--currency", "INR"]
_RATED_INFLOW = ["record", "2026-03-12", "Dividend", "2000", "--from", "Dividends", "--to", "IndianBank", "--currency", "INR", "--rate", "0.0104"]
_RECONVERSION = ["record", "2026-03-20", "Back to euros", "70000", "--from", "IndianBank", "--to", "Girokonto", "--from-unit", "INR", "--total", "800"]
_COMMANDS = (
    ["positions"],
    ["realised"],
    ["balance", "IndianBank"],
    ["balance", "Demat"],
    ["balance", "Girokonto"],
    ["net-worth"],
)


def _run(session_factory, *args: str) -> str:
    result = CliRunner().invoke(cli, list(args), obj=session_factory)
    assert result.exit_code == 0, (args, result.output)
    return result.output


def _reports(session_factory, entries: list[list[str]]) -> list[str]:
    for args in (*_SETUP, *entries):
        _run(session_factory, *args)
    return [_run(session_factory, *command) for command in _COMMANDS]


def test_two_insertion_orders_give_identical_reports(session_factory) -> None:
    in_date_order = _reports(session_factory, [_REMITTANCE_1, _REMITTANCE_2, _PURCHASE, _RATED_INFLOW, _RECONVERSION])
    assert all("INR" in output for output in in_date_order[:3])

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    base.metadata.create_all(bind=engine)
    other = sessionmaker(bind=engine, expire_on_commit=False)
    # The first remittance and the purchase arrive after later entries: both are backdated.
    shuffled = _reports(other, [_REMITTANCE_2, _RECONVERSION, _RATED_INFLOW, _PURCHASE, _REMITTANCE_1])

    assert shuffled == in_date_order
