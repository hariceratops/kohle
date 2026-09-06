import sys
from decimal import Decimal, InvalidOperation

import click
from tabulate import tabulate

from kohle.db.connection import session_local
from kohle.domain.models import AccountType, UnitKind
from kohle.plugin.plugin_manager import load_plugins
from kohle.use_cases.accounts import AddAccount, ListAccount, ListChildAccounts
from kohle.use_cases.journal import (
    BASE_CURRENCY,
    CrossUnitLine,
    ImportStatement,
    LineInput,
    QueryAccountBalance,
    QueryJournalByPeriod,
    RecordSimpleEntry,
    RecordSplitEntry,
)
from kohle.use_cases.units import AddUnit, ListUnits


class DecimalParamType(click.ParamType):
    name = "decimal"

    def convert(self, value, param, ctx):
        try:
            return Decimal(value)
        except InvalidOperation:
            self.fail(f"{value!r} is not a valid decimal", param, ctx)


DECIMAL = DecimalParamType()


def _parse_line(raw: str) -> LineInput:
    fields = raw.split(":")
    if len(fields) != 5:
        raise click.BadParameter(f"{raw!r} does not split into ACCOUNT:QUANTITY:UNIT:PRICE:SIDE")
    account_name, quantity_str, unit_identifier, price_str, side = fields

    try:
        quantity = Decimal(quantity_str)
    except InvalidOperation:
        raise click.BadParameter(f"{raw!r}: {quantity_str!r} is not a valid decimal quantity") from None

    try:
        unit_price = Decimal(price_str)
    except InvalidOperation:
        raise click.BadParameter(f"{raw!r}: {price_str!r} is not a valid decimal price") from None

    if side not in ("debit", "credit"):
        raise click.BadParameter(f"{raw!r}: {side!r} must be 'debit' or 'credit'")

    return LineInput(account_name, quantity, unit_identifier, unit_price, is_debit=side == "debit")


def _parse_lines(ctx, param, values: tuple[str, ...]) -> list[LineInput]:
    return [_parse_line(value) for value in values]


@click.group()
@click.pass_context
def cli(ctx):
    ctx.obj = ctx.obj or session_local


@cli.command()
@click.argument("name")
@click.option("--type", "account_type", type=click.Choice([t.name for t in AccountType]), default="expense")
@click.option("--iban", default=None)
@click.option("--parent", default=None, help="Name of the parent account, for virtual sub-accounts")
@click.pass_obj
def add_account_cmd(make_session, name: str, account_type: str, iban: str | None, parent: str | None):
    add_account = AddAccount(make_session())
    res = add_account.execute(name, AccountType[account_type], iban, parent)
    if res.is_ok:
        click.echo(f"Added account {name} ({account_type}) with id {res.unwrap().id}")
    else:
        click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
@click.pass_obj
def list_accounts_cmd(make_session):
    list_accounts = ListAccount(make_session())
    res = list_accounts.execute()
    if res.is_ok:
        for a in res.unwrap():
            parent = f", parent={a.parent_id}" if a.parent_id else ""
            click.echo(f"{a.id}: name={a.name}, type={a.type.name}, iban={a.iban or '-'}{parent}")
    else:
        click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
@click.argument("parent_name")
@click.pass_obj
def list_child_accounts_cmd(make_session, parent_name: str):
    list_children = ListChildAccounts(make_session())
    res = list_children.execute(parent_name)
    if res.is_ok:
        for a in res.unwrap():
            click.echo(f"{a.id}: name={a.name}, type={a.type.name}")
    else:
        click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
@click.argument("identifier")
@click.argument("name")
@click.option("--kind", type=click.Choice([k.name for k in UnitKind]), default="security")
@click.pass_obj
def add_unit_cmd(make_session, identifier: str, name: str, kind: str):
    add_unit = AddUnit(make_session())
    res = add_unit.execute(identifier, name, UnitKind[kind])
    if res.is_ok:
        click.echo(f"Added unit {identifier} ({kind}) with id {res.unwrap().id}")
    else:
        click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
@click.pass_obj
def list_units_cmd(make_session):
    list_units = ListUnits(make_session())
    res = list_units.execute()
    if res.is_ok:
        for u in res.unwrap():
            click.echo(f"{u.id}: {u.identifier} ({u.kind.name}) {u.name}")
    else:
        click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
def list_importer_plugins():
    plugins = load_plugins()

    if not plugins:
        click.echo("No plugins found")
        return
    for name in plugins:
        click.echo(name)


@cli.command()
@click.argument("plugin_name", required=True)
@click.argument('account_name')
@click.argument('csv_file', type=click.Path(exists=True))
@click.pass_obj
def import_statement(make_session, plugin_name: str, account_name: str, csv_file):
    plugins = load_plugins()
    if plugin_name not in plugins:
        click.echo("Plugin not found")
        sys.exit(1)

    plugin = plugins[plugin_name]
    statement_res = plugin.import_statement(csv_file)
    if statement_res.is_err:
        click.echo(f"Statement processing failed, reason = {statement_res.unwrap_err()}")
        sys.exit(1)

    df = statement_res.unwrap()
    import_use_case = ImportStatement(make_session())
    res = import_use_case.execute(account_name, df)
    if res.is_ok:
        click.echo(f"Import succeded, {res.unwrap()} entries imported")
    else:
        click.echo(f"Import failed, reason = {res.unwrap_err()}")


