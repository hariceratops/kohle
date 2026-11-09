"""Layer 3 — end-to-end INR scenario (issues 111-125)."""

from datetime import date
from decimal import Decimal

from click.testing import CliRunner

from kohle.app.cli.cli import cli
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.price_services import add_price_service, set_price_binding_service
from kohle.services.unit_services import get_unit_by_identifier_service

TODAY = date(2026, 6, 15)


def _run(session_factory, *args: str) -> str:
    result = CliRunner().invoke(cli, list(args), obj=session_factory)
    assert result.exit_code == 0, result.output
    return result.output


def _rows(output: str, first: int = 2) -> dict[str, list[str]]:
    return {line.split()[0]: line.split() for line in output.splitlines()[first:] if line.strip()}


def test_opening_remittance_purchase_sale_and_reconversion(session_factory, pin_today) -> None:
    pin_today(TODAY)
    for args in (
        ["add-account", "People", "--type", "asset"],
        ["add-account", "Checking", "--type", "asset"],
        ["add-account", "IndianBank", "--type", "asset"],
        ["add-account", "Demat", "--type", "asset"],
        ["add-account", "Opening", "--type", "income"],
        ["add-unit", "EUR", "Euro", "--kind", "currency"],
        ["add-unit", "INR", "Indian rupee", "--kind", "currency"],
        ["add-unit", "INFY", "Infosys", "--kind", "security"],
        ["record", "2026-01-01", "Opening", "5000", "--from", "Opening", "--to", "Checking"],
        # opening: 90,000 rupees already held, worth 1,000 euros
        ["record", "2026-01-01", "Opening", "90000", "--from", "Opening", "--to", "IndianBank", "--to-unit", "INR", "--total", "1000"],
        # remittance: a second lot at a different rate
        ["record", "2026-02-01", "Remittance", "100000", "--from", "Checking", "--to", "IndianBank", "--to-unit", "INR", "--total", "1100"],
        # purchase paid in rupees: costs the first lot's euros
        ["record", "2026-03-01", "Buy INFY", "50", "--from", "IndianBank", "--to", "Demat", "--to-unit", "INFY", "--to-price", "1500", "--currency", "INR"],
        # sale for rupees at a stated rate
        ["record", "2026-04-01", "Sell INFY", "20", "--from", "Demat", "--to", "IndianBank", "--from-unit", "INFY", "--from-price", "1600", "--currency", "INR", "--rate", "0.0105"],
        # reconversion: rupees back into euros
        ["record", "2026-05-01", "Back to euros", "20000", "--from", "IndianBank", "--to", "Checking", "--from-unit", "INR", "--total", "230"],
    ):
        _run(session_factory, *args)

    realised = _run(session_factory, "realised")
    rows = [line.split() for line in realised.splitlines()[2:] if line.startswith("2026")]
    by_unit = {row[2]: row for row in rows}
    # INFY: 20 of 50 shares at 1500 INR each, paid from the first lot (1000 EUR / 90000 INR)
    assert by_unit["INFY"][4:] == ["336.00", "333.33", "2.67"]
    # INR: 15000 from the first lot (166.67) and 5000 from the second (55.00)
    assert by_unit["INR"][4:] == ["230.00", "221.67", "8.33"]
    assert "Realised gain: 11.00" in realised

    with session_factory() as session:
        ctx = DbTransactionContext(session)
        infy = get_unit_by_identifier_service(ctx, "INFY").unwrap()
        inr = get_unit_by_identifier_service(ctx, "INR").unwrap()
        set_price_binding_service(ctx, infy.id, "file", "INFY", "INR").unwrap()
        add_price_service(ctx, infy.id, date(2026, 6, 12), Decimal(1700), "file", "INR").unwrap()
        add_price_service(ctx, inr.id, date(2026, 6, 12), Decimal("0.0106"), "file", "EUR").unwrap()
        session.commit()

    net_worth = _run(session_factory, "net-worth")
    worth_rows = {ln.split()[2]: ln.split() for ln in net_worth.splitlines() if ln.startswith("Own accounts")}
    # 30 INFY at 1700 INR and 127,000 INR (190,000 - 75,000 + 32,000 - 20,000), both at 0.0106 EUR
    assert worth_rows["INFY"][3] == "30.00"
    assert worth_rows["INR"][3] == "127000.00"
    assert "540.60" in worth_rows["INFY"] and "1346.20" in worth_rows["INR"]
    assert "Net worth (at market): 6016.80" in net_worth
    assert "Net worth (at cost): 6011.00" in net_worth
