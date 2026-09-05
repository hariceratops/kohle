import sys

import click
from tabulate import tabulate

from kohle.db.connection import session_local
from kohle.domain.models import AccountType, UnitKind
from kohle.plugin.plugin_manager import load_plugins
from kohle.use_cases.accounts import AddAccount, ListAccount, ListChildAccounts
from kohle.use_cases.journal import ImportStatement, QueryJournalByPeriod
from kohle.use_cases.units import AddUnit, ListUnits


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


if __name__ == "__main__":
    cli()