@cli.command()
@click.argument("entry_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.argument("description")
@click.argument("quantity", type=DECIMAL)
@click.option("--from", "from_account", required=True, help="Account to credit")
@click.option("--to", "to_account", required=True, help="Account to debit")
@click.option("--from-unit", default=None, help="Non-base unit carried by the credit side")
@click.option("--from-price", type=DECIMAL, default=None, help="Price of --from-unit")
@click.option("--to-unit", default=None, help="Non-base unit carried by the debit side")
@click.option("--to-price", type=DECIMAL, default=None, help="Price of --to-unit")
@click.pass_obj
def record_cmd(
    make_session,
    entry_date,
    description: str,
    quantity: Decimal,
    from_account: str,
    to_account: str,
    from_unit: str | None,
    from_price: Decimal | None,
    to_unit: str | None,
    to_price: Decimal | None,
):
    if from_unit and to_unit:
        raise click.BadParameter("only one of --from-unit / --to-unit may be given")
    if from_price is not None and from_unit is None:
        raise click.BadParameter("--from-price requires --from-unit")
    if to_price is not None and to_unit is None:
        raise click.BadParameter("--to-price requires --to-unit")

    cross = None
    if from_unit is not None:
        cross = CrossUnitLine(from_unit, from_price if from_price is not None else Decimal(1), is_debit=False)
    elif to_unit is not None:
        cross = CrossUnitLine(to_unit, to_price if to_price is not None else Decimal(1), is_debit=True)

    record = RecordSimpleEntry(make_session())
    res = record.execute(entry_date.date(), description, quantity, from_account, to_account, cross)
    if res.is_ok:
        if cross is None:
            click.echo(f"Recorded {quantity} {BASE_CURRENCY}: credited {from_account}, debited {to_account}")
        else:
            click.echo(
                f"Recorded {quantity} {cross.identifier} @ {cross.price}: "
                f"credited {from_account}, debited {to_account}"
            )
    else:
        click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
@click.argument("entry_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.argument("description")
@click.option(
    "--line",
    "lines",
    multiple=True,
    callback=_parse_lines,
    help="ACCOUNT:QUANTITY:UNIT:PRICE:SIDE, repeatable, one per journal line; SIDE is debit or credit",
)
@click.pass_obj
def record_split_cmd(make_session, entry_date, description: str, lines: list[LineInput]):
    record = RecordSplitEntry(make_session())
    res = record.execute(entry_date.date(), description, lines)
    if res.is_ok:
        entry = res.unwrap()
        click.echo(f"Recorded entry with {len(entry.lines)} lines")
    else:
        click.echo(f"Failed: {res.unwrap_err()}")


@cli.command()
@click.argument('account_name')
@click.argument("start")
@click.argument("end")
@click.pass_obj
def entries_in_period(make_session, account_name, start, end):
    query = QueryJournalByPeriod(make_session())
    res = query.execute(account_name, start, end)
    if res.is_ok:
        rows = [
            {
                "date": line.entry.entry_date,
                "description": line.entry.description,
                "side": "dr" if line.is_debit else "cr",
                "quantity": line.quantity,
                "unit": line.unit.identifier,
                "value": line.value,
            }
            for line in res.unwrap()
        ]
        click.echo(tabulate(rows, headers="keys", floatfmt=".2f"))
    else:
        click.echo(f"Querying for the period failed {res.unwrap_err()}")


@cli.command()
@click.argument("account_name")
@click.pass_obj
def balance_cmd(make_session, account_name: str):
    query = QueryAccountBalance(make_session())
    res = query.execute(account_name)
    if res.is_ok:
        balances = res.unwrap()
        if not balances:
            click.echo("No holdings")
            return
        rows = [
            {
                "unit": b.unit_identifier,
                "quantity": b.quantity,
                "average cost": b.average_cost,
            }
            for b in balances
        ]
        if len(balances) == 1 and balances[0].unit_identifier == BASE_CURRENCY:
            rows.append({
                "unit": "Total (base currency)",
                "quantity": balances[0].quantity,
                "average cost": None,
            })
        # missingval renders None as "-" without putting a str into the
        # column: a str in an otherwise-Decimal column makes tabulate treat
        # the whole column as non-numeric, silently disabling floatfmt for
        # every other row in it (not just the one with the missing value).
        click.echo(tabulate(rows, headers="keys", floatfmt=".2f", missingval="-"))
    else:
        click.echo(f"Failed: {res.unwrap_err()}")


if __name__ == "__main__":
    cli()
